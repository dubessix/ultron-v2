"""Final add list, steps 1 and 2.

1. Safety cap: a bad command must not freeze the owner's 8 GB / 2-core PC.
   RAM cap per job tree, low-memory guard, time cap for normal commands
   (servers in background mode are never timed), low priority.
2. Screen vision: "what's on my screen / read this error" - screenshot (or an
   image file) goes to Gemini only when asked, and the answer comes back.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from backend.app.tools import terminal_jobs

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def run(coro):
    return asyncio.run(coro)


class JobCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patcher = patch.dict(os.environ, {"ULTRON_HOME": self.home.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.jobs = []
        self.addCleanup(self._kill_all)

    def _kill_all(self):
        for job in self.jobs:
            terminal_jobs.kill_now(job["id"])

    def start(self, code: str, **kwargs):
        job = terminal_jobs.start("python job", self.home.name, use_shell=False,
                                  argv=[sys.executable, "-c", code], **kwargs)
        self.jobs.append(job)
        return job

    def guard_until_stopped(self, job, seconds=15.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if job["id"] in terminal_jobs.guard_once():
                return True
            time.sleep(0.3)
        return False


HUNGRY = "a = b'x' * (160 * 1024 * 1024)\nimport time\ntime.sleep(60)"
SLEEPY = "import time\ntime.sleep(60)"


class TestSafetyCap(JobCase):
    def test_memory_hog_is_stopped_and_the_reason_is_told(self):
        with patch.dict(os.environ, {"ULTRON_JOB_MEMORY_MB": "60"}):
            job = self.start(HUNGRY)
            self.assertTrue(self.guard_until_stopped(job), "the 160 MB job was not stopped at a 60 MB cap")
        self.assertEqual(run(terminal_jobs.wait(job["id"], 5)), -9)
        out = terminal_jobs.output(job)
        self.assertIn("[Ultron safety cap] This command was stopped", out["stderr"])
        self.assertIn("limit 0.1 GB", out["stderr"])
        status = terminal_jobs.status(job["id"])["data"]
        self.assertFalse(status["running"])
        self.assertIn("memory", status["stopped_by_safety_cap"])

    def test_normal_job_under_the_cap_is_left_alone(self):
        job = self.start(SLEEPY)
        for _ in range(3):
            self.assertEqual(terminal_jobs.guard_once(), [])
            time.sleep(0.2)
        self.assertIsNone(run(terminal_jobs.wait(job["id"], 0.1)))

    def test_pc_nearly_out_of_memory_stops_the_big_eater(self):
        with patch.object(terminal_jobs, "_available_mb", return_value=100.0), \
                patch.object(terminal_jobs, "LOW_MEMORY_JOB_MB", 50):
            job = self.start(HUNGRY)
            self.assertTrue(self.guard_until_stopped(job))
        self.assertIn("almost out of memory", terminal_jobs.output(job)["stderr"])

    def test_time_cap_for_normal_commands(self):
        with patch.object(terminal_jobs, "time_limit_seconds", return_value=1):
            job = self.start(SLEEPY)
            self.assertTrue(self.guard_until_stopped(job, seconds=6))
        self.assertIn("ran longer than 1 minutes", terminal_jobs.output(job)["stderr"])
        self.assertIn("mode=background", terminal_jobs.output(job)["stderr"])

    def test_background_servers_have_no_time_cap(self):
        with patch.object(terminal_jobs, "time_limit_seconds", return_value=1):
            job = self.start(SLEEPY, timed=False)
            time.sleep(1.6)
            self.assertEqual(terminal_jobs.guard_once(), [])
        self.assertIsNone(run(terminal_jobs.wait(job["id"], 0.1)))

    def test_caps_can_be_switched_off(self):
        with patch.dict(os.environ, {"ULTRON_JOB_MEMORY_MB": "0", "ULTRON_JOB_MAX_MINUTES": "0"}):
            self.assertEqual(terminal_jobs.memory_limit_mb(), 0)
            self.assertEqual(terminal_jobs.time_limit_seconds(), 0)
        with patch.dict(os.environ, {"ULTRON_JOB_MEMORY_MB": "junk"}):
            self.assertEqual(terminal_jobs.memory_limit_mb(), 2048)

    @unittest.skipIf(os.name == "nt", "POSIX niceness")
    def test_jobs_run_at_low_priority(self):
        import psutil

        job = self.start(SLEEPY)
        self.assertGreaterEqual(psutil.Process(job["pid"]).nice(), 10)

    def test_guard_thread_ends_when_nothing_runs(self):
        with patch.object(terminal_jobs, "GUARD_INTERVAL_SECONDS", 0.2):
            job = self.start("print('hi')")
            run(terminal_jobs.wait(job["id"], 5))
            deadline = time.monotonic() + 5
            while terminal_jobs._guard_thread is not None and time.monotonic() < deadline:
                time.sleep(0.1)
        self.assertIsNone(terminal_jobs._guard_thread)

    def test_terminal_run_times_normal_commands_but_not_background(self):
        from backend.app.tools.system_tools import TerminalRunTool

        seen = []

        def fake_start(*args, **kwargs):
            seen.append(kwargs.get("timed"))
            raise OSError("not really")

        tool = TerminalRunTool()
        with patch.dict(os.environ, {"ULTRON_TEST_FULL_ACCESS": "1"}), \
                patch.object(terminal_jobs, "start", side_effect=fake_start):
            run(tool.execute(command="python --version", mode="wait", cwd=self.home.name))
            run(tool.execute(command="python --version", mode="background", cwd=self.home.name))
        self.assertEqual(seen, [True, False])


class TestScreenVision(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.png = Path(self.dir.name) / "error.png"
        self.png.write_bytes(PNG)

    def tool(self):
        from backend.app.tools.pc_tools import ScreenshotTool

        return ScreenshotTool()

    def fake_orchestrator(self, answer="The error says: ModuleNotFoundError: No module named 'flask'."):
        router = AsyncMock()
        router.look_at_image = AsyncMock(return_value=answer)
        orch = type("O", (), {"router": router})()
        return patch("backend.app.router.get_orchestrator", return_value=orch), router

    def test_look_at_an_image_file(self):
        patcher, router = self.fake_orchestrator()
        with patcher:
            result = run(self.tool().execute(image_path=str(self.png), question="read the error"))
        self.assertTrue(result["success"], result)
        self.assertIn("ModuleNotFoundError", result["data"]["seen"])
        image, mime, question = router.look_at_image.call_args.args
        self.assertEqual((image, mime, question), (PNG, "image/png", "read the error"))

    def test_screenshot_with_a_question_looks_at_the_new_picture(self):
        patcher, router = self.fake_orchestrator("A Chrome window with YouTube open.")
        tool = self.tool()
        shot = {"success": True, "data": {"saved_to": str(self.png), "size_kb": 1}, "error": None}
        with patcher, patch.object(tool, "_capture", AsyncMock(return_value=shot)):
            result = run(tool.execute(question="what's on my screen?"))
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["saved_to"], str(self.png))
        self.assertEqual(result["data"]["seen"], "A Chrome window with YouTube open.")

    def test_plain_screenshot_does_not_call_the_ai(self):
        patcher, router = self.fake_orchestrator()
        tool = self.tool()
        shot = {"success": True, "data": {"saved_to": str(self.png), "size_kb": 1}, "error": None}
        with patcher, patch.object(tool, "_capture", AsyncMock(return_value=shot)):
            result = run(tool.execute())
        self.assertEqual(result, shot)
        router.look_at_image.assert_not_called()  # 0 tokens unless he asks

    def test_failed_capture_is_not_sent(self):
        patcher, router = self.fake_orchestrator()
        tool = self.tool()
        failed = {"success": False, "data": {}, "error": "No screenshot program worked."}
        with patcher, patch.object(tool, "_capture", AsyncMock(return_value=failed)):
            self.assertEqual(run(tool.execute(question="what is this")), failed)
        router.look_at_image.assert_not_called()

    def test_wrong_files_get_a_plain_answer(self):
        text = Path(self.dir.name) / "notes.txt"
        text.write_text("hi")
        self.assertIn("not a picture", run(self.tool().execute(image_path=str(text)))["error"])
        self.assertIn("No image file", run(self.tool().execute(image_path="/nope/x.png"))["error"])

    def test_vision_trouble_is_said_honestly(self):
        router = AsyncMock()
        router.look_at_image = AsyncMock(side_effect=RuntimeError("Every Gemini key is busy right now."))
        orch = type("O", (), {"router": router})()
        with patch("backend.app.router.get_orchestrator", return_value=orch):
            result = run(self.tool().execute(image_path=str(self.png), question="read it"))
        self.assertFalse(result["success"])
        self.assertIn("could not look at it: Every Gemini key is busy", result["error"])


class TestGeminiVisionCall(unittest.TestCase):
    def router(self, handler, keys=("real-gemini-key-aaaa",)):
        from backend.app.brain.llm_router import LLMRouter

        env = {f"GEMINI_API_KEY_{i + 1}": key for i, key in enumerate(keys)}
        clean = {k: "" for k in os.environ if k.startswith(("GEMINI_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY"))}
        with patch.dict(os.environ, {**clean, **env}):
            router = LLMRouter()
        router.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return router

    def test_sends_the_picture_inline_and_returns_the_text(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("x-goog-api-key")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "It says 404."}]}}]})

        router = self.router(handler)
        answer = run(router.look_at_image(PNG, "image/png", "read the page"))
        self.assertEqual(answer, "It says 404.")
        self.assertNotIn("key=", seen["url"])  # the key never goes in a URL (logs)
        self.assertEqual(seen["key"], "real-gemini-key-aaaa")
        parts = seen["body"]["contents"][0]["parts"]
        self.assertIn("Question: read the page", parts[0]["text"])
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(parts[1]["inlineData"]["data"]), PNG)

    def test_no_gemini_key_is_a_clear_message(self):
        router = self.router(lambda request: httpx.Response(500), keys=())
        with self.assertRaisesRegex(RuntimeError, "needs a Gemini key"):
            run(router.look_at_image(PNG, "image/png", "x"))

    def test_rate_limited_key_moves_to_the_next_key(self):
        calls = []

        def handler(request):
            calls.append(request.headers.get("x-goog-api-key"))
            if len(calls) == 1:
                return httpx.Response(429, headers={"retry-after": "30"}, json={"error": {"message": "slow down"}})
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

        router = self.router(handler, keys=("real-gemini-key-aaaa", "real-gemini-key-bbbb"))
        self.assertEqual(run(router.look_at_image(PNG, "image/png", "x")), "ok")
        self.assertEqual(calls, ["real-gemini-key-aaaa", "real-gemini-key-bbbb"])

    def test_empty_or_huge_pictures_are_refused(self):
        router = self.router(lambda request: httpx.Response(500))
        with self.assertRaisesRegex(RuntimeError, "empty"):
            run(router.look_at_image(b"", "image/png", "x"))
        with self.assertRaisesRegex(RuntimeError, "too big"):
            run(router.look_at_image(b"x" * (15 * 1024 * 1024 + 1), "image/png", "x"))


if __name__ == "__main__":
    unittest.main()
