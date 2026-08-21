"""Atomic, verified and rollback-safe filesystem writes."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict


def _verify_candidate(path: Path, temp_path: Path, content: str) -> Dict[str, Any]:
    """Verify syntax without executing user code."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        try:
            ast.parse(content, filename=str(path))
            return {"checked": True, "verified": True, "language": "python", "detail": "syntax OK"}
        except SyntaxError as exc:
            return {
                "checked": True,
                "verified": False,
                "language": "python",
                "detail": f"{exc.msg} at line {exc.lineno}",
            }

    if suffix in {".js", ".mjs", ".cjs"}:
        try:
            completed = subprocess.run(
                ["node", "--check", str(temp_path)],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except FileNotFoundError:
            return {"checked": False, "verified": False, "language": "javascript", "detail": "node unavailable"}
        except subprocess.TimeoutExpired:
            return {"checked": True, "verified": False, "language": "javascript", "detail": "syntax check timed out"}
        detail = (completed.stderr or completed.stdout or "syntax OK").strip()
        return {
            "checked": True,
            "verified": completed.returncode == 0,
            "language": "javascript",
            "detail": detail[:1000],
        }

    return {
        "checked": False,
        "verified": None,
        "language": None,
        "detail": "no non-executing syntax verifier for this file type",
    }


def safe_write_file(filepath: str, content: str) -> Dict[str, Any]:
    """Verify a temporary candidate, back up the original, then replace atomically."""
    if not filepath or not str(filepath).strip():
        return {"success": False, "error": "filepath required", "data": {}}

    from backend.app.security.path_guard import check_path

    path = Path(filepath).expanduser().resolve(strict=False)
    decision = check_path(str(path))
    if not decision["safe"]:
        return {
            "success": False,
            "error": f"Blocked by path guard ({decision['reason']}): {filepath}",
            "data": {},
        }

    exists = path.exists()
    old_content = None
    if exists:
        try:
            old_content = path.read_text(encoding="utf-8")
        except Exception as exc:
            return {
                "success": False,
                "error": f"Failed to read existing file for backup: {exc}",
                "data": {},
            }

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=f".tmp{path.suffix}",
    )
    temp_path = Path(temp_name)
    backup_path = path.with_suffix(path.suffix + ".bak") if exists else None

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        verification = _verify_candidate(path, temp_path, content)
        if verification["checked"] and not verification["verified"]:
            return {
                "success": False,
                "error": f"Candidate verification failed: {verification['detail']}",
                "data": {
                    "file": str(path),
                    "verification": verification,
                    "original_preserved": True,
                },
            }

        if exists and backup_path is not None:
            backup_decision = check_path(str(backup_path))
            if not backup_decision["safe"]:
                return {
                    "success": False,
                    "error": f"Backup path blocked ({backup_decision['reason']}): {backup_path}",
                    "data": {"original_preserved": True},
                }
            backup_path.write_text(old_content or "", encoding="utf-8")

        os.replace(temp_path, path)
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to write file safely: {exc}",
            "data": {"original_preserved": True},
        }
    finally:
        temp_path.unlink(missing_ok=True)

    old_lines = len((old_content or "").splitlines()) if exists else 0
    new_lines = len(content.splitlines())
    action = "updated" if exists else "created"
    return {
        "success": True,
        "data": {
            "message": (
                f"Overwrote file: {filepath} (backup: {backup_path})"
                if exists else f"Created file: {filepath}"
            ),
            "file": filepath,
            "backup": str(backup_path) if backup_path else None,
            "verification": verification,
            "diff": {
                "action": action,
                "file": filepath,
                "old_lines": old_lines,
                "new_lines": new_lines,
                "net_lines_change": new_lines - old_lines,
                "backup": str(backup_path) if backup_path else None,
            },
        },
        "error": None,
    }


def restore_write_backup(filepath: str, backup_path: str | None) -> Dict[str, Any]:
    """Restore a verified write backup or remove a newly-created file."""
    target = Path(filepath).expanduser().resolve(strict=False)
    try:
        if backup_path:
            source = Path(backup_path).expanduser().resolve(strict=False)
            if not source.exists():
                return {"success": False, "error": f"Backup missing: {source}"}
            shutil.copy2(source, target)
            return {"success": True, "action": "restored_backup", "path": str(target)}
        target.unlink(missing_ok=True)
        return {"success": True, "action": "removed_new_file", "path": str(target)}
    except OSError as exc:
        return {"success": False, "error": f"Rollback failed: {exc}"}
