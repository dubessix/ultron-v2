"""Phase 1 UI-polish contracts: protect behavior before visual implementation."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
COMPONENTS = FRONTEND / "components"
WIDGETS = COMPONENTS / "widgets"

EXPECTED_WIDGET_IDS = {
    "todo",
    "calendar",
    "reminder",
    "code_optimizer",
    "semantic_code_graph",
    "coding",
    "music",
    "world_monitor",
    "github_search",
    "git_clone",
    "security_guardian",
    "daily_briefing",
    "git",
    "file_explorer",
    "universal_search",
    "deep_research",
    "weather",
    "market",
    "terminal",
    "memory",
    "notification",
    "system",
}

# Existing visible-symbol debt may only shrink during the icon phase. Any new
# file here would mean UI polish introduced another emoji/symbol dependency.
VISIBLE_SYMBOL_DEBT_FILES = {
    "components/AppShell.jsx",
    "components/NotificationToast.jsx",
    "components/RightPanel.jsx",
    "components/widgets/CalendarWidget.jsx",
    "components/widgets/CodeOptimizerWidget.jsx",
    "components/widgets/CodingWidget.jsx",
    "components/widgets/FileExplorerWidget.jsx",
    "components/widgets/ReminderWidget.jsx",
    "components/widgets/SecurityGuardianWidget.jsx",
    "components/widgets/SemanticCodeGraphWidget.jsx",
    "components/widgets/TerminalWidget.jsx",
    "components/widgets/TodoWidget.jsx",
}
EMOJI_OR_DECORATIVE_SYMBOL = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")


class TestApprovedWidgetBehaviorLock(unittest.TestCase):
    def test_all_22_widget_registry_entries_remain_dynamic(self):
        manager = (WIDGETS / "WidgetManager.js").read_text(encoding="utf-8")
        ids = set(re.findall(r"^\s{2}([a-z_]+):\s*\{", manager, re.MULTILINE))
        lazy_imports = re.findall(r"lazy\(\(\) => import\('./([^']+Widget)'\)\)", manager)
        self.assertEqual(ids, EXPECTED_WIDGET_IDS)
        self.assertEqual(len(lazy_imports), 22)
        self.assertEqual(len(lazy_imports), len(set(lazy_imports)))

    def test_widget_content_remains_centre_floating_overlay_not_left_panel(self):
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8")
        left = (COMPONENTS / "LeftPanel.jsx").read_text(encoding="utf-8")
        container = (WIDGETS / "WidgetContainer.jsx").read_text(encoding="utf-8")

        self.assertIn("<LeftPanel systemMetrics={systemMetrics} backendStatus={backendStatus} />", shell)
        self.assertNotIn("widgetState", left)
        self.assertNotIn("toggleWidget", left)
        self.assertNotIn("WidgetContainer", left)
        self.assertIn("DYNAMIC FLOATING OVERLAYS", shell)
        self.assertGreater(shell.index("<WidgetContainer"), shell.index("<RightPanel"))
        self.assertIn("onClose={() => toggleWidget(key)}", shell)
        self.assertIn("translate3d", container)
        self.assertIn("useDraggable", container)

    def test_widget_launchers_toggle_existing_registry_ids_without_hardcoded_components(self):
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8")
        rail = (COMPONENTS / "WidgetRail.jsx").read_text(encoding="utf-8")
        self.assertIn("Object.entries(WIDGET_REGISTRY).map", rail)
        self.assertIn("onClick={() => toggleWidget(widgetId)}", rail)
        self.assertIn("import WidgetRail", shell)
        self.assertNotIn("import TodoWidget", shell)
        self.assertNotIn("import CalendarWidget", shell)
        self.assertNotIn("import TodoWidget", rail)
        self.assertNotIn("import CalendarWidget", rail)


class TestApprovedPersonalityThemeLock(unittest.TestCase):
    def test_top_identity_and_centre_core_are_personality_driven(self):
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8")
        core = (COMPONENTS / "BlobCanvas.jsx").read_text(encoding="utf-8")
        self.assertIn('const isZora = activePersonality === "zora"', shell)
        self.assertIn("getPersonalityTheme(activePersonality)", shell)
        self.assertIn("const aiName = theme.name", shell)
        self.assertIn("theme.primary", shell)
        self.assertIn("personality={activePersonality}", shell)
        self.assertIn("getPersonalityTheme(personality)", core)
        self.assertIn("theme.coreParticle", core)
        self.assertIn("theme.coreOrbit", core)
        self.assertRegex(core, r"\[aiState, personality, amplitude(?:, isFullHdViewport)?\]")

    def test_frontend_claims_personality_only_after_backend_persistence(self):
        app = (FRONTEND / "App.jsx").read_text(encoding="utf-8")
        request = app.index("await api('/api/personality'")
        persisted_change = app.index("setActivePersonality(result.personality)")
        self.assertLess(request, persisted_change)
        between = app[request:persisted_change]
        self.assertNotIn("setActivePersonality(nextPers)", between)
        self.assertIn("Personality unchanged", app)


class TestApprovedScopeExclusions(unittest.TestCase):
    def test_no_camera_vision_or_edge_browser_feature_is_added(self):
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8").lower()
        left = (COMPONENTS / "LeftPanel.jsx").read_text(encoding="utf-8").lower()
        combined = shell + "\n" + left
        for forbidden in (
            "vision feed",
            "camera feed",
            "edge-style",
            "edge browser",
            "url bar",
        ):
            self.assertNotIn(forbidden, combined)

    def test_visible_emoji_debt_is_bounded_and_cannot_spread_to_new_files(self):
        debt_files: set[str] = set()
        occurrence_count = 0
        for path in FRONTEND.rglob("*"):
            if not path.is_file() or path.suffix not in {".js", ".jsx", ".css", ".html"}:
                continue
            relative = path.relative_to(FRONTEND).as_posix()
            matches = EMOJI_OR_DECORATIVE_SYMBOL.findall(path.read_text(encoding="utf-8"))
            if matches:
                debt_files.add(relative)
                occurrence_count += len(matches)
        self.assertTrue(debt_files.issubset(VISIBLE_SYMBOL_DEBT_FILES), debt_files - VISIBLE_SYMBOL_DEBT_FILES)
        # Baseline: 17 source lines, 18 characters because File Explorer has
        # separate folder and file glyphs on one line. The count may only fall.
        self.assertLessEqual(occurrence_count, 18)


if __name__ == "__main__":
    unittest.main()
