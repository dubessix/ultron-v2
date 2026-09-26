"""
Ultron Model Configuration (Phase 2)

Resolves the model IDs for each AI provider from three sources, in priority order:
  1. Environment variable override (e.g. GEMINI_CHAT_MODEL)
  2. config.yaml  ai.models.<provider>
  3. A hard-coded, currently-valid default

This makes the brain provider-agnostic and future-proof: when a provider
retires a model (as Gemini 1.5 / text-embedding-004 already were), switching is
a config change, not a code edit.
"""

import os
from typing import Optional

import yaml

from backend.app.install_paths import CONFIG_PATH

# Current defaults verified against provider documentation on 2026-08-23.
# Groq shut down llama-3.1-8b-instant on 2026-08-16 and names
# openai/gpt-oss-20b as its direct replacement. Jarvis Phase 1 upgrades the
# default to openai/gpt-oss-120b for markedly more reliable native tool choice
# (still overridable via GROQ_CHAT_MODEL).
_DEFAULTS = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-3.5-flash",
    "nvidia": "nvidia/nemotron-3-ultra-550b-a55b",
    "embedding": "gemini-embedding-001",
    "embedding_dims": 768,
}

# env var name per provider (embedding uses the gemini API key too).
_ENV_MAP = {
    "groq": "GROQ_CHAT_MODEL",
    "gemini": "GEMINI_CHAT_MODEL",
    "nvidia": "NVIDIA_CHAT_MODEL",
    "embedding": "GEMINI_EMBEDDING_MODEL",
}


def _load_ai_config() -> dict:
    """Loads the `ai:` block from config.yaml safely (never raises)."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("ai", {}) or {}
    except Exception:
        return {}


_PROVIDERS = ("groq", "gemini", "nvidia")


def _bounded_number(value, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def get_ai_runtime_settings() -> dict:
    """Return bounded provider routing/retry settings from the existing config."""
    config = _load_ai_config()
    primary = str(config.get("primary_provider") or "groq").strip().lower()
    if primary not in _PROVIDERS:
        primary = "groq"

    secondary = str(config.get("secondary_provider") or "gemini").strip().lower()
    if secondary not in _PROVIDERS or secondary == primary:
        secondary = next(provider for provider in _PROVIDERS if provider != primary)

    # `max_retries` is retained as the legacy config key, but interpreted as the
    # total bounded attempts per provider to preserve the previous three-attempt
    # Groq/NVIDIA behavior without an off-by-one retry surprise.
    max_attempts = int(_bounded_number(config.get("max_retries"), 3, 1, 4))
    return {
        "primary_provider": primary,
        "secondary_provider": secondary,
        "timeout_seconds": _bounded_number(config.get("timeout_seconds"), 30.0, 5.0, 120.0),
        "max_attempts": max_attempts,
        "backoff_base_seconds": _bounded_number(
            config.get("rate_limit_backoff_base_seconds"), 2.0, 0.5, 10.0
        ),
    }


def preferred_models(provider: str) -> list[str]:
    """Owner's choices first (env var, then config.yaml), then the built-in default."""
    provider = provider.lower()
    chosen: list[str] = []
    env_name = _ENV_MAP.get(provider)
    if env_name:
        val = os.getenv(env_name)
        if val and val.strip():
            chosen.append(val.strip())
    models = _load_ai_config().get("models", {}) or {}
    cfg_val = models.get(provider)
    if cfg_val and str(cfg_val).strip():
        chosen.append(str(cfg_val).strip())
    chosen.append(_DEFAULTS.get(provider, _DEFAULTS["groq"]))
    return chosen


def get_model(provider: str) -> str:
    """Resolve the chat/embedding model ID for a provider.

    V2 Step E2: a model the provider retired is skipped automatically (next in
    the owner's choices, then the fallback list, then one the provider lists)."""
    from backend.app.brain import model_fallback

    return model_fallback.choose(provider, preferred_models(provider))


def retire_model(provider: str, model: str) -> Optional[str]:
    """The provider says `model` is gone: remember it; return the next model."""
    from backend.app.brain import model_fallback

    return model_fallback.mark_gone(provider, model, preferred_models(provider))


def get_embedding_dimensions() -> int:
    """Resolve the embedding vector dimensionality (must match stored vectors)."""
    env_val = os.getenv("GEMINI_EMBEDDING_DIMS")
    if env_val and env_val.strip().isdigit():
        return int(env_val.strip())

    dims = _load_ai_config().get("embedding_dimensions")
    if dims is not None and str(dims).strip().isdigit():
        return int(str(dims).strip())

    return int(_DEFAULTS["embedding_dims"])


def get_all_models() -> dict:
    """Return the effective, user-configurable model map used at runtime."""
    return {
        "groq": get_model("groq"),
        "gemini": get_model("gemini"),
        "nvidia": get_model("nvidia"),
        "embedding": get_model("embedding"),
        "embedding_dims": get_embedding_dimensions(),
    }


def validate_model_config() -> dict:
    """Validate obvious retired/malformed model IDs without making API calls."""
    models = get_all_models()
    errors = []
    for provider in ("groq", "gemini", "nvidia", "embedding"):
        value = str(models[provider]).strip()
        if not value or any(ch.isspace() for ch in value):
            errors.append(f"{provider} model ID is empty or contains whitespace")

    if models["groq"] in {"llama-3.1-8b-instant", "llama-3.3-70b-versatile"}:
        errors.append(f"Groq model is retired: {models['groq']}")
    if "gemini-1.5" in models["gemini"]:
        errors.append("Gemini 1.5 chat models are retired")
    if models["embedding"] in {"text-embedding-004", "embedding-001"}:
        errors.append(f"Embedding model is retired: {models['embedding']}")
    if models["nvidia"].startswith("nvidia/nvidia/"):
        errors.append("NVIDIA model contains a duplicated 'nvidia/' prefix")
    if ":free" in models["nvidia"]:
        errors.append("NVIDIA native API model must not use an OpenRouter ':free' suffix")

    dims = models["embedding_dims"]
    if not 128 <= dims <= 3072:
        errors.append("Embedding dimensions must be between 128 and 3072")

    return {"valid": not errors, "models": models, "errors": errors}
