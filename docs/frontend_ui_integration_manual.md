# Frontend Integration Manual

## Backend base

The production build receives `VITE_API_URL=http://127.0.0.1:<configured-backend-port>` from the launcher. Source defaults use port 8000.

`src/api.js` provides:

- `api(path, options)` — JSON requests with non-2xx errors surfaced;
- `executeTool(toolId, args, options)`;
- `executeToolWithConfirmation(...)` — obtains and returns the exact token for the same call.

## Chat

`App.jsx` prefers `/ws/chat` for token streaming and reconciles the resolved session, project, personality, events, provider route, structured action, and pending confirmation. REST `/api/chat` is used by voice-command submission.

## Health

The UI polls `/api/health` every five seconds. When health fails, backend status becomes disconnected/error and stale system metrics are cleared. “Connected” is never displayed from a static default.

## Voice

`useVoice` owns browser Web Speech recognition. Mic ON first waits for `Ultron`/`Hey Ultron`; that one wake unlocks direct follow-up turns until Stop Voice. Final/interim results are index-safe, the latest session callback is used, and one synchronous in-flight guard prevents overlapping REST turns. Recognition aborts during processing/TTS, ignores buffered late results, and resumes after actual playback end/error/stop. Unexpected browser ends use one bounded restart timer (500 ms base, 4 s cap, five attempts). `POST /api/speak` provides audio, and exact confirmation tokens remain backend-issued and unchanged. Automated fake-recognizer/browser checks verify state wiring, not real microphone accuracy or audible acceptance.

## Widgets

Widgets use backend tool/REST results. Important rules:

- no sample rows or fabricated sensor/network values;
- loading, confirmed empty, and unavailable are distinct;
- Level 2/3 widgets use exact confirmation;
- personality selection is persisted through `/api/personality` before the display changes;
- destructive actions refresh from backend only after verified success.

The M4 Memory Console remains a draggable/collapsible centre overlay. It reads `/api/memory/ui`, provides project/category/importance filters and local exact search, shows important memories beside session summaries, labels provenance/revision/timestamps, downloads a redacted JSON export, and sends correction/forget calls through the exact one-time confirmation flow.

## Build

```bash
cd frontend
npm ci
npm run test:voice
npm audit --audit-level=low
npm run build
```

Vite dev and preview bind only to `127.0.0.1`. The production launcher serves built assets with `/healthz` and SPA fallback.
