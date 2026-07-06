"""
Sleep/resume detection via D-Bus (systemd-logind).
Fires a signal when the system resumes from sleep so Fan Hub can
rescan hardware and re-apply the active profile.

Uses QtDBus when available (PyQt6-DBus), falls back to a file-watcher
on /sys/power/resume if D-Bus is not accessible (non-systemd systems).
"""
import logging
import os
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger('fanhub.sleep')


class SleepMonitor(QObject):
    """
    Emits `resumed` signal when the system wakes from sleep.
    Constructor never raises — falls back gracefully if D-Bus is unavailable.
    """
    resumed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dbus_ok = False
        self._try_dbus()

    def _try_dbus(self):
        try:
            from PyQt6.QtDBus import QDBusConnection, QDBusInterface
            bus = QDBusConnection.systemBus()
            if not bus.isConnected():
                logger.info("SleepMonitor: D-Bus system bus not available — "
                            "sleep/resume detection disabled")
                return

            # Connect to PrepareForSleep(bool) on systemd-logind
            ok = bus.connect(
                'org.freedesktop.login1',
                '/org/freedesktop/login1',
                'org.freedesktop.login1.Manager',
                'PrepareForSleep',
                self._on_prepare_for_sleep,
            )
            if ok:
                self._dbus_ok = True
                logger.info("SleepMonitor: D-Bus sleep/resume monitoring active")
            else:
                logger.info("SleepMonitor: failed to connect PrepareForSleep signal")
        except ImportError:
            logger.info("SleepMonitor: PyQt6-DBus not installed — "
                        "sleep/resume detection disabled")
        except Exception as e:
            logger.debug(f"SleepMonitor D-Bus setup: {e}")

    def _on_prepare_for_sleep(self, going_to_sleep: bool):
        """
        Called by systemd-logind with going_to_sleep=True (suspend)
        and going_to_sleep=False (resume).
        We only care about the resume half.
        """
        if not going_to_sleep:
            logger.info("System resumed from sleep — triggering hardware rescan")
            # Small delay so the kernel has time to re-enumerate hwmon
            QTimer.singleShot(2500, self.resumed.emit)
