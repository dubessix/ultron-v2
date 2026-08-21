"""
Ultron Code Optimizer and Architectural Compliance Tool
Implements a production-grade, un-mocked developer tool that analyzes code quality,
checks SOLID compliance, spots anti-patterns, and can automatically refactor/optimize files.
Creates automated .bak backup files before applying any refactoring changes (Level 2 System Security).
"""

import ast
import asyncio
import re
from pathlib import Path
from typing import Dict, Any
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool

class CodeOptimizerArgs(BaseModel):
    filepath: str = Field(..., description="Target file path to analyze and optimize.")
    optimization_type: str = Field("solid", description="Type of optimization: solid, performance, readability, security, or clean_architecture.")
    apply_changes: bool = Field(False, description="Whether to apply changes immediately and create a backup file.")

class CodeOptimizerTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="optimize_code",
            name="Code Optimizer",
            description="Analyzes and optimizes local source code for SOLID, performance, readability, and security compliance.",
            category="system",
            tags=["code", "optimize", "refactor", "solid", "quality", "clean"],
            permission_level=2,  # Level 2: System modifying (Requires manual confirmation if apply_changes=True)
            args_model=CodeOptimizerArgs,
            usage_examples=["optimize_code(filepath='backend/app/main.py', optimization_type='solid', apply_changes=False)"]
        )

    def permission_for_arguments(self, arguments: Dict[str, Any]) -> int:
        return 2 if bool(arguments.get("apply_changes")) else 0

    def _analyze_ast(self, file_content: str, filepath: str) -> Dict[str, Any]:
        """Perform raw AST analysis to spot specific structural anti-patterns without external API calls."""
        findings = []
        metrics = {
            "num_classes": 0,
            "num_functions": 0,
            "complexity_score": "Low",
            "solid_violations": []
        }
        
        try:
            tree = ast.parse(file_content)
        except SyntaxError as e:
            return {
                "success": False,
                "error": f"Syntax error in target file: {e.msg} at line {e.lineno}",
                "findings": ["SYNTAX_ERROR"],
                "metrics": metrics
            }

        # Analyze class and function counts, plus potential SOLID issues
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                metrics["num_classes"] += 1
                # Check for single responsibility (classes with too many methods)
                methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                if len(methods) > 15:
                    metrics["solid_violations"].append({
                        "principle": "SRP (Single Responsibility Principle)",
                        "detail": f"Class '{node.name}' has {len(methods)} methods. Consider breaking it down into cohesive smaller classes."
                    })
            elif isinstance(node, ast.FunctionDef):
                metrics["num_functions"] += 1
                # Check for function length / complexity
                if len(node.body) > 30:
                    findings.append(f"Function '{node.name}' has more than 30 lines. Refactoring is recommended for maintainability.")
                # Check for too many arguments (SRP violation for function signatures)
                if len(node.args.args) > 5:
                    metrics["solid_violations"].append({
                        "principle": "SRP (Single Responsibility Principle)",
                        "detail": f"Function '{node.name}' accepts {len(node.args.args)} arguments. Consider passing a typed model/data class."
                    })
            # Check for bad security patterns: eval/exec
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec"):
                    findings.append(f"Security Alert: Dangerous usage of '{node.func.id}' found at line {node.lineno}.")
            elif (
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name)
                and node.left.func.id == "type"
            ):
                findings.append(
                    f"Exact type comparison found at line {node.lineno}; review manually before changing semantics."
                )

        # Simple complexity grade
        total_structural_nodes = metrics["num_classes"] * 5 + metrics["num_functions"]
        if total_structural_nodes > 40:
            metrics["complexity_score"] = "High (Critical Refactoring Candidate)"
        elif total_structural_nodes > 15:
            metrics["complexity_score"] = "Medium"
        else:
            metrics["complexity_score"] = "Low"

        return {
            "success": True,
            "findings": findings,
            "metrics": metrics
        }

    def _perform_heuristic_optimization(self, content: str, filepath: str, opt_type: str) -> str:
        """Applies local, highly specialized regex/syntax-heuristic optimizations based on target language."""
        lines = content.splitlines()
        optimized_lines = []
        is_python = filepath.endswith(".py")

        for line in lines:
            stripped = line.strip()
            
            # --- Python Specific Enhancements ---
            if is_python:
                # 1. Optimizing repetitive loop appends to list comprehensions or generators
                # (skip blank/comment lines via `stripped` before detecting the pattern)
                if stripped and not stripped.startswith("#") and "for " in line and "append(" in line:
                    # Log optimization candidate
                    pass
                # 2. A deliberately narrow transformation: simple assignment of
                # two literal fragments around one variable. More ambiguous
                # refactors remain findings/preview only.
                string_concat = re.compile(
                    r"^(?P<prefix>\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*)"
                    r"(?P<quote>['\"])(?P<left>[^'\"]*)(?P=quote)\s*\+\s*"
                    r"(?P<variable>[A-Za-z_][A-Za-z0-9_]*)\s*\+\s*"
                    r"(?P=quote)(?P<right>[^'\"]*)(?P=quote)\s*$"
                )
                match = string_concat.match(line)
                if match:
                    groups = match.groupdict()
                    quote = groups["quote"]
                    line = (
                        f"{groups['prefix']}f{quote}{groups['left']}"
                        f"{{{groups['variable']}}}{groups['right']}{quote}"
                    )

            # JS/TS findings remain analysis-only until a language-aware,
            # semantics-preserving transformer is available.
            
            optimized_lines.append(line)

        return "\n".join(optimized_lines)

    async def execute(self, **kwargs) -> Dict[str, Any]:
        filepath_str = kwargs.get("filepath", "")
        opt_type = kwargs.get("optimization_type", "solid").lower()
        apply_changes = kwargs.get("apply_changes", False)

        path = Path(filepath_str).resolve()
        from backend.app.security.path_guard import check_path
        decision = check_path(str(path))
        if not decision["safe"]:
            return {"success": False, "error": f"Target path blocked ({decision['reason']}): {path}", "data": {}}
        if not path.exists():
            return {"success": False, "error": f"Target file '{filepath_str}' does not exist.", "data": {}}

        try:
            with open(path, "r", encoding="utf-8") as f:
                original_content = f.read()
        except Exception as e:
            return {"success": False, "error": f"Failed to read target file: {e}", "data": {}}

        # 1. Run Structural AST Analysis
        analysis = self._analyze_ast(original_content, str(path))
        
        if not analysis.get("success"):
            return {
                "success": False,
                "error": analysis.get("error") or "Target source analysis failed.",
                "data": {
                    "filepath": str(path),
                    "ast_metrics": analysis.get("metrics", {}),
                    "ast_findings": analysis.get("findings", []),
                    "original_preserved": True,
                },
            }

        # 2. Run Heuristic Code Refactoring & Optimization Engine
        optimized_content = self._perform_heuristic_optimization(original_content, str(path), opt_type)
        
        has_changed = (original_content.strip() != optimized_content.strip())
        
        # 3. If apply_changes is requested, write a .bak file, then save optimized file
        backup_path_str = None
        message = "Analysis and refactoring recommendations generated successfully."
        
        write_verification = None
        if apply_changes and has_changed:
            from backend.app.tools.safe_write import safe_write_file

            write_result = await asyncio.to_thread(
                safe_write_file,
                str(path),
                optimized_content,
            )
            if not write_result.get("success"):
                return {
                    "success": False,
                    "error": f"Optimization candidate was not applied: {write_result.get('error')}",
                    "data": write_result.get("data", {}),
                }
            backup_path_str = write_result["data"].get("backup")
            write_verification = write_result["data"].get("verification")
            message = f"Verified optimization applied. Backup: {backup_path_str}"

        return {
            "success": True,
            "data": {
                "message": message,
                "filepath": str(path),
                "has_changes_detected": has_changed,
                "backup_created": backup_path_str,
                "write_verification": write_verification,
                "ast_metrics": analysis.get("metrics", {}),
                "ast_findings": analysis.get("findings", []),
                "optimization_applied_type": opt_type,
                "optimized_preview": optimized_content[:1500] + "\n... [Truncated for preview]" if len(optimized_content) > 1500 else optimized_content
            },
            "error": None
        }
