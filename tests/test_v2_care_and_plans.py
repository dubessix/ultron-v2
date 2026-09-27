"""Care and plans (owner's exam case, like JARVIS with Tony).

"exam tomorrow, not read" then "open anime" must get a real fact, one
recommendation and one offer; when he overrules, his call plus a reminder to
bring him back. Agreed plans are kept: blocks are announced when they start,
"finished it?" when they end, and the morning briefing counts down to the exam.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import unittest
import uuid
from pathlib import Path

from backend.app.core import arrival, plan_context
from backend.app.database.db import get_db_connection
from backend.app.tools.calendar_tool import CalendarTool

ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = re.compile(r"[#*_/\\<>{}|\[\]`~^=+]")


def local(**delta) -> dt.datetime:
    return (dt.datetime.now().astimezone() + dt.timedelta(**delta)).replace(second=0, microsecond=0)


def iso(moment: dt.datetime) -> str:
    return moment.replace(tzinfo=None).isoformat(timespec="seconds")


def ev(title, start, end=None, category="general", extra=None):
    end = end or start + dt.timedelta(hours=1)
    return {"id": uuid.uuid4().hex, "title": title, "description": json.dumps(extra or {}),
            "start_time": iso(start), "end_time": iso(end), "category": category,
            "_start": start, "_end": end}


def run(coro):
    return asyncio.run(coro)


class TestRules(unittest.TestCase):
    def test_both_personalities_get_the_same_care_rules(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        rules = CognitiveOrchestrator._action_mandate_block()
        for needed in ("Care and plans", "one recommendation", "don't do the fun part yet",
                       "his call", "manage_reminder", "NEW fact", "action=plan", "action=mark",
                       "action=shift", "exam, deadline, interview, appointment", "Advice order"):
            self.assertIn(needed, rules)
        self.assertIn(rules.strip(), CognitiveOrchestrator._jarvis_static_prefix())  # cached once, both personas

    def test_no_nagging_or_guilt_left_in_the_personas(self):
        for name in ("ultron", "zora"):
            text = (ROOT / f"backend/app/personalities/{name}.md").read_text(encoding="utf-8")
            self.assertLessEqual(len(text.split()), 400, name)
            self.assertIn("care and plans rules", text, name)
            for banned in ("remind him again, kindly but firmly", "check on him again",
                           "you must", "haven't earned", "not allowed"):
                self.assertNotIn(banned, text, name)
        self.assertIn("As you wish, Sir", (ROOT / "backend/app/personalities/ultron.md").read_text())

    def test_rules_only_name_banned_phrases_as_banned(self):
        from backend.app.core.control_tools import care_rules

        text = care_rules()
        self.assertIn('Never guilt or command ("you must"', text)
        self.assertNotRegex(text, r"\b\d{1,2}:\d{2}\b")  # fixed prefix: no clock times

    def test_yes_plus_new_requests_is_still_a_yes(self):
        from backend.app.core.control_tools import owner_reply_metadata

        text = owner_reply_metadata()["description"]
        self.assertIn("okk do", text)
        self.assertIn("also asks for more, call this first, then handle the rest", text)


class TestOwnerReplyWithExtraRequests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_offer_says_do_the_rest_too(self):
        from unittest.mock import patch

        from backend.app.core.orchestrator import CognitiveOrchestrator

        orch = CognitiveOrchestrator.__new__(CognitiveOrchestrator)
        orch._trust_offers = {}
        orch._turn_owner_yes = False
        with patch.object(CognitiveOrchestrator, "_last_ai_reply",
                          return_value="Shall I start a 10 minute focus session, Sir?"):
            _tool, _args, result = await orch._run_control_tool(
                "owner_reply", {"answer": "yes"}, session_id="care-test", first_call=True, coding_turn=False)
        self.assertTrue(result["success"])
        self.assertIn("no second question", result["data"]["message"])
        self.assertIn("anything else he asked in the same message", result["data"]["message"])
        self.assertTrue(orch._turn_owner_yes)


class CalendarCase(unittest.TestCase):
    def setUp(self):
        self.tag = uuid.uuid4().hex[:6]
        self.tool = CalendarTool()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with get_db_connection() as conn:
            conn.execute("DELETE FROM calendar_events WHERE title LIKE ?", (f"%{self.tag}%",))
            conn.commit()

    def rows(self):
        with get_db_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM calendar_events WHERE title LIKE ? ORDER BY start_time", (f"%{self.tag}%",))]

    def plan(self, blocks):
        return run(self.tool.execute(action="plan", blocks=blocks))

    def day_plan(self, first_in_minutes=30):
        start = local(minutes=first_in_minutes)
        blocks = []
        for number in range(4):
            begin = start + dt.timedelta(minutes=55 * number)
            blocks.append({"title": f"Physics block {number + 1} {self.tag}", "start_time": iso(begin),
                           "end_time": iso(begin + dt.timedelta(minutes=45))})
        sleep = start + dt.timedelta(minutes=55 * 4)
        blocks.append({"title": f"Sleep {self.tag}", "start_time": iso(sleep),
                       "end_time": iso(sleep + dt.timedelta(hours=7)), "check_in": False,
                       "say": "Lights out, Sir. Good night, big day tomorrow."})
        return blocks


class TestPlanInOneCall(CalendarCase):
    def test_full_day_plan_is_one_call(self):
        result = self.plan(self.day_plan())
        self.assertTrue(result["success"], result)
        rows = self.rows()
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["category"] == "plan" for r in rows))
        sleep = json.loads(rows[-1]["description"])
        self.assertFalse(sleep["check_in"])
        self.assertIn("Lights out", sleep["say"])

    def test_one_bad_block_saves_nothing(self):
        blocks = self.day_plan()
        blocks[2]["end_time"] = blocks[2]["start_time"]  # start == end
        result = self.plan(blocks)
        self.assertFalse(result["success"])
        self.assertIn("Block 3", result["error"])
        self.assertEqual(self.rows(), [])  # never half a plan

    def test_limits(self):
        many = [{"title": f"b{i} {self.tag}", "start_time": iso(local(hours=i + 1)),
                 "end_time": iso(local(hours=i + 1, minutes=30))} for i in range(13)]
        self.assertFalse(self.plan(many)["success"])
        past = [{"title": f"old {self.tag}", "start_time": iso(local(hours=-3)), "end_time": iso(local(hours=-2))}]
        self.assertIn("already over", self.plan(past)["error"])
        self.assertFalse(self.plan([])["success"])
        self.assertFalse(self.plan([{"title": "x", "start_time": "tomorrow", "end_time": "later"}])["success"])
        self.assertEqual(self.rows(), [])

    def test_done_by_title(self):
        self.plan(self.day_plan())
        result = run(self.tool.execute(action="mark", title=f"Physics block 1 {self.tag}", status="done"))
        self.assertTrue(result["success"], result)
        self.assertEqual(self.rows()[0]["category"], "plan_done")
        bad = run(self.tool.execute(action="mark", title=f"Physics block 2 {self.tag}", status="maybe"))
        self.assertFalse(bad["success"])

    def test_ten_more_minutes_moves_the_rest_of_the_day(self):
        self.plan(self.day_plan())
        before = self.rows()
        result = run(self.tool.execute(action="shift", title=f"Physics block 2 {self.tag}", minutes=10))
        self.assertTrue(result["success"], result)
        after = self.rows()
        moved = [dt.datetime.fromisoformat(a["start_time"]) - dt.datetime.fromisoformat(b["start_time"])
                 for a, b in zip(after, before, strict=True)]
        self.assertEqual(moved[0], dt.timedelta(0))  # block 1 stays
        self.assertTrue(all(m == dt.timedelta(minutes=10) for m in moved[1:4]))  # 2..4 move
        self.assertFalse(run(self.tool.execute(action="shift", title=f"Physics block 2 {self.tag}", minutes=0))["success"])

    def test_only_plan_blocks_can_be_marked(self):
        run(self.tool.execute(action="create", title=f"Physics exam {self.tag}", category="exam",
                              start_time=iso(local(days=1)), end_time=iso(local(days=1, hours=3))))
        self.assertFalse(run(self.tool.execute(action="mark", title=f"Physics exam {self.tag}"))["success"])


class TestPromptLines(unittest.TestCase):
    def test_soon_shows_the_exam_and_hides_old_ones(self):
        now = local()
        events = [ev("Physics exam", now.replace(hour=10) + dt.timedelta(days=1), category="exam"),
                  ev("Old chemistry exam", now - dt.timedelta(days=5), category="exam"),
                  ev("Far away trip", now + dt.timedelta(days=9)),
                  ev("Physics block 1", now + dt.timedelta(hours=1), category="plan")]
        line = plan_context.soon_line(now, events)
        self.assertTrue(line.startswith("[Soon] Physics exam"))
        self.assertIn("(tomorrow)", line)
        for hidden in ("Old chemistry", "Far away", "block"):
            self.assertNotIn(hidden, line)

    def test_nothing_coming_costs_nothing(self):
        now = local()
        self.assertEqual(plan_context.soon_line(now, []), "")
        self.assertEqual(plan_context.plan_line(now, []), "")

    def test_plan_line_knows_where_he_is(self):
        now = local().replace(hour=19, minute=40)
        events = [ev("Physics block 1", now.replace(hour=18, minute=30), now.replace(hour=19, minute=15), "plan_done"),
                  ev("Physics block 2", now.replace(hour=19, minute=30), now.replace(hour=20, minute=15), "plan"),
                  ev("Physics block 3", now.replace(hour=20, minute=30), now.replace(hour=21, minute=15), "plan")]
        line = plan_context.plan_line(now, events)
        self.assertIn("done 1 of 3", line)
        self.assertIn("now Physics block 2 until 20:15", line)
        self.assertIn("next Physics block 3 at 20:30", line)

    def test_sleep_block_is_not_counted_as_work(self):
        now = local().replace(hour=19, minute=0)
        events = [ev("Physics block 1", now.replace(hour=19, minute=30), now.replace(hour=20, minute=15), "plan"),
                  ev("Sleep", now.replace(hour=23, minute=30), now.replace(hour=23, minute=59), "plan",
                     {"check_in": False})]
        line = plan_context.plan_line(now, events)
        self.assertIn("done 0 of 1", line)
        self.assertIn("lights out 23:30", line)

    def test_soon_list_is_bounded(self):
        now = local()
        events = [ev(f"Thing {i}", now + dt.timedelta(hours=i + 1)) for i in range(20)]
        self.assertLessEqual(plan_context.soon_line(now, events).count("·"), plan_context.MAX_SOON - 1)


class TestSpokenPlan(CalendarCase):
    def setUp(self):
        super().setUp()
        arrival.clear()
        self.addCleanup(arrival.clear)

    def mine(self, warnings):
        return [w for w in warnings if self.tag in w["title"]]

    def test_block_start_and_end_are_spoken_once_in_plain_words(self):
        start = local(minutes=-1)
        self.plan([{"title": f"Physics block 1 {self.tag}", "start_time": iso(start),
                    "end_time": iso(start + dt.timedelta(minutes=45))}])
        spoken = self.mine(arrival.due_warnings())
        self.assertEqual(len(spoken), 1)
        self.assertIn("starts now", spoken[0]["speech"])
        self.assertFalse(self.mine(arrival.due_warnings()))  # only once
        end_check = arrival.due_warnings(now=start + dt.timedelta(minutes=46))
        self.assertIn("Finished it, or ten more minutes?", self.mine(end_check)[0]["speech"])
        self.assertFalse(SYMBOLS.search(self.mine(end_check)[0]["speech"].replace(self.tag, "")))

    def test_plan_blocks_skip_the_fifteen_minute_warning(self):
        start = local(minutes=10)
        self.plan([{"title": f"Physics block 1 {self.tag}", "start_time": iso(start),
                    "end_time": iso(start + dt.timedelta(minutes=45))}])
        self.assertFalse(self.mine(arrival.due_warnings()))

    def test_sleep_block_uses_its_own_line_and_no_check_in(self):
        start = local(minutes=-1)
        self.plan([{"title": f"Sleep {self.tag}", "start_time": iso(start), "check_in": False,
                    "end_time": iso(start + dt.timedelta(hours=7)), "say": "Lights out, Sir. Good night."}])
        spoken = self.mine(arrival.due_warnings())
        self.assertEqual(spoken[0]["speech"], "Lights out, Sir. Good night.")
        self.assertFalse(self.mine(arrival.due_warnings(now=start + dt.timedelta(hours=7, minutes=1))))

    def test_done_blocks_are_quiet(self):
        start = local(minutes=-1)
        self.plan([{"title": f"Physics block 1 {self.tag}", "start_time": iso(start),
                    "end_time": iso(start + dt.timedelta(minutes=45))}])
        run(self.tool.execute(action="mark", title=f"Physics block 1 {self.tag}", status="done"))
        self.assertFalse(self.mine(arrival.due_warnings()))


class TestMorningBriefing(unittest.TestCase):
    def test_exam_countdown_and_plan_progress(self):
        now = local().replace(hour=8, minute=0)
        events = [ev("Physics exam", now.replace(hour=10), category="exam"),
                  ev("Physics block 1", now - dt.timedelta(hours=12), category="plan_done")]
        lines = plan_context.arrival_sentences(now, events)
        self.assertEqual(lines[0], "Physics exam is today at 10 am.")
        speech = arrival.compose({"missed": [], "tasks": [], "next_event": None, "plan": lines}, now)
        self.assertIn("Physics exam is today at 10 am.", speech)
        self.assertFalse(SYMBOLS.search(speech))

    def test_morning_tells_how_last_night_went(self):
        now = local().replace(hour=8, minute=0)
        night = now - dt.timedelta(days=1)
        events = [ev(f"Physics block {i}", night.replace(hour=18 + i), category=c)
                  for i, c in ((1, "plan_done"), (2, "plan_done"), (3, "plan_done"), (4, "plan_skipped"))]
        events.append(ev("Sleep", night.replace(hour=23), category="plan", extra={"check_in": False}))
        self.assertIn("Last night's plan: 3 of 4 blocks done.", plan_context.arrival_sentences(now, events))

    def test_old_briefing_data_still_works(self):
        speech = arrival.compose({"missed": [], "tasks": [], "next_event": None}, local())
        self.assertIn("Nothing needs you right now.", speech)


class TestDoctorFixes(unittest.TestCase):
    def test_busy_port_used_by_ultron_is_fine(self):
        from unittest.mock import patch

        from backend.app import cli

        class Answer:
            status_code = 200
            text = "<title>ULTRON V2</title>"

            @staticmethod
            def json():
                return {"status": "ok"}

        with patch("httpx.get", return_value=Answer()):
            self.assertTrue(cli.port_used_by_ultron(8000, backend=True))
            self.assertTrue(cli.port_used_by_ultron(5173, backend=False))
        with patch("httpx.get", side_effect=OSError("refused")):
            self.assertFalse(cli.port_used_by_ultron(8000, backend=True))

    def test_one_key_grammar(self):
        from backend.app.health_checks import check_brain_state

        data = {"providers": {"gemini": {"configured": True, "key_states": {"active": 1}}}}
        self.assertIn("1 key ready", check_brain_state(8000, fetch=lambda url: data)[0][1])


if __name__ == "__main__":
    unittest.main()
