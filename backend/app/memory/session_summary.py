"""Deterministic, local-only rolling summaries derived from saved conversations.

The conversation table remains the canonical record. A summary is a bounded,
redacted digest stored in the existing ``sessions.summary`` TEXT column and can
always be regenerated from SQLite without an LLM or provider key.
"""

from __future__ import annotations

import datetime
import json
import re
import sqlite3
from typing import Any, Optional

from backend.app.memory.recall_index import index_session_summary


SUMMARY_SCHEMA_VERSION = 1
RECENT_QUERY_LIMIT = 8
RECENT_FOCUS_LIMIT = 5
USER_EXCERPT_LIMIT = 320
ASSISTANT_EXCERPT_LIMIT = 420

_SECRET_ASSIGNMENT = re.compile(
    r"\b([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)"
    r"\s*([:=])\s*([^\s,;]+)",
    re.IGNORECASE,
)
_SECRET_PREFIX = re.compile(
    r"\b(?:gsk_|ghp_|github_pat_|nvapi-|AIza)[A-Za-z0-9_-]{8,}",
    re.IGNORECASE,
)


def _redact(text: Any) -> str:
    value = str(text or "")
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _SECRET_PREFIX.sub("[REDACTED]", value)


def _excerpt(text: Any, limit: int) -> str:
    compact = " ".join(_redact(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


def _parse_tools(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def build_session_summary(conn: sqlite3.Connection, session_id: str) -> Optional[dict[str, Any]]:
    """Build one bounded summary from exact saved rows, without model inference."""
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        return None

    turn_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    )
    if turn_count == 0:
        return None

    rows = conn.execute(
        """
        SELECT rowid AS _rowid, timestamp, user_message, ai_response,
               personality, tools_used, widget_shown, intent
        FROM conversations
        WHERE session_id = ?
        ORDER BY timestamp DESC, rowid DESC
        LIMIT ?
        """,
        (session_id, RECENT_QUERY_LIMIT),
    ).fetchall()
    recent_rows = list(reversed(rows))
    latest = recent_rows[-1]

    recent_focus: list[dict[str, str]] = []
    seen_focus: set[str] = set()
    for row in recent_rows:
        user_excerpt = _excerpt(row["user_message"], USER_EXCERPT_LIMIT)
        if not user_excerpt or user_excerpt in seen_focus:
            continue
        seen_focus.add(user_excerpt)
        recent_focus.append(
            {
                "timestamp": str(row["timestamp"] or ""),
                "user": user_excerpt,
                "intent": str(row["intent"] or "Conversation"),
            }
        )
    recent_focus = recent_focus[-RECENT_FOCUS_LIMIT:]

    tools = sorted(
        {
            tool
            for row in recent_rows
            for tool in _parse_tools(row["tools_used"])
        }
    )
    widgets = sorted(
        {
            str(row["widget_shown"])
            for row in recent_rows
            if row["widget_shown"]
        }
    )
    latest_user = _excerpt(latest["user_message"], USER_EXCERPT_LIMIT)
    latest_assistant = _excerpt(latest["ai_response"], ASSISTANT_EXCERPT_LIMIT)
    summary_text = (
        f"{turn_count} saved conversation turns. "
        f"Latest request: {latest_user}. "
        f"Latest assistant result: {latest_assistant}."
    )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    project_id = str(session["active_project"] or "personal")
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "source": "deterministic_db_digest",
        "session_id": str(session["id"]),
        "project_id": project_id,
        "status": "ended" if session["ended_at"] else "active",
        "started_at": str(session["started_at"] or ""),
        "ended_at": str(session["ended_at"] or "") or None,
        "updated_at": now,
        "last_activity_at": str(latest["timestamp"] or ""),
        "turn_count": turn_count,
        "personality": str(latest["personality"] or session["personality"] or "ultron"),
        "latest": {
            "timestamp": str(latest["timestamp"] or ""),
            "user": latest_user,
            "assistant": latest_assistant,
            "intent": str(latest["intent"] or "Conversation"),
        },
        "recent_focus": recent_focus,
        "tools_used": tools,
        "widgets_shown": widgets,
        "summary_text": summary_text,
    }


def refresh_session_summary(conn: sqlite3.Connection, session_id: str) -> Optional[dict[str, Any]]:
    """Regenerate and store one summary in the existing session row."""
    summary = build_session_summary(conn, session_id)
    if summary is None:
        return None
    conn.execute(
        "UPDATE sessions SET summary = ? WHERE id = ?",
        (json.dumps(summary, ensure_ascii=False, sort_keys=True), session_id),
    )
    index_session_summary(conn, summary)
    conn.commit()
    return summary


def load_session_summary(conn: sqlite3.Connection, session_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT summary FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or not row["summary"]:
        return None
    try:
        value = json.loads(row["summary"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        return None
    return value


def get_last_session_summary(
    conn: sqlite3.Connection,
    project_id: str = "personal",
    exclude_session_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return the newest valid summary in one project, optionally excluding current."""
    rows = conn.execute(
        """
        SELECT s.id, s.summary, MAX(c.timestamp) AS last_activity, MAX(c.rowid) AS last_rowid
        FROM sessions AS s
        JOIN conversations AS c ON c.session_id = s.id
        WHERE COALESCE(NULLIF(s.active_project, ''), 'personal') = ?
          AND s.summary IS NOT NULL
          AND (? IS NULL OR s.id != ?)
        GROUP BY s.id
        ORDER BY last_activity DESC, last_rowid DESC
        LIMIT 20
        """,
        (project_id, exclude_session_id, exclude_session_id),
    ).fetchall()
    for row in rows:
        try:
            value = json.loads(row["summary"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("schema_version") == SUMMARY_SCHEMA_VERSION:
            return value
    return None
