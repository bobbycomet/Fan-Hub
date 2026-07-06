#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Fan Hub — AppImage builder                                          v1.5.5
#
# Produces FanHub-1.5.5-x86_64.AppImage in the current directory.
#
# Requirements on the build machine:
#   python3.10+, rsync, curl
#
# Usage:
#   chmod +x build_appimage.sh
#   ./build_appimage.sh            (does NOT need sudo)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="FanHub"
APP_VERSION="1.5.5"
BUILD_DIR="$SCRIPT_DIR/.appimage_build"
APPDIR="$BUILD_DIR/AppDir"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${BLUE}[build]${NC} $*"; }
ok()   { echo -e "${GREEN}[  ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ── Preflight ─────────────────────────────────────────────────────────────────
log "Fan Hub ${APP_VERSION} — AppImage build"
command -v python3 >/dev/null 2>&1 || err "python3 not found"
command -v rsync   >/dev/null 2>&1 || err "rsync not found (apt install rsync)"
command -v curl    >/dev/null 2>&1 || err "curl not found"

PYTHON="$(command -v python3)"
log "Using Python: $PYTHON  ($(python3 --version))"

# ── Get appimagetool ──────────────────────────────────────────────────────────
APPIMAGETOOL="$BUILD_DIR/appimagetool"
mkdir -p "$BUILD_DIR"
if [ ! -x "$APPIMAGETOOL" ]; then
    log "Downloading appimagetool…"
    curl -Lo "$APPIMAGETOOL" \
        "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
    ok "appimagetool ready"
fi

# ── Create AppDir skeleton ────────────────────────────────────────────────────
log "Creating AppDir…"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/lib"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APPDIR/usr/share/icons/hicolor/512x512/apps"

# ── Create Python venv WITH pip (not --without-pip) ──────────────────────────
VENV="$APPDIR/usr/python"
log "Creating Python venv (with copies, not symlinks)…"

# --copies: all binaries are real files, not symlinks.
# Symlinks break when the AppImage is run from a different path.
python3 -m venv --copies "$VENV"

# python3 -m venv normally installs pip; verify it's there
if [ ! -f "$VENV/bin/pip3" ] && [ ! -f "$VENV/bin/pip" ]; then
    log "pip missing from venv — running ensurepip…"
    "$VENV/bin/python3" -m ensurepip --upgrade
fi

# Always use 'python3 -m pip' rather than the pip binary to avoid path issues
VPYTHON="$VENV/bin/python3"

log "Upgrading pip…"
"$VPYTHON" -m pip install --quiet --upgrade pip

log "Installing Fan Hub dependencies…"
"$VPYTHON" -m pip install --quiet \
    PyQt6 \
    PyQt6-Qt6 \
    PyQt6-sip \
    PyQt6-Charts \
    liquidctl \
    openrgb-python \
    psutil

ok "Python + dependencies installed into AppDir"

# ── Detect real Python version in venv ───────────────────────────────────────
# e.g. "3.11" — needed for LD_LIBRARY_PATH in AppRun
PYVER="$("$VPYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
log "Venv Python version: $PYVER"

# ── Copy Fan Hub source ───────────────────────────────────────────────────────
log "Copying Fan Hub source…"
APP_SRC="$APPDIR/usr/share/fanhub"
mkdir -p "$APP_SRC"
rsync -a --exclude='.appimage_build' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='.git' --exclude='*.AppImage' \
    "$SCRIPT_DIR/" "$APP_SRC/"

# ── AppRun — entry point ──────────────────────────────────────────────────────
log "Writing AppRun…"
cat > "$APPDIR/AppRun" << APPRUN
#!/bin/bash
# AppRun — Fan Hub AppImage entry point

HERE="\$(dirname "\$(readlink -f "\${0}")")"

# Python inside the AppDir
VPYTHON="\$HERE/usr/python/bin/python3"

# Fan Hub source
APP="\$HERE/usr/share/fanhub/main.py"

# Locate PyQt6 Qt6 plugins bundled in the venv
QT6_DIR="\$(ls -d "\$HERE/usr/python/lib/python${PYVER}/site-packages/PyQt6/Qt6" 2>/dev/null | head -1)"

if [ -n "\$QT6_DIR" ]; then
    export QT_PLUGIN_PATH="\$QT6_DIR/plugins:\${QT_PLUGIN_PATH:-}"
    export QT_QPA_PLATFORM_PLUGIN_PATH="\$QT6_DIR/plugins/platforms:\${QT_QPA_PLATFORM_PLUGIN_PATH:-}"
    export LD_LIBRARY_PATH="\$QT6_DIR/lib:\$HERE/usr/python/lib:\${LD_LIBRARY_PATH:-}"
fi

# Tell Fan Hub it is running inside an AppImage
export FANHUB_APPIMAGE="\${APPIMAGE:-\$0}"
export FANHUB_APPDIR="\$HERE"

exec "\$VPYTHON" "\$APP" "\$@"
APPRUN
chmod +x "$APPDIR/AppRun"
ok "AppRun written (using Python $PYVER)"

# ── Desktop entry ─────────────────────────────────────────────────────────────
cat > "$APPDIR/fanhub.desktop" << DESKTOP
[Desktop Entry]
Name=Fan Hub
Comment=Linux Fan Control and RGB Management
Exec=AppRun
Icon=fanhub
Type=Application
Categories=System;Settings;HardwareSettings;
Keywords=fan;temperature;cooling;rgb;hwmon;
DESKTOP
cp "$APPDIR/fanhub.desktop" "$APPDIR/usr/share/applications/fanhub.desktop"

# ── Icons ─────────────────────────────────────────────────────────────────────
ICON_SRC=""
for candidate in \
    "$SCRIPT_DIR/assets/icon_256.png" \
    "$SCRIPT_DIR/assets/icon.png"; do
    [ -f "$candidate" ] && ICON_SRC="$candidate" && break
done

if [ -n "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APPDIR/fanhub.png"
    cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/fanhub.png"
    ok "Icon set from $ICON_SRC"
else
    warn "No icon found — AppImage will have no icon"
    # appimagetool requires an icon; create a 1px placeholder
    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82' \
        > "$APPDIR/fanhub.png"
fi

# ── Build ─────────────────────────────────────────────────────────────────────
OUTPUT="$SCRIPT_DIR/${APP_NAME}-${APP_VERSION}-x86_64.AppImage"
log "Building AppImage → $OUTPUT"

# appimagetool itself is an AppImage; on systems without FUSE use extract-and-run
export APPIMAGE_EXTRACT_AND_RUN=1

"$APPIMAGETOOL" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"

SIZE="$(du -sh "$OUTPUT" | cut -f1)"
ok "Built: $OUTPUT  ($SIZE)"
echo ""
echo -e "${CYAN}Test with:${NC}  ./${APP_NAME}-${APP_VERSION}-x86_64.AppImage"
echo ""
echo "On first launch Fan Hub detects missing system components"
echo "(udev rules, fanhub group, daemon) and offers to install them"
echo "via pkexec — no terminal required."
