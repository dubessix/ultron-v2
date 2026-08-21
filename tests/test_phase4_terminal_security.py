"""
Phase 4 regression — terminal & URL (SSRF) security.

  - terminal_run uses arg-based subprocess for simple commands, requires an
    approved leading command for shell-metacharacter commands, and kills the
    whole process group on timeout (no orphaned children).
  - download_file / read_current_page reject localhost/private/metadata URLs
    (SSRF) and downloads are size-capped.
"""

import asyncio
import unittest
from unittest.mock import patch

from backend.app.security.url_guard import validate_public_url
from backend.app.tools.browser_tools import DownloadFileTool
from backend.app.tools.system_tools import TerminalRunTool
from backend.app.runtime_paths import isolated_test_artifact_path


def _run(coro):
    return asyncio.run(coro)


class TestTerminalSecurity(unittest.TestCase):

    def setUp(self):
        self.tool = TerminalRunTool()

    def test_simple_command_runs_via_exec(self):
        r = _run(self.tool.execute(command="echo phase4_safe"))
        self.assertTrue(r["success"])
        self.assertEqual(r["data"]["stdout"].strip(), "phase4_safe")

    def test_approved_prefix_shell_pipe_allowed(self):
        r = _run(self.tool.execute(command="printf 'a\\nb\\n' | wc -l"))
        self.assertTrue(r["success"])
        self.assertEqual(r["data"]["stdout"].strip(), "2")

    def test_shell_metachar_without_approved_prefix_blocked(self):
        r = _run(self.tool.execute(command="bash -c 'echo a; echo b'"))
        self.assertFalse(r["success"])
        self.assertIn("blocked", r["error"].lower())

    def test_destructive_command_blocked(self):
        r = _run(self.tool.execute(command="rm -rf /"))
        self.assertFalse(r["success"])


class TestUrlGuard(unittest.TestCase):

    def test_blocks_local_and_private(self):
        self.assertFalse(validate_public_url("http://localhost:8000/")[0])
        self.assertFalse(validate_public_url("http://127.0.0.1/")[0])
        self.assertFalse(validate_public_url("http://169.254.169.254/latest/meta-data")[0])
        self.assertFalse(validate_public_url("http://192.168.1.1/")[0])
        self.assertFalse(validate_public_url("ftp://example.com/x")[0])  # non-http

    @patch("backend.app.security.url_guard.socket.getaddrinfo",
           return_value=[(2, 1, 6, "", ("93.184.216.34", 0))])
    def test_allows_public_url(self, _mock):
        ok, _ = validate_public_url("https://example.com/page")
        self.assertTrue(ok)

    @patch("backend.app.security.url_guard.socket.getaddrinfo",
           return_value=[(2, 1, 6, "", ("10.0.0.5", 0))])
    def test_blocks_host_resolving_to_private(self, _mock):
        ok, _ = validate_public_url("https://internal.example.net/")
        self.assertFalse(ok)


class TestDownloadSsrfs(unittest.TestCase):

    def test_download_rejects_localhost(self):
        destination = isolated_test_artifact_path("phase4", "x.bin")
        r = _run(DownloadFileTool().execute(
            url="http://127.0.0.1/secret",
            save_path=str(destination),
        ))
        self.assertFalse(r["success"])
        self.assertIn("SSRF", r["error"])


if __name__ == "__main__":
    unittest.main()
