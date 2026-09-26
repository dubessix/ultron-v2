"""V2 Step 2 - reminders: right time, local zone, never lost, told on arrival."""

from __future__ import annotations

import asyncio
import datetime as dt
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.core import reminder_inbox
from backend.app.core.time_parse import parse_when, speakable_time
from backend.app.database.db import get_db_connection
from backend.app.main import app, run_reminder_scheduler
from backend.app.tools.reminder_tool import ReminderTool

IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")
NOW = dt.datetime(2026, 9, 25, 14, 0, tzinfo=IST)  # a Friday, 2 PM


class LocalZone(unittest.TestCase):
    def setUp(self):
        patcher = patch("backend.app.core.time_parse.local_timezone", return_value=IST)
        patcher.start()
        self.addCleanup(patcher.stop)

    def at(self, text):
        return parse_when(text, NOW)


class TestUnitsAreRight(LocalZone):
    """Old bug: every unit containing an 's' (minutes, hours, days) meant seconds."""

    def test_words_with_s_are_not_seconds(self):
        self.assertEqual(self.at("10 minutes") - NOW, dt.timedelta(minutes=10))
        self.assertEqual(self.at("2 hours") - NOW, dt.timedelta(hours=2))
        self.assertEqual(self.at("3 days") - NOW, dt.timedelta(days=3))
        self.assertEqual(self.at("30 seconds") - NOW, dt.timedelta(seconds=30))

    def test_compact_and_combined(self):
        for text, minutes in (
            ("10m", 10), ("+5m", 5), ("1h30m", 90), ("1 hour 30 minutes", 90),
            ("2 hours and 15 minutes", 135), ("half an hour", 30), ("an hour", 60),
            ("1.5 hours", 90), ("in 20 min", 20), ("10 minute baad", 10), ("2 ghante baad", 120),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.at(text) - NOW, dt.timedelta(minutes=minutes))


class TestNaturalTimes(LocalZone):
    def check(self, text, day, hour, minute=0):
        got = self.at(text)
        self.assertEqual((got.day, got.hour, got.minute), (day, hour, minute), text)

    def test_english(self):
        self.check("tomorrow 10am", 26, 10)
        self.check("tomorrow at 10 am", 26, 10)
        self.check("today at 5:30 pm", 25, 17, 30)
        self.check("tonight", 25, 21)
        self.check("tomorrow morning", 26, 9)
        self.check("tomorrow", 26, 9)  # old bug: 'tomorrow' was ten minutes
        self.check("monday 9am", 28, 9)
        self.check("day after tomorrow", 27, 9)
        self.check("remind me at 8:15 pm", 25, 20, 15)

    def test_hinglish_and_bengali(self):
        self.check("kal subah 10 baje", 26, 10)
        self.check("parso shaam 6 baje", 27, 18)
        self.check("kal sokal 9 ta", 26, 9)
        self.check("aaj raat 10 baje", 25, 22)

    def test_bare_hour_means_the_next_one(self):
        self.check("at 5", 25, 17)   # said at 2 PM -> 5 PM, not 5 AM tomorrow
        self.check("at 11 am", 26, 11)  # already past today -> tomorrow

    def test_iso_without_zone_is_local_not_utc(self):
        """Old bug: naive ISO was UTC, so 10 AM became 3:30 PM in India."""
        self.check("2026-09-26T10:00:00", 26, 10)
        self.assertEqual(self.at("2026-09-26T10:00:00Z").hour, 15)  # explicit UTC kept

    def test_nonsense_is_rejected_not_invented(self):
        for text in ("sometime-ish", "10", "10 tasks", "", "-5m"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.at(text)

    def test_speakable(self):
        self.assertEqual(speakable_time(self.at("tomorrow 10am"), NOW), "10:00 AM tomorrow")
        self.assertEqual(speakable_time(self.at("at 5"), NOW), "5:00 PM today")


class TestReminderTool(unittest.TestCase):
    def run_tool(self, **kwargs):
        return asyncio.run(ReminderTool().execute(**kwargs))

    def test_create_reports_local_time_and_list_shows_it(self):
        title = f"step2-{uuid.uuid4().hex[:6]}"
        created = self.run_tool(action="create", title=title, target_time="in 2 hours")
        self.assertTrue(created["success"], created)
        stored = dt.datetime.fromisoformat(created["data"]["target_time"])
        delta = stored - dt.datetime.now(dt.timezone.utc)
        self.assertTrue(dt.timedelta(minutes=119) < delta <= dt.timedelta(hours=2))
        self.assertIn("when_local", created["data"])
        listed = self.run_tool(action="list")["data"]["reminders"]
        mine = [r for r in listed if r["title"] == title]
        self.assertTrue(mine and "when_local" in mine[0])
        self.run_tool(action="delete", reminder_id=created["data"]["id"])

    def test_past_time_is_refused(self):
        result = self.run_tool(action="create", title="late", target_time="2020-01-01T10:00:00")
        self.assertFalse(result["success"])
        self.assertIn("already past", result["error"])

    def test_snooze_custom_length_and_title_instead_of_id(self):
        title = f"snooze-{uuid.uuid4().hex[:6]}"
        created = self.run_tool(action="create", title=title, target_time="10m")
        snoozed = self.run_tool(action="snooze", reminder_id=title, target_time="15 minutes")
        self.assertTrue(snoozed["success"], snoozed)
        new_time = dt.datetime.fromisoformat(snoozed["data"]["new_target_time"])
        self.assertGreater(new_time - dt.datetime.now(dt.timezone.utc), dt.timedelta(minutes=14))
        self.assertTrue(self.run_tool(action="delete", reminder_id=created["data"]["id"])["success"])


def _insert_due(title, minutes_ago=0.0, kind="reminder"):
    reminder_id = f"step2-{uuid.uuid4()}"
    target = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO reminders_alarms (id, type, title, target_time, recurrence, status) "
            "VALUES (?, ?, ?, ?, 'one_time', 'pending');",
            (reminder_id, kind, title, target.isoformat()),
        )
        conn.commit()
    return reminder_id


def _clear_inbox():
    with get_db_connection() as conn:
        conn.execute("UPDATE reminder_inbox SET delivered_at = 'test-cleared' WHERE delivered_at IS NULL;")
        conn.commit()


class _Screens:
    """Fake ws_manager: 'count' screens connected."""

    def __init__(self, count):
        self.count = count
        self.sent = []
        self.seen = asyncio.Event()

    async def broadcast(self, channel, payload):
        self.sent.append(payload)
        self.seen.set()
        return self.count


async def _fire_once(screens, reminder_id):
    with patch("backend.app.main.ws_manager", screens):
        task = asyncio.create_task(run_reminder_scheduler())
        try:
            for _ in range(60):
                await asyncio.sleep(0.1)
                if any(p.get("reminder", {}).get("id") == reminder_id for p in screens.sent):
                    break
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class TestNeverLost(unittest.TestCase):
    def setUp(self):
        _clear_inbox()

    def test_owner_at_screen_hears_it_live_and_it_is_not_repeated(self):
        rid = _insert_due("drink water")
        screens = _Screens(count=1)
        asyncio.run(_fire_once(screens, rid))
        payload = next(p for p in screens.sent if p["reminder"]["id"] == rid)
        self.assertEqual(payload["type"], "reminder_triggered")
        self.assertEqual(payload["speech"], "Sir, reminder: drink water.")
        self.assertEqual([e for e in reminder_inbox.undelivered() if e["reminder_id"] == rid], [])

    def test_owner_away_then_told_when_he_comes(self):
        rid = _insert_due("call Rahul", minutes_ago=90)  # PC was off at the time
        asyncio.run(_fire_once(_Screens(count=0), rid))
        waiting = [e for e in reminder_inbox.undelivered() if e["reminder_id"] == rid]
        self.assertEqual(len(waiting), 1)
        self.assertTrue(waiting[0]["late"])

        with TestClient(app).websocket_connect("/ws/events?client_id=step2-arrival") as ws:
            message = ws.receive_json()
        self.assertEqual(message["type"], "missed_reminders")
        self.assertIn("call Rahul", message["speech"])
        self.assertTrue(message["speech"].startswith("Welcome back, Sir. While you were away"))
        self.assertIn("set for", message["speech"])  # late ones say when they were due
        self.assertEqual([e for e in reminder_inbox.undelivered() if e["reminder_id"] == rid], [])

    def test_speech_has_no_symbols(self):
        entries = [
            reminder_inbox.describe({"id": "1", "reminder_id": "a", "type": "reminder", "title": "call_Rahul",
                                     "target_time": NOW.isoformat(), "fired_at": NOW.isoformat()}, NOW),
            reminder_inbox.describe({"id": "2", "reminder_id": "b", "type": "alarm", "title": "gym",
                                     "target_time": NOW.isoformat(), "fired_at": NOW.isoformat()}, NOW),
        ]
        speech = reminder_inbox.away_speech(entries)
        self.assertEqual(speech, "Welcome back, Sir. While you were away, 2 reminders: call Rahul; and gym.")
        for symbol in "_#*/\\[]{}<>|@":
            self.assertNotIn(symbol, speech)


if __name__ == "__main__":
    unittest.main()


class TestSchedulerCatchUp(unittest.TestCase):
    """PC off for days: a daily reminder fires ONCE, then waits for its next future time."""

    def test_next_future_target_skips_missed_days(self):
        from backend.app.main import _next_future_target

        now = dt.datetime(2026, 9, 26, 9, 0, tzinfo=dt.timezone.utc)
        three_days_ago = now - dt.timedelta(days=3, hours=1)
        nxt = _next_future_target(three_days_ago, dt.timedelta(days=1), now)
        self.assertGreater(nxt, now)
        self.assertLessEqual(nxt - now, dt.timedelta(days=1))
        self.assertEqual(nxt.hour, three_days_ago.hour)

    def test_on_time_repeat_moves_one_step(self):
        from backend.app.main import _next_future_target

        now = dt.datetime(2026, 9, 26, 9, 0, 1, tzinfo=dt.timezone.utc)
        target = dt.datetime(2026, 9, 26, 9, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(_next_future_target(target, dt.timedelta(days=7), now), target + dt.timedelta(days=7))

    def test_naive_stored_time_is_safe(self):
        from backend.app.main import _next_future_target

        now = dt.datetime(2026, 9, 26, 9, 0, tzinfo=dt.timezone.utc)
        nxt = _next_future_target(dt.datetime(2026, 9, 20, 8, 0), dt.timedelta(days=1), now)
        self.assertGreater(nxt, now)

    def test_db_pass_runs_off_the_event_loop(self):
        import inspect

        from backend.app import main

        self.assertFalse(inspect.iscoroutinefunction(main.collect_due_reminders))
        self.assertIn("asyncio.to_thread(collect_due_reminders)", inspect.getsource(main.run_reminder_scheduler))
