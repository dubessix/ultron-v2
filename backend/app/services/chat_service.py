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
import uuid
import datetime
from typing import Dict, Any, Optional

from backend.app.database.db import get_db_connection
from backend.app.database.models import (
    save_conversation,
    update_session_personality,
    update_session_project,
)
from backend.app.session.session_manager import SessionManager
from backend.app.memory.recall_index import index_conversation_turn
from backend.app.memory.session_summary import refresh_session_summary
from backend.app.utils.text_cleaner import clean_text
from backend.app.core.voice_intent import inspect_voice_aliases
from backend.app.core.voice_preferences import apply_approved_voice_aliases, get_approved_voice_aliases


async def process_chat_message(
    orchestrator,
    content: str,
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    has_confirmed: bool = False,
    confirmation_token: Optional[str] = None,
    input_source: str = "text",
) -> Dict[str, Any]:
    """
    Run the full canonical chat pipeline and return a normalized result dict.

    Returns keys: id, session_id, content, personality, response_ms,
    structured_action, coding, intent, events.
    """
    start_time = time.perf_counter()
    content = str(content or "").strip()
    if not content:
        raise ValueError("Chat content cannot be empty.")
    # V2 Step 8: back after 2+ hours? The welcome-back briefing rides along (no LLM call).
    try:
        from backend.app.core import arrival as _arrival

        arrival_briefing = _arrival.briefing()
    except Exception as exc:
        print(f"[ARRIVAL] skipped: {exc}")
        arrival_briefing = None
    if len(content) > 12000:
        raise ValueError("Chat content exceeds the 12,000-character safety limit.")
    input_source = str(input_source or "text").strip().lower()
    if input_source not in {"text", "voice"}:
        raise ValueError("Chat input_source must be text or voice.")
    # Phase 2 detects safe known-word mismatches but never rewrites content.
    # The future clarification gate, not this service, decides what to do.
    approved_voice_aliases = get_approved_voice_aliases() if input_source == "voice" else {}
    voice_alias_suggestions = inspect_voice_aliases(content) if input_source == "voice" else []
    # No word-list gate stops the turn any more: the AI reads the transcript
    # (with these hints) and asks the owner itself when it is truly unclear.
    voice_clarification = None
    # Preserve raw text in history. Only owner-approved aliases are applied to
    # the transient agent prompt, never to paths/dates/commands or stored text.
    agent_content = (
        apply_approved_voice_aliases(content, approved_voice_aliases)
        if input_source == "voice"
        else content
    )

    # 1. Resolve active session (create it if it doesn't exist yet).
    session_data = SessionManager.get_or_create_session(session_id)
    resolved_session_id = session_data["id"]
    session_personality = session_data.get("personality") or "ultron"
    effective_project_id = (
        (project_id or "").strip()
        or (session_data.get("active_project") or "").strip()
        or "personal"
    )

    # 2. Known voice ambiguity stops before the LLM agent and before any tool
    # planning. This is deliberately a short Jarvis question, not a guessed
    # action. Clear requests continue into the normal agent unchanged.
    if voice_clarification:
        result = {
            "id": str(uuid.uuid4()),
            "content": voice_clarification["question"],
            "active_personality": session_personality,
            "persisted_personality": session_personality,
            "structured_action": {"action": "none"},
            "coding": False,
            "intent": "VOICE_CLARIFICATION",
            "events": [],
            "pending_confirmation": None,
            "provider_route": {"provider": None, "model": None, "cached": False, "offline": False},
            "memory_provenance": [],
            "input_source": input_source,
        }
    else:
        result = await orchestrator.process_request(
            user_prompt=agent_content,
            session_id=resolved_session_id,
            project_id=effective_project_id,
            consecutive_errors=0,
            current_hour=datetime.datetime.now().hour,
            delete_ratio=0.0,
            initial_personality=session_personality,
            user_confirmed=bool(has_confirmed),
            confirmation_token=confirmation_token,
            input_source=input_source,
            voice_alias_suggestions=voice_alias_suggestions,
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
            tools_used=result.get("tools_used") or [],
            widget_shown=result.get("widget_shown"),
            intent=result["intent"],
            mode="developer",
            path_used="fast",
            response_ms=latency_ms,
        )
        # M3: index the exact saved turn for project-scoped no-key FTS recall.
        try:
            index_conversation_turn(
                conn,
                message_id=result["id"],
                session_id=resolved_session_id,
                project_id=effective_project_id,
                user_message=content,
                ai_response=result["content"],
                intent=result["intent"],
            )
        except Exception as exc:
            print(f"[RECALL_INDEX] Conversation index skipped: {exc}")

        # M1: keep a bounded exact digest in the existing sessions.summary
        # column. Summary failure must never lose an already-saved chat turn.
        try:
            refresh_session_summary(conn, resolved_session_id)
        except Exception as exc:
            print(f"[SESSION_SUMMARY] Refresh skipped: {exc}")

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
        "input_source": result.get("input_source", input_source),
        "voice_alias_suggestions": voice_alias_suggestions,
        "voice_clarification": voice_clarification,
        "memory_provenance": result.get("memory_provenance") or [],
        "arrival": arrival_briefing,
    }


def record_followup(
    session_id: Optional[str],
    owner_text: str,
    ai_text: str,
    *,
    tools_used: Optional[list] = None,
    intent: str = "APPROVAL",
    personality: str = "ultron",
    orchestrator=None,
) -> None:
    """Save an approval outcome (done / failed / cancelled) as a real chat turn.

    Without this Ultron's last memory stayed "Should I...?" and he asked again.
    """
    if not session_id or not str(ai_text or "").strip():
        return
    try:
        with get_db_connection() as conn:
            known = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not known:
                raise LookupError("not a chat session (widget/tool call)")
            save_conversation(
                conn=conn,
                msg_id=str(uuid.uuid4()),
                session_id=session_id,
                user_message=owner_text,
                ai_response=ai_text,
                personality=personality,
                tools_used=list(tools_used or []),
                widget_shown=None,
                intent=intent,
                mode="developer",
                path_used="fast",
                response_ms=0,
            )
    except LookupError:
        return  # widget / direct tool approvals have no chat to remember
    except Exception as exc:
        print(f"[APPROVAL_MEMORY] DB save skipped: {exc}")
    try:
        if orchestrator is not None:
            orchestrator.memory.save_chat_turn(session_id, owner_text, ai_text)
    except Exception as exc:
        print(f"[APPROVAL_MEMORY] RAM save skipped: {exc}")
