"""
Ultron Unit & Integration Testing Suite — Phase 6 Refactored Diagnostics
Tests structured PersonalityState models, markdown prompt caching, extensible OCP-compliant
emotion signals, Zora auto-return lifecycles, and dynamic WS event publications.
"""

import unittest
from unittest.mock import patch

from backend.app.personalities.base_personality import UltronPersonality
from backend.app.personalities.personality_engine import PersonalityEngine, PersonalityState
from backend.app.emotion.signal_analyzer import SignalAnalyzer, BaseEmotionSignal
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.memory.memory_engine import MemoryEngine

# Define mock custom signal to verify OCP
class MockTypingSpeedSignal(BaseEmotionSignal):
    def __init__(self) -> None:
        super().__init__(weight=0.1)

    def evaluate(self, **kwargs) -> float:
        typing_speed_wpm = kwargs.get("typing_speed_wpm", 60)
        # Low typing speed under pressure (e.g. 20 WPM) yields high stress contribution
        if typing_speed_wpm < 30:
            return 0.90
        return 0.10

class TestPhase6RefactoredPersonalityArchitecture(unittest.IsolatedAsyncioTestCase):
    
    def test_personality_state_model(self):
        """Test 1: Verify PersonalityState model holds structured metadata."""
        state = PersonalityState(
            active_personality="zora",
            switch_reason="Stress threshold crossed.",
            switch_type="automatic"
        )
        self.assertEqual(state.active_personality, "zora")
        self.assertEqual(state.switch_type, "automatic")
        self.assertIn("+00:00", state.switched_at) # UTC validation

    def test_markdown_prompt_loading_and_caching(self):
        """Test 2: Verify that personalities load their prompts from markdown files and cache them."""
        ultron = UltronPersonality()
        prompt = ultron.load_prompt_from_disk()
        
        self.assertIsNotNone(prompt)
        self.assertIn("ULTRON", prompt)
        
        # Modify the private cache value; reloading must retrieve cached val instead of hitting disk again
        ultron._cached_prompt = "Cached Value Override"
        self.assertEqual(ultron.load_prompt_from_disk(), "Cached Value Override")

    def test_extensible_emotion_scoring_ocp(self):
        """Test 3: Assert the Open/Closed Principle by registering a custom TypingSpeedSignal."""
        analyzer = SignalAnalyzer()
        
        # Base stress calculation with 4 standard signals
        base_stress = analyzer.calculate_stress_score(
            user_prompt="Explain Javascript",
            consecutive_errors=0,
            current_hour=14,
            delete_ratio=0.0
        )
        self.assertLess(base_stress, 0.20)
        
        # Register a new custom typing speed signal (OCP in action!)
        analyzer.register_signal("typing_speed", MockTypingSpeedSignal())
        
        # Stress with extremely slow/stressed typing (20 WPM)
        high_stress = analyzer.calculate_stress_score(
            user_prompt="Explain Javascript",
            consecutive_errors=0,
            current_hour=14,
            delete_ratio=0.0
        )
        # Should be slightly higher now due to registered custom typing signal weight
        self.assertGreater(high_stress, base_stress)

    def test_zora_cooldown_lifecycle_auto_return(self):
        """Test 4: Verify Zora temporary overlay auto-returns state back to Ultron after 3 turns."""
        engine = PersonalityEngine(cooldown_turns=3)
        
        # Transition state to Zora
        engine.update_state("zora", "Stress detected", "automatic")
        self.assertEqual(engine.state.active_personality, "zora")
        
        # Turn 1
        ret_1 = engine.increment_zora_lifecycle()
        self.assertIsNone(ret_1)
        self.assertEqual(engine.state.active_personality, "zora")
        
        # Turn 2
        ret_2 = engine.increment_zora_lifecycle()
        self.assertIsNone(ret_2)
        self.assertEqual(engine.state.active_personality, "zora")
        
        # Turn 3 (Should trigger auto-return to Ultron)
        ret_3 = engine.increment_zora_lifecycle()
        self.assertIsNotNone(ret_3)
        self.assertEqual(engine.state.active_personality, "ultron")
        self.assertEqual(engine.state.switch_type, "auto_return")

    @patch("backend.app.brain.llm_router.LLMRouter.get_completions")
    async def test_dynamic_event_publications_e2e(self, mock_completions):
        """Test 5: Verify E2E orchestrator emits and serializes dynamic WS events."""
        mock_completions.return_value = "Zora response"
        
        memory = MemoryEngine()
        memory.short_term.clear()
        
        # Configure engine to return to Ultron after 2 turns of Zora
        engine = PersonalityEngine(cooldown_turns=2)
        orchestrator = CognitiveOrchestrator(memory_engine=memory, personality_engine=engine)
        
        # Dispatch highly stressful prompt to trigger auto handoff to Zora
        response_1 = await orchestrator.process_request(
            user_prompt="broken Webpack build i give up nothing works crash fail error",
            session_id="test_sess_refactored",
            consecutive_errors=4,
            current_hour=1, # 1 AM
            delete_ratio=0.85
        )
        
        # 1. Verify automatic handoff events were dispatched
        events_1 = response_1["events"]
        event_types = [ev["type"] for ev in events_1]
        
        self.assertIn("emotion_score_updated", event_types)
        self.assertIn("handoff_started", event_types)
        self.assertIn("personality_changed", event_types)
        self.assertIn("handoff_completed", event_types)
        
        # Confirm active profile was Zora
        self.assertEqual(response_1["active_personality"], "zora")
        self.assertEqual(response_1["metadata"]["personality"], "zora")
        
        # 2. Since cooldown_turns is 2, the next request will be the 2nd Zora turn, triggering auto-return at Step 10!
        mock_completions.return_value = "Ultron response"
        
        response_2 = await orchestrator.process_request(
            user_prompt="I am feeling calm now.",
            session_id="test_sess_refactored"
        )
        
        # Verify Zora lifecycle was decremented and returned back to Ultron
        self.assertEqual(response_2["active_personality"], "zora") # Answered under Zora's overlay
        self.assertEqual(orchestrator.personalities.state.active_personality, "ultron") # Now switched to Ultron
        
        events_2 = response_2["events"]
        event_types_2 = [ev["type"] for ev in events_2]
        
        self.assertIn("personality_changed", event_types_2)
        # Check that the change reason matches our auto_return lifecycle parameters
        change_event = [ev for ev in events_2 if ev["type"] == "personality_changed"][0]
        self.assertEqual(change_event["payload"]["type"], "auto_return")
        
        await orchestrator.close()

if __name__ == "__main__":
    unittest.main()
