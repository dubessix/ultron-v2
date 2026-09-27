"""V2 Step E2: keep working for years when providers retire models.

Providers remove models often (Groq shut down five in 2026). When a request
fails because the MODEL is gone (HTTP 400/404/410 whose error names the model:
"decommissioned", "model_not_found", "does not exist", "not found"...), Ultron:

1. marks that model gone (saved in data/model_state.json, so a restart remembers),
2. uses the next model in the provider's fallback list on the very next attempt,
3. if the whole list is gone, asks the provider which models exist today
   (its public /models list) and picks the best match, at most once a day,
4. tells the owner once, in plain words, in his next reply.

A "gone" mark expires after 14 days so a wrong guess can never disable a model
forever. Environment/config overrides always come first in the list.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Iterable, Optional

from backend.app.runtime_paths import runtime_data_path

# Newest-known-good first where it is free; the rest are the next best choices.
# (Checked against console.groq.com/docs/models and ai.google.dev models, 2026-09.)
FALLBACK_CHAINS: dict[str, tuple[str, ...]] = {
    "groq": ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"),
    "gemini": ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash",
               "gemini-3.8-flash", "gemini-3.5-flash-lite"),
    "nvidia": ("nvidia/nemotron-3-ultra-550b-a55b",),
    "embedding": ("gemini-embedding-001",),
}

GONE_TTL_SECONDS = 14 * 86400
DISCOVERY_EVERY_SECONDS = 86400
_MODEL_WORDS = ("decommission", "model_not_found", "does not exist", "not found",
                "no longer", "not supported", "unknown model", "invalid model",
                "deprecated", "retired", "unsupported model")

_lock = threading.RLock()
_state: Optional[dict[str, Any]] = None


def _path():
    return runtime_data_path("model_state.json")


def _load() -> dict[str, Any]:
    global _state
    if _state is None:
        try:
            data = json.loads(_path().read_text(encoding="utf-8"))
            _state = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _state = {}
        for key in ("gone", "discovered", "discovery_at"):
            if not isinstance(_state.get(key), dict):
                _state[key] = {}
        if not isinstance(_state.get("notices"), list):
            _state["notices"] = []
    return _state


def _save() -> None:
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_load(), indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:  # never break a request over a state file
        print(f"[MODEL_FALLBACK] could not save model state: {exc}")


def reset_for_tests(clear_file: bool = False) -> None:
    global _state
    with _lock:
        _state = None
        if clear_file:
            try:
                _path().unlink()
            except OSError:
                pass


def _dedupe(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        item = str(item or "").strip()
        if item and item not in out:
            out.append(item)
    return out


def _is_gone(state: dict, provider: str, model: str, now: float) -> bool:
    marked = state["gone"].get(f"{provider}|{model}")
    if marked is None:
        return False
    if now - float(marked) > GONE_TTL_SECONDS:
        state["gone"].pop(f"{provider}|{model}", None)
        return False
    return True


def choose(provider: str, preferred: Iterable[str]) -> str:
    """First model that is not gone: overrides, then the chain, then a discovered one."""
    provider = provider.lower()
    chain = _dedupe(list(preferred) + list(FALLBACK_CHAINS.get(provider, ())))
    with _lock:
        state = _load()
        now = time.time()
        for model in chain:
            if not _is_gone(state, provider, model, now):
                return model
        found = state["discovered"].get(provider)
        if found and not _is_gone(state, provider, found, now):
            return found
    return chain[0] if chain else ""


def usable_chain(provider: str, preferred: Iterable[str]) -> list[str]:
    """Every model that is not gone, best first (Groq counts daily limits per model)."""
    provider = provider.lower()
    chain = _dedupe(list(preferred) + list(FALLBACK_CHAINS.get(provider, ())))
    with _lock:
        state = _load()
        now = time.time()
        return [m for m in chain if not _is_gone(state, provider, m, now)]


def chain_exhausted(provider: str, preferred: Iterable[str]) -> bool:
    provider = provider.lower()
    chain = _dedupe(list(preferred) + list(FALLBACK_CHAINS.get(provider, ())))
    with _lock:
        state = _load()
        now = time.time()
        return all(_is_gone(state, provider, m, now) for m in chain)


def is_model_gone_error(status: int, body: str) -> bool:
    """True only when the provider says the MODEL itself is unavailable."""
    if int(status) not in {400, 404, 410}:
        return False
    text = str(body or "").lower()
    return "model" in text and any(word in text for word in _MODEL_WORDS)


def _speakable(model: str) -> str:
    return re.sub(r"[/_\-:.]+", " ", str(model)).strip()


def mark_gone(provider: str, model: str, preferred: Iterable[str] = ()) -> Optional[str]:
    """Remember a retired model, queue ONE plain-words notice for the owner and
    return the model to use next (None when the whole list is gone)."""
    provider = provider.lower()
    preferred = list(preferred)
    with _lock:
        state = _load()
        key = f"{provider}|{model}"
        first_time = key not in state["gone"]
        state["gone"][key] = time.time()
        next_model = None if chain_exhausted(provider, preferred) else choose(provider, preferred)
        if next_model == model:
            next_model = None
        if first_time:
            name = {"groq": "Groq", "gemini": "Google Gemini", "nvidia": "NVIDIA",
                    "embedding": "Google"}.get(provider, provider)
            if next_model and next_model != model:
                note = (f"By the way, {name} stopped the model {_speakable(model)}, "
                        f"so I switched to {_speakable(next_model)}. Nothing for you to do.")
            else:
                note = (f"By the way, {name} stopped the model {_speakable(model)}. "
                        f"I am using my other providers for now.")
            if note not in state["notices"]:
                state["notices"] = (state["notices"] + [note])[-3:]
        _save()
    print(f"[MODEL_FALLBACK] {provider}/{model} is gone; next: {next_model or 'none'}")
    return next_model


def pop_notice() -> str:
    """The pending one-time notice(s), cleared once read ('' when none)."""
    with _lock:
        state = _load()
        notes = list(state.get("notices") or [])
        if not notes:
            return ""
        state["notices"] = []
        _save()
    return " ".join(notes)


# ---------------------------------------------------------------- discovery
_SKIP = ("whisper", "guard", "tts", "orpheus", "safeguard", "compound", "playai",
         "embed", "image", "vision", "live", "audio", "transcribe", "reward", "parse",
         "banana", "veo", "imagen", "lyria", "robotics", "computer-use", "aqa")


def pick_best(provider: str, listing: Any) -> Optional[str]:
    """Choose a chat (or embedding) model from a provider /models response."""
    provider = provider.lower()
    try:
        if provider in {"gemini", "embedding"}:
            wanted = "embedContent" if provider == "embedding" else "generateContent"
            names = [
                str(item.get("name", "")).removeprefix("models/")
                for item in (listing or {}).get("models", [])
                if wanted in (item.get("supportedGenerationMethods") or [])
            ]
            if provider == "embedding":
                embeds = [n for n in names if "embedding" in n]
                return sorted(embeds)[-1] if embeds else None
            names = [n for n in names if n.startswith("gemini") and not any(s in n for s in _SKIP)]
            flash = []
            for name in names:
                match = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", name)
                if match:
                    flash.append((float(match.group(1)), name))
            if flash:
                return max(flash)[1]
            stable = [n for n in names if "preview" not in n and "exp" not in n]
            return sorted(stable or names)[-1] if (stable or names) else None

        ids = [
            str(item.get("id", ""))
            for item in (listing or {}).get("data", [])
            if item.get("active", True) is not False
        ]
        ids = [i for i in ids if i and not any(s in i.lower() for s in _SKIP)]
        order = {
            "groq": ("gpt-oss-120b", "gpt-oss", "qwen", "llama", "kimi"),
            "nvidia": ("nemotron-3-ultra", "nemotron", "llama"),
        }.get(provider, ())
        for pattern in order:
            hits = sorted(i for i in ids if pattern in i.lower())
            if hits:
                return hits[-1]
        return sorted(ids)[-1] if ids else None
    except (AttributeError, TypeError, ValueError):
        return None


_LIST_URLS = {
    "groq": "https://api.groq.com/openai/v1/models",
    "nvidia": "https://integrate.api.nvidia.com/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
    "embedding": "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
}


async def discover(provider: str, client: Any, key: str) -> Optional[str]:
    """Ask the provider which models exist today and remember the best one.
    At most once a day per provider; never raises."""
    provider = provider.lower()
    if provider not in _LIST_URLS or not key or not discovery_due(provider):
        return None
    try:
        if provider in {"gemini", "embedding"}:
            response = await client.get(_LIST_URLS[provider], headers={"x-goog-api-key": key}, timeout=15.0)
        else:
            response = await client.get(_LIST_URLS[provider], headers={"Authorization": f"Bearer {key}"},
                                        timeout=15.0)
        model = pick_best(provider, response.json()) if response.status_code == 200 else None
    except Exception as exc:  # network, JSON, anything: try again tomorrow
        print(f"[MODEL_FALLBACK] model list for {provider} unavailable: {exc}")
        model = None
    remember_discovery(provider, model)
    if model:
        print(f"[MODEL_FALLBACK] {provider}: provider lists {model}; using it.")
    return model


def discovery_due(provider: str) -> bool:
    with _lock:
        state = _load()
        last = float(state["discovery_at"].get(provider.lower(), 0) or 0)
    return time.time() - last > DISCOVERY_EVERY_SECONDS


def remember_discovery(provider: str, model: Optional[str]) -> None:
    provider = provider.lower()
    with _lock:
        state = _load()
        state["discovery_at"][provider] = time.time()
        if model:
            state["discovered"][provider] = model
        _save()


def status() -> dict[str, Any]:
    """For `ultron doctor`: which models are marked gone / discovered."""
    with _lock:
        state = _load()
        return {"gone": sorted(state["gone"]), "discovered": dict(state["discovered"])}
