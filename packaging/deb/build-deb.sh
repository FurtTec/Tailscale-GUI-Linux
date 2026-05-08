#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD_DIR="$PROJECT_DIR/dist/deb-build"
PKG_DIR="$BUILD_DIR/tailscale-gui"
VERSION="${1:-0.1.0}"
ARCH="${2:-amd64}"

rm -rf "$BUILD_DIR"
mkdir -p \
  "$PKG_DIR/DEBIAN" \
  "$PKG_DIR/opt/tailscale-gui" \
  "$PKG_DIR/usr/bin" \
  "$PKG_DIR/usr/share/applications" \
  "$PKG_DIR/usr/share/icons/hicolor/scalable/apps"

cp "$PROJECT_DIR/app.py" "$PKG_DIR/opt/tailscale-gui/app.py"
cp -r "$PROJECT_DIR/assets" "$PKG_DIR/opt/tailscale-gui/assets"

cat >"$PKG_DIR/usr/bin/tailscale-gui" <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/tailscale-gui/app.py "$@"
EOF
chmod +x "$PKG_DIR/usr/bin/tailscale-gui"

install -m 644 "$PROJECT_DIR/desktop/tailscale-gui.desktop" "$PKG_DIR/usr/share/applications/tailscale-gui.desktop"
install -m 644 "$PROJECT_DIR/assets/icons/logo.svg" "$PKG_DIR/usr/share/icons/hicolor/scalable/apps/tailscale-gui.svg"

cat >"$PKG_DIR/DEBIAN/control" <<EOF
Package: tailscale-gui
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Maintainer: Tailscale GUI Packager <packager@example.com>
Depends: python3, python3-tk, tailscale
Recommends: python3-pil, python3-pystray, python3-gi, gir1.2-ayatanaappindicator3-0.1
Description: Desktop GUI for Tailscale on Linux
 A lightweight desktop app to run common Tailscale commands,
 manage exit nodes, and view tailnet peers.
EOF

DEB_PATH="$PROJECT_DIR/dist/tailscale-gui_${VERSION}_${ARCH}.deb"
mkdir -p "$PROJECT_DIR/dist"
dpkg-deb --build "$PKG_DIR" "$DEB_PATH"

echo "Built: $DEB_PATH"
