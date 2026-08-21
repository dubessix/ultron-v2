# Changelog

## Personal V1 repair series (2026-08-15)

### Phase 0–2

- Isolated all test storage and bounded semantic scans.
- Centralized effective model configuration and provider/model cache identity.
- Enforced allowed paths and exact one-time action confirmations.

### Phase 3–5

- Serialized coding changes and verified atomic writes.
- Hardened terminal process groups, output bounds, and command policy.
- Added URL/DNS/redirect/download controls and honest external-operation status.
- Corrected newest history and project-scoped memory controls.

### Phase 6–8

- Added online backups, retention, integrity/WAL maintenance, restore lock, and rollback.
- Added centralized background task lifecycle.
- Shipped config, launcher, frontend, prompts, and skills in the wheel.
- Replaced daily Vite dev serving with loopback production assets, two health gates, duplicate lock, monitoring, and bounded cleanup.
- Migrated FastAPI lifecycle to lifespan.

### Phase 9

- Removed known fabricated executable telemetry, weather, research/search, notification, Git, and briefing values.
- Added real local universal search and persisted UI personality selection.
- Changed no-key LLM and TTS/provider failures to explicit unavailable states.
- Reworded limited security checks so zero findings is not a safety guarantee.

### Phase 10

- Updated pinned Python and frontend dependencies.
- Added vulnerability, Ruff, Bandit, coverage, wheel-install, and build release gates.
- Replaced obsolete models/endpoints/counts and absolute quality claims in documentation.

### Safe idle refinement

- Replaced the unused fixed 8 AM briefing polling loop with one first-successful-UI-open briefing per local date and time-appropriate greeting.
- Hidden browser tabs use a slower health poll and refresh immediately on return.
- AI, coding tools, reminders, emergency monitoring, durability, permissions, database schema, and tool contracts remain unchanged.

### Independent clean-source audit fixes

- Fixed source-checkout production frontend startup so `backend.app.static_server` is imported from the repository root without injected `PYTHONPATH`.
- Code Optimizer now rejects invalid AST input, applies writes through atomic syntax verification/backups, and leaves ambiguous semantic transformations analysis-only.
- Invalid task status/priority and reminder recurrence are rejected rather than silently replaced.
- Calendar free-slot calculations normalize aware/naive timestamps and reject invalid duration bounds.
- Exact-commit fresh archive import, tool load, test, audit, build, launcher, REST, WebSocket, CRUD, confirmation, optimizer, live-data, and TTS-byte smoke checks passed.
- A future-due reminder was observed through the real scheduler broadcast and persisted as triggered within the five-second polling window.

### Exhaustive widget/frontend-backend audit

- Verified all 22 registered widget files and every lazy import; mapped each tool-backed widget to a real registered backend tool.
- Routed Market quotes through standardized backend World Monitor data instead of a direct browser fetch.
- Standardized World Monitor success/error payloads so ToolRegistry preserves earthquakes, market quotes, sentiment, and public-search details.
- Git Clone now passes the verified cloned path to VS Code; GUI dispatch remains explicitly unverified.
- Task, calendar, and semantic graph widgets now surface mutation/query failures instead of failing silently.
- Typed chat now falls back to REST only when a WebSocket request was never sent; an interrupted sent request is not replayed.
- Read-only Code Optimizer analysis no longer requests destructive confirmation; applying changes still requires exact confirmation.
- Live Git Clone exact confirmation, market/world schemas, semantic graph, optimizer, and frontend root were exercised in isolated storage.

### Lightweight beginner setup and app-menu launch

- Added one shared Tkinter setup/key window with honest progress text, secret-preserving key updates, runtime install/repair, Doctor/assets check, and shortcut creation.
- Added Windows and Ubuntu double-click setup wrappers plus canonical daily start scripts.
- Added Windows Start Menu/Desktop and Ubuntu Applications entries for Ultron, Stop Ultron, and Ultron Keys.
- Added signed prebuilt frontend assets so default-port daily installation/start does not require Node/npm; changed source/custom ports still require a verified rebuild.
- Added graceful external `ultron stop` request handling with PID ownership checks and zombie-process completion handling.
- Added Claude-Code-style main UI activity text from real health/WebSocket/confirmation states.

Git commit history is the source of truth for exact changes and hashes.
