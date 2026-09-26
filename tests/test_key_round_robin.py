"""API-key round-robin must keep working with the Step 1 free-tier budget guard.

Keys from different accounts each have their own free limit. The guard counts
tokens per key, so a full key is skipped (next key used) and a provider is only
skipped/paused when EVERY key is full. ULTRON_GROQ_KEYS_SHARE_LIMIT=1 restores
one shared bucket for owners whose keys are all from one account.
"""

import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.app.brain.api_key_manager import APIKeyManager
from backend.app.brain.llm_router import LLMRouter

KEYS = {f"GROQ_API_KEY_{i}": f"gsk_real_key_number_{i}_abcdef" for i in range(1, 4)}


def _ok(content="ok", prompt_tokens=100):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 10},
        },
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )


class KeyRoundRobinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = {k: "" for k in ("GROQ_API_KEY_4", "ULTRON_GROQ_KEYS_SHARE_LIMIT")}
        env.update(KEYS)
        self.env = patch.dict(os.environ, env)
        self.env.start()
        self.router = LLMRouter(key_manager=APIKeyManager())
        self.used = []

        async def fake_post(url, headers=None, json=None, timeout=None):
            self.used.append(headers["Authorization"].split()[-1])
            return _ok()

        self.router.client.post = fake_post

    async def asyncTearDown(self):
        await self.router.close()
        self.env.stop()

    async def test_same_key_is_kept_while_it_has_room(self):
        # Owner's rule (V2): no jumping groq1 -> groq2 -> groq3 without a real
        # limit. One key keeps Groq's per-account prompt cache warm.
        for _ in range(6):
            await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual(self.used, [KEYS["GROQ_API_KEY_1"]] * 6)

    async def test_moves_on_only_when_the_key_is_really_full_and_stays(self):
        key1, key2 = KEYS["GROQ_API_KEY_1"], KEYS["GROQ_API_KEY_2"]
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.router.token_budget.record_usage(self.router._bucket("groq", key1), {"prompt_tokens": 7900})
        for _ in range(3):
            await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual(self.used, [key1, key2, key2, key2])  # no jump back

    async def test_real_429_moves_to_next_key_and_stays(self):
        key1, key2 = KEYS["GROQ_API_KEY_1"], KEYS["GROQ_API_KEY_2"]
        answers = [httpx.Response(429, headers={"retry-after": "7"},
                                  request=httpx.Request("POST", "https://api.groq.com")),
                   _ok(), _ok()]
        used = []

        async def post(url, headers=None, json=None, timeout=None):
            used.append(headers["Authorization"].split(" ", 1)[1])
            return answers.pop(0)

        self.router.client.post = post
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual(used, [key1, key2, key2])

    async def test_busy_provider_retries_the_same_key(self):
        key1 = KEYS["GROQ_API_KEY_1"]
        answers = [httpx.Response(503, request=httpx.Request("POST", "https://api.groq.com")), _ok()]
        used = []

        async def post(url, headers=None, json=None, timeout=None):
            used.append(headers["Authorization"].split(" ", 1)[1])
            return answers.pop(0)

        self.router.client.post = post
        with patch("backend.app.brain.llm_router.asyncio.sleep", new=AsyncMock()) as sleep:
            await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual(used, [key1, key1])
        sleep.assert_awaited()  # short pause, not a jump
        self.assertEqual(self.router.key_manager.active_keys("groq")[0], key1)  # not cooled

    async def test_network_blip_retries_the_same_key(self):
        key1 = KEYS["GROQ_API_KEY_1"]
        used = []

        async def post(url, headers=None, json=None, timeout=None):
            used.append(headers["Authorization"].split(" ", 1)[1])
            if len(used) == 1:
                raise httpx.ConnectError("blip")
            return _ok()

        self.router.client.post = post
        with patch("backend.app.brain.llm_router.asyncio.sleep", new=AsyncMock()):
            await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual(used, [key1, key1])

    async def test_daily_limit_rests_the_key_for_hours(self):
        key1 = KEYS["GROQ_API_KEY_1"]
        response = httpx.Response(429, headers={"retry-after": "7200"},
                                  request=httpx.Request("POST", "https://api.groq.com"))
        self.router._classify_http_failure("groq", key1, response)
        self.assertNotIn(key1, self.router.key_manager.active_keys("groq"))
        remaining = self.router.key_manager._cooldowns[key1] - __import__("time").time()
        self.assertGreater(remaining, 7000)

    async def test_full_key_is_skipped_not_waited_on(self):
        key1 = KEYS["GROQ_API_KEY_1"]
        self.router.token_budget.record_usage(self.router._bucket("groq", key1), {"prompt_tokens": 7900})
        with patch("backend.app.brain.llm_router.asyncio.sleep", new=AsyncMock()) as sleep:
            await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        sleep.assert_not_awaited()
        self.assertEqual(self.used, [KEYS["GROQ_API_KEY_2"]])

    async def test_each_key_has_its_own_budget(self):
        # 3 keys x ~7K tokens: far above one key's 8K/min, no pause needed.
        for key in KEYS.values():
            self.router.token_budget.record_usage(self.router._bucket("groq", key), {"prompt_tokens": 3000})
        self.assertEqual(self.router._provider_wait("groq", 4000), 0)

    async def test_provider_skipped_only_when_every_key_is_full(self):
        for key in list(KEYS.values())[:2]:
            self.router.token_budget.record_usage(self.router._bucket("groq", key), {"prompt_tokens": 7900})
        self.assertEqual(self.router._provider_wait("groq", 400), 0)
        self.router.token_budget.record_usage(
            self.router._bucket("groq", KEYS["GROQ_API_KEY_3"]), {"prompt_tokens": 7900}
        )
        self.assertGreater(self.router._provider_wait("groq", 400), 0)

    async def test_all_keys_full_pauses_briefly_then_sends(self):
        for key in KEYS.values():
            self.router.token_budget.record_usage(self.router._bucket("groq", key), {"prompt_tokens": 7900})
        with patch("backend.app.brain.llm_router.asyncio.sleep", new=AsyncMock()) as sleep:
            await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        sleep.assert_awaited_once()
        self.assertLessEqual(sleep.await_args.args[0], LLMRouter._MAX_BUDGET_WAIT_SECONDS)
        self.assertEqual(len(self.used), 1)

    async def test_usage_is_recorded_on_the_key_that_was_used(self):
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        bucket1 = self.router._bucket("groq", KEYS["GROQ_API_KEY_1"])
        bucket2 = self.router._bucket("groq", KEYS["GROQ_API_KEY_2"])
        self.assertEqual(self.router.token_budget.used(bucket1), (110, 1))
        self.assertEqual(self.router.token_budget.used(bucket2), (0, 0))

    async def test_share_limit_setting_uses_one_bucket(self):
        with patch.dict(os.environ, {"ULTRON_GROQ_KEYS_SHARE_LIMIT": "1"}):
            buckets = {self.router._bucket("groq", key) for key in KEYS.values()}
            self.assertEqual(buckets, {"groq"})
            self.router.token_budget.record_usage("groq", {"prompt_tokens": 7900})
            self.assertGreater(self.router._provider_wait("groq", 400), 0)

    async def test_rate_limited_key_still_cools_and_rotates(self):
        calls = []

        async def post(url, headers=None, json=None, timeout=None):
            key = headers["Authorization"].split()[-1]
            calls.append(key)
            if key == KEYS["GROQ_API_KEY_1"]:
                return httpx.Response(429, json={"error": {"message": "rate"}},
                                      request=httpx.Request("POST", url))
            return _ok()

        self.router.client.post = post
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual(calls[:2], [KEYS["GROQ_API_KEY_1"], KEYS["GROQ_API_KEY_2"]])
        self.assertNotIn(KEYS["GROQ_API_KEY_1"], self.router.key_manager.active_keys("groq"))

    def test_bucket_never_contains_the_raw_key(self):
        bucket = self.router._bucket("groq", KEYS["GROQ_API_KEY_1"])
        self.assertTrue(bucket.startswith("groq#"))
        self.assertNotIn("gsk_", bucket)


if __name__ == "__main__":
    unittest.main()
