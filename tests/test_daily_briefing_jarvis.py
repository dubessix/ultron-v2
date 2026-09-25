"""Daily briefing sounds like an assistant: short natural speech, clean chat text."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from backend.app.database.db import get_db_connection
from backend.app.tools.daily_briefing_tool import DailyBriefingTool, _headline, _is_index_page

# The voice must never read symbols, links or bracket tags.
SPOKEN_JUNK = re.compile(r"[#*_/\\<>{}|\[\]`~^=+@%°]|https?:|\.com\b|===")
NOW = dt.datetime(2026, 9, 25, 9, 30).astimezone()

WEATHER = {
    "available": True, "source": "Open-Meteo", "temperature": "29.4°C", "temp_c": 29,
    "high_c": 33, "low_c": 26, "condition": "cloudy", "windspeed": "12.0 km/h",
    "rain": {"time": "2026-09-25T16:00", "chance": 70},
}
NEWS = {"available": True, "items": [
    {"title": "OpenAI ships a new model - Reuters",
     "headline": "OpenAI ships a new model", "site": "Reuters",
     "url": "https://news.google.com/rss/articles/CBMiVeryLongGarbageToken?oc=5"},
]}
NO_WEATHER = {"available": False, "temperature": None, "source": "Open-Meteo", "error": "offline"}
NO_NEWS = {"available": False, "items": [], "error": "offline"}
FLAGS = (True, True, True, True)


def at(hour, minute=0, days=0):
    return (NOW.replace(hour=hour, minute=minute) + dt.timedelta(days=days))


def busy_day():
    return {
        "events": [{"title": "Team sync", "start": at(11), "category": "work"},
                   {"title": "Dentist", "start": at(15, 30), "category": "personal"}],
        "reminders": [{"title": "call mom", "at": at(19)}],
        "tasks": [
            {"title": "project report", "priority": "high", "due": at(23, 59, days=-1),
             "date_only": True, "project": "Work", "overdue": True},
            {"title": "pay electricity bill", "priority": "medium", "due": at(18),
             "date_only": False, "project": "Home", "overdue": False},
        ],
    }


class SpeechFeelsLikeAnAssistant(unittest.TestCase):
    def setUp(self):
        self.tool = DailyBriefingTool()

    def compose(self, day, weather=WEATHER, news=NEWS, greeting="Good morning, Sir."):
        return self.tool._compose(NOW, greeting, weather, news, day, FLAGS)

    def test_busy_day_speech_is_natural_and_ordered(self):
        speech, _ = self.compose(busy_day())
        self.assertTrue(speech.startswith("Good morning, Sir. It's Friday, 25 September."))
        self.assertIn("cloudy and 29 degrees, heading up to 33", speech)
        self.assertIn("Rain is likely around 4 PM, so keep an umbrella handy.", speech)
        self.assertIn("2 events left today, starting with Team sync at 11 AM.", speech)
        self.assertIn("I'll remind you about call mom at 7 PM.", speech)
        self.assertIn("1 is overdue: project report.", speech)
        self.assertIn("I'd clear project report first.", speech)
        self.assertIn("headlines on your screen", speech)

    def test_speech_never_contains_symbols_or_links(self):
        for day in (busy_day(), {"events": [], "reminders": [], "tasks": []}):
            for weather, news in ((WEATHER, NEWS), (NO_WEATHER, NO_NEWS)):
                speech, _ = self.compose(day, weather, news)
                self.assertIsNone(SPOKEN_JUNK.search(speech), speech)

    def test_speech_is_short(self):
        speech, _ = self.compose(busy_day())
        self.assertLess(len(speech), 520, speech)  # about 30 seconds of voice

    def test_clear_day_gets_a_helpful_line(self):
        speech, text = self.compose({"events": [], "reminders": [], "tasks": []})
        self.assertIn("Your day is clear, a good window for focused work.", speech)
        self.assertIn("No events on your calendar.", text)
        self.assertIn("Nothing due today.", text)

    def test_event_within_the_hour_is_the_suggestion(self):
        day = {"events": [{"title": "Standup", "start": at(10), "category": "work"}],
               "reminders": [], "tasks": []}
        speech, _ = self.compose(day)
        self.assertIn("Standup is within the hour, so you may want to get ready.", speech)

    def test_offline_sources_are_honest(self):
        speech, text = self.compose(busy_day(), NO_WEATHER, NO_NEWS)
        self.assertIn("I couldn't reach the weather service just now.", speech)
        self.assertIn("no estimate was substituted", text)
        self.assertIn("no headlines were substituted", text)
        self.assertNotIn("degrees", speech)


class ChatTextIsClean(unittest.TestCase):
    def test_no_robot_markup_and_no_long_links(self):
        _, text = DailyBriefingTool()._compose(NOW, "Good morning, Sir.", WEATHER, NEWS, busy_day(), FLAGS)
        for junk in ("===", "[SCHEDULE", "[HIGH", "BACKLOG", "http", "General/Root"):
            self.assertNotIn(junk, text)
        self.assertIn("OpenAI ships a new model  (Reuters)", text)
        self.assertIn("11 AM  Team sync", text)
        self.assertIn("Reminder: call mom", text)
        self.assertIn("project report  (overdue)", text)
        self.assertIn("pay electricity bill  (due 6 PM)", text)
        self.assertIn("TASKS  (2 open, 1 overdue)", text)
        self.assertIn("Suggestion: I'd clear project report first.", text)

    def test_headline_source_from_title_or_site(self):
        self.assertEqual(_headline("Big AI news - TechCrunch", "https://news.google.com/x"),
                         ("Big AI news", "TechCrunch"))
        self.assertEqual(_headline("Big AI news", "https://www.theverge.com/a/b"),
                         ("Big AI news", "theverge.com"))
        self.assertEqual(_headline("Big AI news", "https://news.google.com/rss/x")[1], "")


class NewsSectionPagesAreSkipped(unittest.TestCase):
    def test_index_pages_are_not_headlines(self):
        for title in ("Google News - Artificial intelligence - Latest",
                      "AI News | Latest Headlines and Developments | Reuters",
                      "AI News Today - Latest Artificial Intelligence News & Updates"):
            self.assertTrue(_is_index_page(title), title)
        self.assertFalse(_is_index_page("OpenAI ships a new reasoning model - Reuters"))


class RealDatabaseDay(unittest.TestCase):
    """Tasks due today/overdue and today's reminders are read (not only 'high')."""

    def setUp(self):
        self.tag = uuid.uuid4().hex[:6]
        self.ids = []

    def tearDown(self):
        with get_db_connection() as conn:
            for table, row_id in self.ids:
                conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
            conn.commit()

    def _insert(self, table, sql, values):
        row_id = uuid.uuid4().hex
        with get_db_connection() as conn:
            conn.execute(sql, (row_id, *values))
            conn.commit()
        self.ids.append((table, row_id))

    def test_reads_due_today_overdue_and_reminders(self):
        now = dt.datetime.now().astimezone()
        later = (now + dt.timedelta(minutes=30)).replace(microsecond=0)
        yesterday = (now - dt.timedelta(days=1)).date().isoformat()
        self._insert("project_tasks",
                     "INSERT INTO project_tasks (id, title, priority, due_date, status) VALUES (?, ?, 'low', ?, 'todo')",
                     (f"overdue {self.tag}", yesterday))
        self._insert("project_tasks",
                     "INSERT INTO project_tasks (id, title, priority, due_date, status) VALUES (?, ?, 'low', ?, 'done')",
                     (f"finished {self.tag}", yesterday))
        if later.date() == now.date():
            self._insert("reminders_alarms",
                         "INSERT INTO reminders_alarms (id, type, title, target_time, recurrence, status) "
                         "VALUES (?, 'reminder', ?, ?, 'none', 'pending')",
                         (f"water {self.tag}", later.astimezone(dt.timezone.utc).isoformat()))
        day = DailyBriefingTool._local_day(now, True, True)
        titles = [t["title"] for t in day["tasks"]]
        self.assertIn(f"overdue {self.tag}", titles)
        self.assertNotIn(f"finished {self.tag}", titles)
        overdue = next(t for t in day["tasks"] if t["title"] == f"overdue {self.tag}")
        self.assertTrue(overdue["overdue"])
        if later.date() == now.date():
            self.assertIn(f"water {self.tag}", [r["title"] for r in day["reminders"]])

    def test_full_tool_returns_speech_and_text(self):
        tool = DailyBriefingTool()
        with patch.object(tool, "_get_local_weather", new=AsyncMock(return_value=WEATHER)), \
             patch.object(tool, "_get_live_news", new=AsyncMock(return_value=NEWS)):
            result = asyncio.run(tool.execute())
        data = result["data"]
        self.assertTrue(result["success"])
        self.assertTrue(data["speech"])
        self.assertTrue(data["briefing_text"])
        self.assertIsNone(SPOKEN_JUNK.search(data["speech"]), data["speech"])


if __name__ == "__main__":
    unittest.main()
