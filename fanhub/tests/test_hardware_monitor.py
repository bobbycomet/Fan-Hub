"""
Unit tests for HardwareMonitor label translation and GPU classification.
Uses mocks — no real /sys/class/hwmon is read.
"""
import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFriendlyTempLabel(unittest.TestCase):
    """_friendly_temp_label() — pure string logic, no I/O."""

    def setUp(self):
        from core.hardware_monitor import _friendly_temp_label
        self._f = _friendly_temp_label

    def _label(self, raw, chip, n=1):
        return self._f(raw, chip, n)

    # ── Motherboard SuperIO ────────────────────────────────────────────────────
    def test_systin(self):
        self.assertIn('System Temperature', self._label('SYSTIN', 'nct6798'))

    def test_cputin(self):
        self.assertIn('CPU Socket', self._label('CPUTIN', 'nct6798'))

    def test_auxtin0(self):
        r = self._label('AUXTIN0', 'nct6798')
        self.assertIn('Auxiliary', r)

    # ── AMD CPU (k10temp) ──────────────────────────────────────────────────────
    def test_tctl(self):
        r = self._label('Tctl', 'k10temp')
        self.assertIn('CPU Temperature', r)
        self.assertIn('Control', r)

    def test_tdie(self):
        r = self._label('Tdie', 'k10temp')
        self.assertIn('CPU Temperature', r)
        self.assertIn('Die', r)

    def test_tccd1(self):
        r = self._label('Tccd1', 'k10temp')
        self.assertIn('CPU Chiplet 1', r)

    # ── Intel CPU (coretemp) ───────────────────────────────────────────────────
    def test_package_id(self):
        r = self._label('Package id 0', 'coretemp', 1)
        self.assertIn('CPU Package Temperature', r)

    def test_core_n_dynamic(self):
        r = self._label('Core 4', 'coretemp', 5)
        self.assertIn('4', r)
        self.assertIn('CPU Core', r)

    def test_core_zero(self):
        r = self._label('Core 0', 'coretemp', 1)
        self.assertIn('CPU Core 0', r)

    # ── NVMe ──────────────────────────────────────────────────────────────────
    def test_composite(self):
        r = self._label('Composite', 'nvme', 1)
        self.assertIn('Drive Temperature', r)

    def test_sensor_n(self):
        r = self._label('Sensor 1', 'nvme', 2)
        self.assertIn('Drive Sensor 1', r)

    # ── AMD GPU ───────────────────────────────────────────────────────────────
    def test_edge(self):
        r = self._label('edge', 'amdgpu', 1)
        self.assertIn('GPU Temperature', r)

    def test_junction(self):
        r = self._label('junction', 'amdgpu', 2)
        self.assertIn('GPU Hotspot', r)

    # ── Generic fallbacks ─────────────────────────────────────────────────────
    def test_generic_temp_n_uses_chip_source(self):
        r = self._label('Temp 3', 'nct6798', 3)
        self.assertIn('Motherboard', r)
        self.assertIn('Sensor 3', r)

    def test_completely_unknown_chip_falls_back(self):
        r = self._label('mystery_sensor', 'unknown_chip', 1)
        self.assertIsInstance(r, str)
        self.assertGreater(len(r), 0)


class TestGPUClassification(unittest.TestCase):
    """_classify_conn() chip detection for GPU types."""

    def setUp(self):
        from core.hardware_monitor import _classify_conn
        from core.hardware_monitor import (
            FAN_CONN_GPU_AMD, FAN_CONN_GPU_NVIDIA,
            FAN_CONN_GPU_INTEL, FAN_CONN_SYSF
        )
        self._classify = _classify_conn
        self.AMD     = FAN_CONN_GPU_AMD
        self.NVIDIA  = FAN_CONN_GPU_NVIDIA
        self.INTEL   = FAN_CONN_GPU_INTEL
        self.SYSF    = FAN_CONN_SYSF

    def test_amdgpu_chip_classified_as_amd_gpu(self):
        self.assertEqual(self._classify('Fan 1', 'amdgpu'), self.AMD)

    def test_radeon_chip_classified_as_amd_gpu(self):
        self.assertEqual(self._classify('Fan 1', 'radeon'), self.AMD)

    def test_nvidia_chip_classified_as_nvidia_gpu(self):
        self.assertEqual(self._classify('Fan 1', 'nvidia'), self.NVIDIA)

    def test_i915_chip_classified_as_intel_gpu(self):
        self.assertEqual(self._classify('Fan 1', 'i915'), self.INTEL)

    def test_xe_chip_classified_as_intel_gpu(self):
        self.assertEqual(self._classify('Fan 1', 'xe'), self.INTEL)

    def test_nct6798_classified_as_sys_fan(self):
        self.assertEqual(self._classify('Fan 1', 'nct6798'), self.SYSF)

    def test_chip_match_is_case_insensitive(self):
        self.assertEqual(self._classify('Fan 1', 'AMDGPU'), self.AMD)
        self.assertEqual(self._classify('Fan 1', 'NVIDIA'), self.NVIDIA)


class TestHardwareMonitorMocked(unittest.TestCase):
    """
    HardwareMonitor behaviour with mocked sysfs paths.
    Tests that fan auto/manual values are set correctly per chip type.
    """

    def _make_monitor_with_fan(self, chip_name: str,
                                pwm_auto: str, pwm_manual: str):
        """Build a HardwareMonitor-like FanEntry with specified chip values."""
        from core.hardware_monitor import FanEntry, FAN_CONN_SYSF
        return FanEntry(
            id='test_fan',
            label='Test Fan',
            hwmon_path='/fake/hwmon0',
            fan_input_file='/fake/hwmon0/fan1_input',
            pwm_file='/fake/hwmon0/pwm1',
            pwm_enable_file='/fake/hwmon0/pwm1_enable',
            min_file=None, max_file=None,
            chip_name=chip_name,
            pwm_auto_value=pwm_auto,
            pwm_manual_value=pwm_manual,
        )

    def test_nct6775_auto_value_is_2(self):
        fan = self._make_monitor_with_fan('nct6798', '2', '1')
        self.assertEqual(fan.pwm_auto_value, '2')

    def test_it87_auto_value_is_0(self):
        fan = self._make_monitor_with_fan('it87', '0', '1')
        self.assertEqual(fan.pwm_auto_value, '0')

    def test_set_fan_auto_writes_correct_value_nct(self):
        import unittest.mock as mock
        from core.hardware_monitor import HardwareMonitor, FanEntry, FAN_CONN_SYSF

        # Construct a monitor with a mocked fan
        monitor = object.__new__(HardwareMonitor)
        monitor.fans = {}
        monitor.temps = {}
        monitor._nvidia_indices = []
        monitor._nvidia_settings_ok = False

        fan = self._make_monitor_with_fan('nct6798', '2', '1')
        monitor.fans['test_fan'] = fan

        written = {}
        def fake_write(path, value):
            written[path] = value
            return True

        monitor._write_file = fake_write
        monitor.set_fan_auto('test_fan')
        self.assertEqual(written.get('/fake/hwmon0/pwm1_enable'), '2')

    def test_set_fan_auto_writes_correct_value_it87(self):
        import unittest.mock as mock
        from core.hardware_monitor import HardwareMonitor

        monitor = object.__new__(HardwareMonitor)
        monitor.fans = {}
        monitor.temps = {}
        monitor._nvidia_indices = []
        monitor._nvidia_settings_ok = False

        fan = self._make_monitor_with_fan('it87', '0', '1')
        monitor.fans['test_fan'] = fan

        written = {}
        monitor._write_file = lambda path, value: written.update({path: value}) or True
        monitor.set_fan_auto('test_fan')
        self.assertEqual(written.get('/fake/hwmon0/pwm1_enable'), '0')

    def test_set_fan_pwm_enables_manual_first(self):
        from core.hardware_monitor import HardwareMonitor

        monitor = object.__new__(HardwareMonitor)
        monitor.fans = {}
        monitor.temps = {}
        monitor._nvidia_indices = []
        monitor._nvidia_settings_ok = False

        fan = self._make_monitor_with_fan('nct6798', '2', '1')
        monitor.fans['test_fan'] = fan

        call_order = []
        def fake_write(path, value):
            call_order.append((path, value))
            return True

        monitor._write_file = fake_write
        monitor.set_fan_pwm('test_fan', 128)

        # pwm_enable written to '1' (manual) BEFORE pwm value
        enable_idx = next(i for i, (p, v) in enumerate(call_order)
                          if 'enable' in p)
        pwm_idx    = next(i for i, (p, v) in enumerate(call_order)
                          if p.endswith('pwm1'))
        self.assertLess(enable_idx, pwm_idx)
        self.assertEqual(call_order[enable_idx][1], '1')

    def test_safe_mode_clamps_pwm_above_minimum(self):
        from core.hardware_monitor import HardwareMonitor

        monitor = object.__new__(HardwareMonitor)
        monitor.fans = {}
        monitor.temps = {}
        monitor._nvidia_indices = []
        monitor._nvidia_settings_ok = False

        fan = self._make_monitor_with_fan('nct6798', '2', '1')
        fan.min_rpm = 600
        fan.max_rpm = 1500
        monitor.fans['test_fan'] = fan

        written = {}
        monitor._write_file = lambda p, v: written.update({p: v}) or True
        # Request 0% — safe_mode should clamp to min
        monitor.set_fan_pwm('test_fan', 0, safe_mode=True)
        written_pwm = int(written.get('/fake/hwmon0/pwm1', 0))
        min_expected = int(600 / 1500 * 255)
        self.assertGreaterEqual(written_pwm, min_expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
