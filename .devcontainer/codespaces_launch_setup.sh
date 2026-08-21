#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DISPLAY="${DISPLAY:-:1}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/ultron-runtime-$(id -u)}"
export BROWSER="google-chrome --start-maximized --no-first-run --no-default-browser-check --disable-dev-shm-usage %s"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

if pgrep -u "$(id -u)" -f "[b]ackend.app.installer" >/dev/null 2>&1; then
    exit 0
fi

cd "$ROOT"
exec bash "$ROOT/SETUP_ULTRON_UBUNTU.sh"
