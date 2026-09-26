"""Browser helper extras: sleep tabs (free RAM), reopen closed, close duplicates, find in history."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from backend.app.core.live_progress import line_for
from backend.app.tools.browser_tools import BrowserTabsArgs, BrowserTabsTool
from backend.app.tools.context_builder import ToolContextBuilder as ContextBuilder
from backend.app.tools.tool_registry import ToolRegistry

EXTRAS = ("sleep", "reopen", "dedupe", "history")


class TestBrowserTabExtras(unittest.TestCase):
    def test_new_actions_are_accepted(self):
        for action in EXTRAS:
            self.assertEqual(BrowserTabsArgs(action=action).action, action)
        with self.assertRaises(ValidationError):
            BrowserTabsArgs(action="explode")

    def test_tool_passes_action_and_words_to_the_helper(self):
        fake = AsyncMock(return_value={"success": True, "data": {"slept": 3}, "error": None})
        with patch("backend.app.core.browser_bridge.call", fake):
            for action in EXTRAS:
                result = asyncio.run(BrowserTabsTool().execute(action=action, which="react hooks"))
                self.assertTrue(result["success"])
                fake.assert_awaited_with(action, {"which": "react hooks"})
            asyncio.run(BrowserTabsTool().execute(action="sleep"))
            fake.assert_awaited_with("sleep", {"which": "current"})

    def test_no_helper_gives_setup_steps_not_a_crash(self):
        with patch("backend.app.core.browser_bridge._socket", None):
            result = asyncio.run(BrowserTabsTool().execute(action="sleep"))
        self.assertFalse(result["success"])
        self.assertIn("chrome://extensions", result["error"])

    def test_plain_talk_along_lines(self):
        self.assertEqual(line_for("browser_tabs", {"action": "sleep"}), "Putting tabs to sleep to free memory")
        self.assertEqual(line_for("browser_tabs", {"action": "reopen"}), "Reopening the tab")
        self.assertEqual(line_for("browser_tabs", {"action": "dedupe"}), "Closing duplicate tabs")
        self.assertEqual(line_for("browser_tabs", {"action": "history", "which": "react hooks"}),
                         "Searching your history for react hooks")

    def test_owner_words_bring_the_tab_tool(self):
        ids = ToolRegistry().get_registered_ids()
        for prompt in ("chrome is slow", "free some memory please", "open back the tab I closed",
                       "close duplicate tabs", "open the site about react hooks I saw yesterday"):
            with self.subTest(prompt=prompt):
                self.assertIn("browser_tabs", ContextBuilder.select_relevant_tool_ids(prompt, ids))


if __name__ == "__main__":
    unittest.main()
