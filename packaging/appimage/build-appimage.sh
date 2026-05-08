#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD_DIR="$PROJECT_DIR/dist/appimage-build"
APPDIR="$BUILD_DIR/TailscaleGUI.AppDir"
VERSION="${1:-0.1.0}"

rm -rf "$BUILD_DIR"
mkdir -p \
  "$APPDIR/usr/bin" \
  "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
  "$APPDIR/opt/tailscale-gui"

cp "$PROJECT_DIR/app.py" "$APPDIR/opt/tailscale-gui/app.py"
cp -r "$PROJECT_DIR/assets" "$APPDIR/opt/tailscale-gui/assets"
cp "$PROJECT_DIR/desktop/tailscale-gui.desktop" "$APPDIR/usr/share/applications/tailscale-gui.desktop"
cp "$PROJECT_DIR/assets/icons/logo.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/tailscale-gui.svg"

cat >"$APPDIR/usr/bin/tailscale-gui" <<'EOF'
#!/usr/bin/env bash
SELF_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "$SELF_DIR/opt/tailscale-gui/app.py" "$@"
EOF
chmod +x "$APPDIR/usr/bin/tailscale-gui"

cat >"$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SELF_DIR/usr/bin/tailscale-gui" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cp "$PROJECT_DIR/assets/icons/logo.svg" "$APPDIR/.DirIcon"
cp "$PROJECT_DIR/desktop/tailscale-gui.desktop" "$APPDIR/tailscale-gui.desktop"
ln -sf "usr/share/icons/hicolor/scalable/apps/tailscale-gui.svg" "$APPDIR/tailscale-gui.svg"

APPIMAGETOOL="$BUILD_DIR/appimagetool"
if ! command -v appimagetool >/dev/null 2>&1; then
  curl -L "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -o "$APPIMAGETOOL"
  chmod +x "$APPIMAGETOOL"
else
  APPIMAGETOOL="$(command -v appimagetool)"
fi

OUT_PATH="$PROJECT_DIR/dist/TailscaleGUI-${VERSION}-x86_64.AppImage"
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$OUT_PATH"

echo "Built: $OUT_PATH"
echo "Note: This AppImage expects python3, python3-tk, and tailscale on the host system."
