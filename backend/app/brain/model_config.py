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

import yaml

from backend.app.install_paths import CONFIG_PATH

# Currently-valid, long-runway defaults (verified against provider docs 2026-08-14):
#   - gemini-3.5-flash    : stable flagship flash, valid to ~May 2027
#   - gemini-embedding-001: stable embeddings, flexible dims, valid to >=May 2028
_DEFAULTS = {
    "groq": "llama-3.1-8b-instant",
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


def get_model(provider: str) -> str:
    """Resolve the chat/embedding model ID for a provider."""
    provider = provider.lower()
    env_name = _ENV_MAP.get(provider)
    if env_name:
        val = os.getenv(env_name)
        if val and val.strip():
            return val.strip()

    models = _load_ai_config().get("models", {}) or {}
    cfg_val = models.get(provider)
    if cfg_val and str(cfg_val).strip():
        return str(cfg_val).strip()

    return _DEFAULTS.get(provider, _DEFAULTS["groq"])


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
