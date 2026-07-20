#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Fan Hub Uninstaller
# Removes everything installed by install.sh.
# Does NOT remove ~/.config/fanhub/ (your profiles and curves are kept).
# Run: sudo ./uninstall.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[FanHub]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $*"; }

[ "$EUID" -ne 0 ] && echo -e "${RED}[ERROR ]${NC} Please run as root: sudo ./uninstall.sh" && exit 1

ACTUAL_USER="${SUDO_USER:-$USER}"
INSTALL_PREFIX="/opt/fanhub"

# ── Confirm ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}This will remove Fan Hub from your system.${NC}"
echo -e "  Your settings and profiles in ${CYAN}~/.config/fanhub/${NC} will be kept."
echo ""
read -rp "Continue? [y/N] " CONFIRM
[[ "${CONFIRM,,}" == "y" || "${CONFIRM,,}" == "yes" ]] || { echo "Aborted."; exit 0; }
echo ""

# ── Stop and disable daemon ───────────────────────────────────────────────────
# ── Detect init system ────────────────────────────────────────────────────────
INIT_SYSTEM="unknown"
PID1_COMM="$(cat /proc/1/comm 2>/dev/null | tr '[:upper:]' '[:lower:]')"
case "$PID1_COMM" in
    *systemd*)   INIT_SYSTEM="systemd" ;;
    runit*)      INIT_SYSTEM="runit"   ;;
esac
if [ "$INIT_SYSTEM" = "unknown" ]; then
    [ -d /run/systemd/private ]           && INIT_SYSTEM="systemd"
    [ -d /etc/sv ] || [ -f /run/runit.stopit ] && INIT_SYSTEM="runit"
    [ -d /run/openrc ]                    && INIT_SYSTEM="openrc"
    command -v systemctl  >/dev/null 2>&1 && INIT_SYSTEM="systemd"
    command -v sv         >/dev/null 2>&1 && [ "$INIT_SYSTEM" = "unknown" ] && INIT_SYSTEM="runit"
    command -v rc-service >/dev/null 2>&1 && [ "$INIT_SYSTEM" = "unknown" ] && INIT_SYSTEM="openrc"
fi
log "Init system: $INIT_SYSTEM"

log "Stopping Fan Hub daemon…"
case "$INIT_SYSTEM" in
    systemd)
        systemctl stop    fanhub-daemon.service  2>/dev/null && ok "  Daemon stopped"   || true
        systemctl disable fanhub-daemon.service  2>/dev/null && ok "  Daemon disabled"  || true
        systemctl stop    openrgb-server.service 2>/dev/null && ok "  OpenRGB stopped"  || true
        systemctl disable openrgb-server.service 2>/dev/null && ok "  OpenRGB disabled" || true
        ;;
    runit)
        sv down fanhub-daemon 2>/dev/null && ok "  Daemon stopped" || true
        rm -f /var/service/fanhub-daemon  2>/dev/null && ok "  Daemon disabled" || true
        ;;
    openrc)
        rc-service fanhub-daemon stop  2>/dev/null && ok "  Daemon stopped"  || true
        rc-update delete fanhub-daemon 2>/dev/null && ok "  Daemon disabled" || true
        ;;
esac

# ── Kill any running GUI instance ─────────────────────────────────────────────
log "Stopping any running Fan Hub GUI…"
pkill -f "$INSTALL_PREFIX/main.py"          2>/dev/null && ok "  GUI stopped" || true
pkill -f "$INSTALL_PREFIX/venv/bin/python3" 2>/dev/null || true
sleep 1

# ── systemd service files ─────────────────────────────────────────────────────
log "Removing service files…"
case "$INIT_SYSTEM" in
    systemd)
        rm -f /etc/systemd/system/fanhub-daemon.service
        rm -f /etc/systemd/system/openrgb-server.service
        systemctl daemon-reload 2>/dev/null || true
        ok "systemd service files removed"
        ;;
    runit)
        rm -rf /etc/sv/fanhub-daemon
        ok "runit service directory removed"
        ;;
    openrc)
        rm -f /etc/init.d/fanhub-daemon
        ok "OpenRC init script removed"
        ;;
esac

# ── udev rules ────────────────────────────────────────────────────────────────
log "Removing udev rules…"
rm -f /etc/udev/rules.d/99-fanhub.rules
udevadm control --reload-rules 2>/dev/null || true
ok "udev rules removed"

# ── Kernel module autoload config ─────────────────────────────────────────────
log "Removing kernel module config…"
rm -f /etc/modules-load.d/fanhub.conf
ok "Module autoload config removed"

# ── Launchers ─────────────────────────────────────────────────────────────────
log "Removing launchers…"
rm -f /usr/local/bin/fanhub
rm -f /usr/local/bin/fanhub-sudo
rm -f /usr/local/bin/fanhub-daemon
ok "Launchers removed"

# ── polkit policy ─────────────────────────────────────────────────────────────
log "Removing polkit policy…"
rm -f /usr/share/polkit-1/actions/org.fanhub.policy
ok "polkit policy removed"

# ── Desktop entry ─────────────────────────────────────────────────────────────
log "Removing desktop entry…"
rm -f /usr/share/applications/fanhub.desktop
update-desktop-database /usr/share/applications/ 2>/dev/null || true
ok "Desktop entry removed"

# ── Icons ─────────────────────────────────────────────────────────────────────
log "Removing icons…"
for SIZE in 16 32 48 64 128 256; do
    rm -f "/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/fanhub.png"
done
rm -f /usr/share/pixmaps/fanhub.png
gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
ok "Icons removed"

# ── Application files ─────────────────────────────────────────────────────────
log "Removing application files from $INSTALL_PREFIX…"
if [ -d "$INSTALL_PREFIX" ]; then
    rm -rf "$INSTALL_PREFIX"
    ok "Removed $INSTALL_PREFIX"
else
    warn "$INSTALL_PREFIX not found — already removed?"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Fan Hub has been removed from your system.       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Your settings are still at: ${CYAN}~/.config/fanhub/${NC}"
echo -e "  Remove them with:           ${CYAN}rm -rf ~/.config/fanhub${NC}"
echo ""
echo -e "  The ${CYAN}fanhub${NC} group still exists (safe to leave)."
echo -e "  Remove it with:  ${CYAN}sudo groupdel fanhub${NC}"
echo ""
