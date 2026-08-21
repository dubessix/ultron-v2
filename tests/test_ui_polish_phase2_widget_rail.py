"""Phase 2 regressions for the approved far-left dynamic Widget icon rail."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "frontend" / "src" / "components"
WIDGETS = COMPONENTS / "widgets"
EXPECTED_WIDGET_IDS = {
    "todo", "calendar", "reminder", "code_optimizer", "semantic_code_graph",
    "coding", "music", "world_monitor", "github_search", "git_clone",
    "security_guardian", "daily_briefing", "git", "file_explorer",
    "universal_search", "deep_research", "weather", "market", "terminal",
    "memory", "notification", "system",
}


class TestFarLeftWidgetRail(unittest.TestCase):
    def test_widget_rail_is_dynamic_accessible_and_personality_aware(self):
        rail = (COMPONENTS / "WidgetRail.jsx").read_text(encoding="utf-8")
        self.assertIn("Object.entries(WIDGET_REGISTRY)", rail)
        self.assertIn("config.icon", rail)
        self.assertIn("toggleWidget(widgetId)", rail)
        self.assertIn("aria-label", rail)
        self.assertIn("title={config.title}", rail)
        self.assertIn('activePersonality === "zora"', rail)
        self.assertIn("text-pink-400", rail)
        self.assertIn("text-emerald-400", rail)
        self.assertNotIn("WidgetContainer", rail)
        self.assertNotRegex(rail, r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")

    def test_registry_provides_one_vector_icon_for_every_widget(self):
        manager = (WIDGETS / "WidgetManager.js").read_text(encoding="utf-8")
        ids = set(re.findall(r"^\s{2}([a-z_]+):\s*\{", manager, re.MULTILINE))
        icon_lines = re.findall(r"^\s{4}icon:\s*([A-Za-z0-9_]+),", manager, re.MULTILINE)
        self.assertEqual(ids, EXPECTED_WIDGET_IDS)
        self.assertEqual(len(icon_lines), len(EXPECTED_WIDGET_IDS))
        self.assertEqual(len(icon_lines), len(set(icon_lines)))
        self.assertIn("from 'lucide-react'", manager)

    def test_app_shell_places_rail_before_three_panel_content_and_removes_text_hotbuttons(self):
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8")
        self.assertIn("import WidgetRail from './WidgetRail'", shell)
        self.assertIn("<WidgetRail", shell)
        self.assertLess(shell.index("<WidgetRail"), shell.index("<LeftPanel"))
        self.assertNotIn("Quick-toggle widget hot-buttons", shell)
        self.assertNotIn("{config.id}", shell)
        self.assertIn("DYNAMIC FLOATING OVERLAYS", shell)
        self.assertGreater(shell.index("<WidgetContainer"), shell.index("<RightPanel"))

    def test_rail_bottom_controls_have_real_behaviour_not_dead_buttons(self):
        rail = (COMPONENTS / "WidgetRail.jsx").read_text(encoding="utf-8")
        self.assertIn("setExpanded", rail)
        self.assertIn("toggleWidget('system')", rail)
        self.assertIn("Expand widget labels", rail)
        self.assertIn("Open system widget", rail)


if __name__ == "__main__":
    unittest.main()
