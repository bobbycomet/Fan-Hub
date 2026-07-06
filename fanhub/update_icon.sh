#!/bin/bash
# Quick icon update — run after extracting new fanhub tarball
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="/opt/fanhub"

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo ./update_icon.sh"
    exit 1
fi

echo "Updating icons..."
cp "$SCRIPT_DIR/assets/icon.png"     "$INSTALL_PREFIX/assets/icon.png"
cp "$SCRIPT_DIR/assets/icon_16.png"  "$INSTALL_PREFIX/assets/icon_16.png"
cp "$SCRIPT_DIR/assets/icon_32.png"  "$INSTALL_PREFIX/assets/icon_32.png"
cp "$SCRIPT_DIR/assets/icon_48.png"  "$INSTALL_PREFIX/assets/icon_48.png"
cp "$SCRIPT_DIR/assets/icon_64.png"  "$INSTALL_PREFIX/assets/icon_64.png"
cp "$SCRIPT_DIR/assets/icon_128.png" "$INSTALL_PREFIX/assets/icon_128.png"
cp "$SCRIPT_DIR/assets/icon_256.png" "$INSTALL_PREFIX/assets/icon_256.png"

# Install into system icon theme
for SIZE in 16 32 48 64 128 256; do
    ICON_DIR="/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps"
    mkdir -p "$ICON_DIR"
    cp "$INSTALL_PREFIX/assets/icon_${SIZE}.png" "$ICON_DIR/fanhub.png"
done
cp "$INSTALL_PREFIX/assets/icon.png" /usr/share/pixmaps/fanhub.png

# Refresh icon cache
gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
update-desktop-database /usr/share/applications/ 2>/dev/null || true

echo "Icons updated. You may need to log out and back in for desktop changes."
