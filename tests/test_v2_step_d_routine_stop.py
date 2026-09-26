"""V2 Step D: owner routines ("coding mode") and "stop / ruko" while a job runs."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml

from backend.app.core import stop_signal
from backend.app.core.live_progress import line_for
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.tools import routine_tool, terminal_jobs
from backend.app.tools.context_builder import ToolContextBuilder
from backend.app.tools.system_tools import TerminalRunTool
from backend.app.tools.tool_registry import ToolRegistry

PY = f'"{sys.executable}"'


class TempHome(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.work, True)
        self.file = self.work / "routines.yaml"
        for target, value in (("backend.app.tools.routine_tool.routines_path", lambda: self.file),
                              ("backend.app.tools.routine_tool._vscode_storage_files", lambda: [self.work / "storage.json"])):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def write(self, data):
        self.file.write_text(yaml.safe_dump(data), encoding="utf-8")


class TestRoutineFile(TempHome):
    def test_first_use_writes_an_editable_file_with_coding_mode(self):
        routines = routine_tool.load_routines()
        self.assertTrue(self.file.exists())
        self.assertIn("coding mode", routines)
        self.assertIn("normal mode", routines)
        tools = [step["tool"] for step in routines["coding mode"]]
        self.assertIn("terminal_run", tools)
        self.assertIn("open_url", tools)
        registered = set(ToolRegistry().get_registered_ids())
        for steps in routines.values():
            for step in steps:
                self.assertIn(step["tool"], registered, step)  # every default step is a real tool

    def test_each_os_gets_its_own_terminal_step(self):
        steps = routine_tool.load_routines()["coding mode"]
        mine = [s for s in steps if routine_tool._for_this_os(s)]
        terminals = [s for s in mine if s.get("say") == "a terminal there"]
        self.assertEqual(len(terminals), 1)

    def test_last_project_comes_from_vscode_then_recent_folder_then_home(self):
        project = self.work / "my app"
        project.mkdir()
        uri = "file://" + ("/" if os.name == "nt" else "") + project.as_posix().replace(" ", "%20")
        (self.work / "storage.json").write_text(json.dumps({"windowsState": {"lastActiveWindow": {"folder": uri}}}))
        self.assertEqual(Path(routine_tool.last_project()), project)
        (self.work / "storage.json").write_text("{broken")
        with patch("backend.app.core.recent_folders.last", return_value=str(self.work)):
            self.assertEqual(routine_tool.last_project(), str(self.work))
        with patch("backend.app.core.recent_folders.last", return_value=None):
            self.assertEqual(routine_tool.last_project(), str(Path.home()))

    def test_broken_or_huge_file_is_an_honest_error(self):
        self.file.write_text("just words", encoding="utf-8")
        result = asyncio.run(routine_tool.RoutineTool().execute(name="coding mode"))
        self.assertFalse(result["success"])
        self.file.write_text("x: [" + "1," * 40000 + "]", encoding="utf-8")
        result = asyncio.run(routine_tool.RoutineTool().execute(name="coding mode"))
        self.assertFalse(result["success"])
        self.assertIn("too big", result["error"])


class TestRunningARoutine(TempHome):
    async def run_routine(self, name, results):
        calls = []

        async def fake(self_registry, tool_id, args, **kwargs):
            calls.append((tool_id, args, kwargs.get("owner_approved")))
            return results.get(tool_id, {"success": True, "data": {}, "error": None})

        with patch.object(ToolRegistry, "execute_tool", fake):
            result = await routine_tool.RoutineTool().execute(name=name)
        return result, calls

    async def test_steps_run_in_order_and_a_failure_does_not_stop_the_rest(self):
        self.write({"study mode": [
            {"say": "notes", "tool": "file_actions", "args": {"action": "open", "path": "{project}"}},
            {"say": "music", "tool": "open_url", "args": {"url": "https://example.com"}},
            {"say": "pop-up", "tool": "notify", "args": {"message": "focus"}},
        ]})
        with patch("backend.app.tools.routine_tool.last_project", return_value="/tmp/proj"):
            result, calls = await self.run_routine("Study Mode please", {
                "open_url": {"success": False, "data": {}, "error": "no browser"}})
        self.assertEqual([c[0] for c in calls], ["file_actions", "open_url", "notify"])
        self.assertEqual(calls[0][1]["path"], "/tmp/proj")  # {project} filled in
        self.assertTrue(all(c[2] for c in calls))  # the owner asked for it: owner-approved
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["done"], ["notes", "pop-up"])
        self.assertEqual(result["data"]["failed"], [{"step": "music", "error": "no browser"}])

    async def test_level_3_steps_are_never_run_from_a_routine(self):
        self.write({"danger mode": [{"say": "wipe", "tool": "delete_folder", "args": {"folderpath": "/tmp/x"}},
                                    {"say": "pop-up", "tool": "notify", "args": {"message": "hi"}}]})
        pending = {"success": False, "status": "PENDING_CONFIRMATION", "confirmation_token": "tok"}
        with patch("backend.app.security.pending_actions.PendingActionRegistry.claim") as claim:
            result, _ = await self.run_routine("danger mode", {"delete_folder": pending})
        self.assertEqual(result["data"]["needs_your_yes"], ["wipe"])
        self.assertEqual(result["data"]["done"], ["pop-up"])
        claim.assert_called_once()  # the unanswered question is withdrawn
        self.assertTrue(claim.call_args.kwargs.get("cancel"))

    async def test_unknown_or_blocked_tools_are_reported_not_run(self):
        self.write({"odd mode": [{"tool": "routine", "args": {"name": "odd mode"}},
                                 {"tool": "rm_rf_everything"},
                                 {"tool": "switch_mode", "args": {"to": "coding"}}]})
        result, calls = await self.run_routine("odd mode", {})
        self.assertEqual(calls, [])
        self.assertFalse(result["success"])
        self.assertEqual(len(result["data"]["failed"]), 3)

    async def test_unknown_name_lists_what_exists_and_list_action(self):
        routine_tool.load_routines()
        result = await routine_tool.RoutineTool().execute(name="party mode")
        self.assertFalse(result["success"])
        self.assertIn("coding mode", result["error"])
        listed = await routine_tool.RoutineTool().execute(action="list")
        self.assertIn("coding mode", listed["data"]["routines"])

    async def test_stop_mid_routine_starts_nothing_more(self):
        self.write({"long mode": [{"say": f"s{i}", "tool": "notify", "args": {"message": str(i)}} for i in range(5)]})
        stop_signal.begin()
        calls = []

        async def fake(self_registry, tool_id, args, **kwargs):
            calls.append(args["message"])
            if len(calls) == 2:
                stop_signal.request()
            return {"success": True, "data": {}, "error": None}

        with patch.object(ToolRegistry, "execute_tool", fake):
            result = await routine_tool.RoutineTool().execute(name="long mode")
        self.assertEqual(calls, ["0", "1"])
        self.assertIn("stopped", result["data"])

    async def test_real_tool_runs_through_the_real_registry(self):
        self.write({"check mode": [{"say": "pc check", "tool": "system_metrics", "args": {}}]})
        result = await routine_tool.RoutineTool().execute(name="check mode")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["done"], ["pc check"])


class TestStopSignal(unittest.IsolatedAsyncioTestCase):
    async def test_stop_only_hits_jobs_already_running(self):
        async def job():
            stop_signal.begin()
            await asyncio.sleep(0.05)
            return stop_signal.requested()

        running = asyncio.create_task(job())
        await asyncio.sleep(0.01)
        stop_signal.request()
        self.assertTrue(await running)
        self.assertFalse(await asyncio.create_task(job()), "the next job starts clean")

    async def test_no_job_no_stop(self):
        self.assertFalse(await asyncio.create_task(asyncio.sleep(0, result=stop_signal.requested())))


class TestStopInTheJobLoop(unittest.IsolatedAsyncioTestCase):
    async def test_stop_after_the_first_step_runs_nothing_more(self):
        orchestrator = CognitiveOrchestrator()
        executed = []

        async def fake_exec(call, **kwargs):
            executed.append(call["name"])
            stop_signal.request()  # owner says "ruko" while the first step runs
            return call["arguments"], {"success": True, "data": {}, "error": None}

        orchestrator._execute_native_agent_call = fake_exec
        two = {"content": "", "provider": "groq", "model": "t", "native_tools": True, "provider_state": None,
               "tool_calls": [{"id": "a", "name": "list_contents", "arguments": {"folderpath": "~"}},
                              {"id": "b", "name": "organize_folder", "arguments": {"folderpath": "~"}}]}
        orchestrator.router.get_completions_with_tools = AsyncMock(return_value=two)
        stop_signal.begin()
        result = await orchestrator._run_native_agent_loop(
            two, system_prompt="s", user_prompt="clean up", tools=[], session_id="stop-test",
            project_id="personal", project_root=str(Path.home()), coding_turn=False, provider_for_turn="groq")
        await orchestrator.close()
        self.assertEqual(executed, ["list_contents"])
        self.assertTrue(result["stopped"])
        self.assertTrue(result["content"].startswith("Stopped, Sir."))
        orchestrator.router.get_completions_with_tools.assert_not_awaited()


class TestStopEndsAWaitingCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.work, True)
        env = patch.dict(os.environ, {"ULTRON_TEST_FULL_ACCESS": "1"})
        env.start()
        self.addCleanup(env.stop)

    async def test_stop_kills_the_command_the_job_is_waiting_on(self):
        stop_signal.begin()
        marker = self.work / "finished.txt"
        code = f"import time,pathlib; time.sleep(6); pathlib.Path(r'{marker}').write_text('x')"
        asyncio.get_running_loop().call_later(0.8, stop_signal.request)
        started = time.monotonic()
        result = await TerminalRunTool().execute(command=f'{PY} -c "{code}"', cwd=str(self.work), wait_seconds=30)
        self.assertLess(time.monotonic() - started, 4.0)
        self.assertFalse(result["success"])
        self.assertIn("you said stop", result["error"])
        job = result["data"]["job_id"]
        for _ in range(40):
            if not terminal_jobs.status(job)["data"]["running"]:
                break
            await asyncio.sleep(0.1)
        self.assertFalse(terminal_jobs.status(job)["data"]["running"])
        await asyncio.sleep(0.2)
        self.assertFalse(marker.exists())


class TestWiring(unittest.TestCase):
    def test_api_stop_endpoint(self):
        from fastapi.testclient import TestClient

        from backend.app.main import app

        before = stop_signal._stop_at
        with TestClient(app) as client:
            response = client.post("/api/stop")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["stopping"])
        self.assertGreater(stop_signal._stop_at, before)

    def test_owner_words_bring_the_routine_tool_and_a_plain_line(self):
        ids = ToolRegistry().get_registered_ids()
        for prompt in ("coding mode", "start coding mode", "study mode on"):
            self.assertIn("routine", ToolContextBuilder.select_relevant_tool_ids(prompt, ids), prompt)
        self.assertEqual(line_for("routine", {"name": "coding mode"}), "Starting coding mode")


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(os.name == "nt", "the Linux default steps")
class TestCodingModeForReal(TempHome):
    """The real default 'coding mode' through the real tools and real shell, with
    stand-in programs that record what they were asked to do."""

    async def test_default_coding_mode_opens_editor_terminal_music_and_quiets_notifications(self):
        bin_dir = self.work / "bin"
        bin_dir.mkdir()
        log = self.work / "calls.log"
        for name in ("code", "gnome-terminal", "gsettings", "fakebrowser"):
            script = bin_dir / name
            script.write_text(f'#!/bin/sh\necho "{name} $* @ $(pwd)" >> "{log}"\n', encoding="utf-8")
            script.chmod(0o755)
        project = self.work / "proj"
        project.mkdir()
        env = patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                                      "BROWSER": str(bin_dir / "fakebrowser"), "ULTRON_TEST_FULL_ACCESS": "1"})
        env.start()
        self.addCleanup(env.stop)
        import webbrowser

        webbrowser._tryorder = None  # re-read $BROWSER
        with patch("backend.app.tools.routine_tool.last_project", return_value=str(project)):
            result = await routine_tool.RoutineTool().execute(name="coding mode")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["failed"], [], result)
        self.assertEqual(result["data"]["done"],
                         ["VS Code in your project", "a terminal there", "lofi music", "notifications quiet"])
        for _ in range(40):  # background steps finish on their own
            text = log.read_text() if log.exists() else ""
            if text.count("\n") >= 4:
                break
            await asyncio.sleep(0.1)
        text = log.read_text()
        self.assertIn(f"code . @ {project}", text)
        self.assertIn(f"gnome-terminal --working-directory={project} @ {project}", text)
        self.assertIn("gsettings set org.gnome.desktop.notifications show-banners false", text)
        self.assertIn("fakebrowser https://www.youtube.com/watch?v=jfKfPfyJRdk", text)
