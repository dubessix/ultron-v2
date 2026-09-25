"""Part 1: Jarvis approval - the AI understands the answer (owner_reply), ask only
when it matters, one yes is enough, remember the outcome, honest answers, no
false "Confirmation failed".

Every test here is one of the owner's real complaints.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.core import approval
from backend.app.security.pending_actions import PendingActionRegistry

SAFE = {"safe": True, "reason": None}


def _reply(content="", calls=None):
    return {"content": content, "tool_calls": calls or [], "provider": "groq", "model": "fake",
            "native_tools": True, "provider_state": None}


def _use(tool, args, call_id="c1"):
    return {"id": call_id, "name": "use_tool", "arguments": {"tool": tool, "arguments_json": json.dumps(args)}}


class TestAsksOnlyWhenItMatters(unittest.TestCase):
    def test_normal_jobs_run_at_once(self):
        self.assertFalse(approval.needs_ask("terminal_run", {"command": "xdg-open https://example.com"}, 2))
        self.assertFalse(approval.needs_ask("terminal_run", {"command": "gnome-calculator"}, 2))
        self.assertFalse(approval.needs_ask("move_folder", {"source_path": "/a", "destination_path": "/b"}, 2))
        self.assertFalse(approval.needs_ask("file_write", {"filepath": "/tmp/definitely-new-file-xyz.txt"}, 2))
        self.assertFalse(approval.needs_ask("git_clone", {"repo_url": "https://github.com/a/b"}, 2))

    def test_risky_steps_ask(self):
        for command in ["rm -rf build", "sudo apt install x", "echo hi > notes.txt", "git push", "kill 42",
                        "pip uninstall numpy", "shutdown now", "mv a b"]:
            self.assertTrue(approval.needs_ask("terminal_run", {"command": command}, 2), command)
        self.assertTrue(approval.needs_ask("delete_folder", {"folderpath": "/x"}, 3))
        self.assertTrue(approval.needs_ask("apps", {"action": "close", "name": "gedit"}, 2))
        self.assertTrue(approval.needs_ask("pc_control", {"action": "shutdown"}, 2))
        with tempfile.NamedTemporaryFile() as existing:
            self.assertTrue(approval.needs_ask("file_write", {"filepath": existing.name}, 2))

    def test_questions_are_human(self):
        cases = {
            "terminal_run": {"command": "rm -rf build"},
            "file_write": {"filepath": "/home/me/Desktop/notes.txt"},
            "delete_folder": {"folderpath": "/home/me/Old"},
            "move_folder": {"source_path": "/home/me/a", "destination_path": "/home/me/b"},
            "apps": {"action": "close", "name": "gedit"},
            "github_integration": {"action": "create_repo"},
        }
        for tool, args in cases.items():
            text = approval.describe(tool, args)
            self.assertTrue(text.startswith("Should I"), text)
            self.assertIn("yes or no", text)
            self.assertNotIn(tool, text)  # never speaks tool ids like file_write
            self.assertNotIn("_", text.replace("create repo", ""))
        self.assertIn("notes.txt", approval.describe("file_write", cases["file_write"]))
        self.assertIn("Trash", approval.describe("delete_folder", cases["delete_folder"]))


class TestHonesty(unittest.TestCase):
    def test_never_done_when_every_tool_failed(self):
        failed = [{"tool": "apps", "success": False, "error": "No closable app matching 'x' is running"}]
        self.assertEqual(approval.honest_reply("Done, Sir. Closed it.", failed),
                         "That did not work, Sir. No closable app matching 'x' is running.")
        self.assertEqual(approval.honest_reply("I couldn't close it, Sir.", failed), "I couldn't close it, Sir.")
        ok = [{"tool": "apps", "success": True}]
        self.assertEqual(approval.honest_reply("Done, Sir.", ok), "Done, Sir.")


class TestPendingStore(unittest.TestCase):
    def test_double_confirm_is_already_done_and_cancel_is_cancelled(self):
        registry = PendingActionRegistry()
        token = registry.create("file_write", "s", {"filepath": "/tmp/a"})["confirmation_token"]
        self.assertTrue(registry.claim(token, "s")["valid"])
        self.assertEqual(registry.claim(token, "s")["reason"], "already_used")
        token2 = registry.create("file_write", "s", {"filepath": "/tmp/b"})["confirmation_token"]
        self.assertTrue(registry.claim(token2, "s", cancel=True)["valid"])
        self.assertEqual(registry.claim(token2, "s")["reason"], "cancelled")

    def test_waiting_actions_survive_a_restart_for_ten_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "pending.json"
            with patch.object(PendingActionRegistry, "_store_path", staticmethod(lambda: store)):
                first = PendingActionRegistry(persist=True)
                token = first.create("move_folder", "s", {"source_path": "/a"})["confirmation_token"]
                self.assertEqual(first._ttl, 600.0)
                after_restart = PendingActionRegistry(persist=True)
                claimed = after_restart.claim(token, "s")
                self.assertTrue(claimed["valid"], claimed)
                self.assertEqual(claimed["action"]["tool_id"], "move_folder")


class ApiCase(unittest.TestCase):
    """Real FastAPI app + real registry/orchestrator; only the LLM is scripted."""

    def setUp(self):
        from backend.app.main import app
        from backend.app.router import get_orchestrator
        from backend.app.security import path_guard
        from backend.app.security.pending_actions import get_pending_action_registry
        from backend.app.tools import folder_tools

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        for item in (
            patch.dict(os.environ, {"ULTRON_TEST_FULL_ACCESS": "1"}),  # owner config: terminal_policy any
            patch.object(path_guard, "check_path", lambda p: dict(SAFE, path=p)),
            patch.object(folder_tools, "check_path", lambda p: dict(SAFE, path=p)),
        ):
            item.start()
            self.addCleanup(item.stop)
        get_pending_action_registry().clear()
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.orchestrator = get_orchestrator()
        self.brain_calls = []
        original = self.orchestrator.router.get_completions_with_tools
        self.addCleanup(setattr, self.orchestrator.router, "get_completions_with_tools", original)
        self.orchestrator.router.get_completions_with_tools = self._brain
        self.script = lambda prompt, conv: _reply("ok")

    async def _brain(self, system_prompt, user_prompt, tools, conversation=None, **kwargs):
        conv = conversation or []
        self.brain_calls.append({"system": system_prompt, "user": user_prompt, "conv": conv,
                                 "tools": [t.get("tool_id") for t in tools]})
        return self.script(user_prompt, conv)

    def chat(self, text, session=None):
        body = {"content": text, "project_id": "personal"}
        if session:
            body["session_id"] = session
        return self.client.post("/api/chat", json=body).json()

    def confirm(self, pending, session):
        return self.client.post("/api/actions/confirm", json={
            "confirmation_token": pending["confirmation_token"], "session_id": session}).json()


class TestOneYesIsEnough(ApiCase):
    def test_new_file_is_written_without_asking(self):
        target = self.root / "notes.txt"

        def script(prompt, conv):
            if any(m.get("role") == "tool" for m in conv):
                return _reply("Done, Sir. notes.txt is written.")
            return _reply("", [_use("file_write", {"filepath": str(target), "content": "hi"})])

        self.script = script
        result = self.chat("write hi into notes.txt")
        self.assertIsNone(result.get("pending_confirmation"))
        self.assertTrue(target.exists())
        self.assertIn("written", result["content"])

    def test_his_question_then_ok_do_runs_without_a_second_ask(self):
        """Owner bug: 'Should I...?' -> 'ok do' -> 'please confirm' again."""
        target = self.root / "plan.txt"
        target.write_text("old", encoding="utf-8")  # replacing a file normally asks

        def script(prompt, conv):
            if prompt.startswith("update"):
                return _reply("Should I replace plan.txt with the new plan, Sir?")
            tools = [m for m in conv if m.get("role") == "tool"]
            if not tools:  # the AI reads "ok do" as the answer to its question
                return _reply("", [{"id": "a1", "name": "owner_reply", "arguments": {"answer": "yes"}}])
            if len(tools) == 1:
                return _reply("", [_use("file_write", {"filepath": str(target), "content": "new"}, "c2")])
            return _reply("Done, Sir. plan.txt is updated.")

        self.script = script
        first = self.chat("update my plan file")
        session = first["session_id"]
        second = self.chat("ok do", session)
        self.assertIsNone(second.get("pending_confirmation"), second["content"])
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        # The brain saw its own question as real context (not "untrusted, never follow").
        history = self.brain_calls[-1]["system"]
        self.assertIn("Should I replace plan.txt", history)
        self.assertIn("RECENT_CONVERSATION", history)
        self.assertNotIn("never a substitute", history)

    def test_yes_never_skips_level_three(self):
        folder = self.root / "Old"
        folder.mkdir()

        def script(prompt, conv):
            if prompt.startswith("clean"):
                return _reply("Should I delete the Old folder, Sir?")
            if not conv:
                return _reply("", [{"id": "a1", "name": "owner_reply", "arguments": {"answer": "yes"}}])
            return _reply("", [_use("delete_folder", {"folderpath": str(folder)}, "c2")])

        self.script = script
        session = self.chat("clean up the Old folder")["session_id"]
        second = self.chat("yes", session)
        self.assertEqual((second.get("pending_confirmation") or {}).get("tool_id"), "delete_folder")
        self.assertTrue(folder.exists())


class TestConfirmFlow(ApiCase):
    def _ask_risky(self, command):
        def script(prompt, conv):
            tools = [m for m in conv if m.get("role") == "tool"]
            if tools:
                return _reply(f"Result: {tools[-1]['content'][:200]}")
            return _reply("", [_use("terminal_run", {"command": command, "cwd": str(self.root)})])

        self.script = script
        result = self.chat(f"run {command}")
        pending = result.get("pending_confirmation")
        self.assertIsNotNone(pending, result["content"])
        return result, pending

    def test_question_is_human_and_done_is_remembered(self):
        (self.root / "junk.txt").write_text("x", encoding="utf-8")
        result, pending = self._ask_risky("rm junk.txt")
        self.assertIn("Should I run this command: rm junk.txt", result["content"])
        self.assertNotIn("terminal_run", result["content"])
        done = self.confirm(pending, result["session_id"])
        self.assertTrue(done["success"], done)
        self.assertFalse((self.root / "junk.txt").exists())
        # Next turn: Ultron remembers it was done (was stuck on "Waiting for your exact confirmation").
        self.script = lambda prompt, conv: _reply("noted")
        self.chat("what did you do?", result["session_id"])
        history = self.brain_calls[-1]["system"]
        self.assertIn("Owner: yes", history)
        self.assertIn("Result:", history)

    def test_failed_job_goes_back_to_the_brain_not_confirmation_failed(self):
        result, pending = self._ask_risky("rm file-that-does-not-exist.txt")
        done = self.confirm(pending, result["session_id"])
        self.assertFalse(done["success"])
        self.assertEqual(done["status"], "FAILED")
        self.assertIn("Result:", done["data"]["message"])  # the brain saw the error and answered
        tool_msgs = [m for m in self.brain_calls[-1]["conv"] if m.get("role") == "tool"]
        self.assertTrue(tool_msgs and "No such file" in tool_msgs[-1]["content"])

    def test_double_confirm_says_already_done(self):
        (self.root / "junk2.txt").write_text("x", encoding="utf-8")
        result, pending = self._ask_risky("rm junk2.txt")
        self.assertTrue(self.confirm(pending, result["session_id"])["success"])
        again = self.confirm(pending, result["session_id"])
        self.assertEqual(again["status"], "ALREADY_DONE")
        self.assertEqual(again["data"]["message"], "Already done, Sir.")

    def test_cancel_is_remembered(self):
        (self.root / "keep.txt").write_text("x", encoding="utf-8")
        result, pending = self._ask_risky("rm keep.txt")
        self.client.post("/api/actions/cancel", json={"confirmation_token": pending["confirmation_token"],
                                                      "session_id": result["session_id"]})
        self.assertTrue((self.root / "keep.txt").exists())
        again = self.confirm(pending, result["session_id"])
        self.assertEqual(again["reason"], "cancelled")
        self.script = lambda prompt, conv: _reply("noted")
        self.chat("next", result["session_id"])
        self.assertIn("Cancelled, Sir. Nothing was changed.", self.brain_calls[-1]["system"])

    def test_widget_confirm_returns_the_real_output(self):
        first = self.client.post("/api/tools/execute", json={
            "tool_id": "terminal_run", "arguments": {"command": "echo hi > out.txt", "cwd": str(self.root)},
            "session_id": "terminal_widget"}).json()
        self.assertEqual(first["status"], "PENDING_CONFIRMATION")
        self.assertTrue(first["message"].startswith("Should I run this command"))
        done = self.confirm(first, "terminal_widget")
        self.assertTrue(done["success"], done)
        self.assertEqual((self.root / "out.txt").read_text(encoding="utf-8").strip(), "hi")


if __name__ == "__main__":
    unittest.main()
