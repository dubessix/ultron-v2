#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=============================================="
echo "  ULTRON PERSONAL V1 - UBUNTU SETUP"
echo "=============================================="

missing=()
command -v python3 >/dev/null 2>&1 || missing+=(python3)
python3 -c 'import venv' >/dev/null 2>&1 || missing+=(python3-venv)
python3 -c 'import tkinter' >/dev/null 2>&1 || missing+=(python3-tk)
command -v git >/dev/null 2>&1 || missing+=(git)

if [ "${#missing[@]}" -gt 0 ]; then
    echo "Installing required Ubuntu packages: ${missing[*]}"
    if command -v pkexec >/dev/null 2>&1; then
        pkexec apt-get update
        pkexec apt-get install -y "${missing[@]}"
    else
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
    fi
fi

echo "Opening the Ultron setup window..."
exec python3 -m backend.app.installer
