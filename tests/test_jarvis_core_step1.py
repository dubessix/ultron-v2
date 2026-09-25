"""V2 Step 1 - Jarvis Core: every tool reachable, multi-step jobs, token budget."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from backend.app.brain.llm_router import LLMRouter
from backend.app.brain.token_budget import TokenBudget
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.tools import tool_catalog
from backend.app.tools.tool_catalog import (
    build_tool_menu,
    menu_tool_ids,
    parse_use_tool_call,
    use_tool_metadata,
)
from backend.app.tools.tool_registry import ToolRegistry
from tests.test_jarvis_full_access import FullAccessCase


def _reply(content="", calls=None, provider="groq"):
    return {
        "content": content,
        "tool_calls": calls or [],
        "provider": provider,
        "model": "test",
        "native_tools": True,
        "provider_state": None,
    }


def _use(call_id, tool, args):
    return {
        "id": call_id,
        "name": "use_tool",
        "arguments": {"tool": tool, "arguments_json": json.dumps(args)},
    }


class TestToolMenuCoversEverything(unittest.TestCase):
    def test_every_registered_tool_has_exactly_one_menu_line(self):
        registered = ToolRegistry().get_registered_ids()
        listed = menu_tool_ids()
        self.assertEqual(len(listed), len(set(listed)), "duplicate menu entries")
        self.assertEqual(set(registered) - set(listed), set(), "tools missing from the menu")
        self.assertEqual(set(listed) - set(registered), set(), "menu lists unknown tools")

    def test_menu_mentions_every_id_and_new_custom_tools(self):
        registered = ToolRegistry().get_registered_ids()
        menu = build_tool_menu([*registered, "brand_new_tool"])
        for tool_id in registered:
            self.assertIn(tool_id, menu)
        self.assertIn("brand_new_tool", menu)

    def test_menu_is_small(self):
        menu = build_tool_menu(ToolRegistry().get_registered_ids())
        self.assertLess(len(menu) // 4, 1100, "menu must stay ~1K tokens")


class TestStaticPrefix(unittest.TestCase):
    def setUp(self):
        CognitiveOrchestrator._STATIC_PREFIX_CACHE = None
        CognitiveOrchestrator._PC_PROFILE_CACHE = None

    def test_prefix_is_identical_every_turn_and_imports_no_tools(self):
        real_import = importlib.import_module
        with patch(
            "backend.app.tools.tool_registry.importlib.import_module", wraps=real_import
        ) as imports:
            first = CognitiveOrchestrator._jarvis_static_prefix()
            second = CognitiveOrchestrator._jarvis_static_prefix()
        self.assertEqual(first, second)
        self.assertEqual(imports.call_count, 0, "menu text must not import tool modules")
        self.assertIn("[ACTION MANDATE]", first)
        self.assertIn("[TOOL MENU]", first)
        self.assertIn("compress_folder", first)

    def test_pc_profile_names_home_and_how_to_open_things(self):
        profile = CognitiveOrchestrator._pc_profile()
        self.assertIn("[OWNER PC]", profile)
        self.assertIn("Home:", profile)
        self.assertTrue(any(word in profile for word in ("xdg-open", "start", "open <")))


class TestUseToolParsing(unittest.TestCase):
    def test_json_string(self):
        self.assertEqual(
            parse_use_tool_call({"tool": "list_contents", "arguments_json": '{"folderpath": "Desktop"}'}),
            ("list_contents", {"folderpath": "Desktop"}, None),
        )

    def test_dict_and_flattened_variants(self):
        self.assertEqual(
            parse_use_tool_call({"tool": "weather_tool", "arguments": {"city": "Kolkata"}})[1],
            {"city": "Kolkata"},
        )
        self.assertEqual(
            parse_use_tool_call({"tool": "weather_tool", "city": "Kolkata"})[1],
            {"city": "Kolkata"},
        )
        self.assertEqual(parse_use_tool_call({"tool": "system_metrics", "arguments_json": ""})[1], {})

    def test_errors_are_explained(self):
        self.assertIn("needs 'tool'", parse_use_tool_call({"arguments_json": "{}"})[2])
        self.assertIn("not valid JSON", parse_use_tool_call({"tool": "x", "arguments_json": "{bad"})[2])
        self.assertIn("JSON object", parse_use_tool_call({"tool": "x", "arguments_json": "[1]"})[2])

    def test_schema_is_provider_safe_and_small(self):
        meta = use_tool_metadata(ToolRegistry().get_registered_ids())
        schema = LLMRouter._native_tool_schema(meta, openai_style=False)
        props = schema["parameters"]["properties"]
        self.assertEqual(props["arguments_json"]["type"], "string")  # Gemini-safe
        self.assertLess(len(json.dumps(schema)) // 4, 200)


class TestActionTurnsGetTheWholeToolbox(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.orchestrator = CognitiveOrchestrator()
        self.native = AsyncMock(return_value=_reply("Done."))
        self.orchestrator.router.get_completions_with_tools = self.native

    async def asyncTearDown(self):
        await self.orchestrator.close()

    async def test_unknown_wording_still_reaches_every_tool(self):
        await self.orchestrator.process_request("take a screenshot", session_id="s1-shot")
        system_prompt = self.native.await_args.args[0]
        ids = [item["tool_id"] for item in self.native.await_args.args[2]]
        self.assertIn("use_tool", ids)
        self.assertTrue(system_prompt.startswith("\n\n[ACTION MANDATE]") or system_prompt.startswith("[ACTION MANDATE]"))
        for tool_id in ("terminal_run", "compress_folder", "manage_reminder", "spotify_play"):
            self.assertIn(tool_id, system_prompt)

    async def test_native_schemas_stay_bounded(self):
        await self.orchestrator.process_request(
            "clean my desktop folder, zip the screenshots and remind me at 5",
            session_id="s1-multi",
        )
        ids = [item["tool_id"] for item in self.native.await_args.args[2]]
        self.assertLessEqual(len(ids), CognitiveOrchestrator.JARVIS_NATIVE_LIMIT + 1)

    async def test_prefix_is_byte_identical_across_different_requests(self):
        await self.orchestrator.process_request("what's the weather in Kolkata", session_id="s1-a")
        first = self.native.await_args.args[0]
        await self.orchestrator.process_request("open my Downloads folder", session_id="s1-b")
        second = self.native.await_args.args[0]
        prefix = CognitiveOrchestrator._jarvis_static_prefix()
        self.assertTrue(first.startswith(prefix) and second.startswith(prefix))


class TestMultiStepJobThroughUseTool(FullAccessCase):
    def _run(self, brain, prompt, executed):
        async def spy(self_registry, tool_id, args, **kwargs):
            executed.append((tool_id, args))
            if tool_id == "list_contents" and not args.get("folderpath"):
                return {"success": False, "data": {}, "error": "Input validation schema match failed. Problems: folderpath: Field required"}
            return {"success": True, "data": {"ok": tool_id}, "error": None}

        async def run():
            orchestrator = CognitiveOrchestrator()
            orchestrator.router.get_completions_with_tools = brain
            try:
                with patch.object(ToolRegistry, "execute_tool", new=spy):
                    return await orchestrator.process_request(prompt, session_id="s1-job")
            finally:
                await orchestrator.close()

        return asyncio.run(run())

    def test_find_list_organize_zip_in_one_turn(self):
        plan = [
            [_use("c1", "locate_path", {"name": "old_screens"})],
            [_use("c2", "list_contents", {"folderpath": "old_screens"})],
            [_use("c3", "organize_folder", {"folderpath": "Desktop"})],
            [_use("c4", "compress_folder", {"folderpath": "old_screens"})],
        ]
        seen_tools, seen_history = [], []

        async def brain(system_prompt, user_prompt, tools, **kwargs):
            seen_tools.append([t["tool_id"] for t in tools])
            seen_history.append(list(kwargs.get("conversation") or []))
            step = len(seen_tools) - 1
            if step < len(plan):
                return _reply(calls=plan[step])
            return _reply("Desktop organized and the screenshots are zipped, Sir.")

        executed = []
        response = self._run(brain, "clean my desktop and zip the old screenshots", executed)

        self.assertEqual(
            [tool for tool, _ in executed],
            ["locate_path", "list_contents", "organize_folder", "compress_folder"],
        )
        # Folder names were auto-resolved to real paths by the path guard.
        self.assertEqual(executed[1][1]["folderpath"], str(self.home / "Desktop" / "old_screens"))
        self.assertEqual(response["tools_used"], ["locate_path", "list_contents", "organize_folder", "compress_folder"])
        # Provider sees answers under the name it called (use_tool).
        tool_messages = [m for m in seen_history[-1] if m.get("role") == "tool"]
        self.assertTrue(tool_messages and all(m["name"] == "use_tool" for m in tool_messages))
        # After first use, the real schema is declared natively for later steps.
        self.assertIn("list_contents", seen_tools[-1])
        self.assertIn("zipped", response["content"])

    def test_bad_arguments_get_the_real_schema_then_retry(self):
        plan = [
            [_use("c1", "list_contents", {})],
            [_use("c2", "list_contents", {"folderpath": "Downloads"})],
        ]
        history = []

        async def brain(system_prompt, user_prompt, tools, **kwargs):
            history.append(list(kwargs.get("conversation") or []))
            step = len(history) - 1
            return _reply(calls=plan[step]) if step < len(plan) else _reply("Your Downloads has one file.")

        executed = []
        self._run(brain, "what is in downloads", executed)
        first_answer = [m for m in history[1] if m.get("role") == "tool"][0]["content"]
        self.assertIn("Correct schema for list_contents", first_answer)
        self.assertIn("folderpath", first_answer)
        self.assertEqual(executed[-1][1]["folderpath"], str(self.home / "Downloads"))

    def test_unknown_tool_gets_did_you_mean(self):
        history = []

        async def brain(system_prompt, user_prompt, tools, **kwargs):
            history.append(list(kwargs.get("conversation") or []))
            if len(history) == 1:
                return _reply(calls=[_use("c1", "compress_folders", {"folderpath": "Desktop"})])
            return _reply("Done.")

        self._run(brain, "zip my desktop", [])
        answer = [m for m in history[1] if m.get("role") == "tool"][0]["content"]
        self.assertIn("Did you mean", answer)
        self.assertIn("compress_folder", answer)

    def test_everyday_jobs_stop_after_fifteen_steps(self):
        async def brain(system_prompt, user_prompt, tools, **kwargs):
            return _reply(calls=[_use("c", "system_metrics", {})])

        executed = []
        response = self._run(brain, "keep checking my pc", executed)
        self.assertEqual(len(executed), 15)
        self.assertIn("15 tool steps", response["content"])


class TestTokenBudget(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.budget = TokenBudget(clock=lambda: self.now[0])

    def test_cached_prefix_does_not_count(self):
        counted = self.budget.record_usage(
            "groq",
            {"prompt_tokens": 2000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 1500}},
        )
        self.assertEqual(counted, 600)
        # Next estimate subtracts the cached part (but not below a quarter).
        self.assertEqual(self.budget.estimate("groq", 8000, max_output=0), 500)

    def test_room_and_wait_time(self):
        self.budget.record_usage("groq", {"prompt_tokens": 6000, "completion_tokens": 500})
        self.assertGreater(self.budget.room("groq", 1500), 0)
        self.assertEqual(self.budget.room("groq", 500), 0)
        self.now[0] += 61
        self.assertEqual(self.budget.room("groq", 1500), 0)

    def test_request_count_limit(self):
        for _ in range(30):
            self.budget.record_usage("groq", {"prompt_tokens": 10})
        self.assertGreater(self.budget.room("groq", 10), 0)

    def test_unlimited_providers_and_env_override(self):
        self.budget.record_usage("gemini", {"prompt_tokens": 10**6})
        self.assertEqual(self.budget.room("gemini", 10**6), 0)
        with patch.dict(os.environ, {"ULTRON_GROQ_TPM": "100000"}):
            self.budget.record_usage("groq", {"prompt_tokens": 9000})
            self.assertEqual(self.budget.room("groq", 1000), 0)


class TestRouterUsesTheBudget(unittest.IsolatedAsyncioTestCase):
    async def test_job_starts_on_next_provider_when_groq_minute_is_full(self):
        router = LLMRouter()
        try:
            router.key_manager.has_real_key = lambda provider: provider in {"groq", "gemini"}
            router.get_provider_order = lambda preference=None: ["groq", "gemini"]
            router.token_budget.record_usage("groq", {"prompt_tokens": 7900})
            router._execute_openai_native_tools = AsyncMock(side_effect=AssertionError("groq must be skipped"))
            router._execute_gemini_native_tools = AsyncMock(return_value=_reply("hi", provider="gemini"))
            result = await router.get_completions_with_tools(
                "sys", "hello", [{"tool_id": "use_tool", "description": "d", "input_schema": {}}]
            )
            self.assertEqual(result["provider"], "gemini")
        finally:
            await router.close()

    async def test_locked_job_waits_instead_of_failing(self):
        router = LLMRouter()
        try:
            router.token_budget.record_usage("groq", {"prompt_tokens": 7900})
            with patch("backend.app.brain.llm_router.asyncio.sleep", new=AsyncMock()) as sleep:
                await router._respect_budget("groq", {"messages": ["x" * 400], "max_tokens": 600})
            sleep.assert_awaited()
            self.assertLessEqual(sleep.await_args.args[0], router._MAX_BUDGET_WAIT_SECONDS)
        finally:
            await router.close()


class TestSlimSchemas(unittest.TestCase):
    def test_optional_null_branches_and_long_prose_are_trimmed(self):
        schema = {
            "type": "object",
            "properties": {
                "title": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "x" * 400},
                "action": {"type": "string", "enum": ["create", "list"]},
            },
            "required": ["action"],
        }
        slim = LLMRouter._clean_native_schema(schema)
        self.assertEqual(slim["properties"]["title"]["type"], "string")
        self.assertNotIn("anyOf", slim["properties"]["title"])
        self.assertLessEqual(len(slim["properties"]["title"]["description"]), 120)
        self.assertEqual(slim["properties"]["action"]["enum"], ["create", "list"])
        self.assertEqual(slim["required"], ["action"])

    def test_biggest_real_schemas_shrink(self):
        registry = ToolRegistry()
        for tool_id in ("manage_task", "manage_reminder", "manage_calendar"):
            meta = registry.get_tool(tool_id).get_metadata()
            before = len(json.dumps(meta["input_schema"]))
            after = len(json.dumps(LLMRouter._native_tool_schema(
                {"tool_id": tool_id, "description": meta["description"], "input_schema": meta["input_schema"]},
                openai_style=True,
            )))
            with self.subTest(tool=tool_id):
                self.assertLess(after, before)


class TestValidationErrorsExplainThemselves(unittest.IsolatedAsyncioTestCase):
    async def test_missing_field_is_named(self):
        result = await ToolRegistry().execute_tool("list_contents", {})
        self.assertFalse(result["success"])
        self.assertIn("Input validation schema match failed.", result["error"])
        self.assertIn("folderpath", result["error"])


if __name__ == "__main__":
    unittest.main()
