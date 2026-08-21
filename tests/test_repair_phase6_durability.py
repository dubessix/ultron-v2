"""Phase 6 regressions: automatic durability, locked restore, and task lifecycle."""

from __future__ import annotations

import asyncio
import os
from contextlib import closing
import shutil
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from backend.app.background_tasks import BackgroundTaskManager
from backend.app.database import db as _db
from backend.app.database.backup import backup_database, restore_database
from backend.app.database.durability import DurabilityScheduler, DurabilitySettings
from backend.app.database.models import initialize_database
from backend.app.router import (
    BackupRequest,
    ConfirmActionRequest,
    confirm_pending_action,
    restore_db,
)
from backend.app.runtime_paths import TEST_ROOT, runtime_data_path
from backend.app.security.pending_actions import get_pending_action_registry


def _insert_conversation(label: str) -> None:
    with _db.get_db_connection() as conn:
        session_id = "phase6-session"
        conn.execute(
            "INSERT OR IGNORE INTO sessions "
            "(id, current_goal, current_mode, personality) VALUES (?, ?, ?, ?);",
            (session_id, "durability", "developer", "ultron"),
        )
        conn.execute(
            "INSERT INTO conversations "
            "(id, session_id, user_message, ai_response, personality, tools_used, "
            "intent, mode, path_used, response_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                str(uuid.uuid4()),
                session_id,
                label,
                f"reply-{label}",
                "ultron",
                "[]",
                "Conversation",
                "developer",
                "fast",
                1,
            ),
        )
        conn.commit()


def _conversation_labels() -> list[str]:
    with _db.get_db_connection() as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT user_message FROM conversations ORDER BY rowid ASC;"
            ).fetchall()
        ]


class Phase6DatabaseCase(unittest.TestCase):
    def setUp(self) -> None:
        parent = str(TEST_ROOT) if TEST_ROOT is not None else None
        self.temp_dir = Path(tempfile.mkdtemp(prefix="phase6_db_", dir=parent))
        self.original_db_path = _db.DB_PATH
        self.original_db_dir = _db.DB_DIR
        _db.DB_DIR = self.temp_dir
        _db.DB_PATH = self.temp_dir / "ultron.db"
        get_pending_action_registry().clear()
        with _db.get_db_connection() as conn:
            initialize_database(conn)

    def tearDown(self) -> None:
        get_pending_action_registry().clear()
        _db.DB_PATH = self.original_db_path
        _db.DB_DIR = self.original_db_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_restore_rejects_valid_database_outside_approved_backup_tree(self):
        _insert_conversation("protected")
        made = backup_database()
        self.assertTrue(made["success"])
        outside = self.temp_dir.parent / f"outside_{uuid.uuid4().hex}.db"
        shutil.copy2(made["data"]["backup_path"], outside)
        try:
            result = restore_database(str(outside))
        finally:
            outside.unlink(missing_ok=True)
        self.assertFalse(result["success"])
        self.assertIn("approved backup directory", result["error"])
        self.assertEqual(_conversation_labels(), ["protected"])

    def test_restore_rejects_integrity_ok_database_with_wrong_schema(self):
        import sqlite3

        wrong = self.temp_dir / "backups" / "unrelated.db"
        wrong.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(wrong))) as conn:
            conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY);")
            conn.commit()
        result = restore_database(str(wrong))
        self.assertFalse(result["success"])
        self.assertIn("missing required tables", result["error"])

    def test_maintenance_gate_blocks_new_database_connections(self):
        with _db.maintenance_coordinator.maintenance("phase6 test", timeout_seconds=1):
            status = _db.maintenance_coordinator.status()
            self.assertTrue(status["maintenance_active"])
            with self.assertRaises(_db.DatabaseMaintenanceError):
                with _db.get_db_connection():
                    pass
            backup_result = backup_database()
            self.assertFalse(backup_result["success"])
            self.assertIn("maintenance", backup_result["error"].lower())
        self.assertFalse(_db.maintenance_coordinator.status()["maintenance_active"])

    def test_new_write_tool_is_rejected_during_restore_maintenance(self):
        from pydantic import BaseModel
        from backend.app.tools.tool_base import BaseTool
        from backend.app.tools.tool_registry import ToolRegistry

        executed = False

        class NoArgs(BaseModel):
            pass

        class WriteProbe(BaseTool):
            def __init__(self):
                super().__init__(
                    tool_id="phase6_write_probe",
                    name="Phase 6 Write Probe",
                    description="Regression-only write probe.",
                    category="test",
                    tags=["test"],
                    permission_level=1,
                    args_model=NoArgs,
                    usage_examples=[],
                )

            async def execute(self, **kwargs):
                nonlocal executed
                executed = True
                return {"success": True, "data": {}, "error": None}

        registry = ToolRegistry()
        registry.register(WriteProbe())
        with _db.maintenance_coordinator.maintenance("restore test", timeout_seconds=1):
            result = asyncio.run(
                registry.execute_tool("phase6_write_probe", {}, session_id="phase6")
            )
        self.assertFalse(result["success"])
        self.assertIn("DatabaseMaintenance", result["error"])
        self.assertFalse(executed)

    def test_maintenance_timeout_clears_gate_after_live_connection_does_not_drain(self):
        entered = threading.Event()
        release = threading.Event()

        def hold_connection():
            with _db.get_db_connection():
                entered.set()
                release.wait(timeout=2)

        thread = threading.Thread(target=hold_connection, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(timeout=1))
        try:
            with self.assertRaises(_db.DatabaseMaintenanceTimeoutError):
                with _db.maintenance_coordinator.maintenance(
                    "timeout test", timeout_seconds=0.05
                ):
                    pass
        finally:
            release.set()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(_db.maintenance_coordinator.status()["maintenance_active"])

    def test_restore_endpoint_requires_exact_one_time_confirmation(self):
        _insert_conversation("backup-a")
        _insert_conversation("backup-b")
        made = backup_database()
        self.assertTrue(made["success"])
        backup_path = made["data"]["backup_path"]
        with _db.get_db_connection() as conn:
            conn.execute("DELETE FROM conversations;")
            conn.commit()

        pending = asyncio.run(
            restore_db(
                BackupRequest(
                    backup_path=backup_path,
                    session_id="restore-owner",
                )
            )
        )
        self.assertEqual(pending["status"], "PENDING_CONFIRMATION")
        self.assertFalse(pending["success"])
        self.assertEqual(_conversation_labels(), [])

        confirmed = asyncio.run(
            confirm_pending_action(
                ConfirmActionRequest(
                    confirmation_token=pending["confirmation_token"],
                    session_id="restore-owner",
                )
            )
        )
        self.assertTrue(confirmed["success"], confirmed)
        self.assertEqual(_conversation_labels(), ["backup-a", "backup-b"])

        replay = asyncio.run(
            confirm_pending_action(
                ConfirmActionRequest(
                    confirmation_token=pending["confirmation_token"],
                    session_id="restore-owner",
                )
            )
        )
        self.assertFalse(replay["success"])
        self.assertEqual(replay["status"], "CONFIRMATION_REJECTED")

    def test_failed_post_restore_integrity_automatically_rolls_back(self):
        _insert_conversation("backup-content")
        made = backup_database()
        self.assertTrue(made["success"])
        backup_path = made["data"]["backup_path"]

        with _db.get_db_connection() as conn:
            conn.execute("DELETE FROM conversations;")
            conn.commit()
        _insert_conversation("current-content")

        from backend.app.database import backup as backup_module

        original_verify = backup_module.verify_db_file
        failed_live_check = False

        def fail_first_live_post_check(path):
            nonlocal failed_live_check
            candidate = Path(path).resolve(strict=False)
            if candidate == _db.DB_PATH.resolve(strict=False) and not failed_live_check:
                failed_live_check = True
                return {
                    "valid": False,
                    "integrity": ["forced post-restore failure"],
                    "tables": {},
                    "error": "forced post-restore failure",
                }
            return original_verify(path)

        with mock.patch.object(
            backup_module, "verify_db_file", side_effect=fail_first_live_post_check
        ):
            restored = restore_database(backup_path)

        self.assertFalse(restored["success"])
        self.assertTrue(restored["data"]["rollback_restored"], restored)
        self.assertEqual(_conversation_labels(), ["current-content"])

    def test_automatic_scheduler_creates_missing_daily_backup_but_not_a_duplicate(self):
        _insert_conversation("first-daily-backup")
        settings = DurabilitySettings(
            automatic_backups=True,
            backup_interval_hours=24,
            backup_generations=3,
            integrity_check_interval_hours=24,
            wal_checkpoint_interval_hours=6,
            audit_retention_days=90,
            cache_retention_days=7,
            log_retention_days=30,
            scheduler_poll_seconds=60,
            restore_lock_timeout_seconds=30,
        )
        first = DurabilityScheduler(settings).run_once()
        self.assertTrue(first["backup"]["success"], first)
        self.assertEqual(len(list((self.temp_dir / "backups").glob("ultron_*.db"))), 1)

        # Simulate an application restart: the on-disk backup timestamp, rather
        # than only in-memory state, prevents another backup before 24 hours.
        second = DurabilityScheduler(settings).run_once()
        self.assertEqual(second["backup"]["status"], "not_due")
        self.assertEqual(len(list((self.temp_dir / "backups").glob("ultron_*.db"))), 1)

    def test_automatic_cycle_creates_backup_prunes_generations_and_old_audit_files(self):
        _insert_conversation("daily-data")
        for index in range(3):
            made = backup_database()
            self.assertTrue(made["success"])
            old = time.time() - (300 - index)
            os.utime(made["data"]["backup_path"], (old, old))

        with _db.get_db_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_audit_logs (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    tool_name TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    success BOOLEAN NOT NULL,
                    session_id TEXT,
                    permission_level INTEGER NOT NULL,
                    error TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO tool_audit_logs "
                "(id, timestamp, tool_name, arguments, duration_ms, success, permission_level) "
                "VALUES (?, datetime('now', '-400 days'), ?, ?, ?, ?, ?);",
                (str(uuid.uuid4()), "old", "{}", 1, 1, 0),
            )
            conn.commit()

        unique = uuid.uuid4().hex
        old_cache = runtime_data_path("cache", f"phase6_{unique}.tmp")
        old_log = runtime_data_path("logs", f"phase6_{unique}.log")
        old_cache.parent.mkdir(parents=True, exist_ok=True)
        old_log.parent.mkdir(parents=True, exist_ok=True)
        old_cache.write_text("old cache", encoding="utf-8")
        old_log.write_text("old log", encoding="utf-8")
        old_time = time.time() - 400 * 86400
        os.utime(old_cache, (old_time, old_time))
        os.utime(old_log, (old_time, old_time))

        settings = DurabilitySettings(
            automatic_backups=True,
            backup_interval_hours=24,
            backup_generations=2,
            integrity_check_interval_hours=24,
            wal_checkpoint_interval_hours=6,
            audit_retention_days=90,
            cache_retention_days=7,
            log_retention_days=30,
            scheduler_poll_seconds=60,
            restore_lock_timeout_seconds=30,
        )
        result = DurabilityScheduler(settings).run_once(force=True)

        self.assertTrue(result["backup"]["success"], result)
        self.assertTrue(result["integrity"]["success"], result)
        self.assertTrue(result["wal_checkpoint"]["success"], result)
        backups = list((self.temp_dir / "backups").glob("ultron_*.db"))
        self.assertEqual(len(backups), 2)
        self.assertFalse(old_cache.exists())
        self.assertFalse(old_log.exists())
        with _db.get_db_connection() as conn:
            old_audits = conn.execute(
                "SELECT COUNT(*) FROM tool_audit_logs WHERE tool_name = 'old';"
            ).fetchone()[0]
        self.assertEqual(old_audits, 0)


class TestPhase6BackgroundTasks(unittest.TestCase):
    def test_singleton_prevents_duplicates_and_shutdown_cancels_all(self):
        async def scenario():
            manager = BackgroundTaskManager()
            factory_calls = 0
            started = asyncio.Event()
            cancelled = asyncio.Event()

            async def worker():
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

            def factory():
                nonlocal factory_calls
                factory_calls += 1
                return worker()

            first = manager.start_singleton("durability_scheduler", factory)
            second = manager.start_singleton("durability_scheduler", factory)
            self.assertIs(first, second)
            self.assertEqual(factory_calls, 1)
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertEqual(manager.active_names(), ["durability_scheduler"])

            stopped = await manager.cancel_all(timeout_seconds=1)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(stopped["cancelled"], 1)
            self.assertEqual(stopped["remaining"], 0)
            self.assertFalse(stopped["timed_out"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
