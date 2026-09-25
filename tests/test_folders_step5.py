"""V2 Step 5 - folder power: real OS folders, deep index, asks when unsure, remembers."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.app.core import folder_index, recent_folders
from backend.app.security import path_locator
from backend.app.security.path_locator import AmbiguousPath, auto_resolve, clean_name, home_folder, locate_detailed


class FakeHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name).resolve() / "home"
        self.home.mkdir()
        self.db = Path(self._tmp.name) / "index.db"
        patches = [
            patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),
                                    "XDG_CONFIG_HOME": str(self.home / ".config")}),
            patch.object(path_locator, "_windows_shell_folder", lambda _c: None),
            patch.object(folder_index, "db_path", lambda: self.db),
            patch.object(path_locator, "search_roots", lambda extra=(): [self.home, *map(Path, extra)]),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        path_locator._cache.clear()
        recent_folders.clear()
        self.addCleanup(recent_folders.clear)
        self.addCleanup(self._tmp.cleanup)

    def make(self, *parts: str, file: str | None = None) -> Path:
        folder = self.home.joinpath(*parts)
        folder.mkdir(parents=True, exist_ok=True)
        if file:
            (folder / file).write_text("x", encoding="utf-8")
        return folder


class TestRealOsFolders(FakeHome):
    def test_onedrive_desktop_wins_over_empty_home_desktop(self):
        """Windows 11 bug: an empty C:\\Users\\X\\Desktop hid the real OneDrive Desktop."""
        self.make("Desktop")
        real = self.make("OneDrive", "Desktop", file="notes.txt")
        self.assertEqual(home_folder("desktop"), real)

    def test_home_desktop_with_files_still_works(self):
        real = self.make("Desktop", file="a.txt")
        self.assertEqual(home_folder("Desktop"), real)

    def test_windows_settings_are_trusted_first(self):
        moved = self.make("D-drive", "MyDesktop")
        with patch.object(path_locator, "_windows_shell_folder", lambda c: moved if c == "Desktop" else None):
            self.assertEqual(home_folder("Desktop"), moved)

    @unittest.skipIf(os.name == "nt", "XDG user-dirs are Linux only")
    def test_ubuntu_xdg_user_dirs(self):
        translated = self.make("Schreibtisch")
        config = self.make(".config")
        (config / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Schreibtisch"\n', encoding="utf-8")
        self.assertEqual(home_folder("Desktop"), translated)

    def test_spoken_filler_is_removed(self):
        self.assertEqual(clean_name("downloads wala folder"), "downloads")
        self.assertEqual(clean_name("my college projects folder"), "college projects")
        self.assertEqual(clean_name("mera Projects folder"), "Projects")


class TestDeepIndex(FakeHome):
    def test_index_finds_folders_deeper_than_the_live_walk(self):
        deep = self.make("a", "b", "c", "d", "e", "f", "g", "SecretProj")
        self.assertEqual(locate_detailed("SecretProj")["matches"], [])  # old 4-level limit
        path_locator._cache.clear()
        self.assertGreater(folder_index.build([self.home], path=self.db), 7)
        found = locate_detailed("SecretProj")
        self.assertEqual(found["matches"], [str(deep)])
        self.assertEqual(found["how"], "index")

    def test_spelling_mistakes_are_forgiven(self):
        target = self.make("work", "College_Projects")
        folder_index.build([self.home], path=self.db)
        self.assertEqual(locate_detailed("colege projects")["matches"][:1], [str(target)])

    def test_deleted_folder_is_not_returned(self):
        gone = self.make("x", "Temporary")
        folder_index.build([self.home], path=self.db)
        gone.rmdir()
        self.assertEqual(folder_index.lookup("Temporary", path=self.db)["exact"], [])

    def test_index_stores_names_only(self):
        self.make("docs", file="secret-contents.txt")
        folder_index.build([self.home], path=self.db)
        self.assertEqual(folder_index.lookup("secret-contents.txt", path=self.db)["exact"], [])


class TestAsksWhenUnsure(FakeHome):
    def setUp(self):
        super().setUp()
        self.one = self.make("Desktop", "Projects", file="a.txt")
        self.two = self.make("Documents", "Projects", file="b.txt")

    def test_two_same_name_folders_are_ambiguous(self):
        found = locate_detailed("Projects")
        self.assertTrue(found["ambiguous"])
        self.assertEqual(sorted(found["exact"]), sorted([str(self.one), str(self.two)]))
        with self.assertRaises(AmbiguousPath) as clash:
            auto_resolve("Projects", self.home)
        self.assertIn("Ask the owner", str(clash.exception))

    def test_recently_used_folder_breaks_the_tie(self):
        recent_folders.remember(self.two)
        path_locator._cache.clear()
        found = locate_detailed("Projects")
        self.assertFalse(found["ambiguous"])
        self.assertEqual(found["matches"][0], str(self.two))

    def test_locate_tool_returns_choices(self):
        from backend.app.tools.locate_tool import LocatePathTool

        with patch("backend.app.security.path_guard.check_path", lambda p: {"safe": True}):
            result = asyncio.run(LocatePathTool().execute(name="Projects"))
        self.assertTrue(result["data"]["ambiguous"])
        self.assertEqual(len(result["data"]["choices"]), 2)
        self.assertNotIn("best", result["data"])
        self.assertIn("ask the owner", result["data"]["message"])

    def test_path_guard_hands_the_question_to_the_ai(self):
        from backend.app.security import path_guard

        with patch.object(path_guard, "check_path", lambda p: {"safe": True, "reason": None, "path": p}):
            decision = path_guard.resolve_agent_tool_arguments(
                "list_contents", {"path": "Projects"}, str(self.home / "Desktop"), confine_to_project=False
            )
        if decision.get("reason") != "ambiguous":  # field name differs per tool
            decision = path_guard.resolve_agent_tool_arguments(
                "organize_folder", {"folderpath": "Projects"}, str(self.home), confine_to_project=False
            )
        self.assertFalse(decision["safe"])
        self.assertEqual(decision["reason"], "ambiguous")
        self.assertEqual(len(decision["choices"]), 2)


class TestRemembersFolders(FakeHome):
    def test_that_folder_means_the_last_one(self):
        used = self.make("Music", "Bollywood")
        recent_folders.remember(used)
        for phrase in ("that folder", "same folder", "wahi folder", "last folder", "there"):
            with self.subTest(phrase=phrase):
                self.assertEqual(locate_detailed(phrase)["matches"], [str(used)])

    def test_not_references(self):
        for phrase in ("that folder named Projects", "Projects", "downloads"):
            self.assertFalse(recent_folders.is_reference(phrase), phrase)

    def test_files_record_their_folder_and_list_is_bounded(self):
        folder = self.make("Docs", file="cv.pdf")
        recent_folders.remember(folder / "cv.pdf")
        self.assertEqual(recent_folders.last(), str(folder))
        for index in range(40):
            recent_folders.remember(self.make("many", f"f{index}"))
        self.assertLessEqual(len(recent_folders.recent()), recent_folders.MAX_ITEMS)


class TestShortAnswerReachesTheBrain(unittest.IsolatedAsyncioTestCase):
    async def test_answer_2_after_a_question_is_not_vague(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        orchestrator = CognitiveOrchestrator()
        try:
            orchestrator.memory.gate.should_save = lambda _p: False
            session = "step5-choice"
            orchestrator.memory.save_chat_turn(
                session, "open projects", "Sir, two Projects folders: Desktop or Documents?")
            reply = {"content": "Opening the Documents one, Sir.", "tool_calls": [], "provider": "groq",
                     "model": "t", "native_tools": True, "provider_state": None}
            orchestrator.router.get_completions_with_tools = AsyncMock(return_value=reply)
            orchestrator.router.get_completions = AsyncMock(return_value=reply["content"])
            result = await orchestrator.process_request("2", session_id=session)
            self.assertNotIn("not entirely sure", result["content"])
            # without a question before, "2" is still treated as vague
            fresh = await orchestrator.process_request("2", session_id="step5-fresh")
            self.assertIn("not entirely sure", fresh["content"])
        finally:
            await orchestrator.close()


if __name__ == "__main__":
    unittest.main()
