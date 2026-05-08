#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$AUTOSTART_DIR"

if [[ ! -x "$BIN_DIR/tailscale-gui" ]]; then
  echo "Launcher not found at $BIN_DIR/tailscale-gui"
  echo "Run ./install-desktop.sh first."
  exit 1
fi

cat >"$AUTOSTART_DIR/tailscale-gui-applet.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Tailscale GUI Applet
Comment=Start Tailscale GUI in tray mode
Exec=$BIN_DIR/tailscale-gui --tray
Icon=tailscale-gui
Terminal=false
Categories=Network;Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
EOF

echo "Autostart applet installed: $AUTOSTART_DIR/tailscale-gui-applet.desktop"
echo "It will start in tray mode on next login."
