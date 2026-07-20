"""
DaemonController — single place for all fanhub-daemon init system interactions.

Supports systemd, runit (Void Linux), and OpenRC (Alpine, Gentoo).
Detected at runtime via core.init_system.detect_init().

Every public method is safe to call on any init system — unsupported
operations return False rather than raising.
"""
import os
import signal
import subprocess
import logging
from typing import Tuple

from core.init_system import detect_init, init_name

logger = logging.getLogger('fanhub.daemon')

SERVICE     = 'fanhub-daemon'
RUNIT_SVC   = f'/etc/sv/{SERVICE}'           # runit service directory
RUNIT_LINK  = f'/var/service/{SERVICE}'      # enabled when symlinked here
OPENRC_SVC  = f'/etc/init.d/{SERVICE}'       # OpenRC init script
SYSTEMD_SVC = f'/etc/systemd/system/{SERVICE}.service'


# ── Value object ──────────────────────────────────────────────────────────────

class DaemonStatus:
    """Describes the current daemon state across all init systems."""
    __slots__ = ('installed', 'active', 'enabled', 'init', 'no_init_support')

    def __init__(self, installed: bool, active: bool, enabled: bool,
                 init: str = 'unknown', no_init_support: bool = False):
        self.installed       = installed
        self.active          = active
        self.enabled         = enabled
        self.init            = init
        self.no_init_support = no_init_support

    def summary(self) -> Tuple[str, str]:
        """Return (text, css_color) for the Settings tab status label."""
        if self.no_init_support:
            return (
                f"⚠  Init system ({init_name()}) is not directly supported. "
                "See Settings for manual setup instructions.",
                "#aa6600"
            )
        if not self.installed:
            return (
                "⚠  Daemon not installed — run  sudo ./install.sh  to install it.",
                "#aa6600"
            )
        if self.active and self.enabled:
            return ("● Running — curves active. Enabled at startup.", "#44ff88")
        if self.active:
            return ("◐ Running now, but not enabled at startup.", "#ffaa44")
        if self.enabled:
            return ("◑ Enabled at startup, but not currently running. "
                    "Click ▶ Start now.", "#ffaa44")
        return (
            "○ Stopped and disabled. "
            "Enable the checkbox above and save to activate.",
            "#556677"
        )


# ── Main controller ───────────────────────────────────────────────────────────

class DaemonController:
    """
    All init-system interactions for fanhub-daemon in one class.
    Dispatches to the appropriate backend (systemd/runit/openrc) based on
    what's actually running, detected once at import time.
    """

    # ── Low-level runners ─────────────────────────────────────────────────────

    @staticmethod
    def _run(*args, timeout: int = 5) -> Tuple[int, str]:
        """Run a command. Returns (returncode, stdout)."""
        try:
            r = subprocess.run(list(args), capture_output=True,
                               text=True, timeout=timeout)
            return r.returncode, r.stdout.strip()
        except FileNotFoundError:
            return -1, '__not_found__'
        except Exception as e:
            logger.debug(f"{' '.join(str(a) for a in args)}: {e}")
            return -2, ''

    @staticmethod
    def _systemctl(*args, timeout: int = 5) -> Tuple[int, str]:
        return DaemonController._run('systemctl', *args, timeout=timeout)

    @staticmethod
    def _sv(*args, timeout: int = 5) -> Tuple[int, str]:
        return DaemonController._run('sv', *args, timeout=timeout)

    @staticmethod
    def _rc_service(*args, timeout: int = 5) -> Tuple[int, str]:
        return DaemonController._run('rc-service', SERVICE, *args, timeout=timeout)

    @staticmethod
    def _rc_update(*args, timeout: int = 5) -> Tuple[int, str]:
        return DaemonController._run('rc-update', *args, timeout=timeout)

    # ── Status ────────────────────────────────────────────────────────────────

    @classmethod
    def status(cls) -> DaemonStatus:
        init = detect_init()

        if init == 'systemd':
            rc_a, active_out  = cls._systemctl('is-active',  SERVICE)
            rc_e, enabled_out = cls._systemctl('is-enabled', SERVICE)
            if active_out == '__not_found__':
                return DaemonStatus(False, False, False, init,
                                    no_init_support=False)
            installed = enabled_out not in ('not-found', 'not found', '')
            return DaemonStatus(
                installed = installed,
                active    = active_out  == 'active',
                enabled   = enabled_out == 'enabled',
                init      = init,
            )

        if init == 'runit':
            installed = os.path.isdir(RUNIT_SVC)
            enabled   = os.path.islink(RUNIT_LINK)
            active    = False
            if enabled:
                rc, out = cls._sv('status', SERVICE)
                active = rc == 0 and out.startswith('run:')
            return DaemonStatus(installed, active, enabled, init)

        if init == 'openrc':
            installed = os.path.isfile(OPENRC_SVC)
            # rc-service status exits 0 when running
            rc, out = cls._rc_service('status')
            active  = (rc == 0 and 'started' in out.lower())
            # rc-update show shows services in runlevels
            rc2, out2 = cls._rc_update('show', 'default')
            enabled = SERVICE in out2
            return DaemonStatus(installed, active, enabled, init)

        # Unknown init — report honestly
        return DaemonStatus(False, False, False, init, no_init_support=True)

    @classmethod
    def is_active(cls) -> bool:
        return cls.status().active

    @classmethod
    def is_enabled(cls) -> bool:
        return cls.status().enabled

    # ── Start / stop ──────────────────────────────────────────────────────────

    @classmethod
    def start(cls) -> bool:
        init = detect_init()
        if init == 'systemd':
            rc, _ = cls._systemctl('start', SERVICE, timeout=8)
            return rc == 0
        if init == 'runit':
            # Ensure enabled first (symlink exists)
            if not os.path.islink(RUNIT_LINK):
                try:
                    os.symlink(RUNIT_SVC, RUNIT_LINK)
                except Exception:
                    pass
            rc, _ = cls._sv('up', SERVICE, timeout=8)
            return rc == 0
        if init == 'openrc':
            rc, _ = cls._rc_service('start', timeout=8)
            return rc == 0
        return False

    @classmethod
    def stop(cls) -> bool:
        init = detect_init()
        if init == 'systemd':
            rc, _ = cls._systemctl('stop', SERVICE, timeout=8)
            return rc == 0
        if init == 'runit':
            rc, _ = cls._sv('down', SERVICE, timeout=8)
            return rc == 0
        if init == 'openrc':
            rc, _ = cls._rc_service('stop', timeout=8)
            return rc == 0
        return False

    @classmethod
    def enable(cls) -> bool:
        """Enable + start the daemon at boot."""
        init = detect_init()
        if init == 'systemd':
            rc, _ = cls._systemctl('enable', '--now', SERVICE, timeout=8)
            return rc == 0
        if init == 'runit':
            try:
                if not os.path.islink(RUNIT_LINK):
                    os.symlink(RUNIT_SVC, RUNIT_LINK)
                cls._sv('up', SERVICE, timeout=8)
                return True
            except Exception as e:
                logger.warning(f"runit enable: {e}")
                return False
        if init == 'openrc':
            rc1, _ = cls._rc_update('add', SERVICE, 'default', timeout=5)
            rc2, _ = cls._rc_service('start', timeout=8)
            return rc1 == 0
        return False

    @classmethod
    def disable(cls) -> bool:
        """Disable + stop the daemon."""
        init = detect_init()
        if init == 'systemd':
            rc, _ = cls._systemctl('disable', '--now', SERVICE, timeout=8)
            return rc == 0
        if init == 'runit':
            cls._sv('down', SERVICE, timeout=8)
            try:
                if os.path.islink(RUNIT_LINK):
                    os.unlink(RUNIT_LINK)
                return True
            except Exception as e:
                logger.warning(f"runit disable: {e}")
                return False
        if init == 'openrc':
            cls._rc_service('stop', timeout=8)
            rc, _ = cls._rc_update('delete', SERVICE, 'default', timeout=5)
            return rc == 0
        return False

    @classmethod
    def reload(cls) -> bool:
        """
        Tell the daemon to re-read config without restarting.
        All three init systems support SIGHUP — we send it directly to the
        daemon process rather than via the init system, so this works
        universally regardless of init.
        """
        if not cls.is_active():
            return False

        # Find the daemon PID from the pidfile or /proc
        pid = cls._find_daemon_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGHUP)
                logger.debug(f"Sent SIGHUP to fanhub-daemon (pid {pid})")
                return True
            except ProcessLookupError:
                pass
            except PermissionError:
                pass

        # systemd fallback: use systemctl kill which works without knowing PID
        if detect_init() == 'systemd':
            rc, _ = cls._systemctl('kill', '--signal=SIGHUP', SERVICE, timeout=4)
            return rc == 0

        return False

    @staticmethod
    def _find_daemon_pid() -> int | None:
        """Find the running fanhub-daemon process ID."""
        # 1. Try pidfile written by daemon itself
        for pidfile in ('/run/fanhub-daemon.pid', '/var/run/fanhub-daemon.pid'):
            try:
                with open(pidfile) as f:
                    return int(f.read().strip())
            except Exception:
                pass

        # 2. Scan /proc for matching command line
        try:
            for entry in os.scandir('/proc'):
                if not entry.name.isdigit():
                    continue
                try:
                    with open(f'/proc/{entry.name}/cmdline', 'rb') as f:
                        cmdline = f.read().decode(errors='replace')
                    if 'fanhub_daemon.py' in cmdline:
                        return int(entry.name)
                except Exception:
                    pass
        except Exception:
            pass
        return None

    @classmethod
    def set_enabled(cls, enable: bool) -> bool:
        """Enable+start or disable+stop in one call."""
        if enable:
            ok = cls.enable()
            if ok:
                logger.info(f"fanhub-daemon enabled ({detect_init()})")
            return ok
        else:
            ok = cls.disable()
            if ok:
                logger.info(f"fanhub-daemon disabled ({detect_init()})")
            return ok

    @classmethod
    def init_system(cls) -> str:
        """Return the detected init system name string."""
        return detect_init()
