# Current Personal V1 Technical Blueprint

This replaces the historical aspirational blueprint with the implemented architecture.

## Product boundary

One owner, one local laptop, localhost UI, local SQLite, cloud provider APIs when configured. No OAuth server, multi-user tenancy, container orchestration, or public SaaS layer is required.

## Brain

- Groq chat default: `llama-3.1-8b-instant`
- Gemini fallback: `gemini-3.5-flash`
- NVIDIA coding: `nvidia/nemotron-3-ultra-550b-a55b`
- Embedding: `gemini-embedding-001`, configurable dimensions (default 768)
- Provider/model-aware cache and redacted key-state rotation
- Explicit offline state when no provider is configured

## Memory

SQLite stores sessions/history and float32 embedding BLOBs. Recall/list/dedup/correction/forget/restore/re-embed operations are project-scoped. Legacy memories without project metadata belong to `personal`.

## Tools and safety

Filesystem, terminal, Git/GitHub, browser/search, weather/research, music/Spotify, reminders, tasks, calendar, memory, security, conversion, coding analysis, world monitor, and system telemetry are registered lazily.

Filesystem roots are configurable and fail closed. Level 2/3 actions require exact one-time confirmation. Coding modifications are sequential, inspected, pre-verified, backed up, and atomically replaced.

## Durability

Automatic online SQLite backups, retention, integrity checks, WAL checkpoints, generated-data retention, exclusive restore maintenance, safety copy, and automatic rollback support long-term local use.

## UI and launcher

React widgets consume real backend data or display unavailable. Vite dev/preview is loopback-only. Daily operation uses a production build and Python static server. Launcher controls dependency/build fingerprints, health gates, browser dispatch, process monitoring, and cleanup.

## Voice

Browser Web Speech handles recognition. `POST /api/speak` preflights Edge-TTS and streams audio. No fake audio is returned when the provider fails.

## Quality boundary

Automated tests, audits, coverage, and builds are release gates, not proof of zero future defects. Windows/browser/microphone/Spotify/live-provider acceptance remains a real-device requirement.
