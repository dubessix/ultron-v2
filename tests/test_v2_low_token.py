"""Low-token plan (T4, T6, T7) + owner's identity rule.

- The fixed start of every prompt must stay byte-identical (Groq caches it and
  cached tokens do not count toward the free limit).
- Recent chat: newest turn kept almost whole, older turns only their gist.
- Ultron/Zora: "like Jarvis but sharper", never call themselves Jarvis.
- Meter: today's real counted tokens from the provider's own numbers.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._ai_script import reply
from tests.test_jarvis_approval import ApiCase

ROOT = Path(__file__).resolve().parents[1]


class TestFixedPrefixStaysCached(ApiCase):
    def test_prompt_start_is_identical_across_orders_and_sessions(self):
        self.script = lambda prompt, conv: reply("Done, Sir.")
        first = self.chat("how much RAM is free")
        self.chat("open my Downloads folder", first["session_id"])
        self.chat("kal subah 10 baje yaad dilana")  # a NEW session
        prompts = [call["system"] for call in self.brain_calls]
        self.assertGreaterEqual(len(prompts), 3)

        from backend.app.core.orchestrator import CognitiveOrchestrator

        fixed = CognitiveOrchestrator._jarvis_static_prefix()
        persona = (ROOT / "backend/app/personalities/ultron.md").read_text(encoding="utf-8").strip()
        for prompt in prompts:
            self.assertTrue(prompt.startswith(fixed), "rules + PC + tool menu must come first, unchanged")
            self.assertIn(persona, prompt[: len(fixed) + len(persona) + 4])
        # Changing parts (recent chat, time) only after the fixed part.
        for prompt in prompts:
            self.assertGreater(prompt.index("[RECENT_CONVERSATION]"), len(fixed) + len(persona))

    def test_fixed_part_has_no_clock_or_ram_numbers(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        fixed = CognitiveOrchestrator._jarvis_static_prefix()
        self.assertNotIn("[Now]", fixed)
        self.assertNotRegex(fixed, r"\b\d{1,2}:\d{2}\b")  # no time of day
        self.assertEqual(fixed, CognitiveOrchestrator._jarvis_static_prefix())


class TestRecentChatIsSmallButKeepsTheNewestTurn(unittest.TestCase):
    def _format(self, turns):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        return CognitiveOrchestrator._format_prompt_history(turns)

    def test_newest_reply_stays_whole_for_follow_ups(self):
        headlines = "Here are the headlines. " + " ".join(f"{i}. Story number {i}." for i in range(1, 30))
        turns = [{"user": "open downloads", "ai": "Opening your Downloads, Sir."}] * 5
        turns.append({"user": "news today", "ai": headlines})
        text = self._format(turns)
        self.assertIn("29. Story number 29.", text)  # "open the second one" still works

    def test_worst_case_is_bounded_and_smaller_than_before(self):
        turns = [{"user": "word " * 600, "ai": "reply " * 600} for _ in range(8)]
        text = self._format(turns)
        self.assertLessEqual(len(text), 4300)
        self.assertEqual(text.count("Owner:"), 6)  # still the last 6 turns

    def test_older_turns_keep_their_start(self):
        turns = [{"user": f"order {i} " + "x" * 900, "ai": f"answer {i} " + "y" * 900} for i in range(6)]
        text = self._format(turns)
        for i in range(6):
            self.assertIn(f"order {i}", text)
            self.assertIn(f"answer {i}", text)


class TestIdentity(unittest.TestCase):
    def test_ultron_is_like_jarvis_but_never_calls_himself_jarvis(self):
        ultron = (ROOT / "backend/app/personalities/ultron.md").read_text(encoding="utf-8")
        zora = (ROOT / "backend/app/personalities/zora.md").read_text(encoding="utf-8")
        self.assertIn("You are ULTRON", ultron)
        self.assertIn("Like Jarvis, but sharper", ultron)
        self.assertIn("never call yourself Jarvis", ultron)
        self.assertIn("never call yourself Jarvis", zora)
        self.assertNotIn("personal Jarvis", ultron)

        from backend.app.core.orchestrator import CognitiveOrchestrator

        rules = CognitiveOrchestrator._action_mandate_block()
        self.assertNotIn("You are the owner's Jarvis", rules)
        self.assertIn("never 'Jarvis'", rules)

    def test_every_tool_rule_is_still_in_the_rules(self):
        # The identity fix must not remove a single tool-calling rule.
        from backend.app.core.orchestrator import CognitiveOrchestrator

        rules = CognitiveOrchestrator._action_mandate_block()
        for rule in ("call tools now", "Multi-step jobs", "Talk while working", "Live facts",
                     "try one other route", "Never ask permission in words", "Small doubt",
                     "Ask only when", "non-interactive flags", "owner_reply", "switch_mode",
                     "manage_memory", "Never claim something happened", "Final reply"):
            self.assertIn(rule, rules)

    def test_personas_are_short(self):
        for name in ("ultron", "zora"):
            words = len((ROOT / f"backend/app/personalities/{name}.md").read_text(encoding="utf-8").split())
            self.assertLess(words, 400, name)

    def test_both_care_about_him_like_jarvis(self):
        # Owner: "exam tomorrow, I didn't study" must get real concern, a push to
        # study and an OFFER of help, not a silent tool call or "Got it, Sir".
        for name in ("ultron", "zora"):
            text = (ROOT / f"backend/app/personalities/{name}.md").read_text(encoding="utf-8")
            self.assertIn("## Caring for Debjeet", text, name)
            self.assertIn("exam", text, name)
            self.assertIn("not orders: offer, then act after his yes", text, name)
            self.assertIn("Shall I", text, name)
            self.assertIn('never a bare "Done"', text, name)

    def test_rules_offer_unasked_help_and_sound_warm(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        rules = CognitiveOrchestrator._action_mandate_block()
        self.assertIn("Something he did NOT ask for", rules)
        self.assertIn("Shall I set a reminder for your exam, Sir?", rules)
        self.assertIn('never a bare "Done"', rules)
        self.assertNotIn('("Done, Sir.")', rules)


class TestUsageMeter(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        patcher = patch("backend.app.brain.usage_meter._path", return_value=self.dir / "usage.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_counts_like_groq_does(self):
        from backend.app.brain import usage_meter

        for _ in range(3):
            usage_meter.add("groq", {"prompt_tokens": 2400, "completion_tokens": 150,
                                     "prompt_tokens_details": {"cached_tokens": 2000}}, today="2026-09-27")
        row = usage_meter.today("2026-09-27")["groq"]
        self.assertEqual(row["calls"], 3)
        self.assertEqual(row["counted"], 3 * (400 + 150))
        line = usage_meter.summary_line(groq_keys=2, day="2026-09-27")
        self.assertIn("3 calls", line)
        self.assertIn("of 400K Groq tokens", line)
        self.assertIn("cache hits 83%", line)

    def test_keeps_only_two_weeks_and_never_raises(self):
        from backend.app.brain import usage_meter

        for day in range(1, 21):
            usage_meter.add("groq", {"prompt_tokens": 10}, today=f"2026-09-{day:02d}")
        self.assertEqual(usage_meter.today("2026-09-01"), {})
        self.assertIn("groq", usage_meter.today("2026-09-20"))
        usage_meter.add("groq", "not a dict")  # ignored safely
        (self.dir / "usage.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(usage_meter.today(), {})
        usage_meter.add("groq", {"prompt_tokens": 5})  # recovers from a broken file

    def test_doctor_warns_near_the_daily_limit(self):
        from backend.app import health_checks
        from backend.app.brain import usage_meter

        usage_meter.add("groq", {"prompt_tokens": 190_000})
        with patch.dict(os.environ, {"GROQ_API_KEY_1": "gsk_" + "Z9" * 20}, clear=False):
            result = health_checks.check_usage_today()
        self.assertEqual(result[0][0], "warn")
        self.assertIn("GROQ_API_KEY_2", result[0][2])


if __name__ == "__main__":
    unittest.main()
