"""V2 Step A: the tools the owner uses every day work right (news count, find, organize)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SAFE = {"safe": True, "reason": ""}


class TestNewsCount(unittest.TestCase):
    def run_news(self, **kwargs):
        from backend.app.tools.web_search_tools import NewsArgs, NewsSearchTool

        fake = [{"title": f"Headline {i}", "url": f"https://n.example/{i}", "snippet": "s"} for i in range(15)]
        search = AsyncMock(side_effect=lambda q, limit: fake[:limit])
        with patch("backend.app.tools._realsearch.real_web_search", search):
            args = NewsArgs(**kwargs).model_dump()
            result = asyncio.run(NewsSearchTool().execute(**args))
        return result, search

    def test_top_ten_gives_ten(self):
        result, search = self.run_news(count=10)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]["headlines"]), 10)
        self.assertEqual(search.call_args.kwargs["limit"], 10)

    def test_default_is_five_and_too_many_is_capped(self):
        result, _ = self.run_news()
        self.assertEqual(len(result["data"]["headlines"]), 5)
        result, _ = self.run_news(count=50)
        self.assertEqual(len(result["data"]["headlines"]), 10)
        result, _ = self.run_news(count="abc")
        self.assertEqual(len(result["data"]["headlines"]), 5)

    def test_schema_offers_count(self):
        from backend.app.tools.web_search_tools import NewsSearchTool

        self.assertIn("count", NewsSearchTool().get_metadata()["input_schema"]["properties"])


class FolderCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ultron_step_a_"))
        for target in ("backend.app.security.path_guard.check_path", "backend.app.tools.folder_tools.check_path"):
            patcher = patch(target, return_value=SAFE)
            patcher.start()
            self.addCleanup(patcher.stop)
        journal = patch("backend.app.core.action_journal.record", return_value={})
        self.journal = journal.start()
        self.addCleanup(journal.stop)

    def make(self, name: str, size: int = 10, age: float = 0.0) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        if age:
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))
        return path


class TestFindFiles(FolderCase):
    def find(self, **kwargs):
        from backend.app.tools.filesystem_tools import FindFilesArgs, FindFilesTool

        args = FindFilesArgs(search_root=str(self.dir), **kwargs).model_dump()
        return asyncio.run(FindFilesTool().execute(**args))

    def names(self, result):
        return [item["name"] for item in result["data"]["matches"]]

    def test_spaces_dots_underscores_dashes_and_capitals_do_not_matter(self):
        for name in ("Demon.Slayer.Mugen.Train.mkv", "demon_slayer-infinity_castle.mp4", "DEMON SLAYER.srt", "other.mkv"):
            self.make(name)
        got = set(self.names(self.find(pattern="demon slayer")))
        self.assertEqual(got, {"Demon.Slayer.Mugen.Train.mkv", "demon_slayer-infinity_castle.mp4", "DEMON SLAYER.srt"})
        self.assertIn("Demon.Slayer.Mugen.Train.mkv", self.names(self.find(pattern="Demon-Slayer")))

    def test_word_order_free_and_glob_ignores_capitals(self):
        self.make("Mugen Train Demon Slayer.MKV")
        self.assertEqual(self.names(self.find(pattern="demon train")), ["Mugen Train Demon Slayer.MKV"])
        self.assertEqual(self.names(self.find(pattern="*.mkv")), ["Mugen Train Demon Slayer.MKV"])

    def test_type_filter_and_aliases(self):
        self.make("demon slayer.mkv")
        self.make("demon slayer.pdf")
        self.make("demon slayer.mp3")
        self.assertEqual(self.names(self.find(pattern="demon", file_type="movies")), ["demon slayer.mkv"])
        self.assertEqual(self.names(self.find(pattern="demon", file_type="song")), ["demon slayer.mp3"])
        self.assertEqual(self.names(self.find(pattern="demon", file_type="pdf")), ["demon slayer.pdf"])
        # unknown type = no filter, never an error
        self.assertEqual(len(self.names(self.find(pattern="demon", file_type="spaceship"))), 3)

    def test_max_twenty_newest_first_with_more_note(self):
        for i in range(30):
            self.make(f"clip_{i:02d}.mp4", age=1000 - i)
        result = self.find(pattern="clip")
        self.assertEqual(result["data"]["matches_count"], 30)
        self.assertEqual(len(result["data"]["matches"]), 20)
        self.assertEqual(result["data"]["matches"][0]["name"], "clip_29.mp4")
        self.assertIn("10 more", result["data"]["more"])

    def test_biggest_first(self):
        self.make("small.mp4", size=10)
        self.make("big.mp4", size=5000)
        self.assertEqual(self.names(self.find(pattern="mp4", sort="largest"))[0], "big.mp4")

    def test_hidden_and_cache_folders_skipped(self):
        self.make(".cache/demon.mkv")
        self.make("node_modules/demon.mkv")
        self.make("Movies/demon.mkv")
        self.assertEqual(len(self.names(self.find(pattern="demon"))), 1)

    def test_empty_pattern_is_a_clear_error(self):
        from backend.app.tools.filesystem_tools import FindFilesTool

        result = asyncio.run(FindFilesTool().execute(pattern="  ", search_root=str(self.dir)))
        self.assertFalse(result["success"])


class TestOrganizeFolder(FolderCase):
    def organize(self):
        from backend.app.tools.folder_tools import OrganizeFolderTool

        return asyncio.run(OrganizeFolderTool().execute(folderpath=str(self.dir)))

    def test_real_downloads_sorted_into_the_right_groups(self):
        for name in ("movie.mkv", "song.mp3", "photo.JPG", "notes.pdf", "setup.deb", "tool.AppImage",
                     "backup.zip", "script.py", "weird.xyz"):
            self.make(name)
        result = self.organize()
        self.assertTrue(result["success"])
        expected = {"videos/movie.mkv", "music/song.mp3", "images/photo.JPG", "documents/notes.pdf",
                    "installers/setup.deb", "installers/tool.AppImage", "archives/backup.zip",
                    "code/script.py", "others/weird.xyz"}
        for rel in expected:
            self.assertTrue((self.dir / rel).is_file(), rel)
        self.assertEqual(result["data"]["moved_count"], 9)
        self.assertEqual(result["data"]["groups"]["installers"], 2)

    def test_unfinished_downloads_and_hidden_files_left_alone(self):
        self.make("big_movie.mkv.crdownload")
        self.make("file.part")
        self.make("temp.tmp")
        self.make(".hidden")
        result = self.organize()
        for name in ("big_movie.mkv.crdownload", "file.part", "temp.tmp", ".hidden"):
            self.assertTrue((self.dir / name).is_file(), name)
        self.assertEqual(result["data"]["moved_count"], 0)
        self.assertIn("file.part", result["data"]["left_alone_unfinished"])

    def test_never_overwrites_same_name(self):
        self.make("videos/movie.mkv", size=99)
        self.make("movie.mkv", size=5)
        result = self.organize()
        self.assertEqual((self.dir / "videos/movie.mkv").stat().st_size, 99)
        self.assertTrue((self.dir / "movie.mkv").is_file())
        self.assertIn("movie.mkv", result["data"]["left_alone_same_name_exists"])

    def test_moves_are_journaled_for_undo(self):
        self.make("a.mp3")
        self.organize()
        self.assertEqual(self.journal.call_args.args[0], "organize")
        self.assertEqual(len(self.journal.call_args.kwargs["moves"]), 1)


if __name__ == "__main__":
    unittest.main()


class TestLiveLine(unittest.TestCase):
    def setUp(self):
        from backend.app.core import live_context
        self.lc = live_context
        live_context._cache.update(at=0.0, apps=[], ram=None)
        self.addCleanup(live_context._cache.update, at=0.0, apps=[], ram=None)

    def _fake_psutil(self, names, ram=57.6):
        from types import SimpleNamespace
        procs = [SimpleNamespace(info={"name": n}) for n in names]
        return SimpleNamespace(virtual_memory=lambda: SimpleNamespace(percent=ram),
                               process_iter=lambda attrs: iter(procs))

    def test_format_with_city_apps_ram(self):
        import datetime, sys
        fake = self._fake_psutil(["chrome", "chrome", "code", "Code.exe", "bash", "mpv"])
        with patch.dict(sys.modules, {"psutil": fake}), patch.dict(os.environ, {"ULTRON_HOME_CITY": "Kolkata"}), \
                patch("backend.app.core.recent_folders.last", return_value=None):
            line = self.lc.live_line(datetime.datetime(2026, 9, 26, 21, 40))
        self.assertTrue(line.startswith("[Now] Sat 26 Sep 2026 21:40"))
        self.assertIn("Kolkata", line)
        self.assertIn("open: Chrome, VS Code, mpv", line)  # no duplicates, bash ignored
        self.assertIn("RAM 58%", line)
        self.assertLess(len(line) // 4, 45)

    def test_never_raises_when_psutil_breaks(self):
        import sys
        from types import SimpleNamespace
        broken = SimpleNamespace(virtual_memory=lambda: (_ for _ in ()).throw(RuntimeError("x")))
        with patch.dict(sys.modules, {"psutil": broken}), patch("backend.app.core.recent_folders.last",
                                                               side_effect=RuntimeError("x")):
            line = self.lc.live_line()
        self.assertIn("open: none seen", line)

    def test_scan_is_cached(self):
        import sys
        calls = []
        fake = self._fake_psutil(["firefox"])
        original = fake.process_iter
        fake.process_iter = lambda attrs: (calls.append(1), original(attrs))[1]
        with patch.dict(sys.modules, {"psutil": fake}):
            self.lc.live_line()
            self.lc.live_line()
        self.assertEqual(len(calls), 1)


class TestStaticPrefixStaysCached(unittest.TestCase):
    def test_prefix_is_byte_identical_and_has_the_rules(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator
        o = CognitiveOrchestrator.__new__(CognitiveOrchestrator)
        first, second = o._jarvis_static_prefix(), o._jarvis_static_prefix()
        self.assertEqual(first, second)
        self.assertNotIn("[Now]", first)
        mandate = o._action_mandate_block()
        for phrase in ("You don't just talk; you execute", "check", "one other route", "~/Documents/Ultron"):
            self.assertIn(phrase, mandate)
