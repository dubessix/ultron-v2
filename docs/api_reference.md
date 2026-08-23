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

`content` is limited to 12,000 characters for REST and canonical WebSocket processing. Response includes resolved session/project, content, personality, latency, structured action, events, provider route, optional pending confirmation, and content-free `memory_provenance` describing any saved sources injected into the turn.

### `GET /api/history?session_id=<id>`

Returns the newest bounded session history in chronological display order.

### `GET /api/session-summary/{session_id}`

Returns the bounded deterministic digest stored in the existing session record. If missing, it is rebuilt from canonical saved conversations. Secret-like assignments/prefixes are redacted.

### `GET /api/session-summary/last?project_id=personal&exclude_session_id=<id>`

Returns the latest valid summary in one project, optionally excluding the current session. A missing previous summary returns `available: false` rather than fabricated content.

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

Level 2/3 tools return `PENDING_CONFIRMATION` with a token bound to the exact session, tool, and canonical arguments. Native cloud-agent `file_read` also requires this exact confirmation before local content can leave the machine; direct local read-only API use remains Level 0.

### `POST /api/actions/confirm`

```json
{"confirmation_token": "...", "session_id": "frontend_tools"}
```

Claims and executes the exact stored action without regenerating that action. For a paused native agent, the backend then resumes the original provider/history with the real confirmed result; the response may contain the next `pending_confirmation`. Tokens expire and cannot be replayed.

## Voice

### `POST /api/speak`

```json
{"text": "Hello", "personality": "ultron"}
```

Text is limited to 4,000 characters. The endpoint preflights the existing Edge TTS provider and streams non-cached `audio/mpeg`. Client disconnect/Stop Voice closes generation; immediate provider/no-audio failure returns HTTP 503 and fake audio is not generated.

## Memory

### `GET /api/memory/recent?limit=5&project_id=personal`

Returns recent project-scoped memories with bounded content preview.

### `GET /api/memory/ui`

Query parameters:

```text
project_id=personal
query=SQLite
category=decision
importance=high
limit=30
```

Returns the safe M4 dashboard read model: project-scoped memory cards, deterministic session summaries, counts, active filters, revision/correction state, timestamps, and content-safe provenance. Exact local search uses the durable recall index; embeddings, provider internals, correction hashes, and unredacted legacy secret-like text are not exposed.

Memory write/list/organize/correct/forget/export/restore/re-embed operations use `manage_memory` through the tool endpoint; correction and forgetting require exact one-time confirmation. JSON export contains only bounded, redacted, restorable public fields. M2 stores a stable category (`explicit`, `owner_preference`, `decision`, `project_fact`, `task`, `goal`, `problem`, `solution`, `session_event`), importance (`low`, `normal`, `high`, `critical`), project/session source, content hash and revision metadata. `organize` returns project-scoped category/importance/type counts.

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
