"""Project-scoped explicit memory management."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.app.memory.memory_engine import MemoryEngine
from backend.app.memory.structured_memory import (
    ALLOWED_IMPORTANCE,
    ALLOWED_MEMORY_CATEGORIES,
    bounded_text,
    corrected_memory_metadata,
    explicit_memory_metadata,
    memory_inventory,
    normalize_category,
    normalize_importance,
)
from backend.app.tools.tool_base import BaseTool


class MemoryArgs(BaseModel):
    action: str = Field(
        ...,
        description="search (past chats and saved facts), list, organize, remember, forget, correct, export, restore, reembed",
    )
    project_id: str = Field("personal", min_length=1)
    content: Optional[str] = None
    memory_id: Optional[str] = None
    mem_type: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[str] = None
    limit: int = Field(10, ge=1, le=500)
    memories: Optional[List[Dict[str, Any]]] = None


class MemoryTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="manage_memory",
            name="Memory Manager",
            description="Project-scoped search/list/organize/remember/forget/correct/export/restore/re-embed.",
            category="memory",
            tags=["memory", "organize", "remember", "forget", "correct", "export", "restore"],
            permission_level=1,
            args_model=MemoryArgs,
            usage_examples=[
                "manage_memory(action='remember', project_id='personal', content='Prefers emerald theme')",
                "manage_memory(action='list', project_id='personal')",
            ],
        )
        self.memory = MemoryEngine()

    def permission_for_arguments(self, arguments: Dict[str, Any]) -> int:
        action = str(arguments.get("action", "list")).lower()
        if action in {"search", "list", "organize", "export"}:
            return 0
        if action == "remember":
            return 1
        if action in {"restore", "reembed"}:
            return 2
        if action in {"forget", "correct"}:
            return 3
        return 1

    @staticmethod
    def _validation_error(category: Any, importance: Any) -> Optional[str]:
        if normalize_category(category) is None:
            return (
                "Unsupported memory category. Allowed: "
                + ", ".join(ALLOWED_MEMORY_CATEGORIES)
            )
        if normalize_importance(importance) is None:
            return (
                "Unsupported memory importance. Allowed: "
                + ", ".join(ALLOWED_IMPORTANCE)
            )
        return None

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = str(kwargs.get("action") or "list").lower()
        project_id = str(kwargs.get("project_id") or "personal").strip()
        content = kwargs.get("content")
        memory_id = kwargs.get("memory_id")
        mem_type = kwargs.get("mem_type")
        category = kwargs.get("category")
        importance = kwargs.get("importance")
        limit = int(kwargs.get("limit", 10))

        if action == "remember":
            if not content or not str(content).strip():
                return {"success": False, "error": "content is required for remember.", "data": {}}
            category = category or "explicit"
            importance = importance or "normal"
            validation_error = self._validation_error(category, importance)
            if validation_error:
                return {"success": False, "error": validation_error, "data": {}}
            clean_content = bounded_text(content, 4000)
            metadata = explicit_memory_metadata(
                project_id=project_id,
                category=category,
                importance=importance,
                content=clean_content,
            )
            status = await self.memory.vector_store.remember(
                "episodic", clean_content, metadata, return_status=True
            )
            ok = status in {"saved", "duplicate"}
            return {
                "success": ok,
                "data": {
                    # a near-identical fact already saved = he already knows it
                    "message": "Remembered." if status == "saved" else "Already remembered.",
                    "project_id": project_id,
                    "category": metadata["category"],
                    "importance": metadata["importance"],
                } if ok else {},
                "error": None if ok else "Could not save the memory (database error).",
            }

        if action == "search":
            # The AI decides when to look into the past (no word-list trigger).
            query = str(content or "").strip()
            if not query:
                return {"success": False, "error": "content (what to search for) is required.", "data": {}}
            from backend.app.database.db import get_db_connection
            from backend.app.memory.recall_index import search_recall_index

            try:
                with get_db_connection() as conn:
                    found = search_recall_index(conn, query, project_id=project_id, limit=min(limit, 8))
            except Exception as exc:  # the index is optional; semantic search may still work
                print(f"[MEMORY_TOOL] recall index skipped: {exc}")
                found = []
            try:
                events = await self.memory.episodic.recall_related_events(query, limit=5, project_id=project_id)
            except Exception:
                events = []
            hits, seen_ids = [], set()
            for item in list(found) + [e for e in events if e.get("similarity", 0.0) >= 0.45]:
                text = bounded_text(str(item.get("content") or item.get("text") or ""), 300)
                if not text:
                    continue
                if "source_type" in item:  # word-index hit (chat, summary or saved fact)
                    source = item.get("source_type")
                    memory_id = item.get("source_id") if source == "memory" else None
                else:  # meaning (vector) hit = always a saved memory row
                    source, memory_id = "memory", item.get("id")
                # memory_id lets forget/correct act on the exact saved fact
                if memory_id and memory_id in seen_ids:
                    continue
                if memory_id:
                    seen_ids.add(memory_id)
                hit = {"text": text, "kind": "saved fact" if source == "memory" else "past chat",
                       "when": item.get("updated_at") or item.get("created_at") or item.get("timestamp")}
                if memory_id and source == "memory":
                    hit["memory_id"] = memory_id
                hits.append(hit)
            hits = hits[:10]
            return {"success": True, "data": {"count": len(hits), "results": hits}, "error": None}

        if action in {"list", "export"}:
            rows = self.memory.vector_store.list_recent_memories(
                limit=limit, mem_type=mem_type, project_id=project_id
            )
            if action == "export":
                from backend.app.memory.memory_ui import safe_export_memories

                data = safe_export_memories(rows, project_id)
            else:
                data = {
                    "count": len(rows),
                    "project_id": project_id,
                    "format": None,
                    "memories": rows,
                }
            return {
                "success": True,
                "data": data,
                "error": None,
            }

        if action == "organize":
            rows = self.memory.vector_store.list_recent_memories(
                limit=500,
                project_id=project_id,
            )
            return {
                "success": True,
                "data": memory_inventory(rows, project_id),
                "error": None,
            }

        if action in {"forget", "correct"}:
            if not memory_id:
                return {"success": False, "error": "memory_id is required.", "data": {}}
            existing = self.memory.vector_store.get_memory(memory_id)
            if not existing or existing.get("metadata", {}).get("project_id", "personal") != project_id:
                return {"success": False, "error": "Memory not found in the requested project.", "data": {}}
            if action == "forget":
                deleted = self.memory.vector_store.delete_vector_memory(memory_id)
                return {
                    "success": deleted,
                    "data": {"message": f"Forgot memory {memory_id}.", "project_id": project_id} if deleted else {},
                    "error": None if deleted else "Memory deletion failed.",
                }
            if not content or not str(content).strip():
                return {"success": False, "error": "content is required for correct.", "data": {}}
            existing_metadata = dict(existing.get("metadata") or {})
            category = category or existing_metadata.get("category") or "explicit"
            importance = importance or existing_metadata.get("importance") or "normal"
            validation_error = self._validation_error(category, importance)
            if validation_error:
                return {"success": False, "error": validation_error, "data": {}}
            clean_content = bounded_text(content, 4000)
            revision_metadata = corrected_memory_metadata(existing, clean_content)
            revision_metadata.update(
                {
                    "project_id": project_id,
                    "category": normalize_category(category),
                    "importance": normalize_importance(importance),
                    "source": "user_correction",
                }
            )
            updated = await self.memory.vector_store.update_vector_memory(
                memory_id,
                clean_content,
                revision_metadata,
            )
            return {
                "success": updated,
                "data": {
                    "message": f"Corrected memory {memory_id}.",
                    "project_id": project_id,
                    "revision": revision_metadata["revision"],
                } if updated else {},
                "error": None if updated else "Memory correction failed.",
            }

        if action == "restore":
            memories = kwargs.get("memories") or []
            restored = 0
            failed = 0
            for item in memories[:limit]:
                item_content = bounded_text(item.get("content"), 4000)
                if not item_content:
                    failed += 1
                    continue
                item_type = str(item.get("type") or "episodic")
                imported_metadata = dict(item.get("metadata") or {})
                item_category = imported_metadata.get("category") or category or "explicit"
                item_importance = imported_metadata.get("importance") or importance or "normal"
                structured_metadata = explicit_memory_metadata(
                    project_id=project_id,
                    category=item_category,
                    importance=item_importance,
                    content=item_content,
                    restored=True,
                )
                if structured_metadata is None:
                    failed += 1
                    continue
                imported_metadata.update(structured_metadata)
                saved = await self.memory.vector_store.remember(
                    item_type, item_content, imported_metadata
                )
                restored += int(saved)
                failed += int(not saved)
            return {
                "success": failed == 0,
                "data": {"project_id": project_id, "restored": restored, "failed": failed},
                "error": None if failed == 0 else "Some memories could not be restored.",
            }

        if action == "reembed":
            result = await self.memory.vector_store.reembed_project(project_id, limit=limit)
            return {"success": True, "data": {"project_id": project_id, **result}, "error": None}

        return {"success": False, "error": f"Unsupported action '{action}'.", "data": {}}
