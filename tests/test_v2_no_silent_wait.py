"""Final list step 3: no long silent waits.

When every Groq key's minute is full in the middle of a job, the job goes on
with Gemini (a real limit, so this is allowed) instead of a silent pause of up
to 20 s. Without Gemini, Ultron says one honest line and waits.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, patch

import tests.test_v2_brain_ladder as base

TOOLS = [{"tool_id": "use_tool", "description": "x", "input_schema": {"type": "object", "properties": {}}}]


def _fill(router, keys):
    for key in keys:
        bucket = f"groq#{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"
        router.token_budget.record_usage(bucket, {"prompt_tokens": 7400, "completion_tokens": 100})


class TestFullGroqMinuteMidJob(base.RouterCase):
    env_keys = {**base.GROQ, **base.GEMINI}

    async def test_job_goes_on_with_gemini_instead_of_waiting(self):
        _fill(self.router, base.GROQ.values())
        self.script([base._gemini_ok()])
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            result = await self.router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
        self.assertEqual(result["provider"], "gemini")  # the agent loop keeps the job there
        self.assertEqual([s[0] for s in self.sent], ["gemini"])
        sleep.assert_not_awaited()

    async def test_groq_with_room_is_kept(self):
        _fill(self.router, [base.GROQ["GROQ_API_KEY_1"]])  # key 2 still free
        self.script([base._groq_ok()])
        result = await self.router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
        self.assertEqual(result["provider"], "groq")
        self.assertEqual(self.sent[0][1], base.GROQ["GROQ_API_KEY_2"])

    async def test_job_already_on_gemini_is_untouched(self):
        self.script([base._gemini_ok()])
        result = await self.router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="gemini")
        self.assertEqual(result["provider"], "gemini")


class TestNoGeminiSaysOneLine(base.RouterCase):
    env_keys = base.GROQ

    async def test_long_wait_is_spoken_once_then_groq_answers(self):
        _fill(self.router, base.GROQ.values())
        self.script([base._groq_ok()])
        said = []

        async def publish(event):
            said.append(event)

        with patch("asyncio.sleep", new=AsyncMock()) as sleep, \
                patch("backend.app.core.live_progress.publish", new=publish):
            result = await self.router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
        self.assertEqual(result["provider"], "groq")
        sleep.assert_awaited()
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0]["speak"])
        self.assertEqual(said[0]["type"], "ultron_progress")
        self.assertRegex(said[0]["text"], r"^One moment, Sir\. The free AI limit frees up in about \d+ seconds\.$")

    async def test_speaking_failure_never_breaks_the_job(self):
        _fill(self.router, base.GROQ.values())
        self.script([base._groq_ok()])
        with patch("asyncio.sleep", new=AsyncMock()), \
                patch("backend.app.core.live_progress.publish", new=AsyncMock(side_effect=RuntimeError("no ws"))):
            result = await self.router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
        self.assertEqual(result["content"], "ok")

    async def test_short_wait_stays_silent(self):
        said = []

        async def publish(event):
            said.append(event)

        # 3 s of 8K used: well under the 5 s line, so a plain quiet pause.
        with patch("backend.app.core.live_progress.publish", new=publish), \
                patch.object(self.router.token_budget, "room", return_value=3.0), \
                patch("asyncio.sleep", new=AsyncMock()) as sleep:
            await self.router._respect_budget("groq", {"model": "m", "messages": []})
        sleep.assert_awaited_once_with(3.0)
        self.assertEqual(said, [])


def _gemini_busy_then_quota():
    """What the owner's log showed: 503 high demand, then 429 daily free quota."""
    req = base.httpx.Request("POST", "https://generativelanguage.googleapis.com")
    busy = base.httpx.Response(503, request=req, json={"error": {
        "code": 503, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}})
    quota = base.httpx.Response(429, request=req, headers={"retry-after": "40"}, json={"error": {
        "code": 429, "message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20",
        "status": "RESOURCE_EXHAUSTED"}})
    return [busy, quota]


class TestGeminiFailingNeverFailsTheTurn(base.RouterCase):
    env_keys = {**base.GROQ, **base.GEMINI}

    def route(self, gemini_answers):
        self.sent = []

        async def post(url, headers=None, json=None, timeout=None):
            if "googleapis" in url:
                self.sent.append("gemini")
                return gemini_answers.pop(0) if gemini_answers else _gemini_busy_then_quota()[0]
            self.sent.append("groq")
            return base._groq_ok("Done on Groq, Sir.")

        self.router.client.post = post

    async def test_mid_job_switch_goes_back_to_groq_when_gemini_is_busy(self):
        _fill(self.router, base.GROQ.values())
        self.route(_gemini_busy_then_quota())
        with patch("asyncio.sleep", new=AsyncMock()), \
                patch("backend.app.core.live_progress.publish", new=AsyncMock()):
            result = await self.router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
        self.assertEqual(result["provider"], "groq")
        self.assertEqual(result["content"], "Done on Groq, Sir.")
        self.assertEqual(self.sent[0], "gemini")
        self.assertEqual(self.sent[-1], "groq")

    async def test_new_job_on_gemini_goes_back_to_groq_too(self):
        _fill(self.router, base.GROQ.values())
        self.route(_gemini_busy_then_quota())
        with patch("asyncio.sleep", new=AsyncMock()), \
                patch("backend.app.core.live_progress.publish", new=AsyncMock()):
            result = await self.router.get_completions_with_tools("sys", "hi", TOOLS)
        self.assertEqual(result["provider"], "groq")
        self.assertIn("gemini", self.sent)

    async def test_the_log_shows_the_real_reason_without_keys(self):
        _fill(self.router, base.GROQ.values())
        self.route(_gemini_busy_then_quota())
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch("asyncio.sleep", new=AsyncMock()), \
                patch("backend.app.core.live_progress.publish", new=AsyncMock()):
            await self.router.get_completions_with_tools("sys", "hi", TOOLS, provider_lock="groq")
        log = out.getvalue()
        self.assertIn("gemini answered HTTP 503: This model is currently experiencing high demand.", log)
        self.assertNotIn("AIza", log)

    async def test_a_job_too_big_for_groq_does_not_bounce_back(self):
        self.route([])
        with patch("asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await self.router.get_completions_with_tools("sys", "x" * 40000, TOOLS, provider_lock="groq")
        self.assertNotIn("groq", self.sent)  # Groq would reject it anyway
