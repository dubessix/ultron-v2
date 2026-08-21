"""
Ultron Hybrid Vector Store Engine
Enforces standard SQLite BLOB persistence and runs high-speed local NumPy Cosine Similarity math.
Bypasses local transformers footprint, fully complying with 8GB RAM host limitations.
"""

import hashlib
import json
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
        for _attempt in range(2):
            api_key = self.key_manager.get_active_key("gemini")
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
                raise RuntimeError(f"Embedding API rejected request with HTTP {response.status_code}")

            try:
                vector = response.json()["embedding"]["values"]
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("Embedding API returned an invalid response schema") from exc
            if len(vector) != dims:
                raise RuntimeError(
                    f"Embedding API returned {len(vector)} dimensions; expected {dims}"
                )
            self._cache_embedding(cache_key, vector)
            return vector

        raise RuntimeError(f"Gemini embedding provider unavailable: {last_error}")

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
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Saves a serialized vector memory row. Implements duplicate checks:
        if a high similarity exceeds config-defined threshold, halts writing.
        """
        # Convert list to high-performance NumPy float32 array
        np = _lazy_numpy()
        new_vec = np.array(embedding, dtype=np.float32)
        
        # 1. Run duplicate verification inside the same project scope.
        duplicate_filter = None
        if metadata and metadata.get("project_id"):
            duplicate_filter = {"project_id": metadata["project_id"]}
        existing_matches = self.search_similarity(
            mem_type, embedding, limit=1, metadata_filter=duplicate_filter
        )
        if existing_matches:
            top_similarity = existing_matches[0]["similarity"]
            if top_similarity > self.duplicate_threshold:
                print(f"[VECTOR_STORE] Duplicate write aborted. Similarity ({top_similarity:.3f}) exceeds threshold ({self.duplicate_threshold}).")
                return False

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
            conn.commit()

            # Opportunistic storage-retention guard (bounds long-term growth).
            self._writes_since_prune += 1
            if self._writes_since_prune >= self.prune_interval:
                self._writes_since_prune = 0
                try:
                    self.prune()
                except Exception as e:
                    print(f"[VECTOR_STORE] Warning: retention prune failed: {e}")

            return True

    def search_similarity(
        self,
        mem_type: str,
        query_embedding: List[float],
        limit: int = 5,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Loads all matching type vector binaries from SQLite, deserializes them to NumPy arrays,
        computes local Cosine Similarities, and returns sorted top matches.
        """
        np = _lazy_numpy()
        target_vec = np.array(query_embedding, dtype=np.float32)
        target_norm = np.linalg.norm(target_vec)
        
        if target_norm == 0:
            return []

        matches = []
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, content, embedding, metadata, created_at FROM vector_memories WHERE type = ?;",
                (mem_type,)
            )
            rows = cursor.fetchall()

            for row in rows:
                try:
                    row_metadata = json.loads(row["metadata"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    row_metadata = {}
                if metadata_filter:
                    mismatch = False
                    for key, value in metadata_filter.items():
                        actual = row_metadata.get(key, "personal" if key == "project_id" else None)
                        if actual != value:
                            mismatch = True
                            break
                    if mismatch:
                        continue
                # Load binary BLOB back to NumPy float32 array
                db_vec = np.frombuffer(row["embedding"], dtype=np.float32)
                db_norm = np.linalg.norm(db_vec)
                
                if db_norm == 0:
                    continue

                # Robustness: if a stored vector's dimensionality differs from the
                # current embedding (e.g. a legacy model change), skip it instead of
                # crashing the whole recall with a dimension mismatch. These rows can
                # be re-embedded / pruned later.
                if db_vec.shape != target_vec.shape:
                    print(f"[VECTOR_STORE] Skipping memory {row['id']}: dimension mismatch "
                          f"({db_vec.shape[0]} != {target_vec.shape[0]}). Re-embed to migrate.")
                    continue

                # Execute Cosine Similarity equation: dot(A, B) / (norm(A) * norm(B))
                similarity = float(np.dot(target_vec, db_vec) / (target_norm * db_norm))
                
                matches.append({
                    "id": row["id"],
                    "content": row["content"],
                    "similarity": similarity,
                    "metadata": row_metadata,
                    "created_at": row["created_at"]
                })

        # Sort matches chronologically by similarity descending
        matches.sort(key=lambda x: x["similarity"], reverse=True)
        return matches[:limit]

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
        embedding = await self.generate_embedding(content)
        updated_metadata = dict(existing.get("metadata") or {})
        updated_metadata.update(metadata or {})
        updated_metadata["embedding_model"] = get_model("embedding")
        updated_metadata["embedding_dimensions"] = len(embedding)
        np = _lazy_numpy()
        blob = np.array(embedding, dtype=np.float32).tobytes()
        with get_db_connection() as conn:
            cursor = conn.execute(
                "UPDATE vector_memories SET content = ?, embedding = ?, metadata = ? WHERE id = ?;",
                (content, sqlite3.Binary(blob), json.dumps(updated_metadata), msg_id),
            )
            conn.commit()
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
                conn.commit()
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
    ) -> List[Dict[str, Any]]:
        """Return recent rows filtered to a project when requested."""
        with get_db_connection() as conn:
            if mem_type:
                rows = conn.execute(
                    "SELECT id, type, content, metadata, created_at FROM vector_memories WHERE type = ? ORDER BY rowid DESC;",
                    (mem_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, type, content, metadata, created_at FROM vector_memories ORDER BY rowid DESC;"
                ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            try:
                metadata = json.loads(item.pop("metadata") or "{}")
            except (json.JSONDecodeError, TypeError):
                metadata = {}
            if project_id and metadata.get("project_id", "personal") != project_id:
                continue
            item["metadata"] = metadata
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def prune(self, max_per_type: int = 2000) -> int:
        """
        Lightweight storage-retention guard. Keeps only the most recent
        `max_per_type` rows per memory type, deleting the oldest beyond the cap.
        This bounds long-term growth so memory stays tiny even over years of use.
        Returns the number of rows removed.
        """
        removed = 0
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # For each distinct type, delete rows beyond the newest max_per_type.
            cursor.execute("SELECT DISTINCT type FROM vector_memories;")
            types = [row["type"] for row in cursor.fetchall()]
            for mem_type in types:
                # Find the cutoff id: the id at offset max_per_type when ordered newest-first.
                cursor.execute(
                    """
                    SELECT id FROM vector_memories
                    WHERE type = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1 OFFSET ?;
                    """,
                    (mem_type, max_per_type),
                )
                cutoff = cursor.fetchone()
                if cutoff:
                    cursor.execute(
                        """
                        DELETE FROM vector_memories
                        WHERE type = ? AND rowid <= (SELECT rowid FROM vector_memories
                                                     WHERE id = ?);
                        """,
                        (mem_type, cutoff["id"]),
                    )
                    removed += cursor.rowcount
            conn.commit()
        if removed:
            print(f"[VECTOR_STORE] Storage retention: pruned {removed} old memory rows (bounded to {max_per_type}/type).")
        return removed
