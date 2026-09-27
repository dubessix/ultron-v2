"""Long goals (final list step 5): "finish React by December".

No new tool. A goal is a normal task in the project "Goals" (manage_task create,
project_name="Goals", due_date=...). Its steps are subtasks (parent_task_id).
Once a week the welcome-back status says one progress line per goal (top two),
built from local data: NO LLM call, zero tokens. Plain words only (voice).
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Optional

GOALS_PROJECT = "Goals"
MAX_SPOKEN = 2


def _as_local(value) -> Optional[_dt.datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        if len(text) == 10:
            return _dt.datetime.combine(_dt.date.fromisoformat(text), _dt.time(23, 59)).astimezone()
        moment = _dt.datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        return None
    return moment.astimezone() if moment.tzinfo else moment.replace(tzinfo=_dt.datetime.now().astimezone().tzinfo)


def _name(title) -> str:
    text = re.sub(r"^\s*goal\s*[:\-]\s*", "", str(title or ""), flags=re.I)
    return " ".join(re.sub(r"[^\w\s'.,-]", " ", text).split())[:80] or "your goal"


def is_goal(row: dict) -> bool:
    """A goal itself (not one of its steps)."""
    return (str(row.get("project_name") or "").strip().lower() == GOALS_PROJECT.lower()
            and not row.get("parent_task_id"))


def open_goals(conn) -> list[dict]:
    """Open goals with their step counts, soonest date first."""
    rows = [dict(r) for r in conn.execute(
        "SELECT id, title, due_date, created_at, project_name, parent_task_id FROM project_tasks "
        "WHERE lower(project_name) = ? AND (parent_task_id IS NULL OR parent_task_id = '') "
        "AND status != 'done' LIMIT 20", (GOALS_PROJECT.lower(),))]
    for goal in rows:
        counts = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) FROM project_tasks "
            "WHERE parent_task_id = ?", (goal["id"],)).fetchone()
        goal["steps"] = int(counts[0] or 0)
        goal["steps_done"] = int(counts[1] or 0)
    far = _dt.datetime.max.replace(tzinfo=_dt.timezone.utc)
    rows.sort(key=lambda g: _as_local(g.get("due_date")) or far)
    return rows


def _time_left(days: int) -> str:
    if days > 21:
        return f"about {round(days / 7)} weeks left"
    return "1 day left" if days == 1 else f"{days} days left"


def progress_line(goal: dict, now: _dt.datetime) -> str:
    """One spoken line: facts first, a pace hint only when the numbers say so."""
    name = _name(goal.get("title"))
    due = _as_local(goal.get("due_date"))
    steps, done = int(goal.get("steps") or 0), int(goal.get("steps_done") or 0)
    parts = []
    if steps:
        parts.append(f"{done} of {steps} steps done")
    if due is not None:
        days = (due.date() - now.date()).days
        if days < 0:
            late = -days
            return (f"Goal check, {name}: its date passed {late} day{'s' if late != 1 else ''} ago"
                    f"{', ' + parts[0] if parts else ''}. Shall I set a new date?")
        parts.append("due today" if days == 0 else _time_left(days))
        start = _as_local(goal.get("created_at"))
        if steps and start is not None and due > start:
            time_used = (now - start).total_seconds() / (due - start).total_seconds()
            work_done = done / steps
            if work_done + 0.2 < time_used:
                parts.append("a little behind pace")
            elif work_done >= time_used + 0.2:
                parts.append("ahead of pace")
    if not parts:
        return f"Goal check, {name}: still open. Want me to break it into steps?"
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Goal check, {name}: {body}."


def weekly_lines(conn, now: _dt.datetime) -> list[str]:
    try:
        return [progress_line(goal, now) for goal in open_goals(conn)[:MAX_SPOKEN]]
    except Exception as exc:  # an old database without the table must never break the greeting
        print(f"[GOALS] unavailable: {exc}")
        return []


def week_key(now: _dt.datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"
