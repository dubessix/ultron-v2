"""
Ultron Filesystem Tools
Implements production-grade, validated FileRead, FileWrite, and FindFiles tools with complete metadata parameters.
Uses high-performance recursive globbing while safely ignoring cache/virtual environment structures.
"""

import os
import asyncio
import datetime
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, model_validator
from backend.app.tools.tool_base import BaseTool

# --- Validation Schemas ---

class FileReadArgs(BaseModel):
    filepath: str = Field(..., description="Target absolute or relative file path to read.")

class FileWriteArgs(BaseModel):
    filepath: str = Field(..., description="Target file path to write.")
    content: Optional[str] = Field(None, description="Complete replacement text for full-file mode.")
    search_text: Optional[str] = Field(None, description="Exact unique block to replace in patch mode.")
    replace_text: Optional[str] = Field(None, description="Replacement block for patch mode; may be empty.")
    expected_sha256: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description="Required inspected file fingerprint for patch mode.",
    )

    @model_validator(mode="after")
    def validate_write_mode(self):
        full_mode = self.content is not None
        patch_mode = self.search_text is not None or self.replace_text is not None
        if full_mode == patch_mode:
            raise ValueError("Provide either content or search_text/replace_text patch fields.")
        if patch_mode:
            if not self.search_text:
                raise ValueError("Patch mode requires non-empty search_text.")
            if self.replace_text is None:
                raise ValueError("Patch mode requires replace_text (empty is allowed).")
            if not self.expected_sha256 or any(
                character not in "0123456789abcdefABCDEF"
                for character in self.expected_sha256
            ):
                raise ValueError("Patch mode requires a 64-character SHA-256 fingerprint.")
        return self

class FindFilesArgs(BaseModel):
    pattern: str = Field(..., description="Glob pattern or substring to search for (e.g. '*.pdf', 'resume').")
    search_root: Optional[str] = Field(".", description="Folder to search in: full path, '~', 'Desktop', 'Documents', 'Downloads', a drive like 'D:/', or just a folder name (auto-found).")

# --- Tool Implementations ---

class FileReadTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="file_read",
            name="File Reader",
            description="Reads and retrieves text contents of local files.",
            category="filesystem",
            tags=["file", "read", "load", "view"],
            permission_level=0, # Level 0: Read-Only (no confirmation)
            args_model=FileReadArgs,
            usage_examples=["file_read(filepath='src/App.jsx')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        filepath = kwargs.get("filepath", "")
        path = Path(filepath).resolve()
        
        # Security: block reading sensitive/system paths (e.g. /etc, C:\Windows, ~/.ssh).
        from backend.app.security.path_guard import is_path_safe
        if not is_path_safe(str(path)):
            return {"success": False, "error": f"Blocked by path guard: {filepath}", "data": {}}
        if not path.exists():
            return {"success": False, "error": f"File does not exist: {filepath}", "data": {}}
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return {
                "success": True,
                "data": {
                    "content": content,
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "bytes": len(content.encode("utf-8")),
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to read file: {e}", "data": {}}

class FileWriteTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="file_write",
            name="File Writer",
            description=(
                "Writes a complete file or applies one exact fingerprint-bound text patch "
                "through verified atomic replacement."
            ),
            category="filesystem",
            tags=["file", "write", "save", "create"],
            permission_level=2, # Filesystem write requires exact confirmation
            args_model=FileWriteArgs,
            usage_examples=["file_write(filepath='src/notes.txt', content='Active metrics')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        filepath = kwargs.get("filepath", "")
        content = kwargs.get("content")
        expected_sha256 = kwargs.get("expected_sha256")
        write_mode = "full"

        if content is None:
            write_mode = "patch"
            path = Path(filepath).expanduser().resolve(strict=False)
            try:
                current = path.read_text(encoding="utf-8")
            except OSError as exc:
                return {
                    "success": False,
                    "error": f"Patch target could not be read: {exc}",
                    "data": {"original_preserved": True},
                }
            current_sha256 = hashlib.sha256(current.encode("utf-8")).hexdigest()
            if current_sha256.lower() != str(expected_sha256 or "").lower():
                return {
                    "success": False,
                    "error": "File changed since inspection; read it again before patching.",
                    "data": {
                        "original_preserved": True,
                        "current_sha256": current_sha256,
                    },
                }
            search_text = str(kwargs.get("search_text") or "")
            if current.count(search_text) != 1:
                return {
                    "success": False,
                    "error": "Patch search_text must match exactly one block.",
                    "data": {
                        "original_preserved": True,
                        "matches": current.count(search_text),
                    },
                }
            content = current.replace(search_text, str(kwargs.get("replace_text") or ""), 1)

        # Route both full and patch modes through one verified atomic write path.
        from backend.app.tools.safe_write import safe_write_file
        result = await asyncio.to_thread(
            safe_write_file,
            filepath,
            str(content),
            expected_sha256,
        )
        if isinstance(result.get("data"), dict):
            result["data"]["write_mode"] = write_mode
        return result

class FindFilesTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="find_files",
            name="File Finder",
            description="Searches for files recursively inside the workspace using glob or text pattern checks.",
            category="filesystem",
            tags=["file", "find", "search", "glob", "locate"],
            permission_level=0, # Level 0: Read-Only (no confirmation)
            args_model=FindFilesArgs,
            usage_examples=["find_files(pattern='*.pdf')"]
        )
        self.workspace_root = Path(__file__).resolve().parent.parent.parent.parent

    async def execute(self, **kwargs) -> Dict[str, Any]:
        pattern = kwargs.get("pattern", "").strip()
        search_root_str = kwargs.get("search_root", ".")
        
        root_path = Path(search_root_str).resolve()
        if not root_path.exists():
            root_path = (self.workspace_root / search_root_str).resolve()
            if not root_path.exists():
                return {"success": False, "error": f"Search root folder '{search_root_str}' does not exist.", "data": {}}

        from backend.app.security.path_guard import check_path
        decision = check_path(str(root_path))
        if not decision["safe"]:
            return {"success": False, "error": f"Search root blocked ({decision['reason']}): {root_path}", "data": {}}

        if not pattern:
            return {"success": False, "error": "Pattern parameter cannot be empty.", "data": {}}

        skip_dirs = {".git", ".venv", "venv", "env", ".arena", ".cache", ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules", "build", "dist", "data", "coverage", "out", "target"}
        is_glob = "*" in pattern or "?" in pattern or "[" in pattern

        # Phase 3/Point-22: recursive workspace walking is IO-heavy — run it in a
        # worker thread so it can't block the event loop and freeze the assistant.
        def _run_search():
            found = []
            for root, dirs, files in os.walk(root_path):
                # Prune cache/virtual environments recursively
                dirs[:] = [d for d in dirs if d not in skip_dirs]

                for file in files:
                    file_path = Path(root) / file
                    # Fix 20: relative_to raises ValueError for paths outside workspace;
                    # fall back to absolute path so searching outside never crashes.
                    try:
                        file_rel = str(file_path.relative_to(self.workspace_root))
                    except ValueError:
                        file_rel = str(file_path)

                    matched = file_path.match(pattern) if is_glob else (pattern.lower() in file.lower())

                    if matched:
                        try:
                            stat = file_path.stat()
                            mtime = datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat()
                            found.append({
                                "name": file,
                                "filepath": file_rel,
                                "size_kb": f"{stat.st_size / 1024:.1f} KB",
                                "modified_at": mtime,
                            })
                        except OSError:
                            continue
            return found

        try:
            results = await asyncio.to_thread(_run_search)
            return {
                "success": True,
                "data": {
                    "pattern": pattern,
                    "matches_count": len(results),
                    "matches": results
                },
                "error": None
            }
        except Exception as e:
            return {"success": False, "error": f"File finder search aborted: {e}", "data": {}}
