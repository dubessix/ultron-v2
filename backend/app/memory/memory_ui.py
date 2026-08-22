"""Safe, project-scoped read model for the M4 memory dashboard.

The UI never receives embeddings, correction-history hashes, provider details, or
unredacted legacy text. Canonical conversations/vector rows remain untouched.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

from backend.app.database.db import get_db_connection
from backend.app.memory.recall_index import search_recall_index
from backend.app.memory.session_summary import SUMMARY_SCHEMA_VERSION
from backend.app.memory.structured_memory import (
    ALLOWED_IMPORTANCE,
    ALLOWED_MEMORY_CATEGORIES,
    bounded_text,
    normalize_category,
    normalize_importance,
    redact_sensitive_text,
)
from backend.app.memory.vector_store import VectorStore


MEMORY_UI_LIMIT = 100
MEMORY_SCAN_LIMIT = 500
_SUMMARY_SCAN_LIMIT = 500
_IMPORTANCE_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,127}$")
_EXPORT_METADATA_FIELDS = (
    "schema_version",
    "kind",
    "source",
    "project_id",
    "session_id",
    "category",
    "importance",
    "revision",
    "corrected",
    "created_at",
    "updated_at",
)


def normalize_project_scope(value: Any) -> str:
    """Keep project selection bounded and prevent a secret-like value becoming UI text."""
    project_id = str(value or "personal").strip() or "personal"
    if not _SAFE_ID.fullmatch(project_id):
        raise ValueError("project_id must use letters, numbers, spaces, dot, dash, slash, colon, or underscore.")
    if redact_sensitive_text(project_id) != project_id:
        raise ValueError("project_id cannot contain secret-like text.")
    return project_id


def _safe_id(value: Any, limit: int = 160) -> str:
    return bounded_text(value, limit)


def _safe_timestamp(value: Any) -> Optional[str]:
    clean = bounded_text(value, 80)
    return clean or None


def public_memory_record(row: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Flatten one vector row into the small display contract used by React."""
    metadata = dict(row.get("metadata") or {})
    category = normalize_category(metadata.get("category")) or "session_event"
    importance = normalize_importance(metadata.get("importance")) or "normal"
    memory_id = _safe_id(row.get("id"), 160)
    created_at = _safe_timestamp(metadata.get("created_at") or row.get("created_at"))
    updated_at = _safe_timestamp(metadata.get("updated_at") or created_at)
    return {
        "id": memory_id,
        "type": _safe_id(row.get("type") or "unknown", 40),
        "project_id": project_id,
        "session_id": _safe_id(metadata.get("session_id"), 160) or None,
        "content": bounded_text(row.get("content"), 1600),
        "category": category,
        "importance": importance,
        "kind": _safe_id(metadata.get("kind") or row.get("type") or "memory", 80),
        "source": _safe_id(metadata.get("source") or "stored_memory", 80),
        "revision": max(1, int(metadata.get("revision") or 1)),
        "corrected": bool(metadata.get("corrected")),
        "created_at": created_at,
        "updated_at": updated_at,
        "provenance": {
            "source_type": "memory",
            "source_id": memory_id,
            "project_id": project_id,
            "session_id": _safe_id(metadata.get("session_id"), 160) or None,
        },
    }


def _safe_export_metadata(metadata: dict[str, Any], project_id: str) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for field in _EXPORT_METADATA_FIELDS:
        if field not in metadata:
            continue
        value = metadata[field]
        if field == "project_id":
            safe[field] = project_id
        elif field == "category":
            safe[field] = normalize_category(value) or "session_event"
        elif field == "importance":
            safe[field] = normalize_importance(value) or "normal"
        elif field == "revision":
            safe[field] = max(1, int(value or 1))
        elif field == "corrected":
            safe[field] = bool(value)
        elif isinstance(value, str):
            safe[field] = bounded_text(value, 240)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[field] = value
    return safe


def safe_export_memories(rows: Iterable[dict[str, Any]], project_id: str) -> dict[str, Any]:
    """Return a restorable JSON export without embeddings, secret text, or internal hashes."""
    project_id = normalize_project_scope(project_id)
    memories: list[dict[str, Any]] = []
    for row in rows:
        metadata = dict(row.get("metadata") or {})
        if str(metadata.get("project_id") or "personal") != project_id:
            continue
        memories.append(
            {
                "id": _safe_id(row.get("id"), 160),
                "type": _safe_id(row.get("type") or "episodic", 40),
                "content": bounded_text(row.get("content"), 4000),
                "created_at": _safe_timestamp(row.get("created_at")),
                "metadata": _safe_export_metadata(metadata, project_id),
            }
        )
    return {
        "format": "ultron-memory-export-v1",
        "project_id": project_id,
        "count": len(memories),
        "memories": memories,
    }


def _public_summary(value: dict[str, Any], project_id: str) -> Optional[dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        return None
    if str(value.get("project_id") or "personal") != project_id:
        return None
    session_id = _safe_id(value.get("session_id"), 160)
    if not session_id:
        return None
    personality = str(value.get("personality") or "ultron").lower()
    if personality not in {"ultron", "zora"}:
        personality = "ultron"
    status = str(value.get("status") or "active").lower()
    if status not in {"active", "ended"}:
        status = "active"
    return {
        "session_id": session_id,
        "project_id": project_id,
        "summary_text": bounded_text(value.get("summary_text"), 1600),
        "status": status,
        "personality": personality,
        "turn_count": max(0, int(value.get("turn_count") or 0)),
        "started_at": _safe_timestamp(value.get("started_at")),
        "ended_at": _safe_timestamp(value.get("ended_at")),
        "last_activity_at": _safe_timestamp(value.get("last_activity_at")),
        "updated_at": _safe_timestamp(value.get("updated_at")),
        "tools_used": [
            bounded_text(tool, 80)
            for tool in list(value.get("tools_used") or [])[:20]
            if bounded_text(tool, 80)
        ],
        "provenance": {
            "source_type": "session_summary",
            "source_id": session_id,
            "project_id": project_id,
            "session_id": session_id,
        },
    }


def _list_summaries(project_id: str) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT summary
            FROM sessions
            WHERE COALESCE(NULLIF(active_project, ''), 'personal') = ?
              AND summary IS NOT NULL
            ORDER BY COALESCE(ended_at, started_at) DESC, rowid DESC
            LIMIT ?
            """,
            (project_id, _SUMMARY_SCAN_LIMIT),
        ).fetchall()
    summaries: list[dict[str, Any]] = []
    for row in rows:
        try:
            parsed = json.loads(row["summary"] or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        item = _public_summary(parsed, project_id)
        if item:
            summaries.append(item)
    summaries.sort(
        key=lambda item: item.get("last_activity_at") or item.get("updated_at") or "",
        reverse=True,
    )
    return summaries


def _ranked_search_keys(project_id: str, query: str, limit: int) -> list[str]:
    if not query:
        return []
    with get_db_connection() as conn:
        matches = search_recall_index(
            conn,
            query,
            project_id=project_id,
            limit=min(50, max(limit * 2, 20)),
        )
    return [
        str(item["document_key"])
        for item in matches
        if item.get("source_type") in {"memory", "session_summary"}
    ]


def _matches_query(item: dict[str, Any], query: str, search_keys: set[str], key: str) -> bool:
    if not query:
        return True
    # FTS handles stemming/individual terms; substring keeps quoted-looking exact
    # phrases intuitive without involving any provider or semantic fabrication.
    return key in search_keys or query.casefold() in str(item.get("content") or item.get("summary_text") or "").casefold()


def build_memory_ui_payload(
    *,
    project_id: str = "personal",
    query: str = "",
    category: Optional[str] = None,
    importance: Optional[str] = None,
    limit: int = 30,
) -> dict[str, Any]:
    """Build one bounded local dashboard payload from canonical stored data."""
    project_id = normalize_project_scope(project_id)
    safe_query = bounded_text(query, 240)
    normalized_category = normalize_category(category) if category else None
    normalized_importance = normalize_importance(importance) if importance else None
    if category and normalized_category is None:
        raise ValueError("Unsupported memory category.")
    if importance and normalized_importance is None:
        raise ValueError("Unsupported memory importance.")
    limit = max(1, min(int(limit), MEMORY_UI_LIMIT))

    store = VectorStore()
    raw_rows = store.list_recent_memories(
        limit=MEMORY_SCAN_LIMIT,
        project_id=project_id,
    )
    all_memories = [public_memory_record(row, project_id) for row in raw_rows]
    all_summaries = _list_summaries(project_id)

    ranked_keys = _ranked_search_keys(project_id, safe_query, limit)
    search_keys = set(ranked_keys)
    rank = {key: index for index, key in enumerate(ranked_keys)}

    memories = [
        item
        for item in all_memories
        if (not normalized_category or item["category"] == normalized_category)
        and (not normalized_importance or item["importance"] == normalized_importance)
        and _matches_query(item, safe_query, search_keys, f"memory:{item['id']}")
    ]
    summaries = [
        item
        for item in all_summaries
        if _matches_query(item, safe_query, search_keys, f"summary:{item['session_id']}")
    ]

    if safe_query:
        memories.sort(
            key=lambda item: (
                rank.get(f"memory:{item['id']}", len(rank) + 1),
                _IMPORTANCE_ORDER[item["importance"]],
                item.get("updated_at") or "",
            )
        )
        summaries.sort(
            key=lambda item: (
                rank.get(f"summary:{item['session_id']}", len(rank) + 1),
                item.get("last_activity_at") or "",
            )
        )
    else:
        memories.sort(
            key=lambda item: (
                _IMPORTANCE_ORDER[item["importance"]],
                item.get("updated_at") or item.get("created_at") or "",
            )
        )

    return {
        "project_id": project_id,
        "filters": {
            "query": safe_query,
            "category": normalized_category,
            "importance": normalized_importance,
            "mode": "local_exact_fts" if safe_query else "project_recent",
        },
        "counts": {
            "memories": len(all_memories),
            "important": sum(item["importance"] in {"high", "critical"} for item in all_memories),
            "sessions": len(all_summaries),
            "shown_memories": min(len(memories), limit),
            "shown_sessions": min(len(summaries), limit),
        },
        "categories": list(ALLOWED_MEMORY_CATEGORIES),
        "importance_levels": list(ALLOWED_IMPORTANCE),
        "memories": memories[:limit],
        "summaries": summaries[:limit],
    }
