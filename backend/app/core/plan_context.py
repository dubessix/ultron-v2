"""What is coming up and where he is in today's plan (0 LLM calls).

* soon_line()  -> "[Soon] Physics exam Mon 28 Sep 10:00 (tomorrow)" for every
  AI call, so Ultron knows about exams and deadlines even in a new chat.
* plan_line()  -> "[Plan today] done 1 of 4 · now Physics block 2 until 20:15"
  only on days with plan blocks (manage_calendar action=plan).
* plan_speech() -> the lines the once-a-minute heads-up loop speaks when a plan
  block starts ("Physics block 2 starts now, Sir.") or ends ("…Finished it, or
  ten more minutes?"). Spoken from local data, never an AI call.
* arrival_sentences() -> exam countdown + plan progress for the welcome-back
  briefing.

Everything is small and bounded; empty strings when nothing is coming up, so a
normal day costs 0 extra tokens. Plain words only (the voice reads them).
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Optional

SOON_DAYS = 3
MAX_SOON = 4
START_WINDOW_MIN = 5   # speak "starts now" up to 5 minutes late (PC was busy)
END_WINDOW_MIN = 5


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _local(value) -> Optional[_dt.datetime]:
    try:
        parsed = _dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone()  # naive = owner-local time


def _clock(moment: _dt.datetime) -> str:
    return moment.strftime("%H:%M")


def _spoken_clock(moment: _dt.datetime) -> str:
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}:{moment.minute:02d} {suffix}" if moment.minute else f"{hour} {suffix}"


def _clean(title) -> str:
    return " ".join(str(title or "").replace("_", " ").split())[:80]


def _extra(event: dict) -> dict:
    try:
        data = json.loads(event.get("description") or "{}")
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _day_word(when: _dt.datetime, now: _dt.datetime) -> str:
    days = (when.date() - now.date()).days
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"


def _events() -> list[dict]:
    from backend.app.database.db import get_db_connection

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, description, start_time, end_time, category FROM calendar_events LIMIT 800"
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["_start"], item["_end"] = _local(item.get("start_time")), _local(item.get("end_time"))
        if item["_start"] is not None and item["_end"] is not None:
            out.append(item)
    return out


def _is_plan(event: dict) -> bool:
    return str(event.get("category") or "").startswith("plan")


def _today_plan(events: list[dict], now: _dt.datetime, days_back: int = 0) -> list[dict]:
    day = now.date() - _dt.timedelta(days=days_back)
    blocks = [e for e in events if _is_plan(e) and e["_start"].date() == day]
    return sorted(blocks, key=lambda e: e["_start"])


def _work(blocks: list[dict]) -> list[dict]:
    """Blocks that count as work (the sleep block has check_in false)."""
    return [b for b in blocks if _extra(b).get("check_in", True)]


def _progress(blocks: list[dict]) -> tuple[int, int, int]:
    work = _work(blocks)
    done = sum(1 for b in work if b["category"] == "plan_done")
    skipped = sum(1 for b in work if b["category"] == "plan_skipped")
    return done, skipped, len(work)


# --------------------------------------------------------------------------- prompt lines
def soon_line(now: Optional[_dt.datetime] = None, events: Optional[list[dict]] = None) -> str:
    """Exams, deadlines and events in the next few days (not plan blocks)."""
    try:
        now = now or _now()
        events = _events() if events is None else events
        horizon = now + _dt.timedelta(days=SOON_DAYS)
        soon = sorted((e for e in events if not _is_plan(e) and e["_end"] >= now and e["_start"] <= horizon),
                      key=lambda e: e["_start"])[:MAX_SOON]
        if not soon:
            return ""
        parts = [f"{_clean(e['title'])} {e['_start'].strftime('%a %d %b')} {_clock(e['_start'])} "
                 f"({_day_word(e['_start'], now)})" for e in soon]
        return "[Soon] " + " · ".join(parts)
    except Exception:
        return ""


def plan_line(now: Optional[_dt.datetime] = None, events: Optional[list[dict]] = None) -> str:
    try:
        now = now or _now()
        events = _events() if events is None else events
        blocks = _today_plan(events, now)
        if not blocks:
            return ""
        done, skipped, total = _progress(blocks)
        parts = [f"done {done} of {total}" + (f", skipped {skipped}" if skipped else "")]
        current = next((b for b in blocks if b["category"] == "plan" and b["_start"] <= now < b["_end"]), None)
        upcoming = next((b for b in blocks if b["category"] == "plan" and b["_start"] > now), None)
        missed = [b for b in _work(blocks) if b["category"] == "plan" and b["_end"] <= now]
        if current:
            parts.append(f"now {_clean(current['title'])} until {_clock(current['_end'])}")
        if upcoming:
            parts.append(f"next {_clean(upcoming['title'])} at {_clock(upcoming['_start'])}")
        if missed:
            parts.append(f"not checked: {', '.join(_clean(b['title']) for b in missed[:3])}")
        last = blocks[-1]
        if _extra(last).get("check_in", True):
            parts.append(f"plan ends {_clock(last['_end'])}")
        else:
            parts.append(f"lights out {_clock(last['_start'])}")
        return "[Plan today] " + " · ".join(parts)
    except Exception:
        return ""


def prompt_lines() -> str:
    """Both lines for one AI call (one small DB read)."""
    try:
        now = _now()
        events = _events()
    except Exception:
        return ""
    from backend.app.core import proactive

    lines = [line for line in (soon_line(now, events), plan_line(now, events), proactive.recent_line(now)) if line]
    return ("\n" + "\n".join(lines)) if lines else ""


# --------------------------------------------------------------------------- spoken lines
def plan_speech(event: dict, now: _dt.datetime, owner: str = "Sir") -> list[tuple[str, str]]:
    """(once-key, speech) for a plan block that starts or ends right now."""
    if event.get("category") != "plan":
        return []
    start, end = _local(event.get("start_time")), _local(event.get("end_time"))
    if start is None or end is None:
        return []
    out = []
    title = _clean(event.get("title"))
    extra = _extra(event)
    since_start = (now - start).total_seconds() / 60
    if 0 <= since_start <= START_WINDOW_MIN and now < end:
        speech = extra.get("say") or f"{owner}, {title} starts now."
        out.append((f"plan_start|{event['id']}|{start.isoformat()}", _clean_speech(speech)))
    since_end = (now - end).total_seconds() / 60
    if extra.get("check_in", True) and 0 <= since_end <= END_WINDOW_MIN:
        out.append((f"plan_end|{event['id']}|{end.isoformat()}",
                    f"{title} is over, {owner}. Finished it, or ten more minutes?"))
    return out


def _clean_speech(text: str) -> str:
    return " ".join(str(text).split())[:200]


def arrival_sentences(now: _dt.datetime, events: Optional[list[dict]] = None) -> list[str]:
    """Exam countdown and plan progress for the welcome-back briefing."""
    try:
        events = _events() if events is None else events
    except Exception:
        return []
    out = []
    horizon = now + _dt.timedelta(days=SOON_DAYS)
    from backend.app.core.proactive import IMPORTANT

    important = sorted((e for e in events if str(e.get("category") or "") in IMPORTANT
                        and now <= e["_end"] and e["_start"] <= horizon), key=lambda e: e["_start"])
    if important:
        first = important[0]
        out.append(f"{_clean(first['title'])} is {_day_word(first['_start'], now)} at "
                   f"{_spoken_clock(first['_start'])}.")
    blocks = _today_plan(events, now)
    done, _skipped, total = _progress(blocks)
    if total:
        upcoming = next((b for b in _work(blocks) if b["category"] == "plan" and b["_start"] > now), None)
        line = f"Today's plan: {done} of {total} blocks done"
        if upcoming:
            line += f", next is {_clean(upcoming['title'])} at {_spoken_clock(upcoming['_start'])}"
        out.append(line + ".")
    else:
        done, _skipped, total = _progress(_today_plan(events, now, days_back=1))
        if total:
            out.append(f"Last night's plan: {done} of {total} blocks done.")
    return out
