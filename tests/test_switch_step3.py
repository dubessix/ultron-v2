"""V2 Step 3 - the Ultron <-> Zora switch obeys the owner."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.personalities.personality_engine import PersonalityEngine


def _switch(start: str, text: str) -> str:
    engine = PersonalityEngine()
    engine.update_state(start, "test", "manual")
    changed = engine.detect_manual_switch(text)
    return changed.active_personality if changed else start


class TestCallingANameSwitches(unittest.TestCase):
    def test_many_ways_to_call_zora(self):
        for text in (
            "Hey Zora", "hey zora, how are you", "Zora, I'm tired", "zora", "ok zora what's up",
            "switch to zora", "switch me back to zora", "bring zora back", "talk to zora",
            "I want zora", "i need zora", "zora mode", "zora kahan ho", "zora kothay",
            "where is zora", "Zorah, hi", "Can you switch to Zora please",
        ):
            with self.subTest(text=text):
                self.assertEqual(_switch("ultron", text), "zora")

    def test_ways_back_to_ultron(self):
        for text in (
            "Ultron, open downloads", "hey ultron", "back to work", "switch to ultron",
            "go back to ultron", "ultron mode", "altron open chrome", "bring ultron back",
        ):
            with self.subTest(text=text):
                self.assertEqual(_switch("zora", text), "ultron")

    def test_mentioning_a_name_does_not_switch(self):
        """Old bug: any sentence containing 'ultron' dragged Zora away."""
        for text in ("how does ultron handle memory?", "i love the ultron voice", "play music"):
            with self.subTest(text=text):
                self.assertEqual(_switch("zora", text), "zora")
        for text in ("what can zora do?", "is zora better than ultron", "open downloads"):
            with self.subTest(text=text):
                self.assertEqual(_switch("ultron", text), "ultron")


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
    async def asyncSetUp(self):
        self.orchestrator = CognitiveOrchestrator(personality_engine=PersonalityEngine(cooldown_turns=3))
        reply = {"content": "Of course.", "tool_calls": [], "provider": "groq", "model": "t",
                 "native_tools": True, "provider_state": None}
        self.orchestrator.router.get_completions_with_tools = AsyncMock(return_value=reply)
        self.orchestrator.router.get_completions = AsyncMock(return_value="Of course.")

    async def asyncTearDown(self):
        await self.orchestrator.close()

    async def say(self, text):
        result = await self.orchestrator.process_request(text, session_id="step3-switch")
        return result["active_personality"]

    async def test_a_real_evening(self):
        self.assertEqual(await self.say("open my downloads folder"), "ultron")
        self.assertEqual(await self.say("Hey Zora, I had a long day"), "zora")
        for text in ("tell me something nice", "play some calm music", "what's the weather",
                     "how does ultron compare to you?"):
            self.assertEqual(await self.say(text), "zora", text)
        self.assertEqual(await self.say("ok back to work"), "ultron")
        self.assertEqual(await self.say("what can zora do?"), "ultron")

    async def test_zora_prompt_is_used_after_switch(self):
        await self.say("switch to zora")
        system_prompt = self.orchestrator.router.get_completions.await_args
        native = self.orchestrator.router.get_completions_with_tools.await_args
        sent = str(system_prompt) + str(native)
        self.assertIn("Zora", sent)


if __name__ == "__main__":
    unittest.main()
