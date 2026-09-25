"""Arrival briefing + heads-up warnings (V2 Step 8).

* Arrival: when the owner comes back after >= 2 hours away, Ultron speaks 2-3
  sentences: reminders that fired while he was away, today's open tasks, and
  the next event. Built from local data - NO LLM call, zero tokens.
* Heads-up: "Sir, your deadline is in 1 hour." / "Your meeting starts in 15
  minutes." - checked once a minute, each warning spoken only once.
All speech is plain words (no symbols) so the voice never reads characters.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
from pathlib import Path
from typing import Optional

AWAY_SECONDS = 2 * 3600
TASK_WARN_MINUTES = 60
EVENT_WARN_MINUTES = 15
_lock = threading.Lock()


def _state_path() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("presence.json")


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


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _as_local(value) -> Optional[_dt.datetime]:
    """ISO text / date -> aware local datetime. Naive values are local time."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        if len(text) == 10:  # plain date = end of that day
            day = _dt.date.fromisoformat(text)
            return _dt.datetime.combine(day, _dt.time(23, 59)).astimezone()
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()


def _clock(moment: _dt.datetime) -> str:
    """7:05 PM -> '7:05 PM', 7:00 -> '7 PM' (spoken naturally)."""
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    return f"{hour} {suffix}" if moment.minute == 0 else f"{hour}:{moment.minute:02d} {suffix}"


def _minutes_text(minutes: int) -> str:
    if minutes >= 55:
        return "1 hour"
    if minutes <= 1:
        return "a minute"
    return f"{minutes} minutes"


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _clean(title: str) -> str:
    return " ".join(str(title or "").replace("_", " ").split()).strip(" .")[:80]


# ---------------------------------------------------------------------------
# presence
# ---------------------------------------------------------------------------
def last_seen() -> Optional[_dt.datetime]:
    value = _load().get("last_seen")
    return _as_local(value) if value else None


def touch(moment: Optional[_dt.datetime] = None) -> None:
    """The owner is here (any chat, voice, click, or key press)."""
    with _lock:
        data = _load()
        data["last_seen"] = (moment or _now()).isoformat()
        try:
            _save(data)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def _gather(since: _dt.datetime, now: _dt.datetime) -> dict:
    from backend.app.database.db import get_db_connection

    since_utc = since.astimezone(_dt.timezone.utc).isoformat()
    with get_db_connection() as conn:
        missed = [dict(r) for r in conn.execute(
            "SELECT title, type, fired_at FROM reminder_inbox WHERE fired_at >= ? ORDER BY fired_at LIMIT 20",
            (since_utc,))]
        tasks = [dict(r) for r in conn.execute(
            "SELECT title, priority, due_date, status FROM project_tasks WHERE status != 'done' LIMIT 200")]
        events = [dict(r) for r in conn.execute("SELECT title, start_time FROM calendar_events LIMIT 500")]
    end_of_day = now.replace(hour=23, minute=59, second=59)
    today_tasks = []
    for task in tasks:
        due = _as_local(task.get("due_date"))
        if due is not None and due <= end_of_day:
            today_tasks.append({**task, "_due": due, "overdue": due < now})
        elif due is None and task.get("priority") == "high":
            today_tasks.append({**task, "_due": None, "overdue": False})
    rank = {"high": 0, "medium": 1, "low": 2}
    today_tasks.sort(key=lambda t: (not t["overdue"], rank.get(t.get("priority"), 1), t["_due"] or end_of_day))
    upcoming = []
    for event in events:
        start = _as_local(event.get("start_time"))
        if start is not None and now <= start <= now + _dt.timedelta(hours=24):
            upcoming.append({**event, "_start": start})
    upcoming.sort(key=lambda e: e["_start"])
    return {"missed": missed, "tasks": today_tasks, "next_event": upcoming[0] if upcoming else None}


def _greeting(now: _dt.datetime, owner: str) -> str:
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    return f"Good {part}, {owner}. Welcome back."


def compose(data: dict, now: _dt.datetime, owner: str = "Sir") -> str:
    sentences = [_greeting(now, owner)]
    missed = data["missed"]
    if missed:
        names = [_clean(m["title"]) for m in missed[:3]]
        more = len(missed) - len(names)
        tail = f" and {more} more" if more > 0 else ""
        word = "reminder" if len(missed) == 1 else "reminders"
        sentences.append(f"While you were away, {len(missed)} {word} went off: {_join(names)}{tail}.")
    tasks = data["tasks"]
    event = data["next_event"]
    parts = []
    if tasks:
        overdue = sum(1 for t in tasks if t["overdue"])
        top = _clean(tasks[0]["title"])
        label = "task" if len(tasks) == 1 else "tasks"
        extra = f", {overdue} overdue" if overdue else ""
        parts.append(f"you have {len(tasks)} {label} for today{extra}, starting with {top}")
    if event:
        when = event["_start"]
        day = "" if when.date() == now.date() else " tomorrow"
        parts.append(f"next up is {_clean(event['title'])} at {_clock(when)}{day}")
    if parts:
        sentence = _join(parts)
        sentences.append(sentence[0].upper() + sentence[1:] + ".")
    if len(sentences) == 1:
        sentences.append("Nothing needs you right now.")
    return " ".join(sentences)


def briefing(force: bool = False, now: Optional[_dt.datetime] = None, owner: str = "Sir") -> Optional[dict]:
    """The welcome-back payload if he was away >= 2 hours (or force); updates presence."""
    now = now or _now()
    seen = last_seen()
    away = (now - seen).total_seconds() if seen else None
    touch(now)
    if not force and (away is None or away < AWAY_SECONDS):
        return None
    since = seen or (now - _dt.timedelta(hours=12))
    try:
        data = _gather(since, now)
    except Exception as exc:
        print(f"[ARRIVAL] briefing data unavailable: {exc}")
        return None
    return {
        "type": "arrival_briefing",
        "speech": compose(data, now, owner),
        "away_minutes": int(away // 60) if away is not None else None,
        "missed": [_clean(m["title"]) for m in data["missed"]],
        "tasks": [_clean(t["title"]) for t in data["tasks"][:5]],
        "next_event": ({"title": _clean(data["next_event"]["title"]),
                        "start": data["next_event"]["_start"].isoformat()} if data["next_event"] else None),
    }


# ---------------------------------------------------------------------------
# heads-up warnings
# ---------------------------------------------------------------------------
def due_warnings(now: Optional[_dt.datetime] = None, owner: str = "Sir") -> list[dict]:
    """Warnings to speak now; each (kind, title, time) only once."""
    from backend.app.database.db import get_db_connection

    now = now or _now()
    with get_db_connection() as conn:
        tasks = [dict(r) for r in conn.execute(
            "SELECT id, title, due_date FROM project_tasks WHERE status != 'done' AND due_date IS NOT NULL LIMIT 300")]
        events = [dict(r) for r in conn.execute("SELECT id, title, start_time FROM calendar_events LIMIT 500")]
    out: list[dict] = []
    with _lock:
        state = _load()
        warned = set(state.get("warned") or [])
        for task in tasks:
            if len(str(task.get("due_date") or "")) == 10:
                continue  # date-only deadlines have no exact hour to warn about
            due = _as_local(task["due_date"])
            if due is None:
                continue
            minutes = int((due - now).total_seconds() // 60)
            key = f"task|{task['id']}|{due.isoformat()}"
            if 0 <= minutes <= TASK_WARN_MINUTES and key not in warned:
                warned.add(key)
                out.append({"type": "heads_up", "kind": "deadline", "title": _clean(task["title"]),
                            "minutes": minutes,
                            "speech": f"{owner}, heads up: {_clean(task['title'])} is due in {_minutes_text(minutes)}."})
        for event in events:
            start = _as_local(event["start_time"])
            if start is None:
                continue
            minutes = int((start - now).total_seconds() // 60)
            key = f"event|{event['id']}|{start.isoformat()}"
            if 0 <= minutes <= EVENT_WARN_MINUTES and key not in warned:
                warned.add(key)
                out.append({"type": "heads_up", "kind": "event", "title": _clean(event["title"]),
                            "minutes": minutes,
                            "speech": f"{owner}, {_clean(event['title'])} starts in {_minutes_text(minutes)}, at {_clock(start)}."})
        if out:
            state["warned"] = sorted(warned)[-500:]
            try:
                _save(state)
            except OSError:
                pass
    return out


def clear() -> None:
    with _lock:
        try:
            _state_path().unlink()
        except OSError:
            pass
