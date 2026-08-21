"""
Ultron Unit & Integration Testing Suite — Phase 5 Diagnostics
Tests NumPy Cosine Similarity math, duplicate write prevention thresholds,
Memory Gate prompt filtering, and Episodic/Semantic/Emotional async operations.
"""

import unittest
import numpy as np
import uuid

from backend.app.memory.vector_store import VectorStore
from backend.app.memory.memory_gate import MemoryGate
from backend.app.memory.episodic_memory import EpisodicMemory
from backend.app.memory.semantic_memory import SemanticMemory
from backend.app.memory.emotional_memory import EmotionalMemory
from backend.app.database.db import get_db_connection

class TestPhase5VectorMemoryArchitecture(unittest.IsolatedAsyncioTestCase):
    
    @classmethod
    def setUpClass(cls):
        """Prepare clean SQLite schemas on setup."""
        # Wipes existing records to prevent testing state bleed
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS vector_memories;")
            conn.commit()

    def test_numpy_cosine_similarity(self):
        """Test 1: Verify local Cosine Similarity dot calculations."""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [1.0, 0.0, 0.0]  # Identical (Cosine = 1.0)
        vec_c = [0.0, 1.0, 0.0]  # Orthogonal (Cosine = 0.0)
        vec_d = [-1.0, 0.0, 0.0] # Opposite (Cosine = -1.0)
        
        # Test similarities on standalone calculations
        store = VectorStore()
        # Use `store`: confirm it loads a sane deduplication threshold (0 < t <= 1).
        self.assertTrue(0 < store.duplicate_threshold <= 1.0)
        
        # Override table search directly to test calculations
        target = np.array(vec_a, dtype=np.float32)
        norm_t = np.linalg.norm(target)
        
        sim_b = float(np.dot(target, np.array(vec_b, dtype=np.float32)) / (norm_t * np.linalg.norm(vec_b)))
        sim_c = float(np.dot(target, np.array(vec_c, dtype=np.float32)) / (norm_t * np.linalg.norm(vec_c)))
        sim_d = float(np.dot(target, np.array(vec_d, dtype=np.float32)) / (norm_t * np.linalg.norm(vec_d)))
        
        self.assertAlmostEqual(sim_b, 1.0, places=5)
        self.assertAlmostEqual(sim_c, 0.0, places=5)
        self.assertAlmostEqual(sim_d, -1.0, places=5)

    def test_duplicate_write_abortions(self):
        """Test 2: Assert duplicate writes are blocked when similarity exceeds 0.95."""
        store = VectorStore()
        
        msg_id_1 = str(uuid.uuid4())
        msg_id_2 = str(uuid.uuid4())
        
        content = "Fixed CORS policy bug in routers."
        embedding = [0.1] * 768 # Static flat embedding
        
        # Save first vector memory (successful write)
        write_1 = store.save_vector_memory(msg_id_1, "episodic", content, embedding)
        self.assertTrue(write_1)
        
        # Save exact duplicate vector memory; must return False (abort write)
        write_2 = store.save_vector_memory(msg_id_2, "episodic", content, embedding)
        self.assertFalse(write_2)

    def test_memory_gate_filtering(self):
        """Test 3: Assert Memory Gate skips low-density queries (Greetings/Thanks)."""
        gate = MemoryGate()
        
        # Low-density queries (should return False)
        self.assertFalse(gate.is_semantically_dense("hi"))
        self.assertFalse(gate.is_semantically_dense("hello!"))
        self.assertFalse(gate.is_semantically_dense("thank you."))
        self.assertFalse(gate.is_semantically_dense(""))
        
        # High-density prompts (should return True)
        self.assertTrue(gate.is_semantically_dense("What is Webpack loader error?"))
        self.assertTrue(gate.is_semantically_dense("React Query manages client status"))

    async def test_subclass_vector_operations(self):
        """Test 4: Verify Episodic, Semantic, and Emotional memory layer operations."""
        store = VectorStore()
        episodic = EpisodicMemory(store)
        semantic = SemanticMemory(store)
        emotional = EmotionalMemory(store)
        
        # Clear existing tables to ensure clean state
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vector_memories;")
            conn.commit()
            
        # Test 4.1: Episodic memory write and recall
        ev_success = await episodic.record_event("User deployed beta server webhook.")
        self.assertTrue(ev_success)
        
        events = await episodic.recall_related_events("beta deployment")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["content"], "User deployed beta server webhook.")
        
        # Test 4.2: Semantic memory write and recall
        sem_success = await semantic.learn_concept("JWT is used for stateless auth tokens.")
        self.assertTrue(sem_success)
        
        concepts = await semantic.recall_related_concepts("authentication token")
        self.assertEqual(len(concepts), 1)
        self.assertEqual(concepts[0]["content"], "JWT is used for stateless auth tokens.")
        
        # Test 4.3: Emotional memory write and recall
        em_success = await emotional.log_emotional_record("User feels exhausted late at night.")
        self.assertTrue(em_success)
        
        emotions = await emotional.recall_stress_triggers("stress level")
        self.assertEqual(len(emotions), 1)
        self.assertEqual(emotions[0]["content"], "User feels exhausted late at night.")

if __name__ == "__main__":
    unittest.main()
