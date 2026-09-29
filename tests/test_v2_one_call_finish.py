"""B8: a simple action that works cleanly ends the turn with its own done line.

Saves the second brain call (~3.5K tokens). Anything that needs the result
(lookups, choices, failures, multi-step jobs, coding) still gets the normal
second call, so Ultron is never weaker."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from backend.app.brain.llm_router import LLMRouter
from backend.app.tools import tool_catalog
from tests._ai_script import call, reply
from tests.test_jarvis_approval import ApiCase

RUN = "backend.app.tools.tool_registry.ToolRegistry.execute_tool"


def ok(**data):
    return AsyncMock(return_value={"success": True, "data": data, "error": None})


class TestOneCallFinish(ApiCase):
    def action(self, tool, args, line="Firefox is open, Sir.", direct=False):
        def script(prompt, conv):
            if any(m.get("role") == "tool" for m in conv):
                return reply("Second call answer, Sir.")
            if direct:
                return reply("", [call(tool, {**args, "say_when_done": line})])
            return reply("", [{"id": "c1", "name": "use_tool", "arguments": {
                "tool": tool, "arguments_json": json.dumps(args), "say_when_done": line}}])
        self.script = script

    def test_clean_action_needs_one_call(self):
        self.action("apps", {"action": "open", "name": "firefox"})
        with patch(RUN, new=ok(message="Opened firefox")) as run:
            result = self.chat("open firefox")
        self.assertTrue(result["content"].startswith("Firefox is open, Sir."))
        self.assertEqual(len(self.brain_calls), 1)
        sent = run.await_args.kwargs["args"]
        self.assertNotIn("say_when_done", sent)  # the tool never sees it

    def test_direct_tool_call_too(self):
        self.action("set_volume", {"level": 40}, "Volume is at 40, Sir.", direct=True)
        with patch(RUN, new=ok()) as run:
            result = self.chat("volume 40")
        self.assertTrue(result["content"].startswith("Volume is at 40, Sir."))
        self.assertEqual(len(self.brain_calls), 1)
        self.assertEqual(run.await_args.kwargs["args"], {"level": 40})

    def test_failure_gets_the_normal_second_call(self):
        self.action("apps", {"action": "open", "name": "firefox"})
        with patch(RUN, new=AsyncMock(return_value={"success": False, "data": {}, "error": "not installed"})):
            result = self.chat("open firefox")
        self.assertEqual(len(self.brain_calls), 2)
        self.assertNotIn("Firefox is open", result["content"])

    def test_lookups_always_get_the_second_call(self):
        self.action("apps", {"action": "running"}, "Here is what runs, Sir.")
        with patch(RUN, new=ok(apps=["firefox"])):
            self.chat("what apps are running")
        self.assertEqual(len(self.brain_calls), 2)
        self.action("system_metrics", {}, "Your PC is fine, Sir.")
        with patch(RUN, new=ok(ram_percent=91.0)):
            self.chat("how is my pc")
        self.assertEqual(len(self.brain_calls), 4)

    def test_choices_or_notes_get_the_second_call(self):
        for data in ({"choices": ["a", "b"]}, {"note": "still running"}, {"verified": False},
                     {"message": "Which one, Sir?"}):
            self.brain_calls.clear()
            self.action("apps", {"action": "close", "name": "code"}, "Closed, Sir.")
            with patch(RUN, new=ok(**data)):
                self.chat("close code")
            self.assertEqual(len(self.brain_calls), 2, data)

    def test_without_a_line_nothing_changes(self):
        self.action("apps", {"action": "open", "name": "firefox"}, line="")
        with patch(RUN, new=ok()):
            result = self.chat("open firefox")
        self.assertEqual(len(self.brain_calls), 2)
        self.assertIn("Second call answer", result["content"])

    def test_two_calls_in_one_answer_get_the_second_call(self):
        def script(prompt, conv):
            if any(m.get("role") == "tool" for m in conv):
                return reply("Both done, Sir.")
            return reply("", [
                {"id": "c1", "name": "use_tool", "arguments": {"tool": "set_volume", "arguments_json": '{"level": 10}',
                                                                "say_when_done": "Quiet now, Sir."}},
                {"id": "c2", "name": "use_tool", "arguments": {"tool": "pause_music", "arguments_json": "{}"}}])
        self.script = script
        with patch(RUN, new=ok()):
            result = self.chat("quiet and pause")
        self.assertIn("Both done", result["content"])

    def test_the_done_line_still_passes_the_leak_guard(self):
        self.action("apps", {"action": "open", "name": "firefox"}, "The user wants firefox. Firefox is open, Sir.")
        with patch(RUN, new=ok()):
            result = self.chat("open firefox")
        self.assertTrue(result["content"].startswith("Firefox is open, Sir."))


class TestSchemas(ApiCase):
    def test_only_simple_actions_offer_the_line(self):
        schema = LLMRouter._native_tool_schema(
            {"tool_id": "set_volume", "description": "x", "input_schema": {"type": "object", "properties": {"level": {"type": "integer"}}}},
            openai_style=True)
        self.assertIn("say_when_done", schema["function"]["parameters"]["properties"])
        schema = LLMRouter._native_tool_schema(
            {"tool_id": "file_read", "description": "x", "input_schema": {"type": "object", "properties": {"filepath": {"type": "string"}}}},
            openai_style=False)
        self.assertNotIn("say_when_done", schema["parameters"]["properties"])
        meta = tool_catalog.use_tool_metadata([])
        self.assertNotIn("say_when_done", meta["input_schema"]["required"])

    def test_allowlist_is_real_tools_and_no_reads(self):
        from backend.app.tools.tool_registry import ToolRegistry

        registered = set(ToolRegistry().get_registered_ids())
        self.assertLessEqual(set(tool_catalog.ONE_CALL_TOOLS), registered)
        for read in ("file_read", "list_contents", "locate_path", "system_metrics", "weather_tool",
                     "universal_search", "terminal_run", "file_write", "delete_folder", "read_current_page"):
            self.assertFalse(tool_catalog.one_call_ok(read, {}), read)
        self.assertFalse(tool_catalog.one_call_ok("manage_reminder", {"action": "list"}))
        self.assertTrue(tool_catalog.one_call_ok("manage_reminder", {"action": "create"}))
        self.assertEqual(tool_catalog.parse_use_tool_call({"tool": "notify", "title": "t", "say_when_done": "x y"})[1],
                         {"title": "t"})
