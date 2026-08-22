"""Project-scoped exact/FTS recall index backed by canonical SQLite records."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Iterable, Optional

from backend.app.memory.structured_memory import bounded_text, normalize_category, normalize_importance


RECALL_INDEX_SCHEMA_VERSION = 1
RECALL_SYNC_LIMIT = 5000
_STOP_WORDS = {
    "a", "an", "and", "are", "did", "do", "for", "from", "how", "i", "in",
    "is", "it", "last", "me", "my", "of", "on", "our", "that", "the", "this",
    "to", "was", "we", "what", "when", "where", "who", "why", "you",
}
_TOKEN = re.compile(r"[A-Za-z0-9_]{2,}")


def ensure_recall_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS recall_fts USING fts5(
            document_key UNINDEXED,
            source_type UNINDEXED,
            source_id UNINDEXED,
            project_id UNINDEXED,
            session_id UNINDEXED,
            category UNINDEXED,
            importance UNINDEXED,
            revision UNINDEXED,
            corrected UNINDEXED,
            updated_at UNINDEXED,
            content,
            tokenize='porter unicode61'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recall_index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def _meta_value(conn: sqlite3.Connection, key: str) -> Optional[str]:
    ensure_recall_index(conn)
    row = conn.execute("SELECT value FROM recall_index_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    ensure_recall_index(conn)
    conn.execute(
        "INSERT INTO recall_index_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def upsert_recall_document(
    conn: sqlite3.Connection,
    *,
    document_key: str,
    source_type: str,
    source_id: str,
    project_id: str,
    session_id: Optional[str],
    category: str,
    importance: str,
    revision: int,
    corrected: bool,
    updated_at: str,
    content: str,
) -> None:
    ensure_recall_index(conn)
    conn.execute("DELETE FROM recall_fts WHERE document_key = ?", (document_key,))
    conn.execute(
        """
        INSERT INTO recall_fts(
            document_key, source_type, source_id, project_id, session_id,
            category, importance, revision, corrected, updated_at, content
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_key,
            source_type,
            source_id,
            project_id or "personal",
            session_id,
            category,
            importance,
            int(revision or 1),
            int(bool(corrected)),
            updated_at or "",
            bounded_text(content, 1600),
        ),
    )


def delete_recall_document(conn: sqlite3.Connection, document_key: str) -> None:
    ensure_recall_index(conn)
    conn.execute("DELETE FROM recall_fts WHERE document_key = ?", (document_key,))


def mark_recall_index_dirty(conn: sqlite3.Connection) -> None:
    _set_meta(conn, "initial_sync_complete", "0")


def index_conversation_turn(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    session_id: str,
    project_id: str,
    user_message: str,
    ai_response: str,
    intent: str,
    timestamp: str = "",
) -> None:
    content = (
        f"Owner: {bounded_text(user_message, 700)}\n"
        f"Assistant: {bounded_text(ai_response, 700)}"
    )
    upsert_recall_document(
        conn,
        document_key=f"conversation:{message_id}",
        source_type="conversation",
        source_id=message_id,
        project_id=project_id,
        session_id=session_id,
        category=normalize_category(intent) or "session_event",
        importance="normal",
        revision=1,
        corrected=False,
        updated_at=timestamp,
        content=content,
    )


def index_session_summary(conn: sqlite3.Connection, summary: dict[str, Any]) -> None:
    focus = "\n".join(
        f"Focus: {bounded_text(item.get('user'), 320)}"
        for item in summary.get("recent_focus", [])
    )
    content = bounded_text(summary.get("summary_text"), 1000)
    if focus:
        content += "\n" + focus
    upsert_recall_document(
        conn,
        document_key=f"summary:{summary['session_id']}",
        source_type="session_summary",
        source_id=str(summary["session_id"]),
        project_id=str(summary.get("project_id") or "personal"),
        session_id=str(summary["session_id"]),
        category="session_summary",
        importance="high",
        revision=int(summary.get("schema_version") or 1),
        corrected=False,
        updated_at=str(summary.get("updated_at") or summary.get("last_activity_at") or ""),
        content=content,
    )


def index_vector_memory(
    conn: sqlite3.Connection,
    *,
    memory_id: str,
    mem_type: str,
    content: str,
    metadata: dict[str, Any],
    created_at: str = "",
) -> None:
    category = normalize_category(metadata.get("category")) or "session_event"
    importance = normalize_importance(metadata.get("importance")) or "normal"
    upsert_recall_document(
        conn,
        document_key=f"memory:{memory_id}",
        source_type="memory",
        source_id=memory_id,
        project_id=str(metadata.get("project_id") or "personal"),
        session_id=metadata.get("session_id"),
        category=category,
        importance=importance,
        revision=int(metadata.get("revision") or 1),
        corrected=bool(metadata.get("corrected")),
        updated_at=str(metadata.get("updated_at") or created_at or metadata.get("created_at") or ""),
        content=content,
    )


def rebuild_recall_index(conn: sqlite3.Connection) -> dict[str, int]:
    """Rebuild from canonical tables for existing owner databases."""
    ensure_recall_index(conn)
    conn.execute("DELETE FROM recall_fts")
    counts = {"conversation": 0, "session_summary": 0, "memory": 0}

    conversations = conn.execute(
        """
        SELECT c.id, c.session_id, c.timestamp, c.user_message, c.ai_response,
               c.intent, COALESCE(NULLIF(s.active_project, ''), 'personal') AS project_id
        FROM conversations AS c
        JOIN sessions AS s ON s.id = c.session_id
        ORDER BY c.rowid DESC
        LIMIT ?
        """,
        (RECALL_SYNC_LIMIT,),
    ).fetchall()
    for row in reversed(conversations):
        index_conversation_turn(
            conn,
            message_id=str(row["id"]),
            session_id=str(row["session_id"]),
            project_id=str(row["project_id"]),
            user_message=str(row["user_message"]),
            ai_response=str(row["ai_response"]),
            intent=str(row["intent"] or "Conversation"),
            timestamp=str(row["timestamp"] or ""),
        )
        counts["conversation"] += 1

    summaries = conn.execute(
        "SELECT id, summary FROM sessions WHERE summary IS NOT NULL ORDER BY started_at DESC LIMIT ?",
        (RECALL_SYNC_LIMIT,),
    ).fetchall()
    for row in summaries:
        try:
            summary = json.loads(row["summary"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(summary, dict) and summary.get("session_id"):
            index_session_summary(conn, summary)
            counts["session_summary"] += 1

    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vector_memories'"
    ).fetchone()
    if table:
        memories = conn.execute(
            "SELECT id, type, content, metadata, created_at FROM vector_memories "
            "ORDER BY rowid DESC LIMIT ?",
            (RECALL_SYNC_LIMIT,),
        ).fetchall()
        for row in reversed(memories):
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            index_vector_memory(
                conn,
                memory_id=str(row["id"]),
                mem_type=str(row["type"]),
                content=str(row["content"]),
                metadata=metadata,
                created_at=str(row["created_at"] or ""),
            )
            counts["memory"] += 1

    _set_meta(conn, "schema_version", RECALL_INDEX_SCHEMA_VERSION)
    _set_meta(conn, "initial_sync_complete", "1")
    conn.commit()
    return counts


def ensure_initial_sync(conn: sqlite3.Connection) -> None:
    if _meta_value(conn, "initial_sync_complete") != "1":
        rebuild_recall_index(conn)


def _fts_query(query: str) -> Optional[str]:
    tokens: list[str] = []
    for token in _TOKEN.findall(query.lower()):
        if token in _STOP_WORDS or token in tokens:
            continue
        tokens.append(token)
        if len(tokens) >= 12:
            break
    return " OR ".join(f'"{token}"' for token in tokens) if tokens else None


def search_recall_index(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: str,
    exclude_session_id: Optional[str] = None,
    categories: Optional[Iterable[str]] = None,
    importance: Optional[Iterable[str]] = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    ensure_initial_sync(conn)
    limit = max(1, min(int(limit), 50))
    match_query = _fts_query(query)
    if not match_query:
        return []
    rows = conn.execute(
        """
        SELECT document_key, source_type, source_id, project_id, session_id,
               category, importance, revision, corrected, updated_at, content,
               bm25(recall_fts) AS rank
        FROM recall_fts
        WHERE recall_fts MATCH ?
          AND project_id = ?
          AND (? IS NULL OR session_id IS NULL OR session_id != ?)
        ORDER BY rank ASC, updated_at DESC
        LIMIT ?
        """,
        (match_query, project_id, exclude_session_id, exclude_session_id, max(limit * 4, limit)),
    ).fetchall()
    category_filter = {normalize_category(value) or str(value) for value in (categories or [])}
    importance_filter = {normalize_importance(value) or str(value) for value in (importance or [])}
    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["revision"] = int(item.get("revision") or 1)
        item["corrected"] = bool(int(item.get("corrected") or 0))
        if category_filter and item["category"] not in category_filter:
            continue
        if importance_filter and item["importance"] not in importance_filter:
            continue
        results.append(item)
        if len(results) >= limit:
            break
    return results
