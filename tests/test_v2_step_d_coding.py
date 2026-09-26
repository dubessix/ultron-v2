"""V2 Step D: the coding brain works like the Jarvis brain.

- reading project files needs no yes; secret/key files are blocked in code
- a failed step goes back to the brain (it can fix it) instead of ending the job
- three failures in a row -> honest stop, never a loop
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.security.path_guard import _contains_sensitive_component, check_path


def _reply(*calls, content=""):
    return {"content": content, "tool_calls": [{"id": f"c{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(calls)],
            "provider": "nvidia", "model": "test", "native_tools": True, "provider_state": None}


class TestSecretsStayBlocked(unittest.TestCase):
    def test_key_and_token_files_are_blocked_everywhere(self):
        for path in ("~/proj/server.key", "~/proj/cert.pem", "~/.npmrc", "~/.pypirc", "~/proj/.env.local",
                     "~/.ssh/config", "~/vault.kdbx", "~/.docker/config.json"):
            with self.subTest(path=path):
                self.assertTrue(_contains_sensitive_component(Path(path).expanduser()))
                self.assertFalse(check_path(str(Path(path).expanduser()))["safe"])

    def test_normal_code_files_are_not_blocked(self):
        for path in ("~/proj/app.py", "~/proj/keyboard.js", "~/proj/README.md", "~/proj/keys.txt"):
            with self.subTest(path=path):
                self.assertFalse(_contains_sensitive_component(Path(path).expanduser()))


class TestCodingBrainKeepsGoing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.orchestrator = CognitiveOrchestrator()
        self.calls = []

        async def fake_exec(call, **kwargs):
            self.calls.append((call["name"], kwargs["coding_turn"]))
            ok = call["name"] != "file_read" or call["arguments"].get("filepath") == "good.py"
            return call["arguments"], ({"success": True, "data": {"content": "x = 1"}, "error": None} if ok
                                       else {"success": False, "data": {}, "error": "File not found."})

        self.orchestrator._execute_native_agent_call = fake_exec

    async def asyncTearDown(self):
        await self.orchestrator.close()

    async def _loop(self, first, *later):
        self.orchestrator.router.get_completions_with_tools = AsyncMock(side_effect=list(later))
        return await self.orchestrator._run_native_agent_loop(
            first, system_prompt="s", user_prompt="fix the bug", tools=[], session_id="d-test",
            project_id="personal", project_root=str(Path.home()), coding_turn=True, provider_for_turn="nvidia")

    async def test_a_failure_goes_back_to_the_brain_which_fixes_it(self):
        result = await self._loop(
            _reply(("file_read", {"filepath": "wrong.py"})),
            _reply(("file_read", {"filepath": "good.py"})),
            _reply(content="Fixed it, Sir."),
        )
        self.assertEqual([c[0] for c in self.calls], ["file_read", "file_read"])
        self.assertEqual(result["content"], "Fixed it, Sir.")
        self.assertTrue(result["tool_results"][-1]["success"])

    async def test_three_failures_in_a_row_stop_honestly(self):
        bad = _reply(("file_read", {"filepath": "wrong.py"}))
        result = await self._loop(bad, bad, bad, bad, bad)
        self.assertEqual(len(self.calls), 3)
        self.assertIn("3 failed tries in a row", result["content"])
        self.assertIn("File not found", result["content"])

    async def test_a_success_resets_the_count(self):
        bad = _reply(("file_read", {"filepath": "wrong.py"}))
        good = _reply(("file_read", {"filepath": "good.py"}))
        result = await self._loop(bad, bad, good, bad, bad, _reply(content="Done after retries."))
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(result["content"], "Done after retries.")


if __name__ == "__main__":
    unittest.main()
