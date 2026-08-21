#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP="$HOME/Desktop"
APPLICATIONS="$HOME/.local/share/applications"
mkdir -p "$DESKTOP" "$APPLICATIONS"
chmod +x "$ROOT/SETUP_ULTRON_UBUNTU.sh" "$ROOT/start_ultron.sh" \
  "$ROOT/.devcontainer/codespaces_desktop.sh" "$ROOT/.devcontainer/codespaces_launch_setup.sh"

cat > "$APPLICATIONS/ultron-codespaces-setup.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=1 — Setup Ultron
Comment=Run the real Ubuntu Ultron setup wrapper
Exec=$ROOT/.devcontainer/codespaces_launch_setup.sh
Path=$ROOT
Terminal=false
Icon=$ROOT/images/ultron_icon.png
Categories=Development;Utility;
EOF
chmod +x "$APPLICATIONS/ultron-codespaces-setup.desktop"
cp "$APPLICATIONS/ultron-codespaces-setup.desktop" "$DESKTOP/1 — Setup Ultron.desktop"
chmod +x "$DESKTOP/1 — Setup Ultron.desktop"

printf '%s\n' \
  "Ultron Codespaces desktop prepared." \
  "No API key or GitHub token was copied into the demo." \
  "Open forwarded port 6080, connect with password 'vscode', then use the Setup window."
