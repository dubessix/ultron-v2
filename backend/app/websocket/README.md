# Module: Real-Time WebSocket Streaming Subsystem (`backend/app/websocket/`)

This moudle manages high-speed, multi-channel WebSocket streaming networks. It ensures token-by-token text streaming, widget activations, system logging broadcasts, and push-on-change hardware metrics are pushed to the client in real-time.

---

## 1. Directory File Map & Responsibilities

```
backend/app/
├── main.py                     # Host FastAPI registry and WS endpoint wrappers
└── websocket/
    ├── connection_manager.py   # Thread-safe WebSocketManager tracking active channels
    └── README.md               # Documentation (This file)
```

### A. `connection_manager.py` (The Central Coordinator)
*   **Role**: Exposes `WebSocketManager`. Tracks client IDs and open WebSocket handles in thread-safe memory maps grouped by channels:
    *   `chat`: Progressive token-by-token streaming, active tool execution state updates, and dynamic HTML5 floating widget openings.
    *   `events`: Server-initiated pushing gateway (broadcasting reminders, background task logs, and automatic Zora transitions).
    *   `logs`: Live shell log stream aggregator.
    *   `dashboard`: Live host machine hardware usage pusher.
*   **Safety limits**: Wraps all transmissions in connection-drop checks, deleting closed sockets on-the-fly to prevent memory bloat on an 8GB PC.

### B. `backend/app/main.py` (FastAPI Endpoint Hooks)
*   Exposes endpoints:
    *   `/ws/chat`: Receives prompts, calls the Orchestrator, splits completions into words, and streams them as `type: "token"` packets.
    *   `/ws/events`: Keeps connections open for async server pushes.
    *   `/ws/logs`: Subscribes clients to terminal logging queues.
    *   `/ws/dashboard`: Monitors RAM/CPU via `psutil` and pushes packets on a slow, low-intensity 5s interval to conserve CPU.

---

## 2. Diagnostic Tests & Manual Execution

To verify Phase 8 WebSockets independently when your development machine is restored, run:

```bash
# Execute complete unit, integration, and E2E diagnostics across all 8 completed phases
./venv/bin/python -m unittest tests/test_phase1.py tests/test_phase2.py tests/test_phase3.py tests/test_phase4.py tests/test_phase5.py tests/test_phase6.py tests/test_phase7.py tests/test_phase8.py
```

This test suite verifies:
1.  Handshaking and client subscription tracking.
2.  Progressive, word-by-word streaming of text tokens.
3.  Active widget payload injection on matching prompts.
4.  Dynamic event broadcasting to multiple concurrent subscribers.
