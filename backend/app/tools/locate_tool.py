"""Jarvis 'where is it?' tool — finds folders/files anywhere on this PC by name."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from pydantic import BaseModel, Field

from backend.app.tools.tool_base import BaseTool


class LocatePathArgs(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Folder or file name as the owner said it, e.g. 'Projects', 'invoice.pdf', 'college notes'.",
    )
    kind: str = Field(
        "folder",
        pattern="^(folder|file|any)$",
        description="What to look for: folder, file or any.",
    )


class LocatePathTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="locate_path",
            name="Path Locator",
            description=(
                "Finds where a folder or file lives on this PC by name (Desktop, Documents, "
                "Downloads, OneDrive, every drive). Use it when the owner names a folder "
                "without a full path, then pass the returned path to other tools."
            ),
            category="filesystem",
            tags=["locate", "where", "find folder", "directory", "path", "auto find"],
            permission_level=0,  # read-only
            args_model=LocatePathArgs,
            usage_examples=["locate_path(name='Projects')", "locate_path(name='resume.pdf', kind='file')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from backend.app.security.path_guard import check_path
        from backend.app.security.path_locator import locate

        name = str(kwargs.get("name") or "").strip()
        kind = str(kwargs.get("kind") or "folder")
        if not name:
            return {"success": False, "data": {}, "error": "Name is required."}
        matches = await asyncio.to_thread(locate, name, kind=kind, limit=15)
        allowed = [path for path in matches if check_path(path)["safe"]][:8]
        hidden = len(matches) - len(allowed) if len(matches) <= 15 else None
        if not allowed:
            return {
                "success": False,
                "data": {"name": name, "kind": kind, "matches": []},
                "error": f"No accessible {kind} named '{name}' was found on this PC.",
            }
        return {
            "success": True,
            "data": {
                "name": name,
                "kind": kind,
                "best": allowed[0],
                "matches": allowed,
                "message": (
                    f"Found {len(allowed)} match(es). Best: {allowed[0]}"
                    + (" — ask the owner which one if unsure." if len(allowed) > 1 else "")
                ),
                **({"blocked_matches": hidden} if hidden else {}),
            },
            "error": None,
        }
