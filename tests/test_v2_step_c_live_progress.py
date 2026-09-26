"""V2 Step C7: Ultron says what he is doing while tools run (like IRIS / Stonic)."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from backend.app.core import live_progress


class FakeManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, channel, event):
        self.events.append((channel, event))
        return 1


class TestLines(unittest.TestCase):
    def test_plain_short_words(self):
        self.assertEqual(live_progress.line_for("apps", {"action": "open", "name": "chrome"}), "Opening chrome")
        self.assertEqual(live_progress.line_for("list_contents", {"folderpath": "/home/debjeet-dhar/Downloads/"}),
                         "Looking inside Downloads")
        self.assertEqual(live_progress.line_for("terminal_run", {"command": "npm install"}), "Running npm install")
        self.assertEqual(live_progress.line_for("close_tab", {"which": "youtube"}), "Closing the youtube tab")
        self.assertEqual(live_progress.line_for("close_tab", {}), "Closing the tab")
        self.assertIn("with some new tool", live_progress.line_for("some_new_tool", {}))

    def test_voice_never_gets_symbols(self):
        line = live_progress.line_for("terminal_run", {"command": "cat a.txt | grep {x} > out && rm -rf /tmp/*"})
        for bad in "|{}>&*/":
            self.assertNotIn(bad, line)
        self.assertLessEqual(len(line), 50)

    def test_preamble_only_when_short_plain_words(self):
        self.assertEqual(live_progress.spoken_preamble("  Opening your Downloads, Sir. "), "Opening your Downloads, Sir.")
        self.assertIsNone(live_progress.spoken_preamble(""))
        self.assertIsNone(live_progress.spoken_preamble('{"tool": "x"}'))
        self.assertIsNone(live_progress.spoken_preamble("x" * 200))


class TestTiming(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = FakeManager()
        live_progress.set_manager(self.manager)
        self.addCleanup(live_progress.set_manager, None)

    def spoken(self):
        return [e for _c, e in self.manager.events if e["speak"]]

    async def test_quick_step_is_shown_but_never_spoken(self):
        with patch.object(live_progress, "SLOW_SECONDS", 0.2):
            step = await live_progress.Step("apps", {"action": "open", "name": "chrome"}, "s1").start()
            await asyncio.sleep(0.05)
            step.done()
            await asyncio.sleep(0.3)
        self.assertEqual(len(self.manager.events), 1)
        channel, event = self.manager.events[0]
        self.assertEqual(channel, "events")
        self.assertEqual(event, {"type": "ultron_progress", "text": "Opening chrome", "speak": False,
                                 "tool": "apps", "session_id": "s1"})

    async def test_slow_step_speaks_once(self):
        with patch.object(live_progress, "SLOW_SECONDS", 0.1):
            step = await live_progress.Step("terminal_run", {"command": "npm install"}, "s1").start()
            await asyncio.sleep(0.3)
            step.done()
        self.assertEqual([e["text"] for e in self.spoken()], ["Running npm install"])

    async def test_brains_own_words_are_used(self):
        with patch.object(live_progress, "PREAMBLE_SECONDS", 0.05):
            step = await live_progress.Step("find_files", {"pattern": "x"}, "s1", "Let me look for it, Sir.").start()
            await asyncio.sleep(0.2)
            step.done()
        self.assertEqual(self.manager.events[0][1]["text"], "Let me look for it, Sir.")
        self.assertEqual([e["text"] for e in self.spoken()], ["Let me look for it, Sir."])

    async def test_no_screen_connected_is_fine(self):
        live_progress.set_manager(None)
        step = await live_progress.Step("apps", {}, "s1").start()
        step.done()


class TestAgentLoopTalks(unittest.IsolatedAsyncioTestCase):
    async def test_native_loop_announces_each_tool(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        manager = FakeManager()
        live_progress.set_manager(manager)
        self.addCleanup(live_progress.set_manager, None)
        orchestrator = CognitiveOrchestrator.__new__(CognitiveOrchestrator)
        orchestrator.max_agent_steps, orchestrator.max_coding_steps = 5, 5
        orchestrator._dispatch_log = lambda *a, **k: None
        orchestrator._remember_folders = lambda *a, **k: None

        async def fake_exec(call, **kwargs):
            await asyncio.sleep(0.01)
            return call["arguments"], {"success": True, "data": {"opened": True}, "error": None}

        class Router:
            async def get_completions_with_tools(self, *a, **k):
                return {"content": "Chrome is open, Sir.", "tool_calls": []}

        orchestrator.router = Router()
        orchestrator._execute_native_agent_call = fake_exec
        first = {"content": "", "tool_calls": [{"id": "c1", "name": "apps", "arguments": {"action": "open", "name": "chrome"}}]}
        out = await orchestrator._run_native_agent_loop(
            first, system_prompt="s", user_prompt="open chrome", tools=[], session_id="s9", project_id="personal",
            project_root=None, coding_turn=False, provider_for_turn="groq")
        self.assertEqual(out["content"], "Chrome is open, Sir.")
        texts = [e["text"] for _c, e in manager.events if e["type"] == "ultron_progress"]
        self.assertEqual(texts, ["Opening chrome"])
        self.assertEqual(manager.events[0][1]["session_id"], "s9")


if __name__ == "__main__":
    unittest.main()
