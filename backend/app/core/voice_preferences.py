"""Owner-approved persistent aliases for browser voice transcripts.

Only the owner can save a preference through the explicit clarification UI.
This module stores a bounded allowlist in existing persistent metadata; it never
learns aliases from a transcript automatically and never handles paths, dates,
commands, or other sensitive values.
"""

from __future__ import annotations

import json
import re
from typing import Mapping

from backend.app.memory.persistent_memory import PersistentMemory


_PREFERENCE_KEY = "voice_alias_preferences.v1"
_MAX_ALIASES = 20
# These are the only pairs that the current clarification UI can offer/store.
_APPROVABLE_ALIASES = {
    "jora": "Zora",
    "ultorn": "Ultron",
}


def _clean_alias(value: str) -> str:
    return str(value or "").strip().lower()


def _load() -> dict[str, str]:
    raw = PersistentMemory().get(_PREFERENCE_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    valid: dict[str, str] = {}
    for alias, canonical in parsed.items():
        clean = _clean_alias(alias)
        expected = _APPROVABLE_ALIASES.get(clean)
        if expected and canonical == expected:
            valid[clean] = expected
    return valid


def get_approved_voice_aliases() -> dict[str, str]:
    """Return a copy of exact owner-approved alias mappings."""
    return dict(_load())


def remember_voice_alias(alias: str, canonical: str) -> dict[str, str]:
    """Persist one explicitly approved and allowlisted voice alias."""
    clean = _clean_alias(alias)
    expected = _APPROVABLE_ALIASES.get(clean)
    if expected is None or canonical != expected:
        raise ValueError("This voice alias cannot be saved.")
    preferences = _load()
    preferences[clean] = expected
    bounded = dict(list(sorted(preferences.items()))[:_MAX_ALIASES])
    PersistentMemory().set(_PREFERENCE_KEY, json.dumps(bounded, sort_keys=True))
    return bounded


def apply_approved_voice_aliases(transcript: str, aliases: Mapping[str, str] | None = None) -> str:
    """Use only owner-approved exact word replacements for agent interpretation."""
    text = str(transcript or "")
    for alias, canonical in (aliases or {}).items():
        text = re.sub(rf"(?<![\w]){re.escape(alias)}(?![\w])", canonical, text, flags=re.IGNORECASE)
    return text
