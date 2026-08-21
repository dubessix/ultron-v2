"""
Ultron Canonical Chat-Processing Service (Phase 1)

Single source of truth for processing a user chat turn. Used by BOTH the REST
endpoint (/api/chat) and the WebSocket channel (/ws/chat) so that regardless of
transport the behavior is identical:

  1. Resolve (or create) the session in SQLite.
  2. Restore the persisted per-session personality.
  3. Run the cognitive orchestrator pipeline.
  4. Persist the turn + the *effective* personality back to the session.

Keeping this in one place removes the previous divergence where the WebSocket
path skipped session creation, personality persistence, and conversation
storage entirely (so WS history never survived a restart).
"""

import time
import datetime
from typing import Dict, Any, Optional

from backend.app.database.db import get_db_connection
from backend.app.database.models import (
    save_conversation,
    update_session_personality,
    update_session_project,
)
from backend.app.session.session_manager import SessionManager
from backend.app.utils.text_cleaner import clean_text


async def process_chat_message(
    orchestrator,
    content: str,
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    has_confirmed: bool = False,
    confirmation_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the full canonical chat pipeline and return a normalized result dict.

    Returns keys: id, session_id, content, personality, response_ms,
    structured_action, coding, intent, events.
    """
    start_time = time.perf_counter()

    # 1. Resolve active session (create it if it doesn't exist yet).
    session_data = SessionManager.get_or_create_session(session_id)
    resolved_session_id = session_data["id"]
    session_personality = session_data.get("personality") or "ultron"
    effective_project_id = (
        (project_id or "").strip()
        or (session_data.get("active_project") or "").strip()
        or "personal"
    )

    # 2. Process query via the cognitive orchestrator.
    result = await orchestrator.process_request(
        user_prompt=content,
        session_id=resolved_session_id,
        project_id=effective_project_id,
        consecutive_errors=0,
        current_hour=datetime.datetime.now().hour,
        delete_ratio=0.0,
        initial_personality=session_personality,
        user_confirmed=bool(has_confirmed),
        confirmation_token=confirmation_token,
    )

    latency_ms = int((time.perf_counter() - start_time) * 1000)

    # 3. Persist the turn + the effective personality to the session.
    with get_db_connection() as conn:
        try:
            update_session_personality(
                conn,
                resolved_session_id,
                result.get("persisted_personality", result.get("active_personality", "ultron")),
            )
            update_session_project(conn, resolved_session_id, effective_project_id)
        except Exception:
            pass
        save_conversation(
            conn=conn,
            msg_id=result["id"],
            session_id=resolved_session_id,
            user_message=content,
            ai_response=result["content"],
            personality=result["active_personality"],
            tools_used=[],
            widget_shown=None,
            intent=result["intent"],
            mode="developer",
            path_used="fast",
            response_ms=latency_ms,
        )

    raw_content = result["content"]
    return {
        "id": result["id"],
        "session_id": resolved_session_id,
        "project_id": effective_project_id,
        "content": clean_text(raw_content) if raw_content else raw_content,
        "personality": result["active_personality"],
        "response_ms": latency_ms,
        "structured_action": result.get("structured_action") or {},
        "coding": result.get("coding", False),
        "intent": result.get("intent", ""),
        "events": result.get("events", []),
        "pending_confirmation": result.get("pending_confirmation"),
        "provider_route": result.get("provider_route") or {
            "provider": None, "model": None, "cached": False, "offline": False
        },
    }
