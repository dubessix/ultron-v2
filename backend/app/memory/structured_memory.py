"""M2 deterministic structure for durable project memories.

This module never invents facts. It classifies exact owner/assistant text into a
small stable taxonomy, redacts common secrets, and attaches auditable metadata
before the existing vector store persists it.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from typing import Any, Iterable, Optional


STRUCTURED_MEMORY_SCHEMA_VERSION = 1
ALLOWED_MEMORY_CATEGORIES = (
    "explicit",
    "owner_preference",
    "decision",
    "project_fact",
    "task",
    "goal",
    "problem",
    "solution",
    "session_event",
)
ALLOWED_IMPORTANCE = ("low", "normal", "high", "critical")

_CATEGORY_ALIASES = {
    "preference": "owner_preference",
    "preferences": "owner_preference",
    "fact": "project_fact",
    "architecture": "project_fact",
    "work": "project_fact",
    "todo": "task",
    "issue": "problem",
    "bug": "problem",
    "fix": "solution",
    "event": "session_event",
    "episodic": "session_event",
    "emotional": "session_event",
    "semantic": "project_fact",
    "filesystem": "project_fact",
    "memory": "explicit",
}
_IMPORTANCE_ALIASES = {"medium": "normal", "urgent": "critical", "important": "high"}

_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "owner_preference",
        re.compile(
            r"\b(i prefer|i like|i dislike|i don'?t want|my preference|always use|never use|"
            r"please keep|for me)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "decision",
        re.compile(
            r"\b(we decided|decision|decided to|we chose|choose|selected|final choice|will use)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "goal",
        re.compile(
            r"\b(our goal|my goal|goal is|aim to|want to build|we want to|roadmap|long[- ]term)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "task",
        re.compile(
            r"\b(todo|to-do|need to|next step|remind me|must implement|action item|"
            r"follow up|study plan|study schedule|exam|deadline)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "problem",
        re.compile(
            r"\b(bug|error|issue|problem|mistake|broken|fails?|failure|not working|blocked)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "solution",
        re.compile(
            r"\b(fixed|resolved|solution|lesson learned|workaround|repair(?:ed)?|"
            r"root cause|corrected)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "project_fact",
        re.compile(
            r"\b(project uses|tech stack|architecture|database|backend|frontend|api|framework|"
            r"repository|codebase|model|provider)\b",
            re.IGNORECASE,
        ),
    ),
)

_SECRET_ASSIGNMENT = re.compile(
    r"\b([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)"
    r"\s*([:=])\s*([^\s,;]+)",
    re.IGNORECASE,
)
_SECRET_PREFIX = re.compile(
    r"\b(?:gsk_|ghp_|github_pat_|nvapi-|AIza)[A-Za-z0-9_-]{8,}",
    re.IGNORECASE,
)
_IMPORTANT_HINT = re.compile(
    r"\b(important|high priority|must remember|never forget|critical|always|never|final decision)\b",
    re.IGNORECASE,
)
_CRITICAL_HINT = re.compile(r"\b(critical|never forget|must always)\b", re.IGNORECASE)


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return _SECRET_PREFIX.sub("[REDACTED]", text)


def bounded_text(value: Any, limit: int) -> str:
    compact = " ".join(redact_sensitive_text(value).split())
    return compact if len(compact) <= limit else compact[: max(0, limit - 1)].rstrip() + "…"


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_category(category: Any) -> Optional[str]:
    clean = str(category or "").strip().lower().replace("-", "_").replace(" ", "_")
    clean = _CATEGORY_ALIASES.get(clean, clean)
    return clean if clean in ALLOWED_MEMORY_CATEGORIES else None


def normalize_importance(importance: Any) -> Optional[str]:
    clean = str(importance or "").strip().lower()
    clean = _IMPORTANCE_ALIASES.get(clean, clean)
    return clean if clean in ALLOWED_IMPORTANCE else None


def classify_category(user_prompt: str, ai_response: str = "") -> str:
    combined = f"{user_prompt}\n{ai_response}"
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(combined):
            return category
    return "session_event"


def classify_importance(user_prompt: str, category: str) -> str:
    if _CRITICAL_HINT.search(user_prompt):
        return "critical"
    if _IMPORTANT_HINT.search(user_prompt) or category in {
        "owner_preference",
        "decision",
        "goal",
        "problem",
    }:
        return "high"
    return "normal"


def build_structured_turn_memory(
    user_prompt: str,
    ai_response: str,
    *,
    project_id: str,
    session_id: Optional[str],
) -> Optional[dict[str, Any]]:
    """Create one exact structured memory payload, or None for empty text."""
    owner_text = bounded_text(user_prompt, 600)
    outcome_text = bounded_text(ai_response, 600)
    if not owner_text:
        return None
    category = classify_category(owner_text, outcome_text)
    importance = classify_importance(owner_text, category)
    content = f"Owner: {owner_text}"
    if outcome_text:
        content += f"\nAssistant outcome: {outcome_text}"
    created_at = utc_now()
    return {
        "content": content,
        "metadata": {
            "schema_version": STRUCTURED_MEMORY_SCHEMA_VERSION,
            "kind": "structured_turn",
            "source": "automatic_exact_turn",
            "project_id": str(project_id or "personal"),
            "session_id": session_id,
            "category": category,
            "importance": importance,
            "revision": 1,
            "content_sha256": content_sha256(content),
            "created_at": created_at,
            "updated_at": created_at,
        },
    }


def explicit_memory_metadata(
    *,
    project_id: str,
    category: Any,
    importance: Any,
    content: str,
    **extra: Any,
) -> Optional[dict[str, Any]]:
    normalized_category = normalize_category(category)
    normalized_importance = normalize_importance(importance)
    if normalized_category is None or normalized_importance is None:
        return None
    now = utc_now()
    return {
        "schema_version": STRUCTURED_MEMORY_SCHEMA_VERSION,
        "kind": "explicit_remember",
        "source": "user",
        "project_id": project_id,
        "category": normalized_category,
        "importance": normalized_importance,
        "revision": 1,
        "content_sha256": content_sha256(content),
        "created_at": now,
        "updated_at": now,
        **extra,
    }


def corrected_memory_metadata(existing: dict[str, Any], new_content: str) -> dict[str, Any]:
    current = dict(existing.get("metadata") or {})
    previous_hash = content_sha256(str(existing.get("content") or ""))
    history = list(current.get("correction_history") or [])[-9:]
    history.append(previous_hash)
    current.update(
        {
            "schema_version": STRUCTURED_MEMORY_SCHEMA_VERSION,
            "revision": int(current.get("revision") or 1) + 1,
            "previous_content_sha256": previous_hash,
            "correction_history": history,
            "content_sha256": content_sha256(new_content),
            "corrected": True,
            "updated_at": utc_now(),
        }
    )
    return current


def memory_inventory(memories: Iterable[dict[str, Any]], project_id: str) -> dict[str, Any]:
    categories = {category: 0 for category in ALLOWED_MEMORY_CATEGORIES}
    importance = {level: 0 for level in ALLOWED_IMPORTANCE}
    types: dict[str, int] = {}
    total = 0
    for item in memories:
        metadata = dict(item.get("metadata") or {})
        if metadata.get("project_id", "personal") != project_id:
            continue
        category = normalize_category(metadata.get("category")) or "session_event"
        level = normalize_importance(metadata.get("importance")) or "normal"
        mem_type = str(item.get("type") or "unknown")
        categories[category] += 1
        importance[level] += 1
        types[mem_type] = types.get(mem_type, 0) + 1
        total += 1
    return {
        "project_id": project_id,
        "total": total,
        "categories": categories,
        "importance": importance,
        "types": dict(sorted(types.items())),
    }
