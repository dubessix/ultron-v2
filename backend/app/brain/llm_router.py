"""Provider-aware LLM routing, caching and failover."""

from __future__ import annotations

import contextvars
import hashlib
from typing import ClassVar, Optional

import httpx

from backend.app.brain.api_key_manager import APIKeyManager
from backend.app.brain.cache_policy import BaseCachePolicy, HeuristicKeywordCachePolicy
from backend.app.brain.model_config import get_model
from backend.app.brain.smart_cache import SmartCache


class LLMRouter:
    _CASCADE: ClassVar[dict[str, list[str]]] = {
        "groq": ["groq", "gemini", "nvidia"],
        "gemini": ["gemini", "groq", "nvidia"],
        "nvidia": ["nvidia", "groq", "gemini"],
    }
    _TEMPORARY_STATUS: ClassVar[set[int]] = {408, 425, 500, 502, 503, 504}
    _AUTH_STATUS: ClassVar[set[int]] = {401, 403}

    def __init__(
        self,
        key_manager: Optional[APIKeyManager] = None,
        cache: Optional[SmartCache] = None,
        cache_policy: Optional[BaseCachePolicy] = None,
    ) -> None:
        self.key_manager = key_manager or APIKeyManager()
        self.cache = cache or SmartCache()
        self.cache_policy = cache_policy or HeuristicKeywordCachePolicy()
        self.limits = httpx.Limits(max_keepalive_connections=5, max_connections=20)
        self.client = httpx.AsyncClient(limits=self.limits, timeout=30.0)
        # Context-local metadata stays correct when several sessions route concurrently.
        self._route_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
            f"ultron_llm_route_{id(self)}",
            default=None,
        )

    def _generate_cache_hash(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        provider: str = "groq",
        model: Optional[str] = None,
    ) -> str:
        """Cache identity includes the actual provider and effective model."""
        effective_model = model or get_model(provider)
        payload = (
            f"provider={provider.lower()}|||model={effective_model}|||"
            f"temperature={temperature}|||{system_prompt}|||{user_prompt}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_route_metadata(self) -> dict:
        """Return a copy of the provider/model used by the current async context."""
        route = self._route_context.get()
        return dict(route or {"provider": None, "model": None, "cached": False, "offline": False})

    def _set_route(self, provider: str, model: Optional[str], *, cached: bool, offline: bool = False) -> None:
        self._route_context.set({
            "provider": provider,
            "model": model,
            "cached": cached,
            "offline": offline,
        })

    def _provider_executor(self, provider: str):
        if provider == "groq":
            return self._execute_groq_pipeline
        if provider == "gemini":
            return self._execute_gemini_pipeline
        if provider == "nvidia":
            return self._execute_nvidia_pipeline
        raise ValueError(f"Unsupported provider: {provider}")

    async def get_completions(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        provider_preference: str = "groq",
    ) -> str:
        """Route to configured providers without allowing mock/error cache pollution."""
        pref = provider_preference.lower()
        if pref not in self._CASCADE:
            pref = "groq"
        cache_skip = self.cache_policy.should_bypass_cache(system_prompt, user_prompt)
        last_error = None
        configured_provider_seen = False

        for provider in self._CASCADE[pref]:
            if not self.key_manager.has_real_key(provider):
                print(f"[LLM_ROUTER] No configured key for '{provider}' — skipping.")
                continue

            configured_provider_seen = True
            model = get_model(provider)
            cache_key = self._generate_cache_hash(
                system_prompt, user_prompt, temperature, provider, model
            )
            if not cache_skip:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    self._set_route(provider, model, cached=True)
                    print(f"[LLM_ROUTER] {provider}/{model} cache hit.")
                    return cached

            try:
                response = await self._provider_executor(provider)(
                    system_prompt, user_prompt, temperature
                )
                if not isinstance(response, str) or not response.strip():
                    raise RuntimeError(f"{provider} returned an empty completion")
                if not cache_skip:
                    self.cache.set(cache_key, response)
                self._set_route(provider, model, cached=False)
                return response
            except Exception as exc:
                last_error = exc
                print(f"[LLM_ROUTER] Provider '{provider}' unavailable: {exc}")

        if not configured_provider_seen:
            self._set_route("offline", None, cached=False, offline=True)
            print("[LLM_ROUTER] No real API keys configured — returning explicit unavailable state.")
            return (
                "[Offline] No real LLM provider is configured, so this prompt was not "
                "processed by an AI model. Configure a provider key and retry."
            )

        self._set_route("unavailable", None, cached=False)
        raise RuntimeError(f"All configured LLM providers failed: {last_error}")

    def _classify_http_failure(self, provider: str, key: str, response: httpx.Response) -> str:
        """Update key state safely and return 'retry' or raise a config/request error."""
        status = response.status_code
        if status == 429:
            self.key_manager.mark_key_cooling(provider, key, duration_sec=60)
            return "retry"
        if status in self._AUTH_STATUS:
            self.key_manager.mark_key_failed(provider, key)
            return "retry"
        if status in self._TEMPORARY_STATUS:
            self.key_manager.mark_key_cooling(provider, key, duration_sec=30)
            return "retry"

        # 400/404/422 normally indicate a bad model ID or payload, not a bad key.
        detail = (response.text or "").replace("\n", " ")[:200]
        raise RuntimeError(f"{provider} rejected request with HTTP {status}: {detail}")

    async def _execute_groq_pipeline(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        provider = "groq"
        for attempt in range(3):
            key = self.key_manager.get_active_key(provider)
            payload = {
                "model": get_model(provider),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": 512,
            }
            try:
                response = await self.client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=20.0,
                )
            except httpx.RequestError as exc:
                self.key_manager.mark_key_cooling(provider, key, duration_sec=30)
                if attempt == 2:
                    raise RuntimeError(f"Groq network attempts exhausted: {exc}") from exc
                continue
            if response.status_code != 200:
                self._classify_http_failure(provider, key, response)
                continue
            try:
                return response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError("Groq returned an invalid response schema") from exc
        raise RuntimeError("Groq key pool is unavailable")

    async def _execute_gemini_pipeline(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        provider = "gemini"
        model = get_model(provider)
        for attempt in range(2):
            key = self.key_manager.get_active_key(provider)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            payload = {
                "contents": [{
                    "parts": [{"text": f"System Guidelines: {system_prompt}\n\nUser Query: {user_prompt}"}]
                }],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": 512},
            }
            try:
                response = await self.client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=25.0,
                )
            except httpx.RequestError as exc:
                self.key_manager.mark_key_cooling(provider, key, duration_sec=30)
                if attempt == 1:
                    raise RuntimeError(f"Gemini network attempts exhausted: {exc}") from exc
                continue
            if response.status_code != 200:
                self._classify_http_failure(provider, key, response)
                continue
            try:
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError("Gemini returned an invalid response schema") from exc
        raise RuntimeError("Gemini key pool is unavailable")

    async def _execute_nvidia_pipeline(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        provider = "nvidia"
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        for attempt in range(3):
            key = self.key_manager.get_active_key(provider)
            payload = {
                "model": get_model(provider),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": 1024,
            }
            try:
                response = await self.client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=40.0,
                )
            except httpx.RequestError as exc:
                self.key_manager.mark_key_cooling(provider, key, duration_sec=30)
                if attempt == 2:
                    raise RuntimeError(f"NVIDIA network attempts exhausted: {exc}") from exc
                continue
            if response.status_code != 200:
                self._classify_http_failure(provider, key, response)
                continue
            try:
                return response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError("NVIDIA returned an invalid response schema") from exc
        raise RuntimeError("NVIDIA key pool is unavailable")

    async def close(self) -> None:
        if not self.client.is_closed:
            await self.client.aclose()
