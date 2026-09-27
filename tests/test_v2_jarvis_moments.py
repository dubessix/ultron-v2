"""JARVIS moments at 0 tokens (owner: "make it like that, not only for that").

General, not only physics or memory: any exam, deadline, interview or
appointment; any PC strain (RAM, CPU, disk, battery). Each line is spoken
once, only when he is here (event lines) or not at night (PC lines), with
plain words, and his answer is understood on the next message.
"""

from __future__ import annotations

import datetime as dt
import re
import unittest
import uuid
from unittest.mock import patch

from backend.app.core import arrival, proactive
from backend.app.core.proactive import PcReadings

SYMBOLS = re.compile(r"[#*_/\\<>{}|\[\]`~^=+]")


def at(hour, minute=0, days=0):
    base = dt.datetime.now().astimezone().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base + dt.timedelta(days=days)


def ev(title, start, hours=3, category="exam"):
    return {"id": uuid.uuid4().hex, "title": title, "category": category, "description": "{}",
            "start_time": start.replace(tzinfo=None).isoformat(), "end_time": (start + dt.timedelta(hours=hours)).replace(tzinfo=None).isoformat(),
            "_start": start, "_end": start + dt.timedelta(hours=hours)}


class Case(unittest.TestCase):
    def setUp(self):
        proactive.clear()
        self.addCleanup(proactive.clear)

    def speak(self, now, *, readings=None, events=(), active=True, helper=False, top_app="Chrome"):
        with patch.object(proactive, "_active", return_value=active), \
                patch.object(proactive, "top_memory_app", return_value=top_app):
            return proactive.run_checks(now=now, readings=readings or PcReadings(), events=list(events),
                                        helper_connected=helper)

    def assertPlain(self, items):
        for item in items:
            self.assertEqual(item["type"], "heads_up")
            self.assertFalse(SYMBOLS.search(item["speech"].replace("%", "")), item["speech"])


class TestPcStrain(Case):
    def test_memory_after_five_minutes_names_the_app_and_offers(self):
        now = at(15)
        high = PcReadings(ram_percent=93)
        for minute in range(4):
            self.assertEqual(self.speak(now + dt.timedelta(minutes=minute), readings=high, helper=True), [])
        said = self.speak(now + dt.timedelta(minutes=4), readings=high, helper=True)
        self.assertEqual(said[0]["speech"], "Memory is at 93%, Sir, mostly Chrome. Shall I sleep the background tabs?")
        self.assertPlain(said)
        self.assertEqual(self.speak(now + dt.timedelta(minutes=5), readings=high, helper=True), [])  # once

    def test_memory_speaks_again_only_after_it_recovered(self):
        now = at(15)
        for minute in range(5):
            self.speak(now + dt.timedelta(minutes=minute), readings=PcReadings(ram_percent=95))
        self.speak(now + dt.timedelta(minutes=6), readings=PcReadings(ram_percent=60))  # recovered
        again = [self.speak(now + dt.timedelta(minutes=7 + m), readings=PcReadings(ram_percent=95)) for m in range(5)]
        self.assertEqual(sum(len(x) for x in again), 1)

    def test_other_app_gets_a_fact_not_an_offer_it_cannot_keep(self):
        now = at(15)
        said = []
        for minute in range(5):
            said += self.speak(now + dt.timedelta(minutes=minute), readings=PcReadings(ram_percent=91), top_app="VS Code")
        self.assertEqual(said[0]["speech"], "Memory is at 91%, Sir, mostly VS Code. Closing VS Code would free the most.")

    def test_cpu_disk_battery(self):
        now = at(15)
        said = []
        for minute in range(5):
            said += self.speak(now + dt.timedelta(minutes=minute),
                               readings=PcReadings(cpu_percent=99, disk_free_gb=3.2, battery_percent=12, battery_plugged=False))
        text = " | ".join(s["speech"] for s in said)
        self.assertIn("processor has been at full load for five minutes", text)
        self.assertIn("3.2 gigabytes left. Shall I find the biggest files?", text)
        self.assertIn("Battery is at 12%, Sir. Time to plug in.", text)
        self.assertEqual(len(said), 3)  # each once
        self.assertPlain(said)

    def test_desktop_without_battery_and_healthy_pc_stay_silent(self):
        now = at(15)
        for minute in range(10):
            self.assertEqual(self.speak(now + dt.timedelta(minutes=minute),
                                        readings=PcReadings(ram_percent=55, cpu_percent=20, disk_free_gb=180)), [])

    def test_quiet_at_night_unless_he_is_here(self):
        night = at(2)
        for minute in range(6):
            self.assertEqual(self.speak(night + dt.timedelta(minutes=minute),
                                        readings=PcReadings(ram_percent=95), active=False), [])
        self.assertTrue(self.speak(night + dt.timedelta(minutes=7), readings=PcReadings(ram_percent=95), active=True))


class TestImportantEvents(Case):
    def test_evening_before_any_important_event(self):
        for category, title in (("exam", "Physics exam"), ("interview", "TCS interview"),
                                ("deadline", "Project submission"), ("appointment", "Dentist")):
            proactive.clear()
            event = ev(title, at(10, days=1), category=category)
            said = self.speak(at(20), events=[event])
            self.assertEqual(said[0]["speech"], f"Tomorrow: {title} at 10 am, Sir. Shall we make a plan for tonight?")
            self.assertEqual(self.speak(at(21), events=[event]), [])  # once

    def test_normal_events_do_not_trigger_care_lines(self):
        self.assertEqual(self.speak(at(20), events=[ev("Movie with friends", at(10, days=1), category="general")]), [])

    def test_late_night_before(self):
        event = ev("Physics exam", at(10))
        said = self.speak(at(0, 30), events=[event])
        self.assertEqual(said[0]["speech"], "It's past midnight, Sir, and Physics exam is at 10 am. "
                                            "Sleep will do more for you now than another hour awake.")
        self.assertEqual(self.speak(at(1, 30), events=[event]), [])

    def test_the_day_after_he_is_asked_how_it_went(self):
        event = ev("Physics exam", at(10, days=-1))
        said = self.speak(at(18), events=[event])
        self.assertEqual(said[0]["speech"], "How did the Physics exam go, Sir?")
        self.assertEqual(self.speak(at(19), events=[event]), [])  # once
        line = proactive.recent_line(at(18, 10))
        self.assertIn('"How did the Physics exam go, Sir?"', line)
        self.assertIn("manage_memory remember", line)

    def test_event_lines_wait_until_he_is_here(self):
        event = ev("Physics exam", at(10, days=1))
        self.assertEqual(self.speak(at(20), events=[event], active=False), [])
        self.assertTrue(self.speak(at(20, 30), events=[event], active=True))

    def test_no_questions_in_the_middle_of_the_night(self):
        event = ev("Physics exam", at(10, days=-1))
        self.assertEqual(self.speak(at(23, 30), events=[event]), [])


class TestNextMessageUnderstandsIt(Case):
    def test_his_yes_is_understood_then_the_line_expires(self):
        now = at(15)
        for minute in range(5):
            self.speak(now + dt.timedelta(minutes=minute), readings=PcReadings(ram_percent=93), helper=True)
        line = proactive.recent_line(now + dt.timedelta(minutes=10))
        self.assertIn("Shall I sleep the background tabs?", line)
        self.assertIn("act on that", line)
        self.assertEqual(proactive.recent_line(now + dt.timedelta(hours=2)), "")

    def test_nothing_said_costs_nothing(self):
        self.assertEqual(proactive.recent_line(), "")


class TestMorningStatus(Case):
    def test_one_breath_order_and_followup_once(self):
        now = at(8)
        exam = ev("Physics exam", at(10))
        yesterday = ev("Chemistry exam", at(10, days=-1))
        with patch.object(proactive, "_active", return_value=False):
            ask = proactive.briefing_followup(now, [exam, yesterday])
        self.assertEqual(ask, "How did the Chemistry exam go, Sir?")
        self.assertIsNone(proactive.briefing_followup(now, [exam, yesterday]))  # once
        speech = arrival.compose({"missed": [], "tasks": [{"title": "Revise optics", "overdue": False}],
                                  "next_event": None,
                                  "plan": ["Physics exam is today at 10 am.", "Last night's plan: 3 of 4 blocks done."],
                                  "followup": ask}, now)
        self.assertTrue(speech.startswith("Good morning, Sir. Welcome back. Physics exam is today at 10 am. "
                                          "Last night's plan: 3 of 4 blocks done. How did the Chemistry exam go, Sir?"))
        self.assertIn("starting with Revise optics", speech)
        self.assertFalse(SYMBOLS.search(speech))


class TestSafety(Case):
    def test_never_raises_and_state_stays_bounded(self):
        with patch.object(proactive, "_load", side_effect=RuntimeError("disk gone")):
            self.assertEqual(proactive.run_checks(readings=PcReadings(), events=[]), [])
        state = {}
        now = at(12)
        for number in range(400):
            proactive._mark(state, f"k{number}", now + dt.timedelta(seconds=number))
        self.assertLessEqual(len(state["said"]), 300)

    def test_real_reading_is_cheap_and_safe(self):
        readings = proactive.read_pc()
        self.assertIsInstance(readings, PcReadings)


if __name__ == "__main__":
    unittest.main()
