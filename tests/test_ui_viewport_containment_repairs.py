"""Regressions for short-window Codespaces and laptop containment."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
COMPONENTS = SRC / "components"


class TestInvisibleContainedScrolling(unittest.TestCase):
    def test_all_scroll_regions_hide_native_scrollbar_chrome(self):
        css = (SRC / "index.css").read_text(encoding="utf-8")
        self.assertIn(".no-visible-scrollbar", css)
        self.assertIn(".scrollbar-thin", css)
        self.assertIn(".custom-scrollbar", css)
        self.assertIn("scrollbar-width: none", css)
        self.assertIn("::-webkit-scrollbar", css)
        self.assertIn("display: none", css)

    def test_main_panels_explicitly_block_horizontal_overflow(self):
        left = (COMPONENTS / "LeftPanel.jsx").read_text(encoding="utf-8")
        right = (COMPONENTS / "RightPanel.jsx").read_text(encoding="utf-8")
        container = (COMPONENTS / "widgets" / "WidgetContainer.jsx").read_text(encoding="utf-8")
        self.assertIn("overflow-x-hidden", left)
        self.assertIn("no-visible-scrollbar", left)
        self.assertIn("no-visible-scrollbar", right)
        self.assertIn("overflow-x-hidden", container)
        self.assertIn("no-visible-scrollbar", container)


class TestShortLaptopComposition(unittest.TestCase):
    def test_short_height_has_explicit_compact_dashboard_rules(self):
        css = (SRC / "index.css").read_text(encoding="utf-8")
        self.assertIn("@media (min-width: 768px) and (max-height: 650px)", css)
        for name in (
            ".ultron-workspace",
            ".ultron-left-panel",
            ".ultron-overview-panel",
            ".ultron-network-panel",
            ".ultron-detail-card",
            ".ultron-core-panel",
            ".ultron-core-controls",
            ".ultron-right-panel",
        ):
            self.assertIn(name, css)

    def test_desktop_panels_stay_three_column_from_768_pixels(self):
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8")
        left = (COMPONENTS / "LeftPanel.jsx").read_text(encoding="utf-8")
        right = (COMPONENTS / "RightPanel.jsx").read_text(encoding="utf-8")
        self.assertIn("md:col-span-6", shell)
        self.assertIn("md:col-span-3", left)
        self.assertIn("md:col-span-3", right)

    def test_core_canvas_uses_available_width_and_height_without_clipping(self):
        core = (COMPONENTS / "BlobCanvas.jsx").read_text(encoding="utf-8")
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8")
        self.assertIn("--core-size", core)
        self.assertIn("ultron-core-canvas", core)
        self.assertIn("ultron-core-stage", shell)
        self.assertIn("min-h-0", shell)


class TestFloatingWidgetBounds(unittest.TestCase):
    def test_initial_and_dragged_widget_positions_are_clamped(self):
        hook = (SRC / "hooks" / "useDraggable.js").read_text(encoding="utf-8")
        self.assertIn("itemWidth", hook)
        self.assertIn("itemHeight", hook)
        self.assertIn("maxX", hook)
        self.assertIn("maxY", hook)
        self.assertIn("Math.min", hook)
        self.assertIn("Math.max", hook)

    def test_widget_size_never_exceeds_workspace(self):
        container = (COMPONENTS / "widgets" / "WidgetContainer.jsx").read_text(encoding="utf-8")
        self.assertIn("calc(100% - 16px)", container)
        self.assertIn("initialWidth", container)
        self.assertIn("initialHeight", container)


class TestCodespacesWindow(unittest.TestCase):
    def test_codespaces_chrome_requests_a_maximized_window(self):
        script = (ROOT / ".devcontainer" / "codespaces_launch_setup.sh").read_text(encoding="utf-8")
        self.assertIn("--start-maximized", script)


if __name__ == "__main__":
    unittest.main()
