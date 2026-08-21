# WebSocket Contract

Base: `ws://127.0.0.1:8000`

## `/ws/chat`

Client message:

```json
{
  "content": "List my tasks",
  "session_id": "optional",
  "project_id": "personal",
  "has_confirmed": false,
  "confirmation_token": null
}
```

Server sequence:

1. `progress`
2. `stream_start`
3. zero or more `token`
4. `stream_end`
5. optional `widget` and broadcast events
6. `done`

`done` contains message/session/project IDs, effective personality, latency, coding/intent, structured action, provider route, events, and optional pending confirmation.

During database maintenance the server emits an `error` with `status: database_maintenance` and disconnects cleanly.

## `/ws/events`

Server-initiated reminder, personality, daily-briefing, emergency, and operational events. Clients keep the connection alive with text ping messages.

## `/ws/logs`

Reserved for live operational log subscribers. Terminal/tool results remain subject to path/confirmation/security boundaries.

## `/ws/dashboard`

Pushes reported process RAM, CPU, and total RAM changes at bounded intervals.

## Voice

There is no duplex voice WebSocket. Browser recognition uses the Web Speech API. TTS uses `POST /api/speak`, and browser playback handles interruption locally.

## Transport notes

- The launcher binds the backend to `127.0.0.1`.
- The shared orchestrator is not closed on individual WebSocket disconnects.
- Message/action confirmation tokens must not be logged in full or reused.
