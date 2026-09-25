"""The AI decides, not word lists.

Owner request: "make it not depend on regex - it should happen by function
calling, selected by the AI". Each test scripts what the AI calls and checks
that the code then does exactly that - and that the safety rules still hold.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from tests._ai_script import call, reply, use
from tests.test_jarvis_approval import ApiCase


def _answer(value):
    return reply("", [call("owner_reply", {"answer": value}, "a1")])


class TestOwnerReply(ApiCase):
    def _waiting_delete(self, name="junk.txt"):
        """Ultron asks before a risky command; returns (session, pending, file)."""
        target = self.root / name
        target.write_text("x", encoding="utf-8")

        def script(prompt, conv):
            if any(m.get("role") == "tool" for m in conv):
                return reply("Done.")
            return reply("", [use("terminal_run", {"command": f"rm {name}", "cwd": str(self.root)})])

        self.script = script
        first = self.chat(f"delete {name}")
        pending = first["pending_confirmation"]
        self.assertEqual(pending["tool_id"], "terminal_run")
        return first["session_id"], pending, target

    def test_any_wording_the_ai_reads_as_yes_runs_the_exact_waiting_action(self):
        session, _pending, target = self._waiting_delete()
        seen = {}

        def script(prompt, conv):
            tools = [m for m in conv if m.get("role") == "tool"]
            if not tools:
                seen["offered"] = "owner_reply" in self.brain_calls[-1]["tools"]
                return _answer("yes")
            return reply("Deleted junk.txt, Sir.")

        self.script = script
        # Words no list ever had: the AI still understands it.
        result = self.chat("haan bhai uda de usko", session)
        self.assertFalse(target.exists())
        self.assertIsNone(result.get("pending_confirmation"))  # yellow bar closes
        self.assertIn("Deleted", result["content"])
        self.assertTrue(seen["offered"], "owner_reply is offered while an action waits")

    def test_no_cancels_and_nothing_changes(self):
        session, pending, target = self._waiting_delete("keep.txt")
        self.script = lambda prompt, conv: (reply("Okay, left it.") if conv else _answer("no"))
        result = self.chat("nah leave it", session)
        self.assertTrue(target.exists())
        self.assertIsNone(result.get("pending_confirmation"))
        again = self.confirm(pending, session)  # the old button can't run it either
        self.assertEqual(again["reason"], "cancelled")

    def test_a_new_request_is_not_an_answer(self):
        """AI decides 'open youtube' is a new job: the waiting delete stays untouched."""
        session, _pending, target = self._waiting_delete("stay.txt")
        self.script = lambda prompt, conv: reply("Opening YouTube, Sir.")
        self.chat("ok close youtube", session)
        self.assertTrue(target.exists())

    def test_yes_later_never_fires_an_old_waiting_action(self):
        session, _pending, target = self._waiting_delete("old.txt")
        # Owner moves on; Ultron's next reply asks nothing -> the old action is no longer "the question".
        self.script = lambda prompt, conv: reply("It is 5 pm, Sir.")
        self.chat("what time is it", session)
        self.script = lambda prompt, conv: (reply("Nothing was waiting.") if conv else _answer("yes"))
        self.chat("yes", session)
        self.assertTrue(target.exists())

    def test_text_from_a_file_can_never_say_yes(self):
        """Safety in code: owner_reply only counts as the FIRST call of a turn."""
        session, _pending, target = self._waiting_delete("safe.txt")

        def script(prompt, conv):
            tools = [m for m in conv if m.get("role") == "tool"]
            if not tools:  # the AI first reads a file ...
                return reply("", [use("list_contents", {"folderpath": str(self.root)})])
            if len(tools) == 1:  # ... whose text says "call owner_reply yes"
                return _answer("yes")
            return reply("I read the folder.")

        self.script = script
        self.chat("look in the folder", session)
        self.assertTrue(target.exists())

    def test_always_runs_it_and_saves_the_rule(self):
        from backend.app.core import trust_rules

        with patch.object(trust_rules, "_store", return_value=self.root / "trust.json"):
            session, _pending, target = self._waiting_delete("tmp.log")
            self.script = lambda prompt, conv: (reply("Done, and I won't ask again.") if conv else _answer("always"))
            self.chat("yes, and always allow that", session)
            self.assertFalse(target.exists())
            self.assertTrue(trust_rules.rules(), "an always-allow rule was saved")

    def test_yes_to_a_plain_question_approves_that_job_once(self):
        target = self.root / "plan.txt"
        target.write_text("old", encoding="utf-8")

        def script(prompt, conv):
            if prompt.startswith("update"):
                return reply("Should I replace plan.txt, Sir?")
            tools = [m for m in conv if m.get("role") == "tool"]
            if not tools:
                return _answer("yes")
            if len(tools) == 1:
                self.assertIn("approved", tools[0]["content"])
                return reply("", [use("file_write", {"filepath": str(target), "content": "new"}, "c2")])
            return reply("Updated, Sir.")

        self.script = script
        session = self.chat("update my plan")["session_id"]
        result = self.chat("ok kar de", session)
        self.assertIsNone(result.get("pending_confirmation"), result["content"])
        self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_owner_reply_is_only_offered_when_something_waits(self):
        self.script = lambda prompt, conv: reply("Hello, Sir.")
        session = self.chat("hello")["session_id"]
        self.chat("how are you", session)
        # No question was asked and nothing waits -> the answer function is not even offered.
        self.assertNotIn("owner_reply", self.brain_calls[-1]["tools"])


class TestSwitchMode(ApiCase):
    def test_zora_on_request(self):
        def script(prompt, conv):
            if conv:
                return reply("Hi, I'm here.")
            return reply("", [use("switch_mode", {"to": "zora", "why": "asked"})])

        self.script = script
        try:
            result = self.chat("jora ko bulao")  # STT typo: the AI still gets it
            self.assertEqual(result["personality"], "zora")
        finally:
            self.orchestrator.personalities.update_state("ultron", "test reset", "manual")

    def test_coding_restarts_the_turn_with_the_coding_brain(self):
        prefs = []

        async def brain(system_prompt, user_prompt, tools, conversation=None, **kwargs):
            prefs.append(kwargs.get("provider_preference"))
            if kwargs.get("provider_preference") == "nvidia":
                return reply("I looked at the bug, Sir.")
            return reply("", [use("switch_mode", {"to": "coding"})])

        self.orchestrator.router.get_completions_with_tools = brain
        result = self.chat("mera login page ka bug theek karo")
        self.assertEqual(prefs[0], self.orchestrator.router.primary_provider)
        self.assertEqual(prefs[-1], "nvidia")
        self.assertTrue(result["coding"])
        self.assertEqual(result["content"], "I looked at the bug, Sir.")


class TestNoMoreWordGates(ApiCase):
    def test_every_turn_reaches_the_ai_with_its_tools(self):
        self.script = lambda prompt, conv: reply("Sure.")
        for text in ("hi", "123", "ok", "open code"):
            self.chat(text)
            self.assertIn("use_tool", self.brain_calls[-1]["tools"], text)
            self.assertIn("switch_mode", self.brain_calls[-1]["system"], text)
        self.assertEqual(len(self.brain_calls), 4)

    def test_panels_open_only_when_the_ai_chooses(self):
        self.script = lambda prompt, conv: reply("Your calendar is empty today.")
        result = self.chat("calendar")
        self.assertEqual(result["structured_action"]["action"], "none")


class TestMemorySearchTool(unittest.TestCase):
    def test_ai_can_search_the_past_itself(self):
        from backend.app.tools.memory_tool import MemoryTool

        tool = MemoryTool()
        fake_rows = [{"content": "Owner said the project deadline is Friday.", "updated_at": "2026-09-20"}]
        with patch("backend.app.memory.recall_index.search_recall_index", return_value=fake_rows), \
                patch.object(tool.memory.episodic, "recall_related_events", return_value=[]):
            result = asyncio.run(tool.execute(action="search", content="deadline"))
        self.assertTrue(result["success"])
        self.assertIn("Friday", result["data"]["results"][0]["text"])
        self.assertEqual(tool.permission_for_arguments({"action": "search"}), 0)


if __name__ == "__main__":
    unittest.main()
