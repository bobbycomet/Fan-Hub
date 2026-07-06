#!/usr/bin/env python3
"""
Fan Hub daemon — headless background service.
Loads AppState + CurveEngine, starts PollingWorker, runs until SIGTERM/SIGINT.

Usage:
  sudo fanhub-daemon              # run once in foreground (systemd will daemonise)
  sudo fanhub-daemon --status     # print current sensor readings and exit

Install as a systemd service via:  sudo ./install.sh --daemon-only
or manually:  sudo cp fanhub-daemon.service /etc/systemd/system/
              sudo systemctl daemon-reload && sudo systemctl enable --now fanhub

The daemon and the GUI can coexist — the daemon writes fan speeds via sysfs,
the GUI is read/write and will override the daemon for any fan it controls.
Profiles saved by the GUI are read by the daemon on startup.
"""
import sys
import os
import signal
import logging
import argparse
import time

# Must come before PyQt imports
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QCoreApplication, QTimer

CONFIG_DIR = os.path.expanduser('~/.config/fanhub')
LOG_PATH   = os.path.join(CONFIG_DIR, 'fanhub-daemon.log')


def _setup_logging(verbose: bool = False):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(LOG_PATH, mode='a'))
    except Exception:
        pass
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=handlers,
    )


def _print_status(hw, state):
    unit = state.settings.get('temp_unit', 'C')
    print("\n── Temperatures ──────────────────────────────────")
    for sensor in hw.temps.values():
        val = sensor.value_f if unit == 'F' else sensor.value
        sym = '°F' if unit == 'F' else '°C'
        print(f"  {sensor.label:<40} {val:.1f}{sym}")
    print("\n── Fans ──────────────────────────────────────────")
    for fan in hw.fans.values():
        rpm_s = f"{fan.current_rpm:>5} RPM" if fan.current_rpm else "  -- RPM"
        pct_s = f"{fan.current_percent:>5.1f}%"
        ctrl  = "✓" if fan.controllable else "✗"
        print(f"  {ctrl} {fan.label:<38} {rpm_s}  {pct_s}")
    profile = state.active_profile or "(none)"
    print(f"\n── Active profile: {profile}")
    print()


def main():
    parser = argparse.ArgumentParser(description='Fan Hub headless daemon')
    parser.add_argument('--status',  action='store_true', help='Print sensor status and exit')
    parser.add_argument('--verbose', action='store_true', help='Debug logging')
    args = parser.parse_args()

    _setup_logging(args.verbose)
    logger = logging.getLogger('fanhub.daemon')

    # QCoreApplication needed for QThread / signals (no windows — daemon only)
    app = QCoreApplication(sys.argv)
    app.setApplicationName("fanhub-daemon")

    from core.app_state import AppState
    from core.hardware_monitor import HardwareMonitor
    from core.fan_curves import CurveEngine, ProfileManager
    from core.polling_worker import PollingWorker

    state = AppState()
    hw    = HardwareMonitor()
    hw.read_all_fans()
    hw.read_all_temps()

    if args.status:
        _print_status(hw, state)
        return

    engine  = CurveEngine(
        hysteresis_global=state.settings.get('hysteresis', 2.0),
        emergency_temp   =state.settings.get('emergency_temp', 90.0),
    )
    pm = ProfileManager(state)

    if state.active_profile:
        if pm.load_profile(state.active_profile, engine):
            logger.info(f"Loaded profile: {state.active_profile}")
        else:
            logger.warning(f"Profile not found: {state.active_profile}")

    # GPU fans: default to performance curve unless profile already assigns them
    for fid, fan in hw.fans.items():
        if fan.gpu_vendor and fan.controllable:
            if fid not in engine.fan_assignments:
                engine.assign_curve(fid, 'performance')
                logger.info(f"GPU fan {fid}: defaulting to 'performance' curve")

    worker = PollingWorker(
        hw, engine, None, None, state,
        interval_ms=state.settings.get('poll_interval_ms', 1000),
    )

    def _on_emergency(temp):
        logger.warning(f"EMERGENCY: {temp:.1f}°C — all fans at 100%")

    def _on_error(msg):
        logger.error(f"Worker error: {msg}")

    worker.emergency_triggered.connect(_on_emergency)
    worker.error_occurred.connect(_on_error)

    # Sleep/resume recovery
    try:
        from core.sleep_monitor import SleepMonitor
        sm = SleepMonitor()
        def _on_resume():
            logger.info("Resume detected — rescanning hardware")
            worker.stop()
            hw.rescan()
            hw.read_all_fans()
            worker.start()
        sm.resumed.connect(_on_resume)
    except Exception as e:
        logger.debug(f"SleepMonitor: {e}")

    worker.start()
    logger.info(
        f"Fan Hub daemon started — {len(hw.fans)} fans, "
        f"{len(hw.temps)} sensors, profile={state.active_profile or 'none'}"
    )

    def _shutdown(signum, frame):
        logger.info("Shutting down — restoring fans to auto")
        worker.stop()
        for fid in hw.fans:
            hw.set_fan_auto(fid)
        app.quit()

    def _reload(signum, frame):
        """SIGHUP: reload config and re-apply active profile without restarting."""
        logger.info("SIGHUP received — reloading config")
        try:
            # Reload state from disk
            state._load_config()
            # Update engine settings
            engine.hysteresis_global = state.settings.get('hysteresis', 2.0)
            engine.emergency_temp    = state.settings.get('emergency_temp', 90.0)
            # Reload active profile curves
            active = state.active_profile
            if active:
                pm.load_profile(active, engine)
                logger.info(f"Reloaded profile: {active}")
            # Also apply GPU default if no assignment exists for GPU fans
            for fid, fan in hw.fans.items():
                if fan.gpu_vendor and fan.controllable:
                    if fid not in engine.fan_assignments:
                        engine.assign_curve(fid, 'performance')
        except Exception as e:
            logger.error(f"Reload error: {e}")

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGHUP,  _reload)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
