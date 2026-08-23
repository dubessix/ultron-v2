# WebSocket Channels

Ultron keeps four local channels:

- `/ws/chat` — canonical chat request/response transport.
- `/ws/events` — real orchestrator/personality/tool events.
- `/ws/logs` — operational log broadcasts.
- `/ws/dashboard` — push-on-change dashboard data.

`/ws/chat` uses the same canonical service as `POST /api/chat`, including session/project persistence, memory, tools, personality, provider route, and exact confirmation. Current providers finish a response before the WebSocket sends it. The channel therefore emits real progress, then one exact completed-content frame, events/widgets, and `done`; it does not fake model token streaming with timed word delays.

The frontend may fall back to REST only when the WebSocket request was never sent. Once sent, failures are surfaced without replay, preventing duplicate tool or chat side effects.
