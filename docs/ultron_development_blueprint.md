# Current Personal V1 Technical Blueprint

This replaces the historical aspirational blueprint with the implemented architecture.

## Product boundary

One owner, one local laptop, localhost UI, local SQLite, cloud provider APIs when configured. No OAuth server, multi-user tenancy, container orchestration, or public SaaS layer is required.

## Brain

- Groq chat default: `openai/gpt-oss-20b`
- Gemini fallback: `gemini-3.5-flash`
- NVIDIA coding: `nvidia/nemotron-3-ultra-550b-a55b`
- Embedding: `gemini-embedding-001`, configurable dimensions (default 768)
- Config-driven primary/secondary order, timeout, bounded attempts and cooldown backoff
- Capability-ordered providers (not provider round-robin) with per-provider key rotation
- Provider/model-aware cache and rejected-model process guard
- Auto coding mode by default; manual Coding ON forces NVIDIA for all turns
- Explicit offline state when no provider is configured

## Owner personality and memory

Ultron and Zora are original partners built by and for Debjeet. They learn only from his current words, canonical history, corrected saved memory, summaries, and real tool results. History, recall, and project blocks are bounded and labelled `DATA_NOT_INSTRUCTIONS`. Study plans/deadlines and stated mistakes/lessons map into the existing task/problem/solution taxonomy; nothing is inferred as owner fact.

SQLite stores sessions/history and float32 embedding BLOBs. Recall/list/dedup/correction/forget/restore/re-embed operations are project-scoped. Legacy memories without project metadata belong to `personal`.

## Tools and safety

Filesystem, terminal, Git/GitHub, browser/search, weather/research, music/Spotify, reminders, tasks, calendar, memory, security, conversion, coding analysis, world monitor, and system telemetry remain available through 69 lazily registered IDs. Prompt assembly ranks IDs from a lightweight manifest, caps context at eight relevant tools, and imports only those selected classes and real input schemas; direct execution stays JIT by ID.

Filesystem roots are configurable and fail closed. Native provider function calls run in a bounded sequential inspect/act/observe loop and remain locked to the starting provider. Agent-relative paths resolve through the configured project ID/root and cannot escape that root. Local file-content egress requires exact confirmation; tool results are bounded/redacted before cloud continuation, and the original agent history resumes after approval. Level 2/3 actions still require exact one-time confirmation. Coding modifications are inspected, fingerprint-bound, syntax-verified, backed up, and atomically replaced; the existing file-write tool also supports exact single-block patch mode without adding another tool ID.

## Durability

Automatic online SQLite backups, retention, integrity checks, WAL checkpoints, generated-data retention, exclusive restore maintenance, safety copy, and automatic rollback support long-term local use.

## UI and launcher

React widgets consume real backend data or display unavailable. Vite dev/preview is loopback-only. Daily operation uses a production build and Python static server. Launcher controls dependency/build fingerprints, health gates, browser dispatch, process monitoring, and cleanup.

## Voice

Browser Web Speech handles low-runtime-load recognition. One `Ultron`/`Hey Ultron` wake unlocks follow-up turns until Stop Voice; transcript replacement, latest callback refs, half-duplex TTS pause, bounded restart and truthful states are covered by deterministic frontend tests. Canonical chat/session/project/exact-confirmation behavior is preserved. `POST /api/speak` preflights and streams the existing Edge TTS only. Stop Voice aborts fetch/generation; supported browsers play progressive MP3 chunks and others use the complete-blob fallback. No fake audio is returned when the provider fails.

## Quality boundary

Automated tests, audits, coverage, and builds are release gates, not proof of zero future defects. Windows/browser/microphone/Spotify/live-provider acceptance remains a real-device requirement.
