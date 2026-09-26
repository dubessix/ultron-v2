"""
Ultron Filesystem Tools
Implements production-grade, validated FileRead, FileWrite, and FindFiles tools with complete metadata parameters.
Uses high-performance recursive globbing while safely ignoring cache/virtual environment structures.
"""

import fnmatch
import os
import re
import time
import asyncio
import datetime
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from backend.app.tools.tool_base import BaseTool

# --- Validation Schemas ---

class FileReadArgs(BaseModel):
    filepath: str = Field(..., description="Target absolute or relative file path to read.")

class FileWriteArgs(BaseModel):
    filepath: str = Field(..., description="Target file path to write.")
    content: Optional[str] = Field(None, description="Complete replacement text for full-file mode.")
    search_text: Optional[str] = Field(None, description="Edit mode: the exact text to change (must appear once). Use instead of content to change part of a file.")
    replace_text: Optional[str] = Field(None, description="Replacement block for patch mode; may be empty.")
    expected_sha256: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description="Optional fingerprint from file_read (coding mode requires it).",
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
            if self.expected_sha256 and any(
                character not in "0123456789abcdefABCDEF"
                for character in self.expected_sha256
            ):
                raise ValueError("expected_sha256 must be a 64-character SHA-256 fingerprint.")
        return self

FILE_TYPES: Dict[str, frozenset] = {
    "video": frozenset({".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts"}),
    "music": frozenset({".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus", ".wma"}),
    "image": frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic", ".tiff", ".ico"}),
    "pdf": frozenset({".pdf"}),
    "document": frozenset({".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".rtf", ".xls", ".xlsx", ".ods",
                           ".csv", ".ppt", ".pptx", ".odp", ".epub"}),
    "archive": frozenset({".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"}),
    "code": frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs",
                       ".php", ".rb", ".html", ".css", ".json", ".yaml", ".yml", ".sh", ".sql"}),
    "installer": frozenset({".deb", ".rpm", ".appimage", ".exe", ".msi", ".snap", ".flatpak", ".dmg", ".apk"}),
}
FIND_FILES_LIMIT = 20
FIND_FILES_MAX_VISITS = 400_000   # never walk forever on a huge disk
FIND_FILES_MAX_SECONDS = 25.0


def normalize_name(text: str) -> str:
    """'Demon.Slayer_Mugen-Train' -> 'demon slayer mugen train' (spaces . _ - and capitals don't matter)."""
    return " ".join(re.split(r"[\s._\-]+", str(text or "").lower())).strip()


class FindFilesArgs(BaseModel):
    pattern: str = Field(..., description="Name words or a glob (e.g. 'demon slayer', 'resume', '*.pdf'). Capitals, spaces, dots, _ and - don't matter.")
    search_root: Optional[str] = Field(".", description="Folder to search in: full path, '~', 'Desktop', 'Documents', 'Downloads', a drive like 'D:/', or just a folder name (auto-found).")
    file_type: Optional[str] = Field(None, description="Only this kind: video, music, image, pdf, document, archive, code, installer.")
    sort: Optional[str] = Field("newest", description="newest (default) or biggest.")

    @field_validator("file_type", mode="before")
    @classmethod
    def _known_type(cls, value):
        if value in (None, ""):
            return None
        key = str(value).strip().lower().rstrip("s")
        aliases = {"movie": "video", "film": "video", "song": "music", "audio": "music", "photo": "image",
                   "picture": "image", "doc": "document", "zip": "archive", "setup": "installer", "app": "installer"}
        key = aliases.get(key, key)
        return key if key in FILE_TYPES else None

    @field_validator("sort", mode="before")
    @classmethod
    def _known_sort(cls, value):
        return "biggest" if str(value or "").strip().lower() in ("biggest", "largest", "size", "big") else "newest"

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
            if expected_sha256 and current_sha256.lower() != str(expected_sha256).lower():
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
                    "error": ("search_text was not found; read the file and copy the exact text."
                              if current.count(search_text) == 0 else
                              "search_text appears more than once; include more lines so it is unique."),
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
            description="Find files by name words or glob anywhere under a folder (capitals, spaces, dots, _ and - don't matter), optional type (video/music/image/pdf/document/archive/code/installer). Max 20, newest or biggest first. Use when the owner names a file; use locate_path for folders.",
            category="filesystem",
            tags=["file", "find", "search", "glob", "locate"],
            permission_level=0, # Level 0: Read-Only (no confirmation)
            args_model=FindFilesArgs,
            usage_examples=["find_files(pattern='demon slayer', search_root='~', file_type='video')", "find_files(pattern='resume', file_type='pdf')"]
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
        glob_lower = pattern.lower()
        words = normalize_name(pattern).split()
        wanted_ext = FILE_TYPES.get(kwargs.get("file_type") or "")
        sort_key = "biggest" if kwargs.get("sort") == "biggest" else "newest"
        search_hidden = root_path.name.startswith(".")

        def _matches(name: str, path: Path) -> bool:
            if wanted_ext is not None and path.suffix.lower() not in wanted_ext:
                return False
            if is_glob:
                if "/" in pattern or "\\" in pattern:
                    return Path(str(path).lower()).match(glob_lower)
                return fnmatch.fnmatch(name.lower(), glob_lower)
            normalized = normalize_name(name)
            return all(word in normalized for word in words)

        # Recursive walking is IO-heavy: run it in a worker thread so it can't
        # block the event loop, and cap visits/time so a huge disk never hangs.
        def _run_search():
            found = []
            visited = 0
            deadline = time.monotonic() + FIND_FILES_MAX_SECONDS
            stopped_early = False
            for root, dirs, files in os.walk(root_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs and (search_hidden or not d.startswith("."))]
                for file in files:
                    visited += 1
                    if visited > FIND_FILES_MAX_VISITS or (visited % 2000 == 0 and time.monotonic() > deadline):
                        stopped_early = True
                        break
                    file_path = Path(root) / file
                    if not _matches(file, file_path):
                        continue
                    try:
                        file_rel = str(file_path.relative_to(self.workspace_root))
                    except ValueError:
                        file_rel = str(file_path)
                    try:
                        stat = file_path.stat()
                    except OSError:
                        continue
                    found.append({
                        "name": file,
                        "filepath": file_rel,
                        "size_bytes": stat.st_size,
                        "size_kb": f"{stat.st_size / 1024:.1f} KB",
                        "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat(),
                    })
                if stopped_early:
                    break
            return found, stopped_early

        try:
            results, stopped_early = await asyncio.to_thread(_run_search)
            if sort_key == "biggest":
                results.sort(key=lambda item: item["size_bytes"], reverse=True)
            else:
                results.sort(key=lambda item: item["modified_at"], reverse=True)
            shown = results[:FIND_FILES_LIMIT]
            data = {
                "pattern": pattern,
                "matches_count": len(results),
                "matches": shown,
                "sorted_by": sort_key,
            }
            if kwargs.get("file_type"):
                data["file_type"] = kwargs.get("file_type")
            if len(results) > len(shown):
                data["more"] = f"{len(results) - len(shown)} more not shown; narrow the words, type or folder."
            if stopped_early:
                data["note"] = "Search stopped early on a very large folder; results may be partial."
            return {"success": True, "data": data, "error": None}
        except Exception as e:
            return {"success": False, "error": f"File finder search aborted: {e}", "data": {}}
