"""Deterministic safety hints for browser voice transcripts.

This module never changes a command, chooses a tool, or inspects raw audio.
It identifies a deliberately small vocabulary of likely STT mismatches and a
small set of known ambiguous requests. The service layer can safely ask the
owner before any agent/tool execution when clarification is required.
"""

from __future__ import annotations

import re
from typing import TypedDict


class VoiceAliasSuggestion(TypedDict):
    heard: str
    suggested: str
    category: str


class VoiceClarification(TypedDict):
    question: str
    options: list[str]
    reason: str


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


def plan_voice_clarification(
    transcript: str,
    alias_suggestions: list[VoiceAliasSuggestion] | None = None,
) -> VoiceClarification | None:
    """Return a short clarification only for known ambiguity or unsafe vagueness.

    Returning ``None`` means the request is allowed through to the normal agent.
    This deliberately does not ask on every voice request.
    """
    text = str(transcript or "").strip()
    lowered = text.lower()
    aliases = list(alias_suggestions or [])

    if any(item["heard"] == "jora" for item in aliases):
        return {
            "question": "Did you mean Zora, sir?",
            "options": ["Yes, switch to Zora", "No, I meant something else"],
            "reason": "personality_alias",
        }

    exact_ambiguities: tuple[tuple[re.Pattern[str], VoiceClarification], ...] = (
        (
            re.compile(r"^open\s+code[.?!]*$", re.IGNORECASE),
            {
                "question": "I heard open code. Did you mean VS Code, Code Optimizer, or Code Graph?",
                "options": ["Open VS Code", "Open Code Optimizer", "Open Code Graph"],
                "reason": "open_code_ambiguous",
            },
        ),
        (
            re.compile(r"^(go\s+to|open)\s+(the\s+)?default[.?!]*$", re.IGNORECASE),
            {
                "question": "Did you mean the default Ultron personality, default app settings, or the home dashboard?",
                "options": ["Use Ultron personality", "Open app settings", "Show home dashboard"],
                "reason": "default_ambiguous",
            },
        ),
        (
            re.compile(r"^open\s+settings[.?!]*$", re.IGNORECASE),
            {
                "question": "Which settings do you want: voice, keys, or system settings?",
                "options": ["Voice settings", "API key settings", "System settings"],
                "reason": "settings_ambiguous",
            },
        ),
        (
            re.compile(r"^show\s+memory\s+code[.?!]*$", re.IGNORECASE),
            {
                "question": "Did you mean Memory, Code Optimizer, or Code Graph?",
                "options": ["Open Memory", "Open Code Optimizer", "Open Code Graph"],
                "reason": "memory_code_ambiguous",
            },
        ),
    )
    for pattern, clarification in exact_ambiguities:
        if pattern.fullmatch(text):
            return clarification

    # Vague destructive requests must name an exact target before the existing
    # confirmation gate is reached. Do not infer a path or filename.
    if re.fullmatch(r"(?:delete|remove|erase)\s+(?:the\s+)?(?:thing|file|folder|report|project)[.?!]*", lowered):
        return {
            "question": "Which exact file or folder should I delete?",
            "options": [],
            "reason": "unsafe_target_missing",
        }
    if re.fullmatch(r"(?:run|execute)\s+(?:a\s+)?command[.?!]*", lowered):
        return {
            "question": "Which exact command do you want me to run?",
            "options": [],
            "reason": "unsafe_command_missing",
        }

    return None
