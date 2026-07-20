#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Fan Hub Installer / Updater
# Supports: Ubuntu, Debian, Arch, Manjaro, Fedora, RHEL, openSUSE, Void,
#           Alpine, and any distro with Python 3.10+ and systemd.
# ─────────────────────────────────────────────────────────────────────────────
set -e

# FANHUB_SOURCE_DIR is set by the AppImage configure dialog so that when
# install.sh is extracted to /tmp and run as root via pkexec, it still knows
# where the actual application source files are (inside the AppImage or
# wherever the user unpacked the tarball).
if [ -n "$FANHUB_SOURCE_DIR" ] && [ -d "$FANHUB_SOURCE_DIR" ]; then
    FANHUB_DIR="$FANHUB_SOURCE_DIR"
else
    FANHUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
INSTALL_PREFIX="/opt/fanhub"
BIN_LINK="/usr/local/bin/fanhub"
DESKTOP_FILE="/usr/share/applications/fanhub.desktop"
UDEV_RULES="/etc/udev/rules.d/99-fanhub.rules"
ICON_SRC="$FANHUB_DIR/assets/icon.png"
VERSION_FILE="$INSTALL_PREFIX/VERSION"
CURRENT_VERSION="1.6.0"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[FanHub]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
err()  { echo -e "${RED}[ERROR ]${NC} $*"; exit 1; }

[ "$EUID" -ne 0 ] && err "Please run as root: sudo ./install.sh"

# Resolve the real (non-root) user who invoked this installer.
# pkexec sets PKEXEC_UID; sudo sets SUDO_USER; fallback to USER.
if [ -n "$PKEXEC_UID" ]; then
    ACTUAL_USER="$(getent passwd "$PKEXEC_UID" | cut -d: -f1)"
elif [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    ACTUAL_USER="$SUDO_USER"
else
    ACTUAL_USER="${USER:-root}"
fi
log "Fan Hub installer v${CURRENT_VERSION} — user: $ACTUAL_USER"

# ── Distro detection ──────────────────────────────────────────────────────────
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="${ID,,}"          # lowercase
        DISTRO_LIKE="${ID_LIKE,,}"   # e.g. "debian" for Ubuntu
    elif command -v lsb_release >/dev/null 2>&1; then
        DISTRO_ID="$(lsb_release -si | tr '[:upper:]' '[:lower:]')"
        DISTRO_LIKE=""
    else
        DISTRO_ID="unknown"
        DISTRO_LIKE=""
    fi
}

detect_distro
log "Detected distro: ${DISTRO_ID} (like: ${DISTRO_LIKE:-none})"

# ── Package installation — per distro ────────────────────────────────────────
install_system_packages() {
    local pm=""
    case "$DISTRO_ID" in
        # ── Debian/Ubuntu family ──────────────────────────────────────────────
        ubuntu|debian|linuxmint|pop|elementary|kali|raspbian|armbian|zorin)
            pm="apt" ;;
        *)
            # ID_LIKE covers: "linux mint" → debian, "manjaro" → arch, etc.
            case "$DISTRO_LIKE" in
                *debian*|*ubuntu*) pm="apt" ;;
                *arch*)            pm="pacman" ;;
                *fedora*|*rhel*)   pm="dnf" ;;
                *suse*)            pm="zypper" ;;
            esac
            ;;
    esac
    # Direct ID matches for distros that don't set ID_LIKE cleanly
    case "$DISTRO_ID" in
        arch|manjaro|endeavouros|garuda|artix|cachyos|crystal|blackarch)
            pm="pacman" ;;
        fedora|rhel|centos|rocky|almalinux|ol|nobara|ultramarine)
            pm="dnf" ;;
        opensuse*|sles|sled)
            pm="zypper" ;;
        void)
            pm="xbps" ;;
        alpine)
            pm="apk" ;;
        gentoo)
            pm="emerge" ;;
        nixos)
            pm="nix" ;;
    esac

    if [ -z "$pm" ]; then
        warn "Unknown distro '${DISTRO_ID}' — skipping system package install."
        warn "Ensure python3, python3-pip, python3-venv, i2c-tools, and"
        warn "lm-sensors are installed, then re-run this script."
        return 0
    fi

    log "Installing system dependencies via $pm…"
    case "$pm" in
        apt)
            apt-get update -qq
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                python3 python3-pip python3-venv \
                libhidapi-hidraw0 libhidapi-libusb0 \
                i2c-tools lm-sensors usbutils curl \
                policykit-1 2>/dev/null || \
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                python3 python3-pip python3-venv \
                libhidapi-hidraw0 libhidapi-libusb0 \
                i2c-tools lm-sensors usbutils curl
            ;;
        pacman)
            pacman -Sy --noconfirm --needed \
                python python-pip \
                hidapi \
                i2c-tools lm_sensors usbutils curl \
                polkit 2>/dev/null || true
            ;;
        dnf)
            dnf install -y \
                python3 python3-pip \
                hidapi \
                i2c-tools lm_sensors usbutils curl \
                polkit 2>/dev/null || true
            ;;
        zypper)
            zypper install -y --no-recommends \
                python3 python3-pip \
                libhidapi-hidraw0 libhidapi-libusb0 \
                i2c-tools sensors usbutils curl \
                polkit 2>/dev/null || true
            ;;
        xbps)
            xbps-install -Sy \
                python3 python3-pip \
                hidapi \
                i2c-tools lm_sensors usbutils curl \
                polkit 2>/dev/null || true
            ;;
        apk)
            apk add --no-cache \
                python3 py3-pip \
                hidapi \
                i2c-tools lm-sensors usbutils curl \
                polkit 2>/dev/null || true
            ;;
        emerge)
            warn "Gentoo detected — skipping auto-emerge. Install manually:"
            warn "  emerge dev-python/pip sys-apps/i2c-tools sys-apps/lm-sensors"
            ;;
        nix)
            warn "NixOS detected — the imperative installer doesn't work well on NixOS."
            warn "Use the AppImage instead, or add Fan Hub to your configuration.nix."
            warn "Required packages: python3, i2c-tools, lm_sensors"
            ;;
    esac
    ok "System dependencies installed"
}

install_system_packages

# ── lm-sensors detect ─────────────────────────────────────────────────────────
log "Detecting sensors (this probes hardware — takes a few seconds)…"
yes "" | sensors-detect --auto 2>/dev/null || true
ok "Sensor detection complete"

# ── Detect existing installation ──────────────────────────────────────────────
IS_UPDATE=false
PREV_VERSION="(none)"
if [ -d "$INSTALL_PREFIX" ] && [ -f "$VERSION_FILE" ]; then
    PREV_VERSION="$(cat "$VERSION_FILE" 2>/dev/null || echo 'unknown')"
    IS_UPDATE=true
    log "Existing installation found: v${PREV_VERSION} → upgrading to v${CURRENT_VERSION}"
elif [ -d "$INSTALL_PREFIX" ]; then
    IS_UPDATE=true
    log "Existing installation found (no version file) → upgrading to v${CURRENT_VERSION}"
else
    log "Fresh installation of v${CURRENT_VERSION}"
fi

# ── Stop running instance if updating ────────────────────────────────────────
if [ "$IS_UPDATE" = true ]; then
    log "Stopping any running Fan Hub instance…"
    pkill -f "fanhub/main.py" 2>/dev/null && sleep 1 || true
    pkill -f "fanhub/venv/bin/python3.*main.py" 2>/dev/null && sleep 1 || true
    systemctl stop openrgb-server.service 2>/dev/null || true
    CONFIG_DIR_USR="/home/$ACTUAL_USER/.config/fanhub"
    [ -d "$CONFIG_DIR_USR" ] && log "User config preserved at $CONFIG_DIR_USR"
fi

# ── Python venv ───────────────────────────────────────────────────────────────
log "Setting up Python environment at $INSTALL_PREFIX…"
mkdir -p "$INSTALL_PREFIX"

# On update, recreate venv to pick up any new Python version
if [ "$IS_UPDATE" = true ] && [ -d "$INSTALL_PREFIX/venv" ]; then
    log "Refreshing Python virtual environment…"
    rm -rf "$INSTALL_PREFIX/venv"
fi

# --system-site-packages lets us use distro PyQt6 if present (saves ~60MB download)
python3 -m venv "$INSTALL_PREFIX/venv" --system-site-packages

log "Installing Python packages into venv…"
"$INSTALL_PREFIX/venv/bin/python3" -m pip install --upgrade pip -q
"$INSTALL_PREFIX/venv/bin/python3" -m pip install \
    PyQt6 PyQt6-Charts \
    liquidctl \
    openrgb-python \
    psutil pyserial Pillow -q || warn "Some optional packages failed to install"
ok "Python environment ready"

# ── Copy application files ────────────────────────────────────────────────────
log "Copying application files…"

if [ "$IS_UPDATE" = true ]; then
    find "$INSTALL_PREFIX" -name "*.py"  -not -path "*/venv/*" -delete 2>/dev/null || true
    find "$INSTALL_PREFIX" -name "*.pyc" -delete 2>/dev/null || true
    find "$INSTALL_PREFIX" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
fi

cp -r "$FANHUB_DIR"/. "$INSTALL_PREFIX/"
chmod +x "$INSTALL_PREFIX/main.py"
echo "$CURRENT_VERSION" > "$VERSION_FILE"

# Generate icon sizes with Pillow
"$INSTALL_PREFIX/venv/bin/python3" -c "
from PIL import Image; import os
src = '$INSTALL_PREFIX/assets/icon.png'
if os.path.exists(src):
    img = Image.open(src)
    for size in [16, 32, 48, 64, 128, 256]:
        img.resize((size, size), Image.LANCZOS).save(f'$INSTALL_PREFIX/assets/icon_{size}.png')
    print('Icon sizes generated')
" 2>/dev/null || warn "Could not generate icon sizes (Pillow missing)"

ok "Files installed to $INSTALL_PREFIX"

# ── Install icons ─────────────────────────────────────────────────────────────
log "Installing icons…"
if [ -f "$ICON_SRC" ]; then
    for SIZE in 16 32 48 64 128 256; do
        ICON_DIR="/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps"
        mkdir -p "$ICON_DIR"
        SIZED="$INSTALL_PREFIX/assets/icon_${SIZE}.png"
        cp "${SIZED:-$ICON_SRC}" "$ICON_DIR/fanhub.png" 2>/dev/null || \
            cp "$ICON_SRC" "$ICON_DIR/fanhub.png"
    done
    mkdir -p /usr/share/pixmaps
    cp "$ICON_SRC" /usr/share/pixmaps/fanhub.png
    gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
    ok "Icons installed"
else
    warn "Icon file not found — skipping"
fi

# ── Launcher ──────────────────────────────────────────────────────────────────
log "Creating launchers…"
cat > "$BIN_LINK" << 'LAUNCHER'
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
chmod +x "$BIN_LINK"

cat > /usr/local/bin/fanhub-sudo << 'SUDOEOF'
#!/bin/bash
exec sudo /usr/local/bin/fanhub "$@"
SUDOEOF
chmod +x /usr/local/bin/fanhub-sudo

POLICY_DIR="/usr/share/polkit-1/actions"
if [ -d "$POLICY_DIR" ] && [ -f "$INSTALL_PREFIX/assets/org.fanhub.policy" ]; then
    cp "$INSTALL_PREFIX/assets/org.fanhub.policy" "$POLICY_DIR/"
    ok "polkit policy installed"
fi
ok "Launchers created"

# ── udev rules ────────────────────────────────────────────────────────────────
log "Installing udev rules…"

groupadd -f fanhub 2>/dev/null || true
usermod -aG fanhub "$ACTUAL_USER" 2>/dev/null || true

cat > "$UDEV_RULES" << 'UDEV'
# Fan Hub — targeted hwmon PWM access (fanhub group only, not world-writable)
KERNEL=="pwm[0-9]*",        SUBSYSTEM=="hwmon", ACTION=="add", GROUP="fanhub", MODE="0660"
KERNEL=="pwm[0-9]*_enable", SUBSYSTEM=="hwmon", ACTION=="add", GROUP="fanhub", MODE="0660"
KERNEL=="fan[0-9]*_min",    SUBSYSTEM=="hwmon", ACTION=="add", GROUP="fanhub", MODE="0660"
# Fallback: set ownership on hwmon node add
KERNEL=="hwmon[0-9]*", SUBSYSTEM=="hwmon", ACTION=="add", \
    RUN+="/bin/sh -c 'chown root:fanhub /sys%p/pwm* 2>/dev/null; chmod 660 /sys%p/pwm* 2>/dev/null || true'"
# I2C bus
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
# USB cooling/RGB devices — TAG+="uaccess" lets the logged-in user access them
SUBSYSTEMS=="usb", ATTRS{idVendor}=="1b1c", TAG+="uaccess"  # Corsair
SUBSYSTEMS=="usb", ATTRS{idVendor}=="2433", TAG+="uaccess"  # NZXT
SUBSYSTEMS=="usb", ATTRS{idVendor}=="2516", TAG+="uaccess"  # Cooler Master
SUBSYSTEMS=="usb", ATTRS{idVendor}=="3842", TAG+="uaccess"  # EVGA
SUBSYSTEMS=="usb", ATTRS{idVendor}=="264a", TAG+="uaccess"  # Thermaltake
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0c70", TAG+="uaccess"  # Aqua Computer
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0db0", TAG+="uaccess"  # MSI
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0b05", TAG+="uaccess"  # ASUS
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", TAG+="uaccess"
UDEV

udevadm control --reload-rules && udevadm trigger
ok "udev rules installed"

# ── Groups ────────────────────────────────────────────────────────────────────
log "Configuring user groups…"
groupadd -f i2c     2>/dev/null || true
groupadd -f plugdev 2>/dev/null || true
usermod -aG i2c,plugdev,fanhub "$ACTUAL_USER" 2>/dev/null || true
ok "Groups configured (i2c, plugdev, fanhub)"

# ── Kernel modules ────────────────────────────────────────────────────────────
log "Loading kernel modules…"
for mod in i2c-dev coretemp it87 nct6775 w83795; do
    modprobe "$mod" 2>/dev/null && ok "  Loaded: $mod" || true
done

# modules-load.d is systemd — use /etc/modules as fallback for non-systemd
MODULES_LOAD_DIR="/etc/modules-load.d"
if [ -d "$MODULES_LOAD_DIR" ]; then
    cat > "$MODULES_LOAD_DIR/fanhub.conf" << 'MODS'
i2c-dev
coretemp
it87
nct6775
MODS
    ok "Kernel modules configured (systemd modules-load.d)"
elif [ -f /etc/modules ]; then
    for mod in i2c-dev coretemp it87 nct6775; do
        grep -q "^$mod" /etc/modules || echo "$mod" >> /etc/modules
    done
    ok "Kernel modules configured (/etc/modules)"
fi

# ── Detect init system ────────────────────────────────────────────────────────
log "Detecting init system…"
INIT_SYSTEM="unknown"

# Check PID 1 name first — most reliable method
PID1_COMM="$(cat /proc/1/comm 2>/dev/null | tr '[:upper:]' '[:lower:]')"
case "$PID1_COMM" in
    *systemd*)  INIT_SYSTEM="systemd" ;;
    runit*)     INIT_SYSTEM="runit"   ;;
    openrc-init|init)
        # 'init' is ambiguous; check further
        [ -d /run/openrc ] || [ -f /sbin/openrc-run ] && INIT_SYSTEM="openrc"
        ;;
esac

# Fallbacks when PID1 name is ambiguous
if [ "$INIT_SYSTEM" = "unknown" ]; then
    [ -d /run/systemd/private ]          && INIT_SYSTEM="systemd"
    [ -d /etc/sv ] || [ -f /run/runit.stopit ] && INIT_SYSTEM="runit"
    [ -d /run/openrc ]                   && INIT_SYSTEM="openrc"
    command -v systemctl >/dev/null 2>&1 && INIT_SYSTEM="systemd"
    command -v sv >/dev/null 2>&1        && [ "$INIT_SYSTEM" = "unknown" ] && INIT_SYSTEM="runit"
    command -v rc-service >/dev/null 2>&1 && [ "$INIT_SYSTEM" = "unknown" ] && INIT_SYSTEM="openrc"
fi

log "Init system: $INIT_SYSTEM"

# ── OpenRGB server service (systemd only) ────────────────────────────────────
OPENRGB_BIN="$(command -v openrgb 2>/dev/null || echo '')"
if [ -n "$OPENRGB_BIN" ] && [ "$INIT_SYSTEM" = "systemd" ]; then
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
    systemctl start  openrgb-server.service 2>/dev/null || \
        warn "OpenRGB server failed to start"
    ok "OpenRGB server service installed"
elif [ -n "$OPENRGB_BIN" ]; then
    warn "OpenRGB found but init is ${INIT_SYSTEM} — start it manually: openrgb --server"
fi

# ── Desktop entry ─────────────────────────────────────────────────────────────
log "Creating desktop entry…"
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" << DESKTOP
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
update-desktop-database /usr/share/applications/ 2>/dev/null || true
ok "Desktop entry created"

# ── Config directory ──────────────────────────────────────────────────────────
CONFIG_DIR="/home/$ACTUAL_USER/.config/fanhub"
mkdir -p "$CONFIG_DIR/profiles"
chown -R "$ACTUAL_USER:$ACTUAL_USER" "$CONFIG_DIR"
ok "Config directory: $CONFIG_DIR"

# ── Daemon ────────────────────────────────────────────────────────────────────
log "Installing Fan Hub daemon…"
chmod +x "$INSTALL_PREFIX/fanhub_daemon.py"

# Shared CLI wrapper (same for all init systems)
cat > /usr/local/bin/fanhub-daemon << 'DAEMONEOF'
#!/bin/bash
exec /opt/fanhub/venv/bin/python3 /opt/fanhub/fanhub_daemon.py "$@"
DAEMONEOF
chmod +x /usr/local/bin/fanhub-daemon

case "$INIT_SYSTEM" in

  # ── systemd ────────────────────────────────────────────────────────────────
  systemd)
    cat > /etc/systemd/system/fanhub-daemon.service << 'SVCEOF'
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
SVCEOF
    systemctl daemon-reload
    if systemctl is-enabled --quiet fanhub-daemon 2>/dev/null; then
        systemctl restart fanhub-daemon 2>/dev/null && \
            ok "Daemon restarted (was already enabled)" || \
            warn "Daemon restart failed — check: systemctl status fanhub-daemon"
    else
        ok "Daemon installed (systemd). Enable in Fan Hub → Settings → Background Daemon."
        log "  Or: sudo systemctl enable --now fanhub-daemon"
    fi
    ;;

  # ── runit (Void Linux) ─────────────────────────────────────────────────────
  runit)
    mkdir -p /etc/sv/fanhub-daemon/log
    cat > /etc/sv/fanhub-daemon/run << 'RUNIT'
#!/bin/sh
# runit run script — process must stay in the foreground (no fork/daemonize)
exec /opt/fanhub/venv/bin/python3 /opt/fanhub/fanhub_daemon.py 2>&1
RUNIT
    chmod +x /etc/sv/fanhub-daemon/run
    # Optional log service (runit log directory)
    cat > /etc/sv/fanhub-daemon/log/run << 'RUNITLOG'
#!/bin/sh
exec svlogd -tt /var/log/fanhub-daemon
RUNITLOG
    chmod +x /etc/sv/fanhub-daemon/log/run
    mkdir -p /var/log/fanhub-daemon
    ok "Daemon installed (runit service at /etc/sv/fanhub-daemon)."
    log "  Enable with: sudo ln -s /etc/sv/fanhub-daemon /var/service/"
    log "  Start now:   sudo sv up fanhub-daemon"
    log "  Or enable in Fan Hub → Settings → Background Daemon."
    ;;

  # ── OpenRC (Alpine, Gentoo) ────────────────────────────────────────────────
  openrc)
    cat > /etc/init.d/fanhub-daemon << 'OPENRC'
#!/sbin/openrc-run
name="fanhub-daemon"
description="Fan Hub headless fan curve daemon"
command="/opt/fanhub/venv/bin/python3"
command_args="/opt/fanhub/fanhub_daemon.py"
command_background="true"
pidfile="/run/fanhub-daemon.pid"
output_log="/var/log/fanhub-daemon.log"
error_log="/var/log/fanhub-daemon.log"

depend() {
    need localmount
    after modules
}
OPENRC
    chmod +x /etc/init.d/fanhub-daemon
    ok "Daemon installed (OpenRC service at /etc/init.d/fanhub-daemon)."
    log "  Enable with: sudo rc-update add fanhub-daemon default"
    log "  Start now:   sudo rc-service fanhub-daemon start"
    log "  Or enable in Fan Hub → Settings → Background Daemon."
    ;;

  # ── Unknown / unsupported ──────────────────────────────────────────────────
  *)
    warn "Could not detect init system — daemon service not installed."
    warn "Fan Hub will work but fan curves won't persist across reboots."
    warn "Run the daemon manually: sudo fanhub-daemon"
    ;;
esac

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [ "$IS_UPDATE" = true ]; then
    echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  Fan Hub updated: v${PREV_VERSION} → v${CURRENT_VERSION}              ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
else
    echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  Fan Hub v${CURRENT_VERSION} installed successfully! 🌀    ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
fi
echo ""
echo -e "  Run:         ${CYAN}fanhub${NC}"
echo -e "  Run as root: ${CYAN}sudo fanhub${NC}"
echo -e "  Logs:        ${CYAN}~/.config/fanhub/fanhub.log${NC}"
echo -e "  Distro:      ${CYAN}${DISTRO_ID}${NC}"
echo ""
echo -e "${YELLOW}NOTE: Log out and back in for group changes to take effect.${NC}"
echo -e "${YELLOW}      Until then: sudo fanhub${NC}"
echo ""
[ -z "$OPENRGB_BIN" ] && \
    echo -e "${YELLOW}RGB TIP: Install OpenRGB from https://openrgb.org${NC}\n"

exit 0
