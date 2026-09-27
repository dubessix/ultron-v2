"""P1-P3 of the final optimization plan.

P1  Groq counts DAILY limits per model: a daily limit on gpt-oss-120b rests only
    that key+model; the smart model is kept on other keys first, then the
    lighter model is used on the same keys. Minute limits behave as before.
P2  One step too big for a free Groq key (8K per minute) goes to Gemini, and the
    job stays there; Gemini gets Google's placeholder signature for calls another
    model made.
P3  The Doctor shows resting keys and models while Ultron runs.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.app.brain import model_fallback
from backend.app.brain.api_key_manager import APIKeyManager
from backend.app.brain.llm_router import LLMRouter

GROQ = {f"GROQ_API_KEY_{i}": f"gsk_real_key_number_{i}_abcdef" for i in range(1, 3)}
GEMINI = {"GEMINI_API_KEY_1": "AIzaRealGeminiKeyForTests_abcdef123"}
BIG, SMALL = "openai/gpt-oss-120b", "openai/gpt-oss-20b"
REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _groq_ok(content="ok"):
    return httpx.Response(200, request=REQ, json={
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10}})


def _daily_429(model=BIG):
    return httpx.Response(429, request=REQ, headers={"retry-after": "7200"}, text=(
        f"Rate limit reached for model `{model}` in organization `org_x` service tier `on_demand` "
        "on tokens per day (TPD): Limit 200000, Used 199500, Requested 3000."))


def _gemini_ok(text="From Gemini, Sir."):
    return httpx.Response(200, request=httpx.Request("POST", "https://generativelanguage.googleapis.com"),
                          json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


class RouterCase(unittest.IsolatedAsyncioTestCase):
    env_keys: dict = GROQ

    async def asyncSetUp(self):
        env = {k: "" for k in ("GROQ_API_KEY_3", "GROQ_API_KEY_4", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2",
                               "NVIDIA_API_KEY_1", "ULTRON_GROQ_KEYS_SHARE_LIMIT", "GROQ_MODEL")}
        env.update(self.env_keys)
        self.env = patch.dict(os.environ, env)
        self.env.start()
        model_fallback.reset_for_tests()
        self.meter_dir = Path(tempfile.mkdtemp())
        meter = patch("backend.app.brain.usage_meter._path", return_value=self.meter_dir / "usage.json")
        meter.start()
        self.addCleanup(meter.stop)
        self.addCleanup(shutil.rmtree, self.meter_dir, True)
        self.router = LLMRouter(key_manager=APIKeyManager())
        self.sent = []  # (provider, key or '', model, body)

    async def asyncTearDown(self):
        await self.router.close()
        self.env.stop()
        model_fallback.reset_for_tests()

    def script(self, answers):
        async def post(url, headers=None, json=None, timeout=None):
            if "googleapis" in url:
                self.sent.append(("gemini", "", url.split("/models/")[1].split(":")[0], json))
            else:
                key = headers["Authorization"].split(" ", 1)[1]
                self.sent.append(("groq", key, json.get("model"), json))
            return answers.pop(0)

        self.router.client.post = post


class TestP1PerModelDailyLimits(RouterCase):
    async def test_daily_limit_keeps_the_smart_model_on_the_next_key_first(self):
        k1, k2 = GROQ["GROQ_API_KEY_1"], GROQ["GROQ_API_KEY_2"]
        self.script([_daily_429(), _groq_ok(), _groq_ok()])
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual([(s[1], s[2]) for s in self.sent], [(k1, BIG), (k2, BIG), (k2, BIG)])
        # key 1 is NOT cooled: its lighter model is still free today
        self.assertEqual(self.router.key_manager.runtime_status()["groq"]["cooling"], 0)

    async def test_when_the_smart_model_is_used_up_everywhere_the_lighter_one_answers(self):
        self.script([_daily_429(), _daily_429(), _groq_ok("light")])
        text = await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual(text, "light")
        self.assertEqual(self.sent[-1][2], SMALL)
        self.assertEqual(self.sent[-1][3]["reasoning_effort"], "low")
        summary = self.router.model_rest_summary("groq")
        self.assertEqual(summary[0]["model"], BIG)
        self.assertEqual(summary[0]["keys_resting"], 2)
        self.assertGreater(summary[0]["free_in_minutes"], 100)

    async def test_minute_limit_still_cools_the_key_like_before(self):
        k1, k2 = GROQ["GROQ_API_KEY_1"], GROQ["GROQ_API_KEY_2"]
        minute = httpx.Response(429, request=REQ, headers={"retry-after": "7"},
                                text="Rate limit reached on tokens per minute (TPM): Limit 8000")
        self.script([minute, _groq_ok()])
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        self.assertEqual([(s[1], s[2]) for s in self.sent], [(k1, BIG), (k2, BIG)])
        self.assertEqual(self.router.key_manager.runtime_status()["groq"]["cooling"], 1)
        self.assertEqual(self.router.model_rest_summary("groq"), [])

    async def test_key_cools_only_when_every_model_on_it_is_used_up(self):
        key = GROQ["GROQ_API_KEY_1"]
        for model in self.router._model_ladder("groq"):
            self.router._rest_model("groq", key, model, 3600)
        status = self.router.key_manager.runtime_status()["groq"]
        self.assertEqual(status["cooling"], 1)
        self.assertEqual(self.router._model_for_key("groq", key), (None, len(self.router._model_ladder("groq"))))

    async def test_rest_expires_by_itself(self):
        key = GROQ["GROQ_API_KEY_1"]
        self.router._rest_model("groq", key, BIG, 3600)
        self.router._model_rest[("groq", self.router._key_id(key), BIG)] = 1.0  # long ago
        self.assertEqual(self.router._model_for_key("groq", key), (BIG, 0))

    async def test_meter_splits_use_by_model(self):
        from backend.app.brain import usage_meter

        self.script([_groq_ok(), _daily_429(), _daily_429(), _groq_ok()])
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        await self.router._execute_groq_pipeline("sys", "hi", 0.2)
        row = usage_meter.today()["groq"]
        self.assertEqual(set(row["models"]), {"gpt-oss-120b", "gpt-oss-20b"})
        self.assertIn("gpt-oss-20b", usage_meter.summary_line(2))

    async def test_native_tool_path_uses_the_same_ladder_and_reports_the_real_model(self):
        self.script([_daily_429(), _daily_429(), _groq_ok("light")])
        tools = [{"tool_id": "use_tool", "description": "x", "input_schema": {"type": "object", "properties": {}}}]
        result = await self.router.get_completions_with_tools("sys", "hi", tools, provider_lock="groq")
        self.assertEqual(result["model"], SMALL)
        self.assertEqual(result["content"], "light")


class TestP2BigJobsGoToGemini(RouterCase):
    env_keys = {**GROQ, **GEMINI}
    TOOLS = [{"tool_id": "use_tool", "description": "x", "input_schema": {"type": "object", "properties": {}}}]

    def _history(self, page_chars):
        return [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_groq_1", "name": "read_current_page", "arguments": {"url": "https://x.org"}}]},
            {"role": "tool", "tool_call_id": "call_groq_1", "name": "read_current_page",
             "content": json.dumps({"success": True, "data": {"text": "w" * page_chars}})},
        ]

    async def test_normal_step_stays_on_groq(self):
        self.script([_groq_ok()])
        result = await self.router.get_completions_with_tools(
            "sys", "hi", self.TOOLS, conversation=self._history(2000), provider_lock="groq")
        self.assertEqual(result["provider"], "groq")

    async def test_step_too_big_for_groq_continues_the_job_on_gemini(self):
        self.script([_gemini_ok()])
        result = await self.router.get_completions_with_tools(
            "sys", "write the biography", self.TOOLS, conversation=self._history(30000), provider_lock="groq")
        self.assertEqual(result["provider"], "gemini")
        self.assertEqual([s[0] for s in self.sent], ["gemini"])  # Groq was never sent a doomed request
        model_turn = self.sent[0][3]["contents"][1]
        self.assertEqual(model_turn["parts"][0]["thoughtSignature"], "skip_thought_signature_validator")
        response_part = self.sent[0][3]["contents"][2]["parts"][0]["functionResponse"]
        self.assertNotIn("id", response_part)  # Groq's call id is not a Gemini id

    async def test_new_job_too_big_for_groq_starts_on_gemini(self):
        self.script([_gemini_ok()])
        result = await self.router.get_completions_with_tools(
            "sys", "x" * 40000, self.TOOLS)
        self.assertEqual(result["provider"], "gemini")

    async def test_groq_saying_413_hands_the_job_over_once(self):
        too_large = httpx.Response(413, request=REQ, text="Request too large for model: Limit 8000")
        self.script([too_large, _gemini_ok()])
        result = await self.router.get_completions_with_tools(
            "sys", "hi", self.TOOLS, conversation=self._history(2000), provider_lock="groq")
        self.assertEqual(result["provider"], "gemini")
        self.assertEqual([s[0] for s in self.sent], ["groq", "gemini"])
        self.assertEqual(self.router.key_manager.runtime_status()["groq"]["failed"], 0)

    async def test_without_gemini_a_big_step_still_tries_groq(self):
        os.environ["GEMINI_API_KEY_1"] = ""
        self.router.key_manager = APIKeyManager()
        self.script([_groq_ok()])
        result = await self.router.get_completions_with_tools(
            "sys", "hi", self.TOOLS, conversation=self._history(30000), provider_lock="groq")
        self.assertEqual(result["provider"], "groq")


class TestGeminiSignatures(unittest.TestCase):
    def test_only_gemini_3_and_newer_get_the_placeholder(self):
        self.assertEqual(LLMRouter._foreign_signature("gemini-3.5-flash"), "skip_thought_signature_validator")
        self.assertEqual(LLMRouter._foreign_signature("gemini-4-pro"), "skip_thought_signature_validator")
        self.assertIsNone(LLMRouter._foreign_signature("gemini-2.5-flash"))
        self.assertIsNone(LLMRouter._foreign_signature(""))

    def test_gemini_own_turns_keep_their_real_parts(self):
        real = [{"functionCall": {"name": "x", "args": {}}, "thoughtSignature": "REAL"}]
        history = [{"role": "assistant", "provider_state": {"parts": real}, "tool_calls": [{"id": "abc", "name": "x"}]},
                   {"role": "tool", "tool_call_id": "abc", "name": "x", "content": "{}"}]
        contents = LLMRouter._gemini_contents("hi", history, "skip_thought_signature_validator")
        self.assertEqual(contents[1]["parts"], real)
        self.assertEqual(contents[2]["parts"][0]["functionResponse"]["id"], "abc")

    def test_only_first_foreign_call_of_a_turn_is_signed(self):
        history = [{"role": "assistant", "tool_calls": [{"id": "a", "name": "x"}, {"id": "b", "name": "y"}]}]
        parts = LLMRouter._gemini_contents("hi", history, "skip_thought_signature_validator")[1]["parts"]
        self.assertIn("thoughtSignature", parts[0])
        self.assertNotIn("thoughtSignature", parts[1])


class TestP3DoctorShowsTheBrainState(unittest.TestCase):
    def test_resting_models_and_keys_in_plain_words(self):
        from backend.app.health_checks import check_brain_state

        data = {"providers": {
            "groq": {"configured": True, "key_states": {"active": 3, "cooling": 1, "failed": 0},
                     "model_rests": [{"model": BIG, "keys_resting": 2, "free_in_minutes": 95}]},
            "gemini": {"configured": True, "key_states": {"active": 1, "cooling": 0, "failed": 1}},
            "nvidia": {"configured": False}}}
        checks = check_brain_state(8000, fetch=lambda url: data)
        self.assertEqual(len(checks), 2)
        self.assertEqual(checks[0][0], "ok")
        self.assertIn("groq now: 3 keys ready, 1 resting", checks[0][1])
        self.assertIn("gpt-oss-120b used up on 2 key(s), free in about 95 min", checks[0][1])
        self.assertEqual(checks[1][0], "warn")

    def test_nothing_extra_when_ultron_is_not_running(self):
        from backend.app.health_checks import check_brain_state

        def down(url):
            raise OSError("refused")

        self.assertEqual(check_brain_state(8000, fetch=down), [])

    def test_extension_hint_names_the_real_folder(self):
        from backend.app.health_checks import check_browser_helper

        checks = check_browser_helper(8000, fetch=lambda url: {"browser_helper": {"connected": False}})
        self.assertIn("ultron-v2/extension/chrome", checks[0][2])


if __name__ == "__main__":
    unittest.main()
