"""V2 Step E2/E3: retired models switch by themselves; rate limits wait, bounded."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.app.brain import model_fallback as mf
from backend.app.brain.api_key_manager import APIKeyManager
from backend.app.brain.llm_router import LLMRouter
from backend.app.brain.model_config import get_model

GROQ_GONE = (
    '{"error":{"message":"The model `openai/gpt-oss-120b` has been decommissioned and is no '
    'longer supported. Please refer to https://console.groq.com/docs/deprecations",'
    '"type":"invalid_request_error","code":"model_decommissioned"}}'
)
GEMINI_GONE = (
    '{"error":{"code":404,"message":"models/gemini-3.5-flash is not found for API version '
    'v1beta, or is not supported for generateContent.","status":"NOT_FOUND"}}'
)
TOOL_CALL = {"choices": [{"message": {"content": "Done.", "tool_calls": []}}]}
TOOLS = [{"tool_id": "file_read", "description": "Read.", "permission_level": 0,
          "input_schema": {"type": "object", "properties": {"filepath": {"type": "string"}}}}]


def response(status, body=None, text=None, headers=None):
    request = httpx.Request("POST", "https://provider.invalid")
    if text is not None:
        return httpx.Response(status, text=text, headers=headers or {}, request=request)
    return httpx.Response(status, json=body or {}, headers=headers or {}, request=request)


def router_with(provider="groq", keys=1):
    manager = APIKeyManager()
    manager._keys = {name: [] for name in manager.PROVIDERS}
    manager._keys[provider] = [{"key": f"real-{provider}-key-{i}", "state": "ACTIVE"} for i in range(keys)]
    return LLMRouter(key_manager=manager)


class Clean(unittest.TestCase):
    def setUp(self):
        mf.reset_for_tests(clear_file=True)
        self.addCleanup(mf.reset_for_tests, True)
        for name in ("GROQ_CHAT_MODEL", "GEMINI_CHAT_MODEL"):
            if name in os.environ:
                patcher = patch.dict(os.environ, {name: ""})
                patcher.start()
                self.addCleanup(patcher.stop)


class TestKnowsWhenAModelIsGone(Clean):
    def test_only_model_errors_count(self):
        self.assertTrue(mf.is_model_gone_error(400, GROQ_GONE))
        self.assertTrue(mf.is_model_gone_error(404, GEMINI_GONE))
        self.assertTrue(mf.is_model_gone_error(404, '{"error":{"code":"model_not_found","message":'
                                                    '"The model `x` does not exist"}}'))
        self.assertFalse(mf.is_model_gone_error(400, '{"error":"tool call validation failed"}'))
        self.assertFalse(mf.is_model_gone_error(429, GROQ_GONE))
        self.assertFalse(mf.is_model_gone_error(500, GROQ_GONE))

    def test_next_model_in_the_list_and_restart_remembers(self):
        self.assertEqual(get_model("groq"), "openai/gpt-oss-120b")
        nxt = mf.mark_gone("groq", "openai/gpt-oss-120b", ["openai/gpt-oss-120b"])
        self.assertEqual(nxt, "openai/gpt-oss-20b")
        self.assertEqual(get_model("groq"), "openai/gpt-oss-20b")
        mf.reset_for_tests()                     # "restart": reload from the state file
        self.assertEqual(get_model("groq"), "openai/gpt-oss-20b")

    def test_owner_override_comes_first_and_falls_back_when_retired(self):
        with patch.dict(os.environ, {"GROQ_CHAT_MODEL": "qwen/qwen3.8-27b"}):
            self.assertEqual(get_model("groq"), "qwen/qwen3.8-27b")
            mf.mark_gone("groq", "qwen/qwen3.8-27b", ["qwen/qwen3.8-27b"])
            self.assertEqual(get_model("groq"), "openai/gpt-oss-120b")

    def test_a_gone_mark_expires_so_a_wrong_guess_is_never_forever(self):
        mf.mark_gone("groq", "openai/gpt-oss-120b")
        with patch.object(mf.time, "time", return_value=mf.time.time() + mf.GONE_TTL_SECONDS + 5):
            self.assertEqual(get_model("groq"), "openai/gpt-oss-120b")

    def test_he_tells_you_once_in_plain_words(self):
        mf.mark_gone("groq", "openai/gpt-oss-120b")
        mf.mark_gone("groq", "openai/gpt-oss-120b")  # same model again: no second notice
        note = mf.pop_notice()
        self.assertIn("Groq stopped the model openai gpt oss 120b", note)
        self.assertIn("switched to openai gpt oss 20b", note)
        self.assertNotIn("/", note)
        self.assertEqual(mf.pop_notice(), "")


class TestRouterSwitchesByItself(Clean, unittest.IsolatedAsyncioTestCase):
    async def test_retired_model_switches_in_the_same_order(self):
        router = router_with("groq")
        router.client.post = AsyncMock(side_effect=[response(400, text=GROQ_GONE), response(200, TOOL_CALL)])
        try:
            result = await router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
        finally:
            await router.close()
        models = [call.kwargs["json"]["model"] for call in router.client.post.await_args_list]
        self.assertEqual(models, ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
        self.assertEqual(result["model"], "openai/gpt-oss-20b")
        self.assertEqual(result["content"], "Done.")

    async def test_whole_list_gone_asks_the_provider_once_a_day(self):
        for model in mf.FALLBACK_CHAINS["groq"]:
            mf.mark_gone("groq", model)
        router = router_with("groq")
        listing = {"data": [{"id": "whisper-large-v3"}, {"id": "llama-prompt-guard"},
                            {"id": "openai/gpt-oss-safeguard-20b"}, {"id": "newco/gpt-oss-2-200b"},
                            {"id": "qwen/qwen4-30b"}]}
        router.client.get = AsyncMock(return_value=response(200, listing))
        router.client.post = AsyncMock(return_value=response(200, TOOL_CALL))
        try:
            await router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
            await router.get_completions_with_tools("sys", "again", TOOLS, provider_lock="groq")
        finally:
            await router.close()
        self.assertEqual(router.client.get.await_count, 1)   # once a day, not every order
        self.assertEqual(router.client.post.await_args.kwargs["json"]["model"], "newco/gpt-oss-2-200b")

    async def test_gemini_retired_model_switches_too(self):
        router = router_with("gemini")
        ok = {"candidates": [{"content": {"parts": [{"text": "Hi."}]}}]}
        router.client.post = AsyncMock(side_effect=[response(404, text=GEMINI_GONE), response(200, ok)])
        try:
            result = await router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="gemini")
        finally:
            await router.close()
        urls = [call.args[0] for call in router.client.post.await_args_list]
        self.assertIn("gemini-3.5-flash:", urls[0])
        self.assertIn("gemini-3.6-flash:", urls[1])
        self.assertEqual(result["model"], "gemini-3.6-flash")


class TestPicksFromTodaysList(Clean):
    def test_gemini_newest_flash_and_embedding(self):
        listing = {"models": [
            {"name": "models/gemini-4.1-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-4.2-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-4.2-flash-tts", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-4.2-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-embedding-002", "supportedGenerationMethods": ["embedContent"]},
        ]}
        self.assertEqual(mf.pick_best("gemini", listing), "gemini-4.2-flash")
        self.assertEqual(mf.pick_best("embedding", listing), "gemini-embedding-002")
        self.assertIsNone(mf.pick_best("groq", {"data": []}))
        self.assertIsNone(mf.pick_best("groq", "garbage"))


class FakeClock:
    """Key cooldowns use time.time(); the router's waits use asyncio.sleep."""

    def __init__(self):
        self.now = 1_000_000.0
        self.slept = 0.0

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        self.slept += seconds


class TestRateLimitsWaitThenFinish(Clean, unittest.IsolatedAsyncioTestCase):
    async def test_thirty_rate_limits_no_crash_every_order_finishes(self):
        clock = FakeClock()
        router = router_with("groq", keys=3)
        limited = lambda: response(429, {"error": "rate"}, headers={"retry-after": "2"})  # noqa: E731
        replies = []
        for _ in range(10):                    # 10 orders x 3 rate limits = 30
            replies += [limited(), limited(), limited(), response(200, TOOL_CALL)]
        router.client.post = AsyncMock(side_effect=replies)
        done = 0
        with patch("backend.app.brain.api_key_manager.time.time", clock.time), \
                patch("backend.app.brain.llm_router.asyncio.sleep", clock.sleep):
            try:
                for order in range(10):
                    result = await router.get_completions_with_tools("sys", f"order {order}", TOOLS,
                                                                     provider_lock="groq")
                    done += result["content"] == "Done."
            finally:
                await router.close()
        self.assertEqual(done, 10)
        self.assertEqual(router.client.post.await_count, 40)
        self.assertLess(clock.slept, 10 * 5)       # short waits only (retry-after 2 s)

    async def test_long_limits_fail_fast_and_clean_never_hang(self):
        clock = FakeClock()
        router = router_with("groq", keys=1)
        router.client.post = AsyncMock(return_value=response(429, {"error": "rate"}, headers={"retry-after": "600"}))
        with patch("backend.app.brain.api_key_manager.time.time", clock.time), \
                patch("backend.app.brain.llm_router.asyncio.sleep", clock.sleep):
            try:
                with self.assertRaises(RuntimeError):
                    await router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
            finally:
                await router.close()
        self.assertLessEqual(clock.slept, LLMRouter._MAX_COOLING_WAIT_SECONDS)
        self.assertLessEqual(router.client.post.await_count, 3)


if __name__ == "__main__":
    unittest.main()
