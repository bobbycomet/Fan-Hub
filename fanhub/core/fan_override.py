"""
Per-fan override registry — the single source of truth for whether a fan
is being controlled by the curve engine (AUTO) or by the user (MANUAL).

This is what eliminates the race condition between the GUI, daemon, and
curve engine. The polling worker checks this registry before applying any
curve target. If a fan is MANUAL, the curve engine never touches it.

The registry lives in the curve engine process. The daemon receives override
commands via the IPC socket (core/ipc.py) and writes them here.
"""
from enum import Enum
from typing import Dict, Optional


class FanControlMode(str, Enum):
    AUTO   = 'auto'    # Curve engine drives this fan
    MANUAL = 'manual'  # User has taken direct control; curve engine skips it
    CURVE  = 'curve'   # Explicit curve assignment (subset of AUTO)


class FanOverrideRegistry:
    """
    Thread-safe registry of per-fan control modes and manual speed values.
    
    The polling worker holds a reference to this and consults it on every
    cycle. The GUI and IPC handler write to it when the user changes a fan.
    """

    def __init__(self):
        import threading
        self._lock   = threading.Lock()
        # {fan_id: FanControlMode}
        self._modes:  Dict[str, FanControlMode] = {}
        # {fan_id: float}  — speed in % (0–100) when MANUAL
        self._speeds: Dict[str, float] = {}

    # ── Writes (GUI thread / IPC thread) ─────────────────────────────────────

    def set_manual(self, fan_id: str, speed_pct: float):
        """User has directly set a fan speed. Curve engine will skip this fan."""
        with self._lock:
            self._modes[fan_id]  = FanControlMode.MANUAL
            self._speeds[fan_id] = max(0.0, min(100.0, speed_pct))

    def set_auto(self, fan_id: str):
        """Return fan to curve/daemon control."""
        with self._lock:
            self._modes[fan_id] = FanControlMode.AUTO
            self._speeds.pop(fan_id, None)

    def set_all_auto(self):
        """Release all manual overrides — called by 'All Auto' button."""
        with self._lock:
            self._modes.clear()
            self._speeds.clear()

    # ── Reads (polling worker thread) ────────────────────────────────────────

    def is_manual(self, fan_id: str) -> bool:
        with self._lock:
            return self._modes.get(fan_id) == FanControlMode.MANUAL

    def manual_speed(self, fan_id: str) -> Optional[float]:
        with self._lock:
            return self._speeds.get(fan_id)

    def mode(self, fan_id: str) -> FanControlMode:
        with self._lock:
            return self._modes.get(fan_id, FanControlMode.AUTO)

    def snapshot(self) -> dict:
        """Return a copy of the full state for serialisation."""
        with self._lock:
            return {
                'modes':  {k: v.value for k, v in self._modes.items()},
                'speeds': dict(self._speeds),
            }

    def load_snapshot(self, data: dict):
        """Restore state from a serialised snapshot."""
        with self._lock:
            self._modes  = {k: FanControlMode(v)
                            for k, v in data.get('modes', {}).items()}
            self._speeds = dict(data.get('speeds', {}))
