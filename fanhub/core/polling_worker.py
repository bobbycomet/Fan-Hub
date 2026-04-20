"""
Background polling worker - runs on a QThread to avoid blocking UI.
Emits signals with updated sensor and fan data.
"""
import logging
from PyQt6.QtCore import QThread, pyqtSignal, QTimer

logger = logging.getLogger('fanhub.worker')


class PollingWorker(QThread):
    """
    Polls hardware sensors and applies fan curves on a fixed interval.
    Emits signals that the UI can connect to for live updates.
    """

    # Signals — object type used for liquid list so LiquidDevice dataclasses
    # cross the thread boundary without needing to be registered Qt metatypes.
    sensors_updated     = pyqtSignal(dict)    # {sensor_id: float °C}
    fans_updated        = pyqtSignal(dict)    # {fan_id: dict}
    liquid_updated      = pyqtSignal(object)  # list[LiquidDevice]
    emergency_triggered = pyqtSignal(float)
    error_occurred      = pyqtSignal(str)

    def __init__(self, hw_monitor, curve_engine, liquid_manager,
                 rgb_manager, state, interval_ms=1000):
        super().__init__()
        self.hw       = hw_monitor
        self.curves   = curve_engine
        self.liquid   = liquid_manager
        self.rgb      = rgb_manager
        self.state    = state
        self.interval_ms = interval_ms
        self._running = False
        self._apply_curves = True
        self._rgb_reactive = False
        self._rgb_reactive_sensor = None
        self._rgb_reactive_device_ids = []

    def run(self):
        self._running = True
        while self._running:
            try:
                self._poll_cycle()
            except Exception as e:
                logger.error(f"Poll cycle error: {e}")
                self.error_occurred.emit(str(e))
            self.msleep(self.interval_ms)

    def _poll_cycle(self):
        # Read temperatures
        temps = self.hw.read_all_temps()
        unit = self.state.settings.get('temp_unit', 'C')
        if unit == 'F':
            temp_values = {sid: s.value_f for sid, s in temps.items()}
        else:
            temp_values = {sid: s.value for sid, s in temps.items()}
        # Always pass Celsius internally for curve computation
        temp_c_values = {sid: s.value for sid, s in temps.items()}
        self.sensors_updated.emit(temp_values)

        # Emergency check always uses °C
        if temp_c_values:
            max_temp = max(temp_c_values.values())
            if max_temp >= self.state.settings.get('emergency_temp', 90.0):
                self.emergency_triggered.emit(max_temp)

        # Read fans
        fans = self.hw.read_all_fans()
        fan_data = {fid: {
            'label':    f.label,
            'rpm':      f.current_rpm,
            'pwm':      f.current_pwm,
            'percent':  f.current_percent,
            'mode':     f.mode,
            'is_hub':   f.is_hub_channel,
            'hub_type': f.hub_type,
        } for fid, f in fans.items()}
        self.fans_updated.emit(fan_data)

        # Apply fan curves (always uses Celsius for physics)
        if self._apply_curves:
            self._apply_fan_curves(temp_c_values, fans)

        # Read liquid devices
        # BUG FIX: guard against liquid manager being None or unavailable
        if self.liquid is not None and self.liquid.available:
            try:
                devices = self.liquid.read_all_status()
                self.liquid_updated.emit(devices)
            except Exception as e:
                logger.debug(f"Liquid read error: {e}")

        # Reactive RGB
        # BUG FIX: guard against rgb manager being None
        if self._rgb_reactive and self.rgb is not None and temp_values:
            try:
                avg_temp = sum(temp_values.values()) / len(temp_values)
                for dev_id in self._rgb_reactive_device_ids:
                    self.rgb.set_temp_reactive(dev_id, avg_temp)
            except Exception as e:
                logger.debug(f"RGB reactive error: {e}")

    def _apply_fan_curves(self, temps, fans):
        safe = self.state.settings.get('safe_mode', True)
        for fan_id, fan in fans.items():
            target = self.curves.compute_speed(fan_id, temps)
            if target is None:
                continue  # auto mode
            if fan.mode in ('pwm', 'pwm_manual', 'pwm_auto'):
                self.hw.set_fan_percent(fan_id, target, safe_mode=safe)
            elif fan.mode == 'dc':
                self.hw.set_fan_dc_percent(fan_id, target)

    def set_interval(self, ms: int):
        self.interval_ms = max(250, ms)

    def set_curves_active(self, active: bool):
        self._apply_curves = active

    def set_rgb_reactive(self, active: bool, sensor_id=None, device_ids=None):
        self._rgb_reactive = active
        self._rgb_reactive_sensor = sensor_id
        self._rgb_reactive_device_ids = device_ids or []

    def stop(self):
        self._running = False
        self.wait(3000)
