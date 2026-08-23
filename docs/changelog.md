# Changelog

## Real lazy-tool polish F2 (2026-08-23)

- Replaced prompt-time `get_all_tools()` with a lightweight prompt-scoped selector capped at eight relevant tools.
- JIT-imports only selected tool classes and includes their real Pydantic input schemas; greetings import no tool modules.
- Preserved all 69 registered IDs, direct JIT execution, path validation, exact confirmation, sequential execution, and audit behavior.
- Kept native provider function calling outside this phase.

## Final brain-truth polish F1 (2026-08-23)

- Replaced the retired Groq chat default with the official `openai/gpt-oss-20b` replacement and made validation reject known retired Groq IDs.
- Connected existing primary/secondary provider, timeout, attempt and cooldown-backoff configuration to runtime routing.
- Kept provider selection capability-ordered and per-provider API keys round-robin; known rejected provider/model pairs are skipped for the rest of the process.
- Clarified modes: Coding Auto routes coding intents to NVIDIA; manual Coding ON forces NVIDIA for every turn.

## One-wake voice conversation milestone (2026-08-23)

- Kept browser Web Speech as the low-runtime-load STT path; no always-on Python microphone service or local Whisper/openWakeWord runtime was added.
- Added one `Ultron`/`Hey Ultron` wake per Mic session followed by direct multi-turn conversation until Stop Voice.
- Replaced interim hypotheses by result index, restricted broad legacy wake triggers, accepted punctuation, and routed through the latest session callback.
- Added half-duplex processing/TTS pause, actual playback completion/error settlement, object-URL cleanup, and Stop Voice audio cancellation.
- Added deduplicated bounded recognition restart and explicit fatal/recoverable error handling.
- Preserved canonical project/session, response provenance/events/coding/widget actions and exact confirmation tokens while blocking same-tick overlap/replay.
- Added truthful waiting/active/paused/reconnecting/heard-text UI states for Ultron and Zora.
- Added cumulative Vitest/jsdom voice contracts to local and Windows/Ubuntu cloud gates; real owner microphone and audible TTS remain hardware acceptance.

## Memory and Core milestone (2026-08-22)

- Added deterministic session summaries and structured project memories with redaction, importance, revisioned correction, and exact-confirmed forgetting.
- Added durable project-scoped FTS recall, previous/current summary context, bounded conflict ordering, forgotten/corrected synchronization, and content-free provenance.
- Rebuilt the Ultron/Zora centre Core as a deterministic adaptive Fibonacci particle shell with state reactions and reduced-motion support.
- Added the M4 Memory Console: session summaries, important memories, project/category/importance filters, exact local search, redacted export, provenance/timestamps, and in-UI exact confirmation for correction/forgetting.
- Updated the signed prebuilt frontend so normal setup receives the M4 interface without requiring Node/npm.

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
