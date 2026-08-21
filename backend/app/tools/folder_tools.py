"""
Ultron Production-Grade Folder Management Tools
Implements real local directory operations: Create, Rename, Delete, Copy, Move, List, Compress, Extract ZIP, and Organize.
Includes Level 3 confirmation gates for dangerous directory deletions, and Level 2 for folder organizations.
"""

import os
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Any
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool
from backend.app.security.path_guard import check_path


def _guard_paths(*paths: Path):
    for path in paths:
        decision = check_path(str(path))
        if not decision["safe"]:
            return {
                "success": False,
                "error": f"Blocked by path guard ({decision['reason']}): {path}",
                "data": {},
            }
    return None

# --- Validation Schemas ---

class CreateFolderArgs(BaseModel):
    folderpath: str = Field(..., description="Target directory path to create.")

class RenameFolderArgs(BaseModel):
    old_path: str = Field(..., description="Current folder path.")
    new_path: str = Field(..., description="Target new folder path.")

class DeleteFolderArgs(BaseModel):
    folderpath: str = Field(..., description="Target folder path to remove recursively.")

class CopyMoveFolderArgs(BaseModel):
    source_path: str = Field(..., description="Source folder path.")
    destination_path: str = Field(..., description="Destination target path.")

class ListContentsArgs(BaseModel):
    folderpath: str = Field(..., description="Directory path to list.")

class CompressFolderArgs(BaseModel):
    folderpath: str = Field(..., description="Folder path to compress.")
    archive_format: str = Field("zip", description="Format: zip | tar | gztar.")

class ExtractZipArgs(BaseModel):
    zippath: str = Field(..., description="Source ZIP file path.")
    extract_to: str = Field(..., description="Target destination directory.")

class OrganizeFolderArgs(BaseModel):
    folderpath: str = Field(..., description="Target folder path (e.g. Downloads) to scan and organize recursively.")

# --- Tool Implementations ---

class CreateFolderTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="create_folder",
            name="Folder Creator",
            description="Creates a local directory recursively.",
            category="filesystem",
            tags=["folder", "directory", "create", "mkdir"],
            permission_level=2,
            args_model=CreateFolderArgs,
            usage_examples=["create_folder(folderpath='D:\\backups')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        folderpath = kwargs.get("folderpath", "")
        path = Path(folderpath).resolve()
        blocked = _guard_paths(path)
        if blocked:
            return blocked
        try:
            path.mkdir(parents=True, exist_ok=True)
            return {"success": True, "data": {"message": f"Successfully created directory: {folderpath}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to create directory: {e}", "data": {}}

class RenameFolderTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="rename_folder",
            name="Folder Renamer",
            description="Renames or moves a local folder.",
            category="filesystem",
            tags=["folder", "rename", "move"],
            permission_level=2,
            args_model=RenameFolderArgs,
            usage_examples=["rename_folder(old_path='old', new_path='new')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        old = Path(kwargs.get("old_path", "")).resolve()
        new = Path(kwargs.get("new_path", "")).resolve()
        blocked = _guard_paths(old, new)
        if blocked:
            return blocked
        try:
            os.rename(old, new)
            return {"success": True, "data": {"message": f"Successfully renamed {old.name} to {new.name}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to rename folder: {e}", "data": {}}

class DeleteFolderTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="delete_folder",
            name="Folder Deleter",
            description="Deletes a folder and all its contents recursively. Dangerous.",
            category="filesystem",
            tags=["folder", "delete", "remove", "rmdir"],
            permission_level=3, # Level 3: Dangerous/Destructive (Requires confirmation)
            args_model=DeleteFolderArgs,
            usage_examples=["delete_folder(folderpath='D:\\temp_backup')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        folderpath = kwargs.get("folderpath", "")
        path = Path(folderpath).resolve()
        blocked = _guard_paths(path)
        if blocked:
            return blocked
        if not path.exists():
            return {"success": False, "error": f"Directory does not exist: {folderpath}", "data": {}}
        try:
            shutil.rmtree(path)
            return {"success": True, "data": {"message": f"Successfully deleted directory recursively: {folderpath}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to delete directory: {e}", "data": {}}

class CopyFolderTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="copy_folder",
            name="Folder Copier",
            description="Copies a folder and all its contents recursively to a new target directory.",
            category="filesystem",
            tags=["folder", "copy", "duplicate"],
            permission_level=2,
            args_model=CopyMoveFolderArgs,
            usage_examples=["copy_folder(source_path='src', destination_path='backup_src')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        src = Path(kwargs.get("source_path", "")).resolve()
        dest = Path(kwargs.get("destination_path", "")).resolve()
        blocked = _guard_paths(src, dest)
        if blocked:
            return blocked
        try:
            shutil.copytree(src, dest, dirs_exist_ok=True)
            return {"success": True, "data": {"message": f"Successfully copied directory from {src.name} to {dest.name}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to copy directory: {e}", "data": {}}

class MoveFolderTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="move_folder",
            name="Folder Mover",
            description="Moves a folder and all its contents recursively to a new destination.",
            category="filesystem",
            tags=["folder", "move", "shutil"],
            permission_level=2,
            args_model=CopyMoveFolderArgs,
            usage_examples=["move_folder(source_path='temp', destination_path='data\\temp')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        src = Path(kwargs.get("source_path", "")).resolve()
        dest = Path(kwargs.get("destination_path", "")).resolve()
        blocked = _guard_paths(src, dest)
        if blocked:
            return blocked
        try:
            shutil.move(str(src), str(dest))
            return {"success": True, "data": {"message": f"Successfully moved directory to {dest}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to move directory: {e}", "data": {}}

class ListContentsTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="list_contents",
            name="Folder Contents Lister",
            description="Lists all files and subfolders inside a target directory.",
            category="filesystem",
            tags=["folder", "list", "ls", "contents"],
            permission_level=0, # Level 0: Read-Only
            args_model=ListContentsArgs,
            usage_examples=["list_contents(folderpath='D:\\SaaS-Builds')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        folderpath = kwargs.get("folderpath", "")
        # Explicit ~ resolves to home; ordinary relative paths resolve from the
        # project workspace so registry preflight and execution use one target.
        raw = folderpath.strip()
        expanded = os.path.expanduser(raw)
        if not os.path.isabs(expanded):
            workspace = Path(__file__).resolve().parent.parent.parent.parent
            expanded = str(workspace / expanded)
        path = Path(expanded).resolve()
        blocked = _guard_paths(path)
        if blocked:
            return blocked
        if not path.exists():
            return {"success": False, "error": f"Directory does not exist: {folderpath}", "data": {}}
        try:
            contents = os.listdir(path)
            details = []
            for item in contents:
                item_path = path / item
                details.append({
                    "name": item,
                    "type": "folder" if item_path.is_dir() else "file",
                    "size": f"{item_path.stat().st_size / 1024:.1f} KB" if item_path.is_file() else None
                })
            return {"success": True, "data": {"contents": details, "raw_names": contents, "path": str(path)}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to list directory contents: {e}", "data": {}}

class CompressFolderTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="compress_folder",
            name="Folder Compressor",
            description="Compresses a folder recursively into a ZIP or TAR archive file.",
            category="filesystem",
            tags=["folder", "compress", "zip", "archive", "tar"],
            permission_level=2,
            args_model=CompressFolderArgs,
            usage_examples=["compress_folder(folderpath='src', archive_format='zip')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        folderpath = kwargs.get("folderpath", "")
        fmt = kwargs.get("archive_format", "zip")
        path = Path(folderpath).resolve()
        blocked = _guard_paths(path, path.parent)
        if blocked:
            return blocked
        if not path.exists():
            return {"success": False, "error": f"Directory does not exist: {folderpath}", "data": {}}
        try:
            archive_path = shutil.make_archive(
                base_name=str(path),
                format=fmt,
                root_dir=str(path.parent),
                base_dir=str(path.name)
            )
            return {"success": True, "data": {"archive_path": archive_path, "message": f"Successfully compressed folder into {fmt} archive."}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to compress directory: {e}", "data": {}}

class ExtractZipTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="extract_zip",
            name="ZIP Extractor",
            description="Extracts a ZIP archive file recursively to a target directory.",
            category="filesystem",
            tags=["folder", "extract", "unzip", "zipfile"],
            permission_level=2,
            args_model=ExtractZipArgs,
            usage_examples=["extract_zip(zippath='src.zip', extract_to='extracted_src')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        zippath = Path(kwargs.get("zippath", "")).resolve()
        dest = Path(kwargs.get("extract_to", "")).resolve()
        blocked = _guard_paths(zippath, dest)
        if blocked:
            return blocked
        if not zippath.exists():
            return {"success": False, "error": f"ZIP archive does not exist: {zippath}", "data": {}}
        try:
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zippath, 'r') as zip_ref:
                # Zip-slip protection: ensure every member stays inside dest.
                dest_resolved = dest.resolve()
                for member in zip_ref.infolist():
                    member_path = (dest / member.filename).resolve()
                    if not member_path.is_relative_to(dest_resolved):
                        return {"success": False, "error": f"Zip-slip blocked: '{member.filename}' escapes target directory.", "data": {}}
                zip_ref.extractall(dest)
            return {"success": True, "data": {"message": f"Successfully extracted archive to {dest}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to extract ZIP: {e}", "data": {}}

class OrganizeFolderTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="organize_folder",
            name="Folder Organizer",
            description="Scans the target directory, groups files by extensions, creates subfolders, and moves files recursively. Protects duplicates.",
            category="filesystem",
            tags=["folder", "organize", "files", "clean"],
            permission_level=2, # Level 2: Requires manual confirmation
            args_model=OrganizeFolderArgs,
            usage_examples=["organize_folder(folderpath='D:\\Downloads')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        folderpath = kwargs.get("folderpath", "")
        path = Path(folderpath).resolve()
        blocked = _guard_paths(path)
        if blocked:
            return blocked
        if not path.exists():
            return {"success": False, "error": f"Directory does not exist: {folderpath}", "data": {}}

        # Define file categorization maps
        categories = {
            "images": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"],
            "documents": [".pdf", ".docx", ".doc", ".xlsx", ".txt", ".pptx", ".csv"],
            "archives": [".zip", ".tar", ".gz", ".rar", ".7z"],
            "code": [".py", ".js", ".jsx", ".html", ".css", ".json", ".sh", ".bat"],
            "executables": [".exe", ".msi", ".deb", ".dmg"]
        }

        moved_count = 0
        try:
            for item in os.listdir(path):
                item_path = path / item
                if item_path.is_file():
                    ext = item_path.suffix.lower()
                    target_category = "others"
                    for cat, ext_list in categories.items():
                        if ext in ext_list:
                            target_category = cat
                            break

                    # Create subfolder recursively
                    subfolder = path / target_category
                    subfolder.mkdir(exist_ok=True)

                    # Move file safely
                    dest_path = subfolder / item
                    if not dest_path.exists():
                        shutil.move(str(item_path), str(dest_path))
                        moved_count += 1

            return {"success": True, "data": {"moved_count": moved_count, "message": f"Successfully organized {moved_count} files into sorted subfolders."}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to organize directory: {e}", "data": {}}
