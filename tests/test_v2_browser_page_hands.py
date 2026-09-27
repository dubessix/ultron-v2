"""Final list step 4: hands inside the open web page.

The page work itself (look, click, type, scroll, the send/buy guard) is tested
in frontend/src/browserPageHands.test.js with the real extension code. Here: the
tool, the one-yes rule, the spoken question, the menu, and step 2's screen
vision being findable by the brain.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.app.core import approval
from backend.app.tools import browser_tools
from backend.app.tools.browser_tools import BrowserPageTool
from backend.app.tools.tool_catalog import build_tool_menu
from backend.app.tools.tool_registry import ToolRegistry


class TestTool(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        browser_tools._last_needs_yes.clear()
        self.tool = BrowserPageTool()

    async def test_sends_the_step_to_the_helper(self):
        call = AsyncMock(return_value={"success": True, "data": {"clicked": "Add to cart"}, "error": None})
        with patch("backend.app.core.browser_bridge.call", new=call):
            result = await self.tool.execute(action="click", target="3")
        self.assertTrue(result["success"])
        action, args = call.await_args.args
        self.assertEqual(action, "click")
        self.assertEqual(args["target"], "3")
        self.assertEqual(args["which"], "current")
        self.assertFalse(args["confirmed"])

    async def test_needs_yes_is_remembered_for_the_question(self):
        reply = {"success": True, "error": None, "data": {"done": False, "needs_yes": True, "label": "Place your order"}}
        with patch("backend.app.core.browser_bridge.call", new=AsyncMock(return_value=reply)):
            await self.tool.execute(action="click", target="12")
        question = approval.describe("browser_page", {"action": "click", "target": "12", "confirmed": True})
        self.assertEqual(question, "Should I press Place your order, Sir? Say yes or no.")

    async def test_old_helper_gets_a_clear_fix(self):
        reply = {"success": False, "data": {}, "error": 'Unknown browser action "look".'}
        with patch("backend.app.core.browser_bridge.call", new=AsyncMock(return_value=reply)):
            result = await self.tool.execute(action="look")
        self.assertIn("chrome://extensions", result["error"])

    async def test_type_without_text_does_nothing(self):
        call = AsyncMock()
        with patch("backend.app.core.browser_bridge.call", new=call):
            result = await self.tool.execute(action="type", target="search")
        self.assertFalse(result["success"])
        call.assert_not_awaited()


class TestOneYes(unittest.TestCase):
    def test_normal_steps_never_ask(self):
        for args in ({"action": "look"}, {"action": "click", "target": "3"},
                     {"action": "type", "target": "search", "text": "cable", "submit": True}):
            self.assertEqual(BrowserPageTool().permission_for_arguments(args), 0)
            self.assertFalse(approval.needs_ask("browser_page", args, 0))

    def test_confirmed_always_asks_so_the_brain_cannot_skip_the_yes(self):
        args = {"action": "click", "target": "Buy now", "confirmed": True}
        self.assertEqual(BrowserPageTool().permission_for_arguments(args), 2)
        self.assertTrue(approval.needs_ask("browser_page", args, 2))

    def test_send_question_reads_words_not_symbols(self):
        question = approval.describe("browser_page", {"action": "type", "submit": True, "text": "Hi Riya :) <3 @5pm"})
        self.assertEqual(question, "Should I send this: Hi Riya 3 5pm, Sir? Say yes or no.")


class TestBrainCanFindThem(unittest.TestCase):
    def test_menu_lists_page_hands_and_screen_vision_and_stays_small(self):
        menu = build_tool_menu(ToolRegistry().get_registered_ids())
        self.assertIn("browser_page(action=look|click|type|scroll", menu)
        self.assertIn("screenshot(?question, ?image_path", menu)
        self.assertLess(len(menu) // 4, 1100)

    def test_words_attach_the_full_schemas(self):
        from backend.app.tools.context_builder import ToolContextBuilder

        ids = ToolRegistry().get_registered_ids()
        pick = ToolContextBuilder.select_relevant_tool_ids
        self.assertIn("browser_page", pick("click the buy button on amazon", ids))
        self.assertIn("browser_page", pick("type usb cable in the search box", ids))
        self.assertIn("screenshot", pick("what is on my screen right now", ids))
        self.assertIn("screenshot", pick("read this error for me", ids))

if __name__ == "__main__":
    unittest.main()
