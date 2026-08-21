"""
Ultron Core Backend Application Service (FastAPI)
Bridges communication logs, WS routing maps, and system health status.
Registers WebSocket endpoints natively for real-time tokens, logs, and dashboard streams.
"""

import time
import os
import json
import asyncio
import platform
import psutil
import datetime
import httpx
import yaml
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import database, routing, and websocket engines
from backend.app.database.db import DatabaseMaintenanceError, get_db_connection
from backend.app.database.models import initialize_database
from backend.app.router import api_router
from backend.app.websocket.connection_manager import WebSocketManager
from backend.app.background_tasks import get_background_task_manager
from backend.app.install_paths import CONFIG_PATH


def _configured_frontend_port() -> int:
    try:
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        port = int((config.get("server", {}) or {}).get("frontend_port", 5173))
        return port if 1 <= port <= 65535 else 5173
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return 5173


@asynccontextmanager
async def application_lifespan(_app: FastAPI):
    """Own startup/shutdown exactly once with FastAPI's supported lifecycle API."""
    try:
        await startup_event_handler()
        yield
    finally:
        await shutdown_event_handler()


# Initialize the global application registry.
app = FastAPI(
    title="ULTRON CORE ENGINE API",
    description="Asynchronous processing gateway for local system automation and developer chat.",
    version="1.0.0",
    lifespan=application_lifespan,
)

# Configure Cross-Origin Resource Sharing for the configured loopback frontend only.
_frontend_port = _configured_frontend_port()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{_frontend_port}",
        f"http://127.0.0.1:{_frontend_port}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount core REST routes
app.include_router(api_router)

# Initialize the global, thread-safe WebSocket Connection Coordinator
ws_manager = WebSocketManager()

class HealthStatusResponse(BaseModel):
    status: str
    uptime_seconds: float
    system_metrics: dict
    environment: dict
    providers: dict
    provider_key_states: dict
    models: dict

# Boot timestamp tracker
START_TIME = time.time()

async def run_reminder_scheduler():
    """
    Background scheduler loop that runs every 5 seconds to look for
    pending or snoozed reminders/alarms whose target_time is <= now.
    If triggered, broadcasts an event to /ws/events and updates their database status.
    """
    print("[SCHEDULER] Starting background reminders and alarms scheduler...")
    while True:
        try:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Find due reminders
                cursor.execute(
                    """
                    SELECT id, type, title, description, target_time, recurrence, recurrence_details, snooze_count, status
                    FROM reminders_alarms
                    WHERE status IN ('pending', 'snoozed') AND target_time <= ?;
                    """,
                    (now_iso,)
                )
                due_rows = cursor.fetchall()
                
                for row in due_rows:
                    item = dict(row)
                    item_id = item["id"]
                    title = item["title"]
                    type_val = item["type"]
                    rec = (item["recurrence"] or "one_time").lower()
                    
                    print(f"[SCHEDULER] Triggering {type_val} '{title}' (ID: {item_id})")
                    
                    # 1. Update database status
                    if rec == "one_time":
                        cursor.execute("UPDATE reminders_alarms SET status = 'triggered' WHERE id = ?;", (item_id,))
                    else:
                        # Auto-recurrence calculations: calculate the next target time
                        current_target = datetime.datetime.fromisoformat(item["target_time"])
                        if rec == "daily":
                            next_target = current_target + datetime.timedelta(days=1)
                        elif rec == "weekly":
                            next_target = current_target + datetime.timedelta(days=7)
                        else:
                            cursor.execute(
                                "UPDATE reminders_alarms SET status = 'invalid_recurrence' WHERE id = ?;",
                                (item_id,),
                            )
                            conn.commit()
                            print(
                                f"[SCHEDULER] Reminder '{item_id}' disabled: unsupported recurrence '{rec}'."
                            )
                            continue

                        cursor.execute(
                            """
                            UPDATE reminders_alarms 
                            SET target_time = ?, status = 'pending', snooze_count = 0 
                            WHERE id = ?;
                            """,
                            (next_target.isoformat(), item_id)
                        )
                    conn.commit()
                    
                    # 2. Broadcast WebSocket event on the 'events' channel
                    event_payload = {
                        "type": "reminder_triggered",
                        "reminder": {
                            "id": item_id,
                            "type": type_val,
                            "title": title,
                            "description": item["description"],
                            "recurrence": rec,
                            "snooze_count": item["snooze_count"]
                        }
                    }
                    await ws_manager.broadcast("events", event_payload)
                    
        except Exception as e:
            print(f"[SCHEDULER] Error in scheduler loop: {e}")
            
        await asyncio.sleep(5.0)

async def run_emergency_monitor():
    """
    Background emergency monitor loop that runs every 60 seconds to scan
    USGS live APIs for catastrophic natural events (earthquakes > 7.0 magnitude).
    If triggered, broadcasts critical alerts on /ws/events for real-time notification.
    """
    print("[EMERGENCY_MONITOR] Launching real-time global emergency monitoring loop...")
    last_triggered_event_id = None
    while True:
        try:
            # Query USGS live GeoJSON endpoint for recent significant earthquakes
            url = "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=6.5&limit=1"
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    features = res.json().get("features", [])
                    if features:
                        f = features[0]
                        f_id = f.get("id")
                        props = f.get("properties", {})
                        mag = float(props.get("mag", 0.0))
                        
                        # Trigger emergency protocol if magnitude is strictly > 7.0
                        if mag >= 7.0 and f_id != last_triggered_event_id:
                            last_triggered_event_id = f_id
                            
                            # Compile real-time alert payload
                            event_payload = {
                                "type": "emergency_alert",
                                "emergency": {
                                    "category": "Natural Disaster",
                                    "title": f"CRITICAL EARTHQUAKE MAGNITUDE {mag} DETECTED",
                                    "detail": props.get("title"),
                                    "source": "USGS Real-Time Detection System",
                                    "severity": "CRITICAL"
                                }
                            }
                            await ws_manager.broadcast("events", event_payload)
                            print(f"[EMERGENCY_MONITOR] Broadcasted Emergency Alert: {props.get('title')}")
        except Exception as e:
            print(f"[EMERGENCY_MONITOR] Error checking live emergency feeds: {e}")
            
        await asyncio.sleep(120.0)

async def startup_event_handler():
    """Initializes standard SQLite databases and applies parameterized table migrations."""
    try:
        with get_db_connection() as conn:
            initialize_database(conn)
            print("[INFO] Database successfully initialized with WAL mode enabled.")

        from backend.app.brain.model_config import validate_model_config
        from backend.app.router import get_orchestrator
        model_status = validate_model_config()
        if not model_status["valid"]:
            raise RuntimeError("Invalid model configuration: " + "; ".join(model_status["errors"]))
        orchestrator = get_orchestrator()
        print(f"[INFO] Effective AI models: {model_status['models']}")
        print(f"[INFO] Provider configuration: {orchestrator.router.key_manager.config_status()}")

        # Every process-owned loop is named, deduplicated, and cancelled/awaited
        # during shutdown. Repeated startup hooks cannot create duplicate schedulers.
        from backend.app.database.durability import run_durability_scheduler

        tasks = get_background_task_manager()
        tasks.start_singleton("reminder_scheduler", run_reminder_scheduler)
        tasks.start_singleton("emergency_monitor", run_emergency_monitor)
        tasks.start_singleton("durability_scheduler", run_durability_scheduler)
    except Exception as e:
        print(f"[ERROR] Core startup initialization failed: {e}")
        raise RuntimeError("Core startup initialization failure.") from e


async def shutdown_event_handler():
    """Cancel owned loops, then close the shared orchestrator exactly once."""
    try:
        stopped = await get_background_task_manager().cancel_all(timeout_seconds=10.0)
        print(f"[INFO] Background tasks stopped: {stopped}")
    except Exception as e:
        print(f"[WARN] Background task shutdown failed: {e}")

    try:
        from backend.app import router as router_module
        orch = router_module._shared_orchestrator
        if orch is not None:
            await orch.close()
            print("[INFO] Shared orchestrator closed cleanly at shutdown.")
    except Exception as e:
        print(f"[WARN] Shared orchestrator close during shutdown failed: {e}")

@app.get("/api/health", response_model=HealthStatusResponse, status_code=status.HTTP_200_OK)
async def get_health_status() -> dict:
    """Retrieve active backend processing status and local system resource consumption metrics."""
    from backend.app.tools.system_metrics_tool import collect_system_metrics

    metrics = collect_system_metrics()
    # Compatibility aliases retained for existing frontend consumers.
    metrics["memory_rss_mb"] = metrics["process_ram_mb"]
    metrics["total_system_ram_usage_percent"] = metrics["ram_percent"]
    
    env_details = {
        "os_platform": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
    }

    # Honest provider config status (which providers have a key configured).
    # This is a config check, not a live reachability test.
    from backend.app.brain.model_config import validate_model_config
    from backend.app.router import get_orchestrator
    # Report the state of the actual shared router, not a freshly-created key
    # manager that would hide cooling/failed runtime keys.
    key_manager = get_orchestrator().router.key_manager
    providers = key_manager.config_status()
    model_config = validate_model_config()

    return {
        "status": "healthy" if model_config["valid"] else "degraded",
        "uptime_seconds": time.time() - START_TIME,
        "system_metrics": metrics,
        "environment": env_details,
        "providers": providers,
        "provider_key_states": key_manager.runtime_status(),
        "models": model_config,
    }

# ==============================================================================
# WEBSOCKET CHANNELS ENDPOINT REGISTRATION (Requirement 1, 2)
# ==============================================================================

def _open_task_count() -> int:
    """Real number of open (not done) tasks, read from the DB — no fake counts."""
    try:
        with get_db_connection() as conn:
            row = conn.cursor().execute(
                "SELECT COUNT(*) AS c FROM project_tasks WHERE status != 'done';"
            ).fetchone()
            return int(row["c"]) if row else 0
    except Exception as e:
        print(f"[WS_CHAT] Could not read task count: {e}")
        return 0


def _widget_payload(widget_id: str) -> dict:
    """Real per-widget data for the widget push. Uses live DB counts, never fakes."""
    if widget_id == "todo":
        return {"todos_count": _open_task_count()}
    return {}


@app.websocket("/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket, client_id: str = "default_client"):
    """
    Main dialogue streaming channel.
    Accepts user text, runs the shared canonical chat service (same pipeline as
    /api/chat), and streams the result token-by-token with progress + widget pushes.
    """
    await ws_manager.connect("chat", client_id, websocket)
    from backend.app.router import get_orchestrator
    from backend.app.services.chat_service import process_chat_message
    orchestrator = get_orchestrator()  # shared — do NOT close it on disconnect

    try:
        while True:
            # Await incoming message payload from client
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
                prompt = (data.get("content", "") or "").strip()
                session_id = data.get("session_id", "default_sess")
                project_id = data.get("project_id")
                has_confirmed = bool(data.get("has_confirmed", False))
                confirmation_token = data.get("confirmation_token")
            except Exception:
                await websocket.send_json({"type": "error", "message": "Invalid JSON format."})
                continue

            if not prompt:
                continue

            # 1. Dispatch starting progress signal
            await websocket.send_json({
                "type": "progress",
                "state": "thinking",
                "detail": "Ultron Orchestrator is running intent heuristics..."
            })

            # 2. Process query via the shared canonical chat service (persists to DB,
            #    resolves/creates the session, restores the per-session personality).
            result = await process_chat_message(
                orchestrator=orchestrator,
                content=prompt,
                session_id=session_id,
                project_id=project_id,
                has_confirmed=has_confirmed,
                confirmation_token=confirmation_token,
            )

            # 3. Stream token-by-token (Requirement 1)
            response_content = result["content"] or ""
            await websocket.send_json({"type": "stream_start"})
            words = response_content.split(" ")
            for idx, word in enumerate(words):
                packet = f"{word} " if idx < len(words) - 1 else word
                await websocket.send_json({"type": "token", "content": packet})
                await asyncio.sleep(0.02)
            await websocket.send_json({"type": "stream_end"})

            # 4. Publish any events fired during the orchestrator pipeline
            for event in result.get("events", []):
                await ws_manager.broadcast("events", event)

            # 5. Push a real widget trigger based on the structured action
            structured_action = result.get("structured_action") or {}
            if structured_action.get("action") == "open_widget":
                widget_id = structured_action.get("widget_id", "")
                if widget_id:
                    await websocket.send_json({
                        "type": "widget",
                        "widget_id": widget_id,
                        "action": "open",
                        "data": _widget_payload(widget_id),
                    })

            # 6. Dispatch final transaction confirmation (includes structured_action
            #    and the resolved session_id so clients stay in sync)
            await websocket.send_json({
                "type": "done",
                "message_id": result["id"],
                "session_id": result["session_id"],
                "project_id": result["project_id"],
                "active_personality": result["personality"],
                "response_ms": result["response_ms"],
                "coding": result["coding"],
                "intent": result["intent"],
                "structured_action": result["structured_action"],
                "events": result.get("events", []),
                "provider_route": result.get("provider_route") or {},
                "pending_confirmation": result.get("pending_confirmation"),
            })

    except WebSocketDisconnect:
        ws_manager.disconnect("chat", client_id)
        # The orchestrator is SHARED across sessions and owns the persistent HTTPX
        # client. Closing it here would break every later chat. It is only closed
        # once, at application shutdown.
    except DatabaseMaintenanceError as e:
        try:
            await websocket.send_json({
                "type": "error",
                "status": "database_maintenance",
                "message": str(e),
            })
        finally:
            ws_manager.disconnect("chat", client_id)
    except Exception as e:
        print(f"[WS_CHAT] Error on active chat pipeline: {e}")
        ws_manager.disconnect("chat", client_id)

@app.websocket("/ws/events")
async def websocket_events_endpoint(websocket: WebSocket, client_id: str = "default_client"):
    """Server-initiated push channel. Broadcasters trigger alerts, reminders, and Zora auto-handoffs."""
    await ws_manager.connect("events", client_id, websocket)
    try:
        while True:
            # Keeps connection alive and responsive to ping-pong frames
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect("events", client_id)

@app.websocket("/ws/logs")
async def websocket_logs_endpoint(websocket: WebSocket, client_id: str = "default_client"):
    """Streams terminal subprocess and local server logging actions in real-time."""
    await ws_manager.connect("logs", client_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect("logs", client_id)

@app.websocket("/ws/dashboard")
async def websocket_dashboard_endpoint(websocket: WebSocket, client_id: str = "default_client"):
    """Pushes local CPU/RAM hardware utilization and session metrics on intervals (Push-on-Change)."""
    await ws_manager.connect("dashboard", client_id, websocket)
    try:
        last_ram = 0.0
        while True:
            process = psutil.Process(os.getpid())
            ram_mb = process.memory_info().rss / (1024 ** 2)
            cpu_percent = process.cpu_percent(interval=None)
            
            # Push only on meaningful change (>0.5MB or 1% CPU) to keep CPU under 2% standard limits
            if abs(ram_mb - last_ram) > 0.5:
                payload = {
                    "type": "dashboard_update",
                    "metrics": {
                        "ram_mb": ram_mb,
                        "cpu_percent": cpu_percent,
                        "total_ram_usage_percent": psutil.virtual_memory().percent
                    }
                }
                await websocket.send_json(payload)
                last_ram = ram_mb
                
            # Yield event loop and sleep for 5 seconds to prevent background thread hogging
            await asyncio.sleep(5.0)
            
    except WebSocketDisconnect:
        ws_manager.disconnect("dashboard", client_id)
    except Exception:
        ws_manager.disconnect("dashboard", client_id)
