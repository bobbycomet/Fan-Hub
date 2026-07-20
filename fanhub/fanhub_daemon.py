"""
fanhub-daemon — headless fan curve daemon.

Runs as a QCoreApplication (no windows, no display needed).
Receives per-fan override commands via IPC (QLocalServer / UNIX socket).
Applies fan curves from config.json every poll cycle.

Priority:
  1. MANUAL override (received via IPC from GUI)
  2. Emergency (sensor >= emergency_temp)
  3. Curve / fixed assignment
"""
import sys
import os
import signal
import logging

# Must be set before QCoreApplication is created
os.environ.setdefault('QT_MULTIMEDIA_BACKEND', 'dummy')

from PyQt6.QtCore import QCoreApplication, QTimer

# Add fanhub root to path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core.app_state import AppState
from core.hardware_monitor import HardwareMonitor
from core.fan_curves import CurveEngine, ProfileManager
from core.fan_override import FanOverrideRegistry, FanControlMode
from core.ipc import IPCServer
from core.init_system import detect_init

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.expanduser('~/.config/fanhub/fanhub-daemon.log'),
            mode='a'),
    ]
)
logger = logging.getLogger('fanhub.daemon')


def main():
    # QCoreApplication — no windows, no display
    app = QCoreApplication(sys.argv)
    app.setApplicationName('fanhub-daemon')
    app.setApplicationVersion('1.6.0')

    logger.info(f"fanhub-daemon starting (init: {detect_init()})")

    # ── Load state ────────────────────────────────────────────────────────────
    state  = AppState()
    hw     = HardwareMonitor()
    hw.apply_inverted_flags(state.settings.get('pwm_inverted_fans', {}))
    engine = CurveEngine(
        hysteresis_global=state.settings.get('hysteresis', 2.0),
        emergency_temp   =state.settings.get('emergency_temp', 90.0),
    )
    pm = ProfileManager(state)
    overrides = FanOverrideRegistry()

    # Apply active profile
    if state.active_profile:
        if pm.load_profile(state.active_profile, engine):
            logger.info(f"Loaded profile: {state.active_profile}")
        else:
            logger.warning(f"Profile not found: {state.active_profile}")

    # GPU fans default to performance curve unless profile assigns them
    for fid, fan in hw.fans.items():
        if fan.gpu_vendor and fan.controllable:
            if fid not in engine.fan_assignments:
                engine.assign_curve(fid, 'performance')
                logger.info(f"GPU fan {fid}: defaulting to performance curve")

    # ── IPC server ────────────────────────────────────────────────────────────
    ipc = IPCServer()
    ipc.start()

    def _on_override(fan_id: str, speed: float):
        logger.debug(f"IPC override: {fan_id} → {speed:.1f}%")
        overrides.set_manual(fan_id, speed)

    def _on_release(fan_id: str):
        logger.debug(f"IPC release: {fan_id}")
        overrides.set_auto(fan_id)

    def _on_release_all():
        logger.debug("IPC release_all")
        overrides.set_all_auto()

    def _on_reload():
        logger.info("IPC reload — re-reading config")
        _reload_config()

    ipc.override_received.connect(_on_override)
    ipc.release_received.connect(_on_release)
    ipc.release_all.connect(_on_release_all)
    ipc.reload_requested.connect(_on_reload)

    # ── Reload helper (SIGHUP + IPC reload) ──────────────────────────────────
    def _reload_config():
        try:
            state._load_config()
            engine.hysteresis_global = state.settings.get('hysteresis', 2.0)
            engine.emergency_temp    = state.settings.get('emergency_temp', 90.0)
            hw.apply_inverted_flags(state.settings.get('pwm_inverted_fans', {}))
            active = state.active_profile
            if active:
                pm.load_profile(active, engine)
                logger.info(f"Reloaded profile: {active}")
            for fid, fan in hw.fans.items():
                if fan.gpu_vendor and fan.controllable:
                    if fid not in engine.fan_assignments:
                        engine.assign_curve(fid, 'performance')
        except Exception as e:
            logger.error(f"Reload error: {e}")

    # ── Signal handlers ───────────────────────────────────────────────────────
    def _shutdown(signum, frame):
        logger.info("Shutdown — restoring fans to auto")
        for fid in hw.fans:
            try:
                hw.set_fan_auto(fid)
            except Exception:
                pass
        ipc.stop()
        app.quit()

    def _reload_sig(signum, frame):
        logger.info("SIGHUP — reloading config")
        _reload_config()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGHUP,  _reload_sig)

    # ── Poll loop ─────────────────────────────────────────────────────────────
    _cycle   = [0]
    _last_em = [False]

    def _poll():
        _cycle[0] += 1
        cycle = _cycle[0]

        # Suppress slow nvidia-smi on non-nvidia cycles
        old_nv = list(hw._nvidia_indices)
        if cycle % 3 != 0:
            hw._nvidia_indices = []
        try:
            temps = hw.read_all_temps()
        finally:
            hw._nvidia_indices = old_nv

        temp_vals = {sid: s.value for sid, s in temps.items() if s.value > 0}
        emergency_temp = engine.emergency_temp
        max_temp = max(temp_vals.values()) if temp_vals else 0.0
        is_em = max_temp >= emergency_temp

        if is_em and not _last_em[0]:
            logger.warning(f"EMERGENCY: {max_temp:.1f}°C >= {emergency_temp}°C — all AUTO fans → 100%")
        elif not is_em and _last_em[0]:
            logger.info("Emergency cleared — returning to curves")
        _last_em[0] = is_em

        fans = hw.read_all_fans()
        safe = state.settings.get('safe_mode', True)

        for fid, fan in fans.items():
            if not fan.controllable:
                continue

            # MANUAL override — daemon does not touch this fan
            if overrides.is_manual(fid):
                spd = overrides.manual_speed(fid)
                if spd is not None:
                    pwm = int(spd / 100.0 * 255)
                    try:
                        hw.set_fan_pwm(fid, pwm, safe_mode=safe)
                    except Exception:
                        pass
                continue

            # Emergency — AUTO fans jump to 100%
            if is_em:
                try:
                    hw.set_fan_pwm(fid, 255, safe_mode=False)
                except Exception:
                    pass
                continue

            # Curve / fixed
            target = engine.compute_speed(fid, temp_vals)
            if target is not None:
                pwm = int(target / 100.0 * 255)
                try:
                    hw.set_fan_pwm(fid, pwm, safe_mode=safe)
                except Exception:
                    pass

    interval_ms = state.settings.get('poll_interval_ms', 1000)
    timer = QTimer()
    timer.setInterval(interval_ms)
    timer.timeout.connect(_poll)
    timer.start()

    logger.info(f"Daemon polling every {interval_ms}ms")
    app.exec()


if __name__ == '__main__':
    main()
