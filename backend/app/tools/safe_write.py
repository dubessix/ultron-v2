"""Atomic, verified and rollback-safe filesystem writes."""

from __future__ import annotations

import ast
import hashlib
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

    if suffix in {".jsx", ".ts", ".tsx"}:
        executable = shutil.which("esbuild")
        if executable is None:
            local_bin = Path(__file__).resolve().parents[3] / "frontend" / "node_modules" / ".bin"
            candidates = [local_bin / "esbuild", local_bin / "esbuild.cmd"]
            executable = next((str(candidate) for candidate in candidates if candidate.is_file()), None)
        if executable is None:
            return {
                "checked": False,
                "verified": None,
                "language": suffix.lstrip("."),
                "detail": "esbuild syntax verifier unavailable",
            }
        try:
            completed = subprocess.run(
                [
                    executable,
                    str(temp_path),
                    f"--loader={suffix.lstrip('.')}",
                    "--log-level=error",
                    f"--outfile={os.devnull}",
                ],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "checked": False,
                "verified": None,
                "language": suffix.lstrip("."),
                "detail": f"syntax check failed: {exc}",
            }
        detail = (completed.stderr or completed.stdout or "syntax OK").strip()
        return {
            "checked": True,
            "verified": completed.returncode == 0,
            "language": suffix.lstrip("."),
            "detail": detail[:1000],
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
            return {"checked": False, "verified": None, "language": "javascript", "detail": "node unavailable"}
        except subprocess.TimeoutExpired:
            return {"checked": False, "verified": None, "language": "javascript", "detail": "syntax check timed out"}
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


BACKUPS_KEPT = 40


def _backup_path_for(path: Path) -> Path:
    """A timestamped copy in Ultron's own data folder (never clutters the owner's folders)."""
    import time
    import uuid

    from backend.app.runtime_paths import runtime_data_path

    folder = runtime_data_path("file_backups")
    _prune_backups(folder)
    return folder / f"{time.strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:6]}_{path.name}"


def _prune_backups(folder: Path) -> None:
    try:
        files = sorted((f for f in folder.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[BACKUPS_KEPT - 1:]:
        try:
            old.unlink()
        except OSError:
            pass


def safe_write_file(
    filepath: str,
    content: str,
    expected_sha256: str | None = None,
) -> Dict[str, Any]:
    """Verify a candidate and optional inspection fingerprint before atomic replace."""
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

    if expected_sha256 is not None:
        current_sha256 = hashlib.sha256((old_content or "").encode("utf-8")).hexdigest()
        if not exists or current_sha256.lower() != str(expected_sha256).lower():
            return {
                "success": False,
                "error": "File changed since inspection; read it again before writing.",
                "data": {
                    "original_preserved": True,
                    "current_sha256": current_sha256 if exists else None,
                },
            }

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=f".tmp{path.suffix}",
    )
    temp_path = Path(temp_name)
    backup_path = _backup_path_for(path) if exists else None

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        verification = _verify_candidate(path, temp_path, content)
        # Refuse only a REAL syntax error; a missing checker never blocks the owner's job.
        if verification["checked"] and verification["verified"] is False:
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
            backup_path.parent.mkdir(parents=True, exist_ok=True)
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

    try:
        from backend.app.core import action_journal

        if exists:
            action_journal.record("edit", f"edited {path.name}", path=str(path), backup=str(backup_path))
        else:
            action_journal.record("create", f"created {path.name}", path=str(path))
    except Exception:
        pass  # the write itself succeeded; undo history is best effort

    old_lines = len((old_content or "").splitlines()) if exists else 0
    new_lines = len(content.splitlines())
    action = "updated" if exists else "created"
    return {
        "success": True,
        "data": {
            "message": (
                f"Updated file: {filepath} (undo possible)"
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
