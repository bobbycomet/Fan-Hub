"""
PollingWorker — background QThread that reads hardware and applies fan curves.

Fan control priority (highest to lowest):
  1. Manual override  — user explicitly set a speed via Fan Control tab or IPC.
                        Curve engine and daemon NEVER touch this fan until released.
  2. Emergency        — any sensor >= emergency_temp → all AUTO fans jump to 100%.
                        Manual fans are NOT touched (user controls those).
  3. Curve / fixed    — CurveEngine computes target from temperature.
  4. Hardware auto    — no assignment → fan keeps board's own auto mode.

Staggered polling:
  hwmon sysfs  — every cycle   (~microseconds)
  nvidia-smi   — every 3 cycles
  liquidctl    — every 5 cycles
  system stats — every 2 cycles
"""
import logging
import threading
from typing import Dict, Optional

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger('fanhub.polling')


class PollingWorker(QThread):

    # ── Signals ───────────────────────────────────────────────────────────────
    sensors_updated      = pyqtSignal(dict)         # {sid: float} — temperatures
    fans_updated         = pyqtSignal(dict)         # {fid: FanEntry}
    liquid_updated       = pyqtSignal(list)         # [LiquidDevice]
    emergency_triggered  = pyqtSignal(float)        # max temp
    emergency_cleared    = pyqtSignal()
    error_occurred       = pyqtSignal(str)          # error message for status bar
    stats_updated        = pyqtSignal(dict)         # system stats from psutil

    def __init__(self, hw, curves, liquid, rgb, state, interval_ms: int = 1000):
        super().__init__()
        self.hw      = hw
        self.curves  = curves
        self.liquid  = liquid
        self.rgb     = rgb
        self.state   = state

        self._running         = False
        self._fan_lock        = threading.Lock()
        self._cycle           = 0
        self._nvidia_interval = 3
        self._liquid_interval = 5
        self._last_emergency  = False
        self._interval_ms     = interval_ms
        self._interval_lock   = threading.Lock()

        # IPC client — connects to daemon if running (set by MainWindow)
        self._ipc: Optional[object] = None

        # Override registry — the single source of truth for MANUAL vs AUTO
        # fan control, shared between this worker and the IPC channel to the
        # daemon so GUI and daemon never fight over the same fan.
        from core.fan_override import FanOverrideRegistry
        self.overrides = FanOverrideRegistry()

        # System stats collector (CPU/RAM/disk/net via psutil)
        from core.system_stats import SystemStatsCollector
        self._stats = SystemStatsCollector()
        self._stats_interval = 2

    def set_ipc(self, ipc_client):
        self._ipc = ipc_client

    def set_interval(self, ms: int):
        """Called from Settings when the user changes poll interval live —
        takes effect on the next sleep without restarting the thread."""
        with self._interval_lock:
            self._interval_ms = max(100, int(ms))

    def stop(self):
        self._running = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        self._running = True
        while self._running:
            try:
                self._poll_cycle()
            except Exception as e:
                logger.error(f"Poll cycle error: {e}")
                self.error_occurred.emit(str(e))
            with self._interval_lock:
                ms = self._interval_ms
            self.msleep(ms)

    def _poll_cycle(self):
        self._cycle += 1

        # ── Read temperatures ─────────────────────────────────────────────────
        old_indices = list(self.hw._nvidia_indices)
        if self._cycle % self._nvidia_interval != 0:
            self.hw._nvidia_indices = []
        temps = self.hw.read_all_temps()
        self.hw._nvidia_indices = old_indices

        temp_vals = {sid: s.value for sid, s in temps.items() if s.value > 0}
        self.sensors_updated.emit(temp_vals)

        # ── Emergency check (only AUTO fans jump to 100%) ─────────────────────
        emergency_temp = self.state.settings.get('emergency_temp', 90.0)
        max_temp = max(temp_vals.values()) if temp_vals else 0.0
        is_emergency = max_temp >= emergency_temp

        if is_emergency and not self._last_emergency:
            self.emergency_triggered.emit(max_temp)
        elif not is_emergency and self._last_emergency:
            self.emergency_cleared.emit()
        self._last_emergency = is_emergency

        # ── Apply fan control ─────────────────────────────────────────────────
        with self._fan_lock:
            fans = self.hw.read_all_fans()
            self._apply_fan_control(temp_vals, fans, is_emergency)
        self.fans_updated.emit(dict(fans))

        # ── System stats (psutil, staggered) ──────────────────────────────────
        if self._cycle % self._stats_interval == 0:
            try:
                self.stats_updated.emit(self._stats.collect())
            except Exception as e:
                logger.debug(f"Stats collect: {e}")

        # ── Liquidctl (staggered) ─────────────────────────────────────────────
        if (self.liquid and self.liquid.available
                and self._cycle % self._liquid_interval == 0):
            try:
                self.liquid_updated.emit(self.liquid.read_all_status())
            except Exception as e:
                logger.debug(f"Liquid read: {e}")

    def _apply_fan_control(self, temps: dict, fans: dict,
                           is_emergency: bool):
        """
        Per-fan dispatch — this is what eliminates the GUI/daemon race
        condition and the "flapping" that was triggering false emergency
        warnings:
          MANUAL → hold at user_speed; curve engine never touches this fan.
          AUTO + emergency → 100%.
          AUTO, no emergency → curve/fixed target from CurveEngine.
        """
        safe_mode = self.state.settings.get('safe_mode', True)

        for fan_id, fan in fans.items():
            if not fan.controllable:
                continue

            # ── MANUAL override — absolute priority, never overridden ────────
            if self.overrides.is_manual(fan_id):
                spd = self.overrides.manual_speed(fan_id)
                if spd is not None:
                    self._write_speed(fan_id, spd, safe_mode)
                continue

            # ── Emergency (AUTO fans only) ────────────────────────────────────
            if is_emergency:
                self._write_speed(fan_id, 100.0, False)
                continue

            # ── Curve / fixed ─────────────────────────────────────────────────
            target = self.curves.compute_speed(fan_id, temps)
            if target is not None:
                self._write_speed(fan_id, target, safe_mode)

    def _write_speed(self, fan_id: str, pct: float, safe_mode: bool):
        """Convert percent to PWM and write to hardware."""
        pwm = int(pct / 100.0 * 255)
        try:
            self.hw.set_fan_pwm(fan_id, pwm, safe_mode=safe_mode)
        except Exception as e:
            logger.debug(f"set_fan_pwm {fan_id}: {e}")

    # ── External control (called from GUI thread) ─────────────────────────────

    def set_fan_manual(self, fan_id: str, speed_pct: float):
        """
        GUI user dragged a slider or clicked a preset — this is a MANUAL
        override. Marks the fan MANUAL in the shared registry (so this
        worker's next poll cycle skips curve computation for it), applies
        the speed immediately, and notifies the daemon via IPC so it also
        stops touching this fan instead of fighting the GUI's chosen speed.
        """
        self.overrides.set_manual(fan_id, speed_pct)
        safe = self.state.settings.get('safe_mode', True)
        with self._fan_lock:
            self._write_speed(fan_id, speed_pct, safe)
        if self._ipc and self._ipc.is_connected:
            self._ipc.send_override(fan_id, speed_pct)

    def set_fan_auto(self, fan_id: str):
        """GUI user clicked 'Auto' — return fan to curve control."""
        self.overrides.set_auto(fan_id)
        self.hw.set_fan_auto(fan_id)
        if self._ipc and self._ipc.is_connected:
            self._ipc.send_release(fan_id)

    def set_all_auto(self):
        """'All Auto' button — release all manual overrides."""
        self.overrides.set_all_auto()
        for fan_id in self.hw.fans:
            self.hw.set_fan_auto(fan_id)
        if self._ipc and self._ipc.is_connected:
            self._ipc.send_release_all()
