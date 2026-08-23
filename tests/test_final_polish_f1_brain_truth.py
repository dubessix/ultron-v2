"""F1 final-polish regressions for current models, routing config and modes."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import yaml

from backend.app.brain.llm_router import LLMRouter
from backend.app.brain.model_config import (
    get_ai_runtime_settings,
    get_model,
    validate_model_config,
)
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.install_paths import CONFIG_PATH


class TestCurrentModelTruth(unittest.TestCase):
    def test_default_groq_model_is_current_official_replacement(self):
        with patch.dict(os.environ, {"GROQ_CHAT_MODEL": ""}, clear=False):
            self.assertEqual(get_model("groq"), "openai/gpt-oss-20b")

    def test_retired_groq_model_is_rejected_even_as_env_override(self):
        with patch.dict(os.environ, {"GROQ_CHAT_MODEL": "llama-3.1-8b-instant"}, clear=False):
            result = validate_model_config()
        self.assertFalse(result["valid"])
        self.assertTrue(any("Groq" in error and "retired" in error for error in result["errors"]))

    def test_repository_config_matches_current_default(self):
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["ai"]["models"]["groq"], "openai/gpt-oss-20b")


class TestConfigDrivenProviderRouting(unittest.IsolatedAsyncioTestCase):
    async def test_primary_secondary_timeout_attempts_and_backoff_drive_router(self):
        configured = {
            "primary_provider": "gemini",
            "secondary_provider": "groq",
            "timeout_seconds": 17.0,
            "max_attempts": 2,
            "backoff_base_seconds": 3.0,
        }
        with patch("backend.app.brain.llm_router.get_ai_runtime_settings", return_value=configured):
            router = LLMRouter()
        try:
            self.assertEqual(router.primary_provider, "gemini")
            self.assertEqual(router.secondary_provider, "groq")
            self.assertEqual(router.request_timeout, 17.0)
            self.assertEqual(router.provider_attempts, 2)
            self.assertEqual(router.backoff_base_seconds, 3.0)
            self.assertEqual(router.get_provider_order("nvidia"), ["nvidia", "gemini", "groq"])
            self.assertEqual(router.get_provider_order("unknown"), ["gemini", "groq", "nvidia"])
        finally:
            await router.close()

    def test_runtime_settings_are_bounded_and_provider_names_validated(self):
        with patch(
            "backend.app.brain.model_config._load_ai_config",
            return_value={
                "primary_provider": "invalid-provider",
                "secondary_provider": "also-invalid",
                "timeout_seconds": 999,
                "max_retries": 99,
                "rate_limit_backoff_base_seconds": -5,
            },
        ):
            settings = get_ai_runtime_settings()
        self.assertEqual(settings["primary_provider"], "groq")
        self.assertEqual(settings["secondary_provider"], "gemini")
        self.assertEqual(settings["timeout_seconds"], 120.0)
        self.assertEqual(settings["max_attempts"], 4)
        self.assertEqual(settings["backoff_base_seconds"], 0.5)

    async def test_rejected_model_is_skipped_on_later_turns(self):
        router = LLMRouter()
        router.key_manager._keys = {
            "groq": [{"key": "g-test", "state": "ACTIVE"}],
            "gemini": [{"key": "m-test", "state": "ACTIVE"}],
            "nvidia": [],
        }
        router._rejected_models[("groq", get_model("groq"))] = "known rejected model"
        called = {"groq": 0, "gemini": 0}

        async def groq(*_args):
            called["groq"] += 1
            return "must not run"

        async def gemini(*_args):
            called["gemini"] += 1
            return "fallback ok"

        router._execute_groq_pipeline = groq
        router._execute_gemini_pipeline = gemini
        try:
            result = await router.get_completions("system", "prompt", provider_preference="groq")
        finally:
            await router.close()
        self.assertEqual(result, "fallback ok")
        self.assertEqual(called, {"groq": 0, "gemini": 1})

    async def test_backoff_config_controls_rate_limit_cooldown(self):
        configured = {
            "primary_provider": "groq",
            "secondary_provider": "gemini",
            "timeout_seconds": 30.0,
            "max_attempts": 3,
            "backoff_base_seconds": 3.0,
        }
        with patch("backend.app.brain.llm_router.get_ai_runtime_settings", return_value=configured):
            router = LLMRouter()
        response = httpx.Response(
            429,
            text="rate limited",
            request=httpx.Request("POST", "https://provider.invalid"),
        )
        try:
            with patch.object(router.key_manager, "mark_key_cooling") as cooling:
                self.assertEqual(router._classify_http_failure("groq", "secret", response), "retry")
                cooling.assert_called_once_with("groq", "secret", duration_sec=90)
        finally:
            await router.close()


class TestCodingModeUiTruth(unittest.TestCase):
    def test_frontend_labels_auto_and_forced_nvidia_modes(self):
        root = Path(__file__).resolve().parent.parent
        app = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        shell = (root / "frontend" / "src" / "components" / "AppShell.jsx").read_text(encoding="utf-8")
        self.assertIn("Returning coding mode to Auto", app)
        self.assertIn("Forced NVIDIA", app)
        self.assertIn("Coding Auto", shell)
        self.assertIn("Auto mode: coding intents use NVIDIA", shell)


class TestCodingModeTruth(unittest.IsolatedAsyncioTestCase):
    async def test_auto_mode_routes_only_coding_and_force_mode_routes_all_turns(self):
        orchestrator = CognitiveOrchestrator()
        try:
            orchestrator.set_coding_mode(False)
            self.assertTrue(orchestrator._should_use_coding_provider("CODING", "write code"))
            self.assertFalse(orchestrator._should_use_coding_provider("CONVERSATION", "hello"))

            orchestrator.set_coding_mode(True)
            self.assertTrue(orchestrator._should_use_coding_provider("CONVERSATION", "hello"))
        finally:
            orchestrator.set_coding_mode(False)
            await orchestrator.close()


if __name__ == "__main__":
    unittest.main()
