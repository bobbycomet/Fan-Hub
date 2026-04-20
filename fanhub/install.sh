#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Fan Hub Installer / Updater — Ubuntu/Debian
# ─────────────────────────────────────────────────────────────────────────────

set -e

FANHUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="/opt/fanhub"
BIN_LINK="/usr/local/bin/fanhub"
DESKTOP_FILE="/usr/share/applications/fanhub.desktop"
UDEV_RULES="/etc/udev/rules.d/99-fanhub.rules"
ICON_SRC="$FANHUB_DIR/assets/icon.png"
VERSION_FILE="$INSTALL_PREFIX/VERSION"
CURRENT_VERSION="1.5.2"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[FanHub]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
err()  { echo -e "${RED}[ERROR ]${NC} $*"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    err "Please run as root: sudo ./install.sh"
fi

ACTUAL_USER="${SUDO_USER:-$USER}"
log "Fan Hub installer v${CURRENT_VERSION} — user: $ACTUAL_USER"

# ── Detect existing installation ──────────────────────────────────────────────
IS_UPDATE=false
PREV_VERSION="(none)"
if [ -d "$INSTALL_PREFIX" ] && [ -f "$VERSION_FILE" ]; then
    PREV_VERSION="$(cat "$VERSION_FILE" 2>/dev/null || echo 'unknown')"
    IS_UPDATE=true
    log "Existing installation found: v${PREV_VERSION} → upgrading to v${CURRENT_VERSION}"
elif [ -d "$INSTALL_PREFIX" ]; then
    IS_UPDATE=true
    PREV_VERSION="unknown"
    log "Existing installation found (no version file) → upgrading to v${CURRENT_VERSION}"
else
    log "Fresh installation of v${CURRENT_VERSION}"
fi

# ── Stop running instance if updating ────────────────────────────────────────
if [ "$IS_UPDATE" = true ]; then
    log "Stopping any running Fan Hub instance…"
    pkill -f "fanhub/main.py" 2>/dev/null && sleep 1 || true
    pkill -f "fanhub/venv/bin/python3.*main.py" 2>/dev/null && sleep 1 || true

    # Stop OpenRGB service if managed by us
    systemctl stop openrgb-server.service 2>/dev/null || true

    # Backup user config (never overwrite it)
    CONFIG_DIR_USR="/home/$ACTUAL_USER/.config/fanhub"
    if [ -d "$CONFIG_DIR_USR" ]; then
        log "User config preserved at $CONFIG_DIR_USR"
    fi
fi

# ── System dependencies ───────────────────────────────────────────────────────
log "Installing system dependencies…"
apt-get update -qq
apt-get install -y \
    python3 python3-pip python3-venv \
    python3-pyqt6 python3-pyqt6.qtcharts \
    libhidapi-hidraw0 libhidapi-libusb0 \
    i2c-tools lm-sensors usbutils wget curl 2>/dev/null || \
apt-get install -y \
    python3 python3-pip python3-venv \
    libhidapi-hidraw0 libhidapi-libusb0 \
    i2c-tools lm-sensors usbutils wget curl
ok "System dependencies installed"

# ── lm-sensors detect ─────────────────────────────────────────────────────────
log "Detecting sensors…"
yes "" | sensors-detect --auto 2>/dev/null || true
ok "Sensor detection complete"

# ── Python venv ───────────────────────────────────────────────────────────────
log "Setting up Python environment at $INSTALL_PREFIX…"
mkdir -p "$INSTALL_PREFIX"

# BUG FIX: on update, recreate venv to pick up any new Python version
if [ "$IS_UPDATE" = true ] && [ -d "$INSTALL_PREFIX/venv" ]; then
    log "Refreshing Python virtual environment…"
    rm -rf "$INSTALL_PREFIX/venv"
fi

python3 -m venv "$INSTALL_PREFIX/venv" --system-site-packages

log "Installing Python packages…"
"$INSTALL_PREFIX/venv/bin/pip" install --upgrade pip -q
"$INSTALL_PREFIX/venv/bin/pip" install \
    PyQt6 PyQt6-Charts \
    liquidctl \
    openrgb-python \
    psutil pyserial Pillow -q || warn "Some optional packages failed"
ok "Python environment ready"

# ── Copy application files ────────────────────────────────────────────────────
log "Copying application files…"

# BUG FIX: on update, remove old Python files first to avoid stale .pyc caches
if [ "$IS_UPDATE" = true ]; then
    find "$INSTALL_PREFIX" -name "*.py" -not -path "*/venv/*" -delete 2>/dev/null || true
    find "$INSTALL_PREFIX" -name "*.pyc" -delete 2>/dev/null || true
    find "$INSTALL_PREFIX" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
fi

# Copy all files preserving directory structure
cp -r "$FANHUB_DIR"/. "$INSTALL_PREFIX/"
chmod +x "$INSTALL_PREFIX/main.py"

# Write version file
echo "$CURRENT_VERSION" > "$VERSION_FILE"

# Generate icon sizes if Pillow is available
"$INSTALL_PREFIX/venv/bin/python3" -c "
from PIL import Image
import os
src = '$INSTALL_PREFIX/assets/icon.png'
if os.path.exists(src):
    img = Image.open(src)
    for size in [16, 32, 48, 64, 128, 256]:
        img.resize((size, size), Image.LANCZOS).save(f'$INSTALL_PREFIX/assets/icon_{size}.png')
    print('Icon sizes generated')
" 2>/dev/null || warn "Could not generate icon sizes (Pillow missing)"

ok "Files installed to $INSTALL_PREFIX"

# ── Install icons into system icon theme ──────────────────────────────────────
log "Installing icons…"
if [ -f "$ICON_SRC" ]; then
    for SIZE in 16 32 48 64 128 256; do
        ICON_DIR="/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps"
        mkdir -p "$ICON_DIR"
        SRC_SIZED="$INSTALL_PREFIX/assets/icon_${SIZE}.png"
        if [ -f "$SRC_SIZED" ]; then
            cp "$SRC_SIZED" "$ICON_DIR/fanhub.png"
        else
            cp "$ICON_SRC" "$ICON_DIR/fanhub.png"
        fi
    done
    # Also put in pixmaps
    cp "$ICON_SRC" /usr/share/pixmaps/fanhub.png
    gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
    ok "Icons installed"
else
    warn "Icon file not found at $ICON_SRC — skipping icon install"
fi

# ── Wrapper script ────────────────────────────────────────────────────────────
log "Creating launchers…"

# ── Main launcher (tries pkexec first, falls back to direct run) ──────────
cat > "$BIN_LINK" << 'LAUNCHER'
#!/bin/bash
FANHUB_HOME="/opt/fanhub"
export PYTHONPATH="$FANHUB_HOME"
# If running as root already (sudo fanhub), just launch directly
if [ "$EUID" -eq 0 ]; then
    exec "$FANHUB_HOME/venv/bin/python3" "$FANHUB_HOME/main.py" "$@"
fi
# Try pkexec (GUI password prompt, no terminal needed)
if command -v pkexec >/dev/null 2>&1; then
    exec pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" \
        WAYLAND_DISPLAY="$WAYLAND_DISPLAY" XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
        PYTHONPATH="$FANHUB_HOME" \
        "$FANHUB_HOME/venv/bin/python3" "$FANHUB_HOME/main.py" "$@"
fi
# Last resort: direct (will fail if no hwmon write perms; user sees the error)
exec "$FANHUB_HOME/venv/bin/python3" "$FANHUB_HOME/main.py" "$@"
LAUNCHER
chmod +x "$BIN_LINK"

# ── sudo wrapper for terminal users ────────────────────────────────────────
SUDO_LINK="/usr/local/bin/fanhub-sudo"
cat > "$SUDO_LINK" << 'SUDOEOF'
#!/bin/bash
exec sudo /usr/local/bin/fanhub "$@"
SUDOEOF
chmod +x "$SUDO_LINK"

# ── pkexec policy file ─────────────────────────────────────────────────────
POLICY_DIR="/usr/share/polkit-1/actions"
if [ -d "$POLICY_DIR" ] && [ -f "$INSTALL_PREFIX/assets/org.fanhub.policy" ]; then
    cp "$INSTALL_PREFIX/assets/org.fanhub.policy" "$POLICY_DIR/"
    ok "polkit policy installed"
else
    warn "polkit policy directory not found — pkexec may prompt for password"
fi

ok "Launchers created: fanhub (pkexec), fanhub-sudo (sudo)"

# ── udev rules ────────────────────────────────────────────────────────────────
log "Installing udev rules…"
cat > "$UDEV_RULES" << 'UDEV'
# Fan Hub — hwmon write access
KERNEL=="hwmon*", SUBSYSTEM=="hwmon", ACTION=="add", RUN+="/bin/chmod -R a+w /sys%p"
# i2c access
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
# Corsair
SUBSYSTEMS=="usb", ATTRS{idVendor}=="1b1c", TAG+="uaccess"
# NZXT
SUBSYSTEMS=="usb", ATTRS{idVendor}=="2433", TAG+="uaccess"
# Cooler Master
SUBSYSTEMS=="usb", ATTRS{idVendor}=="2516", TAG+="uaccess"
# EVGA
SUBSYSTEMS=="usb", ATTRS{idVendor}=="3842", TAG+="uaccess"
# Thermaltake
SUBSYSTEMS=="usb", ATTRS{idVendor}=="264a", TAG+="uaccess"
# Aqua Computer
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0c70", TAG+="uaccess"
# MSI / ASUS
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0db0", TAG+="uaccess"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0b05", TAG+="uaccess"
# Generic HID
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", TAG+="uaccess"
UDEV
udevadm control --reload-rules && udevadm trigger
ok "udev rules installed"

# ── Groups ────────────────────────────────────────────────────────────────────
log "Configuring user groups…"
groupadd -f i2c 2>/dev/null || true
groupadd -f plugdev 2>/dev/null || true
usermod -aG i2c,plugdev "$ACTUAL_USER" 2>/dev/null || true
ok "Groups configured"

# ── Kernel modules ────────────────────────────────────────────────────────────
log "Loading kernel modules…"
for mod in i2c-dev coretemp it87 nct6775 w83795; do
    modprobe "$mod" 2>/dev/null && ok "  Loaded: $mod" || true
done
cat > /etc/modules-load.d/fanhub.conf << 'MODS'
i2c-dev
coretemp
it87
nct6775
MODS
ok "Kernel modules configured"

# ── OpenRGB server systemd service ────────────────────────────────────────────
OPENRGB_BIN="$(which openrgb 2>/dev/null || echo '')"
if [ -n "$OPENRGB_BIN" ]; then
    log "Setting up OpenRGB server service…"
    cat > /etc/systemd/system/openrgb-server.service << SVCEOF
[Unit]
Description=OpenRGB SDK Server
After=network.target

[Service]
Type=simple
User=$ACTUAL_USER
ExecStart=$OPENRGB_BIN --server --server-port 6742
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF
    systemctl daemon-reload
    systemctl enable openrgb-server.service
    systemctl start openrgb-server.service 2>/dev/null || warn "OpenRGB server failed to start"
    ok "OpenRGB server service installed"
fi

# ── Desktop entry ─────────────────────────────────────────────────────────────
log "Creating desktop entry…"
cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Fan Hub
GenericName=Fan Controller
Comment=Comprehensive Linux Fan & RGB Control
Exec=/usr/local/bin/fanhub %U
Icon=fanhub
Terminal=false
Categories=System;HardwareSettings;
Keywords=fan;cpu;temperature;cooling;rgb;pwm;
StartupNotify=true
StartupWMClass=fanhub
X-Ubuntu-Gettext-Domain=fanhub
DESKTOP
update-desktop-database /usr/share/applications/ 2>/dev/null || true
ok "Desktop entry created"

# ── Config directory ──────────────────────────────────────────────────────────
CONFIG_DIR="/home/$ACTUAL_USER/.config/fanhub"
mkdir -p "$CONFIG_DIR/profiles"
chown -R "$ACTUAL_USER:$ACTUAL_USER" "$CONFIG_DIR"
ok "Config directory: $CONFIG_DIR"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [ "$IS_UPDATE" = true ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   Fan Hub updated: v${PREV_VERSION} → v${CURRENT_VERSION}  ✓         ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
else
    echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   Fan Hub v${CURRENT_VERSION} installed successfully! 🌀  ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
fi
echo ""
echo -e "  Run:          ${CYAN}fanhub${NC}  (or find it in your app menu)"
echo -e "  Run as root:  ${CYAN}sudo fanhub${NC}  (for full fan control)"
echo -e "  Logs:         ${CYAN}~/.config/fanhub/fanhub.log${NC}"
echo -e "  Version:      ${CYAN}${CURRENT_VERSION}${NC}"
echo ""
echo -e "${YELLOW}NOTE: Log out and back in for group changes to take effect.${NC}"
echo -e "${YELLOW}      Until then, run with: sudo fanhub${NC}"
echo ""
if [ -z "$OPENRGB_BIN" ]; then
    echo -e "${YELLOW}RGB TIP: Install OpenRGB from https://openrgb.org${NC}"
    echo -e "  Then run: openrgb --server &"
    echo ""
fi
