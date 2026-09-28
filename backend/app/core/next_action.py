"""Suggest the next action (final list step 6).

After a finished job, ONE short offer: "Next on your list: X. Want to start on it?"
Recommend once, then respect: the same task at most once a day, at most one
offer every two hours, never at night, never when the reply already asks a
question, never after list/plan tools (they already talk about the list), never
in coding jobs or after a failed step. Local data only: NO LLM call, 0 tokens.
Plain words only (the voice reads it).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

MIN_GAP_SECONDS = 2 * 3600
QUIET_HOURS = (23, 6)  # from 11 pm to 6 am: no offers
# These tools already talk about the list/plan, so an offer would repeat them.
LIST_TOOLS = {
    "manage_task", "manage_calendar", "manage_reminder", "daily_briefing", "universal_search",
    "manage_memory", "jarvis_actions", "routine",
}
_lock = threading.Lock()


def _state_path() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("next_action.json")


def _load() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def clear() -> None:
    try:
        _state_path().unlink()
    except OSError:
        pass


def _words(title) -> str:
    return " ".join(re.sub(r"[^\w\s'.,-]", " ", str(title or "")).split())[:80]


def _next_task(now: _dt.datetime, skip: set[str]) -> Optional[dict]:
    """The top open task for today: overdue first, then high priority, then soonest due."""
    from backend.app.core import goals
    from backend.app.core.arrival import _as_local
    from backend.app.database.db import get_db_connection

    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    with get_db_connection() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, title, priority, due_date, project_name, parent_task_id FROM project_tasks "
            "WHERE status != 'done' LIMIT 300")]
    picks = []
    for task in rows:
        if task["id"] in skip or goals.is_goal(task) or not _words(task.get("title")):
            continue
        due = _as_local(task.get("due_date"))
        if due is not None and due <= end_of_day:
            picks.append((0 if due < now else 1, {"high": 0, "medium": 1, "low": 2}.get(task.get("priority"), 1),
                          due, task))
        elif due is None and task.get("priority") == "high":
            picks.append((1, 0, end_of_day, task))
    if not picks:
        return None
    picks.sort(key=lambda p: p[:3])
    return picks[0][3]


def suggest(content: str, results: list, *, coding_turn: bool = False,
            now: Optional[_dt.datetime] = None) -> str:
    """content + one offer line when it truly fits; otherwise content unchanged."""
    try:
        text = str(content or "").rstrip()
        done = [r for r in results or [] if isinstance(r, dict)]
        if coding_turn or not text or not done or text.endswith("?"):
            return content
        from backend.app.core.control_tools import CONTROL_TOOL_IDS

        if any(not r.get("success") or (r.get("result") or {}).get("needs_yes") for r in done):
            return content  # a failed step, or a step still waiting for the owner's yes
        if {str(r.get("tool")) for r in done} & (LIST_TOOLS | CONTROL_TOOL_IDS):
            return content
        now = now or _dt.datetime.now().astimezone()
        start, end = QUIET_HOURS
        if now.hour >= start or now.hour < end:
            return content
        with _lock:
            state = _load()
            last = state.get("last_at")
            if last:
                try:
                    if (now - _dt.datetime.fromisoformat(last)).total_seconds() < MIN_GAP_SECONDS:
                        return content
                except (TypeError, ValueError):
                    pass
            today = now.date().isoformat()
            said = set(state.get("said", {}).get(today, []))
            task = _next_task(now, said)
            if task is None:
                return content
            name = _words(task["title"])
            if name.lower() in text.lower():
                return content  # the reply already talks about it
            state = {"last_at": now.isoformat(), "said": {today: sorted(said | {task["id"]})}}
            try:
                _save(state)
            except OSError:
                pass
        return f"{text} Next on your list: {name}. Want to start on it?"
    except Exception as exc:  # an offer must never break a finished job
        print(f"[NEXT_ACTION] skipped: {exc}")
        return content
