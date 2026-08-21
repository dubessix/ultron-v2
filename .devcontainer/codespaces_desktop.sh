#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DISPLAY="${DISPLAY:-:1}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/ultron-runtime-$(id -u)}"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

# desktop-lite starts noVNC/X asynchronously. Wait for the real display instead
# of pretending the setup window opened before it is reachable.
ready=0
for _ in $(seq 1 90); do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done
if [ "$ready" -ne 1 ]; then
    echo "Ultron setup was not opened: Codespaces desktop display did not become ready."
    exit 1
fi

if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    eval "$(dbus-launch --sh-syntax)"
    export DBUS_SESSION_BUS_ADDRESS DBUS_SESSION_BUS_PID
fi

if ! pgrep -u "$(id -u)" -f "[p]cmanfm --desktop" >/dev/null 2>&1; then
    pcmanfm --desktop --profile=ultron-codespaces >/tmp/ultron-pcmanfm.log 2>&1 &
fi

xdg-mime default google-chrome.desktop x-scheme-handler/http >/dev/null 2>&1 || true
xdg-mime default google-chrome.desktop x-scheme-handler/https >/dev/null 2>&1 || true
if command -v gio >/dev/null 2>&1; then
    gio set "$HOME/Desktop/1 — Setup Ultron.desktop" metadata::trusted true >/dev/null 2>&1 || true
fi

sleep 2
exec "$ROOT/.devcontainer/codespaces_launch_setup.sh"
