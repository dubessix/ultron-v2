"""Jarvis Phase 1 contract: a brain that is fresh, forgiving and tool-shaped."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.app.brain.cache_policy import HeuristicKeywordCachePolicy
from backend.app.brain.llm_router import LLMRouter
from backend.app.brain.model_config import get_model


class _Resp:
    def __init__(self, body: dict):
        self.status_code = 200
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class _Capture:
    """Stands in for httpx.AsyncClient.post and records the JSON payload."""

    def __init__(self, body: dict):
        self.body = body
        self.payloads: list[dict] = []

    async def __call__(self, url, **kwargs):
        self.payloads.append(kwargs.get("json") or {})
        return _Resp(self.body)


OPENAI_OK = {"choices": [{"message": {"content": "ok", "tool_calls": []}}]}
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
TOOL = {
    "tool_id": "weather_tool",
    "description": "Weather",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
}


class TestLiveDataNeverCached(unittest.TestCase):
    def test_live_world_prompts_bypass_cache(self):
        policy = HeuristicKeywordCachePolicy()
        for prompt in (
            "what's the weather in Kolkata",
            "latest AI news",
            "what time is it",
            "bitcoin price now",
            "show my cpu usage",
            "play some music",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(policy.should_bypass_cache("s", prompt))

    def test_timeless_knowledge_still_cacheable(self):
        policy = HeuristicKeywordCachePolicy()
        for prompt in ("What is Javascript?", "Explain recursion", "Compare postgres vs sqlite"):
            with self.subTest(prompt=prompt):
                self.assertFalse(policy.should_bypass_cache("s", prompt))


class TestRouterPayloads(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.router = LLMRouter()
        self.router.key_manager._keys = {
            "groq": [{"key": "g-test", "state": "ACTIVE"}],
            "gemini": [{"key": "m-test", "state": "ACTIVE"}],
            "nvidia": [{"key": "n-test", "state": "ACTIVE"}],
        }

    async def asyncTearDown(self):
        await self.router.close()

    def test_default_groq_model_is_the_strong_tool_caller(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("GROQ_CHAT_MODEL", None)
            self.assertEqual(get_model("groq"), "openai/gpt-oss-120b")

    async def test_groq_native_is_sequential_low_reasoning_and_roomy(self):
        cap = _Capture(OPENAI_OK)
        with patch.object(self.router.client, "post", cap):
            await self.router._execute_openai_native_tools("groq", "sys", "hi", [TOOL], [], 0.3)
        payload = cap.payloads[-1]
        self.assertIs(payload["parallel_tool_calls"], False)
        self.assertEqual(payload["max_tokens"], 2048)
        if payload["model"].startswith("openai/gpt-oss"):
            self.assertEqual(payload["reasoning_effort"], "low")

    async def test_plain_paths_have_room_to_answer(self):
        cap = _Capture(OPENAI_OK)
        with patch.object(self.router.client, "post", cap):
            await self.router._execute_groq_pipeline("sys", "hi", 0.5)
            await self.router._execute_nvidia_pipeline("sys", "hi", 0.5)
        self.assertTrue(all(p["max_tokens"] >= 2048 for p in cap.payloads))

    async def test_gemini_plain_uses_real_system_instruction(self):
        cap = _Capture(GEMINI_OK)
        with patch.object(self.router.client, "post", cap):
            await self.router._execute_gemini_pipeline("BE JARVIS", "hello", 0.5)
        payload = cap.payloads[-1]
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "BE JARVIS")
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "hello")
        self.assertGreaterEqual(payload["generationConfig"]["maxOutputTokens"], 2048)

    def test_gemini_function_response_pairs_real_call_id_only(self):
        conv = [
            {"role": "tool", "name": "weather_tool", "tool_call_id": "abc123", "content": "{}"},
            {"role": "tool", "name": "system_metrics", "tool_call_id": "gemini-call-1", "content": "{}"},
        ]
        contents = LLMRouter._gemini_contents("q", conv)
        parts = contents[-1]["parts"]
        self.assertEqual(parts[0]["functionResponse"]["id"], "abc123")
        self.assertNotIn("id", parts[1]["functionResponse"])

    async def test_rejected_model_expires_after_ttl(self):
        model = get_model("groq")
        self.router._rejected_models[("groq", model)] = "HTTP 404 blip"
        self.assertEqual(self.router._active_rejection("groq", model), "HTTP 404 blip")
        self.router._rejected_at[("groq", model)] -= LLMRouter.REJECTION_TTL_SECONDS + 1
        self.assertIsNone(self.router._active_rejection("groq", model))
        self.assertNotIn(("groq", model), self.router._rejected_models)


if __name__ == "__main__":
    unittest.main()
