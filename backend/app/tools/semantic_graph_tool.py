"""
Ultron Semantic Code Search Graph Tool
Implements a production-grade, un-mocked developer intelligence tool that parses the
local workspace's Python codebase using AST (Abstract Syntax Tree), builds an in-memory 
semantic symbol-dependency-caller graph, and queries it for modular relationships.
Provides dependency tracking, symbol resolution, and call-graph traversal (Level 1 Write Security).
"""

import os
import ast
import json
import re
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool
from backend.app.runtime_paths import runtime_data_path

class SemanticGraphArgs(BaseModel):
    query_type: str = Field("summary", description="Query type: build, search, callers, dependencies, or summary.")
    target_symbol: Optional[str] = Field(None, description="The specific class, function, or symbol to locate/trace callers for.")
    target_path: Optional[str] = Field(None, description="Relative or absolute path of a specific file to trace dependencies for.")

class SemanticGraphTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="semantic_code_graph",
            name="Semantic Code Search Graph",
            description="Builds, traverses, and queries an AST-based semantic graph of symbols, imports, and function callers across the codebase.",
            category="system",
            tags=["code", "ast", "search", "graph", "dependencies", "callers", "intelligence"],
            permission_level=1,  # Level 1: Read/Write query (No confirmation required)
            args_model=SemanticGraphArgs,
            usage_examples=[
                "semantic_code_graph(query_type='summary')",
                "semantic_code_graph(query_type='callers', target_symbol='get_db_connection')",
                "semantic_code_graph(query_type='dependencies', target_path='backend/app/main.py')"
            ]
        )
        self.workspace_root = Path(__file__).resolve().parent.parent.parent.parent
        self.graph_cache_path = runtime_data_path("cache", "semantic_graph.json")
        # Hard bounds prevent accidental indexing of a virtual environment or an
        # unexpectedly huge workspace from consuming minutes and tens of MB.
        self.max_index_files = int(os.getenv("ULTRON_SEMANTIC_MAX_FILES", "5000"))
        self.max_scan_seconds = float(os.getenv("ULTRON_SEMANTIC_MAX_SECONDS", "20"))
        self.max_cache_bytes = int(os.getenv("ULTRON_SEMANTIC_MAX_CACHE_BYTES", str(16 * 1024 * 1024)))

    def _parse_file_ast(self, file_path: Path) -> Dict[str, Any]:
        """Parses a single python file's AST to extract symbols, classes, functions, calls, and imports."""
        file_relative = str(file_path.relative_to(self.workspace_root))
        
        symbols = []
        calls = []
        imports = []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content, filename=str(file_path))
        except Exception as e:
            return {
                "file": file_relative,
                "error": f"AST Parse Error: {e}",
                "classes": [],
                "functions": [],
                "imports": [],
                "calls": []
            }

        class_defs = []
        func_defs = []

        class ASTVisitor(ast.NodeVisitor):
            def __init__(self, file_rel: str):
                self.file_rel = file_rel
                self.current_class = None

            def visit_ClassDef(self, node: ast.ClassDef):
                class_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [ast.unparse(b) for b in node.bases],
                    "docstring": ast.get_docstring(node) or ""
                }
                class_defs.append(class_info)
                
                # Push class context
                old_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old_class

            def visit_FunctionDef(self, node: ast.FunctionDef):
                func_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "class_context": self.current_class,
                    "args": [arg.arg for arg in node.args.args],
                    "docstring": ast.get_docstring(node) or ""
                }
                func_defs.append(func_info)
                self.generic_visit(node)

            def visit_Import(self, node: ast.Import):
                for alias in node.names:
                    imports.append({
                        "name": alias.name,
                        "alias": alias.asname,
                        "line": node.lineno
                    })
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append({
                        "name": f"{module}.{alias.name}" if module else alias.name,
                        "alias": alias.asname,
                        "line": node.lineno
                    })
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call):
                try:
                    call_name = ast.unparse(node.func)
                    # Exclude basic builtins or expressions that aren't symbol calls
                    if re.match(r'^[a-zA-Z0-9_\.]+$', call_name):
                        calls.append({
                            "name": call_name,
                            "line": node.lineno
                        })
                        # Track unique referenced symbols (dedup below).
                        symbols.append(call_name)
                except Exception:
                    pass
                self.generic_visit(node)

        visitor = ASTVisitor(file_relative)
        visitor.visit(tree)

        # Deduplicate symbols (preserve order) so the list is meaningful/usable.
        unique_symbols = list(dict.fromkeys(symbols))

        return {
            "file": file_relative,
            "classes": class_defs,
            "functions": func_defs,
            "imports": imports,
            "calls": calls,
            "symbols": unique_symbols
        }

    def _scan_workspace(self) -> Dict[str, Any]:
        """Build a bounded graph without traversing generated/dependency trees."""
        graph = {
            "files": {},
            "symbol_index": {},
            "call_index": {},
            "meta": {
                "truncated": False,
                "reason": None,
                "max_files": self.max_index_files,
                "max_seconds": self.max_scan_seconds,
                "cache_saved": False,
            },
        }
        ignored_dirs = {
            ".git", ".venv", "venv", "env", ".env", ".arena", ".cache",
            ".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__",
            "node_modules", "build", "dist", "data", "coverage", "out",
            "target", "backups", "logs",
        }
        started = time.monotonic()
        indexed = 0
        stop = False

        for root, dirs, files in os.walk(self.workspace_root):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                if not file.endswith(".py"):
                    continue
                if indexed >= self.max_index_files:
                    graph["meta"].update(truncated=True, reason="file_limit")
                    stop = True
                    break
                if time.monotonic() - started >= self.max_scan_seconds:
                    graph["meta"].update(truncated=True, reason="time_limit")
                    stop = True
                    break

                file_path = Path(root) / file
                parsed = self._parse_file_ast(file_path)
                file_rel = parsed["file"]
                graph["files"][file_rel] = parsed
                indexed += 1

                for cls in parsed["classes"]:
                    graph["symbol_index"].setdefault(cls["name"], []).append({
                        "type": "class",
                        "file": file_rel,
                        "line": cls["line"],
                        "bases": cls["bases"],
                    })

                for func in parsed["functions"]:
                    graph["symbol_index"].setdefault(func["name"], []).append({
                        "type": "function",
                        "file": file_rel,
                        "line": func["line"],
                        "class_context": func["class_context"],
                    })

                for call in parsed["calls"]:
                    call_name = call["name"]
                    root_name = call_name.split(".")[-1]
                    entries = graph["call_index"].setdefault(root_name, [])
                    if not any(c["file"] == file_rel and c["line"] == call["line"] for c in entries):
                        entries.append({
                            "full_expression": call_name,
                            "file": file_rel,
                            "line": call["line"],
                        })
            if stop:
                break

        graph["meta"]["files_indexed"] = indexed
        graph["meta"]["duration_ms"] = int((time.monotonic() - started) * 1000)

        # Write through a temporary file and keep the cache only when bounded.
        self.graph_cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_cache = self.graph_cache_path.with_suffix(".json.tmp")
        try:
            with open(temp_cache, "w", encoding="utf-8") as f:
                json.dump(graph, f, separators=(",", ":"))
            cache_size = temp_cache.stat().st_size
            graph["meta"]["cache_bytes"] = cache_size
            if cache_size > self.max_cache_bytes:
                temp_cache.unlink(missing_ok=True)
                graph["meta"].update(truncated=True, reason="cache_size_limit")
                print(f"[SEMANTIC_GRAPH] Cache not saved: {cache_size} bytes exceeds limit.")
            else:
                os.replace(temp_cache, self.graph_cache_path)
                graph["meta"]["cache_saved"] = True
        except Exception as e:
            temp_cache.unlink(missing_ok=True)
            print(f"[SEMANTIC_GRAPH] Warning: Failed to save graph cache: {e}")

        return graph

    def _is_cache_stale(self, cache_mtime: float) -> bool:
        """Returns True if any tracked .py file is newer than the cache file.

        Enables automatic cache invalidation so the graph always reflects the
        current workspace (new/changed/removed source files) instead of serving
        a stale snapshot forever.
        """
        ignored_dirs = {
            ".git", ".venv", "venv", "env", ".arena", ".cache",
            ".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__",
            "node_modules", "build", "dist", "data", "coverage", "out",
            "target", "backups", "logs",
        }
        for root, dirs, files in os.walk(self.workspace_root):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                if file.endswith(".py"):
                    file_path = Path(root) / file
                    try:
                        if file_path.stat().st_mtime > cache_mtime:
                            return True
                    except OSError:
                        continue
        return False

    def _load_graph(self) -> Dict[str, Any]:
        """Loads semantic graph from local JSON cache, or rebuilds it if the
        cache is missing, corrupt, or stale relative to the source workspace."""
        if self.graph_cache_path.exists():
            try:
                cache_mtime = self.graph_cache_path.stat().st_mtime
                with open(self.graph_cache_path, "r", encoding="utf-8") as f:
                    graph = json.load(f)
                # Serve the cache only if no source file has changed since it was built.
                if not self._is_cache_stale(cache_mtime):
                    return graph
            except Exception:
                pass
        return self._scan_workspace()

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query_type = kwargs.get("query_type", "summary").lower()
        target_symbol = kwargs.get("target_symbol")
        target_path_str = kwargs.get("target_path")

        # Load or build the graph
        if query_type == "build":
            # Phase 3/Point-22: AST-scanning the whole codebase is CPU/IO heavy —
            # run it in a worker thread so it never blocks the event loop.
            graph = await asyncio.to_thread(self._scan_workspace)
            return {
                "success": True,
                "data": {
                    "message": "Semantic Code Graph refreshed successfully.",
                    "stats": {
                        "files_indexed": len(graph["files"]),
                        "unique_symbols": len(graph["symbol_index"]),
                        "unique_calls_tracked": len(graph["call_index"])
                    }
                },
                "error": None
            }

        graph = await asyncio.to_thread(self._load_graph)

        if query_type == "search":
            if not target_symbol:
                return {"success": False, "error": "target_symbol parameter is required for query_type='search'.", "data": {}}
            
            # Find definitions and calls
            definitions = graph["symbol_index"].get(target_symbol, [])
            usages = graph["call_index"].get(target_symbol, [])
            
            return {
                "success": True,
                "data": {
                    "symbol": target_symbol,
                    "definitions": definitions,
                    "usages_count": len(usages),
                    "usages": usages
                },
                "error": None
            }

        elif query_type == "callers":
            if not target_symbol:
                return {"success": False, "error": "target_symbol parameter is required for query_type='callers'.", "data": {}}
            
            usages = graph["call_index"].get(target_symbol, [])
            return {
                "success": True,
                "data": {
                    "symbol": target_symbol,
                    "callers_count": len(usages),
                    "callers": usages
                },
                "error": None
            }

        elif query_type == "dependencies":
            if not target_path_str:
                return {"success": False, "error": "target_path parameter is required for query_type='dependencies'.", "data": {}}
            
            # Find file in graph files list
            matching_file = None
            target_path = Path(target_path_str)
            
            for file_rel in graph["files"]:
                if file_rel == str(target_path) or file_rel.endswith(target_path.name) or target_path_str in file_rel:
                    matching_file = file_rel
                    break
                    
            if not matching_file:
                return {"success": False, "error": f"File '{target_path_str}' not found in the indexed semantic graph.", "data": {}}
                
            parsed = graph["files"][matching_file]
            return {
                "success": True,
                "data": {
                    "file": matching_file,
                    "imports": parsed["imports"],
                    "classes_defined": [c["name"] for c in parsed["classes"]],
                    "functions_defined": [f["name"] for f in parsed["functions"]]
                },
                "error": None
            }

        elif query_type == "summary":
            # Compute codebase statistics
            total_classes = sum(len(f["classes"]) for f in graph["files"].values())
            total_functions = sum(len(f["functions"]) for f in graph["files"].values())
            total_imports = sum(len(f["imports"]) for f in graph["files"].values())
            
            # Find top 5 most highly imported or used internal symbols
            sorted_symbols = sorted(
                [(sym, len(calls)) for sym, calls in graph["call_index"].items()],
                key=lambda x: x[1],
                reverse=True
            )[:5]
            
            return {
                "success": True,
                "data": {
                    "stats": {
                        "files_indexed": len(graph["files"]),
                        "total_classes": total_classes,
                        "total_functions": total_functions,
                        "total_imports": total_imports,
                        "unique_symbols": len(graph["symbol_index"])
                    },
                    "top_called_symbols": [{"symbol": sym, "call_count": count} for sym, count in sorted_symbols]
                },
                "error": None
            }

        else:
            return {"success": False, "error": f"Unsupported query_type '{query_type}'.", "data": {}}
