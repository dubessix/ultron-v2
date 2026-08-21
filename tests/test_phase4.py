"""
Ultron Unit & Integration Testing Suite — Phase 4 Diagnostics
Tests core intent analyzer categories, confidence heuristics, speed track routing,
and full async Orchestrator pipeline execution under mock LLM clients.
"""

import unittest
from unittest.mock import patch

from backend.app.core.intent_analyzer import IntentAnalyzer
from backend.app.core.confidence_engine import ConfidenceEngine
from backend.app.core.decision_engine import DecisionEngine
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.memory.memory_engine import MemoryEngine

class TestPhase4OrchestratorArchitecture(unittest.IsolatedAsyncioTestCase):
    
    def test_intent_analysis_heuristics(self):
        """Test 1: Verify correct intent classification for various user queries."""
        analyzer = IntentAnalyzer()
        
        self.assertEqual(analyzer.analyze("Hi there, good morning!"), "CONVERSATION")
        self.assertEqual(analyzer.analyze("Explain what a CORS policy error is"), "DEVELOPER_HELP")
        self.assertEqual(analyzer.analyze("i feel so overwhelmed and tired"), "EMOTIONAL")
        self.assertEqual(analyzer.analyze("Compare postgres vs mongodb"), "RESEARCH")
        self.assertEqual(analyzer.analyze("What is the capital of France?"), "EXPLANATION")

    def test_confidence_calculations(self):
        """Test 2: Verify that short/vague prompts drop below 60% confidence."""
        engine = ConfidenceEngine()
        
        # High confidence for detailed query
        self.assertEqual(engine.calculate_confidence("How do I configure Vite with React?", "DEVELOPER_HELP"), 1.0)
        
        # Short dev commands (e.g. "webpack") are now valid — not rejected as vague.
        self.assertGreaterEqual(engine.calculate_confidence("webpack", "DEVELOPER_HELP"), 0.60)
        
        # Extremely low confidence for empty/digit queries
        self.assertLess(engine.calculate_confidence("123", "CONVERSATION"), 0.60)
        self.assertEqual(engine.calculate_confidence("", "CONVERSATION"), 0.0)

    def test_decision_track_routing(self):
        """Test 3: Assert different intents/confidences are mapped to correct speed paths."""
        engine = DecisionEngine()
        
        # Fast path for conversation/explanation
        self.assertEqual(engine.get_speed_track("CONVERSATION", 0.95), "fast")
        self.assertEqual(engine.get_speed_track("EXPLANATION", 1.0), "fast")
        
        # Medium path for developer help / planning
        self.assertEqual(engine.get_speed_track("DEVELOPER_HELP", 1.0), "medium")
        self.assertEqual(engine.get_speed_track("PLANNING", 0.90), "medium")
        
        # Heavy path for research
        self.assertEqual(engine.get_speed_track("RESEARCH", 1.0), "heavy")
        
        # Low confidence forced to heavy path (for clarification handling)
        self.assertEqual(engine.get_speed_track("DEVELOPER_HELP", 0.45), "heavy")

    @patch("backend.app.brain.llm_router.LLMRouter.get_completions")
    async def test_orchestrator_pipeline_execution(self, mock_completions):
        """Test 4: Verify full 7-step async pipeline and low confidence clarification."""
        mock_completions.return_value = "Mocked completions success response"
        
        memory = MemoryEngine()
        memory._buffer_for("test_sess_4").clear()
        
        orchestrator = CognitiveOrchestrator(memory_engine=memory)
        
        # --- Case A: Low Confidence Prompt (Should trigger single clarifying question instantly) ---
        # A genuinely vague input (e.g. "123") scores low -> clarify.
        response_a = await orchestrator.process_request("123", session_id="test_sess_4")
        
        self.assertIn("clarify", response_a["content"])
        self.assertLess(response_a["confidence"], 0.60)
        self.assertEqual(response_a["speed_track"], "heavy")
        
        # Verify clarifying turn was saved to memory history
        self.assertEqual(len(memory.get_session_context("test_sess_4")), 1)
        self.assertEqual(memory.get_session_context("test_sess_4")[0]["user"], "123")
        self.assertIn("clarify", memory.get_session_context("test_sess_4")[0]["ai"])

        # --- Case B: Detailed Prompt (Should execute full pipeline and call router) ---
        response_b = await orchestrator.process_request(
            "Explain the difference between SQL and NoSQL.", 
            session_id="test_sess_4"
        )
        
        self.assertEqual(response_b["content"], "Mocked completions success response")
        self.assertEqual(response_b["intent"], "RESEARCH")
        self.assertEqual(response_b["confidence"], 1.0)
        self.assertEqual(response_b["speed_track"], "heavy")
        self.assertFalse(response_b["cache_skip"]) # General knowledge query

        # Verify successful turn was saved to memory history
        self.assertEqual(len(memory.get_session_context("test_sess_4")), 2)
        self.assertEqual(memory.get_session_context("test_sess_4")[1]["user"], "Explain the difference between SQL and NoSQL.")
        self.assertEqual(memory.get_session_context("test_sess_4")[1]["ai"], "Mocked completions success response")
        
        await orchestrator.close()

if __name__ == "__main__":
    unittest.main()
