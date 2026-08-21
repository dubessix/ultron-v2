"""Regression tests for provider/model/cache/key-state hardening."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import unittest

import httpx

from backend.app.brain.api_key_manager import APIKeyCoolingError, APIKeyManager
from backend.app.brain.llm_router import LLMRouter
from backend.app.brain.model_config import get_all_models, validate_model_config
from backend.app.brain.smart_cache import SmartCache
from backend.app.memory.vector_store import VectorStore, _lazy_numpy


class TestModelConfiguration(unittest.TestCase):
    def test_all_models_are_configurable_and_valid(self):
        result = validate_model_config()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(
            result["models"]["nvidia"],
            "nvidia/nemotron-3-ultra-550b-a55b",
        )
        self.assertEqual(
            set(get_all_models()),
            {"groq", "gemini", "nvidia", "embedding", "embedding_dims"},
        )


class TestProviderAwareCache(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = APIKeyManager()
        self.manager._keys = {
            "groq": [{"key": "g-test", "state": "ACTIVE"}],
            "gemini": [],
            "nvidia": [{"key": "n-test", "state": "ACTIVE"}],
        }
        self.router = LLMRouter(
            key_manager=self.manager,
            cache=SmartCache(max_items=20, expiry_hours=1),
        )
        self.router.cache.clear()

    async def asyncTearDown(self):
        await self.router.close()

    async def test_same_prompt_cannot_cross_provider_cache(self):
        async def groq(*_args):
            return "GROQ_RESULT"

        async def nvidia(*_args):
            return "NVIDIA_RESULT"

        self.router._execute_groq_pipeline = groq
        self.router._execute_nvidia_pipeline = nvidia

        first = await self.router.get_completions("system", "same", provider_preference="groq")
        second = await self.router.get_completions("system", "same", provider_preference="nvidia")

        self.assertEqual(first, "GROQ_RESULT")
        self.assertEqual(second, "NVIDIA_RESULT")
        self.assertEqual(self.router.get_route_metadata()["provider"], "nvidia")

    async def test_offline_unavailable_state_is_never_cached_over_a_later_real_provider(self):
        self.manager._keys = {"groq": [], "gemini": [], "nvidia": []}
        offline = await self.router.get_completions("system", "probe", provider_preference="groq")
        self.assertTrue(offline.startswith("[Offline]"))
        self.assertEqual(len(self.router.cache._cache), 0)

        self.manager._keys["groq"] = [{"key": "g-real", "state": "ACTIVE"}]

        async def groq(*_args):
            return "REAL_RESULT"

        self.router._execute_groq_pipeline = groq
        real = await self.router.get_completions("system", "probe", provider_preference="groq")
        self.assertEqual(real, "REAL_RESULT")

    def test_model_changes_change_cache_identity(self):
        first = self.router._generate_cache_hash("s", "u", 0.7, "groq", "model-a")
        second = self.router._generate_cache_hash("s", "u", 0.7, "groq", "model-b")
        self.assertNotEqual(first, second)


class TestKeyStateSafety(unittest.TestCase):
    def setUp(self):
        self.manager = APIKeyManager()
        self.manager._keys = {
            "groq": [{"key": "only-key", "state": "ACTIVE"}],
            "gemini": [],
            "nvidia": [],
        }

    def test_cooling_key_is_never_force_reused(self):
        self.manager.mark_key_cooling("groq", "only-key", duration_sec=60)
        with self.assertRaises(APIKeyCoolingError):
            self.manager.get_active_key("groq")
        self.assertEqual(self.manager._keys["groq"][0]["state"], "COOLING")

    def _response(self, status: int) -> httpx.Response:
        return httpx.Response(
            status,
            text="provider response",
            request=httpx.Request("POST", "https://provider.invalid/test"),
        )

    def test_temporary_http_failure_cools_but_does_not_fail_key(self):
        router = LLMRouter(key_manager=self.manager, cache=SmartCache(max_items=2))
        try:
            self.assertEqual(
                router._classify_http_failure("groq", "only-key", self._response(503)),
                "retry",
            )
            self.assertEqual(self.manager._keys["groq"][0]["state"], "COOLING")
        finally:
            asyncio.run(router.close())

    def test_auth_failure_marks_key_failed(self):
        router = LLMRouter(key_manager=self.manager, cache=SmartCache(max_items=2))
        try:
            router._classify_http_failure("groq", "only-key", self._response(401))
            self.assertEqual(self.manager._keys["groq"][0]["state"], "FAILED")
        finally:
            asyncio.run(router.close())

    def test_bad_model_request_does_not_mark_key_failed(self):
        router = LLMRouter(key_manager=self.manager, cache=SmartCache(max_items=2))
        try:
            with self.assertRaises(RuntimeError):
                router._classify_http_failure("groq", "only-key", self._response(404))
            self.assertEqual(self.manager._keys["groq"][0]["state"], "ACTIVE")
        finally:
            asyncio.run(router.close())


class TestOfflineEmbeddingDeterminism(unittest.IsolatedAsyncioTestCase):
    async def test_offline_embedding_does_not_mutate_numpy_rng(self):
        manager = APIKeyManager()
        manager._keys = {"groq": [], "gemini": [], "nvidia": []}
        store = VectorStore(key_manager=manager)
        np = _lazy_numpy()

        np.random.seed(12345)
        expected = float(np.random.random())
        np.random.seed(12345)
        await store.generate_embedding("stable offline text")
        actual = float(np.random.random())
        self.assertEqual(actual, expected)

    async def test_offline_embedding_cache_is_bounded(self):
        manager = APIKeyManager()
        manager._keys = {"groq": [], "gemini": [], "nvidia": []}
        store = VectorStore(key_manager=manager)
        store._embedding_cache_limit = 3
        for index in range(10):
            await store.generate_embedding(f"fact {index}")
        self.assertLessEqual(len(store._embedding_cache), 3)

    def test_offline_embedding_is_stable_across_processes(self):
        code = (
            "import asyncio,json; "
            "from backend.app.brain.api_key_manager import APIKeyManager; "
            "from backend.app.memory.vector_store import VectorStore; "
            "m=APIKeyManager(); m._keys={'groq':[],'gemini':[],'nvidia':[]}; "
            "v=asyncio.run(VectorStore(key_manager=m).generate_embedding('cross process')); "
            "print(json.dumps(v[:12]))"
        )
        env = dict(os.environ)
        env["ULTRON_TEST_MODE"] = "1"
        env.pop("ULTRON_TEST_ROOT", None)
        first = subprocess.check_output([sys.executable, "-c", code], text=True, env=env).strip()
        second = subprocess.check_output([sys.executable, "-c", code], text=True, env=env).strip()
        self.assertEqual(json.loads(first), json.loads(second))


if __name__ == "__main__":
    unittest.main()
