"""Bounded real search across approved filenames and local assistant records."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field

from backend.app.database.db import get_db_connection
from backend.app.security.path_guard import check_path, get_allowed_paths
from backend.app.tools.tool_base import BaseTool


class UniversalSearchArgs(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    project_id: str = Field("personal", min_length=1, max_length=200)
    limit: int = Field(20, ge=1, le=50)


class UniversalSearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="universal_search",
            name="Universal Local Search",
            description="Searches real approved filenames, tasks, reminders, and project-scoped memories.",
            category="search",
            tags=["search", "files", "tasks", "reminders", "memory", "projects"],
            permission_level=0,
            args_model=UniversalSearchArgs,
            usage_examples=["universal_search(query='release notes', project_id='personal')"],
        )

    @staticmethod
    def _database_results(query: str, project_id: str, limit: int) -> list[dict]:
        pattern = f"%{query}%"
        results = []
        with get_db_connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
            if "project_tasks" in tables:
                rows = conn.execute(
                    """
                    SELECT id, title, project_name, module_name, status
                    FROM project_tasks
                    WHERE title LIKE ? OR description LIKE ? OR project_name LIKE ? OR module_name LIKE ?
                    ORDER BY created_at DESC LIMIT ?;
                    """,
                    (pattern, pattern, pattern, pattern, limit),
                ).fetchall()
                results.extend({
                    "id": row["id"],
                    "name": row["title"],
                    "category": "Task",
                    "detail": f"{row['project_name']}/{row['module_name']} · {row['status']}",
                } for row in rows)
            if len(results) < limit and "reminders_alarms" in tables:
                remaining = limit - len(results)
                rows = conn.execute(
                    """
                    SELECT id, title, description, target_time, status
                    FROM reminders_alarms
                    WHERE title LIKE ? OR description LIKE ?
                    ORDER BY target_time ASC LIMIT ?;
                    """,
                    (pattern, pattern, remaining),
                ).fetchall()
                results.extend({
                    "id": row["id"],
                    "name": row["title"],
                    "category": "Reminder",
                    "detail": f"{row['target_time']} · {row['status']}",
                } for row in rows)
            if len(results) < limit and "vector_memories" in tables:
                rows = conn.execute(
                    """
                    SELECT id, type, content, metadata, created_at
                    FROM vector_memories WHERE content LIKE ?
                    ORDER BY created_at DESC LIMIT ?;
                    """,
                    (pattern, min(200, limit * 5)),
                ).fetchall()
                for row in rows:
                    try:
                        metadata = json.loads(row["metadata"] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        metadata = {}
                    if metadata.get("project_id", "personal") != project_id:
                        continue
                    results.append({
                        "id": row["id"],
                        "name": str(row["content"])[:100],
                        "category": "Memory",
                        "detail": f"{row['type']} · {row['created_at']}",
                    })
                    if len(results) >= limit:
                        break
        return results[:limit]

    @staticmethod
    def _file_results(query: str, limit: int) -> tuple[list[dict], bool, int]:
        lowered = query.casefold()
        results = []
        scanned = 0
        truncated = False
        deadline = time.monotonic() + 1.5
        skip_dirs = {
            ".git", ".venv", "venv", "node_modules", "dist", "build", "data",
            "__pycache__", ".cache", ".pytest_cache", ".ruff_cache", "coverage",
        }
        seen_roots = set()
        for root_text in get_allowed_paths():
            root = Path(root_text).resolve(strict=False)
            if root in seen_roots or not root.is_dir():
                continue
            seen_roots.add(root)
            for current, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [name for name in dirs if name not in skip_dirs]
                for filename in files:
                    scanned += 1
                    if scanned > 3000 or time.monotonic() >= deadline:
                        truncated = True
                        return results, truncated, scanned
                    if lowered not in filename.casefold():
                        continue
                    path = Path(current) / filename
                    decision = check_path(str(path))
                    if not decision["safe"]:
                        continue
                    results.append({
                        "id": str(path.resolve(strict=False)),
                        "name": filename,
                        "category": "File",
                        "detail": str(path.resolve(strict=False)),
                    })
                    if len(results) >= limit:
                        return results, truncated, scanned
        return results, truncated, scanned

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = str(kwargs.get("query") or "").strip()
        project_id = str(kwargs.get("project_id") or "personal").strip()
        limit = int(kwargs.get("limit", 20))
        try:
            results = self._database_results(query, project_id, limit)
            remaining = max(0, limit - len(results))
            if remaining:
                file_results, truncated, scanned = self._file_results(query, remaining)
                results.extend(file_results)
            else:
                truncated, scanned = False, 0
        except Exception as exc:
            return {
                "success": False,
                "data": {"status": "unavailable", "results": []},
                "error": f"Local search failed: {exc}",
            }
        return {
            "success": True,
            "data": {
                "query": query,
                "project_id": project_id,
                "results": results[:limit],
                "count": len(results[:limit]),
                "files_scanned": scanned,
                "truncated": truncated,
                "searched_sources": ["approved filenames", "tasks", "reminders", "project memories"],
            },
            "error": None,
        }
