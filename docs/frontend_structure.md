# Frontend Structure

```text
frontend/
├── index.html
├── package.json / package-lock.json
├── vite.config.js                 loopback-only dev/preview
└── src/
    ├── main.jsx
    ├── App.jsx                    health/session/chat/voice coordination
    ├── api.js                     REST/tool/confirmation helper
    ├── index.css
    ├── hooks/
    │   ├── useDraggable.js
    │   └── useVoice.js
    └── components/
        ├── AppShell.jsx
        ├── BlobCanvas.jsx
        ├── LeftPanel.jsx          reported telemetry/unavailable states
        ├── RightPanel.jsx         chat and operational logs
        ├── NotificationToast.jsx
        └── widgets/               lazy real-data tools and explicit failures
```

`WidgetManager.js` is the registry for widget titles, dimensions, and lazy components. The backend `structured_action` is the authority for automatic widget opening.

Daily operation does not run the Vite development server. `launcher.py` fingerprints source and lockfile, uses `npm ci` and `npm run build` only when needed, then serves `dist` through `backend.app.static_server` on loopback.

Frontend backend state comes from `/api/health`. Widgets must display returned data, an empty confirmed result, loading, or unavailable—never sample records as fallback.
