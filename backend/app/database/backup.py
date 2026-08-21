"""Verified SQLite backup, retention, integrity, checkpoint, and safe restore."""

from __future__ import annotations

import datetime
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from backend.app.database import db as _db

_CORE_TABLES = (
    "sessions",
    "conversations",
    "vector_memories",
    "reminders_alarms",
    "project_tasks",
    "calendar_events",
    "tool_audit_logs",
)
_CORE_TABLE_COUNT_QUERIES = {
    table: query for table, query in (
        ("sessions", "SELECT COUNT(*) FROM sessions;"),
        ("conversations", "SELECT COUNT(*) FROM conversations;"),
        ("vector_memories", "SELECT COUNT(*) FROM vector_memories;"),
        ("reminders_alarms", "SELECT COUNT(*) FROM reminders_alarms;"),
        ("project_tasks", "SELECT COUNT(*) FROM project_tasks;"),
        ("calendar_events", "SELECT COUNT(*) FROM calendar_events;"),
        ("tool_audit_logs", "SELECT COUNT(*) FROM tool_audit_logs;"),
    )
}
_REQUIRED_RESTORE_TABLES = {
    "sessions",
    "conversations",
    "reminders_alarms",
    "project_tasks",
    "calendar_events",
}


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def get_approved_backup_root() -> Path:
    """Return the only tree accepted as a database restore source."""
    return (_db.DB_DIR / "backups").resolve(strict=False)


def _fsync_file(path: Path) -> None:
    # Windows requires a writable file descriptor for FlushFileBuffers/fsync.
    # These are newly-created app-owned backup/restore files, so r+b is valid.
    with open(path, "r+b") as handle:
        os.fsync(handle.fileno())


def _verify_connection(conn: sqlite3.Connection) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "valid": False,
        "integrity": [],
        "tables": {},
        "schema_version": 0,
        "missing_required_tables": [],
        "error": None,
    }
    try:
        rows = conn.execute("PRAGMA integrity_check;").fetchall()
        report["integrity"] = [row[0] for row in rows]
        integrity_valid = bool(rows) and all(row[0] == "ok" for row in rows)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            ).fetchall()
        }
        missing = sorted(_REQUIRED_RESTORE_TABLES - tables)
        report["missing_required_tables"] = missing
        report["schema_version"] = int(conn.execute("PRAGMA user_version;").fetchone()[0])
        report["valid"] = integrity_valid and not missing
        if integrity_valid and missing:
            report["error"] = "missing required tables: " + ", ".join(missing)
        for table in _CORE_TABLES:
            if table in tables:
                report["tables"][table] = conn.execute(
                    _CORE_TABLE_COUNT_QUERIES[table]
                ).fetchone()[0]
    except sqlite3.Error as exc:
        report["error"] = str(exc)
        report["valid"] = False
    return report


def verify_db_file(path: Path) -> Dict[str, Any]:
    """Read-only integrity verification for a standalone SQLite file."""
    path = Path(path)
    report: Dict[str, Any] = {
        "valid": False,
        "integrity": [],
        "tables": {},
        "schema_version": 0,
        "missing_required_tables": sorted(_REQUIRED_RESTORE_TABLES),
        "error": None,
    }
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        report["error"] = f"file missing or inaccessible: {exc}"
        return report
    try:
        if not resolved.is_file() or resolved.stat().st_size == 0:
            report["error"] = "file missing or empty"
            return report
        uri = f"file:{resolved.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=15.0)
        try:
            return _verify_connection(conn)
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as exc:
        report["error"] = str(exc)
        return report


def prune_backups(
    dest_dir: Optional[Path] = None,
    generations: int = 30,
) -> Dict[str, Any]:
    """Keep only the newest verified-backup generations in the backup root."""
    root = Path(dest_dir or get_approved_backup_root()).resolve(strict=False)
    keep = max(1, min(int(generations), 365))
    if not root.exists():
        return {"success": True, "removed": 0, "kept": 0, "errors": []}
    candidates = sorted(
        (
            path for path in root.glob("ultron_*.db")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    removed = 0
    errors = []
    for path in candidates[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
    return {
        "success": not errors,
        "removed": removed,
        "kept": min(len(candidates), keep),
        "errors": errors,
    }


def backup_database(
    dest_dir: Optional[Path] = None,
    retention_generations: Optional[int] = None,
) -> Dict[str, Any]:
    """Create and verify an atomic backup using SQLite's online backup API."""
    root = Path(dest_dir or get_approved_backup_root()).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    backup_path = root / f"ultron_{_timestamp()}.db"
    temp_path = root / f".{backup_path.name}.{os.getpid()}.tmp"

    try:
        # The online backup API takes a transactionally consistent snapshot even
        # while short-lived WAL readers/writers are active.
        with _db.get_db_connection() as source:
            destination = sqlite3.connect(str(temp_path), timeout=15.0)
            try:
                source.backup(destination, pages=256, sleep=0.01)
                destination.commit()
            finally:
                destination.close()
        _fsync_file(temp_path)
        report = verify_db_file(temp_path)
        if not report["valid"]:
            temp_path.unlink(missing_ok=True)
            return {
                "success": False,
                "error": (
                    "Backup verification failed: "
                    f"{report['error'] or report['integrity']}"
                ),
                "data": {"verification": report},
            }
        os.replace(temp_path, backup_path)
        _fsync_file(backup_path)
    except (_db.DatabaseMaintenanceError, OSError, sqlite3.Error) as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"success": False, "error": f"Backup failed: {exc}", "data": {}}

    retention = None
    if retention_generations is not None:
        retention = prune_backups(root, retention_generations)
    return {
        "success": True,
        "data": {
            "backup_path": str(backup_path),
            "bytes": backup_path.stat().st_size,
            "verification": report,
            "retention": retention,
        },
        "error": None,
    }


def _resolve_restore_source(backup_path: str) -> tuple[Optional[Path], Optional[str]]:
    root = get_approved_backup_root()
    try:
        source = Path(backup_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"Backup source is missing or inaccessible: {exc}"
    try:
        source.relative_to(root)
    except ValueError:
        return None, f"Restore source must be inside the approved backup directory: {root}"
    if not source.is_file() or source.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        return None, "Restore source must be a SQLite backup file."
    return source, None


def _remove_live_sidecars() -> None:
    for suffix in ("-wal", "-shm"):
        try:
            Path(str(_db.DB_PATH) + suffix).unlink(missing_ok=True)
        except OSError:
            # The following integrity check catches any unsafe replacement state.
            pass


def _checkpoint_live_exclusive() -> None:
    if not _db.DB_PATH.exists():
        return
    conn = sqlite3.connect(str(_db.DB_PATH), timeout=15.0)
    try:
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
        if row and int(row[0]) != 0:
            raise sqlite3.OperationalError(f"WAL checkpoint remained busy: {tuple(row)}")
    finally:
        conn.close()


def _atomic_replace_database(source: Path) -> Dict[str, Any]:
    temp = _db.DB_DIR / f".{_db.DB_PATH.name}.restore.{os.getpid()}.tmp"
    try:
        shutil.copy2(str(source), str(temp))
        _fsync_file(temp)
        copied = verify_db_file(temp)
        if not copied["valid"]:
            raise OSError(
                "temporary restore copy failed verification: "
                f"{copied['error'] or copied['integrity']}"
            )
        _remove_live_sidecars()
        os.replace(temp, _db.DB_PATH)
        _fsync_file(_db.DB_PATH)
        return copied
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def restore_database(
    backup_path: str,
    maintenance_timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    """Restore an approved backup under an exclusive lock with auto-rollback."""
    source, source_error = _resolve_restore_source(backup_path)
    if source is None:
        return {"success": False, "error": source_error, "data": {}}

    source_report = verify_db_file(source)
    if not source_report["valid"]:
        return {
            "success": False,
            "error": (
                "Refusing to restore: backup is not a valid database "
                f"({source_report['error'] or source_report['integrity']})"
            ),
            "data": {"verification": source_report},
        }

    safety: Optional[Path] = None
    try:
        with _db.maintenance_coordinator.maintenance(
            reason="database restore",
            timeout_seconds=maintenance_timeout_seconds,
        ):
            replacement_attempted = False
            try:
                _db.DB_DIR.mkdir(parents=True, exist_ok=True)
                _checkpoint_live_exclusive()

                if _db.DB_PATH.exists():
                    safety_dir = get_approved_backup_root() / "safety"
                    safety_dir.mkdir(parents=True, exist_ok=True)
                    safety = safety_dir / f"ultron_pre_restore_{_timestamp()}.db"
                    shutil.copy2(str(_db.DB_PATH), str(safety))
                    _fsync_file(safety)
                    safety_report = verify_db_file(safety)
                    if not safety_report["valid"]:
                        safety.unlink(missing_ok=True)
                        return {
                            "success": False,
                            "error": "Failed to create a verified pre-restore safety copy.",
                            "data": {"verification": safety_report},
                        }

                # Mark before entering the helper: if a post-replace fsync raises,
                # the verified safety copy must still be restored.
                replacement_attempted = True
                _atomic_replace_database(source)
                post = verify_db_file(_db.DB_PATH)
                if post["valid"]:
                    return {
                        "success": True,
                        "data": {
                            "restored_from": str(source),
                            "safety_backup": str(safety) if safety else None,
                            "verification": post,
                            "rollback_restored": False,
                        },
                        "error": None,
                    }

                rollback_report = None
                rollback_restored = False
                if safety is not None:
                    _atomic_replace_database(safety)
                    rollback_report = verify_db_file(_db.DB_PATH)
                    rollback_restored = bool(rollback_report["valid"])
                return {
                    "success": False,
                    "error": (
                        "Restored database failed integrity verification; "
                        + (
                            "the pre-restore safety copy was restored automatically."
                            if rollback_restored
                            else "automatic safety rollback also failed. Stop using the database."
                        )
                    ),
                    "data": {
                        "safety_backup": str(safety) if safety else None,
                        "verification": post,
                        "rollback_restored": rollback_restored,
                        "rollback_verification": rollback_report,
                    },
                }
            except Exception as exc:
                rollback_report = None
                rollback_restored = False
                if replacement_attempted and safety is not None:
                    try:
                        _atomic_replace_database(safety)
                        rollback_report = verify_db_file(_db.DB_PATH)
                        rollback_restored = bool(rollback_report["valid"])
                    except Exception as rollback_exc:
                        rollback_report = {"valid": False, "error": str(rollback_exc)}
                return {
                    "success": False,
                    "error": f"Restore failed safely: {exc}",
                    "data": {
                        "safety_backup": str(safety) if safety else None,
                        "rollback_restored": rollback_restored,
                        "rollback_verification": rollback_report,
                    },
                }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Could not enter database maintenance mode: {exc}",
            "data": {},
        }


def checkpoint_wal() -> Dict[str, Any]:
    """Run one centralized non-destructive WAL checkpoint during normal operation."""
    try:
        with _db.get_db_connection() as conn:
            row = conn.execute("PRAGMA wal_checkpoint(PASSIVE);").fetchone()
        values = tuple(row) if row else ()
        return {
            "success": bool(row is not None and int(row[0]) == 0),
            "data": {"checkpoint": values},
            "error": None if row is not None and int(row[0]) == 0 else f"Checkpoint busy: {values}",
        }
    except Exception as exc:
        return {"success": False, "data": {}, "error": str(exc)}


def check_integrity() -> Dict[str, Any]:
    """Report live DB integrity while participating in the maintenance gate."""
    try:
        with _db.get_db_connection() as conn:
            report = _verify_connection(conn)
        return {
            "success": bool(report["valid"]),
            "data": report,
            "error": None if report["valid"] else report["error"] or str(report["integrity"]),
        }
    except Exception as exc:
        return {
            "success": False,
            "data": {"valid": False, "integrity": [], "tables": {}, "error": str(exc)},
            "error": str(exc),
        }
