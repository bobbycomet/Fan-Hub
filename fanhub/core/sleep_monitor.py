"""
Sleep/resume detection.

Strategy, tried in order:
  1. D-Bus systemd-logind PrepareForSleep (systemd systems, most reliable)
  2. elogind PrepareForSleep via D-Bus (OpenRC + elogind — same D-Bus path)
  3. /sys/power/wakeup_count file-watcher (runit/OpenRC without elogind)
     Polls every 5 seconds; detects resume when the count increments.
  4. Nothing — sleep detection silently disabled, fan curves stay active
     but hardware won't be rescanned after wake.
"""
import logging
import os
import time

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QThread

logger = logging.getLogger('fanhub.sleep')

_WAKEUP_COUNT = '/sys/power/wakeup_count'


class SleepMonitor(QObject):
    """
    Emits `resumed` signal when the system wakes from sleep.
    Constructor never raises — falls back gracefully at each layer.
    """
    resumed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dbus_ok   = False
        self._watcher   = None

        if self._try_dbus():
            logger.info("SleepMonitor: D-Bus (logind/elogind) active")
        elif os.path.exists(_WAKEUP_COUNT):
            self._start_wakeup_watcher()
            logger.info("SleepMonitor: wakeup_count file-watcher active "
                        "(non-systemd fallback)")
        else:
            logger.info("SleepMonitor: no sleep/resume detection available")

    # ── D-Bus path (systemd-logind or elogind) ────────────────────────────────

    def _try_dbus(self) -> bool:
        """
        Try to connect to PrepareForSleep on the D-Bus system bus.
        Works on systemd AND on OpenRC/runit systems that run elogind,
        because elogind exposes the identical org.freedesktop.login1 interface.
        """
        try:
            from PyQt6.QtDBus import QDBusConnection, QDBusInterface
            bus = QDBusConnection.systemBus()
            if not bus.isConnected():
                return False
            ok = bus.connect(
                'org.freedesktop.login1',
                '/org/freedesktop/login1',
                'org.freedesktop.login1.Manager',
                'PrepareForSleep',
                self._on_prepare_for_sleep,
            )
            self._dbus_ok = ok
            return ok
        except ImportError:
            logger.debug("SleepMonitor: PyQt6.QtDBus not available")
        except Exception as e:
            logger.debug(f"SleepMonitor D-Bus: {e}")
        return False

    def _on_prepare_for_sleep(self, going_to_sleep: bool):
        if not going_to_sleep:
            logger.info("System resumed (D-Bus PrepareForSleep) — rescanning")
            QTimer.singleShot(2500, self.resumed.emit)

    # ── File-watcher fallback (/sys/power/wakeup_count) ───────────────────────

    def _start_wakeup_watcher(self):
        """
        Poll every 5 seconds. Detecting resume from wakeup_count ALONE is
        unreliable — on some systems (observed: USB peripherals causing
        continuous wakeup source churn) the counter increments constantly
        while the machine is fully awake, which would fire spurious
        "resume" events every poll and trigger a disruptive full hardware
        rescan while the user is actively using the app.

        The reliable signal is wall-clock GAP between timer ticks. This
        QTimer is set to fire every 5 seconds; if the actual measured gap
        between two consecutive ticks is much larger than 5 seconds, the
        process itself was frozen (real suspend-to-RAM), because a frozen
        process cannot service its own timers. USB/RTC wakeup_count churn
        does not freeze the process, so the tick interval stays normal —
        it will never trigger this path no matter how often the counter
        changes.
        """
        self._last_wakeup    = self._read_wakeup_count()
        self._last_tick_time = time.monotonic()
        self._interval_s     = 5.0
        self._watcher = QTimer(self)
        self._watcher.setInterval(int(self._interval_s * 1000))
        self._watcher.timeout.connect(self._poll_wakeup_count)
        self._watcher.start()

    def _read_wakeup_count(self) -> int:
        try:
            with open(_WAKEUP_COUNT) as f:
                return int(f.read().strip())
        except Exception:
            return 0

    def _poll_wakeup_count(self):
        now = time.monotonic()
        gap = now - self._last_tick_time
        self._last_tick_time = now

        current = self._read_wakeup_count()
        changed = current != self._last_wakeup
        self._last_wakeup = current

        # A frozen process's QTimer cannot fire during suspend — the tick
        # after resume will show a gap several times larger than the
        # configured interval. Require both signals so a single busy CPU
        # spike (which can also delay a timer tick slightly) doesn't
        # false-positive: the gap must be large AND wakeup_count must have
        # actually moved.
        if gap > (self._interval_s * 3) and changed:
            logger.info(
                f"System resumed (timer gap {gap:.0f}s vs expected "
                f"{self._interval_s:.0f}s, wakeup_count changed) — rescanning")
            QTimer.singleShot(2500, self.resumed.emit)
        elif changed:
            logger.debug(
                f"wakeup_count changed but timer gap was normal "
                f"({gap:.1f}s) — process never froze, ignoring "
                "(likely USB/RTC wakeup source, not real suspend)")
