#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Fan Hub — Debian package builder
# Produces fanhub_1.5.5-01_amd64.deb
#
# Usage:
#   chmod +x build_deb.sh
#   ./build_deb.sh            (does NOT need root)
#
# Requirements on the build machine:
#   dpkg-deb, python3, fakeroot
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_NAME="fanhub"
PKG_VERSION="1.6.0"
PKG_ARCH="amd64"
DEB_FILE="${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}.deb"
BUILD_DIR="$SCRIPT_DIR/.deb_build"
PKGROOT="$BUILD_DIR/pkgroot"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log() { echo -e "${CYAN}[deb]${NC} $*"; }
ok()  { echo -e "${GREEN}[ ok ]${NC} $*"; }
err() { echo -e "${RED}[err ]${NC} $*"; exit 1; }

command -v dpkg-deb >/dev/null 2>&1 || err "dpkg-deb not found (apt install dpkg)"
command -v fakeroot >/dev/null 2>&1 || err "fakeroot not found (apt install fakeroot)"
command -v python3  >/dev/null 2>&1 || err "python3 not found"

log "Building ${DEB_FILE}…"
rm -rf "$BUILD_DIR"
PKGROOT="$BUILD_DIR/pkgroot"

# ── Directory structure ───────────────────────────────────────────────────────
log "Creating package directory tree…"
install -d "$PKGROOT/DEBIAN"
install -d "$PKGROOT/opt/fanhub"
install -d "$PKGROOT/usr/local/bin"
install -d "$PKGROOT/usr/share/applications"
install -d "$PKGROOT/usr/share/polkit-1/actions"
install -d "$PKGROOT/usr/share/icons/hicolor/16x16/apps"
install -d "$PKGROOT/usr/share/icons/hicolor/32x32/apps"
install -d "$PKGROOT/usr/share/icons/hicolor/48x48/apps"
install -d "$PKGROOT/usr/share/icons/hicolor/64x64/apps"
install -d "$PKGROOT/usr/share/icons/hicolor/128x128/apps"
install -d "$PKGROOT/usr/share/icons/hicolor/256x256/apps"
install -d "$PKGROOT/usr/share/pixmaps"
install -d "$PKGROOT/etc/udev/rules.d"
install -d "$PKGROOT/etc/modules-load.d"
install -d "$PKGROOT/etc/systemd/system"
install -d "$PKGROOT/usr/share/doc/fanhub"

# ── Copy application source ───────────────────────────────────────────────────
log "Copying application files…"
rsync -a --exclude='.deb_build' --exclude='.appimage_build' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    --exclude='*.AppImage' --exclude='*.deb' \
    "$SCRIPT_DIR/" "$PKGROOT/opt/fanhub/"

# ── Create Python venv inside the package ────────────────────────────────────
log "Creating Python venv at /opt/fanhub/venv…"
python3 -m venv --copies "$PKGROOT/opt/fanhub/venv"
"$PKGROOT/opt/fanhub/venv/bin/python3" -m pip install --quiet --upgrade pip
"$PKGROOT/opt/fanhub/venv/bin/python3" -m pip install --quiet \
    PyQt6 PyQt6-Charts liquidctl openrgb-python psutil pyserial Pillow

# Generate icons with bundled Pillow
"$PKGROOT/opt/fanhub/venv/bin/python3" -c "
from PIL import Image; import os
src = '$PKGROOT/opt/fanhub/assets/icon.png'
if os.path.exists(src):
    img = Image.open(src)
    for size in [16,32,48,64,128,256]:
        img.resize((size,size),Image.LANCZOS).save(
            f'$PKGROOT/opt/fanhub/assets/icon_{size}.png')
    print('icons generated')
" 2>/dev/null || true

ok "Python venv built"

# ── Icons ─────────────────────────────────────────────────────────────────────
log "Installing icons…"
for size in 16 32 48 64 128 256; do
    src="$PKGROOT/opt/fanhub/assets/icon_${size}.png"
    [ -f "$src" ] || src="$PKGROOT/opt/fanhub/assets/icon.png"
    cp "$src" "$PKGROOT/usr/share/icons/hicolor/${size}x${size}/apps/fanhub.png"
done
cp "$PKGROOT/opt/fanhub/assets/icon.png" "$PKGROOT/usr/share/pixmaps/fanhub.png"

# ── polkit policy ─────────────────────────────────────────────────────────────
cp "$PKGROOT/opt/fanhub/assets/org.fanhub.policy" \
   "$PKGROOT/usr/share/polkit-1/actions/"

# ── udev rules ────────────────────────────────────────────────────────────────
log "Writing udev rules…"
cat > "$PKGROOT/etc/udev/rules.d/99-fanhub.rules" << 'UDEV'
# Fan Hub — targeted hwmon PWM access (fanhub group only, not world-writable)
KERNEL=="pwm[0-9]*",        SUBSYSTEM=="hwmon", ACTION=="add", GROUP="fanhub", MODE="0660"
KERNEL=="pwm[0-9]*_enable", SUBSYSTEM=="hwmon", ACTION=="add", GROUP="fanhub", MODE="0660"
KERNEL=="fan[0-9]*_min",    SUBSYSTEM=="hwmon", ACTION=="add", GROUP="fanhub", MODE="0660"
KERNEL=="hwmon[0-9]*", SUBSYSTEM=="hwmon", ACTION=="add", \
    RUN+="/bin/sh -c 'chown root:fanhub /sys%p/pwm* 2>/dev/null; chmod 660 /sys%p/pwm* 2>/dev/null || true'"
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="1b1c", TAG+="uaccess"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="2433", TAG+="uaccess"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="2516", TAG+="uaccess"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="3842", TAG+="uaccess"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="264a", TAG+="uaccess"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0c70", TAG+="uaccess"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0db0", TAG+="uaccess"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0b05", TAG+="uaccess"
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", TAG+="uaccess"
UDEV

# ── kernel modules ────────────────────────────────────────────────────────────
cat > "$PKGROOT/etc/modules-load.d/fanhub.conf" << 'MODS'
i2c-dev
coretemp
it87
nct6775
MODS

# ── systemd service ───────────────────────────────────────────────────────────
log "Writing systemd service…"
cat > "$PKGROOT/etc/systemd/system/fanhub-daemon.service" << 'SVC'
[Unit]
Description=Fan Hub headless fan curve daemon
After=multi-user.target
Wants=multi-user.target

[Service]
Type=simple
User=root
ExecStart=/opt/fanhub/venv/bin/python3 /opt/fanhub/fanhub_daemon.py
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVC

# ── /usr/local/bin launchers ──────────────────────────────────────────────────
log "Writing launchers…"
cat > "$PKGROOT/usr/local/bin/fanhub" << 'LAUNCHER'
#!/bin/bash
FANHUB_HOME="/opt/fanhub"
export PYTHONPATH="$FANHUB_HOME"
if [ "$EUID" -eq 0 ]; then
    exec "$FANHUB_HOME/venv/bin/python3" "$FANHUB_HOME/main.py" "$@"
fi
if command -v pkexec >/dev/null 2>&1; then
    exec pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" \
        WAYLAND_DISPLAY="$WAYLAND_DISPLAY" XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
        PYTHONPATH="$FANHUB_HOME" \
        "$FANHUB_HOME/venv/bin/python3" "$FANHUB_HOME/main.py" "$@"
fi
exec "$FANHUB_HOME/venv/bin/python3" "$FANHUB_HOME/main.py" "$@"
LAUNCHER
chmod 0755 "$PKGROOT/usr/local/bin/fanhub"

cat > "$PKGROOT/usr/local/bin/fanhub-daemon" << 'DAEMONEOF'
#!/bin/bash
exec /opt/fanhub/venv/bin/python3 /opt/fanhub/fanhub_daemon.py "$@"
DAEMONEOF
chmod 0755 "$PKGROOT/usr/local/bin/fanhub-daemon"

# ── .desktop entry ────────────────────────────────────────────────────────────
cat > "$PKGROOT/usr/share/applications/fanhub.desktop" << 'DESKTOP'
[Desktop Entry]
Version=1.0
Type=Application
Name=Fan Hub
GenericName=Fan Controller
Comment=Linux Fan Control and RGB Management
Exec=/usr/local/bin/fanhub %U
Icon=fanhub
Terminal=false
Categories=System;HardwareSettings;
Keywords=fan;cpu;temperature;cooling;rgb;pwm;
StartupNotify=true
StartupWMClass=fanhub
DESKTOP

# ── copyright / changelog ─────────────────────────────────────────────────────
cat > "$PKGROOT/usr/share/doc/fanhub/copyright" << 'CR'
Fan Hub — Linux Fan Control and RGB Management
MIT License
CR

cat > "$PKGROOT/usr/share/doc/fanhub/changelog.Debian.gz" /dev/null 2>/dev/null || true
printf "fanhub (1.6.0) stable; urgency=low\n\n  * Multi-distro installer support\n  * Sensor name clarity improvements\n  * Fan percent tracking fixes\n\n -- Fan Hub <fanhub@localhost>  $(date -R)\n" \
    | gzip -9 > "$PKGROOT/usr/share/doc/fanhub/changelog.Debian.gz"

# ── DEBIAN/control ────────────────────────────────────────────────────────────
log "Writing DEBIAN/control…"

# Calculate installed size (kB)
INSTALLED_KB="$(du -sk "$PKGROOT/opt/fanhub" | cut -f1)"

cat > "$PKGROOT/DEBIAN/control" << CONTROL
Package: fanhub
Version: 1.6.0
Architecture: amd64
Maintainer: Fan Hub <fanhub@localhost>
Installed-Size: ${INSTALLED_KB}
Depends: python3 (>= 3.10), libhidapi-hidraw0 | libhidapi-libusb0, udev, policykit-1
Recommends: i2c-tools, lm-sensors
Suggests: openrgb
Section: utils
Priority: optional
Homepage: https://github.com/bobbycomet/fanhub
Description: Linux fan control and RGB management
 Fan Hub is a graphical fan speed and RGB controller for Linux.
 Draw temperature-to-speed curves, assign them per fan, save
 profiles, and keep them running at boot via a background daemon.
 .
 Supports motherboard SuperIO fans (nct6775, it87), AMD GPU fans
 via amdgpu hwmon, NVIDIA GPU fans via CoolBits or nvidia-settings,
 AIO coolers and USB hubs via liquidctl, and RGB lighting via OpenRGB.
CONTROL

# ── DEBIAN/conffiles ──────────────────────────────────────────────────────────
# Files in /etc that dpkg should not overwrite on upgrade without asking
cat > "$PKGROOT/DEBIAN/conffiles" << 'CONF'
/etc/udev/rules.d/99-fanhub.rules
/etc/modules-load.d/fanhub.conf
/etc/systemd/system/fanhub-daemon.service
CONF

# ── DEBIAN/postinst ───────────────────────────────────────────────────────────
log "Writing maintainer scripts…"
cat > "$PKGROOT/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e

# Determine the real user (the one who invoked sudo/pkexec)
ACTUAL_USER="${SUDO_USER:-${PKEXEC_UID:+$(getent passwd "$PKEXEC_UID" | cut -d: -f1)}}"
[ -z "$ACTUAL_USER" ] && ACTUAL_USER="$(logname 2>/dev/null || echo '')"

# ── Groups ────────────────────────────────────────────────────────────────────
groupadd -f fanhub  2>/dev/null || true
groupadd -f i2c     2>/dev/null || true
groupadd -f plugdev 2>/dev/null || true
[ -n "$ACTUAL_USER" ] && usermod -aG fanhub,i2c,plugdev "$ACTUAL_USER" 2>/dev/null || true

# ── udev ─────────────────────────────────────────────────────────────────────
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger              2>/dev/null || true

# ── Kernel modules ────────────────────────────────────────────────────────────
for mod in i2c-dev coretemp it87 nct6775; do
    modprobe "$mod" 2>/dev/null || true
done

# ── Sensor detection ──────────────────────────────────────────────────────────
if command -v sensors-detect >/dev/null 2>&1; then
    yes "" | sensors-detect --auto 2>/dev/null || true
fi

# ── Icons ─────────────────────────────────────────────────────────────────────
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor/ 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications/ 2>/dev/null || true
fi

# ── systemd ───────────────────────────────────────────────────────────────────
if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running --quiet 2>/dev/null; then
    systemctl daemon-reload 2>/dev/null || true
    # Only restart daemon if it was already enabled (preserve user choice)
    if systemctl is-enabled --quiet fanhub-daemon 2>/dev/null; then
        systemctl restart fanhub-daemon 2>/dev/null || true
    fi
fi

# ── User config directory ─────────────────────────────────────────────────────
if [ -n "$ACTUAL_USER" ]; then
    USER_HOME="$(getent passwd "$ACTUAL_USER" | cut -d: -f6)"
    if [ -n "$USER_HOME" ]; then
        mkdir -p "$USER_HOME/.config/fanhub/profiles"
        chown -R "$ACTUAL_USER:$ACTUAL_USER" "$USER_HOME/.config/fanhub" 2>/dev/null || true
    fi
fi

# ── Make main.py executable ───────────────────────────────────────────────────
chmod +x /opt/fanhub/main.py        2>/dev/null || true
chmod +x /opt/fanhub/fanhub_daemon.py 2>/dev/null || true

echo ""
echo "Fan Hub 1.6.0 installed."
echo "Run: fanhub  (or find it in your application menu)"
echo "Log out and back in for group membership to take effect."
echo "Until then: sudo fanhub"
echo ""

#DEBHELPER#
exit 0
POSTINST
chmod 0755 "$PKGROOT/DEBIAN/postinst"

# ── DEBIAN/prerm ──────────────────────────────────────────────────────────────
cat > "$PKGROOT/DEBIAN/prerm" << 'PRERM'
#!/bin/bash
set -e
# Stop daemon before removing files
if command -v systemctl >/dev/null 2>&1; then
    systemctl stop    fanhub-daemon 2>/dev/null || true
    systemctl disable fanhub-daemon 2>/dev/null || true
fi
#DEBHELPER#
exit 0
PRERM
chmod 0755 "$PKGROOT/DEBIAN/prerm"

# ── DEBIAN/postrm ─────────────────────────────────────────────────────────────
cat > "$PKGROOT/DEBIAN/postrm" << 'POSTRM'
#!/bin/bash
set -e
case "$1" in
    purge)
        # Remove user config only on purge (not on upgrade or remove)
        rm -rf /opt/fanhub 2>/dev/null || true
        if command -v systemctl >/dev/null 2>&1; then
            systemctl daemon-reload 2>/dev/null || true
        fi
        if command -v gtk-update-icon-cache >/dev/null 2>&1; then
            gtk-update-icon-cache -f /usr/share/icons/hicolor/ 2>/dev/null || true
        fi
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database /usr/share/applications/ 2>/dev/null || true
        fi
        udevadm control --reload-rules 2>/dev/null || true
        ;;
    remove|upgrade|failed-upgrade|abort-install|abort-upgrade|disappear)
        if command -v systemctl >/dev/null 2>&1; then
            systemctl daemon-reload 2>/dev/null || true
        fi
        ;;
esac
#DEBHELPER#
exit 0
POSTRM
chmod 0755 "$PKGROOT/DEBIAN/postrm"

# ── Fix permissions before packaging ──────────────────────────────────────────
log "Setting permissions…"
# All files owned by root
find "$PKGROOT" -not -path "$PKGROOT/DEBIAN/*" \
    -exec chown root:root {} \; 2>/dev/null || true
# Executables
chmod 0755 "$PKGROOT/opt/fanhub/main.py"
chmod 0755 "$PKGROOT/opt/fanhub/fanhub_daemon.py"
find "$PKGROOT/opt/fanhub/venv/bin" -type f -exec chmod 0755 {} \;
# Config files
chmod 0644 "$PKGROOT/etc/udev/rules.d/99-fanhub.rules"
chmod 0644 "$PKGROOT/etc/modules-load.d/fanhub.conf"
chmod 0644 "$PKGROOT/etc/systemd/system/fanhub-daemon.service"
chmod 0644 "$PKGROOT/usr/share/applications/fanhub.desktop"

# ── Build the .deb ────────────────────────────────────────────────────────────
OUTPUT="$SCRIPT_DIR/${DEB_FILE}"
log "Building ${DEB_FILE}…"
fakeroot dpkg-deb --build "$PKGROOT" "$OUTPUT"

SIZE="$(du -sh "$OUTPUT" | cut -f1)"
ok "Built: $OUTPUT  ($SIZE)"
echo ""
echo "Install with:  sudo dpkg -i ${DEB_FILE}"
echo "Then:          sudo apt-get install -f   # fix any missing deps"
echo ""
echo "Or for automatic dep resolution:"
echo "               sudo apt install ./${DEB_FILE}"
