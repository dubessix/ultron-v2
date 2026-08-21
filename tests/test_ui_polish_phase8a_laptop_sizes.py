"""Phase 8A regressions found during real laptop-size browser acceptance."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "frontend" / "src" / "components"
LEFT = COMPONENTS / "LeftPanel.jsx"
SHELL = COMPONENTS / "AppShell.jsx"
CORE = COMPONENTS / "BlobCanvas.jsx"
RIGHT = COMPONENTS / "RightPanel.jsx"
RAIL = COMPONENTS / "WidgetRail.jsx"


class TestShortLaptopLeftPanel(unittest.TestCase):
    def test_short_laptop_height_compacts_cards_without_page_overflow(self):
        source = LEFT.read_text(encoding="utf-8")
        self.assertIn("overflow-y-auto", source)
        self.assertGreaterEqual(source.count("[@media(max-height:800px)]:"), 8)
        self.assertIn("[@media(max-height:800px)]:min-h-20", source)
        self.assertIn("[@media(max-height:800px)]:space-y-2", source)

    def test_detail_unavailable_value_cannot_break_across_lines(self):
        source = LEFT.read_text(encoding="utf-8")
        detail = re.search(r"function DetailMetricCard[\s\S]+?\n}\n\nfunction numberOrNull", source)
        self.assertIsNotNone(detail)
        block = detail.group(0)
        self.assertIn("isUnavailable", block)
        self.assertIn("whitespace-nowrap", block)
        self.assertIn("text-[16px]", block)
        self.assertNotIn("break-words", block)

    def test_core_and_three_panels_remain_bounded(self):
        shell = SHELL.read_text(encoding="utf-8")
        self.assertIn("h-screen w-screen", shell)
        self.assertIn("grid-cols-12", shell)
        self.assertIn("overflow-hidden", shell)
        self.assertIn("min-h-0", shell)


class TestFullHdPresentation(unittest.TestCase):
    def test_particle_core_uses_a_larger_full_hd_geometry_only(self):
        source = CORE.read_text(encoding="utf-8")
        self.assertIn("isFullHdViewport", source)
        self.assertIn("window.innerWidth >= 1700", source)
        self.assertIn("window.innerHeight >= 900", source)
        self.assertIn("isFullHdViewport ? 640 : 520", source)
        self.assertIn("isFullHdViewport ? 1.2 : 1", source)

    def test_full_hd_header_panels_and_controls_receive_larger_presentation_classes(self):
        shell = SHELL.read_text(encoding="utf-8")
        left = LEFT.read_text(encoding="utf-8")
        right = RIGHT.read_text(encoding="utf-8")
        rail = RAIL.read_text(encoding="utf-8")
        self.assertGreaterEqual(shell.count("2xl:"), 12)
        self.assertGreaterEqual(left.count("2xl:"), 12)
        self.assertGreaterEqual(right.count("2xl:"), 8)
        self.assertGreaterEqual(rail.count("2xl:"), 4)


if __name__ == "__main__":
    unittest.main()
