"""
Ultron Hybrid Vector Store Engine
Enforces standard SQLite BLOB persistence and runs high-speed local NumPy Cosine Similarity math.
Bypasses local transformers footprint, fully complying with 8GB RAM host limitations.
"""

import hashlib
import json
import uuid
import yaml
import sqlite3
from typing import List, Dict, Any, Optional
from backend.app.database.db import get_db_connection
from backend.app.brain.api_key_manager import APIKeyManager
from backend.app.brain.model_config import get_model, get_embedding_dimensions
from backend.app.install_paths import CONFIG_PATH

# Lazy-load numpy only when needed (cosine math / embeddings), so the heavy
# NumPy dependency is NOT pulled into memory at backend boot time. This keeps
# startup light on 8GB / dual-core hosts while preserving all functionality.
_np = None

def _lazy_numpy():
    """Import numpy lazily on first use and cache the module reference."""
    global _np
    if _np is None:
        import numpy
        _np = numpy
    return _np

# ---------------------------------------------------------------------------
# V2 Step E: Jarvis memory keeps what matters forever and stays light.
# ---------------------------------------------------------------------------
# Facts the owner told Ultron (and important ones) are NEVER auto-deleted.
KEEP_CATEGORIES = ("explicit", "owner_preference", "decision", "goal")
KEEP_IMPORTANCE = ("high", "critical")
OFFLINE_EMBEDDING = "offline-hash"
_MEM_VERSION = [0]  # bumped on every write so cached views (core profile) refresh


def _json_field(field: str) -> str:
    return f"(CASE WHEN json_valid(metadata) THEN json_extract(metadata, '$.{field}') END)"


# SQL that is true for rows that must be kept forever.
KEEP_SQL = (
    f"({_json_field('kind')} = 'explicit_remember' OR {_json_field('source')} = 'user' OR "
    f"{_json_field('importance')} IN ('high', 'critical') OR "
    f"{_json_field('category')} IN ('explicit', 'owner_preference', 'decision', 'goal'))"
)


def is_kept_forever(metadata: Optional[Dict[str, Any]]) -> bool:
    meta = metadata or {}
    return bool(
        meta.get("kind") == "explicit_remember"
        or meta.get("source") == "user"
        or meta.get("importance") in KEEP_IMPORTANCE
        or meta.get("category") in KEEP_CATEGORIES
    )


def memory_version() -> int:
    return _MEM_VERSION[0]


def _bump_version() -> None:
    _MEM_VERSION[0] += 1


def _memory_setting(name: str, default: int, low: int, high: int) -> int:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            value = (yaml.safe_load(f) or {}).get("memory", {}).get(name, default)
        return max(low, min(int(value), high))
    except Exception:
        return default


class VectorStore:
    def __init__(self, key_manager: Optional[APIKeyManager] = None) -> None:
        self.key_manager = key_manager or APIKeyManager()
        self.duplicate_threshold = self._load_threshold_from_config()
        self._writes_since_prune = 0
        self.prune_interval = 100  # Run retention check every N writes (keeps writes cheap)
        self._embedding_cache: Dict[str, List[float]] = {}
        self._embedding_cache_limit = 256
        self._initialize_table()

    def _load_threshold_from_config(self) -> float:
        """Loads similarity deduplication threshold from config.yaml safely."""
        if not CONFIG_PATH.exists():
            return 0.95
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config.get("memory", {}).get("duplicate_similarity_threshold", 0.95)
        except Exception:
            return 0.95

    def _initialize_table(self) -> None:
        """Initializes the self-contained vector_memories table."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vector_memories (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,         -- episodic | semantic | emotional
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,     -- NumPy float32 array serialized
                    metadata TEXT DEFAULT '{}',  -- JSON formatted meta variables
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

    @staticmethod
    def _deterministic_offline_embedding(text: str, dims: int) -> List[float]:
        """Stable labelled-offline vector without Python hash or global RNG state."""
        np = _lazy_numpy()
        raw = hashlib.shake_256(text.encode("utf-8")).digest(dims * 4)
        integers = np.frombuffer(raw, dtype=np.uint32).astype(np.float64)
        vector = (integers / float(2**32 - 1)) * 2.0 - 1.0
        norm = np.linalg.norm(vector)
        if norm:
            vector = vector / norm
        return vector.astype(np.float32).tolist()

    async def embed(self, text: str) -> tuple:
        """(vector, model name). Never raises: when the embedding service is down or
        out of quota the memory is still saved with a labelled offline vector (and
        is always findable by its words); `reembed` upgrades it later."""
        try:
            vector = await self.generate_embedding(text)
            model = get_model("embedding") if self.key_manager.has_real_key("gemini") else OFFLINE_EMBEDDING
            return vector, model
        except Exception as exc:
            print(f"[VECTOR_STORE] Embedding unavailable, saving with an offline vector: {exc}")
            return self._deterministic_offline_embedding(text.strip(), get_embedding_dimensions()), OFFLINE_EMBEDDING

    async def generate_embedding(self, text: str) -> List[float]:
        """Return a config-driven Gemini embedding or a deterministic offline vector."""
        normalized = text.strip()
        model = get_model("embedding")
        dims = get_embedding_dimensions()
        cache_key = f"{model}|{dims}|{normalized}"
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        if not self.key_manager.has_real_key("gemini"):
            vector = self._deterministic_offline_embedding(normalized, dims)
            self._cache_embedding(cache_key, vector)
            return vector

        import httpx

        url_template = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={key}"
        payload = {
            "model": f"models/{model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": dims,
        }
        last_error = None
        for _attempt in range(3):
            api_key = self.key_manager.get_active_key("gemini")
            payload["model"] = f"models/{model}"
            url = url_template.format(model=model, key=api_key)
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        url,
                        headers={"Content-Type": "application/json"},
                        json=payload,
                    )
            except httpx.RequestError as exc:
                last_error = exc
                self.key_manager.mark_key_cooling("gemini", api_key, duration_sec=30)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                self.key_manager.mark_key_cooling("gemini", api_key, duration_sec=30)
                last_error = RuntimeError(f"Embedding API temporary HTTP {response.status_code}")
                continue
            if response.status_code in (401, 403):
                self.key_manager.mark_key_failed("gemini", api_key)
                last_error = RuntimeError(f"Embedding API authentication HTTP {response.status_code}")
                continue
            if response.status_code != 200:
                # V2 Step E2: Google retired the embedding model -> next one (or ask
                # Google which embedding models exist today, at most once a day).
                from backend.app.brain import model_fallback
                from backend.app.brain.model_config import retire_model

                if model_fallback.is_model_gone_error(response.status_code, response.text or ""):
                    next_model = retire_model("embedding", model)
                    if not next_model:
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            next_model = await model_fallback.discover("embedding", client, api_key)
                    if next_model and next_model != model:
                        model = next_model
                        last_error = RuntimeError("embedding model retired; switched")
                        continue
                raise RuntimeError(f"Embedding API rejected request with HTTP {response.status_code}")

            try:
                vector = response.json()["embedding"]["values"]
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("Embedding API returned an invalid response schema") from exc
            if len(vector) != dims:
                raise RuntimeError(
                    f"Embedding API returned {len(vector)} dimensions; expected {dims}"
                )
            self._cache_embedding(f"{model}|{dims}|{normalized}", vector)
            return vector

        raise RuntimeError(f"Gemini embedding provider unavailable: {last_error}")

    async def remember(
        self,
        mem_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        return_status: bool = False,
    ):
        """Save one memory. Never lost to an embedding outage (offline vector +
        needs_reembed). Returns True/False, or "saved"/"duplicate"/"failed"."""
        try:
            embedding, model_name = await self.embed(content)
            meta = dict(metadata or {})
            meta["embedding_model"] = model_name
            if model_name == OFFLINE_EMBEDDING and self.key_manager.has_real_key("gemini"):
                meta["needs_reembed"] = True
            status = self.save_vector_memory(
                msg_id=str(uuid.uuid4()), mem_type=mem_type, content=content,
                embedding=embedding, metadata=meta, return_status=True,
            )
        except Exception as exc:
            print(f"[VECTOR_STORE] Warning: failed to save {mem_type} memory: {exc}")
            status = "failed"
        return status if return_status else status == "saved"

    async def recall(
        self, mem_type: str, query: str, limit: int = 3, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Similar memories of one type inside a project (never raises)."""
        try:
            query_emb, model_name = await self.embed(query)
            metadata_filter = {"project_id": project_id} if project_id else None
            return self.search_similarity(
                mem_type, query_emb, limit=limit, metadata_filter=metadata_filter,
                embedding_model=model_name,
            )
        except Exception as exc:
            print(f"[VECTOR_STORE] Warning: {mem_type} recall failed: {exc}")
            return []

    def _cache_embedding(self, key: str, vec: List[float]) -> None:
        """Bounded in-memory embedding cache (token saver)."""
        self._embedding_cache[key] = vec
        if len(self._embedding_cache) > self._embedding_cache_limit:
            # Drop the oldest entry (dicts preserve insertion order).
            self._embedding_cache.pop(next(iter(self._embedding_cache)))

    def save_vector_memory(
        self,
        msg_id: str,
        mem_type: str,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
        return_status: bool = False,
    ):
        """
        Saves a serialized vector memory row. Implements duplicate checks:
        if a high similarity exceeds config-defined threshold, halts writing.
        return_status=True returns "saved" / "duplicate" instead of True/False.
        """
        # Convert list to high-performance NumPy float32 array
        np = _lazy_numpy()
        new_vec = np.array(embedding, dtype=np.float32)
        
        # 1. Run duplicate verification inside the same project scope.
        duplicate_filter = None
        if metadata and metadata.get("project_id"):
            duplicate_filter = {"project_id": metadata["project_id"]}
        existing_matches = self.search_similarity(
            mem_type, embedding, limit=1, metadata_filter=duplicate_filter,
            embedding_model=(metadata or {}).get("embedding_model"),
        )
        if existing_matches:
            top_similarity = existing_matches[0]["similarity"]
            if top_similarity > self.duplicate_threshold:
                print(f"[VECTOR_STORE] Duplicate write aborted. Similarity ({top_similarity:.3f}) exceeds threshold ({self.duplicate_threshold}).")
                return "duplicate" if return_status else False

        # 2. Serialize vector array to raw binary BLOB
        vec_blob = new_vec.tobytes()
        enriched_metadata = dict(metadata or {})
        enriched_metadata.setdefault("embedding_model", get_model("embedding"))
        enriched_metadata.setdefault("embedding_dimensions", len(embedding))
        metadata_str = json.dumps(enriched_metadata)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO vector_memories (id, type, content, embedding, metadata)
                VALUES (?, ?, ?, ?, ?);
                """,
                (msg_id, mem_type, content, sqlite3.Binary(vec_blob), metadata_str)
            )
            from backend.app.memory.recall_index import index_vector_memory
            index_vector_memory(
                conn,
                memory_id=msg_id,
                mem_type=mem_type,
                content=content,
                metadata=enriched_metadata,
            )
            conn.commit()
            _bump_version()

            # Opportunistic storage-retention guard (bounds long-term growth).
            self._writes_since_prune += 1
            if self._writes_since_prune >= self.prune_interval:
                self._writes_since_prune = 0
                try:
                    self.prune()
                except Exception as e:
                    print(f"[VECTOR_STORE] Warning: retention prune failed: {e}")

            return "saved" if return_status else True

    def search_similarity(
        self,
        mem_type: str,
        query_embedding: List[float],
        limit: int = 5,
        metadata_filter: Optional[Dict[str, Any]] = None,
        embedding_model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Cosine top matches over a BOUNDED slice: every kept-forever fact plus the
        newest `vector_scan_limit` automatic memories. Years of memories never load
        into RAM at once; older chats stay findable through the word index (FTS).
        Vectors from another embedding model (or offline ones) are not compared."""
        np = _lazy_numpy()
        target_vec = np.array(query_embedding, dtype=np.float32)
        target_norm = float(np.linalg.norm(target_vec))
        if target_norm == 0:
            return []
        scan_limit = _memory_setting("vector_scan_limit", 6000, 200, 50000)
        kept_limit = _memory_setting("kept_scan_limit", 5000, 100, 50000)

        with get_db_connection() as conn:
            newest = conn.execute(
                "SELECT id, content, embedding, metadata, created_at FROM vector_memories "
                "WHERE type = ? ORDER BY rowid DESC LIMIT ?;",
                (mem_type, scan_limit),
            ).fetchall()
            kept = conn.execute(
                "SELECT id, content, embedding, metadata, created_at FROM vector_memories "
                f"WHERE type = ? AND {KEEP_SQL} ORDER BY rowid DESC LIMIT ?;",
                (mem_type, kept_limit),
            ).fetchall()

        seen: set = set()
        candidates = []
        vectors = []
        for row in list(newest) + list(kept):
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            try:
                row_metadata = json.loads(row["metadata"] or "{}")
            except (json.JSONDecodeError, TypeError):
                row_metadata = {}
            if not isinstance(row_metadata, dict):
                row_metadata = {}
            if metadata_filter and any(
                row_metadata.get(key, "personal" if key == "project_id" else None) != value
                for key, value in metadata_filter.items()
            ):
                continue
            if embedding_model:
                stored_model = row_metadata.get("embedding_model")
                # offline vectors only match offline vectors (and real only real)
                if (stored_model == OFFLINE_EMBEDDING) != (embedding_model == OFFLINE_EMBEDDING):
                    continue
            db_vec = np.frombuffer(row["embedding"], dtype=np.float32)
            if db_vec.shape != target_vec.shape:
                continue  # old model size: re-embed to migrate
            candidates.append((row, row_metadata))
            vectors.append(db_vec)

        if not vectors:
            return []
        matrix = np.vstack(vectors)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = np.inf
        scores = (matrix @ target_vec) / (norms * target_norm)
        order = np.argsort(-scores)[: max(1, int(limit))]
        return [
            {
                "id": candidates[i][0]["id"],
                "content": candidates[i][0]["content"],
                "similarity": float(scores[i]),
                "metadata": candidates[i][1],
                "created_at": candidates[i][0]["created_at"],
            }
            for i in order
            if np.isfinite(scores[i]) and scores[i] != 0
        ]

    async def update_vector_memory(
        self,
        msg_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Re-embed and replace one memory while preserving its id/type."""
        existing = self.get_memory(msg_id)
        if not existing:
            return False
        embedding, model_name = await self.embed(content)
        updated_metadata = dict(existing.get("metadata") or {})
        updated_metadata.update(metadata or {})
        updated_metadata["embedding_model"] = model_name
        updated_metadata["embedding_dimensions"] = len(embedding)
        updated_metadata.pop("needs_reembed", None)
        if model_name == OFFLINE_EMBEDDING:
            updated_metadata["needs_reembed"] = True
        np = _lazy_numpy()
        blob = np.array(embedding, dtype=np.float32).tobytes()
        with get_db_connection() as conn:
            cursor = conn.execute(
                "UPDATE vector_memories SET content = ?, embedding = ?, metadata = ? WHERE id = ?;",
                (content, sqlite3.Binary(blob), json.dumps(updated_metadata), msg_id),
            )
            if cursor.rowcount > 0:
                from backend.app.memory.recall_index import index_vector_memory
                index_vector_memory(
                    conn,
                    memory_id=msg_id,
                    mem_type=str(existing.get("type") or "episodic"),
                    content=content,
                    metadata=updated_metadata,
                    created_at=str(existing.get("created_at") or ""),
                )
            conn.commit()
            _bump_version()
            return cursor.rowcount > 0

    async def reembed_project(self, project_id: str, limit: int = 500) -> Dict[str, int]:
        """Migrate legacy/current project vectors to the configured model/dimensions."""
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, content, metadata FROM vector_memories ORDER BY rowid ASC;"
            ).fetchall()
        migrated = 0
        skipped = 0
        for row in rows:
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except (json.JSONDecodeError, TypeError):
                metadata = {}
            if metadata.get("project_id", "personal") != project_id:
                continue
            if migrated >= limit:
                skipped += 1
                continue
            if await self.update_vector_memory(row["id"], row["content"], metadata):
                migrated += 1
        return {"migrated": migrated, "skipped": skipped}

    def delete_vector_memory(self, msg_id: str) -> bool:
        """Delete a specific vector memory row by id (used by memory forget)."""
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM vector_memories WHERE id = ?;", (msg_id,))
                if cur.rowcount > 0:
                    from backend.app.memory.recall_index import delete_recall_document
                    delete_recall_document(conn, f"memory:{msg_id}")
                conn.commit()
                _bump_version()
                return cur.rowcount > 0
        except sqlite3.Error as e:
            print(f"[VECTOR_STORE] Delete failed: {e}")
            return False

    def get_memory(self, msg_id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, type, content, metadata, created_at FROM vector_memories WHERE id = ?;",
                (msg_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["metadata"] = json.loads(item["metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            item["metadata"] = {}
        return item

    def list_recent_memories(
        self,
        limit: int = 20,
        mem_type: Optional[str] = None,
        project_id: Optional[str] = None,
        kept_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Newest rows (filtered in SQL, so years of memory never load at once)."""
        where, params = [], []
        if mem_type:
            where.append("type = ?")
            params.append(mem_type)
        if project_id:
            where.append(f"COALESCE({_json_field('project_id')}, 'personal') = ?")
            params.append(project_id)
        if kept_only:
            where.append(KEEP_SQL)
        sql = "SELECT id, type, content, metadata, created_at FROM vector_memories"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY rowid DESC LIMIT ?;"
        params.append(max(1, int(limit)))
        with get_db_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            try:
                metadata = json.loads(item.pop("metadata") or "{}")
            except (json.JSONDecodeError, TypeError):
                metadata = {}
            item["metadata"] = metadata if isinstance(metadata, dict) else {}
            results.append(item)
        return results

    def prune(self, max_per_type: Optional[int] = None) -> int:
        """Bound AUTOMATIC memories only (newest `max_auto_memories` per type, default
        20,000 = years of use). Facts the owner told Ultron and important ones are
        never deleted. Deleted rows leave the word index directly (no full rebuild)."""
        cap = int(max_per_type) if max_per_type is not None else _memory_setting(
            "max_auto_memories", 20000, 500, 500000
        )
        removed = 0
        with get_db_connection() as conn:
            types = [row["type"] for row in conn.execute("SELECT DISTINCT type FROM vector_memories;")]
            from backend.app.memory.recall_index import delete_recall_document
            for mem_type in types:
                old_ids = [
                    row["id"]
                    for row in conn.execute(
                        f"SELECT id FROM vector_memories WHERE type = ? AND NOT {KEEP_SQL} "
                        "ORDER BY rowid DESC LIMIT -1 OFFSET ?;",
                        (mem_type, cap),
                    )
                ]
                for start_at in range(0, len(old_ids), 500):
                    chunk = old_ids[start_at:start_at + 500]
                    marks = ",".join("?" for _ in chunk)
                    conn.execute(f"DELETE FROM vector_memories WHERE id IN ({marks});", chunk)
                    for memory_id in chunk:
                        delete_recall_document(conn, f"memory:{memory_id}")
                removed += len(old_ids)
            conn.commit()
        if removed:
            _bump_version()
            print(f"[VECTOR_STORE] Storage retention: pruned {removed} old automatic memories "
                  f"(kept facts are never pruned; cap {cap}/type).")
        return removed
