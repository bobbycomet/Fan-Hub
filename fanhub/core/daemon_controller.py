"""
DaemonController — single place for all fanhub-daemon systemd interactions.

Replaces the scattered subprocess calls in main_window.py and settings_tab.py.
"""
import subprocess
import logging
from typing import Tuple

logger = logging.getLogger('fanhub.daemon')

SERVICE = 'fanhub-daemon'


class DaemonStatus:
    """Value object describing current daemon state."""
    __slots__ = ('installed', 'active', 'enabled', 'no_systemd')

    def __init__(self, installed: bool, active: bool,
                 enabled: bool, no_systemd: bool = False):
        self.installed  = installed
        self.active     = active
        self.enabled    = enabled
        self.no_systemd = no_systemd

    def summary(self) -> Tuple[str, str]:
        """Return (text, css_color) for the status label."""
        if self.no_systemd:
            return ("⚠  systemctl not found — non-systemd system, "
                    "daemon management unavailable.", "#aa6600")
        if not self.installed:
            return ("⚠  Daemon not installed — run  sudo ./install.sh  "
                    "to install it.", "#aa6600")
        if self.active and self.enabled:
            return ("● Running — curves active. Enabled at startup.", "#44ff88")
        if self.active:
            return ("◐ Running now, but not enabled at startup.", "#ffaa44")
        if self.enabled:
            return ("◑ Enabled at startup, but not currently running. "
                    "Click ▶ Start now.", "#ffaa44")
        return ("○ Stopped and disabled. "
                "Enable the checkbox above and save to activate.", "#556677")


class DaemonController:
    """
    All systemd interactions for fanhub-daemon in one place.
    Every method is safe to call on non-systemd systems — it catches
    FileNotFoundError and returns a sensible default.
    """

    @staticmethod
    def _run(*args, timeout: int = 5) -> Tuple[int, str]:
        """Run systemctl <args>. Returns (returncode, stdout)."""
        try:
            r = subprocess.run(
                ['systemctl'] + list(args),
                capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout.strip()
        except FileNotFoundError:
            return -1, '__no_systemctl__'
        except Exception as e:
            logger.debug(f"systemctl {' '.join(args)}: {e}")
            return -2, ''

    # ── Read state ────────────────────────────────────────────────────────────

    @classmethod
    def status(cls) -> DaemonStatus:
        """Query systemd for the full daemon state."""
        rc_active,  active_out  = cls._run('is-active',  SERVICE)
        rc_enabled, enabled_out = cls._run('is-enabled', SERVICE)

        if active_out == '__no_systemctl__':
            return DaemonStatus(False, False, False, no_systemd=True)

        # 'not-found' means the service file doesn't exist yet
        installed = enabled_out not in ('not-found', 'not found', '')
        active    = (active_out  == 'active')
        enabled   = (enabled_out == 'enabled')
        return DaemonStatus(installed, active, enabled)

    @classmethod
    def is_active(cls) -> bool:
        _, out = cls._run('is-active', SERVICE)
        return out == 'active'

    @classmethod
    def is_enabled(cls) -> bool:
        _, out = cls._run('is-enabled', SERVICE)
        return out == 'enabled'

    # ── Control ───────────────────────────────────────────────────────────────

    @classmethod
    def start(cls) -> bool:
        rc, _ = cls._run('start', SERVICE, timeout=8)
        return rc == 0

    @classmethod
    def stop(cls) -> bool:
        rc, _ = cls._run('stop', SERVICE, timeout=8)
        return rc == 0

    @classmethod
    def enable(cls) -> bool:
        """Enable and immediately start the daemon."""
        rc, _ = cls._run('enable', '--now', SERVICE, timeout=8)
        return rc == 0

    @classmethod
    def disable(cls) -> bool:
        """Disable and immediately stop the daemon."""
        rc, _ = cls._run('disable', '--now', SERVICE, timeout=8)
        return rc == 0

    @classmethod
    def reload(cls) -> bool:
        """Send SIGHUP so the daemon re-reads config without restarting."""
        if not cls.is_active():
            return False
        rc, _ = cls._run('kill', '--signal=SIGHUP', SERVICE, timeout=4)
        if rc == 0:
            logger.debug("Sent SIGHUP to fanhub-daemon")
            return True
        return False

    @classmethod
    def set_enabled(cls, enable: bool) -> bool:
        """Enable+start or disable+stop in one call."""
        if enable:
            ok = cls.enable()
            if ok:
                logger.info("fanhub-daemon enabled and started")
            return ok
        else:
            ok = cls.disable()
            if ok:
                logger.info("fanhub-daemon disabled and stopped")
            return ok
