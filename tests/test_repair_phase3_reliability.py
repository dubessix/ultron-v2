"""Regression tests for sequential coding, safe writes and terminal cleanup."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.runtime_paths import isolated_test_artifact_path
from backend.app.security.pending_actions import get_pending_action_registry
from backend.app.tools.system_tools import (
    MAX_TERMINAL_OUTPUT_BYTES,
    TerminalRunTool,
    _normalized_executable_name,
)
from backend.app.tools.tool_base import BaseTool
from backend.app.tools.tool_registry import ToolRegistry


class EmptyArgs(BaseModel):
    pass


class CountingFailTool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_id="counting_fail",
            name="Counting Fail",
            description="test",
            category="test",
            tags=["test"],
            permission_level=0,
            args_model=EmptyArgs,
            usage_examples=[],
        )
        self.calls = 0

    async def execute(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("expected failure")


class TestNoAutomaticRetry(unittest.IsolatedAsyncioTestCase):
    async def test_default_registry_execution_attempts_side_effect_once(self):
        registry = ToolRegistry()
        tool = CountingFailTool()
        registry.register(tool)
        result = await registry.execute_tool(tool.id, {})
        self.assertFalse(result["success"])
        self.assertEqual(tool.calls, 1)
        self.assertIn("ExecutionCrash", result["error"])


class TestSequentialOrchestration(unittest.IsolatedAsyncioTestCase):
    async def test_non_coding_tools_run_in_declared_order_not_parallel(self):
        orchestrator = CognitiveOrchestrator()
        events = []
        completion_calls = 0

        async def fake_completion(**_kwargs):
            nonlocal completion_calls
            completion_calls += 1
            if completion_calls == 1:
                return (
                    "Checking.\n[TOOL_CALLS_START]\n"
                    + json.dumps([
                        {"tool_id": "system_metrics", "args": {}},
                        {"tool_id": "weather_tool", "args": {}},
                    ])
                    + "\n[TOOL_CALLS_END]"
                )
            return "Both checks failed safely."

        async def fake_execute(_self, tool_id, **_kwargs):
            events.append(f"start:{tool_id}")
            await asyncio.sleep(0.03)
            events.append(f"end:{tool_id}")
            return {"success": False, "data": {}, "error": "test failure", "metadata": {}}

        orchestrator.router.get_completions = fake_completion
        with patch.object(ToolRegistry, "execute_tool", fake_execute):
            await orchestrator.process_request("plan weather and system status", "phase3_order")
        await orchestrator.close()

        self.assertEqual(
            events,
            [
                "start:system_metrics", "end:system_metrics",
                "start:weather_tool", "end:weather_tool",
            ],
        )

    async def test_coding_stops_after_first_incomplete_step(self):
        orchestrator = CognitiveOrchestrator()
        executed = []
        completion_calls = 0

        async def fake_completion(**_kwargs):
            nonlocal completion_calls
            completion_calls += 1
            if completion_calls == 1:
                return (
                    "Working.\n[TOOL_CALLS_START]\n"
                    + json.dumps([
                        {"tool_id": "file_read", "args": {"filepath": "backend/app/main.py"}},
                        {"tool_id": "file_write", "args": {"filepath": "backend/app/example.py", "content": "VALUE=1\n"}},
                    ])
                    + "\n[TOOL_CALLS_END]"
                )
            return "Stopped after the failed inspection."

        async def fake_execute(_self, tool_id, **_kwargs):
            executed.append(tool_id)
            return {"success": False, "data": {}, "error": "inspection failed", "metadata": {}}

        orchestrator.router.get_completions = fake_completion
        with patch.object(ToolRegistry, "execute_tool", fake_execute):
            await orchestrator.process_request("write code file module", "phase3_stop")
        await orchestrator.close()

        self.assertEqual(executed, ["file_read"])

    async def test_existing_file_write_requires_successful_inspection(self):
        target = isolated_test_artifact_path("phase3_inspection", "existing.py")
        target.write_text("VALUE = 1\n", encoding="utf-8")
        orchestrator = CognitiveOrchestrator()
        orchestrator.memory.gate.should_save = lambda _prompt: False
        calls = 0

        async def fake_completion(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return (
                    "Working.\n[TOOL_CALLS_START]\n"
                    + json.dumps([{
                        "tool_id": "file_write",
                        "args": {"filepath": str(target), "content": "VALUE = 2\n"},
                    }])
                    + "\n[TOOL_CALLS_END]"
                )
            return "Inspection required."

        orchestrator.router.get_completions = fake_completion
        result = await orchestrator.process_request(
            "write code file module", "phase3_inspection_missing"
        )
        self.assertIsNone(result["pending_confirmation"])
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")
        await orchestrator.close()

    async def test_read_then_write_reaches_exact_confirmation(self):
        target = isolated_test_artifact_path("phase3_inspection", "read_first.py")
        target.write_text("VALUE = 1\n", encoding="utf-8")
        orchestrator = CognitiveOrchestrator()
        orchestrator.memory.gate.should_save = lambda _prompt: False
        calls = 0

        async def fake_completion(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return (
                    "Working.\n[TOOL_CALLS_START]\n"
                    + json.dumps([
                        {"tool_id": "file_read", "args": {"filepath": str(target)}},
                        {"tool_id": "file_write", "args": {"filepath": str(target), "content": "VALUE = 2\n"}},
                    ])
                    + "\n[TOOL_CALLS_END]"
                )
            if calls == 2:
                return "Inspected the existing file."
            return "Waiting for exact confirmation."

        orchestrator.router.get_completions = fake_completion
        result = await orchestrator.process_request(
            "write code file module", "phase3_inspection_ok"
        )
        self.assertIsNotNone(result["pending_confirmation"])
        self.assertEqual(result["pending_confirmation"]["tool_id"], "file_write")
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")
        await orchestrator.close()


class TestVerifiedAtomicWrites(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        get_pending_action_registry().clear()
        self.registry = ToolRegistry()
        self.session = "phase3_write"

    async def _confirmed_write(self, target: Path, content: str):
        args = {"filepath": str(target), "content": content}
        pending = await self.registry.execute_tool("file_write", args, session_id=self.session)
        return await self.registry.execute_tool(
            "file_write",
            args,
            has_confirmed=True,
            confirmation_token=pending["confirmation_token"],
            session_id=self.session,
        )

    async def test_invalid_python_never_replaces_original(self):
        target = isolated_test_artifact_path("phase3_write", "module.py")
        target.write_text("VALUE = 1\n", encoding="utf-8")
        result = await self._confirmed_write(target, "def broken(:\n")
        self.assertFalse(result["success"])
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")
        self.assertTrue(result["data"]["original_preserved"])

    async def test_invalid_new_python_is_not_created(self):
        target = isolated_test_artifact_path("phase3_write", "new_bad.py")
        target.unlink(missing_ok=True)
        result = await self._confirmed_write(target, "if True print('bad')\n")
        self.assertFalse(result["success"])
        self.assertFalse(target.exists())

    async def test_valid_python_is_verified_backed_up_and_replaced(self):
        target = isolated_test_artifact_path("phase3_write", "valid.py")
        target.write_text("VALUE = 1\n", encoding="utf-8")
        result = await self._confirmed_write(target, "VALUE = 2\n")
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["verification"]["verified"])
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")
        self.assertEqual(Path(result["data"]["backup"]).read_text(encoding="utf-8"), "VALUE = 1\n")


class TestTerminalBoundsAndCleanup(unittest.IsolatedAsyncioTestCase):
    def test_windows_executable_path_normalizes_to_allowlist_name(self):
        self.assertEqual(_normalized_executable_name(r"C:\\Python312\\python.exe"), "python")
        self.assertEqual(_normalized_executable_name(r"C:\\Node\\npm.cmd"), "npm")

    async def test_unlisted_executable_is_blocked(self):
        result = await TerminalRunTool().execute(command="uname -a")
        self.assertFalse(result["success"])
        self.assertIn("terminal_allowed_commands", result["error"])

    async def test_output_is_bounded_while_pipe_is_fully_drained(self):
        tool = TerminalRunTool()
        command = f'{sys.executable} -c "print(\'x\' * {MAX_TERMINAL_OUTPUT_BYTES + 10000})"'
        result = await tool.execute(command=command)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["stdout_truncated"])
        self.assertLessEqual(
            len(result["data"]["stdout"].encode("utf-8")),
            MAX_TERMINAL_OUTPUT_BYTES + 64,
        )

    async def test_registry_timeout_kills_child_process_group(self):
        registry = ToolRegistry()
        work = isolated_test_artifact_path("phase3_terminal")
        work.mkdir(parents=True, exist_ok=True)
        marker = work / "orphan_marker.txt"
        runner = work / "spawn_child.py"
        child_code = (
            "import time,pathlib; time.sleep(1); "
            f"pathlib.Path({str(marker)!r}).write_text('orphan')"
        )
        runner.write_text(
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            "time.sleep(5)\n",
            encoding="utf-8",
        )
        args = {"command": f"{sys.executable} {runner}", "cwd": str(work)}
        pending = await registry.execute_tool(
            "terminal_run", args, session_id="phase3_terminal"
        )
        result = await registry.execute_tool(
            "terminal_run",
            args,
            has_confirmed=True,
            confirmation_token=pending["confirmation_token"],
            session_id="phase3_terminal",
            timeout=0.2,
            max_retries=0,
        )
        self.assertFalse(result["success"])
        self.assertIn("TimeoutError", result["error"])
        await asyncio.sleep(1.3)
        self.assertFalse(marker.exists(), "child survived cancellation and wrote the marker")


if __name__ == "__main__":
    unittest.main()
