"""
Phase 5 regression — GitHub integration security.

  - When no real token is configured, the tool reports an honest "unavailable"
    state (configured=False) — never fake/dummy success data.
  - Free-text args with shell metacharacters are rejected (defense-in-depth).
  - The PAT is NEVER placed into the git command line / remote URL; it is passed
    only via the subprocess environment to a credential helper.
"""

import asyncio
import os
import unittest
from unittest.mock import patch

from backend.app.tools.github_integration_tool import GitHubIntegrationTool


def _run(coro):
    return asyncio.run(coro)


class FakeProc:
    returncode = 0

    def __init__(self, argv, env):
        self.argv = argv
        self.env = env

    async def communicate(self):
        return b"ok", b""


async def _fake_exec(*args, **kwargs):
    return FakeProc(args, kwargs.get("env") or os.environ)


class TestGitHubNotConfiguredHonest(unittest.TestCase):

    def test_placeholder_token_returns_honest_unavailable(self):
        os.environ["GITHUB_TOKEN_1"] = "your_github_token_here"  # placeholder
        os.environ["GITHUB_USERNAME_1"] = "debjeet"
        r = _run(GitHubIntegrationTool().execute(action="commit_push"))
        self.assertTrue(r["success"])
        self.assertIs(r["data"]["configured"], False)
        # Must NOT contain the old fake dummy item data.
        self.assertNotIn("items", r["data"])
        self.assertIn("NOT CONFIGURED", r["data"]["message"].upper())


class TestArgInjectionBlocked(unittest.TestCase):

    def test_unsafe_commit_message_rejected(self):
        os.environ["GITHUB_TOKEN_1"] = "ghp_REAL_TEST_TOKEN"
        r = _run(GitHubIntegrationTool().execute(
            action="commit_push", commit_message="good message; rm -rf /"))
        self.assertFalse(r["success"])
        self.assertIn("unsafe", r["error"].lower())


class TestTokenNeverInCommand(unittest.TestCase):

    def test_push_passes_token_via_env_not_argv(self):
        token = "ghp_SUPERSECRET_TOKEN_123"
        captured = {}

        async def fake_exec(*args, **kwargs):
            captured["argv"] = args
            captured["env"] = kwargs.get("env") or os.environ
            return FakeProc(args, kwargs.get("env") or os.environ)

        with patch("asyncio.create_subprocess_exec", fake_exec):
            _run(GitHubIntegrationTool()._git_push_secure(token, "debjeet"))

        argv_str = " ".join(captured["argv"])
        # Token must never appear in the command line.
        self.assertNotIn(token, argv_str)
        # And must not try to embed a token in a remote URL.
        self.assertNotIn("@github.com", argv_str)
        # The token is only in the subprocess environment for the credential helper.
        self.assertEqual(captured["env"].get("GIT_PUSH_TOKEN"), token)
        # The push command uses a credential helper, not shell interpolation.
        self.assertIn("credential.helper=", argv_str)


if __name__ == "__main__":
    unittest.main()
