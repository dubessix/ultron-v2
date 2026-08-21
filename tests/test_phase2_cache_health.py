"""
Phase 2 regression — cache thread-safety + honest provider/health reporting.

  - SmartCache operations are safe under concurrent access.
  - /api/health reports an honest provider config status (not live reachability).
"""

import threading
import unittest

from fastapi.testclient import TestClient

from backend.app.brain.smart_cache import SmartCache
from backend.app.main import app


class TestCacheThreadSafety(unittest.TestCase):

    def test_concurrent_set_get_does_not_corrupt(self):
        cache = SmartCache(max_items=50)
        errors = []

        def worker(worker_id):
            try:
                for i in range(200):
                    cache.set(f"k{worker_id}_{i}", i)
                    cache.get(f"k{worker_id}_{i}")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertLessEqual(len(cache._cache), 50)  # bounds enforced


class TestHealthProviderStatus(unittest.TestCase):

    def test_health_reports_provider_config_status(self):
        client = TestClient(app)
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("providers", data)
        self.assertEqual(
            set(data["providers"].keys()),
            {"groq", "gemini", "nvidia"},
        )
        for state in data["providers"].values():
            self.assertIn(state, ("configured", "not_configured"))
        self.assertIn("models", data)
        self.assertTrue(data["models"]["valid"])
        self.assertEqual(
            data["models"]["models"]["nvidia"],
            "nvidia/nemotron-3-ultra-550b-a55b",
        )
        self.assertIn("provider_key_states", data)

    def test_provider_status_reports_effective_models_without_live_calls(self):
        client = TestClient(app)
        response = client.get("/api/providers/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["live_checked"])
        self.assertEqual(
            data["providers"]["nvidia"]["model"],
            "nvidia/nemotron-3-ultra-550b-a55b",
        )
        for provider in data["providers"].values():
            self.assertIsNone(provider["reachable"])


if __name__ == "__main__":
    unittest.main()
