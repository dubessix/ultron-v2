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
                "Downloads, OneDrive, every drive, any depth; forgives spelling). Use it when the owner "
                "names a folder without a full path; name='that folder' = the folder used last. If it "
                "returns choices, ask the owner which one."
            ),
            category="filesystem",
            tags=["locate", "where", "find folder", "directory", "path", "auto find"],
            permission_level=0,  # read-only
            args_model=LocatePathArgs,
            usage_examples=["locate_path(name='Projects')", "locate_path(name='resume.pdf', kind='file')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from backend.app.core import recent_folders
        from backend.app.security.path_guard import check_path
        from backend.app.security.path_locator import locate_detailed

        name = str(kwargs.get("name") or "").strip()
        kind = str(kwargs.get("kind") or "folder")
        if not name:
            return {"success": False, "data": {}, "error": "Name is required."}
        found = await asyncio.to_thread(locate_detailed, name, kind=kind, limit=15)
        allowed = [path for path in found["matches"] if check_path(path)["safe"]][:8]
        hidden = len(found["matches"]) - len(allowed)
        if not allowed:
            return {
                "success": False,
                "data": {"name": name, "kind": kind, "matches": []},
                "error": f"No accessible {kind} named '{name}' was found on this PC.",
            }
        exact = [path for path in found["exact"] if path in allowed]
        if found["ambiguous"] and len(exact) > 1:
            listed = "; ".join(f"{i}) {path}" for i, path in enumerate(exact[:5], 1))
            return {
                "success": True,
                "data": {
                    "name": name,
                    "kind": kind,
                    "ambiguous": True,
                    "choices": exact[:5],
                    "message": (
                        f"{len(exact)} places are named '{name}': {listed}. Do not guess: ask the owner "
                        "which one (say where each is, e.g. 'the one on Desktop or the one on D drive?')."
                    ),
                },
                "error": None,
            }
        if kind in ("folder", "any"):
            recent_folders.remember(allowed[0])
        return {
            "success": True,
            "data": {
                "name": name,
                "kind": kind,
                "best": allowed[0],
                "matches": allowed,
                "found_by": found["how"],
                "message": (
                    f"Found: {allowed[0]}"
                    + (" (closest spelling match - confirm with the owner)" if found["how"] == "fuzzy" else "")
                ),
                **({"blocked_matches": hidden} if hidden else {}),
            },
            "error": None,
        }
