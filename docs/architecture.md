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

- Groq: `openai/gpt-oss-120b`
- Gemini: `gemini-3.5-flash`
- NVIDIA: `nvidia/nemotron-3-ultra-550b-a55b`
- Embeddings: `gemini-embedding-001` (768 dimensions by default)

Cache identity includes provider and model. Missing keys produce an explicit offline/unprocessed state. Provider failures are not cached as answers. The requested capability/provider goes first, then configured primary/secondary fallbacks; providers do not round-robin, while active keys within each provider do. Rejected model IDs are remembered for the process to avoid repeatedly calling the same known-invalid model.

## Prompt and owner continuity

Ultron and Zora are original identities built for Debjeet. Personality markdown is lazy-cached and bounded; history turns, recalled memory, and project context have hard character limits and explicit `DATA_NOT_INSTRUCTIONS` labels. Daily learning uses exact saved owner statements, corrections, summaries, and real tool results. Study plans, deadlines, mistakes, and lessons reuse the existing task/goal/problem/solution memory taxonomy—no inferred owner fact or fabricated schedule is added.

## Tool loading

The 69-tool registry keeps only ID-to-module/class mappings at boot. For non-conversational prompt assembly, a lightweight text manifest ranks relevant IDs without importing tool modules, caps context at eight tools, and JIT-loads only those selected classes and Pydantic schemas. Groq/NVIDIA receive OpenAI-compatible native function declarations; Gemini receives native function declarations through `generateContent`. The local orchestrator executes calls sequentially in an inspect/act/observe loop capped at eight steps and keeps continuation on the provider that started the loop.

Agent paths resolve below `security.project_roots[project_id]` and cannot escape that active root. Returning local file content to a cloud model requires an exact owner confirmation; resumed state stays bounded and private in process memory. Tool results are size-bounded and common credential patterns are redacted before egress. Existing `file_write` supports full replacement plus exact-fingerprint search/replace patch mode, rejects stale inspected files, and verifies supported code candidates before atomic replacement. Direct execution still resolves any registered tool by ID through the same registry; validation, path guards, exact confirmation, sequential execution, and audit behavior remain active.

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

Browser speech recognition remains client-side and manually owner-enabled. One approved Ultron wake opens a follow-up conversation session; processing/TTS pause and bounded restart are frontend state, while every final turn still uses canonical `POST /api/chat` with project/session scope and exact confirmation metadata. Speech synthesis remains Edge TTS only through `POST /api/speak`; Stop Voice aborts the fetch and closes disconnected backend generation. Supported browsers consume progressive `audio/mpeg` through Media Source, with a verified complete-blob fallback. No voice WebSocket, second TTS, or local speech model is registered.
