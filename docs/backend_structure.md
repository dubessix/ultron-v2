# Backend Structure

```text
backend/app/
├── main.py                  FastAPI lifespan, health, WebSockets
├── router.py                REST contracts and shared orchestrator
├── runtime_paths.py         isolated/test and writable runtime storage
├── install_paths.py         source/wheel/user installation layout
├── background_tasks.py      named task tracking and shutdown
├── static_server.py         loopback production frontend server
├── brain/                   provider routing, models, key state, cache
├── core/                    intent/confidence/decision/orchestration
├── database/                SQLite schema, connections, backup/durability
├── memory/                  short/project/vector/episodic/semantic memory
├── personalities/           Ultron/Zora prompts and state
├── security/                path, URL, permission, pending-action controls
├── services/                canonical REST/WebSocket chat processing
├── session/                 session creation/restoration
├── skills/                  coding instruction resources
├── tools/                   local, external, productivity, memory tools
├── voice/                   Edge-TTS provider and interruption lifecycle
└── websocket/               channel connection manager
```

## Important contracts

- All normal SQLite access passes through the maintenance coordinator.
- All tool calls pass schema validation, path preflight where applicable, exact confirmation for Level 2/3, timeout boundaries, and redacted audit logging.
- Coding writes require current inspection and use verified temporary candidates plus atomic replace.
- External server requests use public-host/DNS/redirect controls and bounded payloads.
- Provider/model IDs are config-driven; no-key chat returns explicit offline status.
- Optional data is never replaced with sample telemetry or fake success.

## Process lifecycle

`launcher.py` owns FastAPI and the production static frontend. It builds only when fingerprints change, validates both health schemas, opens a browser only after health, monitors exits, and terminates process groups on shutdown.

See `docs/architecture.md`, `docs/api_reference.md`, and module docstrings for current details.
