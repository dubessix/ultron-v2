"""Project-scoped explicit memory management."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.app.memory.memory_engine import MemoryEngine
from backend.app.tools.tool_base import BaseTool


class MemoryArgs(BaseModel):
    action: str = Field(..., description="list, remember, forget, correct, export, restore, reembed")
    project_id: str = Field("personal", min_length=1)
    content: Optional[str] = None
    memory_id: Optional[str] = None
    mem_type: Optional[str] = None
    category: str = "explicit"
    importance: str = "normal"
    limit: int = Field(10, ge=1, le=500)
    memories: Optional[List[Dict[str, Any]]] = None


class MemoryTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="manage_memory",
            name="Memory Manager",
            description="Project-scoped list/remember/forget/correct/export/restore/re-embed.",
            category="memory",
            tags=["memory", "remember", "forget", "correct", "export", "restore"],
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
        if action in {"list", "export"}:
            return 0
        if action == "remember":
            return 1
        if action in {"restore", "reembed"}:
            return 2
        if action in {"forget", "correct"}:
            return 3
        return 1

    @staticmethod
    def _metadata(project_id: str, category: str, importance: str, **extra) -> dict:
        return {
            "kind": "explicit_remember",
            "source": "user",
            "project_id": project_id,
            "category": category,
            "importance": importance,
            **extra,
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = str(kwargs.get("action") or "list").lower()
        project_id = str(kwargs.get("project_id") or "personal").strip()
        content = kwargs.get("content")
        memory_id = kwargs.get("memory_id")
        mem_type = kwargs.get("mem_type")
        category = str(kwargs.get("category") or "explicit")
        importance = str(kwargs.get("importance") or "normal")
        limit = int(kwargs.get("limit", 10))

        if action == "remember":
            if not content or not str(content).strip():
                return {"success": False, "error": "content is required for remember.", "data": {}}
            ok = await self.memory.episodic.record_event(
                content=str(content).strip(),
                metadata=self._metadata(project_id, category, importance),
            )
            return {
                "success": ok,
                "data": {"message": "Remembered.", "project_id": project_id} if ok else {},
                "error": None if ok else "Failed to save memory (duplicate or provider error).",
            }

        if action in {"list", "export"}:
            rows = self.memory.vector_store.list_recent_memories(
                limit=limit, mem_type=mem_type, project_id=project_id
            )
            return {
                "success": True,
                "data": {
                    "count": len(rows),
                    "project_id": project_id,
                    "format": "json" if action == "export" else None,
                    "memories": rows,
                },
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
            updated = await self.memory.vector_store.update_vector_memory(
                memory_id,
                str(content).strip(),
                self._metadata(
                    project_id,
                    category,
                    importance,
                    corrected_from_sha256=hashlib.sha256(existing["content"].encode("utf-8")).hexdigest(),
                ),
            )
            return {
                "success": updated,
                "data": {"message": f"Corrected memory {memory_id}.", "project_id": project_id} if updated else {},
                "error": None if updated else "Memory correction failed.",
            }

        if action == "restore":
            memories = kwargs.get("memories") or []
            restored = 0
            failed = 0
            for item in memories[:limit]:
                item_content = str(item.get("content") or "").strip()
                if not item_content:
                    failed += 1
                    continue
                item_type = str(item.get("type") or "episodic")
                metadata = dict(item.get("metadata") or {})
                metadata.update(self._metadata(project_id, category, importance, restored=True))
                try:
                    embedding = await self.memory.vector_store.generate_embedding(item_content)
                    saved = self.memory.vector_store.save_vector_memory(
                        str(uuid.uuid4()), item_type, item_content, embedding, metadata
                    )
                except Exception:
                    saved = False
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
