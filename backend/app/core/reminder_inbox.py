"""Reminder inbox: nothing fired while the owner was away is ever lost.

Flow
  scheduler fires a reminder -> record_fired() (delivered_at NULL)
  -> broadcast to live screens; if at least one received it -> mark_delivered()
  -> otherwise it waits; when a screen connects to /ws/events, undelivered()
     items are sent as one "while you were away" message and marked delivered.
Spoken text uses plain words only (no symbols), per the voice rules.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Iterable, Optional

from backend.app.core.time_parse import speakable_time
from backend.app.database.db import get_db_connection

LATE_AFTER = _dt.timedelta(minutes=2)
KEEP_UNDELIVERED = _dt.timedelta(days=7)


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse(value: str) -> _dt.datetime:
    parsed = _dt.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def _clean_title(title: str) -> str:
    return " ".join(str(title or "reminder").replace("_", " ").split()).strip(" .")


def describe(entry: dict, now: Optional[_dt.datetime] = None) -> dict:
    """Add when_local / late / speech_line to an inbox row."""
    now = now or _utc_now()
    target = _parse(entry["target_time"])
    fired = _parse(entry.get("fired_at") or now.isoformat())
    late = fired - target > LATE_AFTER
    kind = "alarm" if entry.get("type") == "alarm" else "reminder"
    title = _clean_title(entry.get("title"))
    when = speakable_time(target, now)
    line = f"{title}, set for {when}" if late else title
    return {
        **entry,
        "when_local": when,
        "late": late,
        "speech_line": line,
        "kind": kind,
    }


def record_fired(cursor, item: dict, fired_at: Optional[_dt.datetime] = None) -> dict:
    """Store one fired reminder (call inside the scheduler's transaction)."""
    fired_at = fired_at or _utc_now()
    entry = {
        "id": str(uuid.uuid4()),
        "reminder_id": item["id"],
        "type": item.get("type") or "reminder",
        "title": item.get("title") or "reminder",
        "description": item.get("description"),
        "target_time": item["target_time"],
        "fired_at": fired_at.isoformat(),
    }
    cursor.execute(
        """
        INSERT INTO reminder_inbox
            (id, reminder_id, type, title, description, target_time, fired_at, delivered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL);
        """,
        (
            entry["id"], entry["reminder_id"], entry["type"], entry["title"],
            entry["description"], entry["target_time"], entry["fired_at"],
        ),
    )
    return describe(entry, fired_at)


def mark_delivered(inbox_ids: Iterable[str]) -> int:
    ids = [str(i) for i in inbox_ids if i]
    if not ids:
        return 0
    stamp = _utc_now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            "UPDATE reminder_inbox SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL;",
            [(stamp, i) for i in ids],
        )
        conn.commit()
        return cursor.rowcount


def undelivered(limit: int = 20) -> list[dict]:
    """Reminders that fired but no screen has received yet (last 7 days)."""
    now = _utc_now()
    cutoff = (now - KEEP_UNDELIVERED).isoformat()
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, reminder_id, type, title, description, target_time, fired_at
            FROM reminder_inbox
            WHERE delivered_at IS NULL AND fired_at >= ?
            ORDER BY fired_at ASC
            LIMIT ?;
            """,
            (cutoff, int(limit)),
        ).fetchall()
    return [describe(dict(row), now) for row in rows]


def live_speech(entry: dict, owner: str = "Sir") -> str:
    kind = "Alarm" if entry.get("kind") == "alarm" else "Reminder"
    return f"{owner}, {kind.lower()}: {entry['speech_line']}."


def away_speech(entries: list[dict], owner: str = "Sir") -> str:
    """One natural sentence for everything missed while away."""
    if not entries:
        return ""
    lines = [entry["speech_line"] for entry in entries[:5]]
    extra = len(entries) - len(lines)
    if len(lines) == 1:
        body = f"one reminder: {lines[0]}"
    else:
        body = f"{len(entries)} reminders: " + "; ".join(lines[:-1]) + f"; and {lines[-1]}"
    if extra > 0:
        body += f". Plus {extra} more on your screen"
    return f"Welcome back, {owner}. While you were away, {body}."


def event_payload(entry: dict) -> dict:
    """Payload for one live reminder_triggered event (keeps the old shape)."""
    return {
        "type": "reminder_triggered",
        "reminder": {
            "id": entry["reminder_id"],
            "inbox_id": entry["id"],
            "type": entry["type"],
            "title": entry["title"],
            "description": entry.get("description"),
            "target_time": entry["target_time"],
            "when_local": entry["when_local"],
            "late": entry["late"],
        },
        "speech": live_speech(entry),
    }


def away_payload(entries: list[dict]) -> dict:
    return {
        "type": "missed_reminders",
        "items": [
            {
                "id": e["reminder_id"],
                "inbox_id": e["id"],
                "type": e["type"],
                "title": e["title"],
                "when_local": e["when_local"],
                "late": e["late"],
            }
            for e in entries
        ],
        "speech": away_speech(entries),
    }
