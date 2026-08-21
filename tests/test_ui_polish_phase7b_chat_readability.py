"""Phase 7B regressions for chat readability and launcher hover names."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "frontend" / "src" / "components"
RIGHT = COMPONENTS / "RightPanel.jsx"
RAIL = COMPONENTS / "WidgetRail.jsx"


class TestRightChatReadability(unittest.TestCase):
    def test_chat_scroll_area_and_messages_contain_long_sources(self):
        source = RIGHT.read_text(encoding="utf-8")
        self.assertIn("overflow-x-hidden overflow-y-auto", source)
        self.assertIn("break-words [overflow-wrap:anywhere]", source)
        self.assertIn('isUser\n                        ? "max-w-[92%]', source)
        self.assertIn(': "w-full max-w-full rounded-tl-none"', source)

    def test_message_typography_is_readable_on_laptop_panel(self):
        source = RIGHT.read_text(encoding="utf-8")
        message = re.search(r'<p className="([^"]+)"[^>]*>\{msg\.text\}</p>', source)
        self.assertIsNotNone(message)
        classes = message.group(1)
        self.assertIn("text-[11px]", classes)
        self.assertIn("leading-[1.7]", classes)
        self.assertIn("whitespace-pre-wrap", classes)

    def test_input_has_visible_contrast_and_can_still_shrink(self):
        source = RIGHT.read_text(encoding="utf-8")
        self.assertIn("border-white/[0.10]", source)
        self.assertIn("bg-white/[0.045]", source)
        self.assertIn("placeholder-white/35", source)
        self.assertIn("min-w-0 flex-1", source)


class TestWidgetLauncherHoverNames(unittest.TestCase):
    def test_collapsed_rail_exposes_immediate_hover_and_keyboard_names(self):
        source = RAIL.read_text(encoding="utf-8")
        self.assertIn("hoveredLauncher", source)
        self.assertIn("onMouseEnter", source)
        self.assertIn("onFocus", source)
        self.assertIn('role="tooltip"', source)
        self.assertIn("hoveredLauncher.label", source)
        self.assertIn("!expanded && hoveredLauncher", source)

    def test_hover_name_does_not_replace_existing_accessible_labels(self):
        source = RAIL.read_text(encoding="utf-8")
        self.assertIn("aria-label={`Open ${config.title}`}", source)
        self.assertIn('aria-label="Open system widget"', source)
        self.assertIn("title={config.title}", source)


if __name__ == "__main__":
    unittest.main()
