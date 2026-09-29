"""Last check on every reply before the owner sees or hears it.

1. Hidden characters: zero-width marks some models leak are removed.
2. Leaked thinking: lines like "The user asked..." or "We need to respond..."
   are the model talking to itself, not to the owner. They are cut.
3. Nothing left: never an empty or bare "Done". Say the real result instead.
4. "Done" with no tool: the brain said it did something but no tool ran this
   turn. `claims_action` spots it so the orchestrator can ask the brain once
   more to really do it (see orchestrator), and `unfinished_claim_reply` is
   the honest line if it still does not.

Only whole sentences with clear leak/claim wording are touched, so a normal
reply is returned exactly as it came.
"""

from __future__ import annotations

import re
from typing import Iterable

_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060\ufeff]")

# The model talking to itself about the conversation (whole sentence only).
_LEAK = re.compile(
    r"^\s*(?:"
    r"the user(?:'s)? (?:said|says|asked|asks|is asking|wants|wanted|requested|requests|just said|message)"
    r"|the assistant (?:should|must|will|needs|is going)"
    r"|(?:we|i) (?:need|have|should|must) to (?:respond|answer|reply|output|produce|call the|use the|tell the user)"
    r"|need to (?:respond|answer|reply|output)"
    r"|let'?s (?:respond|answer|reply|output|produce)"
    r"|let me (?:respond|reply)(?: to the user)?\b"
    r"|so (?:we|i) (?:should|will) (?:respond|answer|reply)"
    r")",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")

# "I've opened...", "Done.", "All set": a first-person claim that work happened now.
_CLAIM_VERBS = (
    r"opened|closed|scheduled|marked|booked|set(?: up)?|added|saved|created|moved|deleted|"
    r"started|launched|played|paused|resumed|muted|unmuted|stopped|sent|turned|reminded|"
    r"updated|renamed|copied|written|wrote|installed|downloaded|removed|cleared|changed|"
    r"put|noted|killed|finished|completed"
)
_CLAIM = re.compile(
    r"(?:^|[.!?]\s+)(?:(?:okay|ok|sure|right|yes|alright|very well)[,!]?\s+)?(?:sir[,!]?\s+)?"
    r"(?:(?:done|all set)(?:[.!,]|\s*$)"
    r"|i(?:'?ve| have)?(?: just)? (?:" + _CLAIM_VERBS + r")\b)",
    re.IGNORECASE,
)
# Talking about an earlier turn is not a lie ("I set that reminder yesterday").
_EARLIER = re.compile(r"\b(earlier|already|yesterday|before|last time|previously|this morning)\b", re.I)


def _last_result_line(results: list[dict]) -> str:
    for item in reversed(results):
        if not isinstance(item, dict) or not item.get("success"):
            continue
        data = item.get("result") if isinstance(item.get("result"), dict) else {}
        message = str(data.get("message") or "").strip()
        if 2 <= len(message.split()) <= 30:
            return message.rstrip(".") + ", Sir."
        name = str(item.get("tool") or "the").replace("_", " ")
        return f"That's done, Sir. The {name} step worked."
    return ""


def fallback_line(results: Iterable[dict] | None) -> str:
    """A short true line when the brain gave no usable words."""
    items = [r for r in results or [] if isinstance(r, dict)]
    line = _last_result_line(items)
    if line:
        return line
    if items:  # tools ran but none worked: honest_reply normally says it first
        return "That did not work, Sir."
    return "Sorry, Sir, I lost my words there. Could you say that again?"


def scrub(text: str, results: Iterable[dict] | None = None) -> str:
    """Remove hidden marks and leaked self-talk; never return empty words."""
    original = str(text or "")
    cleaned = _ZERO_WIDTH.sub("", original)
    parts = [p for p in _SENTENCE.split(cleaned) if p.strip()]
    kept = [p for p in parts if not _LEAK.match(p)]
    if len(kept) != len(parts):
        cleaned = " ".join(p.strip() for p in kept)
        if len(cleaned.split()) < 3:
            return fallback_line(results)
    cleaned = cleaned.strip()
    if not cleaned:
        return fallback_line(results)
    return cleaned if cleaned != original.strip() else original.strip()


def claims_action(text: str) -> bool:
    """True when the reply says work was just done (used only when no tool ran)."""
    value = str(text or "")
    return bool(_CLAIM.search(value)) and not _EARLIER.search(value)


RETRY_NOTE = (
    "\n\n[Check] Your last answer said something was done, but no tool ran this turn, "
    "so nothing happened on the PC. If the owner wants an action, call the tool now. "
    "If you were only talking about something done earlier, answer without claiming new work."
)


def unfinished_claim_reply() -> str:
    return "I have not done that yet, Sir. Should I do it now?"
