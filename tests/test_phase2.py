"""
Ultron Unit & Integration Testing Suite — Phase 2 Diagnostics
Tests local LRU-TTL caching operations, JSON persistence, key manager state changes,
and automatic rate-limit key rotations & Gemini failovers.
"""

import unittest
import os
import httpx
from unittest.mock import MagicMock, patch

from backend.app.brain.api_key_manager import APIKeyManager
from backend.app.brain.smart_cache import SmartCache, CACHE_PATH

from backend.app.brain.llm_router import LLMRouter

class TestPhase2BrainArchitecture(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        """Configure test-specific environment directories."""
        # Clean local cache directory to prevent state bleeding
        if CACHE_PATH.exists():
            try:
                os.remove(CACHE_PATH)
            except OSError:
                pass
                
    def tearDown(self):
        if CACHE_PATH.exists():
            try:
                os.remove(CACHE_PATH)
            except OSError:
                pass

    def test_smart_cache_lru_and_ttl(self):
        """Test 1: Verify LRU eviction bounds and Time-To-Live (TTL) checks."""
        # Set max_items to 3, TTL to 0.1 hours (360 seconds)
        cache = SmartCache(max_items=3, expiry_hours=0.1)
        
        cache.set("key1", "val1")
        cache.set("key2", "val2")
        cache.set("key3", "val3")
        
        # Test item retrieval
        self.assertEqual(cache.get("key1"), "val1")
        
        # Adding a 4th item must evict 'key2' because key1 was recently accessed via get()
        cache.set("key4", "val4")
        self.assertIsNone(cache.get("key2"))
        self.assertEqual(cache.get("key1"), "val1")
        self.assertEqual(cache.get("key3"), "val3")
        self.assertEqual(cache.get("key4"), "val4")

    def test_smart_cache_json_persistence(self):
        """Test 2: Verify local cache disk serialization and recovery on restart."""
        cache = SmartCache(max_items=5)
        cache.set("persist_key", "persist_value")
        
        # Save state
        cache.save_to_disk()
        self.assertTrue(CACHE_PATH.exists())
        
        # Boot a new cache instance; must restore row automatically
        new_cache = SmartCache(max_items=5)
        self.assertEqual(new_cache.get("persist_key"), "persist_value")

    def test_key_manager_state_transitions(self):
        """Test 3: Test round-robin key selection and cooling/failed transitions."""
        manager = APIKeyManager()
        
        # Override key structures with test mocks
        manager._keys["groq"] = [
            {"key": "mock_groq_1", "state": "ACTIVE"},
            {"key": "mock_groq_2", "state": "ACTIVE"},
            {"key": "mock_groq_3", "state": "ACTIVE"}
        ]
        
        # First round-robin pass
        k1 = manager.get_active_key("groq")
        k2 = manager.get_active_key("groq")
        k3 = manager.get_active_key("groq")
        
        self.assertEqual(k1, "mock_groq_1")
        self.assertEqual(k2, "mock_groq_2")
        self.assertEqual(k3, "mock_groq_3")
        
        # Mark key 1 as cooling
        manager.mark_key_cooling("groq", "mock_groq_1", duration_sec=5)
        
        # Next query must automatically bypass key 1 and return key 2
        next_k = manager.get_active_key("groq")
        self.assertEqual(next_k, "mock_groq_2")
        
        # Mark key 2 as failed
        manager.mark_key_failed("groq", "mock_groq_2")
        
        # Next query must return active key 3
        next_k_2 = manager.get_active_key("groq")
        self.assertEqual(next_k_2, "mock_groq_3")

    @patch("httpx.AsyncClient.post")
    async def test_llm_router_failover_pipeline(self, mock_post):
        """Test 4: Verify 429 Rate Limit rotation and automatic Gemini failover."""
        # Setup clean key lists
        manager = APIKeyManager()
        manager._keys["groq"] = [
            {"key": "mock_g_1", "state": "ACTIVE"},
            {"key": "mock_g_2", "state": "ACTIVE"}
        ]
        manager._keys["gemini"] = [
            {"key": "mock_gem_1", "state": "ACTIVE"}
        ]
        
        cache = SmartCache(max_items=5)
        router = LLMRouter(key_manager=manager, cache=cache)
        
        # Define mock responses
        # Attempt 1 (Groq Key 1): 429 -> temporary cooling.
        # Attempt 2 (Groq Key 2): 500 -> temporary cooling.
        # Both keys are then cooling, so Groq is not force-reused and the router
        # cascades to Gemini, which succeeds.
        mock_response_429 = MagicMock(spec=httpx.Response)
        mock_response_429.status_code = 429
        
        mock_response_500 = MagicMock(spec=httpx.Response)
        mock_response_500.status_code = 500
        
        mock_response_success = MagicMock(spec=httpx.Response)
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Gemini Fallback Complete"}]
                }
            }]
        }
        
        # Set mock side effects
        mock_post.side_effect = [
            mock_response_429,
            mock_response_500,
            mock_response_success,
        ]
        
        response = await router.get_completions(
            system_prompt="sys",
            user_prompt="trigger cascade",
            provider_preference="groq"
        )
        
        # Assertions
        self.assertEqual(response, "Gemini Fallback Complete")
        self.assertEqual(manager._keys["groq"][0]["state"], "COOLING")
        self.assertEqual(manager._keys["groq"][1]["state"], "COOLING")
        self.assertEqual(manager._keys["gemini"][0]["state"], "ACTIVE")
        
        await router.close()

if __name__ == "__main__":
    unittest.main()
