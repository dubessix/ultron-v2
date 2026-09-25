"""V2 Step 8 - welcome-back briefing and heads-up warnings (no LLM, zero tokens)."""

from __future__ import annotations

import datetime as dt
import re
import unittest
import uuid

from fastapi.testclient import TestClient

from backend.app.core import arrival
from backend.app.database.db import get_db_connection

SYMBOLS = re.compile(r"[#*_/\\<>{}|\[\]`~^=+]")


def local(**delta) -> dt.datetime:
    return (dt.datetime.now().astimezone() + dt.timedelta(**delta)).replace(microsecond=0)


class Rows(unittest.TestCase):
    def setUp(self):
        arrival.clear()
        self.addCleanup(arrival.clear)
        self.ids: list[tuple[str, str]] = []
        self.tag = uuid.uuid4().hex[:6]

    def tearDown(self):
        with get_db_connection() as conn:
            for table, row_id in self.ids:
                conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
            conn.commit()

    def add_task(self, title, due, priority="medium", status="todo"):
        row_id = uuid.uuid4().hex
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO project_tasks (id, project_name, module_name, title, priority, due_date, status) "
                "VALUES (?, 'personal', 'general', ?, ?, ?, ?)", (row_id, title, priority, due, status))
            conn.commit()
        self.ids.append(("project_tasks", row_id))

    def add_event(self, title, start: dt.datetime):
        row_id = uuid.uuid4().hex
        with get_db_connection() as conn:
            conn.execute("INSERT INTO calendar_events (id, title, start_time, end_time) VALUES (?, ?, ?, ?)",
                         (row_id, title, start.replace(tzinfo=None).isoformat(),
                          (start + dt.timedelta(hours=1)).replace(tzinfo=None).isoformat()))
            conn.commit()
        self.ids.append(("calendar_events", row_id))

    def add_fired(self, title, fired: dt.datetime):
        row_id = uuid.uuid4().hex
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO reminder_inbox (id, reminder_id, type, title, target_time, fired_at) "
                "VALUES (?, 'r', 'reminder', ?, ?, ?)",
                (row_id, title, fired.astimezone(dt.timezone.utc).isoformat(),
                 fired.astimezone(dt.timezone.utc).isoformat()))
            conn.commit()
        self.ids.append(("reminder_inbox", row_id))


class TestComposeSpeech(unittest.TestCase):
    def test_two_to_three_plain_sentences(self):
        now = dt.datetime(2026, 9, 25, 18, 30).astimezone()
        data = {
            "missed": [{"title": "drink water"}, {"title": "call Rahul"}],
            "tasks": [{"title": "project_report", "overdue": True}, {"title": "gym", "overdue": False},
                      {"title": "pay bill", "overdue": False}],
            "next_event": {"title": "Team sync", "_start": now.replace(hour=19, minute=0)},
        }
        speech = arrival.compose(data, now)
        self.assertEqual(
            speech,
            "Good evening, Sir. Welcome back. While you were away, 2 reminders went off: drink water and "
            "call Rahul. You have 3 tasks for today, 1 overdue, starting with project report and next up "
            "is Team sync at 7 PM.",
        )
        self.assertFalse(SYMBOLS.search(speech))
        self.assertLessEqual(speech.count(". "), 3)

    def test_quiet_day(self):
        now = dt.datetime(2026, 9, 25, 9, 0).astimezone()
        speech = arrival.compose({"missed": [], "tasks": [], "next_event": None}, now)
        self.assertEqual(speech, "Good morning, Sir. Welcome back. Nothing needs you right now.")

    def test_many_reminders_are_summarised(self):
        now = dt.datetime(2026, 9, 25, 14, 0).astimezone()
        speech = arrival.compose({"missed": [{"title": f"r{i}"} for i in range(6)], "tasks": [], "next_event": None}, now)
        self.assertIn("6 reminders went off: r0, r1 and r2 and 3 more.", speech)


class TestBriefingTiming(Rows):
    def test_back_after_three_hours(self):
        arrival.touch(local(hours=-3))
        self.add_fired(f"stretch {self.tag}", local(hours=-1))
        self.add_task(f"submit form {self.tag}", local(hours=4).replace(tzinfo=None).isoformat(), priority="high")
        self.add_event(f"dinner {self.tag}", local(hours=2))
        payload = arrival.briefing()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "arrival_briefing")
        self.assertIn(f"stretch {self.tag}", payload["missed"])
        self.assertIn(f"submit form {self.tag}", payload["tasks"])
        self.assertIn("Welcome back", payload["speech"])
        self.assertGreaterEqual(payload["away_minutes"], 179)
        self.assertIsNone(arrival.briefing())  # he is here now: no repeat

    def test_short_break_says_nothing(self):
        arrival.touch(local(minutes=-90))
        self.assertIsNone(arrival.briefing())
        self.assertIsNotNone(arrival.briefing(force=True))

    def test_reminders_before_he_left_are_not_repeated(self):
        self.add_fired(f"old one {self.tag}", local(hours=-5))
        arrival.touch(local(hours=-3))
        payload = arrival.briefing()
        self.assertNotIn(f"old one {self.tag}", payload["missed"])


class TestHeadsUp(Rows):
    def test_deadline_in_an_hour_is_spoken_once(self):
        self.add_task(f"report {self.tag}", local(minutes=50).replace(tzinfo=None).isoformat())
        warnings = [w for w in arrival.due_warnings() if self.tag in w["title"]]
        self.assertEqual(len(warnings), 1)
        self.assertRegex(warnings[0]["speech"], r"^Sir, heads up: report \w+ is due in (49|50) minutes\.$")
        self.assertFalse([w for w in arrival.due_warnings() if self.tag in w["title"]])  # only once

    def test_event_fifteen_minutes_before(self):
        self.add_event(f"standup {self.tag}", local(minutes=10))
        warnings = [w for w in arrival.due_warnings() if self.tag in w["title"]]
        self.assertEqual(len(warnings), 1)
        self.assertIn("starts in", warnings[0]["speech"])
        self.assertFalse(SYMBOLS.search(warnings[0]["speech"]))

    def test_no_false_alarms(self):
        self.add_task(f"far {self.tag}", local(hours=3).replace(tzinfo=None).isoformat())
        self.add_task(f"dateonly {self.tag}", local(minutes=30).date().isoformat())
        self.add_task(f"finished {self.tag}", local(minutes=20).replace(tzinfo=None).isoformat(), status="done")
        self.add_event(f"later {self.tag}", local(hours=2))
        self.assertFalse([w for w in arrival.due_warnings() if self.tag in w["title"]])


class TestApi(Rows):
    def test_arrival_endpoint(self):
        from backend.app.main import app

        client = TestClient(app)
        arrival.touch(local(hours=-4))
        body = client.get("/api/arrival").json()
        self.assertEqual(body["data"]["type"], "arrival_briefing")
        self.assertEqual(client.get("/api/arrival").json()["data"]["type"], "none")


if __name__ == "__main__":
    unittest.main()
