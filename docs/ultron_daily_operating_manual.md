# Daily Operating Manual

## Start

Beginner mode: click `Ultron` in Windows Start Menu/Desktop or Ubuntu Applications. The top activity line shows the real current state. Click `Stop Ultron` for graceful shutdown and `Ultron Keys` to update credentials.

Command mode remains available:

```bash
ultron doctor
ultron start
ultron stop
```

`doctor` separates required failures from optional warnings. `start` uses a single-instance lock, loopback ports, production frontend assets, two health gates, and child monitoring.

If both services are healthy but browser dispatch is unavailable, open:

```text
http://127.0.0.1:5173
```

## Stop

Press `Ctrl+C` in the launcher terminal. The launcher asks both process groups to terminate, waits for a bounded grace period, and force-stops only as a last resort. An unexpected child exit stops its sibling and returns a failure code.

## First-open Jarvis briefing

The first successful UI connection on each local calendar day requests one daily briefing. The greeting follows the actual open time, so opening at afternoon/evening/night does not produce a morning greeting. The successful date is stored in browser local storage to prevent repeat briefings on reload. If persistent browser storage is blocked, a page-level guard still prevents repeats during that open page.

There is no fixed 8 AM background briefing poll. Reminders, emergency monitoring, and durability scheduling remain active and unchanged.

When the browser tab is hidden, health polling slows to 30 seconds; making the tab visible triggers an immediate refresh.

## Chat and providers

- Normal/casual turns prefer Groq.
- Coding turns may use NVIDIA according to the coding-mode policy.
- Gemini is a configured fallback and embedding provider.
- If no real key exists, the UI receives an explicit offline/unprocessed message.

Check configuration without exposing secrets:

```text
GET /api/providers/status
```

## Confirmed actions

Terminal, delete, database restore, and other Level 2/3 actions produce a one-time exact confirmation. Review the displayed path/command/action summary before approving. A raw boolean or replayed token is not authorization.

## Memory and projects

Use a stable project ID for project-specific memory. Recent memory, remember/list/export, correction, deletion, restore, and re-embedding are available through the memory tool. Destructive operations require confirmation.

## Reminders, tasks, and calendar

Widgets read SQLite records. Invalid reminder times are rejected instead of silently creating a different time. Empty/unavailable states are distinct.

## Voice

Browser recognition requires microphone permission and a supported Web Speech implementation. Speech output uses `POST /api/speak`; immediate provider failure returns unavailable rather than fake audio. ffmpeg may be needed for optional media workflows.

## System and external data

Telemetry displays only values reported by psutil. Missing battery/temperature/network sensors show unavailable. Weather/news/research widgets show sourced live results or unavailable; no sample records are substituted.

## Backups

Daily verified backups and retention are automatic by default. Manual commands:

```bash
ultron backup
ultron integrity
```

Practice restore only with a disposable copy first. Restore enters maintenance, verifies the source, creates a safety copy, and rolls back on failed integrity.

## Troubleshooting

- Port occupied: close the existing Ultron instance; do not start a second launcher.
- Frontend rebuild failure: verify Node 20.19+ or 22.12+ and run `npm ci` in `frontend`.
- Provider unavailable: verify the relevant `.env` key and `/api/providers/status`.
- Tool path blocked: add only the intended personal root to `security.allowed_directories`.
- Browser/microphone/Spotify failure: record as unavailable until verified on the real device.
