"""Log fixes 5 + 6: never a false 'done', never leaked self-talk or hidden marks."""

from __future__ import annotations

import unittest

from backend.app.core import approval, reply_guard
from tests._ai_script import reply, use
from tests.test_jarvis_approval import ApiCase


class TestScrub(unittest.TestCase):
    def test_leaked_thinking_is_cut(self):
        text = "The user asked to open YouTube. We need to respond briefly. YouTube is open, Sir."
        self.assertEqual(reply_guard.scrub(text), "YouTube is open, Sir.")

    def test_hidden_marks_are_removed(self):
        self.assertEqual(reply_guard.scrub("Ready\u200b, Sir\u2060.\ufeff"), "Ready, Sir.")

    def test_nothing_left_gives_the_real_result_never_bare_done(self):
        results = [{"tool": "open_app", "success": True, "result": {"message": "Opened Firefox"}}]
        self.assertEqual(reply_guard.scrub("The user wants firefox. Let's respond.", results), "Opened Firefox, Sir.")
        self.assertEqual(reply_guard.scrub("", [{"tool": "open_app", "success": True, "result": {}}]),
                         "That's done, Sir. The open app step worked.")
        self.assertIn("say that again", reply_guard.scrub("\u200b", []))

    def test_normal_replies_are_untouched(self):
        for text in ("Yes, Sir.", "We need to finish chapter 3 before Friday, Sir.",
                     "The user guide says restart it.\nLine two stays.", "Hi."):
            self.assertEqual(reply_guard.scrub(text), text.strip())


class TestClaims(unittest.TestCase):
    def test_claims(self):
        for text in ("Done, Sir.", "Okay Sir, I've opened YouTube.", "I set a reminder for 5 pm.",
                     "All set!", "I have scheduled it for Monday.", "I've marked it done."):
            self.assertTrue(reply_guard.claims_action(text), text)

    def test_not_claims(self):
        for text in ("Done with chapter 3? Nice.", "Your exam is scheduled for Monday.",
                     "I set that reminder earlier.", "Should I open it?", "I have to say, good work."):
            self.assertFalse(reply_guard.claims_action(text), text)

    def test_honest_reply_knows_the_new_words(self):
        failed = [{"tool": "reminder_create", "success": False, "error": "bad time"}]
        for word in ("scheduled", "marked", "booked", "added"):
            self.assertIn("did not work", approval.honest_reply(f"I {word} it, Sir.", failed))


class TestNoToolClaimOnTheRealPath(ApiCase):
    def test_said_done_without_a_tool_then_really_does_it(self):
        target = self.root / "note.txt"

        def script(prompt, conv):
            if any(m.get("role") == "tool" for m in conv):
                return reply("Created note.txt, Sir.")
            if "[Check]" in prompt:
                return reply("", [use("file_write", {"filepath": str(target), "content": "hi"})])
            return reply("Done, Sir. I've created note.txt.")

        self.script = script
        result = self.chat(f"create {target} with hi")
        self.assertTrue(target.exists())
        self.assertIn("Created", result["content"])
        self.assertEqual(sum("[Check]" in c["user"] for c in self.brain_calls), 1)

    def test_still_no_tool_means_the_truth(self):
        self.script = lambda prompt, conv: reply("Done, Sir. I've opened YouTube.")
        result = self.chat("open youtube")
        self.assertEqual(result["content"], reply_guard.unfinished_claim_reply())
        self.assertEqual(len(self.brain_calls), 2)  # one retry, never a loop

    def test_plain_talk_costs_no_extra_call(self):
        self.script = lambda prompt, conv: reply("Good evening, Sir.")
        result = self.chat("hi")
        self.assertEqual(result["content"], "Good evening, Sir.")
        self.assertEqual(len(self.brain_calls), 1)

    def test_leak_is_cut_on_the_real_path(self):
        self.script = lambda prompt, conv: reply("The user said hi. We need to respond. Good evening, Sir.")
        self.assertEqual(self.chat("hi")["content"], "Good evening, Sir.")


if __name__ == "__main__":
    unittest.main()
