# API Reference

Base URL: `http://127.0.0.1:8000`

## Health and providers

### `GET /api/health`

Returns backend status, uptime, reported local metrics, platform, redacted provider state, and effective model validation.

### `GET /api/providers/status?live=false`

Returns configured/redacted key state and model IDs. `live=true` makes a small request only for configured providers; it does not expose keys.

## Chat and sessions

### `POST /api/chat`

```json
{
  "session_id": null,
  "project_id": "personal",
  "content": "Hello",
  "has_confirmed": false,
  "confirmation_token": null
}
```

Response includes resolved session/project, content, personality, latency, structured action, events, provider route, and optional pending confirmation.

### `GET /api/history?session_id=<id>`

Returns the newest bounded session history in chronological display order.

### `POST /api/personality`

```json
{"session_id": "optional", "personality": "ultron"}
```

Persists `ultron` or `zora` for the resolved session.

### `POST /api/coding-mode`

```json
{"enabled": true}
```

Controls the shared coding-provider override.

## Tools and confirmation

### `POST /api/tools/execute`

```json
{
  "tool_id": "system_metrics",
  "arguments": {},
  "session_id": "frontend_tools",
  "has_confirmed": false,
  "confirmation_token": null
}
```

Level 2/3 tools return `PENDING_CONFIRMATION` with a token bound to the exact session, tool, and canonical arguments.

### `POST /api/actions/confirm`

```json
{"confirmation_token": "...", "session_id": "frontend_tools"}
```

Claims and executes the stored action without a second LLM call. Tokens expire and cannot be replayed.

## Voice

### `POST /api/speak`

```json
{"text": "Hello", "personality": "ultron"}
```

Preflights the speech provider and streams `audio/mpeg`. Immediate provider/no-audio failure returns HTTP 503; fake audio is not generated.

## Memory

### `GET /api/memory/recent?limit=5&project_id=personal`

Returns recent project-scoped memories with bounded content preview.

Memory write/list/correct/forget/export/restore/re-embed operations use `manage_memory` through the tool endpoint; destructive operations require exact confirmation.

## Database durability

- `POST /api/db/backup` — verified online backup and configured retention.
- `GET /api/db/integrity` — SQLite integrity and core table counts.
- `POST /api/db/restore` — creates an exact-confirmation action; source must be under the approved backup tree.

## WebSockets

See `docs/websocket_contract.md` for `/ws/chat`, `/ws/events`, `/ws/logs`, and `/ws/dashboard`.

## Error semantics

- HTTP 400: invalid/missing request data.
- HTTP 503: maintenance or provider/service unavailable where explicitly handled.
- Tool failures return `success: false` plus an error/status; unavailable data is not replaced with sample values.
