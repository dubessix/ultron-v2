"""
Phase 2 regression — model/provider configuration.

Ensures retired models are gone and the brain is config-driven:
  - gemini chat uses a current model (default gemini-3.5-flash), NOT the retired
    gemini-1.5-flash.
  - embeddings use gemini-embedding-001 with outputDimensionality=768 (matches
    stored 768-dim vectors) — NOT the retired text-embedding-004.
  - the NVIDIA model ID carries no `:free` suffix (an OpenRouter convention not
    valid on NVIDIA's native build endpoint).
  - env overrides are honored.
"""

import asyncio
import os
import unittest
from unittest.mock import patch

from backend.app.brain.model_config import get_model, get_embedding_dimensions
from backend.app.memory.vector_store import VectorStore


def _run(coro):
    return asyncio.run(coro)


class TestModelConfig(unittest.TestCase):

    _MODEL_ENV_VARS = (
        "GROQ_CHAT_MODEL", "GEMINI_CHAT_MODEL", "NVIDIA_CHAT_MODEL",
        "GEMINI_EMBEDDING_MODEL", "GEMINI_EMBEDDING_DIMS",
    )

    def setUp(self):
        for var in self._MODEL_ENV_VARS:
            os.environ.pop(var, None)

    def tearDown(self):
        for var in self._MODEL_ENV_VARS:
            os.environ.pop(var, None)

    def test_no_retired_gemini_model(self):
        self.assertEqual(get_model("gemini"), "gemini-3.5-flash")
        self.assertNotIn("1.5", get_model("gemini"))

    def test_embedding_model_and_dims(self):
        self.assertEqual(get_model("embedding"), "gemini-embedding-001")
        self.assertEqual(get_embedding_dimensions(), 768)

    def test_nvidia_exact_native_model_id(self):
        self.assertEqual(
            get_model("nvidia"),
            "nvidia/nemotron-3-ultra-550b-a55b",
        )
        self.assertNotIn(":free", get_model("nvidia"))
        self.assertNotIn("nvidia/nvidia/", get_model("nvidia"))

    def test_env_override_honored(self):
        os.environ["GEMINI_CHAT_MODEL"] = "gemini-3.1-flash-lite"
        os.environ["GEMINI_EMBEDDING_DIMS"] = "512"
        self.assertEqual(get_model("gemini"), "gemini-3.1-flash-lite")
        self.assertEqual(get_embedding_dimensions(), 512)


class TestEmbeddingPayload(unittest.TestCase):

    def test_payload_uses_new_model_with_output_dimensionality(self):
        from backend.app.brain.api_key_manager import APIKeyManager

        class FakeResp:
            status_code = 200
            def json(self):
                return {"embedding": {"values": [0.1] * 768}}

        manager = APIKeyManager()
        manager._keys["gemini"] = [{"key": "AIza_TEST", "state": "ACTIVE"}]
        store = VectorStore(key_manager=manager)
        captured = {}

        async def fake_post(*args, **kwargs):
            captured["url"] = args[1] if len(args) > 1 else kwargs.get("url")
            captured["json"] = kwargs.get("json")
            return FakeResp()

        async def main():
            with patch("httpx.AsyncClient.post", fake_post):
                vec = await store.generate_embedding("hello")
            return vec

        vec = _run(main())
        self.assertIn("gemini-embedding-001", captured["url"])
        self.assertNotIn("text-embedding-004", captured["url"])
        self.assertEqual(captured["json"]["outputDimensionality"], 768)
        self.assertEqual(len(vec), 768)


if __name__ == "__main__":
    unittest.main()
