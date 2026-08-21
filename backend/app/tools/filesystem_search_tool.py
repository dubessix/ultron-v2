"""
Ultron Document Search & File Converter Tools
Implements production-grade local file scanners and format converters (Level 1 Security).
1. search_inside_documents: High-speed local string/regex document text scanner.
2. convert_file_format: Standard JSON <-> CSV format converter with automated backup.
"""

import os
import re
import json
import csv
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool

# --- Validation Schemas ---

class SearchDocsArgs(BaseModel):
    search_query: str = Field(..., description="The word, phrase, or regular expression to locate.")
    file_extensions: Optional[str] = Field(".py,.js,.jsx,.ts,.tsx,.txt", description="Comma-separated file extensions to search (e.g. '.py,.txt').")

class ConvertFileArgs(BaseModel):
    source_filepath: str = Field(..., description="Target input file (e.g., 'report.json').")
    destination_filepath: str = Field(..., description="Destination file output (e.g., 'report.csv').")

# --- Document Search Tool ---

class SearchDocumentsTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="search_inside_documents",
            name="Document Search Engine",
            description="Searches for files containing a specific word, text snippet, or regular expression.",
            category="filesystem",
            tags=["file", "search", "grep", "scan", "document", "find", "code"],
            permission_level=0,  # Level 0: Read-Only (no manual confirmation required)
            args_model=SearchDocsArgs,
            usage_examples=["search_inside_documents(search_query='get_db_connection')"]
        )
        self.workspace_root = Path(__file__).resolve().parent.parent.parent.parent

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("search_query", "")
        extensions_str = kwargs.get("file_extensions", ".py,.js,.jsx,.ts,.tsx,.txt")
        
        if not query.strip():
            return {"success": False, "error": "Search query parameter is empty.", "data": {}}

        from backend.app.security.path_guard import check_path
        decision = check_path(str(self.workspace_root))
        if not decision["safe"]:
            return {"success": False, "error": f"Workspace search blocked ({decision['reason']}).", "data": {}}

        allowed_exts = set(extensions_str.lower().split(","))
        findings = []
        
        try:
            regex = re.compile(re.escape(query), re.IGNORECASE)
        except Exception as e:
            return {"success": False, "error": f"Invalid regex construction: {e}", "data": {}}

        skip_dirs = {".git", ".venv", "venv", "env", ".arena", ".cache", ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules", "build", "dist", "data", "coverage", "out", "target"}

        # Phase 3/Point-22: the document scan walks the whole workspace and reads
        # many files — run it in a worker thread so it can't block the event loop.
        def _run_scan():
            results = []
            for root, dirs, files in os.walk(self.workspace_root):
                dirs[:] = [d for d in dirs if d not in skip_dirs]

                for file in files:
                    ext = Path(file).suffix.lower()
                    if ext in allowed_exts:
                        file_path = Path(root) / file
                        try:
                            file_rel = str(file_path.relative_to(self.workspace_root))
                        except ValueError:
                            file_rel = str(file_path)

                        try:
                            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                                for lineno, line in enumerate(f, 1):
                                    if regex.search(line):
                                        results.append({
                                            "file": file_rel,
                                            "line": lineno,
                                            "content": line.strip(),
                                        })
                                        if len(results) >= 50:
                                            return results
                        except Exception:
                            continue

                    if len(results) >= 50:
                        return results
            return results

        findings = await asyncio.to_thread(_run_scan)

        return {
            "success": True,
            "data": {
                "search_query": query,
                "matches_count": len(findings),
                "matches": findings,
                "message": f"Found {len(findings)} matches for query '{query}'."
            },
            "error": None
        }

# --- Format Converter Tool ---

class ConvertFileFormatTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="convert_file_format",
            name="File Format Converter",
            description="Converts JSON files to CSV files, or CSV files to JSON files, saving output safely.",
            category="filesystem",
            tags=["file", "convert", "format", "json", "csv", "data"],
            permission_level=2,  # Format conversion writes a file; exact confirmation required
            args_model=ConvertFileArgs,
            usage_examples=["convert_file_format(source_filepath='report.json', destination_filepath='report.csv')"]
        )
        self.workspace_root = Path(__file__).resolve().parent.parent.parent.parent

    def _convert_json_to_csv(self, src: Path, dest: Path) -> None:
        with open(src, "r", encoding="utf-8") as j_file:
            data = json.load(j_file)
            
        if not isinstance(data, list):
            # If it's a single dict, wrap in a list
            data = [data]
            
        if not data:
            raise ValueError("JSON file is empty.")

        # Extract headers from first dictionary keys
        headers = list(data[0].keys())
        
        with open(dest, "w", encoding="utf-8", newline="") as c_file:
            writer = csv.DictWriter(c_file, fieldnames=headers)
            writer.writeheader()
            for row in data:
                writer.writerow(row)

    def _convert_csv_to_json(self, src: Path, dest: Path) -> None:
        data = []
        with open(src, "r", encoding="utf-8") as c_file:
            reader = csv.DictReader(c_file)
            for row in reader:
                data.append(dict(row))
                
        with open(dest, "w", encoding="utf-8") as j_file:
            json.dump(data, j_file, indent=2)

    async def execute(self, **kwargs) -> Dict[str, Any]:
        src_path_str = kwargs.get("source_filepath", "")
        dest_path_str = kwargs.get("destination_filepath", "")

        src_path = Path(src_path_str).resolve()
        dest_path = Path(dest_path_str).resolve()

        if not src_path.exists():
            # Try to resolve relative to workspace root if absolute check fails
            src_path = (self.workspace_root / src_path_str).resolve()
            dest_path = (self.workspace_root / dest_path_str).resolve()
            if not src_path.exists():
                return {"success": False, "error": f"Source file '{src_path_str}' does not exist.", "data": {}}

        from backend.app.security.path_guard import check_path
        for candidate in (src_path, dest_path):
            decision = check_path(str(candidate))
            if not decision["safe"]:
                return {"success": False, "error": f"Conversion path blocked ({decision['reason']}): {candidate}", "data": {}}

        try:
            # Check file extensions
            src_ext = src_path.suffix.lower()
            dest_ext = dest_path.suffix.lower()

            # Ensure output directories exist
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if src_ext == ".json" and dest_ext == ".csv":
                self._convert_json_to_csv(src_path, dest_path)
            elif src_ext == ".csv" and dest_ext == ".json":
                self._convert_csv_to_json(src_path, dest_path)
            else:
                return {"success": False, "error": f"Unsupported conversion from extension '{src_ext}' to '{dest_ext}'. Only JSON <-> CSV supported.", "data": {}}

            try:
                source_display = str(src_path.relative_to(self.workspace_root))
            except ValueError:
                source_display = str(src_path)
            try:
                destination_display = str(dest_path.relative_to(self.workspace_root))
            except ValueError:
                destination_display = str(dest_path)
            return {
                "success": True,
                "data": {
                    "message": f"Successfully converted format from '{src_path.name}' to '{dest_path.name}'.",
                    "source": source_display,
                    "destination": destination_display,
                },
                "error": None
            }
        except Exception as e:
            return {"success": False, "error": f"Conversion failed: {e}", "data": {}}
