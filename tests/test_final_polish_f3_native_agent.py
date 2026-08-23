"""F3 regressions for native tool calls, bounded agent resume, roots and egress."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from backend.app.brain.api_key_manager import APIKeyManager
from backend.app.brain.llm_router import LLMRouter
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.runtime_paths import TEST_ROOT, isolated_test_artifact_path
from backend.app.security.path_guard import (
    resolve_agent_tool_arguments,
    resolve_project_root,
)
from backend.app.security.pending_actions import PendingActionRegistry, get_pending_action_registry
from backend.app.services.chat_service import process_chat_message
from backend.app.tools.safe_write import safe_write_file
from backend.app.tools.tool_registry import ToolRegistry


def _tools() -> list[dict]:
    return [
        {
            "tool_id": "file_read",
            "description": "Read a project file.",
            "permission_level": 0,
            "input_schema": {
                "type": "object",
                "properties": {"filepath": {"type": "string"}},
                "required": ["filepath"],
            },
        }
    ]


def _response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("POST", "https://provider.invalid"),
    )


class TestNativeProviderAdapters(unittest.IsolatedAsyncioTestCase):
    async def _router_for(self, provider: str) -> LLMRouter:
        manager = APIKeyManager()
        manager._keys = {name: [] for name in manager.PROVIDERS}
        manager._keys[provider] = [{"key": f"real-{provider}-key", "state": "ACTIVE"}]
        return LLMRouter(key_manager=manager)

    async def test_groq_uses_openai_native_tools_and_parses_calls(self):
        router = await self._router_for("groq")
        router.client.post = AsyncMock(
            return_value=_response(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-groq",
                                        "type": "function",
                                        "function": {
                                            "name": "file_read",
                                            "arguments": '{"filepath":"src/app.py"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )
        )
        try:
            result = await router.get_completions_with_tools(
                "system",
                "read app",
                _tools(),
                provider_preference="groq",
                provider_lock="groq",
            )
        finally:
            await router.close()

        body = router.client.post.await_args.kwargs["json"]
        self.assertEqual(body["tools"][0]["function"]["name"], "file_read")
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(result["tool_calls"][0]["arguments"], {"filepath": "src/app.py"})
        self.assertTrue(result["native_tools"])

    async def test_gemini_uses_function_declarations_and_parses_calls(self):
        router = await self._router_for("gemini")
        router.client.post = AsyncMock(
            return_value=_response(
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "file_read",
                                            "args": {"filepath": "src/app.py"},
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                }
            )
        )
        try:
            result = await router.get_completions_with_tools(
                "system",
                "read app",
                _tools(),
                provider_preference="gemini",
                provider_lock="gemini",
            )
        finally:
            await router.close()

        body = router.client.post.await_args.kwargs["json"]
        declaration = body["tools"][0]["functionDeclarations"][0]
        self.assertEqual(declaration["name"], "file_read")
        self.assertEqual(result["tool_calls"][0]["arguments"], {"filepath": "src/app.py"})
        self.assertEqual(result["provider"], "gemini")

    async def test_nvidia_uses_native_tools_with_required_chat_template_flags(self):
        router = await self._router_for("nvidia")
        router.client.post = AsyncMock(
            return_value=_response(
                {"choices": [{"message": {"content": "done", "tool_calls": []}}]}
            )
        )
        try:
            result = await router.get_completions_with_tools(
                "system",
                "read app",
                _tools(),
                provider_preference="nvidia",
                provider_lock="nvidia",
            )
        finally:
            await router.close()

        body = router.client.post.await_args.kwargs["json"]
        self.assertEqual(body["tools"][0]["function"]["name"], "file_read")
        self.assertTrue(body["chat_template_kwargs"]["enable_thinking"])
        self.assertTrue(body["chat_template_kwargs"]["force_nonempty_content"])
        self.assertEqual(result["content"], "done")


class TestCanonicalProjectRoot(unittest.TestCase):
    def test_configured_project_root_resolves_relative_agent_paths_and_blocks_escape(self):
        project = isolated_test_artifact_path("f3_root", "alpha")
        project.mkdir(parents=True, exist_ok=True)
        config = {
            "allowed_directories": [str(project.parent)],
            "project_roots": {"alpha": str(project)},
        }
        with patch("backend.app.security.path_guard._load_security_config", return_value=config):
            root = resolve_project_root("alpha")
            inside = resolve_agent_tool_arguments(
                "file_read",
                {"filepath": "src/app.py"},
                root["path"],
            )
            escaped = resolve_agent_tool_arguments(
                "file_read",
                {"filepath": "../outside.txt"},
                root["path"],
            )

        self.assertTrue(root["safe"])
        self.assertEqual(Path(inside["arguments"]["filepath"]), project / "src" / "app.py")
        self.assertFalse(escaped["safe"])
        self.assertEqual(escaped["reason"], "outside_active_project")


class TestPendingResumeAndCodeValidation(unittest.TestCase):
    def test_coding_fingerprint_normalizes_windows_crlf_like_file_read(self):
        target = isolated_test_artifact_path("f3_fingerprint", "windows_style.py")
        target.write_bytes(b"VALUE = 1\r\n")
        expected = hashlib.sha256(b"VALUE = 1\n").hexdigest()
        self.assertEqual(CognitiveOrchestrator._file_fingerprint(str(target)), expected)

    def test_pending_action_keeps_private_bounded_resume_context(self):
        registry = PendingActionRegistry()
        created = registry.create(
            "file_read",
            "f3-session",
            {"filepath": "src/app.py"},
            resume_context={"kind": "native_agent", "step": 1},
        )
        claimed = registry.claim(created["confirmation_token"], "f3-session")
        self.assertTrue(claimed["valid"])
        self.assertEqual(
            claimed["action"]["resume_context"],
            {"kind": "native_agent", "step": 1},
        )
        self.assertNotIn("resume_context", created)

    def test_invalid_tsx_is_rejected_before_replacing_original(self):
        target = isolated_test_artifact_path("f3_validation", "App.tsx")
        target.write_text("export const App = () => <div />;\n", encoding="utf-8")
        result = safe_write_file(
            str(target),
            "export const App = () => <div>broken</span>;\n",
        )
        self.assertFalse(result["success"])
        self.assertTrue(result["data"]["original_preserved"])
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "export const App = () => <div />;\n",
        )


class TestFingerprintPatchMode(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        get_pending_action_registry().clear()
        self.registry = ToolRegistry()
        self.session = "f3-patch"
        self.target = isolated_test_artifact_path("f3_patch", "module.py")
        self.target.write_text("VALUE = 1\nKEEP = True\n", encoding="utf-8")

    async def asyncTearDown(self):
        get_pending_action_registry().clear()

    async def _confirm(self, arguments: dict) -> dict:
        pending = await self.registry.execute_tool(
            "file_write",
            arguments,
            session_id=self.session,
        )
        self.assertEqual(pending["status"], "PENDING_CONFIRMATION")
        return await self.registry.execute_tool(
            "file_write",
            arguments,
            has_confirmed=True,
            confirmation_token=pending["confirmation_token"],
            session_id=self.session,
        )

    async def test_exact_fingerprint_patch_updates_one_block_and_keeps_backup(self):
        read = await self.registry.execute_tool(
            "file_read",
            {"filepath": str(self.target)},
            session_id=self.session,
        )
        fingerprint = read["data"]["sha256"]
        result = await self._confirm(
            {
                "filepath": str(self.target),
                "search_text": "VALUE = 1",
                "replace_text": "VALUE = 2",
                "expected_sha256": fingerprint,
            }
        )
        self.assertTrue(result["success"])
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "VALUE = 2\nKEEP = True\n",
        )
        self.assertTrue(Path(result["data"]["backup"]).is_file())
        self.assertEqual(result["data"]["write_mode"], "patch")

    async def test_stale_patch_fingerprint_preserves_original(self):
        result = await self._confirm(
            {
                "filepath": str(self.target),
                "search_text": "VALUE = 1",
                "replace_text": "VALUE = 9",
                "expected_sha256": "0" * 64,
            }
        )
        self.assertFalse(result["success"])
        self.assertIn("changed since inspection", result["error"])
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "VALUE = 1\nKEEP = True\n",
        )


class TestNativeAgentConfirmationResume(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        get_pending_action_registry().clear()
        self.target = isolated_test_artifact_path("f3_agent", "module.py")
        self.target.write_text("VALUE = 1\n", encoding="utf-8")
        self.initial_sha256 = hashlib.sha256(b"VALUE = 1\n").hexdigest()
        self.relative = str(self.target.relative_to(TEST_ROOT))
        self.session = "f3-native-agent"
        self.orchestrator = CognitiveOrchestrator()
        self.orchestrator.memory.gate.should_save = lambda _prompt: False
        self.orchestrator.router.get_completions_with_tools = AsyncMock(
            side_effect=[
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-read",
                            "name": "file_read",
                            "arguments": {"filepath": self.relative},
                        }
                    ],
                    "provider": "nvidia",
                    "model": "test-native",
                    "native_tools": True,
                    "provider_state": None,
                },
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-write",
                            "name": "file_write",
                            "arguments": {
                                "filepath": self.relative,
                                "content": "VALUE = 2\n",
                                "expected_sha256": self.initial_sha256,
                            },
                        }
                    ],
                    "provider": "nvidia",
                    "model": "test-native",
                    "native_tools": True,
                    "provider_state": None,
                },
                {
                    "content": "Updated module.py after inspection and confirmation.",
                    "tool_calls": [],
                    "provider": "nvidia",
                    "model": "test-native",
                    "native_tools": True,
                    "provider_state": None,
                },
            ]
        )

    async def asyncTearDown(self):
        await self.orchestrator.close()
        get_pending_action_registry().clear()

    async def _confirm_and_resume(self, pending: dict) -> dict:
        confirmed = await ToolRegistry().execute_pending_action(
            pending["confirmation_token"],
            self.session,
            include_resume_context=True,
        )
        context = confirmed.pop("_resume_context")
        return await self.orchestrator.resume_agent_after_confirmation(context, confirmed)

    async def test_file_content_egress_and_write_each_require_exact_resume(self):
        first = await self.orchestrator.process_request(
            "Read and update the code file module",
            self.session,
            project_id="personal",
        )
        read_pending = first["pending_confirmation"]
        self.assertEqual(read_pending["tool_id"], "file_read")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "VALUE = 1\n")
        self.assertEqual(self.orchestrator.router.get_completions_with_tools.await_count, 1)

        after_read = await self._confirm_and_resume(read_pending)
        write_pending = after_read["pending_confirmation"]
        self.assertIsNotNone(write_pending, after_read)
        self.assertEqual(write_pending["tool_id"], "file_write")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "VALUE = 1\n")

        after_write = await self._confirm_and_resume(write_pending)
        self.assertIsNone(after_write["pending_confirmation"])
        self.assertEqual(self.target.read_text(encoding="utf-8"), "VALUE = 2\n")
        self.assertIn("Updated module.py", after_write["content"])
        self.assertEqual(self.orchestrator.router.get_completions_with_tools.await_count, 3)
        final_history = self.orchestrator.router.get_completions_with_tools.await_args.kwargs[
            "conversation"
        ]
        serialized = json.dumps(final_history)
        self.assertIn("VALUE = 1", serialized)
        self.assertNotIn("api_key", serialized.lower())


class TestToolMetadataPersistence(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_chat_persists_real_tools_and_widget(self):
        class FakeOrchestrator:
            async def process_request(self, **_kwargs):
                return {
                    "id": "f3-persisted-tool-turn",
                    "content": "Git status checked.",
                    "active_personality": "ultron",
                    "persisted_personality": "ultron",
                    "structured_action": {"action": "open_widget", "widget_id": "git"},
                    "coding": False,
                    "intent": "DEVELOPER_HELP",
                    "events": [],
                    "pending_confirmation": None,
                    "provider_route": {"provider": "groq", "model": "test", "cached": False},
                    "memory_provenance": [],
                    "tools_used": ["git_status"],
                    "widget_shown": "git",
                }

        result = await process_chat_message(
            FakeOrchestrator(),
            "Check git status",
            session_id="f3-tool-metadata-session",
            project_id="personal",
        )
        from backend.app.database.db import get_db_connection
        from backend.app.database.models import get_conversation_history

        with get_db_connection() as connection:
            history = get_conversation_history(
                connection,
                result["session_id"],
                limit=1,
            )
        self.assertEqual(history[-1]["tools_used"], ["git_status"])
        self.assertEqual(history[-1]["widget_shown"], "git")

    def test_frontend_keeps_next_resumed_confirmation_visible(self):
        app = Path("frontend/src/App.jsx").read_text(encoding="utf-8")
        self.assertIn("result.pending_confirmation?.confirmation_token", app)
        self.assertIn("setPendingAction(nextPending)", app)
        self.assertIn("Next confirmation required", app)


if __name__ == "__main__":
    unittest.main()
