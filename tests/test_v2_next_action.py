"""Final list step 6: one 'next on your list' offer after a finished job (0 tokens)."""

from __future__ import annotations

import datetime as dt
import unittest
import uuid

from backend.app.core import next_action
from backend.app.database.db import get_db_connection

OK = [{"tool": "apps", "success": True, "result": {}}]


def at(hour, minute=0, days=0) -> dt.datetime:
    base = dt.datetime.now().astimezone().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base + dt.timedelta(days=days)


class Rows(unittest.TestCase):
    def setUp(self):
        next_action.clear()
        self.addCleanup(next_action.clear)
        self.ids: list[str] = []
        with get_db_connection() as conn:  # other tests' leftovers must not decide the pick
            self.hidden = [r[0] for r in conn.execute("SELECT id FROM project_tasks WHERE status != 'done'")]
            conn.executemany("UPDATE project_tasks SET status = 'done' WHERE id = ?", [(i,) for i in self.hidden])
            conn.commit()

    def tearDown(self):
        with get_db_connection() as conn:
            conn.executemany("DELETE FROM project_tasks WHERE id = ?", [(i,) for i in self.ids])
            conn.executemany("UPDATE project_tasks SET status = 'todo' WHERE id = ?", [(i,) for i in self.hidden])
            conn.commit()

    def add(self, title, *, due=None, priority="medium", project="General", parent=None):
        row_id = uuid.uuid4().hex
        with get_db_connection() as conn:
            conn.execute("INSERT INTO project_tasks (id, project_name, title, priority, due_date, status, parent_task_id) "
                         "VALUES (?, ?, ?, ?, ?, 'todo', ?)", (row_id, project, title, priority, due, parent))
            conn.commit()
        self.ids.append(row_id)
        return row_id


class TestOffer(Rows):
    def test_offers_the_top_task_once_in_plain_words(self):
        self.add("Physics revision: chapter 3!", due=at(18).date().isoformat())
        reply = next_action.suggest("VS Code is open, Sir.", OK, now=at(10))
        self.assertEqual(reply, "VS Code is open, Sir. Next on your list: Physics revision chapter 3. Want to start on it?")

    def test_overdue_beats_high_priority_beats_later(self):
        self.add("later thing", due=at(20).isoformat())
        self.add("important thing", priority="high")
        self.add("late thing", due=at(8).isoformat())
        self.assertIn("late thing", next_action.suggest("Done.", OK, now=at(10)))

    def test_recommend_once_then_respect(self):
        first = self.add("write report", priority="high")
        self.add("call mom", priority="high")
        self.assertIn("write report", next_action.suggest("Done.", OK, now=at(10)))
        self.assertEqual(next_action.suggest("Done.", OK, now=at(11)), "Done.")  # 2 hour gap
        later = next_action.suggest("Done.", OK, now=at(13))
        self.assertIn("call mom", later)  # the same task is never offered twice a day
        self.assertEqual(next_action.suggest("Done.", OK, now=at(16)), "Done.")  # nothing new left today
        self.assertIsNotNone(first)

    def test_stays_quiet_when_it_does_not_fit(self):
        self.add("write report", priority="high")
        quiet = [
            ("Should I delete it, Sir?", OK, False, at(10)),                      # already a question
            ("Done.", [], False, at(10)),                                         # plain chat, no job
            ("Done.", [{"tool": "apps", "success": False}], False, at(10)),       # a step failed
            ("Done.", [{"tool": "manage_task", "success": True}], False, at(10)),  # list tools talk already
            ("Done.", [{"tool": "browser_page", "success": True, "result": {"needs_yes": True}}], False, at(10)),
            ("Done.", OK, True, at(10)),                                          # coding job
            ("Done.", OK, False, at(23, 30)),                                     # night
            ("Done.", OK, False, at(5)),
            ("Your write report file is saved.", OK, False, at(10)),              # reply already names it
        ]
        for text, results, coding, now in quiet:
            with self.subTest(text=text, now=now.hour):
                self.assertEqual(next_action.suggest(text, results, coding_turn=coding, now=now), text)

    def test_goals_and_later_tasks_are_not_offered(self):
        self.add("finish React", project="Goals", priority="high")
        self.add("next week thing", due=at(10, days=7).date().isoformat())
        self.assertEqual(next_action.suggest("Done.", OK, now=at(10)), "Done.")

    def test_a_broken_database_never_breaks_the_reply(self):
        from unittest.mock import patch

        with patch("backend.app.database.db.get_db_connection", side_effect=RuntimeError("locked")):
            self.assertEqual(next_action.suggest("Done.", OK, now=at(10)), "Done.")


class TestInTheAgentLoop(Rows):
    async def _run(self):
        from unittest.mock import patch

        from backend.app.core.orchestrator import CognitiveOrchestrator

        orchestrator = CognitiveOrchestrator.__new__(CognitiveOrchestrator)
        with patch("backend.app.core.orchestrator.ToolRegistry"):
            return await CognitiveOrchestrator._run_native_agent_loop(
                orchestrator, {"content": "Chrome is open, Sir.", "tool_calls": []},
                system_prompt="s", user_prompt="open chrome", tools=[], session_id="t", project_id="p",
                project_root=None, coding_turn=False, provider_for_turn="groq",
                tool_results=[{"tool": "apps", "success": True, "result": {}}])

    def test_finished_job_reply_carries_the_offer(self):
        import asyncio

        self.add("pay electricity bill", priority="high")
        now = dt.datetime.now().astimezone()
        reply = asyncio.run(self._run())["content"]
        if now.hour >= 23 or now.hour < 6:
            self.assertEqual(reply, "Chrome is open, Sir.")
        else:
            self.assertEqual(reply, "Chrome is open, Sir. Next on your list: pay electricity bill. Want to start on it?")


if __name__ == "__main__":
    unittest.main()
