"""Regression tests for allowlisted paths and exact one-time confirmations."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.main import app
from backend.app.runtime_paths import BASE_DIR, isolated_test_artifact_path
from backend.app.security import path_guard
from backend.app.security.pending_actions import get_pending_action_registry
from backend.app.tools.tool_registry import ToolRegistry


class TestAllowedDirectoryPolicy(unittest.TestCase):
    def setUp(self):
        self.allowed = isolated_test_artifact_path("phase2_allowed")
        self.allowed.mkdir(parents=True, exist_ok=True)
        self.config = isolated_test_artifact_path("phase2_path_config.yaml")
        self.config.write_text(
            "security:\n"
            f"  allowed_directories: ['{self.allowed}']\n"
            "  empty_allowed_policy: project_only\n"
            "  blocked_directories: ['/etc']\n",
            encoding="utf-8",
        )
        self.original_config = path_guard.CONFIG_PATH
        path_guard.CONFIG_PATH = self.config

    def tearDown(self):
        path_guard.CONFIG_PATH = self.original_config

    def test_configured_allowed_root_is_enforced(self):
        self.assertTrue(path_guard.is_path_safe(str(self.allowed / "ok.txt")))
        self.assertFalse(path_guard.is_path_safe("/tmp/not-an-ultron-test-root/file.txt"))
        self.assertFalse(path_guard.is_path_safe("/etc/passwd"))

    @unittest.skipIf(os.name == "nt", "POSIX symlink test")
    def test_symlink_escape_is_blocked(self):
        link = self.allowed / "escape"
        link.symlink_to("/etc", target_is_directory=True)
        decision = path_guard.check_path(str(link / "passwd"))
        self.assertFalse(decision["safe"])
        self.assertEqual(decision["reason"], "blocked_system_path")

    def test_secure_empty_policy_defaults_to_project_root(self):
        self.config.write_text(
            "security:\n  allowed_directories: []\n  empty_allowed_policy: project_only\n",
            encoding="utf-8",
        )
        self.assertTrue(path_guard.is_path_safe(str(BASE_DIR / "backend" / "app" / "main.py")))
        self.assertFalse(path_guard.is_path_safe("/tmp/outside-project/file.txt"))


class TestExactToolConfirmation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        get_pending_action_registry().clear()
        self.registry = ToolRegistry()
        self.session = "phase2_exact"
        self.target = isolated_test_artifact_path("phase2", "new_file.txt")
        self.target.unlink(missing_ok=True)
        Path(str(self.target) + ".bak").unlink(missing_ok=True)
        self.args = {"filepath": str(self.target), "content": "EXACT CONTENT"}

    async def test_new_file_requires_token_and_raw_boolean_cannot_bypass(self):
        pending = await self.registry.execute_tool(
            "file_write", self.args, session_id=self.session
        )
        self.assertEqual(pending["status"], "PENDING_CONFIRMATION")
        self.assertFalse(self.target.exists())

        raw_boolean = await self.registry.execute_tool(
            "file_write", self.args, has_confirmed=True, session_id=self.session
        )
        self.assertEqual(raw_boolean["status"], "PENDING_CONFIRMATION")
        self.assertFalse(self.target.exists())

        result = await self.registry.execute_tool(
            "file_write",
            self.args,
            has_confirmed=True,
            confirmation_token=pending["confirmation_token"],
            session_id=self.session,
        )
        self.assertTrue(result["success"])
        self.assertEqual(self.target.read_text(encoding="utf-8"), "EXACT CONTENT")

    async def test_token_rejects_argument_session_and_replay_changes(self):
        pending = await self.registry.execute_tool(
            "file_write", self.args, session_id=self.session
        )
        token = pending["confirmation_token"]

        wrong_session = await self.registry.execute_tool(
            "file_write",
            self.args,
            has_confirmed=True,
            confirmation_token=token,
            session_id="other-session",
        )
        self.assertEqual(wrong_session["status"], "PENDING_CONFIRMATION")
        self.assertFalse(self.target.exists())

        changed = {**self.args, "content": "CHANGED"}
        wrong_arguments = await self.registry.execute_tool(
            "file_write",
            changed,
            has_confirmed=True,
            confirmation_token=token,
            session_id=self.session,
        )
        self.assertEqual(wrong_arguments["status"], "PENDING_CONFIRMATION")
        self.assertFalse(self.target.exists())

        exact = await self.registry.execute_tool(
            "file_write",
            self.args,
            has_confirmed=True,
            confirmation_token=token,
            session_id=self.session,
        )
        self.assertTrue(exact["success"])

        replay = await self.registry.execute_tool(
            "file_write",
            self.args,
            has_confirmed=True,
            confirmation_token=token,
            session_id=self.session,
        )
        self.assertEqual(replay["status"], "PENDING_CONFIRMATION")

    async def test_claim_executes_stored_action_directly(self):
        pending = await self.registry.execute_tool(
            "file_write", self.args, session_id=self.session
        )
        result = await self.registry.execute_pending_action(
            pending["confirmation_token"], self.session
        )
        self.assertTrue(result["success"])
        self.assertTrue(self.target.exists())

    async def test_unsafe_path_is_rejected_before_confirmation(self):
        result = await self.registry.execute_tool(
            "file_write",
            {"filepath": "/etc/ultron-test", "content": "x"},
            session_id=self.session,
        )
        self.assertFalse(result["success"])
        self.assertNotEqual(result.get("status"), "PENDING_CONFIRMATION")
        self.assertIn("blocked", result["error"].lower())

    async def test_all_filesystem_entry_points_apply_path_preflight(self):
        cases = {
            "file_read": {"filepath": "/etc/passwd"},
            "find_files": {"pattern": "*", "search_root": "/etc"},
            "create_folder": {"folderpath": "/etc/ultron"},
            "rename_folder": {"old_path": "/etc/a", "new_path": "/etc/b"},
            "delete_folder": {"folderpath": "/etc/ultron"},
            "copy_folder": {"source_path": "/etc", "destination_path": "/etc/copy"},
            "move_folder": {"source_path": "/etc/a", "destination_path": "/etc/b"},
            "list_contents": {"folderpath": "/etc"},
            "compress_folder": {"folderpath": "/etc"},
            "extract_zip": {"zippath": "/etc/a.zip", "extract_to": "/etc/out"},
            "organize_folder": {"folderpath": "/etc"},
            "convert_file_format": {"source_filepath": "/etc/a.json", "destination_filepath": "/etc/a.csv"},
            "optimize_code": {"filepath": "/etc/a.py"},
            "git_clone": {"url": "https://example.com/repo.git", "directory": "/etc/repo"},
            "download_file": {"url": "https://example.com/a", "save_path": "/etc/a"},
            "play_music": {"filepath": "/etc/a.mp3"},
            "open_vscode": {"path": "/etc"},
        }
        for tool_id, arguments in cases.items():
            with self.subTest(tool=tool_id):
                result = await self.registry.execute_tool(
                    tool_id, arguments, session_id=self.session
                )
                self.assertFalse(result["success"], tool_id)
                self.assertNotEqual(result.get("status"), "PENDING_CONFIRMATION", tool_id)
                self.assertIn("blocked", result["error"].lower(), tool_id)


class TestConfirmationAPI(unittest.TestCase):
    def setUp(self):
        get_pending_action_registry().clear()
        self.client = TestClient(app)
        self.target = isolated_test_artifact_path("phase2_api", "confirmed.txt")
        self.session = "phase2_api_session"

    def test_api_executes_exact_pending_action_without_prompt_replay(self):
        first = self.client.post(
            "/api/tools/execute",
            json={
                "tool_id": "file_write",
                "arguments": {"filepath": str(self.target), "content": "FROM API"},
                "session_id": self.session,
            },
        )
        self.assertEqual(first.status_code, 200)
        pending = first.json()
        self.assertEqual(pending["status"], "PENDING_CONFIRMATION")
        self.assertFalse(self.target.exists())

        confirmed = self.client.post(
            "/api/actions/confirm",
            json={
                "confirmation_token": pending["confirmation_token"],
                "session_id": self.session,
            },
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(confirmed.json()["success"])
        self.assertEqual(self.target.read_text(encoding="utf-8"), "FROM API")

        replay = self.client.post(
            "/api/actions/confirm",
            json={
                "confirmation_token": pending["confirmation_token"],
                "session_id": self.session,
            },
        ).json()
        self.assertFalse(replay["success"])
        self.assertEqual(replay["status"], "CONFIRMATION_REJECTED")

    def test_websocket_carries_pending_token_and_direct_confirm_executes(self):
        target = isolated_test_artifact_path("phase2_ws", "module.py")
        tool_call = (
            "Working\n[TOOL_CALLS_START]\n"
            + json.dumps([{
                "tool_id": "file_write",
                "args": {"filepath": str(target), "content": "WS_VALUE = 1\n"},
            }])
            + "\n[TOOL_CALLS_END]"
        )
        with patch(
            "backend.app.brain.llm_router.LLMRouter.get_completions",
            side_effect=[tool_call, "Waiting for confirmation."],
        ):
            with self.client.websocket_connect("/ws/chat?client_id=phase2_exact") as ws:
                ws.send_json({
                    "session_id": self.session,
                    "content": "write code file module",
                })
                done = None
                while done is None:
                    frame = ws.receive_json()
                    if frame["type"] == "done":
                        done = frame

        pending = done["pending_confirmation"]
        self.assertTrue(pending["confirmation_token"])
        self.assertFalse(target.exists())
        result = self.client.post(
            "/api/actions/confirm",
            json={
                "confirmation_token": pending["confirmation_token"],
                "session_id": self.session,
            },
        ).json()
        self.assertTrue(result["success"])
        self.assertEqual(target.read_text(encoding="utf-8"), "WS_VALUE = 1\n")


class TestOrchestratorPendingPropagation(unittest.IsolatedAsyncioTestCase):
    async def test_pending_token_survives_orchestrator_result(self):
        target = isolated_test_artifact_path("phase2_orchestrator", "module.py")
        orchestrator = CognitiveOrchestrator()
        orchestrator.memory.gate.should_save = lambda _prompt: False
        calls = 0

        async def fake_completion(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return (
                    "Working\n[TOOL_CALLS_START]\n"
                    + json.dumps([{
                        "tool_id": "file_write",
                        "args": {"filepath": str(target), "content": "VALUE = 1\n"},
                    }])
                    + "\n[TOOL_CALLS_END]"
                )
            return "Waiting for exact confirmation."

        orchestrator.router.get_completions = fake_completion
        result = await orchestrator.process_request(
            "write code file module",
            "phase2_orchestrator_session",
        )
        pending = result["pending_confirmation"]
        self.assertIsNotNone(pending)
        self.assertTrue(pending["confirmation_token"])
        self.assertEqual(pending["tool_id"], "file_write")
        self.assertFalse(target.exists())
        await orchestrator.close()


class TestFrontendConfirmationContract(unittest.TestCase):
    def test_frontend_uses_token_endpoint_and_no_raw_true_bypass(self):
        app_source = (BASE_DIR / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        shell_source = (BASE_DIR / "frontend" / "src" / "components" / "AppShell.jsx").read_text(encoding="utf-8")
        api_source = (BASE_DIR / "frontend" / "src" / "api.js").read_text(encoding="utf-8")
        widget_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (BASE_DIR / "frontend" / "src" / "components" / "widgets").glob("*.jsx")
        )

        self.assertIn("/api/actions/confirm", app_source)
        self.assertIn("pendingAction?.confirmation_token", shell_source)
        self.assertIn("confirmation_token", api_source)
        self.assertNotIn("has_confirmed: true", app_source + widget_sources)


if __name__ == "__main__":
    unittest.main()
