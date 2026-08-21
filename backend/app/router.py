"""
Ultron REST API Router
Bridges user communication requests, message history lists, and session builders.
Supports structured AI action metadata payloads and explicit backend tool execution endpoints.
"""

import asyncio
from typing import List, Optional, Dict, Any, Literal
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.database.db import DatabaseMaintenanceError, get_db_connection
from backend.app.database.models import get_conversation_history
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.tools.tool_registry import ToolRegistry

# Create regional router registry
api_router = APIRouter(prefix="/api")

# Fix #8: shared orchestrator singleton so short-term memory persists across
# requests within the same process (instead of resetting every message).
_shared_orchestrator = None
def get_orchestrator() -> CognitiveOrchestrator:
    global _shared_orchestrator
    if _shared_orchestrator is None:
        _shared_orchestrator = CognitiveOrchestrator()
    return _shared_orchestrator

# --- Pydantic Models for Input Validation and Type Safety ---

class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Active unique conversation UUID.")
    project_id: Optional[str] = Field(None, description="Active project used to scope long-term memory.")
    content: str = Field(..., min_length=1, description="Raw user prompt query content.")
    has_confirmed: bool = Field(False, description="User confirmation for a pending dangerous tool (delete/terminal).")
    confirmation_token: Optional[str] = Field(None, description="One-time token binding a confirmation to the exact file+content proposed.")

class ChatResponse(BaseModel):
    id: str = Field(..., description="Unique generated message ID.")
    session_id: str = Field(..., description="Active resolved session UUID.")
    project_id: str = Field(..., description="Project scope used for this response and memory.")
    content: str = Field(..., description="Processed response content.")
    personality: str = Field(..., description="Active answering persona profile.")
    response_ms: int = Field(..., description="Calculated processing duration.")
    structured_action: Dict[str, Any] = Field(default_factory=dict, description="Structured AI Action metadata payload.")
    coding: bool = Field(False, description="True if this turn was a coding turn (so UI can auto-show the coding panel).")
    events: List[dict] = Field(default_factory=list, description="Operational log/event stream for the Log tab.")
    intent: str = Field("", description="Detected intent for the turn.")
    pending_confirmation: Optional[Dict[str, Any]] = Field(None, description="One-time pending-action token awaiting user confirmation (bound to file+content).")
    provider_route: Dict[str, Any] = Field(default_factory=dict, description="Actual provider/model route used for this response.")

class ToolExecuteRequest(BaseModel):
    tool_id: str = Field(..., description="ID of the target registered tool.")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Input arguments to validate and feed to tool execution.")
    has_confirmed: bool = Field(False, description="True only when returning an exact confirmation token.")
    confirmation_token: Optional[str] = Field(None, description="One-time token bound to this exact tool call.")
    session_id: Optional[str] = Field(None, description="Session that owns the pending action.")


class ConfirmActionRequest(BaseModel):
    confirmation_token: str = Field(..., min_length=16)
    session_id: Optional[str] = None

class CodingModeRequest(BaseModel):
    enabled: bool = Field(..., description="True to force NVIDIA coding mode ON, False to revert to auto-detect.")


class PersonalityRequest(BaseModel):
    session_id: Optional[str] = None
    personality: Literal["ultron", "zora"]


class BackupRequest(BaseModel):
    backup_path: Optional[str] = Field(None, description="Approved backup file to restore from.")
    session_id: Optional[str] = Field(None, description="Session that owns the exact confirmation.")
    has_confirmed: bool = Field(False, description="True only with an exact one-time token.")
    confirmation_token: Optional[str] = Field(None, description="Token bound to this exact backup path.")

class ConversationHistoryItem(BaseModel):
    id: str
    session_id: str
    timestamp: str
    user_message: str
    ai_response: str
    personality: str
    tools_used: List[str]
    widget_shown: Optional[str]
    intent: str
    mode: str
    path_used: str
    response_ms: int

# --- Endpoint Handlers ---

@api_router.post("/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def post_chat_message(request: ChatRequest) -> ChatResponse:
    """
    Processes user text prompts through the canonical chat-processing service
    (shared with /ws/chat): resolves the session, restores personality, runs the
    orchestrator, and persists the turn to SQLite.
    """
    from backend.app.services.chat_service import process_chat_message

    orchestrator = get_orchestrator()  # shared — memory persists across messages

    try:
        result = await process_chat_message(
            orchestrator=orchestrator,
            content=request.content,
            session_id=request.session_id,
            project_id=request.project_id,
            has_confirmed=request.has_confirmed,
            confirmation_token=request.confirmation_token,
        )
        return ChatResponse(
            id=result["id"],
            session_id=result["session_id"],
            project_id=result["project_id"],
            content=result["content"],
            personality=result["personality"],
            response_ms=result["response_ms"],
            structured_action=result["structured_action"],
            coding=result["coding"],
            intent=result["intent"],
            events=result["events"],
            pending_confirmation=result.get("pending_confirmation"),
            provider_route=result.get("provider_route") or {},
        )
    except DatabaseMaintenanceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chat message cleanly: {str(e)}"
        ) from e
    # Shared orchestrator is intentionally NOT closed here — it persists across
    # messages for memory. (Its persistent httpx client lives for the process.)

@api_router.post("/tools/execute", status_code=status.HTTP_200_OK)
async def execute_backend_tool(request: ToolExecuteRequest) -> Dict[str, Any]:
    """
    CONSTITUTIONAL DESIGN:
    Exposes a clean REST API interface to directly execute and validate backend tools.
    Provides standard Pydantic schema validation and security level checks.
    """
    registry = ToolRegistry()
    try:
        result = await registry.execute_tool(
            tool_id=request.tool_id,
            args=request.arguments,
            has_confirmed=request.has_confirmed,
            confirmation_token=request.confirmation_token,
            session_id=request.session_id,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tool execution encountered unexpected failure: {str(e)}"
        ) from e

@api_router.post("/actions/confirm", status_code=status.HTTP_200_OK)
async def confirm_pending_action(request: ConfirmActionRequest) -> Dict[str, Any]:
    """Execute the exact stored pending action without regenerating it through an LLM."""
    registry = ToolRegistry()
    result = await registry.execute_pending_action(
        confirmation_token=request.confirmation_token,
        session_id=request.session_id,
        timeout=180.0,
    )
    return result


@api_router.get("/history", response_model=List[ConversationHistoryItem], status_code=status.HTTP_200_OK)
async def get_session_history(session_id: str = Query(..., description="Target session UUID.")) -> List[dict]:
    """Retrieves full chronological dialogue history belonging to a specific session."""
    try:
        with get_db_connection() as conn:
            history = get_conversation_history(conn, session_id)
            return history
    except DatabaseMaintenanceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve conversation logs: {str(e)}"
        ) from e

class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to speak.")
    personality: str = Field("ultron", description="Personality voice: ultron or zora.")

@api_router.post("/speak", status_code=status.HTTP_200_OK)
async def speak_text(request: SpeakRequest):
    """Start the provider before sending HTTP 200 so immediate failures return 503."""
    from backend.app.voice.voice_system import VoiceSystem

    voice = VoiceSystem()
    stream = voice.speak(request.text, personality=request.personality)
    try:
        first_chunk = await anext(stream)
    except StopAsyncIteration as exc:
        raise HTTPException(status_code=503, detail="TTS provider returned no audio.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"TTS unavailable: {exc}") from exc

    async def audio_stream():
        yield first_chunk
        async for chunk in stream:
            yield chunk

    return StreamingResponse(audio_stream(), media_type="audio/mpeg")

@api_router.get("/memory/recent", status_code=status.HTTP_200_OK)
async def get_recent_memories(
    limit: int = Query(5, ge=1, le=20),
    project_id: str = Query("personal", min_length=1),
):
    """Return only recent memories belonging to the requested project."""
    try:
        from backend.app.memory.vector_store import VectorStore
        rows = VectorStore().list_recent_memories(limit=limit, project_id=project_id)
        for row in rows:
            row["content"] = (row.get("content") or "")[:120]
        return {"total": len(rows), "project_id": project_id, "memories": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory query failed: {e}") from e

@api_router.post("/db/backup", status_code=status.HTTP_200_OK)
async def create_db_backup():
    """Create a verified online backup without blocking the async event loop."""
    from backend.app.database.backup import backup_database
    from backend.app.database.durability import load_durability_settings

    settings = load_durability_settings()
    result = await asyncio.to_thread(
        backup_database,
        None,
        settings.backup_generations,
    )
    if not result["success"]:
        code = 503 if "maintenance" in (result.get("error") or "").lower() else 500
        raise HTTPException(status_code=code, detail=result["error"])
    return result


@api_router.get("/db/integrity", status_code=status.HTTP_200_OK)
async def db_integrity():
    """Report local database integrity and core table row counts."""
    from backend.app.database.backup import check_integrity

    result = await asyncio.to_thread(check_integrity)
    if not result["success"] and "maintenance" in (result.get("error") or "").lower():
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@api_router.post("/db/restore", status_code=status.HTTP_200_OK)
async def restore_db(request: BackupRequest):
    """Create/validate exact confirmation before executing a locked restore."""
    if not request.backup_path:
        raise HTTPException(status_code=400, detail="backup_path is required.")
    registry = ToolRegistry()
    return await registry.execute_tool(
        tool_id="database_restore",
        args={"backup_path": request.backup_path},
        has_confirmed=request.has_confirmed,
        confirmation_token=request.confirmation_token,
        session_id=request.session_id,
        max_retries=0,
        timeout=180.0,
    )

@api_router.get("/providers/status", status_code=status.HTTP_200_OK)
async def provider_status(live: bool = Query(False, description="Make one tiny live request per configured provider.")):
    """Report effective models, redacted key state and optional live reachability."""
    from backend.app.brain.model_config import validate_model_config, get_model

    orchestrator = get_orchestrator()
    manager = orchestrator.router.key_manager
    report = {
        "configuration": validate_model_config(),
        "providers": {},
        "live_checked": bool(live),
    }
    for provider in ("groq", "gemini", "nvidia"):
        configured = manager.has_real_key(provider)
        item = {
            "configured": configured,
            "model": get_model(provider),
            "key_states": manager.runtime_status()[provider],
            "reachable": None,
            "error": None,
        }
        if live and configured:
            try:
                response = await orchestrator.router._provider_executor(provider)(
                    "Provider health check. Reply exactly OK.",
                    "OK",
                    0.0,
                )
                item["reachable"] = bool(response and response.strip())
            except Exception as exc:
                item["reachable"] = False
                item["error"] = str(exc)[:240]
        report["providers"][provider] = item
    return report


@api_router.post("/personality", status_code=status.HTTP_200_OK)
async def set_session_personality(request: PersonalityRequest) -> dict:
    """Persist an explicit UI personality selection for the resolved session."""
    from backend.app.database.models import update_session_personality
    from backend.app.session.session_manager import SessionManager

    try:
        session = SessionManager.get_or_create_session(request.session_id)
        with get_db_connection() as conn:
            update_session_personality(conn, session["id"], request.personality)
        return {
            "success": True,
            "session_id": session["id"],
            "personality": request.personality,
        }
    except DatabaseMaintenanceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@api_router.post("/coding-mode", status_code=status.HTTP_200_OK)
async def set_coding_mode(request: CodingModeRequest) -> dict:
    """Manually toggle NVIDIA coding mode on/off for the orchestrator."""
    try:
        orch = get_orchestrator()
        orch.set_coding_mode(request.enabled)
        return {"success": True, "coding_mode": orch.coding_mode}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to toggle coding mode: {str(e)}"
        ) from e
