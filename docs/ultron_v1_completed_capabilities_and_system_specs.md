# Personal V1 Capabilities and Verification Boundaries

## Implemented capabilities

- REST and WebSocket chat with provider route metadata
- project-scoped short/long-term memory controls
- coding analysis and confirmation-gated verified writes
- approved filesystem and terminal operations
- reminders, alarms, tasks, calendar, daily briefing
- weather, public search/research, world monitoring
- Git status/clone and authenticated GitHub operations when configured
- local music and Spotify control when supported applications exist
- browser-side recognition and Edge-TTS output
- truthful system telemetry and unavailable sensor states
- automatic verified database backups and safe restore
- localhost-only production launcher
- wheel/source installation layouts

## Security and durability specifications

- SQLite WAL with maintenance gate and migrations
- exact one-time action confirmation
- allowlisted paths and terminal executables
- SSRF/DNS/redirect/size controls
- side-effect retries disabled by default
- tracked/cancelled background tasks
- verified backup retention and restore rollback
- redacted tool audit data

## Quality evidence

The current release process requires passing test, coverage, Ruff, Bandit, dependency-audit, wheel-install, production-build, and data-isolation gates. Exact test counts are intentionally not frozen here because regression coverage grows.

## Not claimed by automated evidence

- absence of every future defect;
- total statement/branch coverage;
- live availability of external providers;
- Windows/browser/microphone/Spotify behavior not exercised on target hardware;
- uninterrupted multi-year operation without maintenance or dependency updates.

Use **Personal V1 release candidate** until owner-hardware acceptance completes.
