"""F2 regressions: prompt context must keep the 70-tool registry (69 + Jarvis locate_path) genuinely lazy."""

from __future__ import annotations

import importlib
import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.tools.context_builder import ToolContextBuilder
from backend.app.tools.tool_registry import ToolRegistry


class TestPromptScopedLazyToolMetadata(unittest.IsolatedAsyncioTestCase):
    async def _compile(self, prompt: str, *, coding_turn: bool = False):
        orchestrator = CognitiveOrchestrator()
        real_import = importlib.import_module
        try:
            with patch.object(
                ToolRegistry,
                "get_all_tools",
                side_effect=AssertionError("prompt assembly must not load all tools"),
            ), patch(
                "backend.app.tools.tool_registry.importlib.import_module",
                wraps=real_import,
            ) as module_import:
                payload = json.loads(
                    orchestrator._compile_tools_metadata(
                        prompt,
                        coding_turn=coding_turn,
                    )
                )
            imported_modules = {
                call.args[0]
                for call in module_import.call_args_list
                if call.args
            }
            return payload, imported_modules
        finally:
            await orchestrator.close()

    async def test_medium_git_prompt_loads_only_a_small_relevant_slice(self):
        payload, imported = await self._compile("Check git status for this working tree")
        ids = [item["tool_id"] for item in payload]

        self.assertIn("git_status", ids)
        self.assertLessEqual(len(ids), 8)
        self.assertEqual(imported, {"backend.app.tools.git_tool"})
        self.assertNotIn("play_music", ids)
        self.assertNotIn("database_restore", ids)

    async def test_coding_prompt_loads_bounded_file_and_terminal_schemas(self):
        payload, imported = await self._compile(
            "Read backend/app.py, fix the code, then run pytest",
            coding_turn=True,
        )
        ids = {item["tool_id"] for item in payload}

        self.assertTrue({"file_read", "file_write", "terminal_run"}.issubset(ids))
        self.assertLessEqual(len(ids), 8)
        self.assertNotIn("backend.app.tools.music_tools", imported)
        self.assertNotIn("backend.app.tools.spotify_tools", imported)
        self.assertNotIn("backend.app.tools.database_tools", imported)

    async def test_selected_metadata_contains_argument_schema_not_all_tools(self):
        payload, _imported = await self._compile("Read the local config file")
        file_read = next(item for item in payload if item["tool_id"] == "file_read")

        self.assertIn("input_schema", file_read)
        self.assertIn("properties", file_read["input_schema"])
        self.assertIn("filepath", file_read["input_schema"]["properties"])
        self.assertLessEqual(len(payload), 8)

    async def test_conversational_turn_imports_no_tool_modules(self):
        payload, imported = await self._compile("Hello, how are you today?")
        self.assertEqual(payload, [])
        self.assertEqual(imported, set())

    async def test_medium_request_pipeline_injects_only_selected_metadata(self):
        orchestrator = CognitiveOrchestrator()
        capture = AsyncMock(
            return_value={
                "content": "The working tree check is ready.",
                "tool_calls": [],
                "provider": "groq",
                "model": "test-native",
                "native_tools": True,
                "provider_state": None,
            }
        )
        orchestrator.router.get_completions_with_tools = capture
        try:
            with patch.object(
                ToolRegistry,
                "get_all_tools",
                side_effect=AssertionError("request pipeline must remain lazy"),
            ):
                response = await orchestrator.process_request(
                    "Check git status for this working tree",
                    session_id="f2-medium-pipeline",
                )
        finally:
            await orchestrator.close()

        self.assertEqual(response["speed_track"], "medium")
        metadata = capture.await_args.args[2]
        # Jarvis Core: the prompt-relevant schema plus the universal use_tool
        # (whose menu is static text) - and still only git_tool was imported.
        self.assertEqual([item["tool_id"] for item in metadata], ["git_status", "use_tool"])
        self.assertNotIn("AVAILABLE_TOOLS_METADATA", capture.await_args.args[0])


class TestLazyRegistryPreservation(unittest.TestCase):
    def test_all_70_tool_ids_remain_registered_without_importing_modules(self):
        real_import = importlib.import_module
        with patch(
            "backend.app.tools.tool_registry.importlib.import_module",
            wraps=real_import,
        ) as module_import:
            registry = ToolRegistry()
            ids = registry.get_registered_ids()

        self.assertEqual(len(ids), 70)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("database_restore", ids)
        self.assertIn("spotify_current_track", ids)
        module_import.assert_not_called()

    def test_every_registered_tool_remains_selectable_by_explicit_name(self):
        registry = ToolRegistry()
        registered_ids = registry.get_registered_ids()
        builder = ToolContextBuilder()

        for tool_id in registered_ids:
            with self.subTest(tool_id=tool_id):
                selected = builder.select_relevant_tool_ids(
                    tool_id.replace("_", " "),
                    registered_ids,
                )
                self.assertIn(tool_id, selected)
                self.assertLessEqual(len(selected), builder.MAX_RELEVANT_TOOLS)


if __name__ == "__main__":
    unittest.main()
