#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/python" ]; then
    echo "Ultron is not installed yet. Opening setup..."
    exec "$ROOT/SETUP_ULTRON_UBUNTU.sh"
fi

mkdir -p "$ROOT/data/logs"
export ULTRON_HOME="$ROOT"
export ULTRON_LAUNCH_LOG="$ROOT/data/logs/launcher-ui.log"
if [ -t 1 ]; then clear; fi

"$ROOT/.venv/bin/python" -m backend.app.cli start
code=$?
if [ "$code" -ne 0 ]; then
    printf '\nULTRON START FAILED\nReview the error above or run Ultron Doctor.\nLog: %s\n' "$ULTRON_LAUNCH_LOG"
    if [ -t 0 ]; then read -r -p "Press Enter to close..." _; fi
fi
exit "$code"
