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

from backend.app.brain.api_key_manager import APIKeyCoolingError, APIKeyManager
from backend.app.brain.cache_policy import BaseCachePolicy, HeuristicKeywordCachePolicy
from backend.app.brain.model_config import get_ai_runtime_settings, get_model
from backend.app.brain.smart_cache import SmartCache
from backend.app.brain.token_budget import TokenBudget


class RequestTooLargeError(RuntimeError):
    """The provider says this one request is bigger than its per-minute limit (HTTP 413)."""


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
        # P1: Groq counts DAILY limits per model. (provider, key id, model) -> rest
        # until (epoch seconds). A daily limit on gpt-oss-120b leaves gpt-oss-20b
        # free on the same key, so only that pair rests.
        self._model_rest: dict[tuple[str, str, str], float] = {}
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

        Providers never rotate: that would change behavior/personality
        between turns. Keys stay on one key until a real limit (see _acquire_key).
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

    def _raise_if_cooling(self, provider: str) -> None:
        """Attempts used up because every key is rate limited: say so (the caller
        then waits for the first free key instead of giving up)."""
        try:
            self.key_manager.get_active_key(provider)
        except APIKeyCoolingError:
            raise
        except Exception:
            return

    @staticmethod
    def _retry_after(response: httpx.Response, cap: int = 90) -> int:
        """Seconds from a 429 'retry-after' header (bounded 1..cap; 0 = not given).
        The key rests the full time (cap 6 h, e.g. a daily limit); the wait loop
        itself never sleeps longer than _MAX_COOLING_WAIT_SECONDS."""
        try:
            headers = getattr(response, "headers", None) or {}
            value = float(str(headers.get("retry-after", "")).strip())
        except (AttributeError, TypeError, ValueError):
            return 0
        return int(max(1, min(value, cap))) if value > 0 else 0

    async def _short_pause(self, attempt: int) -> None:
        """Busy provider or network blip: wait 0.5 s, 1 s, 1.5 s (max 2 s), same key."""
        await asyncio.sleep(min(2.0, 0.5 * (attempt + 1)))

    async def _maybe_discover(self, provider: str) -> None:
        """Whole fallback list retired: ask the provider for today's models (1x/day)."""
        from backend.app.brain import model_fallback
        from backend.app.brain.model_config import preferred_models

        if not model_fallback.chain_exhausted(provider, preferred_models(provider)):
            return
        if not model_fallback.discovery_due(provider):
            return
        try:
            key = self.key_manager.get_active_key(provider)
        except Exception:
            return
        await model_fallback.discover(provider, self.client, key)

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
            await self._maybe_discover(provider)
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
    _MAX_COOLING_ROUNDS: ClassVar[int] = 2
    _MAX_COOLING_WAIT_SECONDS: ClassVar[float] = 40.0

    # Longest pause for the per-minute window before sending anyway.
    _MAX_BUDGET_WAIT_SECONDS: ClassVar[float] = 20.0
    # P2: one request above this (tokens, incl. room for the answer) cannot fit a
    # free Groq key's 8K-per-minute limit, so Groq would reject it outright.
    _GROQ_MAX_REQUEST_TOKENS: ClassVar[int] = 7600
    _GROQ_ANSWER_ROOM: ClassVar[int] = 2048  # max_tokens we ask for; Groq counts it too
    _PER_MODEL_DAILY: ClassVar[frozenset[str]] = frozenset({"groq"})

    # -- budget per API key (keeps the old round-robin capacity) ----------
    @staticmethod
    def _keys_share_limit(provider: str) -> bool:
        """True only when the owner says all keys of this provider are ONE account.

        Default is per key: keys from different accounts each have their own
        free limit, so N keys = N x the capacity (used one after another).
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
        """Stay on the current key while it has room (owner's rule: no jumping).

        The same key keeps Groq's prompt cache warm (each account has its own
        cache). Only when THIS key's minute is really full does it move to the
        next key, and it stays there. When every key is full it pauses
        (max 20 s) on the key that frees up first.
        """
        pool_size = max(1, len(self._active_keys(provider)))
        best_key, best_wait = None, float("inf")
        # P1: a key whose best model hit today's limit gives way to a key that
        # still has it (the smarter model first); lighter models only after that.
        target_rank = self._best_rank(provider) if provider in self._PER_MODEL_DAILY else 0
        for _ in range(pool_size):
            key = self.key_manager.get_active_key(provider)
            if provider in self._PER_MODEL_DAILY and self._model_for_key(provider, key)[1] != target_rank:
                self.key_manager.move_on(provider, key)
                continue
            bucket = self._bucket(provider, key)
            wait = self.token_budget.room(bucket, self._payload_estimate(bucket, payload))
            if wait <= 0:
                return key
            if wait < best_wait:
                best_key, best_wait = key, wait
            self.key_manager.move_on(provider, key)
        if best_key is not None and best_wait > 0:
            await self._respect_budget(provider, payload, key=best_key)
        return best_key or self.key_manager.get_active_key(provider)

    def _record_usage(
        self, provider: str, key: Optional[str], usage: Any, model: Optional[str] = None
    ) -> None:
        self.token_budget.record_usage(
            self._bucket(provider, key), usage if isinstance(usage, dict) else None
        )
        from backend.app.brain import usage_meter

        usage_meter.add(provider, usage if isinstance(usage, dict) else None, model=model)

    # ---------------------------------------------------------- P2: jobs too big for Groq
    def _too_big_for_groq(self, request_chars: int) -> bool:
        return request_chars // 4 + self._GROQ_ANSWER_ROOM > self._GROQ_MAX_REQUEST_TOKENS

    def _handover_provider(self) -> Optional[str]:
        """Where a job too big for a free Groq key goes (big-context providers)."""
        for provider in ("gemini", "nvidia"):
            if self.key_manager.has_real_key(provider):
                return provider
        return None

    # ---------------------------------------------------------- P1: per-model daily limits
    @staticmethod
    def _key_id(key: Optional[str]) -> str:
        return hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _model_ladder(provider: str) -> list[str]:
        """Usable models, best first (owner's choice, then the fallback chain)."""
        from backend.app.brain import model_fallback
        from backend.app.brain.model_config import preferred_models

        try:
            ladder = model_fallback.usable_chain(provider, preferred_models(provider))
        except Exception:
            ladder = []
        return ladder or [get_model(provider)]

    def _model_for_key(self, provider: str, key: Optional[str]) -> tuple[Optional[str], int]:
        """Best model this key may still use today, and its rank (0 = best)."""
        ladder = self._model_ladder(provider)
        if provider not in self._PER_MODEL_DAILY:
            return ladder[0], 0
        now, kid = time.time(), self._key_id(key)
        for rank, model in enumerate(ladder):
            until = self._model_rest.get((provider, kid, model))
            if until is None:
                return model, rank
            if until <= now:
                self._model_rest.pop((provider, kid, model), None)
                return model, rank
        return None, len(ladder)

    def _best_rank(self, provider: str) -> int:
        ranks = [self._model_for_key(provider, key)[1] for key in self._active_keys(provider)]
        return min(ranks) if ranks else 0

    def _rest_model(self, provider: str, key: str, model: str, seconds: int) -> None:
        """Daily limit for this key + model: rest only that pair. When every model
        of this key rests, the key itself cools until the first one is free."""
        kid = self._key_id(key)
        self._model_rest[(provider, kid, model)] = time.time() + max(60, seconds)
        print(f"[LLM_ROUTER] {provider} {model}: daily limit on this key; resting it "
              f"{max(60, seconds) / 3600:.1f} h, other models stay available.")
        if self._model_for_key(provider, key)[0] is None:
            soonest = min(until for (p, k, _m), until in self._model_rest.items() if p == provider and k == kid)
            self.key_manager.mark_key_cooling(provider, key, duration_sec=int(max(1, soonest - time.time())))

    @staticmethod
    def _is_daily_limit(response: Any) -> bool:
        try:
            body = str(getattr(response, "text", "") or "").lower()
        except Exception:
            return False
        return "per day" in body or "(tpd)" in body or "(rpd)" in body

    def model_rest_summary(self, provider: str) -> list[dict[str, Any]]:
        """For the Doctor: which models rest on how many keys, and for how long."""
        now = time.time()
        summary: dict[str, list[float]] = {}
        for (p, _kid, model), until in list(self._model_rest.items()):
            if p == provider and until > now:
                summary.setdefault(model, []).append(until - now)
        return [{"model": m, "keys_resting": len(w), "free_in_minutes": int(min(w) // 60) + 1}
                for m, w in sorted(summary.items())]

    def _apply_model_for_key(self, provider: str, key: str, payload: dict[str, Any]) -> None:
        """Send the best model THIS key may still use (P1)."""
        if provider not in self._PER_MODEL_DAILY:
            return
        model, _rank = self._model_for_key(provider, key)
        if model and model != payload.get("model"):
            payload["model"] = model
            payload.pop("reasoning_effort", None)
            self._apply_groq_reasoning(payload)

    # A mid-job wait longer than this goes to the next provider instead (if any),
    # or is announced out loud (no provider to switch to).
    _MIDJOB_SWITCH_SECONDS = 5.0

    async def _respect_budget(
        self, provider: str, payload: dict[str, Any], key: Optional[str] = None
    ) -> None:
        """Pause briefly when this request would exceed the per-minute window."""
        bucket = self._bucket(provider, key)
        wait = self.token_budget.room(bucket, self._payload_estimate(bucket, payload))
        if wait > 0:
            wait = min(wait, self._MAX_BUDGET_WAIT_SECONDS)
            print(f"[LLM_ROUTER] Pausing {wait:.1f}s to stay inside the {provider} per-minute limit.")
            if wait >= self._MIDJOB_SWITCH_SECONDS:
                await self._say_waiting(wait)  # never a long silence that feels broken
            await asyncio.sleep(wait)

    @staticmethod
    async def _say_waiting(seconds: float) -> None:
        """One honest spoken line during a long limit pause (0 tokens)."""
        try:
            from backend.app.core import live_progress

            await live_progress.publish({
                "type": "ultron_progress", "speak": True, "tool": "", "session_id": "",
                "text": f"One moment, Sir. The free AI limit frees up in about {max(5, round(seconds / 5) * 5)} seconds.",
            })
        except Exception:
            pass

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
    def _gemini_contents(
        user_prompt: str, conversation: list[dict], foreign_signature: Optional[str] = None
    ) -> list[dict]:
        """foreign_signature: Google's documented placeholder for tool calls another
        model made (Gemini 3 rejects unsigned calls in the current turn)."""
        contents: list[dict] = [{"role": "user", "parts": [{"text": user_prompt}]}]
        pending_responses: list[dict] = []
        foreign_ids: set[str] = set()

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
                if (call_id and not call_id.startswith("gemini-call-") and call_id != "call"
                        and call_id not in foreign_ids):
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
                    foreign_ids.add(str(call.get("id") or ""))
                    part: dict[str, Any] = {
                        "functionCall": {
                            "name": str(call.get("name") or ""),
                            "args": call.get("arguments") or {},
                        }
                    }
                    if foreign_signature and not any("functionCall" in p for p in parts):
                        part["thoughtSignature"] = foreign_signature  # first call of the turn
                    parts.append(part)
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
        # P2: one request too big for a free Groq key (8K per minute) would be
        # rejected outright. Hand THIS job to a big-context provider; the agent
        # loop keeps the job there (no jumping back and forth).
        too_big = self._too_big_for_groq(request_chars)
        handover = self._handover_provider()
        if provider_lock == "groq" and too_big and handover:
            print(f"[LLM_ROUTER] this step is too big for a free Groq key; continuing the job on {handover}.")
            provider_order = [handover]
            provider_lock = handover
        elif provider_lock == "groq" and handover:
            # Speed (final list step 3): every Groq key's minute is full. That is a
            # real limit, so rather than a silent pause of up to 20 s the job goes
            # on with the next provider and stays there (no jumping back).
            full_for = self._provider_wait("groq", request_chars)
            if full_for > self._MIDJOB_SWITCH_SECONDS:
                print(f"[LLM_ROUTER] every groq key is full for ~{full_for:.0f}s; "
                      f"continuing this job on {handover} instead of waiting.")
                provider_order = [handover]
                provider_lock = handover
        waited = 0.0
        for _round in range(self._MAX_COOLING_ROUNDS + 1):
            cooling: list[float] = []
            for position, provider in enumerate(provider_order):
                if not self.key_manager.has_real_key(provider):
                    continue
                configured_provider_seen = True
                later_configured = any(p in configured for p in provider_order[position + 1 :])
                if provider == "groq" and too_big and not provider_lock and later_configured:
                    print("[LLM_ROUTER] this job is too big for a free Groq key; starting it on the next provider.")
                    continue
                if not provider_lock and later_configured:
                    wait = self._provider_wait(provider, request_chars)
                    if wait > 0:
                        print(
                            f"[LLM_ROUTER] every {provider} key's per-minute budget nearly used "
                            f"(free in ~{wait:.0f}s); starting this job on the next provider."
                        )
                        cooling.append(float(wait))
                        continue
                await self._maybe_discover(provider)
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
                    model = result.pop("model_used", None) or get_model(provider)  # the model that answered
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
                    if isinstance(exc, APIKeyCoolingError):
                        cooling.append(float(exc.retry_after))
                    print(f"[LLM_ROUTER] Native tools unavailable on '{provider}': {exc}")
                    if (isinstance(exc, RequestTooLargeError) and handover and provider != handover
                            and handover not in provider_order):
                        # Our size guess was low: the provider said too large. Hand over once.
                        print(f"[LLM_ROUTER] continuing this job on {handover} (request too large).")
                        provider_order.append(handover)
                        provider_lock = handover if provider_lock else None
                        continue
                    if provider_lock:
                        break
            # V2 Step E3: every configured provider failed only because all its keys
            # are cooling (rate limit) -> wait for the first key and try again,
            # bounded (never an endless loop, never a long silent hang).
            tried = [p for p in (configured if not provider_lock else [provider_lock])]
            if not cooling or len(cooling) < len(tried):
                break
            pause = max(0.5, min(cooling)) + 0.25
            if waited + pause > self._MAX_COOLING_WAIT_SECONDS:
                break
            print(f"[LLM_ROUTER] All keys are rate limited; waiting {pause:.1f}s, then retrying.")
            await asyncio.sleep(pause)
            waited += pause

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
            self._apply_model_for_key(provider, key, payload)
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
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(
                        f"{provider} native-tool network attempts exhausted: {exc}"
                    ) from exc
                await self._short_pause(attempt)
                continue
            if response.status_code != 200:
                if self._classify_http_failure(provider, key, response, model=payload["model"]) == "pause":
                    await self._short_pause(attempt)
                continue
            body = response.json()
            self._record_usage(provider, key, body.get("usage") if isinstance(body, dict) else None,
                               model=payload["model"])
            result = self._parse_openai_native_message(body)
            result["model_used"] = payload["model"]
            return result
        self._raise_if_cooling(provider)
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
        for attempt in range(self.provider_attempts):
            model = get_model(provider)  # a retired model is swapped between attempts
            key = self.key_manager.get_active_key(provider)
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={key}"
            )
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": self._gemini_contents(
                    user_prompt, conversation, self._foreign_signature(model)
                ),
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
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(
                        f"Gemini native-tool network attempts exhausted: {exc}"
                    ) from exc
                await self._short_pause(attempt)
                continue
            if response.status_code != 200:
                if self._classify_http_failure(provider, key, response) == "pause":
                    await self._short_pause(attempt)
                continue
            return self._parse_gemini_native_message(response.json())
        self._raise_if_cooling(provider)
        raise RuntimeError("Gemini native-tool key pool is unavailable")

    @staticmethod
    def _foreign_signature(model: str) -> Optional[str]:
        """Gemini 3+ validates signatures on replayed calls; older models must not get one."""
        import re

        match = re.search(r"gemini-(\d+)", str(model or ""))
        return "skip_thought_signature_validator" if match and int(match.group(1)) >= 3 else None

    def _classify_http_failure(
        self, provider: str, key: str, response: httpx.Response, model: Optional[str] = None
    ) -> str:
        """Update key state safely and return 'retry' or raise a config/request error."""
        status = response.status_code
        if status == 429 and model and provider in self._PER_MODEL_DAILY and self._is_daily_limit(response):
            # P1: only this model's daily budget is used up on this key.
            self._rest_model(provider, key, model, self._retry_after(response, cap=6 * 3600) or 3600)
            return "retry"
        if status == 429:
            # V2 Step E3: the provider says exactly when this key is free again.
            self.key_manager.mark_key_cooling(
                provider, key,
                duration_sec=self._retry_after(response, cap=6 * 3600) or self._cooldown_seconds(30),
            )
            return "retry"
        if status in self._AUTH_STATUS:
            self.key_manager.mark_key_failed(provider, key)
            return "retry"
        if status == 413:
            # One request bigger than the key's per-minute limit: no key can take it.
            raise RequestTooLargeError(f"{provider} says this request is too large for its limit")
        if status in self._TEMPORARY_STATUS:
            # Provider busy (5xx/timeout): the key is fine. Retry the SAME key
            # after a short pause; no fake "cooling" that makes keys jump.
            return "pause"

        # V2 Step E2: the provider retired this model -> use the next one now.
        from backend.app.brain import model_fallback
        from backend.app.brain.model_config import retire_model

        body = response.text or ""
        if model_fallback.is_model_gone_error(status, body):
            used = model or get_model(provider)
            if retire_model(provider, used):
                return "retry"
            raise RuntimeError(f"{provider} model {used} was retired and no fallback is left")

        # 400/404/422 normally indicate a bad model ID or payload, not a bad key.
        # Remember the rejected provider/model pair for this process so every
        # later turn does not repeatedly pay for the same known-invalid request.
        detail = body.replace("\n", " ")[:200]
        message = f"{provider} rejected request with HTTP {status}: {detail}"
        if status in {400, 404, 422}:
            rejected_key = (provider, model or get_model(provider))
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
            self._apply_model_for_key(provider, key, payload)
            try:
                response = await self.client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.request_timeout,
                )
            except httpx.RequestError as exc:
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(f"Groq network attempts exhausted: {exc}") from exc
                await self._short_pause(attempt)
                continue
            if response.status_code != 200:
                if self._classify_http_failure(provider, key, response, model=payload["model"]) == "pause":
                    await self._short_pause(attempt)
                continue
            try:
                body = response.json()
                self._record_usage(provider, key, body.get("usage"), model=payload["model"])
                return body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                raise RuntimeError("Groq returned an invalid response schema") from exc
        raise RuntimeError("Groq key pool is unavailable")

    async def _execute_gemini_pipeline(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        provider = "gemini"
        for attempt in range(self.provider_attempts):
            model = get_model(provider)  # a retired model is swapped between attempts
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
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(f"Gemini network attempts exhausted: {exc}") from exc
                await self._short_pause(attempt)
                continue
            if response.status_code != 200:
                if self._classify_http_failure(provider, key, response) == "pause":
                    await self._short_pause(attempt)
                continue
            try:
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError("Gemini returned an invalid response schema") from exc
        raise RuntimeError("Gemini key pool is unavailable")

    async def look_at_image(self, image: bytes, mime_type: str, question: str) -> str:
        """Screen vision: Gemini (free, multimodal) answers a question about one
        picture. Only called when the owner asks, so it costs ~1,120 tokens per
        look (Gemini 3 default) and nothing otherwise. Plain text back, or a
        RuntimeError with a short honest reason."""
        import base64

        provider = "gemini"
        if not self.key_manager.has_real_key(provider):
            raise RuntimeError("Screen vision needs a Gemini key (GEMINI_API_KEY_1 in the .env file).")
        if not image:
            raise RuntimeError("The picture is empty.")
        if len(image) > 15 * 1024 * 1024:
            raise RuntimeError("The picture is too big to send (over 15 MB).")
        prompt = (
            "You are the eyes of a desktop assistant. Answer the owner's question about this "
            "picture of his screen in at most 4 short sentences. Quote exact text (errors, names, "
            "numbers) when it matters. If something cannot be read, say so.\n\nQuestion: "
            + (question.strip() or "What is on the screen?")
        )
        payload = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(image).decode("ascii")}},
            ]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600},
        }
        for attempt in range(self.provider_attempts):
            model = get_model(provider)
            key = self.key_manager.get_active_key(provider)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                response = await self.client.post(
                    url, headers={"Content-Type": "application/json", "x-goog-api-key": key},
                    json=payload, timeout=max(30.0, float(self.request_timeout)),
                )
            except httpx.RequestError as exc:
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(f"Could not reach Gemini: {exc}") from exc
                await self._short_pause(attempt)
                continue
            if response.status_code != 200:
                if self._classify_http_failure(provider, key, response) == "pause":
                    await self._short_pause(attempt)
                continue
            try:
                parts = response.json()["candidates"][0]["content"]["parts"]
                text = " ".join(str(part.get("text") or "") for part in parts).strip()
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError("Gemini sent back an answer I could not read.") from exc
            if text:
                return text
            raise RuntimeError("Gemini looked but gave no answer.")
        raise RuntimeError("Every Gemini key is busy right now. Try again in a minute.")

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
                if attempt == self.provider_attempts - 1:
                    raise RuntimeError(f"NVIDIA network attempts exhausted: {exc}") from exc
                await self._short_pause(attempt)
                continue
            if response.status_code != 200:
                if self._classify_http_failure(provider, key, response) == "pause":
                    await self._short_pause(attempt)
                continue
            try:
                return response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError("NVIDIA returned an invalid response schema") from exc
        raise RuntimeError("NVIDIA key pool is unavailable")

    async def close(self) -> None:
        if not self.client.is_closed:
            await self.client.aclose()
