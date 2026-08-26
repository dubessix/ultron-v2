#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

chmod +x "$ROOT/start_codespaces_web.sh" "$ROOT/start_ultron.sh" "$ROOT/SETUP_ULTRON_UBUNTU.sh"

printf '%s\n' \
  "Ultron Codespaces Web Mode prepared." \
  "Run: ./start_codespaces_web.sh" \
  "Then open forwarded port 5173 in your normal browser." \
  "No desktop, VNC, or noVNC service is started."
