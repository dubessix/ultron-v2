"""Provider-aware LLM routing, caching and failover."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import time
from typing import Any, ClassVar, Optional

import httpx

from backend.app.brain.api_key_manager import APIKeyManager
from backend.app.brain.cache_policy import BaseCachePolicy, HeuristicKeywordCachePolicy
from backend.app.brain.model_config import get_ai_runtime_settings, get_model
from backend.app.brain.smart_cache import SmartCache
from backend.app.brain.token_budget import TokenBudget


class LLMRouter:
    _PROVIDERS: ClassVar[tuple[str, ...]] = ("groq", "gemini", "nvidia")
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
        settings = get_ai_runtime_settings()
        self.primary_provider = settings["primary_provider"]
        self.secondary_provider = settings["secondary_provider"]
        self.request_timeout = settings["timeout_seconds"]
        self.provider_attempts = settings["max_attempts"]
        self.backoff_base_seconds = settings["backoff_base_seconds"]
        self._rejected_models: dict[tuple[str, str], str] = {}
        # Free-tier guard, counted per API key (see _keys_share_limit).
        self.token_budget = TokenBudget()
        # Rejections expire so one transient 400/404 (bad payload, provider blip,
        # temporary model outage) does not disable a provider for the process life.
        self._rejected_at: dict[tuple[str, str], float] = {}
        self.limits = httpx.Limits(max_keepalive_connections=5, max_connections=20)
        self.client = httpx.AsyncClient(limits=self.limits, timeout=self.request_timeout)
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

    def get_provider_order(self, provider_preference: str | None = None) -> list[str]:
        """Return stable capability preference + configured fallback order.

        Providers are not round-robin: that would change behavior/personality
        between turns. API keys still rotate within each provider.
        """
        requested = str(provider_preference or "").strip().lower()
        ordered = []
        for provider in (
            requested if requested in self._PROVIDERS else None,
            self.primary_provider,
            self.secondary_provider,
            *self._PROVIDERS,
        ):
            if provider and provider not in ordered:
                ordered.append(provider)
        return ordered

    def _cooldown_seconds(self, multiplier: float) -> int:
        return max(1, int(round(self.backoff_base_seconds * multiplier)))

    async def get_completions(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        provider_preference: str = "groq",
    ) -> str:
        """Route to configured providers without allowing mock/error cache pollution."""
        provider_order = self.get_provider_order(provider_preference)
        cache_skip = self.cache_policy.should_bypass_cache(system_prompt, user_prompt)
        last_error = None
        configured_provider_seen = False

        for provider in provider_order:
            if not self.key_manager.has_real_key(provider):
                print(f"[LLM_ROUTER] No configured key for '{provider}' — skipping.")
                continue

            configured_provider_seen = True
            model = get_model(provider)
            rejected_reason = self._active_rejection(provider, model)
            if rejected_reason:
                last_error = RuntimeError(rejected_reason)
                print(f"[LLM_ROUTER] Skipping rejected model {provider}/{model}.")
                continue
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

    @classmethod
    def _clean_native_schema(cls, schema: dict) -> dict:
        """Dereference Pydantic definitions and keep the provider JSON-schema subset."""
        definitions = schema.get("$defs") or schema.get("definitions") or {}
        allowed = {
            "type",
            "description",
            "properties",
            "required",
            "items",
            "enum",
            "anyOf",
            "oneOf",
            "minimum",
            "maximum",
            "minLength",
            "maxLength",
            "pattern",
            "format",
        }

        def clean(value: Any) -> Any:
            if isinstance(value, list):
                return [clean(item) for item in value]
            if not isinstance(value, dict):
                return value
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                target = definitions.get(reference.rsplit("/", 1)[-1], {})
                return clean(target)
            result = {}
            for key, item in value.items():
                if key not in allowed:
                    continue
                if key == "properties" and isinstance(item, dict):
                    result[key] = {str(name): clean(prop) for name, prop in item.items()}
                else:
                    result[key] = clean(item)
            return result

        cleaned = clean(schema)
        if not isinstance(cleaned, dict):
            return {"type": "object", "properties": {}}
        return cls._slim_schema(cleaned)

    # Token budget: long per-field prose is the biggest schema cost (manage_task
    # alone was ~450 tokens). Field names, types, enums and required stay intact.
    _MAX_FIELD_DESCRIPTION = 110
    _MAX_TOOL_DESCRIPTION = 320

    @classmethod
    def _slim_text(cls, text: Any, limit: int) -> Any:
        if not isinstance(text, str) or len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        return cut + "..."

    @classmethod
    def _slim_schema(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [cls._slim_schema(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key == "description":
                result[key] = cls._slim_text(item, cls._MAX_FIELD_DESCRIPTION)
            elif key == "properties" and isinstance(item, dict):
                result[key] = {name: cls._slim_schema(prop) for name, prop in item.items()}
            elif key == "anyOf" and isinstance(item, list):
                # Optional[str] -> {"type":"string"}: drop the null branch the
                # model never needs to produce (it can simply omit the field).
                branches = [b for b in item if not (isinstance(b, dict) and b.get("type") == "null")]
                if len(branches) == 1 and isinstance(branches[0], dict):
                    for sub_key, sub_value in cls._slim_schema(branches[0]).items():
                        result.setdefault(sub_key, sub_value)
                else:
                    result[key] = cls._slim_schema(branches or item)
            else:
                result[key] = cls._slim_schema(item)
        return result

    @classmethod
    def _native_tool_schema(cls, tool: dict, *, openai_style: bool) -> dict:
        name = str(tool.get("tool_id") or tool.get("name") or "").strip()
        declaration = {
            "name": name,
            "description": cls._slim_text(
                str(tool.get("description") or "Local Ultron tool."),
                cls._MAX_TOOL_DESCRIPTION,
            ),
            "parameters": cls._clean_native_schema(
                tool.get("input_schema") or {
                    "type": "object",
                    "properties": {},
                }
            ),
        }
        if openai_style:
            return {"type": "function", "function": declaration}
        return declaration

    @staticmethod
    def _openai_messages(
        system_prompt: str,
        user_prompt: str,
        conversation: list[dict],
    ) -> list[dict]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        for item in conversation:
            role = item.get("role")
            if role == "assistant":
                message: dict[str, Any] = {
                    "role": "assistant",
                    "content": item.get("content") or None,
                }
                calls = item.get("tool_calls") or []
                if calls:
                    message["tool_calls"] = [
                        {
                            "id": str(call.get("id") or "call"),
                            "type": "function",
                            "function": {
                                "name": str(call.get("name") or ""),
                                "arguments": json.dumps(
                                    call.get("arguments") or {},
                                    separators=(",", ":"),
                                ),
                            },
                        }
                        for call in calls
                    ]
                messages.append(message)
            elif role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(item.get("tool_call_id") or "call"),
                        "name": str(item.get("name") or ""),
                        "content": str(item.get("content") or "{}"),
                    }
                )
        return messages

    REJECTION_TTL_SECONDS: ClassVar[float] = 600.0

    # Longest pause for the per-minute window before sending anyway.
    _MAX_BUDGET_WAIT_SECONDS: ClassVar[float] = 20.0

    # -- budget per API key (keeps the old round-robin capacity) ----------
    @staticmethod
    def _keys_share_limit(provider: str) -> bool:
        """True only when the owner says all keys of this provider are ONE account.

        Default is per key: keys from different accounts each have their own
        free limit, so N keys = N x the capacity (the reason for round-robin).
        Set ULTRON_GROQ_KEYS_SHARE_LIMIT=1 if every key is from one account.
        """
        flag = os.getenv(f"ULTRON_{provider.upper()}_KEYS_SHARE_LIMIT", "")
        return flag.strip().lower() in {"1", "true", "yes", "on"}

    def _bucket(self, provider: str, key: Optional[str] = None) -> str:
        if not key or self._keys_share_limit(provider):
            return provider
        return f"{provider}#{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"

    def _active_keys(self, provider: str) -> list[str]:
        lister = getattr(self.key_manager, "active_keys", None)
        try:
            return list(lister(provider)) if callable(lister) else []
        except Exception:
            return []

    def _provider_wait(self, provider: str, request_chars: int) -> float:
        """Seconds until ANY key of this provider has room (0 = send now)."""
        keys = self._active_keys(provider)
        buckets = {self._bucket(provider, key) for key in keys} or {provider}
        return min(
            self.token_budget.room(bucket, self.token_budget.estimate(bucket, request_chars))
            for bucket in buckets
        )

    def _payload_estimate(self, bucket: str, payload: dict[str, Any]) -> int:
        return self.token_budget.estimate(
            bucket,
            len(json.dumps(payload, default=str)),
            max_output=min(int(payload.get("max_tokens") or 600), 600),
        )

    async def _acquire_key(self, provider: str, payload: dict[str, Any]) -> str:
        """Round-robin to the next key that has room this minute.

        Walks the pool in the normal rotation order; a key whose minute is
        full is skipped (not waited on). Only when every key is full does it
        pause (max 20 s) on the key that frees up first.
        """
        pool_size = max(1, len(self._active_keys(provider)))
        best_key, best_wait = None, float("inf")
        for _ in range(pool_size):
            key = self.key_manager.get_active_key(provider)
            bucket = self._bucket(provider, key)
            wait = self.token_budget.room(bucket, self._payload_estimate(bucket, payload))
            if wait <= 0:
                return key
            if wait < best_wait:
                best_key, best_wait = key, wait
        if best_key is not None and best_wait > 0:
            await self._respect_budget(provider, payload, key=best_key)
        return best_key or self.key_manager.get_active_key(provider)

    def _record_usage(self, provider: str, key: Optional[str], usage: Any) -> None:
        self.token_budget.record_usage(
            self._bucket(provider, key), usage if isinstance(usage, dict) else None
        )

    async def _respect_budget(
        self, provider: str, payload: dict[str, Any], key: Optional[str] = None
    ) -> None:
        """Pause briefly when this request would exceed the per-minute window."""
        bucket = self._bucket(provider, key)
        wait = self.token_budget.room(bucket, self._payload_estimate(bucket, payload))
        if wait > 0:
            wait = min(wait, self._MAX_BUDGET_WAIT_SECONDS)
            print(f"[LLM_ROUTER] Pausing {wait:.1f}s to stay inside the {provider} per-minute limit.")
            await asyncio.sleep(wait)

    @staticmethod
    def _apply_groq_reasoning(payload: dict[str, Any]) -> None:
        """gpt-oss models reason before answering; keep it fast for a voice assistant."""
        if str(payload.get("model") or "").startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = "low"

    def _active_rejection(self, provider: str, model: str) -> Optional[str]:
        """Return the rejection reason while it is fresh; forget it after the TTL."""
        key = (provider, model)
        reason = self._rejected_models.get(key)
        if not reason:
            return None
        rejected_at = self._rejected_at.setdefault(key, time.monotonic())
        if time.monotonic() - rejected_at > self.REJECTION_TTL_SECONDS:
            self._rejected_models.pop(key, None)
            self._rejected_at.pop(key, None)
            print(f"[LLM_ROUTER] Rejection for {provider}/{model} expired; retrying model.")
            return None
        return reason

    @staticmethod
    def _gemini_contents(user_prompt: str, conversation: list[dict]) -> list[dict]:
        contents: list[dict] = [{"role": "user", "parts": [{"text": user_prompt}]}]
        pending_responses: list[dict] = []

        def flush_tool_responses() -> None:
            if pending_responses:
                contents.append({"role": "user", "parts": list(pending_responses)})
                pending_responses.clear()

        for item in conversation:
            role = item.get("role")
            if role == "tool":
                raw_content = str(item.get("content") or "{}")
                try:
                    parsed = json.loads(raw_content)
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed = {"result": raw_content}
                if not isinstance(parsed, dict):
                    parsed = {"result": parsed}
                function_response: dict[str, Any] = {
                    "name": str(item.get("name") or ""),
                    "response": parsed,
                }
                # Gemini 3.x pairs responses to calls by id when it supplied one.
                # Locally synthesised fallback ids are never sent back.
                call_id = str(item.get("tool_call_id") or "")
                if call_id and not call_id.startswith("gemini-call-") and call_id != "call":
                    function_response["id"] = call_id
                pending_responses.append({"functionResponse": function_response})
                continue

            flush_tool_responses()
            if role != "assistant":
                continue
            provider_state = item.get("provider_state") or {}
            raw_parts = provider_state.get("parts") if isinstance(provider_state, dict) else None
            if isinstance(raw_parts, list) and raw_parts:
                parts = raw_parts
            else:
                parts = []
                if item.get("content"):
                    parts.append({"text": str(item["content"])})
                for call in item.get("tool_calls") or []:
                    parts.append(
                        {
                            "functionCall": {
                                "name": str(call.get("name") or ""),
                                "args": call.get("arguments") or {},
                            }
                        }
                    )
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
        flush_tool_responses()
        return contents

    @staticmethod
    def _parse_openai_native_message(payload: dict) -> dict:
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Provider returned an invalid native-tool response") from exc
        calls = []
        for index, raw_call in enumerate(message.get("tool_calls") or []):
            function = raw_call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            arguments_error = None
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                arguments = {}
                arguments_error = str(exc)
            calls.append(
                {
                    "id": str(raw_call.get("id") or f"call-{index}"),
                    "name": str(function.get("name") or ""),
                    "arguments": arguments,
                    "arguments_error": arguments_error,
                }
            )
        return {
            "content": str(message.get("content") or ""),
            "tool_calls": calls,
            "provider_state": None,
        }

    @staticmethod
    def _parse_gemini_native_message(payload: dict) -> dict:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini returned an invalid native-tool response") from exc
        text_parts = []
        calls = []
        for index, part in enumerate(parts):
            if part.get("text") and not part.get("thought"):
                text_parts.append(str(part["text"]))
            function = part.get("functionCall")
            if isinstance(function, dict):
                arguments = function.get("args") or {}
                arguments_error = None
                if not isinstance(arguments, dict):
                    arguments = {}
                    arguments_error = "arguments must be an object"
                calls.append(
                    {
                        "id": str(function.get("id") or f"gemini-call-{index}"),
                        "name": str(function.get("name") or ""),
                        "arguments": arguments,
                        "arguments_error": arguments_error,
                    }
                )
        return {
            "content": "\n".join(text_parts).strip(),
            "tool_calls": calls,
            "provider_state": {"parts": parts},
        }

    async def get_completions_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict],
        *,
        conversation: Optional[list[dict]] = None,
        temperature: float = 0.3,
        provider_preference: str = "groq",
        provider_lock: Optional[str] = None,
    ) -> dict:
        """Use provider-native local function calling without caching side effects."""
        if not tools:
            content = await self.get_completions(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                provider_preference=provider_preference,
            )
            return {
                "content": content,
                "tool_calls": [],
                "provider": self.get_route_metadata().get("provider"),
                "model": self.get_route_metadata().get("model"),
                "native_tools": False,
                "provider_state": None,
            }

        history = list(conversation or [])
        provider_order = (
            [provider_lock]
            if provider_lock in self._PROVIDERS
            else self.get_provider_order(provider_preference)
        )
        configured_provider_seen = False
        last_error = None
        configured = [p for p in provider_order if self.key_manager.has_real_key(p)]
        request_chars = len(system_prompt) + len(user_prompt) + len(
            json.dumps(history, default=str)
        ) + len(json.dumps(tools, default=str))
        for position, provider in enumerate(provider_order):
            if not self.key_manager.has_real_key(provider):
                continue
            configured_provider_seen = True
            if not provider_lock and any(p in configured for p in provider_order[position + 1 :]):
                wait = self._provider_wait(provider, request_chars)
                if wait > 0:
                    print(
                        f"[LLM_ROUTER] every {provider} key's per-minute budget nearly used "
                        f"(free in ~{wait:.0f}s); starting this job on the next provider."
                    )
                    continue
            model = get_model(provider)
            try:
                if provider == "gemini":
                    result = await self._execute_gemini_native_tools(
                        system_prompt,
                        user_prompt,
                        tools,
                        history,
                        temperature,
                    )
                else:
                    result = await self._execute_openai_native_tools(
                        provider,
                        system_prompt,
                        user_prompt,
                        tools,
                        history,
                        temperature,
                    )
                result.update(
                    {
                        "provider": provider,
                        "model": model,
                        "native_tools": True,
                    }
                )
                self._set_route(provider, model, cached=False)
                return result
            except Exception as exc:
                last_error = exc
                print(f"[LLM_ROUTER] Native tools unavailable on '{provider}': {exc}")
                if provider_lock:
                    break

        if not configured_provider_seen and not provider_lock:
            content = await self.get_completions(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                provider_preference=provider_preference,
            )
            return {
                "content": content,
                "tool_calls": [],
                "provider": self.get_route_metadata().get("provider"),
                "model": self.get_route_metadata().get("model"),
                "native_tools": False,
                "provider_state": None,
            }
        self._set_route("unavailable", None, cached=False)
        raise RuntimeError(f"Native tool provider failed: {last_error}")

    async def _execute_openai_native_tools(
        self,
        provider: str,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict],
        conversation: list[dict],
        temperature: float,
    ) -> dict:
        url = (
            "https://api.groq.com/openai/v1/chat/completions"
            if provider == "groq"
            else "https://integrate.api.nvidia.com/v1/chat/completions"
        )
        for attempt in range(self.provider_attempts):
            payload: dict[str, Any] = {
                "model": get_model(provider),
                "messages": self._openai_messages(system_prompt, user_prompt, conversation),
                "tools": [
                    self._native_tool_schema(tool, openai_style=True)
                    for tool in tools
                ],
                "tool_choice": "auto",
                "temperature": temperature,
                "max_tokens": 2048,
            }
            if provider == "groq":
                # gpt-oss on Groq does not support parallel tool use; the agent
                # loop is sequential by design, so request exactly that.
                payload["parallel_tool_calls"] = False
                self._apply_groq_reasoning(payload)
            key = await self._acquire_key(provider, payload)
            if provider == "nvidia":
                payload["chat_template_kwargs"] = {
                    "enable_thinking": True,
                    "force_nonempty_content": True,
                }
            try:
                response = await self.client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.request_timeout,
                )
            except httpx.RequestError as exc:
                self.key_manager.mark_key_cooling(
                    provider,
                    key,
                    duration_sec=self._cooldown_seconds(15),
                )
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(
                        f"{provider} native-tool network attempts exhausted: {exc}"
                    ) from exc
                continue
            if response.status_code != 200:
                self._classify_http_failure(provider, key, response)
                continue
            body = response.json()
            self._record_usage(provider, key, body.get("usage") if isinstance(body, dict) else None)
            return self._parse_openai_native_message(body)
        raise RuntimeError(f"{provider} native-tool key pool is unavailable")

    async def _execute_gemini_native_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict],
        conversation: list[dict],
        temperature: float,
    ) -> dict:
        provider = "gemini"
        model = get_model(provider)
        for attempt in range(self.provider_attempts):
            key = self.key_manager.get_active_key(provider)
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={key}"
            )
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": self._gemini_contents(user_prompt, conversation),
                "tools": [
                    {
                        "functionDeclarations": [
                            self._native_tool_schema(tool, openai_style=False)
                            for tool in tools
                        ]
                    }
                ],
                "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": 2048,
                },
            }
            try:
                response = await self.client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=self.request_timeout,
                )
            except httpx.RequestError as exc:
                self.key_manager.mark_key_cooling(
                    provider,
                    key,
                    duration_sec=self._cooldown_seconds(15),
                )
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(
                        f"Gemini native-tool network attempts exhausted: {exc}"
                    ) from exc
                continue
            if response.status_code != 200:
                self._classify_http_failure(provider, key, response)
                continue
            return self._parse_gemini_native_message(response.json())
        raise RuntimeError("Gemini native-tool key pool is unavailable")

    def _classify_http_failure(self, provider: str, key: str, response: httpx.Response) -> str:
        """Update key state safely and return 'retry' or raise a config/request error."""
        status = response.status_code
        if status == 429:
            self.key_manager.mark_key_cooling(
                provider, key, duration_sec=self._cooldown_seconds(30)
            )
            return "retry"
        if status in self._AUTH_STATUS:
            self.key_manager.mark_key_failed(provider, key)
            return "retry"
        if status in self._TEMPORARY_STATUS:
            self.key_manager.mark_key_cooling(
                provider, key, duration_sec=self._cooldown_seconds(15)
            )
            return "retry"

        # 400/404/422 normally indicate a bad model ID or payload, not a bad key.
        # Remember the rejected provider/model pair for this process so every
        # later turn does not repeatedly pay for the same known-invalid request.
        detail = (response.text or "").replace("\n", " ")[:200]
        message = f"{provider} rejected request with HTTP {status}: {detail}"
        if status in {400, 404, 422}:
            rejected_key = (provider, get_model(provider))
            self._rejected_models[rejected_key] = message
            self._rejected_at[rejected_key] = time.monotonic()
        raise RuntimeError(message)

    async def _execute_groq_pipeline(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        provider = "groq"
        for attempt in range(self.provider_attempts):
            payload = {
                "model": get_model(provider),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": 2048,
            }
            self._apply_groq_reasoning(payload)
            key = await self._acquire_key(provider, payload)
            try:
                response = await self.client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.request_timeout,
                )
            except httpx.RequestError as exc:
                self.key_manager.mark_key_cooling(
                    provider, key, duration_sec=self._cooldown_seconds(15)
                )
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(f"Groq network attempts exhausted: {exc}") from exc
                continue
            if response.status_code != 200:
                self._classify_http_failure(provider, key, response)
                continue
            try:
                body = response.json()
                self._record_usage(provider, key, body.get("usage"))
                return body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                raise RuntimeError("Groq returned an invalid response schema") from exc
        raise RuntimeError("Groq key pool is unavailable")

    async def _execute_gemini_pipeline(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        provider = "gemini"
        model = get_model(provider)
        for attempt in range(self.provider_attempts):
            key = self.key_manager.get_active_key(provider)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": 2048},
            }
            try:
                response = await self.client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=self.request_timeout,
                )
            except httpx.RequestError as exc:
                self.key_manager.mark_key_cooling(
                    provider, key, duration_sec=self._cooldown_seconds(15)
                )
                if attempt == self.provider_attempts - 1:
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
        for attempt in range(self.provider_attempts):
            key = self.key_manager.get_active_key(provider)
            payload = {
                "model": get_model(provider),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": 2048,
            }
            try:
                response = await self.client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.request_timeout,
                )
            except httpx.RequestError as exc:
                self.key_manager.mark_key_cooling(
                    provider, key, duration_sec=self._cooldown_seconds(15)
                )
                if attempt == self.provider_attempts - 1:
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
