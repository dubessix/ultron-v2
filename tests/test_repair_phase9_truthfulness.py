"""Phase 9 regressions: no fabricated telemetry/content or overclaimed success."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from backend.app.database.db import get_db_connection
from backend.app.router import (
    PersonalityRequest,
    SpeakRequest,
    set_session_personality,
    speak_text,
)
from backend.app.runtime_paths import isolated_test_artifact_path
from backend.app.tools.daily_briefing_tool import DailyBriefingTool
from backend.app.tools.git_tool import GitStatusTool
from backend.app.tools.reminder_tool import ReminderTool
from backend.app.tools.security_guardian_tool import SecurityGuardianTool
from backend.app.tools.system_metrics_tool import SystemMetricsTool, collect_system_metrics
from backend.app.tools.tool_registry import ToolRegistry
from backend.app.tools.universal_search_tool import UniversalSearchTool
from backend.app.tools.weather_tool import WeatherTool
from backend.app.voice.edge_tts_provider import EdgeTTSProvider


ROOT = Path(__file__).resolve().parent.parent


class TestNoFabricatedFrontendContent(unittest.TestCase):
    def test_known_fake_dashboard_and_widget_literals_are_absent(self):
        paths = [
            ROOT / "frontend/src/components/LeftPanel.jsx",
            ROOT / "frontend/src/components/RightPanel.jsx",
            ROOT / "frontend/src/components/widgets/SystemWidget.jsx",
            ROOT / "frontend/src/components/widgets/WeatherWidget.jsx",
            ROOT / "frontend/src/components/widgets/GitWidget.jsx",
            ROOT / "frontend/src/components/widgets/DeepResearchWidget.jsx",
            ROOT / "frontend/src/components/widgets/UniversalSearchWidget.jsx",
            ROOT / "frontend/src/components/widgets/NotificationWidget.jsx",
            ROOT / "frontend/src/components/widgets/SecurityGuardianWidget.jsx",
            ROOT / "frontend/src/components/widgets/TodoWidget.jsx",
            ROOT / "frontend/src/components/widgets/CalendarWidget.jsx",
        ]
        source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        forbidden = [
            "55°C",
            "37.2% (Fallback)",
            "94% (Charging)",
            "Latency: 31ms",
            "Kolkata, IN (Offline Fallback)",
            "main (Offline Fallback)",
            "AI Agents are progressing",
            "D:\\\\SaaS-Builds\\\\package.json",
            "Pruned 42 rows",
            "No vulnerabilities detected",
            "TrustQuiz",
            "Web Development Session",
            "// fast",
        ]
        for literal in forbidden:
            self.assertNotIn(literal, source, literal)

    def test_backend_fake_briefing_and_metrics_literals_are_absent(self):
        paths = [
            ROOT / "backend/app/tools/system_metrics_tool.py",
            ROOT / "backend/app/tools/daily_briefing_tool.py",
            ROOT / "backend/app/tools/security_guardian_tool.py",
        ]
        source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for literal in (
            "or 37.2",
            '"94% (Charging)"',
            '"Latency: 31ms // Status: Stable"',
            '"temperature": "29.0°C"',
            "Llama 3.1 405B has established",
            "Gemini 1.5 Flash has received",
            "Codebase is completely clean",
            "Safe to proceed",
        ):
            self.assertNotIn(literal, source, literal)


class TestTruthfulSystemMetrics(unittest.TestCase):
    def test_zero_cpu_and_unavailable_optional_sensors_are_not_replaced(self):
        vm = Mock(percent=41.5)
        disk = Mock(used=10 * 1024**3, total=100 * 1024**3, percent=10.0)
        net = Mock(bytes_sent=1234, bytes_recv=5678)
        process = Mock()
        process.memory_info.return_value = Mock(rss=50 * 1024**2)
        with patch("backend.app.tools.system_metrics_tool.psutil.Process", return_value=process), patch(
            "backend.app.tools.system_metrics_tool.psutil.cpu_percent", return_value=0.0
        ), patch("backend.app.tools.system_metrics_tool.psutil.virtual_memory", return_value=vm), patch(
            "backend.app.tools.system_metrics_tool.psutil.disk_usage", return_value=disk
        ), patch("backend.app.tools.system_metrics_tool.psutil.sensors_battery", return_value=None), patch(
            "backend.app.tools.system_metrics_tool.psutil.sensors_temperatures", return_value={}, create=True
        ), patch("backend.app.tools.system_metrics_tool.psutil.net_io_counters", return_value=net), patch(
            "backend.app.tools.system_metrics_tool.psutil.net_if_stats", return_value={}
        ), patch("backend.app.tools.system_metrics_tool.psutil.boot_time", return_value=100.0), patch(
            "backend.app.tools.system_metrics_tool.time.time", return_value=160.0
        ):
            data = collect_system_metrics()
        self.assertEqual(data["cpu_percent"], 0.0)
        self.assertFalse(data["battery"]["available"])
        self.assertIsNone(data["temperature_c"])
        self.assertEqual(data["uptime_seconds"], 60.0)
        self.assertNotIn("31ms", data["network_display"])

    def test_metrics_tool_returns_structured_real_data(self):
        result = asyncio.run(SystemMetricsTool().execute())
        self.assertTrue(result["success"], result)
        self.assertIn("cpu_percent", result["data"])
        self.assertIn("disk_percent", result["data"])
        self.assertIn("battery", result["data"])


class TestTruthfulWeatherAndBriefing(unittest.TestCase):
    def test_daily_weather_failure_is_explicitly_unavailable(self):
        with patch("backend.app.tools.daily_briefing_tool.httpx.AsyncClient.get", new=AsyncMock(side_effect=OSError("offline"))):
            weather = asyncio.run(DailyBriefingTool()._get_local_weather())
        self.assertFalse(weather["available"])
        self.assertIsNone(weather["temperature"])

    def test_weather_missing_live_temperature_is_failure_not_default_value(self):
        response = Mock(status_code=200)
        response.json.return_value = {"current_weather": {}, "daily": {}}
        with patch("backend.app.tools.weather_tool.httpx.AsyncClient.get", new=AsyncMock(return_value=response)):
            result = asyncio.run(WeatherTool().execute(latitude=22.57, longitude=88.36))
        self.assertFalse(result["success"])
        self.assertNotIn("28.0°C", str(result))

    def test_briefing_marks_live_sources_unavailable_without_substitution(self):
        tool = DailyBriefingTool()
        unavailable_weather = {
            "available": False, "temperature": None, "windspeed": None,
            "source": "Open-Meteo", "error": "offline",
        }
        unavailable_news = {
            "available": False, "items": [], "source": "public web search", "error": "offline",
        }
        with patch.object(tool, "_get_local_weather", new=AsyncMock(return_value=unavailable_weather)), patch.object(
            tool, "_get_live_news", new=AsyncMock(return_value=unavailable_news)
        ):
            result = asyncio.run(tool.execute(include_tasks=False, include_schedule=False))
        text = result["data"]["briefing_text"]
        self.assertIn("no estimate was substituted", text)
        self.assertIn("no headlines were substituted", text)
        self.assertNotIn("Smooth conditions", text)


class TestTruthfulGitStatus(unittest.TestCase):
    def test_non_repository_does_not_claim_main_branch(self):
        directory = isolated_test_artifact_path("phase9_not_git")
        directory.mkdir(parents=True, exist_ok=True)
        result = asyncio.run(GitStatusTool().execute(directory=str(directory)))
        self.assertFalse(result["success"])
        self.assertIn("Not a Git working tree", result["error"])
        self.assertNotIn('"branch": "main"', str(result))


class TestNoInventedReminderTime(unittest.TestCase):
    def test_invalid_time_does_not_silently_schedule_five_minutes_later(self):
        result = asyncio.run(
            ReminderTool().execute(
                action="create",
                title="invalid-time-test",
                target_time="sometime-ish",
            )
        )
        self.assertFalse(result["success"])
        self.assertIn("Invalid target_time", result["error"])


class TestRealUniversalSearchAndPersonality(unittest.TestCase):
    def test_universal_search_returns_real_approved_filename(self):
        self.assertIsInstance(ToolRegistry().get_tool("universal_search"), UniversalSearchTool)
        marker = f"phase9-real-{uuid.uuid4().hex}.txt"
        path = isolated_test_artifact_path("phase9_search", marker)
        path.write_text("real file", encoding="utf-8")
        result = asyncio.run(
            UniversalSearchTool().execute(query=marker[:18], project_id="personal", limit=20)
        )
        self.assertTrue(result["success"], result)
        files = [item for item in result["data"]["results"] if item["category"] == "File"]
        self.assertTrue(any(item["name"] == marker for item in files), result)

    def test_personality_selection_is_persisted_before_ui_claims_it(self):
        session_id = f"phase9-personality-{uuid.uuid4()}"
        result = asyncio.run(
            set_session_personality(PersonalityRequest(session_id=session_id, personality="zora"))
        )
        self.assertTrue(result["success"])
        with get_db_connection() as conn:
            stored = conn.execute(
                "SELECT personality FROM sessions WHERE id = ?;", (session_id,)
            ).fetchone()[0]
        self.assertEqual(stored, "zora")


class TestTruthfulVoiceFailure(unittest.TestCase):
    def test_provider_failure_never_yields_mock_audio(self):
        class FailedCommunicate:
            async def stream(self):
                raise OSError("network down")
                yield  # pragma: no cover

        fake_module = types.SimpleNamespace(
            Communicate=lambda **_kwargs: FailedCommunicate()
        )

        async def collect():
            chunks = []
            async for chunk in EdgeTTSProvider().generate_speech(
                "hello", "en-US-GuyNeural"
            ):
                chunks.append(chunk)
            return chunks

        with patch.dict(sys.modules, {"edge_tts": fake_module}):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                asyncio.run(collect())

    def test_speak_endpoint_returns_503_before_false_success_response(self):
        class FailedVoice:
            async def speak(self, *_args, **_kwargs):
                raise RuntimeError("provider offline")
                yield  # pragma: no cover

        with patch("backend.app.voice.voice_system.VoiceSystem", return_value=FailedVoice()):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(speak_text(SpeakRequest(text="hello", personality="ultron")))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("unavailable", raised.exception.detail.lower())


class TestTruthfulSecurityVerdict(unittest.TestCase):
    def test_zero_findings_does_not_claim_complete_safety(self):
        tool = SecurityGuardianTool()
        with patch.object(tool, "_scan_secrets", return_value=[]), patch.object(
            tool, "_scan_processes", return_value=[]
        ), patch.object(tool, "_scan_dependencies", return_value=[]):
            result = asyncio.run(tool.execute())
        self.assertTrue(result["success"])
        message = result["data"]["message"].lower()
        self.assertIn("no findings", message)
        self.assertIn("not", message)
        self.assertNotIn("completely clean", message)
        self.assertFalse(result["data"]["verified_clean"])

    def test_failed_check_is_reported_not_counted_as_clean(self):
        tool = SecurityGuardianTool()
        with patch.object(tool, "_scan_secrets", side_effect=OSError("denied")), patch.object(
            tool, "_scan_processes", return_value=[]
        ), patch.object(tool, "_scan_dependencies", return_value=[]):
            result = asyncio.run(tool.execute())
        self.assertTrue(result["success"])
        self.assertEqual(
            result["data"]["check_status"]["workspace_secret_patterns"]["status"],
            "failed",
        )
        self.assertIn("incomplete", result["data"]["message"].lower())
        self.assertFalse(result["data"]["verified_clean"])


if __name__ == "__main__":
    unittest.main()
