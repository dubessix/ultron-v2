"""Today's real AI usage, from the provider's own numbers (for `ultron doctor`).

Groq counts `prompt_tokens - cached_tokens + completion_tokens` toward the free
limits; we store exactly that, per day, in one tiny JSON file. Only the last
14 days are kept. Never raises: a meter problem must never break a reply.
"""

from __future__ import annotations

import datetime
import json
import threading
from typing import Any, Optional

_lock = threading.Lock()
_DAYS_KEPT = 14


def _path():
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("usage_meter.json")


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def add(provider: str, usage: Optional[dict[str, Any]], today: Optional[str] = None,
        model: Optional[str] = None) -> None:
    """Record one finished AI call (usage = the provider's `usage` block)."""
    try:
        usage = usage if isinstance(usage, dict) else {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
        day = today or datetime.date.today().isoformat()
        with _lock:
            data = _load()
            row = data.setdefault(day, {}).setdefault(
                provider, {"calls": 0, "prompt": 0, "cached": 0, "completion": 0})
            row["calls"] += 1
            row["prompt"] += prompt
            row["cached"] += cached
            row["completion"] += completion
            if model:
                short = str(model).rsplit("/", 1)[-1][:40]
                per_model = row.setdefault("models", {})
                per_model[short] = per_model.get(short, 0) + max(0, prompt - cached) + completion
            for old in sorted(data)[:-_DAYS_KEPT]:
                data.pop(old, None)
            _save(data)
    except Exception:
        return


def today(day: Optional[str] = None) -> dict[str, dict[str, int]]:
    """{provider: {calls, prompt, cached, completion, counted}} for one day."""
    with _lock:
        rows = _load().get(day or datetime.date.today().isoformat(), {})
    result = {}
    for provider, row in rows.items():
        if not isinstance(row, dict):
            continue
        counted = max(0, row.get("prompt", 0) - row.get("cached", 0)) + row.get("completion", 0)
        result[provider] = {**row, "counted": counted}
    return result


def summary_line(groq_keys: int, day: Optional[str] = None) -> str:
    """Plain words, e.g. 'AI use today: 212 calls, 141K of 400K Groq tokens, cache hits 86%.'"""
    rows = today(day)
    if not rows:
        return "AI use today: no calls yet."
    calls = sum(r["calls"] for r in rows.values())
    groq = rows.get("groq")
    if not groq:
        return f"AI use today: {calls} calls (no Groq calls)."
    limit = 200_000 * max(1, groq_keys)
    hit = round(100 * groq["cached"] / groq["prompt"]) if groq["prompt"] else 0
    models = groq.get("models") or {}
    split = ""
    if len(models) > 1:
        split = " (" + ", ".join(f"{m} {v / 1000:.0f}K" for m, v in sorted(models.items())) + ")"
    return (f"AI use today: {calls} calls, {groq['counted'] / 1000:.0f}K of "
            f"{limit // 1000}K Groq tokens{split}, cache hits {hit}%.")
