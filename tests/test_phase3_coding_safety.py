"""
Phase 3 regression — safe coding agent write-path.

Covers:
  - The shared safe-write path backs up existing files before overwriting and
    writes atomically.
  - The `file_write` tool now also backs up (previously overwrote with no backup).
  - `_coding_safe_write` respects real confirmation (previously hardcoded False)
    and binds confirmation to the EXACT file+content via a one-time token.
  - Path guard blocks sensitive/system paths at any depth.

No real user data is touched: file writes go to temp dirs, and conftest.py
forces a temporary DB/cache.
"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.security.path_guard import is_path_safe
from backend.app.tools.filesystem_tools import FileWriteTool
from backend.app.runtime_paths import isolated_test_artifact_path


def _run(coro):
    return asyncio.run(coro)


def _tmpfile(name):
    return isolated_test_artifact_path("phase3", os.urandom(4).hex(), name)


class TestSafeWriteBackup(unittest.TestCase):

    def test_file_write_tool_backs_up_existing_file(self):
        target = _tmpfile("notes.txt")
        target.write_text("ORIGINAL", encoding="utf-8")

        result = _run(FileWriteTool().execute(filepath=str(target), content="UPDATED"))
        self.assertTrue(result["success"])
        self.assertEqual(target.read_text(encoding="utf-8"), "UPDATED")
        # A .bak backup of the original must exist.
        backup = Path(str(target) + ".bak")
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), "ORIGINAL")

    def test_safe_write_creates_new_file_no_backup(self):
        target = _tmpfile("brand_new.py")
        from backend.app.tools.safe_write import safe_write_file
        result = safe_write_file(str(target), "print('hi')")
        self.assertTrue(result["success"])
        self.assertTrue(target.exists())
        self.assertIsNone(result["data"]["backup"])


class TestCodingSafeWrite(unittest.TestCase):

    def setUp(self):
        self.orch = CognitiveOrchestrator()
        self.session = "sess_" + os.urandom(4).hex()

    def test_new_file_requires_exact_confirmation(self):
        target = _tmpfile("new.py")
        args = {"filepath": str(target), "content": "x=1"}
        pending = _run(self.orch._coding_safe_write(
            args, has_confirmed=False, session_id=self.session))
        self.assertEqual(pending["status"], "PENDING_CONFIRMATION")
        self.assertFalse(target.exists())
        result = _run(self.orch._coding_safe_write(
            args,
            has_confirmed=True,
            session_id=self.session,
            confirmation_token=pending["confirmation_token"],
        ))
        self.assertTrue(result["success"])
        self.assertTrue(target.exists())

    def test_existing_file_requires_confirmation_and_binds_token(self):
        target = _tmpfile("app.py")
        target.write_text("OLD", encoding="utf-8")
        r = _run(self.orch._coding_safe_write(
            {"filepath": str(target), "content": "NEW"},
            has_confirmed=False, session_id=self.session))
        self.assertEqual(r["status"], "PENDING_CONFIRMATION")
        self.assertTrue(r["confirmation_token"])
        # File must NOT have changed.
        self.assertEqual(target.read_text(encoding="utf-8"), "OLD")

        # Confirming with the SAME token + content executes + backs up.
        r2 = _run(self.orch._coding_safe_write(
            {"filepath": str(target), "content": "NEW"},
            has_confirmed=True, session_id=self.session,
            confirmation_token=r["confirmation_token"]))
        self.assertTrue(r2["success"])
        self.assertEqual(target.read_text(encoding="utf-8"), "NEW")
        self.assertTrue(Path(str(target) + ".bak").exists())

    def test_confirmation_rejected_when_content_differs(self):
        """A 'yes' bound to content A must NOT authorize content B."""
        target = _tmpfile("config.yaml")
        target.write_text("a: 1", encoding="utf-8")
        pending = _run(self.orch._coding_safe_write(
            {"filepath": str(target), "content": "a: 2"},
            has_confirmed=False, session_id=self.session))
        token = pending["confirmation_token"]

        # Confirm but with DIFFERENT content -> must ask again, not write.
        r = _run(self.orch._coding_safe_write(
            {"filepath": str(target), "content": "a: 999"},
            has_confirmed=True, session_id=self.session,
            confirmation_token=token))
        self.assertEqual(r["status"], "PENDING_CONFIRMATION")
        self.assertEqual(target.read_text(encoding="utf-8"), "a: 1")

    def test_blocked_path_rejected(self):
        target = _tmpfile("ok.txt")
        bad = str(target.parent / ".env")  # .env is blocked at any depth
        r = _run(self.orch._coding_safe_write(
            {"filepath": bad, "content": "secret"},
            has_confirmed=True, session_id=self.session))
        self.assertFalse(r["success"])
        self.assertIn("blocked", r["error"].lower())


class TestPathGuardDepth(unittest.TestCase):

    def test_blocks_sensitive_at_any_depth(self):
        self.assertFalse(is_path_safe("/tmp/x/.env/creds.txt"))      # .env component
        self.assertFalse(is_path_safe("/tmp/x/.ssh/id_rsa"))         # .ssh component
        self.assertFalse(is_path_safe("/etc/passwd"))                # system dir
        self.assertFalse(is_path_safe("/proc/1/status"))             # system dir
        self.assertFalse(is_path_safe(str(Path(tempfile.gettempdir()) / "a/.env")))

    def test_allows_normal_project_path(self):
        p = isolated_test_artifact_path("phase3_normal", "src", "main.py")
        self.assertTrue(is_path_safe(str(p)))


class TestHeavyToolsRunWithoutFreezing(unittest.IsolatedAsyncioTestCase):
    """Heavy scans are now off the event loop (asyncio.to_thread) — they must
    still return correct results (and not block/crash the suite)."""

    async def test_find_files_still_works_in_thread(self):
        from backend.app.tools.filesystem_tools import FindFilesTool
        tool = FindFilesTool()
        res = await tool.execute(pattern=".py", search_root="backend/app/core")
        self.assertTrue(res["success"])
        # Should find at least the orchestrator itself.
        self.assertGreater(res["data"]["matches_count"], 0)

    async def test_project_context_block_is_awaitable_and_returns_text(self):
        orch = CognitiveOrchestrator()
        ctx = await orch._get_project_context_block()
        self.assertIsInstance(ctx, str)
        self.assertIn("[PROJECT_CONTEXT]", ctx)


if __name__ == "__main__":
    unittest.main()
