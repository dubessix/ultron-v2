"""Groq's own 'tokens left' numbers decide the pause (fewer, shorter waits).

The owner's test: 3 calls of 2,442 tokens, 3 s apart -> tokens left 5558, 3615,
1629. Groq refills about 133 tokens a second (8,000 per minute); our old 60 s
window waited for whole minutes."""

from __future__ import annotations

import unittest

from backend.app.brain.token_budget import TokenBudget


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def headers(left, limit=8000):
    return {"x-ratelimit-remaining-tokens": str(left), "x-ratelimit-limit-tokens": str(limit)}


class TestLiveNumbers(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.budget = TokenBudget(clock=self.clock)
        for _ in range(3):  # the owner's three calls, as our own window saw them
            self.budget.record_usage("groq#k", {"prompt_tokens": 2422, "completion_tokens": 20})

    def test_old_window_alone_waits_most_of_a_minute(self):
        self.assertGreater(self.budget.room("groq#k", 3000), 55)

    def test_groq_numbers_give_the_true_short_wait(self):
        self.budget.observe_headers("groq#k", headers(1629))
        wait = self.budget.room("groq#k", 3000)
        self.assertAlmostEqual(wait, (3000 / 0.9 - 1629) / (8000 / 60), places=3)  # about 12.8 s, not 55+
        self.clock.now += wait + 0.01
        self.assertEqual(self.budget.room("groq#k", 3000), 0.0)

    def test_plenty_left_means_send_now(self):
        self.budget.observe_headers("groq#k", headers(7000))
        self.assertEqual(self.budget.room("groq#k", 3000), 0.0)

    def test_old_numbers_expire_after_a_minute(self):
        self.budget.observe_headers("groq#k", headers(7000))
        self.clock.now += 61
        # back to our own window (which has also emptied by now)
        self.assertEqual(self.budget.room("groq#k", 3000), 0.0)
        self.assertNotIn("groq#k", self.budget._live)

    def test_request_limit_still_counts(self):
        budget = TokenBudget(clock=self.clock)
        for _ in range(30):
            budget.record_usage("groq#r", {"prompt_tokens": 10, "completion_tokens": 1})
        budget.observe_headers("groq#r", headers(7900))
        self.assertGreater(budget.room("groq#r", 100), 0)

    def test_odd_headers_are_ignored(self):
        for bad in ({}, {"x-ratelimit-remaining-tokens": "abc"}, {"x-ratelimit-remaining-tokens": "-5"},
                    {"x-ratelimit-remaining-tokens": "9000", "x-ratelimit-limit-tokens": "8000"}, None):
            self.budget.observe_headers("groq#k", bad)
        self.assertEqual(self.budget._live, {})

    def test_one_oversized_request_is_left_to_groq(self):
        self.budget.observe_headers("groq#k", headers(100))
        self.assertEqual(self.budget.room("groq#k", 9000), 0.0)


class TestRouterReadsTheHeaders(unittest.IsolatedAsyncioTestCase):
    async def test_groq_answer_headers_reach_the_budget(self):
        import tests.test_v2_brain_ladder as base

        case = base.RouterCase("run")
        await case.asyncSetUp()
        try:
            router = case.router
            answer = base.httpx.Response(200, request=base.REQ, headers=headers(4321), json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10}})

            async def post(url, headers=None, json=None, timeout=None):
                return answer

            router.client.post = post
            tools = [{"tool_id": "use_tool", "description": "x", "input_schema": {"type": "object", "properties": {}}}]
            await router.get_completions_with_tools("sys", "hi", tools, provider_lock="groq")
            self.assertEqual([v[1] for v in router.token_budget._live.values()], [4321])
        finally:
            await case.asyncTearDown()


if __name__ == "__main__":
    unittest.main()
