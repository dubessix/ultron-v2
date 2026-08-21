"""Phase 7C regressions for header, rail, and centre controls polish."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "frontend" / "src" / "components"
APP = ROOT / "frontend" / "src" / "App.jsx"
SHELL = COMPONENTS / "AppShell.jsx"
RAIL = COMPONENTS / "WidgetRail.jsx"


class TestTruthfulProviderHeader(unittest.TestCase):
    def test_app_loads_reported_provider_configuration_from_backend(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn("const [providerStatus, setProviderStatus]", source)
        self.assertIn("api('/api/providers/status')", source)
        self.assertIn("backendStatus !== 'CONNECTED'", source)
        self.assertIn("setProviderStatus(null)", source)
        self.assertIn("providerStatus={providerStatus}", source)

    def test_header_derives_provider_label_without_claiming_live_reachability(self):
        source = SHELL.read_text(encoding="utf-8")
        self.assertIn("providerStatus", source)
        self.assertIn("item?.configured", source)
        self.assertIn("No AI Provider", source)
        self.assertIn("AI status unavailable", source)
        self.assertNotIn("AI READY", source)
        self.assertNotIn("Providers online", source)


class TestHeaderAndControlVectorPolish(unittest.TestCase):
    def test_top_identity_has_a_theme_coloured_vector_mark(self):
        source = SHELL.read_text(encoding="utf-8")
        self.assertRegex(source, r"import \{[^}]*Orbit[^}]*\} from 'lucide-react'")
        self.assertIn('aria-label={`${aiName} identity`}', source)
        self.assertIn("textShadow: `0 0 18px ${theme.glow}`", source)

    def test_bottom_controls_keep_real_actions_with_stronger_grouping(self):
        source = SHELL.read_text(encoding="utf-8")
        self.assertIn("shadow-[0_12px_35px_rgba(0,0,0,0.38)]", source)
        self.assertIn('aria-label={`Switch assistant from ${aiName}`}', source)
        self.assertIn('aria-label={codingMode ? "Disable coding mode" : "Enable coding mode"}', source)
        self.assertIn('aria-label={voice.isListening ? "Stop voice listening" : "Enable voice listening"}', source)
        self.assertIn("onClick={togglePersonality}", source)
        self.assertIn("onClick={toggleCodingMode}", source)
        self.assertIn("onClick={handleMicToggle}", source)


class TestRailFinish(unittest.TestCase):
    def test_registry_categories_drive_subtle_idle_icon_colours(self):
        source = RAIL.read_text(encoding="utf-8")
        self.assertIn("RAIL_CATEGORY_TONES", source)
        self.assertIn("config.category", source)
        for category in ("productivity", "system", "developer", "music", "research", "memory"):
            self.assertRegex(source, rf"\b{category}:\s*\"")
        self.assertIn("isVisible", source)
        self.assertIn("activeText", source)

    def test_bottom_rail_actions_have_fixed_separation_from_scrolling_launchers(self):
        source = RAIL.read_text(encoding="utf-8")
        self.assertIn("mt-3 flex shrink-0 flex-col gap-2", source)
        self.assertIn("Show widget names", source)
        self.assertIn("System widget", source)


if __name__ == "__main__":
    unittest.main()
