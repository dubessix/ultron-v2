"""Exhaustive frontend widget-to-backend connection contracts."""

from __future__ import annotations

import asyncio
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from backend.app.tools.tool_registry import ToolRegistry
from backend.app.tools.world_monitor_tool import WorldMonitorTool


ROOT = Path(__file__).resolve().parent.parent
WIDGET_DIR = ROOT / "frontend" / "src" / "components" / "widgets"

EXPECTED_WIDGETS = {
    "todo", "calendar", "reminder", "code_optimizer", "semantic_code_graph",
    "coding", "music", "world_monitor", "github_search", "git_clone",
    "security_guardian", "daily_briefing", "git", "file_explorer",
    "universal_search", "deep_research", "weather", "market", "terminal",
    "memory", "notification", "system",
}

EXPECTED_TOOL_LINKS = {
    "TodoWidget.jsx": {"manage_task"},
    "CalendarWidget.jsx": {"manage_calendar"},
    "ReminderWidget.jsx": {"manage_reminder"},
    "CodeOptimizerWidget.jsx": {"optimize_code"},
    "SemanticCodeGraphWidget.jsx": {"semantic_code_graph"},
    "MusicWidget.jsx": {"play_music", "pause_music", "resume_music", "stop_music", "next_track", "previous_track", "set_volume"},
    "WorldMonitorWidget.jsx": {"world_monitor"},
    "GithubSearchWidget.jsx": {"github_search"},
    "GitCloneWidget.jsx": {"git_clone", "open_vscode"},
    "SecurityGuardianWidget.jsx": {"security_scan"},
    "DailyBriefingWidget.jsx": {"daily_briefing"},
    "GitWidget.jsx": {"git_status"},
    "FileExplorerWidget.jsx": {"list_contents"},
    "UniversalSearchWidget.jsx": {"universal_search"},
    "DeepResearchWidget.jsx": {"tavily_research", "manage_memory"},
    "WeatherWidget.jsx": {"weather_tool"},
    "MarketWidget.jsx": {"world_monitor"},
    "TerminalWidget.jsx": {"terminal_run"},
    "NotificationWidget.jsx": {"manage_reminder"},
    "SystemWidget.jsx": {"system_metrics"},
}


class TestWidgetRegistryCompleteness(unittest.TestCase):
    def test_every_registered_lazy_widget_file_exists_once(self):
        manager = (WIDGET_DIR / "WidgetManager.js").read_text(encoding="utf-8")
        ids = set(re.findall(r"^\s{2}([a-z_]+):\s*\{", manager, re.MULTILINE))
        imports = re.findall(r"import\('./([^']+Widget)'\)", manager)
        self.assertEqual(ids, EXPECTED_WIDGETS)
        self.assertEqual(len(imports), len(EXPECTED_WIDGETS))
        self.assertEqual(len(imports), len(set(imports)))
        for component in imports:
            self.assertTrue((WIDGET_DIR / f"{component}.jsx").is_file(), component)

    def test_widget_tool_ids_exist_in_backend_registry(self):
        backend_ids = set(ToolRegistry().get_registered_ids())
        for filename, expected_tools in EXPECTED_TOOL_LINKS.items():
            source = (WIDGET_DIR / filename).read_text(encoding="utf-8")
            for tool_id in expected_tools:
                self.assertIn(tool_id, source, f"{filename} missing {tool_id}")
                self.assertIn(tool_id, backend_ids, f"backend missing {tool_id}")

    def test_non_tool_widgets_have_real_inputs(self):
        coding = (WIDGET_DIR / "CodingWidget.jsx").read_text(encoding="utf-8")
        memory = (WIDGET_DIR / "MemoryWidget.jsx").read_text(encoding="utf-8")
        self.assertIn("log = []", coding)
        self.assertIn("/api/memory/recent", memory)
        self.assertNotIn("Offline Fallback", coding + memory)


class TestWorldMarketWidgetSchema(unittest.TestCase):
    def test_missing_market_change_stays_unavailable_not_zero(self):
        response = Mock(status_code=200)
        response.json.return_value = {"bitcoin": {"usd": 123.45}}
        with patch(
            "backend.app.tools.world_monitor_tool.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            result = asyncio.run(WorldMonitorTool().execute(endpoint="list_market_quotes"))
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["quotes"][0]["price_usd"], 123.45)
        self.assertIsNone(result["data"]["quotes"][0]["change_24h"])

    def test_missing_fear_greed_score_is_failure(self):
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{}]}
        with patch(
            "backend.app.tools.world_monitor_tool.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            result = asyncio.run(WorldMonitorTool().execute(endpoint="get_fear_greed_index"))
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["status"], "unavailable")


class TestFrontendBackendConnectionSafety(unittest.TestCase):
    def test_live_activity_text_is_driven_by_backend_events(self):
        app = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        shell = (ROOT / "frontend" / "src" / "components" / "AppShell.jsx").read_text(encoding="utf-8")
        self.assertIn("activityText", app)
        self.assertIn("msg.detail", app)
        self.assertIn("Ultron is streaming the response", app)
        self.assertIn("activityText", shell)
        self.assertIn("Claude-Code-style honest live activity text", shell)

    def test_chat_has_no_replay_after_websocket_send(self):
        source = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        self.assertIn("openedAndSent", source)
        self.assertIn("ws.onclose", source)
        self.assertIn("!openedAndSent", source)
        self.assertIn("was not replayed", source)
        self.assertIn("wsResult.canFallback", source)
        self.assertIn("api('/api/chat'", source)

    def test_mutating_widgets_surface_backend_errors(self):
        for filename in ("TodoWidget.jsx", "CalendarWidget.jsx", "SemanticCodeGraphWidget.jsx"):
            source = (WIDGET_DIR / filename).read_text(encoding="utf-8")
            self.assertIn("setError", source, filename)
            self.assertIn("data.error", source, filename)

    def test_market_uses_backend_not_direct_browser_api(self):
        source = (WIDGET_DIR / "MarketWidget.jsx").read_text(encoding="utf-8")
        self.assertIn("executeTool('world_monitor'", source)
        self.assertNotIn("api.coingecko.com", source)

    def test_git_clone_passes_cloned_path_to_vscode(self):
        source = (WIDGET_DIR / "GitCloneWidget.jsx").read_text(encoding="utf-8")
        self.assertIn('run("open_vscode", { path: requestedPath })', source)
        self.assertIn("requested_path", source)


if __name__ == "__main__":
    unittest.main()
