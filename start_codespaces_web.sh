#!/usr/bin/env bash
# GitHub Codespaces Web Mode only. This is never called by local Windows/Linux
# launchers. It owns both child processes so Ctrl+C cannot leave port 8000 or
# 5173 running in the background.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]]; then wait "$pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT INT TERM

cd "$ROOT"

if [[ ! -x "$PYTHON" ]]; then
  echo "Codespaces setup: creating Python environment..."
  python3 -m venv "$ROOT/.venv"
  "$PYTHON" -m pip install --upgrade pip setuptools wheel
  "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
  "$PYTHON" -m backend.app.cli setup
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "Codespaces setup: installing frontend packages..."
  (cd "$ROOT/frontend" && npm ci --no-audit --no-fund)
fi

export ULTRON_HOME="$ROOT"
export ULTRON_CODESPACES_WEB=1
# A relative base keeps browser API/WS traffic on the one forwarded Vite origin.
export VITE_API_URL=.

echo "Starting internal Ultron backend on port 8000..."
"$PYTHON" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "Starting direct browser frontend on forwarded port 5173..."
(
  cd "$ROOT/frontend"
  npm run dev -- --host 0.0.0.0 --port 5173
) &
FRONTEND_PID=$!

echo
echo "Ultron Codespaces Web Mode is ready."
echo "Open forwarded port 5173 in your normal Chrome or Edge browser."
echo "Press Ctrl+C once to stop both frontend and backend."

wait -n "$BACKEND_PID" "$FRONTEND_PID"
status=$?
echo "One Codespaces web service stopped (exit $status); stopping the other service."
exit "$status"
