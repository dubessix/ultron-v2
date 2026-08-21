# Ultron Personal V1 Blueprint

The active technical blueprint is `docs/ultron_development_blueprint.md`.

Summary:

- single-owner, local-first assistant;
- loopback React/FastAPI services;
- cloud LLM routing with explicit offline behavior;
- SQLite WAL history, project memory, reminders, tasks, and calendar;
- confirmation/path-controlled local tools;
- verified backups and safe restore;
- production launcher with health and child monitoring;
- truthful unavailable states instead of sample telemetry/results;
- automated release gates plus separate owner-hardware acceptance.

Current models:

- `llama-3.1-8b-instant`
- `gemini-3.5-flash`
- `nvidia/nemotron-3-ultra-550b-a55b`
- `gemini-embedding-001`

Voice recognition uses browser Web Speech; TTS uses `POST /api/speak`. Current WebSockets are `/ws/chat`, `/ws/events`, `/ws/logs`, and `/ws/dashboard`.
