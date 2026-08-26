"""Deterministic, non-destructive hints for browser voice transcripts.

This module never changes a command, chooses a tool, or inspects raw audio.
It only identifies a small approved vocabulary of likely STT mismatches so the
next clarification phase can ask the owner a short, honest question.
"""

from __future__ import annotations

import re
from typing import TypedDict


class VoiceAliasSuggestion(TypedDict):
    heard: str
    suggested: str
    category: str


# Keep this list intentionally short. Paths, dates, times, terminal commands,
# Git branches, URLs, numbers, names, credentials, and delete targets are never
# normalized by this layer.
_SAFE_VOICE_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("jora", "Zora", "personality"),
    ("ultorn", "Ultron", "personality"),
    ("calender", "Calendar", "widget"),
    ("remindar", "Reminder", "widget"),
    ("git hub", "GitHub", "service"),
)


def inspect_voice_aliases(transcript: str) -> list[VoiceAliasSuggestion]:
    """Return bounded known-word suggestions without modifying the transcript."""
    text = str(transcript or "")[:12000]
    suggestions: list[VoiceAliasSuggestion] = []
    for heard, suggested, category in _SAFE_VOICE_ALIASES:
        if re.search(rf"(?<![\w]){re.escape(heard)}(?![\w])", text, re.IGNORECASE):
            suggestions.append(
                {
                    "heard": heard,
                    "suggested": suggested,
                    "category": category,
                }
            )
    return suggestions[:3]
