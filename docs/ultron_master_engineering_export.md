# Ultron Personal V1 Engineering Reference

## Scope

Ultron/Zora is a local-first assistant for a single owner. This document describes implemented behavior at the current commit; Git history and tests remain the source of truth.

## Runtime services

- `launcher.py`: single-instance process owner and production frontend preparation.
- `backend.app.main`: FastAPI lifespan, REST, WebSocket, health, scheduler ownership.
- `backend.app.static_server`: loopback-only built frontend serving with `/healthz`.
- React frontend: chat, logs, voice controls, and lazy widgets.

Both services bind to `127.0.0.1`. The launcher validates typed health payloads before browser dispatch and shuts down a sibling if either child exits.

## Provider routing

`LLMRouter` uses config-driven model IDs, a real-key cascade, per-provider/model cache identity, temporary cooldowns, and auth/config failure classification. No-key mode explicitly states that no model processed the prompt. Live provider reachability is distinct from configuration status.

## State and memory

SQLite WAL tables hold sessions, conversation history, reminders, tasks, calendar entries, vector memory, and audit records. History selects the newest bounded rows then returns chronological order. Vector metadata records project/session/category/importance/model/dimensions.

## Safety model

1. Pydantic argument validation.
2. Approved-directory/path validation.
3. Permission level resolution.
4. One-time exact confirmation for Level 2/3.
5. Bounded execution with no default side-effect retries.
6. Redacted SQLite audit logging.

Terminal execution uses approved commands, approved working directories, bounded retained output, full pipe draining, and process-group timeout cleanup. Coding writes require inspection fingerprints and syntax verification before atomic replacement.

## Outbound operations

Server-side URL handling blocks credentials, non-HTTP schemes, loopback/private/link-local/reserved/multicast/metadata targets, unsafe DNS answers, and unsafe redirects. Downloads/pages have byte limits and atomic cleanup. GUI/browser dispatch is reported as dispatched or unavailable, not guaranteed opened.

## Durability

SQLite online backups are verified and pruned by configured generations. A low-frequency scheduler handles backup due state, integrity, WAL, audits, caches, and logs. Restore is approved-path and exact-confirmation gated, blocks new DB/tool writes, waits active operations, checkpoints WAL, creates a verified safety copy, atomically replaces, verifies, and rolls back if needed.

## Packaging

The PEP 517 wheel contains backend code, personality and skill markdown, config, launcher, `.env` template, and full frontend source/lockfile. Installed assets are discovered through distribution metadata and writable state is kept outside site-packages.

## Voice and UI truthfulness

Browser recognition is client-side; Edge-TTS uses `POST /api/speak`. Missing providers/sensors/network data produce unavailable states. Research, weather, notifications, Git, system, memory, tasks, and calendar widgets do not insert sample records.

## Release gates

- isolated pytest and independent unittest;
- application coverage threshold;
- Ruff actionable correctness rules;
- Bandit medium/high security findings;
- Python and npm vulnerability audits;
- frontend production build;
- clean wheel installation;
- production-data before/after hash.

## Acceptance still requiring owner hardware

Authenticated provider/GitHub/Tavily calls, Windows process behavior, browser GUI, microphone recognition, audible TTS/interruption, Spotify desktop, and long-duration soak testing must be verified on the target laptop.
