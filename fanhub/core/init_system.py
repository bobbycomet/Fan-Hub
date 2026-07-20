"""
Init system detection — used by DaemonController and install scripts.

Detects which init system is running so Fan Hub can install and manage
the background daemon correctly on systemd, runit, and OpenRC systems.
"""
import os
import subprocess
import logging

logger = logging.getLogger('fanhub.init')

# Cached result so we only probe once per process
_CACHED: str | None = None


def detect_init() -> str:
    """
    Return one of: 'systemd', 'runit', 'openrc', 'unknown'.

    Detection order:
      1. /proc/1/comm — the name of PID 1 (most reliable)
      2. /run/systemd/private — systemd leaves this directory
      3. `sv` / `rc-service` binary presence — runit / OpenRC CLI
      4. DISTRO_ID hint from /etc/os-release as last resort
    """
    global _CACHED
    if _CACHED is not None:
        return _CACHED

    # ── 1. PID 1 name ─────────────────────────────────────────────────────────
    try:
        with open('/proc/1/comm') as f:
            pid1 = f.read().strip().lower()
        if 'systemd' in pid1:
            _CACHED = 'systemd'; return _CACHED
        if pid1 == 'runit' or pid1 == 'runit-init':
            _CACHED = 'runit'; return _CACHED
        if pid1 in ('openrc-init', 'init'):
            # 'init' is ambiguous — check further
            pass
    except Exception:
        pass

    # ── 2. Systemd runtime directory ──────────────────────────────────────────
    if os.path.isdir('/run/systemd/private'):
        _CACHED = 'systemd'; return _CACHED

    # ── 3. Runit runtime directories ──────────────────────────────────────────
    # Void: /run/runit.stopit or /etc/sv
    if os.path.exists('/run/runit.stopit') or os.path.isdir('/etc/sv'):
        _CACHED = 'runit'; return _CACHED

    # ── 4. OpenRC runtime ─────────────────────────────────────────────────────
    # OpenRC creates /run/openrc on boot
    if os.path.isdir('/run/openrc') or os.path.exists('/sbin/openrc-run'):
        _CACHED = 'openrc'; return _CACHED

    # ── 5. Binary presence ────────────────────────────────────────────────────
    try:
        subprocess.run(['systemctl', '--version'],
                       capture_output=True, timeout=2)
        _CACHED = 'systemd'; return _CACHED
    except Exception:
        pass

    if os.path.exists('/usr/bin/sv') or os.path.exists('/bin/sv'):
        _CACHED = 'runit'; return _CACHED

    if os.path.exists('/sbin/rc-service') or os.path.exists('/usr/sbin/rc-service'):
        _CACHED = 'openrc'; return _CACHED

    # ── 6. Distro hint ────────────────────────────────────────────────────────
    try:
        with open('/etc/os-release') as f:
            content = f.read().lower()
        if 'void' in content:
            _CACHED = 'runit'; return _CACHED
        if 'alpine' in content or 'gentoo' in content:
            _CACHED = 'openrc'; return _CACHED
    except Exception:
        pass

    _CACHED = 'unknown'
    return _CACHED


def init_name() -> str:
    """Human-readable init system name."""
    return {
        'systemd': 'systemd',
        'runit':   'runit (Void Linux)',
        'openrc':  'OpenRC (Alpine / Gentoo)',
        'unknown': 'unknown init system',
    }.get(detect_init(), 'unknown')
