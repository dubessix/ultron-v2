"""
Ultron Unit & Integration Testing Suite — Phase 3 Diagnostics
Tests Short-Term deque pruning limits, Persistent SQLite key-value writing/reading,
and Decoupled Heuristic Cache Policy rules.
"""

import unittest
from backend.app.memory.short_term import ShortTermMemory
from backend.app.memory.persistent_memory import PersistentMemory
from backend.app.brain.cache_policy import HeuristicKeywordCachePolicy

class TestPhase3MemoryArchitecture(unittest.TestCase):
    
    def test_short_term_memory_limits(self):
        """Test 1: Verify short-term RAM sliding-window prunes old items past 50 entries."""
        mem = ShortTermMemory(limit=50)
        
        # Add 50 turns
        for i in range(1, 51):
            mem.add_turn(f"user_msg_{i}", f"ai_resp_{i}")
            
        history = mem.get_context_history()
        self.assertEqual(len(history), 50)
        self.assertEqual(history[0]["user"], "user_msg_1")
        self.assertEqual(history[-1]["user"], "user_msg_50")
        
        # Add the 51st turn; must evict the 1st turn ('user_msg_1')
        mem.add_turn("user_msg_51", "ai_resp_51")
        
        new_history = mem.get_context_history()
        self.assertEqual(len(new_history), 50)
        self.assertEqual(new_history[0]["user"], "user_msg_2") # Eviction verified
        self.assertEqual(new_history[-1]["user"], "user_msg_51")

    def test_persistent_sqlite_metadata(self):
        """Test 2: Verify SQLite permanent read-write storage across session restarts."""
        mem = PersistentMemory()
        mem.clear()
        
        # Set username parameter
        mem.set("username", "Debjeet")
        self.assertEqual(mem.get("username"), "Debjeet")
        
        # Overwrite with different preference
        mem.set("username", "Debjeet_Linux_Ubuntu")
        self.assertEqual(mem.get("username"), "Debjeet_Linux_Ubuntu")
        
        # Instantiate a second parallel connector; must retrieve matching state
        new_connector = PersistentMemory()
        self.assertEqual(new_connector.get("username"), "Debjeet_Linux_Ubuntu")
        
        # Prune key
        new_connector.delete("username")
        self.assertIsNone(new_connector.get("username"))

    def test_heuristic_cache_policy(self):
        """Test 3: Assert Decoupled Cache Policy correctly classifies dynamic personal states."""
        policy = HeuristicKeywordCachePolicy()
        
        # Stateful, dynamic personal statements (Must bypass cache -> should_bypass_cache=True)
        self.assertTrue(policy.should_bypass_cache("sys", "What is my name?"))
        self.assertTrue(policy.should_bypass_cache("sys", "Could you show my todo list?"))
        self.assertTrue(policy.should_bypass_cache("sys", "Tell me what my project goals are"))
        self.assertTrue(policy.should_bypass_cache("sys", "Run compile command on terminal"))
        self.assertTrue(policy.should_bypass_cache("sys", "What did we commit to git yesterday?"))
        
        # Stateless, general theoretical queries (Allowed to check cache -> should_bypass_cache=False)
        self.assertFalse(policy.should_bypass_cache("sys", "What is Javascript?"))
        self.assertFalse(policy.should_bypass_cache("sys", "Compare postgres vs sqlite"))
        self.assertFalse(policy.should_bypass_cache("sys", "How does a WebSocket connection operate?"))

if __name__ == "__main__":
    unittest.main()
