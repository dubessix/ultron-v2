"""V2 Step 3 - the Ultron <-> Zora switch obeys the owner."""

from __future__ import annotations

import unittest

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.personalities.personality_engine import PersonalityEngine


class TestZoraStaysWhenChosen(unittest.TestCase):
    def test_manual_zora_never_times_out(self):
        """Old bug: Zora left after 3 turns even when the owner chose her."""
        engine = PersonalityEngine(cooldown_turns=3)
        engine.update_state("zora", "Manual", "manual")
        for _ in range(10):
            self.assertIsNone(engine.increment_zora_lifecycle())
        self.assertEqual(engine.state.active_personality, "zora")

    def test_restored_session_zora_never_times_out(self):
        engine = PersonalityEngine(cooldown_turns=3)
        engine.update_state("zora", "Restored from session", "system")
        for _ in range(5):
            engine.increment_zora_lifecycle()
        self.assertEqual(engine.state.active_personality, "zora")

    def test_stress_handoff_still_returns(self):
        engine = PersonalityEngine(cooldown_turns=3)
        engine.update_state("zora", "Auto-handoff", "automatic")
        results = [engine.increment_zora_lifecycle() for _ in range(3)]
        self.assertIsNotNone(results[-1])
        self.assertEqual(engine.state.active_personality, "ultron")


class TestConversationThroughTheOrchestrator(unittest.IsolatedAsyncioTestCase):
    """Who answers is chosen by the AI with switch_mode - no word list."""

    async def asyncSetUp(self):
        from tests._ai_script import reply, use

        self.orchestrator = CognitiveOrchestrator(personality_engine=PersonalityEngine(cooldown_turns=3))

        def script(prompt, conv):
            if any(m.get("role") == "tool" for m in conv):
                return reply("Of course.")
            low = prompt.lower()
            if "zora" in low and "long day" in low:
                return reply("", [use("switch_mode", {"to": "zora", "why": "asked"})])
            if "back to work" in low:
                return reply("", [use("switch_mode", {"to": "ultron", "why": "asked"})])
            if "nothing works" in low:
                return reply("", [use("switch_mode", {"to": "zora", "why": "mood"})])
            return reply("Of course.")

        self.script = script

    async def asyncTearDown(self):
        await self.orchestrator.close()

    async def say(self, text):
        from tests._ai_script import scripted_brain

        with scripted_brain(self.orchestrator, self.script) as calls:
            result = await self.orchestrator.process_request(text, session_id="step3-switch")
        self.last_calls = calls
        return result["active_personality"]

    async def test_a_real_evening(self):
        self.assertEqual(await self.say("open my downloads folder"), "ultron")
        self.assertEqual(await self.say("Hey Zora, I had a long day"), "zora")
        for text in ("tell me something nice", "play some calm music", "what's the weather",
                     "how does ultron compare to you?"):
            self.assertEqual(await self.say(text), "zora", text)  # he asked: she stays
        self.assertEqual(await self.say("ok back to work"), "ultron")
        self.assertEqual(await self.say("what can zora do?"), "ultron")  # AI: a question, not a switch

    async def test_zora_prompt_is_used_after_switch(self):
        await self.say("Hey Zora, I had a long day")
        await self.say("tell me something nice")
        self.assertIn("Zora", self.last_calls[0]["system"])

    async def test_stress_noticed_by_the_ai_returns_to_ultron_later(self):
        self.assertEqual(await self.say("the build is broken, nothing works"), "zora")
        states = [await self.say(t) for t in ("ok", "thanks", "fine")]
        self.assertEqual(self.orchestrator.personalities.state.active_personality, "ultron", states)


if __name__ == "__main__":
    unittest.main()
