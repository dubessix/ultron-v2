"""V2 Step B4-B5: general hands - edit any file safely, open videos/apps detached."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core import action_journal, approval
from backend.app.tools.filesystem_tools import FileWriteTool


def run(coro):
    return asyncio.run(coro)


class EditCase(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.work, True)
        env = patch.dict(os.environ, {"ULTRON_TEST_FULL_ACCESS": "1"})
        env.start()
        self.addCleanup(env.stop)
        action_journal.clear()
        self.addCleanup(action_journal.clear)

    def edit(self, target, search, replace):
        return run(FileWriteTool().execute(filepath=str(target), search_text=search, replace_text=replace))


class TestEditOnePart(EditCase):
    def test_edit_without_fingerprint_keeps_the_rest(self):
        target = self.work / "notes.md"
        target.write_text("# Title\nold line\nend\n", encoding="utf-8")
        result = self.edit(target, "old line", "new line")
        self.assertTrue(result["success"], result)
        self.assertEqual(target.read_text(encoding="utf-8"), "# Title\nnew line\nend\n")

    def test_backup_lives_in_ultrons_folder_and_undo_restores(self):
        target = self.work / "app.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = self.edit(target, "x = 1", "x = 2")
        self.assertTrue(result["success"], result)
        self.assertFalse(Path(str(target) + ".bak").exists(), "no clutter next to the owner's files")
        self.assertNotEqual(Path(result["data"]["backup"]).parent, self.work)
        undone = action_journal.undo_last()
        self.assertTrue(undone["success"], undone)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 1\n")

    def test_new_file_is_recorded_for_undo(self):
        target = self.work / "fresh.txt"
        run(FileWriteTool().execute(filepath=str(target), content="hi"))
        self.assertEqual(action_journal.recent(1)[0]["kind"], "create")

    def test_clear_messages_when_text_is_missing_or_repeated(self):
        target = self.work / "a.txt"
        target.write_text("same\nsame\n", encoding="utf-8")
        self.assertIn("more than once", self.edit(target, "same", "x")["error"])
        self.assertIn("not found", self.edit(target, "nothing", "x")["error"])
        self.assertEqual(target.read_text(encoding="utf-8"), "same\nsame\n")

    def test_python_syntax_error_is_refused_and_file_kept(self):
        target = self.work / "ok.py"
        target.write_text("def f():\n    return 1\n", encoding="utf-8")
        result = self.edit(target, "return 1", "return (1")
        self.assertFalse(result["success"])
        self.assertIn("verification failed", result["error"])
        self.assertEqual(target.read_text(encoding="utf-8"), "def f():\n    return 1\n")

    def test_missing_checker_never_blocks_a_react_file(self):
        target = self.work / "App.jsx"
        target.write_text("export default function App() { return <h1>Hi</h1> }\n", encoding="utf-8")
        with patch("backend.app.tools.safe_write.shutil.which", return_value=None), \
                patch("backend.app.tools.safe_write.Path.is_file", return_value=False):
            result = self.edit(target, "Hi", "Hello Sir")
        self.assertTrue(result["success"], result)
        self.assertFalse(result["data"]["verification"]["checked"])
        self.assertIn("Hello Sir", target.read_text(encoding="utf-8"))

    def test_backups_are_capped(self):
        from backend.app.tools import safe_write
        target = self.work / "count.txt"
        target.write_text("0", encoding="utf-8")
        with patch.object(safe_write, "BACKUPS_KEPT", 3):
            for i in range(6):
                self.assertTrue(self.edit(target, str(i), str(i + 1))["success"])
            folder = Path(self.edit(target, "6", "7")["data"]["backup"]).parent
        self.assertLessEqual(len(list(folder.iterdir())), 3)


class TestWhenToAsk(unittest.TestCase):
    def test_exact_edit_does_not_ask_but_whole_overwrite_does(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as handle:
            handle.write("x")
        self.addCleanup(os.unlink, handle.name)
        self.assertFalse(approval.needs_ask("file_write", {"filepath": handle.name, "search_text": "x", "replace_text": "y"}, 2))
        self.assertTrue(approval.needs_ask("file_write", {"filepath": handle.name, "content": "all new"}, 2))


class TestOpenIsDetached(unittest.TestCase):
    def test_video_opens_in_its_own_session_so_nothing_kills_it(self):
        from backend.app.tools import pc_tools
        video = Path(tempfile.mkdtemp()) / "movie.mkv"
        self.addCleanup(shutil.rmtree, video.parent, True)
        video.write_bytes(b"x")
        with patch.object(pc_tools.subprocess, "Popen") as popen, \
                patch.object(pc_tools.shutil, "which", return_value="/usr/bin/xdg-open"), \
                patch.object(pc_tools, "IS_WINDOWS", False):
            result = pc_tools.FileActionsTool._open(video, False)
        self.assertTrue(result["success"])
        kwargs = popen.call_args.kwargs
        self.assertTrue(kwargs.get("start_new_session"))
        self.assertIs(kwargs.get("stdin"), pc_tools.subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()


class TestPcFacts(unittest.TestCase):
    def setUp(self):
        from backend.app.core import pc_facts
        self.pf = pc_facts
        pc_facts._memory.clear()
        self.addCleanup(pc_facts._memory.clear)

    def test_line_lists_installed_and_missing_programs(self):
        have = {"python3", "node", "npm", "git", "mpv", "google-chrome"}
        with patch.object(self.pf.shutil, "which", side_effect=lambda c: f"/usr/bin/{c}" if c in have else None), \
                patch.object(self.pf.platform, "system", return_value="Linux"), \
                patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}):
            self.pf.facts(refresh=True)
            line = self.pf.facts_line()
        self.assertIn("GNOME Wayland", line)
        installed, missing = line.split("Not installed:")
        for name in ("python", "node", "git", "mpv", "chrome"):
            self.assertIn(name, installed)
        for name in ("vlc", "libreoffice", "playerctl"):
            self.assertIn(name, missing)
        self.assertNotIn("winget", line)  # Windows-only tools are not listed on Linux
        self.assertLess(len(line) // 4, 90)

    def test_cached_for_the_day(self):
        self.pf.facts(refresh=True)
        with patch.object(self.pf, "collect", side_effect=AssertionError("rescanned")):
            self.pf.facts()
            self.pf._memory.clear()
            self.pf.facts()  # from the disk cache

    def test_facts_are_in_the_cached_prefix(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator
        CognitiveOrchestrator._STATIC_PREFIX_CACHE = None
        CognitiveOrchestrator._PC_PROFILE_CACHE = None
        prefix = CognitiveOrchestrator._jarvis_static_prefix()
        self.assertIn("[OWNER PC] PC: ", prefix)
        self.assertIn("ask before installing", prefix)
        self.assertEqual(prefix, CognitiveOrchestrator._jarvis_static_prefix())
