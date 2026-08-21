"""Phase 7 static regressions for laptop-width layout containment."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "frontend" / "src" / "components"


class TestLaptopLayoutContainment(unittest.TestCase):
    def test_shell_and_three_panel_grid_are_strictly_contained(self):
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8")
        self.assertIn("h-screen w-screen", shell)
        self.assertIn("overflow-hidden", shell)
        self.assertIn("min-w-0 flex-1", shell)
        self.assertIn("min-h-0", shell)
        self.assertIn("grid-cols-12", shell)
        self.assertIn("lg:col-span-6", shell)
        self.assertIn("lg:col-span-3", (COMPONENTS / "LeftPanel.jsx").read_text(encoding="utf-8"))
        self.assertIn("lg:col-span-3", (COMPONENTS / "RightPanel.jsx").read_text(encoding="utf-8"))

    def test_expanded_widget_labels_overlay_without_squeezing_three_panels(self):
        rail = (COMPONENTS / "WidgetRail.jsx").read_text(encoding="utf-8")
        self.assertIn('className="relative z-[1200] h-screen w-14 shrink-0', rail)
        self.assertIn("absolute inset-y-0 left-0", rail)
        self.assertIn('expanded ? "w-52" : "w-14"', rail)
        self.assertIn("overflow-y-auto", rail)

    def test_left_right_and_core_have_independent_overflow_boundaries(self):
        left = (COMPONENTS / "LeftPanel.jsx").read_text(encoding="utf-8")
        right = (COMPONENTS / "RightPanel.jsx").read_text(encoding="utf-8")
        core = (COMPONENTS / "BlobCanvas.jsx").read_text(encoding="utf-8")
        self.assertIn("min-w-0", left)
        self.assertIn("overflow-y-auto", left)
        self.assertIn("min-w-0", right)
        self.assertIn("overflow-hidden", right)
        self.assertIn("min-w-0", right)
        self.assertIn("max-w-full", core)

    def test_chat_input_can_shrink_without_horizontal_clipping(self):
        right = (COMPONENTS / "RightPanel.jsx").read_text(encoding="utf-8")
        self.assertIn("min-w-0", right)
        self.assertIn("flex-1", right)
        self.assertIn("truncate", right)


if __name__ == "__main__":
    unittest.main()
