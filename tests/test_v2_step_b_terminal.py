"""V2 Step B1-B3: one general terminal hand that never hangs and never lies.

  * slow jobs are not killed: after the wait they keep running as a job
  * background mode for servers / GUI programs, status + stop by id
  * programs can not wait for typing (stdin closed, CI=1 ...)
  * the AI sees head + tail of long output, the full log stays on disk
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.tools import terminal_jobs
from backend.app.tools.system_tools import MAX_WAIT_SECONDS, TerminalRunTool

PY = f'"{sys.executable}"'


class TerminalCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.work, True)
        env = patch.dict(os.environ, {"ULTRON_TEST_FULL_ACCESS": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.tool = TerminalRunTool()

    async def run_cmd(self, command, **kwargs):
        return await self.tool.execute(command=command, cwd=str(self.work), **kwargs)

    async def asyncTearDown(self):
        for row in terminal_jobs.status()["data"]["jobs"]:
            if row["running"]:
                await asyncio.to_thread(terminal_jobs.stop, row["job_id"])


class TestWaitMode(TerminalCase):
    async def test_quick_command_returns_output_and_exit_code(self):
        result = await self.run_cmd(f"{PY} -c \"print('hello')\"")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["exit_code"], 0)
        self.assertEqual(result["data"]["stdout"], "hello")

    async def test_failure_is_reported_with_the_real_error(self):
        result = await self.run_cmd(f"{PY} -c \"import sys; sys.stderr.write('boom'); sys.exit(3)\"")
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["exit_code"], 3)
        self.assertIn("boom", result["error"])

    async def test_slow_job_is_not_killed_it_keeps_running(self):
        marker = self.work / "done.txt"
        code = f"import time,pathlib; time.sleep(2); pathlib.Path(r'{marker}').write_text('ok')"
        started = time.monotonic()
        result = await self.run_cmd(f'{PY} -c "{code}"', wait_seconds=1)
        self.assertLess(time.monotonic() - started, 1.9, "the turn does not wait for the whole job")
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["running"])
        self.assertIn("Not finished yet", result["data"]["note"])  # the AI is told to be honest
        job = result["data"]["job_id"]
        for _ in range(40):
            state = terminal_jobs.status(job)["data"]
            if not state["running"]:
                break
            await asyncio.sleep(0.2)
        self.assertEqual(state["exit_code"], 0)
        self.assertEqual(marker.read_text(), "ok")

    async def test_program_asking_for_input_ends_at_once(self):
        started = time.monotonic()
        result = await self.run_cmd(f"{PY} -c \"input('Project name? ')\"", wait_seconds=20)
        self.assertLess(time.monotonic() - started, 10)
        self.assertFalse(result["success"])
        self.assertIn("EOF", result["error"])

    async def test_no_question_variables_are_set(self):
        result = await self.run_cmd(f"{PY} -c \"import os; print(os.environ.get('CI'), os.environ.get('GIT_TERMINAL_PROMPT'))\"")
        self.assertEqual(result["data"]["stdout"], "1 0")

    async def test_long_output_head_and_tail_only(self):
        result = await self.run_cmd(f"{PY} -c \"[print('line', i) for i in range(20000)]\"")
        out = result["data"]["stdout"]
        self.assertTrue(result["data"]["stdout_truncated"])
        self.assertIn("line 0", out)
        self.assertIn("line 19999", out)
        self.assertIn("middle skipped", out)
        self.assertLess(len(out), 6000)  # few tokens for the AI
        self.assertTrue(Path(result["data"]["log"]).stat().st_size > 100000)  # full log kept

    async def test_missing_program_says_so_clearly(self):
        result = await self.run_cmd("surely-not-installed-program-xyz --version")
        self.assertFalse(result["success"])
        self.assertIn("not installed", result["error"])

    def test_wait_limit_is_bounded(self):
        self.assertLessEqual(MAX_WAIT_SECONDS, 120)
        self.assertGreater(self.tool.max_runtime_seconds, MAX_WAIT_SECONDS)


class TestBackgroundJobs(TerminalCase):
    async def test_server_stays_up_after_the_reply_and_stop_kills_the_tree(self):
        child = "import time; time.sleep(60)"
        parent = (f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','{child}']); "
                  "print('ready', flush=True); time.sleep(60)")
        result = await self.run_cmd(f'{PY} -c "{parent}"', mode="background")
        self.assertTrue(result["success"], result)
        self.assertTrue(result["data"]["running"])
        job = result["data"]["job_id"]
        import psutil
        proc = psutil.Process(result["data"]["pid"])
        for _ in range(30):
            if proc.children(recursive=True):
                break
            await asyncio.sleep(0.1)
        family = proc.children(recursive=True) + [proc]
        self.assertGreaterEqual(len(family), 2)

        listed = await self.tool.execute(mode="status")
        self.assertIn(job, [row["job_id"] for row in listed["data"]["jobs"]])
        stopped = await self.tool.execute(mode="stop", job_id=job)
        self.assertTrue(stopped["success"], stopped)
        await asyncio.sleep(0.3)
        for member in family:
            self.assertFalse(member.is_running() and member.status() != psutil.STATUS_ZOMBIE)

    async def test_instant_crash_in_background_is_reported(self):
        result = await self.run_cmd(f"{PY} -c \"raise SystemExit('bad port')\"", mode="background")
        self.assertFalse(result["success"])
        self.assertIn("bad port", result["error"])

    async def test_stop_unknown_job(self):
        result = await self.tool.execute(mode="stop", job_id="nope1234")
        self.assertFalse(result["success"])
        result = await self.tool.execute(mode="stop")
        self.assertFalse(result["success"])


class TestLogsStaySmallForYears(unittest.TestCase):
    def test_huge_log_is_trimmed(self):
        path = Path(tempfile.mkdtemp()) / "big.log"
        self.addCleanup(shutil.rmtree, path.parent, True)
        path.write_bytes(b"x" * 5000 + b"LAST LINE")
        with patch.object(terminal_jobs, "MAX_LOG_BYTES", 1000), patch.object(terminal_jobs, "TRIMMED_KEEP_BYTES", 100):
            terminal_jobs._trim(str(path))
        text = path.read_text()
        self.assertLess(len(text), 200)
        self.assertTrue(text.endswith("LAST LINE"))


class TestRegistryUsesTheToolsOwnLimit(unittest.IsolatedAsyncioTestCase):
    async def test_tool_limit_replaces_the_30s_default(self):
        from backend.app.tools.tool_registry import ToolRegistry

        registry = ToolRegistry()
        tool = registry.get_tool("clipboard")

        async def slow(**_kwargs):
            await asyncio.sleep(1)
            return {"success": True, "data": {}, "error": None}

        with patch.object(tool, "execute", slow), patch.object(tool, "max_runtime_seconds", 0.2, create=True), \
                patch.object(registry, "get_tool", return_value=tool):
            result = await registry.execute_tool("clipboard", {"action": "read"}, owner_approved=True)
        self.assertIn("0.2", str(result.get("error")))


if __name__ == "__main__":
    unittest.main()


class TestShellBuiltins(TerminalCase):
    async def test_builtins_run_through_the_shell(self):
        result = await self.run_cmd("echo hello-builtin")
        self.assertTrue(result["success"], result)
        self.assertIn("hello-builtin", result["data"]["stdout"])
        result = await self.run_cmd("cd")
        self.assertNotIn("not installed", str(result.get("error")))
