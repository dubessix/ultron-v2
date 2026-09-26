"""Owner: "not only the Ultron folder - every directory, also outside, and in the UI".

Real safety rules (no check_path shortcuts): full access mode, a fake home with
Desktop / Documents / Projects. Ultron's tools must work there in personal AND
coding turns, while OS folders and secret files stay blocked.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._ai_script import reply, use
from tests.test_jarvis_approval import ApiCase


class AnyFolderCase(ApiCase):
    def setUp(self):
        super().setUp()
        patch.stopall()  # drop ApiCase's check_path shortcuts: the REAL rules apply
        for item in (patch.dict(os.environ, {"ULTRON_TEST_FULL_ACCESS": "1"}),):
            item.start()
            self.addCleanup(item.stop)
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)
        for folder in ("Desktop", "Documents", "Projects/app"):
            (self.home / folder).mkdir(parents=True)
        (self.home / "Projects/app/main.py").write_text("print('hi')\n", encoding="utf-8")
        from backend.app.security import path_locator
        for item in (patch.object(Path, "home", classmethod(lambda cls: self.home)),
                     # Windows reads the real Desktop/Documents from the registry
                     patch.object(path_locator, "_windows_shell_folder", lambda _c: None),
                     patch("backend.app.core.recent_folders.last", return_value=None)):
            item.start()
            self.addCleanup(item.stop)
        from backend.app.core import orchestrator as orch
        self.addCleanup(setattr, orch, "_SHARED_CODING_MODE", False)

    def run_tool(self, tool, args, coding=False):
        from backend.app.core import orchestrator as orch
        orch._SHARED_CODING_MODE = coding
        seen = {}

        def script(prompt, conv):
            results = [m for m in conv if m.get("role") == "tool"]
            if not results:
                return reply("", [use(tool, args)])
            seen["result"] = str(results[0]["content"])
            return reply("Done, Sir.")

        self.script = script
        answer = self.chat("go")
        return answer, seen.get("result", "")


class TestPersonalTurnsReachEveryFolder(AnyFolderCase):
    def test_write_in_documents_by_short_name(self):
        answer, result = self.run_tool("file_write", {"filepath": "Documents/plan.txt", "content": "x"})
        self.assertTrue((self.home / "Documents/plan.txt").exists(), result)
        self.assertIsNone(answer.get("pending_confirmation"))

    def test_list_desktop_and_shell_starts_outside_ultron(self):
        _answer, result = self.run_tool("list_contents", {"folderpath": "Desktop"})
        self.assertIn('"success":true', result)
        _answer, result = self.run_tool("terminal_run", {"command": "cd"} if os.name == "nt" else {"command": "pwd"})
        self.assertIn(str(self.home), result.replace("\\\\", "\\"))  # never the Ultron code folder

    def test_os_folders_and_secrets_stay_blocked(self):
        (self.home / ".ssh").mkdir()
        (self.home / ".ssh/id_rsa").write_text("KEY", encoding="utf-8")
        _answer, result = self.run_tool("file_read", {"filepath": str(self.home / ".ssh/id_rsa")})
        self.assertNotIn("KEY", result)
        system = r"C:\Windows\win.ini" if os.name == "nt" else "/etc/hostname"
        _answer, result = self.run_tool("file_read", {"filepath": system})
        self.assertNotIn('"success":true', result)


class TestCodingTurnsWorkInTheOwnersProject(AnyFolderCase):
    def test_coding_shell_runs_in_a_project_outside_ultron(self):
        project = self.home / "Projects/app"
        # a look-only command, so coding mode does not ask first (dir = Windows, pwd = Linux)
        answer, result = self.run_tool("terminal_run", {"command": "dir" if os.name == "nt" else "pwd",
                                                        "cwd": str(project)}, coding=True)
        self.assertNotIn("outside_active_project", str(answer))
        self.assertIn('"success":true', result)

    def test_coding_read_outside_ultron_is_not_blocked(self):
        answer, _result = self.run_tool("file_read", {"filepath": str(self.home / "Projects/app/main.py")},
                                        coding=True)
        self.assertNotIn("outside_active_project", str(answer))
        # coding reads still show one privacy question (file goes to the cloud coder)
        self.assertEqual((answer.get("pending_confirmation") or {}).get("tool_id"), "file_read")

    def test_restricted_mode_still_confines_coding(self):
        with patch("backend.app.security.path_guard.full_access_enabled", return_value=False):
            answer, _result = self.run_tool("terminal_run", {"command": "pwd", "cwd": str(self.home)}, coding=True)
        self.assertIn("blocked", str(answer))


class TestProjectScanStaysLight(unittest.TestCase):
    def test_scan_of_a_huge_folder_is_bounded(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        for i in range(60):
            for j in range(10):
                (root / f"d{i}" / f"s{j}").mkdir(parents=True)
        (root / ".hidden").mkdir()
        text = CognitiveOrchestrator.__new__(CognitiveOrchestrator)._scan_project_context(str(root))
        self.assertLessEqual(len(text.splitlines()), 120)
        self.assertNotIn(".hidden", text)


if __name__ == "__main__":
    unittest.main()
