"""Final list step 5: long goals with one progress line a week (zero tokens)."""

from __future__ import annotations

import datetime as dt
import re
import unittest
import uuid

from backend.app.core import arrival, goals
from backend.app.database.db import get_db_connection

SYMBOLS = re.compile(r"[#*_/\\<>{}|\[\]`~^=+]")


def local(**delta) -> dt.datetime:
    return (dt.datetime.now().astimezone() + dt.timedelta(**delta)).replace(microsecond=0)


class GoalRows(unittest.TestCase):
    def setUp(self):
        arrival.clear()
        self.addCleanup(arrival.clear)
        self.ids: list[str] = []

    def tearDown(self):
        with get_db_connection() as conn:
            for row_id in self.ids:
                conn.execute("DELETE FROM project_tasks WHERE id = ?", (row_id,))
            conn.commit()

    def add(self, title, *, project="Goals", due=None, status="todo", parent=None, priority="medium", created=None):
        row_id = uuid.uuid4().hex
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO project_tasks (id, project_name, module_name, title, priority, due_date, status, "
                "parent_task_id, created_at) VALUES (?, ?, 'Root', ?, ?, ?, ?, ?, ?)",
                (row_id, project, title, priority, due, status, parent,
                 (created or local()).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
        self.ids.append(row_id)
        return row_id


class TestProgressLine(GoalRows):
    def line(self, now=None):
        with get_db_connection() as conn:
            return goals.weekly_lines(conn, now or local())

    def test_steps_and_weeks_left_in_plain_words(self):
        goal = self.add("Goal: finish React", due=(local(days=64)).date().isoformat(), created=local(days=-2))
        for i in range(8):
            self.add(f"react step {i}", parent=goal, status="done" if i < 3 else "todo")
        [line] = self.line()
        self.assertEqual(line, "Goal check, finish React: 3 of 8 steps done, about 9 weeks left and ahead of pace.")
        self.assertIsNone(SYMBOLS.search(line))

    def test_behind_pace_is_said_only_when_the_numbers_show_it(self):
        goal = self.add("learn Rust", due=local(days=10).date().isoformat(), created=local(days=-30))
        for i in range(4):
            self.add(f"rust {i}", parent=goal, status="done" if i == 0 else "todo")
        [line] = self.line()
        self.assertEqual(line, "Goal check, learn Rust: 1 of 4 steps done, 10 days left and a little behind pace.")

    def test_passed_date_offers_a_new_date(self):
        self.add("ship portfolio", due=local(days=-2).date().isoformat())
        [line] = self.line()
        self.assertEqual(line, "Goal check, ship portfolio: its date passed 2 days ago. Shall I set a new date?")

    def test_goal_without_steps_or_date_offers_steps(self):
        self.add("read more books")
        [line] = self.line()
        self.assertEqual(line, "Goal check, read more books: still open. Want me to break it into steps?")

    def test_done_goals_and_normal_tasks_are_not_goals(self):
        self.add("old goal", status="done")
        self.add("buy milk", project="General")
        self.assertEqual(self.line(), [])

    def test_only_the_two_nearest_goals_are_spoken(self):
        for days in (90, 10, 40):
            self.add(f"goal in {days}", due=local(days=days).date().isoformat())
        lines = self.line()
        self.assertEqual(len(lines), 2)
        self.assertIn("goal in 10", lines[0])
        self.assertIn("goal in 40", lines[1])


class TestWeeklyInStatus(GoalRows):
    def test_first_welcome_back_of_the_week_says_it_once(self):
        self.add("finish React", due=local(days=30).date().isoformat())
        now = local()
        arrival.touch(now - dt.timedelta(hours=5))
        first = arrival.briefing(now=now)
        self.assertIn("Goal check, finish React", first["speech"])
        arrival.touch(now + dt.timedelta(hours=1))
        again = arrival.briefing(now=now + dt.timedelta(hours=4))
        self.assertNotIn("Goal check", again["speech"])
        arrival.touch(now + dt.timedelta(days=7))
        next_week = arrival.briefing(now=now + dt.timedelta(days=7, hours=3))
        self.assertIn("Goal check, finish React", next_week["speech"])

    def test_a_high_priority_goal_is_not_a_task_for_today(self):
        self.add("become fluent in German", priority="high")
        now = local()
        arrival.touch(now - dt.timedelta(hours=5))
        speech = arrival.briefing(now=now)["speech"]
        self.assertNotIn("task", speech.split("Goal check")[0])

    def test_no_goals_means_no_line_and_no_week_mark(self):
        now = local()
        arrival.touch(now - dt.timedelta(hours=5))
        speech = arrival.briefing(now=now)["speech"]
        self.assertNotIn("Goal check", speech)
        self.assertNotIn("goal_week", arrival._load())


class TestDailyBriefing(GoalRows):
    def test_briefing_says_the_nearest_goal_and_shows_all(self):
        from backend.app.tools.daily_briefing_tool import DailyBriefingTool

        self.add("finish React", due=local(days=30).date().isoformat())
        now = local()
        day = DailyBriefingTool._local_day(now, True, False)
        self.assertEqual(day["tasks"], [t for t in day["tasks"] if t["title"] != "finish React"])
        self.assertEqual(len(day["goals"]), 1)


if __name__ == "__main__":
    unittest.main()
