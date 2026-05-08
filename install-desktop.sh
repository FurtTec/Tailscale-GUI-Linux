#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

if command -v pip3 >/dev/null 2>&1; then
  if ! pip3 install --user -r "$PROJECT_DIR/requirements.txt"; then
    echo "Could not install Python tray dependencies with pip --user."
    echo "If needed, install them manually with your distro packages or a virtual environment."
  fi
else
  echo "pip3 not found. Install pystray and Pillow manually for tray support."
fi

cat >"$BIN_DIR/tailscale-gui" <<EOF
#!/usr/bin/env bash
exec python3 "$PROJECT_DIR/app.py" "\$@"
EOF
chmod +x "$BIN_DIR/tailscale-gui"

install -m 644 "$PROJECT_DIR/assets/icons/logo.svg" "$ICON_DIR/tailscale-gui.svg"

cat >"$APP_DIR/tailscale-gui.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Tailscale GUI
Comment=Desktop GUI for Tailscale CLI
Exec=$BIN_DIR/tailscale-gui
Icon=tailscale-gui
Terminal=false
Categories=Network;Utility;
Keywords=tailscale;vpn;network;
StartupNotify=true
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" || true
fi

echo "Installed launcher at: $APP_DIR/tailscale-gui.desktop"
echo "If it does not appear immediately, log out/in or refresh your app menu."
