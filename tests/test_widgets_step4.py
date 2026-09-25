"""V2 Step 4 - the AI picks the widgets; no more letter-matching misfires."""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from backend.app.core import widgets
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.tools.tool_registry import ToolRegistry
from backend.app.tools.widget_tool import ShowWidgetTool

ROOT = Path(__file__).resolve().parents[1]


class TestNoMoreMisfires(unittest.TestCase):
    def test_ordinary_sentences_open_nothing(self):
        """Old substring guesser: explain->calendar, program->system, digital->git ..."""
        for text in (
            "explain quantum physics", "write a python program", "the digital world is big",
            "let's have brunch", "find the capital of France", "photograph ideas for a trip",
            "what is JavaScript?", "I planted a tree", "tell me about the ram in a sheep farm story",
            "that was a great task force movie", "running late today",
        ):
            with self.subTest(text=text):
                self.assertEqual(widgets.explicit_request(text)["action"], "none", text)

    def test_explicit_requests_still_open(self):
        for text, widget in (
            ("Show me D drive.", "file_explorer"), ("Open downloads.", "file_explorer"),
            ("Research current artificial agents.", "deep_research"), ("show my calendar", "calendar"),
            ("pull up the weather", "weather"), ("open my todo list", "todo"),
            ("show system stats", "system"), ("reminders", "reminder"),
            ("calendar kholo", "calendar"),
        ):
            with self.subTest(text=text):
                self.assertEqual(widgets.explicit_request(text), {"action": "open_widget", "widget_id": widget})


class TestToolDecides(unittest.TestCase):
    def test_ai_show_widget_wins(self):
        results = [
            {"tool": "manage_task", "args": {"action": "list"}, "success": True, "result": {}},
            {"tool": "show_widget", "args": {}, "success": True,
             "result": {"action": "open_widget", "widget_id": "calendar", "refresh": False}},
        ]
        self.assertEqual(widgets.from_tool_results(results), {"action": "open_widget", "widget_id": "calendar"})

    def test_changed_data_refreshes_panel(self):
        created = [{"tool": "manage_reminder", "args": {"action": "create"}, "success": True}]
        listed = [{"tool": "manage_reminder", "args": {"action": "list"}, "success": True}]
        self.assertTrue(widgets.from_tool_results(created).get("refresh"))
        self.assertNotIn("refresh", widgets.from_tool_results(listed))

    def test_failed_tool_opens_nothing(self):
        self.assertIsNone(widgets.from_tool_results([{"tool": "weather_tool", "args": {}, "success": False}]))

    def test_close_all(self):
        results = [{"tool": "show_widget", "success": True, "result": {"action": "close_all_widgets"}}]
        self.assertEqual(widgets.from_tool_results(results), {"action": "close_all_widgets"})


class TestShowWidgetTool(unittest.TestCase):
    def run_tool(self, **kwargs):
        return asyncio.run(ShowWidgetTool().execute(**kwargs))

    def test_aliases_and_errors(self):
        self.assertEqual(self.run_tool(widget_id="tasks")["data"]["widget_id"], "todo")
        self.assertEqual(self.run_tool(widget_id="Calendar Widget")["data"]["widget_id"], "calendar")
        self.assertEqual(self.run_tool(widget_id="reminder", action="close")["data"]["action"], "close_widget")
        self.assertEqual(self.run_tool(action="close_all")["data"], {"action": "close_all_widgets"})
        bad = self.run_tool(widget_id="spaceship")
        self.assertFalse(bad["success"])
        self.assertIn("calendar", bad["error"])  # tells the AI the valid choices

    def test_registered_and_in_menu(self):
        registry = ToolRegistry()
        self.assertIn("show_widget", registry.get_registered_ids())
        menu = (ROOT / "backend/app/tools/tool_catalog.py").read_text(encoding="utf-8")
        self.assertIn('"show_widget"', menu)


class TestMapsStayInSync(unittest.TestCase):
    def test_every_widget_exists_in_frontend(self):
        manager = (ROOT / "frontend/src/components/widgets/WidgetManager.js").read_text(encoding="utf-8")
        frontend_ids = set(re.findall(r'id:\s*"([a-z_]+)"', manager))
        self.assertTrue(set(widgets.WIDGETS) <= frontend_ids, set(widgets.WIDGETS) - frontend_ids)

    def test_every_mapped_tool_is_real(self):
        ids = set(ToolRegistry().get_registered_ids())
        self.assertFalse(set(widgets.TOOL_WIDGETS) - ids, set(widgets.TOOL_WIDGETS) - ids)
        self.assertTrue(set(widgets.TOOL_WIDGETS.values()) <= set(widgets.WIDGETS))


def _reply(content="", calls=None):
    return {"content": content, "tool_calls": calls or [], "provider": "groq", "model": "t",
            "native_tools": True, "provider_state": None}


class TestThroughTheOrchestrator(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.orchestrator = CognitiveOrchestrator()
        self.orchestrator.memory.gate.should_save = lambda _prompt: False

    async def asyncTearDown(self):
        await self.orchestrator.close()

    async def ask(self, text, replies):
        self.orchestrator.router.get_completions_with_tools = AsyncMock(side_effect=replies)
        return await self.orchestrator.process_request(text, session_id="step4-widgets")

    async def test_ai_opens_calendar_via_use_tool(self):
        call = {"id": "c1", "name": "use_tool",
                "arguments": {"tool": "show_widget", "arguments_json": json.dumps({"widget_id": "calendar"})}}
        result = await self.ask("put my week on screen", [_reply(calls=[call]), _reply("Here is your week, Sir.")])
        self.assertEqual(result["structured_action"]["action"], "open_widget")
        self.assertEqual(result["widget_shown"], "calendar")

    async def test_ai_closes_everything(self):
        call = {"id": "c1", "name": "show_widget", "arguments": {"action": "close_all"}}
        result = await self.ask("clean up my screen", [_reply(calls=[call]), _reply("Done, Sir.")])
        self.assertEqual(result["structured_action"], {"action": "close_all_widgets"})

    async def test_plain_question_opens_nothing(self):
        result = await self.ask("explain how a program uses ram", [_reply("It stores data while running.")])
        self.assertEqual(result["structured_action"], {"action": "none"})
        self.assertIsNone(result["widget_shown"])


if __name__ == "__main__":
    unittest.main()
