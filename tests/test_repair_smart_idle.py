"""Post-release safe idle regressions: first-open briefing and hidden-tab throttling."""

from __future__ import annotations

import asyncio
import datetime
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.app.database.db import get_db_connection
from backend.app.main import run_reminder_scheduler
from backend.app.tools.daily_briefing_tool import DailyBriefingTool, _greeting_for_hour
from backend.app.tools.tool_registry import ToolRegistry


ROOT = Path(__file__).resolve().parent.parent


class TestAnyTimeFirstOpenBriefing(unittest.TestCase):
    def test_greeting_matches_local_open_hour(self):
        self.assertEqual(_greeting_for_hour(9)[0], "morning")
        self.assertEqual(_greeting_for_hour(14)[0], "afternoon")
        self.assertEqual(_greeting_for_hour(19)[0], "evening")
        self.assertEqual(_greeting_for_hour(22)[0], "night")
        self.assertNotIn("morning", _greeting_for_hour(22)[1].lower())

    def test_late_first_open_briefing_is_not_morning(self):
        class LateDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 15, 22, 0, tzinfo=tz)

        tool = DailyBriefingTool()
        unavailable_weather = {"available": False, "source": "Open-Meteo", "error": "offline"}
        unavailable_news = {"available": False, "source": "public web search", "items": []}
        with patch(
            "backend.app.tools.daily_briefing_tool.datetime.datetime",
            LateDateTime,
        ), patch.object(
            tool,
            "_get_local_weather",
            new=AsyncMock(return_value=unavailable_weather),
        ), patch.object(
            tool,
            "_get_live_news",
            new=AsyncMock(return_value=unavailable_news),
        ):
            result = asyncio.run(
                tool.execute(include_tasks=False, include_schedule=False)
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["greeting_period"], "night")
        self.assertIn("late-hour briefing", result["data"]["briefing_text"])
        self.assertNotIn("Good morning", result["data"]["briefing_text"])

    def test_fixed_eight_am_background_loop_is_removed(self):
        source = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("run_proactive_intelligence_loop", source)
        self.assertNotIn('"proactive_intelligence"', source)
        self.assertNotIn("now.hour == 8", source)
        # Essential time-sensitive/durability services stay intact.
        self.assertIn('"reminder_scheduler"', source)
        self.assertIn('"emergency_monitor"', source)
        self.assertIn('"durability_scheduler"', source)


class TestReminderTiming(unittest.IsolatedAsyncioTestCase):
    async def test_future_due_reminder_triggers_within_poll_window(self):
        reminder_id = f"timing-{uuid.uuid4()}"
        target = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=0.2)
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO reminders_alarms
                (id, type, title, target_time, recurrence, status)
                VALUES (?, 'reminder', 'timing check', ?, 'one_time', 'pending');
                """,
                (reminder_id, target.isoformat()),
            )
            conn.commit()

        class CaptureManager:
            def __init__(self):
                self.event = asyncio.Event()
                self.payload = None

            async def broadcast(self, channel, payload):
                if channel == "events" and payload.get("reminder", {}).get("id") == reminder_id:
                    self.payload = payload
                    self.event.set()

        capture = CaptureManager()
        started = time.monotonic()
        with patch("backend.app.main.ws_manager", capture):
            task = asyncio.create_task(run_reminder_scheduler())
            try:
                await asyncio.wait_for(capture.event.wait(), timeout=6.5)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        elapsed = time.monotonic() - started
        self.assertLessEqual(elapsed, 6.0)
        self.assertEqual(capture.payload["type"], "reminder_triggered")
        with get_db_connection() as conn:
            status = conn.execute(
                "SELECT status FROM reminders_alarms WHERE id = ?;", (reminder_id,)
            ).fetchone()[0]
        self.assertEqual(status, "triggered")


class TestFrontendSmartIdleContract(unittest.TestCase):
    def test_first_connected_open_runs_at_most_once_per_local_day(self):
        source = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        self.assertIn("ultron_daily_briefing_date", source)
        self.assertIn("briefingAttemptedRef", source)
        self.assertIn("executeTool('daily_briefing'", source)
        self.assertIn("Daily briefing ready", source)
        self.assertIn("speakResponse(text", source)

    def test_hidden_tab_health_poll_is_throttled_and_return_refreshes(self):
        source = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        self.assertIn("document.hidden ? 30000 : 5000", source)
        self.assertIn("visibilitychange", source)
        self.assertIn("else checkHealth()", source)
        self.assertNotIn("setInterval(checkHealth", source)

    def test_tool_registry_feature_set_remains_available(self):
        ids = set(ToolRegistry().get_registered_ids())
        required = {
            "terminal_run", "file_read", "file_write", "git_status", "git_clone",
            "manage_memory", "manage_reminder", "manage_task", "manage_calendar",
            "daily_briefing", "weather_tool", "tavily_research", "universal_search",
            "system_metrics", "play_music", "github_integration",
        }
        self.assertTrue(required.issubset(ids), required - ids)


if __name__ == "__main__":
    unittest.main()
