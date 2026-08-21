"""
Phase 9 regression — durability (backup/restore/integrity + schema versioning).

All tests run against the TEMPORARY DB (conftest.py sets ULTRON_TEST_DB=1), so
real user data is never touched by a backup/restore test.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.app.database import db as _db
from backend.app.database.backup import backup_database, restore_database, check_integrity
from backend.app.database.models import get_schema_version, SCHEMA_VERSION


def _run(coro):
    return asyncio.run(coro)


def _write_real_row(conn):
    import uuid
    cur = conn.cursor()
    # Ensure the parent session exists (FK constraint).
    cur.execute(
        "INSERT OR IGNORE INTO sessions (id, current_goal, current_mode, personality) VALUES (?,?,?,?);",
        ("dur_sess", "Bootstrap V1", "developer", "ultron"),
    )
    cur.execute(
        "INSERT INTO conversations (id, session_id, user_message, ai_response, personality, tools_used, intent, mode, path_used, response_ms) "
        "VALUES (?,?,?,?,?,?,?,?,?,?);",
        (str(uuid.uuid4()), "dur_sess", "hello", "hi", "ultron", "[]", "Conversation", "developer", "fast", 1),
    )
    conn.commit()


class TestBackupRestore(unittest.TestCase):

    def setUp(self):
        # Point DB to a fresh temp path so we never touch real data.
        self._tmp = Path(tempfile.mkdtemp(prefix="ultron_dur_"))
        self._orig_db = _db.DB_PATH
        self._orig_dir = _db.DB_DIR
        _db.DB_PATH = self._tmp / "ultron.db"
        _db.DB_DIR = self._tmp
        from backend.app.database.db import get_db_connection
        from backend.app.database.models import initialize_database
        with get_db_connection() as conn:
            initialize_database(conn)

    def tearDown(self):
        _db.DB_PATH = self._orig_db
        _db.DB_DIR = self._orig_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_backup_creates_verified_copy(self):
        with _db.get_db_connection() as conn:
            _write_real_row(conn)
        result = backup_database(dest_dir=self._tmp / "bk")
        self.assertTrue(result["success"])
        self.assertTrue(Path(result["data"]["backup_path"]).exists())
        self.assertTrue(result["data"]["verification"]["valid"])

    def test_restore_replaces_db_and_keeps_safety_copy(self):
        from backend.app.database.db import get_db_connection
        # Seed some rows, backup, then corrupt/empty, then restore.
        with get_db_connection() as conn:
            _write_real_row(conn)
            _write_real_row(conn)
        result = backup_database()
        backup_path = result["data"]["backup_path"]

        # Wipe the live DB.
        with get_db_connection() as conn:
            conn.execute("DELETE FROM conversations;")
            conn.commit()

        restored = restore_database(backup_path)
        self.assertTrue(restored["success"])
        self.assertTrue(Path(restored["data"]["safety_backup"]).exists())
        with get_db_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        self.assertGreaterEqual(count, 2)

    def test_restore_refuses_invalid_file(self):
        bad = self._tmp / "notadb.txt"
        bad.write_text("this is not a database", encoding="utf-8")
        result = restore_database(str(bad))
        self.assertFalse(result["success"])

    def test_integrity_reports_valid(self):
        result = check_integrity()
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])


class TestSchemaVersioning(unittest.TestCase):

    def test_schema_version_is_current(self):
        from backend.app.database.db import get_db_connection
        with get_db_connection() as conn:
            self.assertEqual(get_schema_version(conn), SCHEMA_VERSION)


class TestMemoryTool(unittest.TestCase):

    def test_remember_list_forget_cycle(self):
        from backend.app.tools.memory_tool import MemoryTool
        tool = MemoryTool()
        r = _run(tool.execute(action="remember", content="Test fact to remember."))
        self.assertTrue(r["success"])
        lst = _run(tool.execute(action="list"))
        self.assertTrue(lst["success"])
        self.assertGreaterEqual(lst["data"]["count"], 1)
        # Forget the remembered id.
        mid = lst["data"]["memories"][0]["id"]
        f = _run(tool.execute(action="forget", memory_id=mid))
        self.assertTrue(f["success"])


if __name__ == "__main__":
    unittest.main()
