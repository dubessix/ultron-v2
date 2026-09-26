"""V2 Step A acceptance: the owner's three real test jobs, end to end.

Real FastAPI app + real tools + real safety; only the AI brain is scripted, so
each test proves the code does exactly what the AI decides, IRIS/Stonic style:
understand -> tools in order -> check -> short true reply.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from tests._ai_script import reply, use
from tests.test_jarvis_approval import ApiCase

HEADLINES = [{"title": f"Headline number {i}", "url": f"https://news.example/{i}", "snippet": "s"} for i in range(1, 11)]


def tool_results(conv):
    return [json.loads(m["content"]) if isinstance(m.get("content"), str) and m["content"].startswith("{") else m.get("content")
            for m in conv if m.get("role") == "tool"]


class TestEveryTurnKnowsNowAndTheRules(ApiCase):
    def test_live_line_and_iris_rules_reach_the_brain(self):
        self.script = lambda prompt, conv: reply("Good evening, Sir.")
        self.chat("hello")
        system = self.brain_calls[-1]["system"]
        self.assertIn("[Now] ", system)
        self.assertIn("RAM ", system)
        self.assertIn("You don't just talk; you execute", system)
        self.assertIn("pick the normal default", system)
        self.assertIn("give all of it", system)
        # the live line is AFTER the cached static block
        self.assertGreater(system.index("[Now] "), system.index("[TOOL MENU]"))


class TestNewsToFileThenRead(ApiCase):
    def test_top_ten_saved_checked_and_read_in_full(self):
        target = self.root / "top_news.txt"
        steps = []

        def script(prompt, conv):
            done = len([m for m in conv if m.get("role") == "tool"])
            steps.append(done)
            if done == 0:
                return reply("", [use("news_search", {"count": 10}, "n1")])
            if done == 1:
                text = "\n".join(f"{i}. {h['title']}" for i, h in enumerate(HEADLINES, 1))
                return reply("", [use("file_write", {"filepath": str(target), "content": text}, "w1")])
            if done == 2:
                return reply("", [use("file_read", {"filepath": str(target)}, "r1")])
            spoken = " ".join(f"{i}, {h['title']}." for i, h in enumerate(HEADLINES, 1))
            return reply(f"Saved, Sir. Here are today's top ten. {spoken}")

        self.script = script
        with patch("backend.app.tools._realsearch.real_web_search", AsyncMock(return_value=HEADLINES)):
            result = self.chat("top 10 news, save it in a text file and read it to me")
        self.assertIsNone(result.get("pending_confirmation"), "a new file never asks")
        self.assertEqual(len(target.read_text().splitlines()), 10)
        for headline in HEADLINES:
            self.assertIn(headline["title"], result["content"])  # read in full, not cut short
        self.assertEqual(steps, [0, 1, 2, 3])


class TestFindTheMovieThenPlay(ApiCase):
    def test_two_matches_one_question_then_plays_the_chosen_one(self):
        movies = self.root / "Movies"
        movies.mkdir()
        mugen = movies / "Demon.Slayer.Mugen.Train.mkv"
        castle = movies / "demon_slayer_infinity_castle.mp4"
        for path in (mugen, castle, movies / "Demon Slayer notes.txt"):
            path.write_bytes(b"x" * 100)
        found = {}

        def ask(prompt, conv):
            results = tool_results(conv)
            if not results:
                return reply("", [use("find_files", {"pattern": "demon slayer", "search_root": str(self.root),
                                                     "file_type": "video"}, "f1")])
            found["names"] = sorted(m["name"] for m in results[0]["data"]["matches"])
            return reply("Found two, Sir. Mugen Train or Infinity Castle?")

        self.script = ask
        first = self.chat("find the demon slayer movie and play it")
        self.assertEqual(found["names"], sorted([mugen.name, castle.name]))  # notes.txt is not a video
        self.assertIn("?", first["content"])

        def play(prompt, conv):
            if not tool_results(conv):
                return reply("", [use("file_actions", {"action": "open", "path": str(castle)}, "o1")])
            return reply("Playing Infinity Castle.")

        self.script = play
        with patch("backend.app.tools.pc_tools.FileActionsTool._open",
                   return_value={"success": True, "data": {"opened": str(castle)}, "error": None}) as opener:
            second = self.chat("infinity", first["session_id"])
        opener.assert_called_once()
        self.assertEqual(opener.call_args.args[0], castle)
        self.assertIsNone(second.get("pending_confirmation"), "opening a video never asks")
        self.assertIn("Infinity Castle", second["content"])


class TestCleanDownloads(ApiCase):
    def test_sorts_at_once_and_leaves_unfinished_downloads(self):
        downloads = self.root / "Downloads"
        downloads.mkdir()
        for name in ("movie.mkv", "song.mp3", "photo.jpg", "setup.deb", "big.iso.crdownload"):
            (downloads / name).write_bytes(b"x")
        seen = {}

        def script(prompt, conv):
            results = tool_results(conv)
            if not results:
                return reply("", [use("organize_folder", {"folderpath": str(downloads)}, "o1")])
            seen["result"] = results[0]
            return reply("Sorted 4 files into 4 folders, Sir. One download is still running, left alone.")

        self.script = script
        result = self.chat("clean my downloads")
        # sorting never overwrites and can be undone, so Ultron does not ask
        self.assertIsNone(result.get("pending_confirmation"))
        for rel in ("videos/movie.mkv", "music/song.mp3", "images/photo.jpg", "installers/setup.deb"):
            self.assertTrue((downloads / rel).exists(), rel)
        self.assertTrue((downloads / "big.iso.crdownload").exists())
        self.assertIn("big.iso.crdownload", json.dumps(seen["result"]))  # the AI is told what was left


if __name__ == "__main__":
    unittest.main()


class TestReactStyleJobThroughGeneralHands(ApiCase):
    """'make a React app and start it': the same general shell hand, no special tool.

    No internet in CI, so a tiny fake 'project maker' plays npm create (slow) and a
    fake dev server plays npm run dev. The real terminal path, jobs and approval run.
    """

    def test_slow_setup_is_honest_then_server_runs_in_background_and_stops(self):
        import sys
        project = self.root / "myapp"
        maker = self.root / "maker.py"
        maker.write_text(
            "import pathlib,sys,time\n"
            "p=pathlib.Path(sys.argv[1]); p.mkdir(); time.sleep(2)\n"
            "(p/'package.json').write_text('{}'); print('Done. Now run: npm run dev')\n",
            encoding="utf-8")
        server = self.root / "server.py"
        server.write_text("import time\nprint('Local: http://localhost:5173', flush=True)\ntime.sleep(60)\n",
                          encoding="utf-8")
        py = f'"{sys.executable}"'
        seen = {}

        def setup(prompt, conv):
            results = tool_results(conv)
            if not results:
                return reply("", [use("terminal_run", {"command": f'{py} "{maker}" "{project}"',
                                                      "cwd": str(self.root), "wait_seconds": 1}, "t1")])
            seen["setup"] = results[0]
            return reply("Setting it up, Sir. Still installing; I'll check in a moment.")

        self.script = setup
        first = self.chat("make a react app called myapp")
        self.assertIsNone(first.get("pending_confirmation"), "a normal command does not ask")
        self.assertTrue(seen["setup"]["data"]["running"], "slow step is not killed, and not claimed done")
        job = seen["setup"]["data"]["job_id"]

        import time
        time.sleep(2.5)

        def start(prompt, conv):
            results = tool_results(conv)
            if not results:
                return reply("", [use("terminal_run", {"mode": "status", "job_id": job}, "s1")])
            if len(results) == 1:
                seen["status"] = results[0]
                return reply("", [use("terminal_run", {"command": f'{py} "{server}"', "cwd": str(project),
                                                      "mode": "background"}, "b1")])
            seen["server"] = results[1]
            return reply("Done, Sir. myapp runs at localhost 5173.")

        self.script = start
        second = self.chat("is it ready? then start it", first["session_id"])
        self.assertEqual(seen["status"]["data"]["exit_code"], 0)
        self.assertTrue((project / "package.json").exists())
        self.assertTrue(seen["server"]["data"]["running"])
        self.assertIn("localhost:5173", seen["server"]["data"]["stdout"])
        self.assertIn("5173", second["content"])

        from backend.app.tools import terminal_jobs
        stopped = terminal_jobs.stop(seen["server"]["data"]["job_id"])
        self.assertTrue(stopped["success"], stopped)
