"""Configured automatic database maintenance for long-running personal use."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from backend.app.database import db as _db
from backend.app.database.backup import (
    backup_database,
    check_integrity,
    checkpoint_wal,
    get_approved_backup_root,
    prune_backups,
)
from backend.app.install_paths import CONFIG_PATH
from backend.app.runtime_paths import runtime_data_path


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _bounded_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


@dataclass(frozen=True)
class DurabilitySettings:
    automatic_backups: bool = True
    backup_interval_hours: float = 24.0
    backup_generations: int = 30
    integrity_check_interval_hours: float = 24.0
    wal_checkpoint_interval_hours: float = 6.0
    audit_retention_days: int = 90
    cache_retention_days: int = 7
    log_retention_days: int = 30
    scheduler_poll_seconds: float = 900.0
    restore_lock_timeout_seconds: float = 30.0


def load_durability_settings() -> DurabilitySettings:
    """Load conservative, bounded durability settings; malformed config fails safe."""
    raw: Dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                raw = (yaml.safe_load(handle) or {}).get("durability", {}) or {}
        except (OSError, yaml.YAMLError, AttributeError):
            raw = {}
    return DurabilitySettings(
        automatic_backups=bool(raw.get("automatic_backups", True)),
        backup_interval_hours=_bounded_float(
            raw.get("backup_interval_hours"), 24.0, 1.0, 168.0
        ),
        backup_generations=_bounded_int(
            raw.get("backup_generations"), 30, 2, 365
        ),
        integrity_check_interval_hours=_bounded_float(
            raw.get("integrity_check_interval_hours"), 24.0, 1.0, 168.0
        ),
        wal_checkpoint_interval_hours=_bounded_float(
            raw.get("wal_checkpoint_interval_hours"), 6.0, 1.0, 168.0
        ),
        audit_retention_days=_bounded_int(
            raw.get("audit_retention_days"), 90, 7, 3650
        ),
        cache_retention_days=_bounded_int(
            raw.get("cache_retention_days"), 7, 1, 365
        ),
        log_retention_days=_bounded_int(
            raw.get("log_retention_days"), 30, 7, 3650
        ),
        scheduler_poll_seconds=_bounded_float(
            raw.get("scheduler_poll_seconds"), 900.0, 60.0, 3600.0
        ),
        restore_lock_timeout_seconds=_bounded_float(
            raw.get("restore_lock_timeout_seconds"), 30.0, 5.0, 120.0
        ),
    )


def _latest_backup_mtime() -> Optional[float]:
    root = get_approved_backup_root()
    if not root.exists():
        return None
    mtimes = [
        path.stat().st_mtime
        for path in root.glob("ultron_*.db")
        if path.is_file() and not path.is_symlink()
    ]
    return max(mtimes) if mtimes else None


def _prune_old_files(root: Path, retention_days: int, now: Optional[float] = None) -> dict:
    """Delete only stale regular files below one generated-data tree."""
    if not root.exists():
        return {"success": True, "removed": 0, "errors": []}
    cutoff = (time.time() if now is None else float(now)) - retention_days * 86400
    removed = 0
    errors = []
    for path in root.rglob("*"):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return {"success": not errors, "removed": removed, "errors": errors}


def prune_audit_logs(retention_days: int) -> dict:
    """Bound tool audit growth without deleting chat, reminder, or memory data."""
    try:
        with _db.get_db_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_audit_logs';"
            ).fetchone()
            if not exists:
                return {"success": True, "removed": 0, "error": None}
            cursor = conn.execute(
                "DELETE FROM tool_audit_logs "
                "WHERE timestamp < datetime('now', ?);",
                (f"-{int(retention_days)} days",),
            )
            conn.commit()
            return {"success": True, "removed": max(0, cursor.rowcount), "error": None}
    except Exception as exc:
        return {"success": False, "removed": 0, "error": str(exc)}


class DurabilityScheduler:
    """One low-frequency loop for backup, integrity, WAL, and retention work."""

    def __init__(self, settings: Optional[DurabilitySettings] = None) -> None:
        self.settings = settings or load_durability_settings()
        self._last_integrity = 0.0
        self._last_checkpoint = 0.0
        self._last_retention = 0.0
        self.last_result: Dict[str, Any] = {}

    def run_once(self, force: bool = False) -> Dict[str, Any]:
        now_wall = time.time()
        now_mono = time.monotonic()
        result: Dict[str, Any] = {
            "backup": {"status": "not_due"},
            "integrity": {"status": "not_due"},
            "wal_checkpoint": {"status": "not_due"},
            "retention": {"status": "not_due"},
        }

        latest = _latest_backup_mtime()
        backup_due = force or latest is None or (
            now_wall - latest >= self.settings.backup_interval_hours * 3600
        )
        if self.settings.automatic_backups and backup_due:
            result["backup"] = backup_database(
                retention_generations=self.settings.backup_generations
            )
        elif not self.settings.automatic_backups:
            result["backup"] = {"status": "disabled"}

        if force or (
            now_mono - self._last_integrity
            >= self.settings.integrity_check_interval_hours * 3600
        ):
            result["integrity"] = check_integrity()
            self._last_integrity = now_mono

        if force or (
            now_mono - self._last_checkpoint
            >= self.settings.wal_checkpoint_interval_hours * 3600
        ):
            result["wal_checkpoint"] = checkpoint_wal()
            self._last_checkpoint = now_mono

        if force or now_mono - self._last_retention >= 86400:
            result["retention"] = {
                "backups": prune_backups(
                    generations=self.settings.backup_generations
                ),
                "audit": prune_audit_logs(self.settings.audit_retention_days),
                "cache_files": _prune_old_files(
                    runtime_data_path("cache"), self.settings.cache_retention_days, now_wall
                ),
                "log_files": _prune_old_files(
                    runtime_data_path("logs"), self.settings.log_retention_days, now_wall
                ),
            }
            self._last_retention = now_mono

        self.last_result = result
        return result

    async def run_forever(self) -> None:
        print("[DURABILITY] Automatic backup/integrity scheduler started.")
        while True:
            try:
                await asyncio.to_thread(self.run_once)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # One failed maintenance pass must not kill future daily backups.
                print(f"[DURABILITY] Maintenance pass failed: {exc}")
            await asyncio.sleep(self.settings.scheduler_poll_seconds)


async def run_durability_scheduler() -> None:
    await DurabilityScheduler().run_forever()
