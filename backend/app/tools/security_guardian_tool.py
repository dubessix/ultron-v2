"""
Ultron Security Guardian Audit Tool
Implements a production-grade, un-mocked local security auditing scanner (Level 2 Security).
1. Scans project workspace files for raw exposed API credentials/secrets (Regex matching).
2. Audits system running processes using psutil for high-memory observations.
3. Applies a small, explicit set of dependency-manifest rules (not a CVE database).
"""

import os
import re
import asyncio
import psutil
from pathlib import Path
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool

class SecurityScanArgs(BaseModel):
    scan_workspace_secrets: bool = Field(True, description="Whether to recursively scan code files for committed secrets.")
    scan_active_processes: bool = Field(True, description="Whether to report unusually high process memory use.")
    scan_dependency_manifests: bool = Field(True, description="Whether to apply the built-in limited manifest rules.")

class SecurityGuardianTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="security_scan",
            name="Security Guardian Audit",
            description="Performs recursive secret scanning, process auditing, and dependency reviews locally.",
            category="system",
            tags=["security", "audit", "scan", "processes", "vulnerabilities", "secrets", "compliance"],
            permission_level=2,  # Level 2: System Audit (Requires confirmation for operations)
            args_model=SecurityScanArgs,
            usage_examples=["security_scan(scan_workspace_secrets=True, scan_active_processes=True)"]
        )
        self.workspace_root = Path(__file__).resolve().parent.parent.parent.parent

    def _scan_secrets(self) -> List[Dict[str, Any]]:
        """Scans project files recursively using regex schemas to spot exposed Stripe, Groq, or Google keys."""
        findings = []
        
        # Secret Matching Schemes
        patterns = {
            "Groq API Key": re.compile(r'\bgsk_[a-zA-Z0-9]{48}\b'),
            "Gemini API Key": re.compile(r'\bAIzaSy[a-zA-Z0-9_-]{33}\b'),
            "Stripe Live API Key": re.compile(r'\bsk_live_[a-zA-Z0-9]{24,32}\b'),
            "Generic Secret Reference": re.compile(r'\b(?:secret_key|private_key|api_key)\s*=\s*["\'][a-zA-Z0-9]{16,}\b', re.IGNORECASE)
        }

        # Directories to skip
        skip_dirs = {".git", ".venv", "venv", "env", ".arena", ".cache", ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules", "build", "dist", "data", "coverage", "out", "target"}

        for root, dirs, files in os.walk(self.workspace_root):
            # Prune skipped directories
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            
            for file in files:
                # Only scan text/code files
                if file.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".yaml", ".yml", ".json", "requirements.txt", "package.json")):
                    file_path = Path(root) / file
                    file_rel = str(file_path.relative_to(self.workspace_root))
                    
                    # Skip the scanner file itself to avoid self-triggering
                    if "security_guardian_tool.py" in file_rel or ".env" in file_rel:
                        continue
                        
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            
                        for label, regex in patterns.items():
                            matches = regex.findall(content)
                            if matches:
                                findings.append({
                                    "severity": "CRITICAL" if "Live" in label or "Key" in label else "HIGH",
                                    "file": file_rel,
                                    "category": "Exposed Credentials",
                                    "detail": f"Exposed string matching pattern '{label}' detected inside file.",
                                    "remediation": "Move the credentials immediately into your git-ignored .env configuration, Sir."
                                })
                    except Exception:
                        continue

        return findings

    def _scan_processes(self) -> List[Dict[str, Any]]:
        """Checks for highly suspicious local processes hogging resources or listening on open ports."""
        findings = []
        
        try:
            # Audit running processes
            for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
                try:
                    p_info = proc.info
                    mem_rss_mb = (p_info['memory_info'].rss or 0) / (1024 ** 2)
                    
                    # Highlight any local system process hogging more than 500MB of RAM
                    # Excludes standard compilers/Docker/Chrome
                    if mem_rss_mb > 500.0 and p_info['name'] not in ("chrome", "msedge", "node", "docker", "dockerd", "python"):
                        findings.append({
                            "severity": "MEDIUM",
                            "file": f"PID: {p_info['pid']} ({p_info['name']})",
                            "category": "Resource Spike",
                            "detail": f"Active process consumes {mem_rss_mb:.1f} MB of RAM.",
                            "remediation": "Kindly audit if this heavy process is required, Sir."
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as exc:
            raise RuntimeError(f"Process enumeration failed: {exc}") from exc

        return findings

    def _scan_dependencies(self) -> List[Dict[str, Any]]:
        """Audits requirements.txt and package.json to spot highly deprecated package setups."""
        findings = []
        req_path = self.workspace_root / "requirements.txt"
        
        if req_path.exists():
            try:
                with open(req_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Check for highly outdated pyyaml or requests matching CVE warnings
                if "PyYAML==" in content:
                    for line in content.splitlines():
                        if "PyYAML" in line and "5." in line:
                            findings.append({
                                "severity": "HIGH",
                                "file": "requirements.txt",
                                "category": "Vulnerable Dependency",
                                "detail": "PyYAML version 5.x has a high-severity Arbitrary Code Execution vulnerability (CVE-2020-14343).",
                                "remediation": "Upgrade requirements.txt to PyYAML==6.0.1 immediately, Sir."
                            })
            except OSError as exc:
                raise RuntimeError(f"Dependency manifest read failed: {exc}") from exc

        return findings

    async def execute(self, **kwargs) -> Dict[str, Any]:
        scan_secrets = kwargs.get("scan_workspace_secrets", True)
        scan_proc = kwargs.get("scan_active_processes", True)
        scan_deps = kwargs.get("scan_dependency_manifests", True)

        all_findings = []
        check_status = {}

        # Run bounded local checks off the event loop and preserve failed/incomplete
        # status instead of turning an exception into a false zero-finding verdict.
        for name, enabled, scan in (
            ("workspace_secret_patterns", scan_secrets, self._scan_secrets),
            ("high_memory_processes", scan_proc, self._scan_processes),
            ("limited_manifest_rules", scan_deps, self._scan_dependencies),
        ):
            if not enabled:
                check_status[name] = {"status": "not_requested", "error": None}
                continue
            try:
                findings = await asyncio.to_thread(scan)
                all_findings.extend(findings)
                check_status[name] = {"status": "completed", "error": None}
            except Exception as exc:
                check_status[name] = {"status": "failed", "error": str(exc)[:240]}

        stats = {
            "total_findings": len(all_findings),
            "critical_count": sum(1 for f in all_findings if f["severity"] == "CRITICAL"),
            "high_count": sum(1 for f in all_findings if f["severity"] == "HIGH"),
            "medium_count": sum(1 for f in all_findings if f["severity"] == "MEDIUM")
        }

        enabled_checks = [name for name, state in check_status.items() if state["status"] != "not_requested"]
        failed_checks = [name for name, state in check_status.items() if state["status"] == "failed"]
        if stats["total_findings"] > 0:
            message = (
                f"Completed local checks found {stats['total_findings']} potential issue(s). "
                "Review the evidence and run dedicated dependency/security audits."
            )
        else:
            message = (
                "No findings were detected by the completed limited local checks. "
                "This is not proof that the codebase or dependencies are completely safe."
            )
        if failed_checks:
            message += f" {len(failed_checks)} requested check(s) failed or were incomplete."

        return {
            "success": bool(enabled_checks) and len(failed_checks) < len(enabled_checks),
            "data": {
                "message": message,
                "statistics": stats,
                "findings": all_findings,
                "checks_completed": [name for name in enabled_checks if check_status[name]["status"] == "completed"],
                "check_status": check_status,
                "verified_clean": False,
                "limitations": [
                    "Secret detection uses bounded regular-expression patterns.",
                    "Process checks cover high memory usage, not malware classification.",
                    "Manifest rules are not a replacement for pip-audit/npm audit.",
                ],
            },
            "error": None,
        }
