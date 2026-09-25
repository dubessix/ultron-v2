"""Jarvis Phase 0 contract: the LLM brain decides tools; keyword gates are hints.

Guarantees locked here:
  1. Action turns ALWAYS reach the model with native tool schemas attached.
  2. Even "fast" knowledge turns are armed (the model may choose not to call).
  3. Only pure social turns go out without tools.
  4. The old "No tool execution is needed" injection never returns.
  5. Natural phrasing routes to the right tool (token + glued-token matching).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from backend.app.core.decision_engine import DecisionEngine
from backend.app.core.intent_analyzer import IntentAnalyzer
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.tools.context_builder import ToolContextBuilder
from backend.app.tools.tool_registry import ToolRegistry


def _native_reply(content: str = "Done.") -> dict:
    return {
        "content": content,
        "tool_calls": [],
        "provider": "groq",
        "model": "test-native",
        "native_tools": True,
        "provider_state": None,
    }


class TestNaturalPhrasingRouting(unittest.TestCase):
    CASES = {
        "what is the weather in Kolkata today?": "weather_tool",
        "play some music": "play_music",
        "show me my cpu and ram usage": "system_metrics",
        "delete my downloads folder": "delete_folder",
        "open VS Code": "open_vscode",
        "organize my desktop files": "organize_folder",
        "increase the volume": "set_volume",
        "search the web for latest AI news": "google_search",
        "read me the news": "news_search",
        "find all pdf files in my documents": "find_files",
        "thanks! now find my invoice pdf": "find_files",
        "run my django server": "terminal_run",
        "set a reminder for 5pm": "manage_reminder",
        "remember that my birthday is on 12 March": "manage_memory",
        "previous song": "previous_track",
        "convert sales.json to csv": "convert_file_format",
    }

    def test_natural_prompts_select_expected_tool(self):
        ids = ToolRegistry().get_registered_ids()
        for prompt, expected in self.CASES.items():
            with self.subTest(prompt=prompt):
                selected = ToolContextBuilder.select_relevant_tool_ids(prompt, ids)
                self.assertIn(expected, selected)
                self.assertLessEqual(len(selected), ToolContextBuilder.MAX_RELEVANT_TOOLS)

    def test_small_talk_selects_nothing_but_belt_is_available(self):
        ids = ToolRegistry().get_registered_ids()
        for prompt in ("hello", "thanks", "tell me a joke"):
            self.assertEqual(ToolContextBuilder.select_relevant_tool_ids(prompt, ids), [])
        belt = ToolContextBuilder.default_utility_ids(ids)
        self.assertIn("weather_tool", belt)
        self.assertIn("google_search", belt)
        self.assertLessEqual(len(belt), ToolContextBuilder.MAX_RELEVANT_TOOLS)


class TestIntentsAreHintsNotGates(unittest.TestCase):
    def setUp(self):
        self.analyzer = IntentAnalyzer()
        self.engine = DecisionEngine()

    def test_vs_code_is_not_a_coding_turn(self):
        self.assertNotEqual(self.analyzer.analyze("open VS Code"), "CODING")

    def test_command_after_thanks_is_not_conversation(self):
        self.assertNotEqual(
            self.analyzer.analyze("thanks! now find my invoice pdf"), "CONVERSATION"
        )

    def test_pure_greetings_stay_conversation(self):
        for prompt in ("hello", "Hi there, good morning!", "thanks jarvis", "Hello, how are you today?"):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.analyzer.analyze(prompt), "CONVERSATION")

    def test_everyday_domains_route_to_medium_track(self):
        for prompt in (
            "what's the weather in Kolkata",
            "play some music",
            "show me cpu usage",
            "delete my downloads folder",
            "open chrome",
            "search latest AI news",
            "open VS Code",
        ):
            with self.subTest(prompt=prompt):
                intent = self.analyzer.analyze(prompt)
                self.assertEqual(self.engine.get_speed_track(intent, 1.0), "medium")


class TestOrchestratorAlwaysArmsTheBrain(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.orchestrator = CognitiveOrchestrator()
        self.native = AsyncMock(return_value=_native_reply())
        self.plain = AsyncMock(return_value="Hello Debjeet.")
        self.orchestrator.router.get_completions_with_tools = self.native
        self.orchestrator.router.get_completions = self.plain

    async def asyncTearDown(self):
        await self.orchestrator.close()

    async def _ask(self, prompt: str, session: str) -> dict:
        return await self.orchestrator.process_request(prompt, session_id=session)

    async def test_weather_turn_reaches_model_with_weather_schema(self):
        await self._ask("What's the weather in Kolkata today?", "p0-weather")
        self.native.assert_awaited()
        system_prompt = self.native.await_args.args[0]
        tool_ids = [item["tool_id"] for item in self.native.await_args.args[2]]
        self.assertIn("weather_tool", tool_ids)
        self.assertIn("[ACTION MANDATE]", system_prompt)
        self.assertNotIn("No tool execution is needed", system_prompt)

    async def test_fast_knowledge_turn_is_still_armed(self):
        response = await self._ask("What is the capital of France?", "p0-fast")
        self.assertEqual(response["speed_track"], "fast")
        self.native.assert_awaited()
        tool_ids = [item["tool_id"] for item in self.native.await_args.args[2]]
        self.assertTrue(tool_ids, "fast turns must still receive the default tool belt")
        self.assertLessEqual(len(tool_ids), ToolContextBuilder.MAX_RELEVANT_TOOLS)

    async def test_greeting_is_also_decided_by_the_ai(self):
        # No regex "small talk" gate: the brain always has its tools and decides.
        await self._ask("Hello, how are you today?", "p0-hello")
        self.native.assert_awaited_once()
        self.plain.assert_not_awaited()
        tool_ids = [item["tool_id"] for item in self.native.await_args.args[2]]
        self.assertIn("use_tool", tool_ids)
        self.assertIn("switch_mode", self.native.await_args.args[0])  # its guide is in the cached prompt


if __name__ == "__main__":
    unittest.main()
