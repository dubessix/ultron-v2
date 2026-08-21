# Current Architecture

## Runtime layout

```text
Browser (127.0.0.1:5173)
  └─ production static frontend server
       ├─ REST/streaming audio → FastAPI (127.0.0.1:8000)
       └─ WebSocket → FastAPI

FastAPI
  ├─ canonical chat service / shared orchestrator
  ├─ provider-aware LLM router and bounded cache
  ├─ project-scoped memory and SQLite WAL database
  ├─ exact-confirmation tool registry
  ├─ filesystem/terminal/external/productivity tools
  ├─ reminders and background durability coordinator
  └─ WebSocket manager
```

## Local boundaries

- Launcher, backend, frontend dev server, and frontend production server bind only to loopback.
- CORS permits only configured localhost/127.0.0.1 frontend origins.
- The launcher validates both health response schemas before opening the browser.
- One launcher instance owns both process groups; an unexpected child exit stops its sibling.

## Storage

SQLite stores sessions, conversations, reminders, tasks, calendar events, vector memories, and tool audits. WAL mode supports normal concurrency. Restore enters exclusive maintenance, waits for active operations, verifies the source, creates a safety copy, atomically replaces the database, checks integrity, and rolls back on failure.

Tests redirect database, cache, backup, logs, and generated files into temporary storage.

## AI routing

Effective models come from `config.yaml` or environment overrides:

- Groq: `llama-3.1-8b-instant`
- Gemini: `gemini-3.5-flash`
- NVIDIA: `nvidia/nemotron-3-ultra-550b-a55b`
- Embeddings: `gemini-embedding-001` (768 dimensions by default)

Cache identity includes provider and model. Missing keys produce an explicit offline/unprocessed state. Provider failures are not cached as answers.

## Security controls

- approved-directory and sensitive/system path enforcement;
- public-URL/DNS/redirect checks for server-side requests;
- exact one-time confirmation for Level 2/3 actions;
- command allowlist plus process-group timeout cleanup;
- sequential coding writes with inspection fingerprints and atomic replacement;
- redacted tool audit arguments.

## Interfaces

REST details: `docs/api_reference.md`.

WebSockets:

- `/ws/chat`
- `/ws/events`
- `/ws/logs`
- `/ws/dashboard`

Browser speech recognition remains client-side. Speech synthesis is `POST /api/speak`; no voice WebSocket is registered.
