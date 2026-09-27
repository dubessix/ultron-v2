#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=============================================="
echo "  ULTRON V2 - UBUNTU SETUP"
echo "=============================================="

missing=()
command -v python3 >/dev/null 2>&1 || missing+=(python3)
# Ubuntu ships the venv module without pip (python3-venv adds it), so test for real.
venv_probe="$(mktemp -d)"
python3 -m venv "$venv_probe/probe" >/dev/null 2>&1 || missing+=(python3-venv)
rm -rf "$venv_probe"
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
