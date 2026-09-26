"""V2 Step E: what Ultron always knows about the owner (like Jarvis knows Tony).

A tiny block with the facts the owner told Ultron to keep (names, family, likes,
dates, decisions, goals) rides along with every order, so Ultron never asks
"what is your sister's name?" twice. It is bounded (a few hundred characters,
about 100 tokens) and only built from saved facts, never invented. Everything
else stays in the searchable memory (manage_memory search) at zero token cost.

It is cached in RAM and rebuilt only after a memory write (memory_version).
"""

from __future__ import annotations

import threading
from typing import Optional

MAX_CHARS = 600       # ~150 tokens at most; usually far less
MAX_FACTS = 14
FACT_CHARS = 140

_lock = threading.Lock()
_cache: dict[str, tuple[int, str]] = {}


def _one_line(text: str) -> str:
    line = " ".join(str(text or "").split())
    # remembered chat turns start with "Owner: ...": keep only his words
    if line.lower().startswith("owner:"):
        line = line[6:].strip()
        cut = line.lower().find(" assistant")
        if cut > 0:
            line = line[:cut].strip()
    return line[: FACT_CHARS - 1] + "…" if len(line) > FACT_CHARS else line


def _always_known(meta: dict) -> bool:
    return (
        meta.get("kind") == "explicit_remember"
        or meta.get("category") == "owner_preference"
        or meta.get("importance") == "critical"
    )


def build_core_profile(project_id: str = "personal", store=None) -> str:
    """Return the always-known block ('' when nothing is saved yet). Never raises."""
    try:
        from backend.app.memory import vector_store as vs

        version = vs.memory_version()
        key = str(project_id or "personal")
        with _lock:
            cached = _cache.get(key)
        if cached and cached[0] == version and store is None:
            return cached[1]

        store = store or vs.VectorStore()
        rows = store.list_recent_memories(limit=60, project_id="personal", kept_only=True)
        if key != "personal":
            rows += store.list_recent_memories(limit=20, project_id=key, kept_only=True)
        # Always-known = facts he told Ultron to keep, his preferences, critical items.
        # (Automatic decisions/goals are kept forever too, but found by search.)
        rows = [r for r in rows if _always_known(r.get("metadata") or {})]
        # explicit "remember this" facts first, then preferences; newest first
        rows.sort(key=lambda r: 0 if (r.get("metadata") or {}).get("kind") == "explicit_remember" else 1)

        facts: list[str] = []
        seen: set[str] = set()
        used = 0
        for row in rows:
            line = _one_line(row.get("content", ""))
            norm = line.lower()
            if not line or norm in seen:
                continue
            if used + len(line) + 3 > MAX_CHARS or len(facts) >= MAX_FACTS:
                break
            seen.add(norm)
            facts.append(line)
            used += len(line) + 3
        block = ""
        if facts:
            block = (
                "\n\nWHAT YOU KNOW ABOUT THE OWNER (he told you; use it naturally, never recite it; "
                "newer facts win; for anything else call manage_memory search):\n"
                + "\n".join(f"- {fact}" for fact in facts)
            )
        with _lock:
            _cache[key] = (version, block)
        return block
    except Exception as exc:  # memory must never break a turn
        print(f"[CORE_PROFILE] skipped: {exc}")
        return ""


def forget_cache(project_id: Optional[str] = None) -> None:
    with _lock:
        if project_id is None:
            _cache.clear()
        else:
            _cache.pop(project_id, None)
