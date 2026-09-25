"""File Explorer + Ultron use the whole disk and follow where Ultron works.

Before: the widget and personal relative paths were stuck in the assistant's
own source folder, and Up could never leave it.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core import recent_folders, widgets
from backend.app.security import path_guard, path_locator
from backend.app.tools import folder_tools
from backend.app.tools.folder_tools import ListContentsTool

REPO = Path(__file__).resolve().parents[1]
SAFE = {"safe": True, "reason": None}


class WholeDisk(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name).resolve() / "home"
        (self.home / "Desktop" / "jerry").mkdir(parents=True)
        (self.home / "notes").mkdir()
        self.outside = Path(self._tmp.name).resolve() / "elsewhere" / "project"
        (self.outside / "src").mkdir(parents=True)
        store = Path(self._tmp.name) / "recent.json"
        for item in (
            patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}),
            patch.object(recent_folders, "_store", lambda: store),
            patch.object(folder_tools, "check_path", lambda p: dict(SAFE, path=p)),
            patch.object(path_guard, "check_path", lambda p: dict(SAFE, path=p)),
            patch.object(path_locator, "_windows_shell_folder", lambda _c: None),
        ):
            item.start()
            self.addCleanup(item.stop)

    def ls(self, folder):
        return asyncio.run(ListContentsTool().execute(folderpath=folder))


class TestListContents(WholeDisk):
    def test_empty_path_opens_home_not_the_app_folder(self):
        result = self.ls("")
        self.assertTrue(result["success"], result)
        self.assertEqual(Path(result["data"]["path"]), self.home)
        self.assertNotEqual(Path(result["data"]["path"]), REPO)

    def test_empty_path_follows_the_folder_ultron_last_used(self):
        recent_folders.remember(self.outside)
        self.assertEqual(Path(self.ls("")["data"]["path"]), self.outside)
        self.assertEqual(Path(self.ls(".")["data"]["path"]), self.outside)

    def test_relative_name_is_found_in_last_folder_then_home(self):
        recent_folders.remember(self.outside)
        self.assertEqual(Path(self.ls("src")["data"]["path"]), self.outside / "src")
        self.assertEqual(Path(self.ls("notes")["data"]["path"]), self.home / "notes")

    def test_up_reaches_the_top_of_the_disk(self):
        result = self.ls(str(self.home / "Desktop"))
        self.assertEqual(Path(result["data"]["parent"]), self.home)
        top = self.ls(Path(self.home).anchor)
        self.assertTrue(top["success"], top)
        self.assertIsNone(top["data"]["parent"])

    def test_listing_a_folder_makes_it_that_folder(self):
        self.ls(str(self.home / "Desktop" / "jerry"))
        self.assertEqual(Path(recent_folders.last()), self.home / "Desktop" / "jerry")


class TestChatPaths(WholeDisk):
    def resolve(self, tool, args, confine=False):
        return path_guard.resolve_agent_tool_arguments(tool, args, str(REPO), confine_to_project=confine)

    def test_personal_dot_means_where_ultron_works(self):
        recent_folders.remember(self.outside)
        decision = self.resolve("list_contents", {"folderpath": "."})
        self.assertTrue(decision["safe"], decision)
        self.assertEqual(Path(decision["arguments"]["folderpath"]), self.outside)

    def test_personal_shell_starts_in_last_folder_and_search_covers_home(self):
        recent_folders.remember(self.outside)
        shell = self.resolve("terminal_run", {"command": "ls"})
        self.assertEqual(Path(shell["arguments"]["cwd"]), self.outside)
        search = self.resolve("find_files", {"pattern": "*.pdf"})
        self.assertEqual(Path(search["arguments"]["search_root"]), self.home)

    def test_home_name_beats_same_name_in_app_folder(self):
        (self.home / "docs").mkdir()  # the app repo also has docs/
        decision = self.resolve("list_contents", {"folderpath": "docs"})
        self.assertEqual(Path(decision["arguments"]["folderpath"]), self.home / "docs")

    def test_coding_mode_stays_locked_to_its_project(self):
        decision = self.resolve("terminal_run", {"command": "ls"}, confine=True)
        self.assertEqual(Path(decision["arguments"]["cwd"]), REPO.resolve())


class TestWidgetFollows(unittest.TestCase):
    def test_folder_listing_reloads_open_file_explorer(self):
        for tool in ("list_contents", "locate_path"):
            action = widgets.from_tool_results([{"tool": tool, "success": True, "args": {}}])
            self.assertEqual(action, {"action": "open_widget", "widget_id": "file_explorer", "refresh": True})

    def test_widget_source_uses_absolute_paths_and_quick_places(self):
        src = (REPO / "frontend/src/components/widgets/FileExplorerWidget.jsx").read_text(encoding="utf-8")
        self.assertNotIn('useState(".")', src)
        self.assertIn("data.data.parent", src)
        self.assertIn('load("")', src)
        for place in ("~/Desktop", "~/Documents", "~/Downloads"):
            self.assertIn(place, src)
        self.assertIn("apiBase", src)


if __name__ == "__main__":
    unittest.main()
