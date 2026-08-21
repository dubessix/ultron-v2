# Cross-Platform Launch Guide

## Supported software baseline

- Python 3.10+
- Node 20.19+ or 22.12+
- npm and Git
- Windows 11 or a current Linux desktop is intended; final device-specific verification is still required

## Install

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python -m backend.app.cli setup
python -m backend.app.cli doctor
```

Activate the virtual environment using the platform-specific command before running the Python module, or install the wheel to get `ultron`.

## Launch

```bash
ultron start
```

Source alternative:

```bash
python launcher.py
```

The launcher binds only to `127.0.0.1`, checks ports, prepares a fingerprinted production frontend, starts both child process groups, validates `/api/health` and `/healthz`, then dispatches the browser. It monitors both children until shutdown.

## Stop

Press `Ctrl+C`. If a graceful wait expires, the launcher force-stops the process tree and verifies exit. On Windows it uses a new process group and `taskkill /T` as the fallback; this path requires acceptance on the owner's Windows machine.

## Common failures

- Unsupported Node: install Node 20.19+ or 22.12+.
- Port occupied: close the existing Ultron launcher; duplicate instances are blocked.
- Build failure: run `npm ci` and `npm run build` inside `frontend` and inspect the first error.
- Backend health failure: run `ultron doctor`, validate config, and inspect FastAPI logs.
- Browser not opened: manually visit `http://127.0.0.1:5173` after both health checks pass.
- Provider offline: configure `.env` and inspect `/api/providers/status`.

Do not bind the application to LAN/public interfaces for routine personal use.
