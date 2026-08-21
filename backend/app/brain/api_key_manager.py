"""Thread-safe API-key rotation and cooldown state management."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from backend.app.install_paths import ENV_PATH

load_dotenv(dotenv_path=ENV_PATH)


class NoAPIKeyError(RuntimeError):
    """Raised when a provider has no configured real key."""


class APIKeyCoolingError(RuntimeError):
    """Raised when every usable key is cooling; callers should use a fallback."""

    def __init__(self, provider: str, retry_after: float) -> None:
        self.provider = provider
        self.retry_after = max(0.0, retry_after)
        super().__init__(
            f"All {provider} keys are cooling; retry after {self.retry_after:.1f}s"
        )


def _looks_like_placeholder(value: Optional[str]) -> bool:
    if not value or not value.strip():
        return True
    lowered = value.strip().lower()
    markers = (
        "dummy_fallback", "placeholder", "changeme", "change_me", "replace_me",
        "your_groq", "your_gemini", "your_nvidia", "your_api", "api_key_here",
    )
    return any(marker in lowered for marker in markers)


class APIKeyManager:
    PROVIDERS = ("groq", "gemini", "nvidia")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._keys: Dict[str, List[Dict[str, Any]]] = {
            provider: [] for provider in self.PROVIDERS
        }
        self._cooldowns: Dict[str, float] = {}
        self._cursors: Dict[str, int] = {provider: 0 for provider in self.PROVIDERS}
        self._load_keys_from_env()

    def _load_keys_from_env(self) -> None:
        limits = {"groq": 4, "gemini": 4, "nvidia": 4}
        prefixes = {
            "groq": "GROQ_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "nvidia": "NVIDIA_API_KEY",
        }
        with self._lock:
            for provider, count in limits.items():
                for index in range(1, count + 1):
                    key = os.getenv(f"{prefixes[provider]}_{index}")
                    if not _looks_like_placeholder(key):
                        self._keys[provider].append({"key": key.strip(), "state": "ACTIVE"})

    def _clean_cooldowns_locked(self) -> None:
        now = time.time()
        for provider in self.PROVIDERS:
            for item in self._keys[provider]:
                key = item["key"]
                if item["state"] == "COOLING" and now >= self._cooldowns.get(key, float("inf")):
                    item["state"] = "ACTIVE"
                    self._cooldowns.pop(key, None)

    def get_active_key(self, provider: str) -> str:
        """Return the next ACTIVE key; never force-reuse a cooling/failed key."""
        provider = provider.lower()
        with self._lock:
            if provider not in self._keys:
                raise ValueError(f"Unsupported LLM provider requested: {provider}")
            self._clean_cooldowns_locked()
            pool = self._keys[provider]
            if not pool:
                raise NoAPIKeyError(f"No real API key configured for {provider}")

            start = self._cursors[provider] % len(pool)
            for offset in range(len(pool)):
                index = (start + offset) % len(pool)
                if pool[index]["state"] == "ACTIVE":
                    self._cursors[provider] = (index + 1) % len(pool)
                    return pool[index]["key"]

            cooling = [
                self._cooldowns.get(item["key"], float("inf"))
                for item in pool if item["state"] == "COOLING"
            ]
            if cooling:
                raise APIKeyCoolingError(provider, min(cooling) - time.time())
            raise RuntimeError(f"All configured API keys for {provider} are failed")

    def has_real_key(self, provider: str) -> bool:
        provider = provider.lower()
        with self._lock:
            return provider in self._keys and any(
                not _looks_like_placeholder(item.get("key"))
                for item in self._keys[provider]
            )

    def has_any_real_key(self) -> bool:
        return any(self.has_real_key(provider) for provider in self.PROVIDERS)

    def config_status(self) -> Dict[str, str]:
        """Report configuration only; this does not claim live reachability."""
        return {
            provider: ("configured" if self.has_real_key(provider) else "not_configured")
            for provider in self.PROVIDERS
        }

    def runtime_status(self) -> Dict[str, Dict[str, int]]:
        """Return redacted key-state counts for diagnostics."""
        with self._lock:
            self._clean_cooldowns_locked()
            result = {}
            for provider in self.PROVIDERS:
                states = {"active": 0, "cooling": 0, "failed": 0}
                for item in self._keys[provider]:
                    states[item["state"].lower()] += 1
                result[provider] = states
            return result

    def mark_key_cooling(
        self,
        provider: str,
        key: str,
        cooldown_duration_sec: int = 60,
        duration_sec: Optional[int] = None,
    ) -> None:
        provider = provider.lower()
        duration = duration_sec if duration_sec is not None else cooldown_duration_sec
        with self._lock:
            for item in self._keys.get(provider, []):
                if item["key"] == key:
                    item["state"] = "COOLING"
                    self._cooldowns[key] = time.time() + max(0, duration)
                    print(f"[API_KEY_MANAGER] {provider} key cooling for {duration}s.")
                    return

    def mark_key_failed(self, provider: str, key: str) -> None:
        provider = provider.lower()
        with self._lock:
            for item in self._keys.get(provider, []):
                if item["key"] == key:
                    item["state"] = "FAILED"
                    self._cooldowns.pop(key, None)
                    print(f"[API_KEY_MANAGER] A {provider} key was marked FAILED.")
                    return
