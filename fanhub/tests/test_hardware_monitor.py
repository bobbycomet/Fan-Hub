"""
Unit tests for HardwareMonitor label translation and GPU classification.
Uses mocks — no real /sys/class/hwmon is read.
"""
import sys, os, shutil, unittest
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
        # AUXTIN0 on most Nuvoton boards = VRM — prefixed with source for context
        self.assertIn('VRM', r)

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
        self.assertIn('CPU CCD 1', r)

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
        # Temp 3 on nct6798 is now identified as VRM by position table
        r = self._label('Temp 3', 'nct6798', 3)
        self.assertIn('VRM', r)

    def test_generic_temp_unknown_position(self):
        # Beyond known positions → Auxiliary Sensor N
        r = self._label('Temp 9', 'nct6798', 9)
        self.assertIn('Auxiliary', r)

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


class TestPWMInversion(unittest.TestCase):
    """
    Regression tests for the inverted-PWM bug: on some it87/IT8686E boards
    (e.g. certain Gigabyte AM4 boards), writing PWM=255 (100% requested)
    spins the fan at MINIMUM speed, and PWM=0 spins it at MAXIMUM — the
    opposite of every other board. fan.pwm_inverted corrects this at the
    write/read boundary while keeping all logical values (current_pwm,
    current_percent, curve engine targets) in normal 0=off/255=full terms.
    """

    def _make_fan(self, inverted: bool):
        from core.hardware_monitor import FanEntry
        return FanEntry(
            id='test_fan',
            label='Test Fan',
            hwmon_path='/fake/hwmon0',
            fan_input_file='/fake/hwmon0/fan1_input',
            pwm_file='/fake/hwmon0/pwm1',
            pwm_enable_file='/fake/hwmon0/pwm1_enable',
            min_file=None, max_file=None,
            chip_name='it8686',
            pwm_auto_value='0', pwm_manual_value='1',
            pwm_inverted=inverted,
        )

    def _make_monitor(self, fan):
        from core.hardware_monitor import HardwareMonitor
        monitor = object.__new__(HardwareMonitor)
        monitor.fans = {'test_fan': fan}
        monitor.temps = {}
        monitor._nvidia_indices = []
        monitor._nvidia_settings_ok = False
        return monitor

    def test_normal_fan_writes_pwm_as_is(self):
        """Sanity check: non-inverted fan writes the requested PWM unchanged."""
        fan = self._make_fan(inverted=False)
        monitor = self._make_monitor(fan)
        written = {}
        monitor._write_file = lambda p, v: written.update({p: v}) or True
        monitor.set_fan_pwm('test_fan', 255)  # request 100%
        self.assertEqual(written['/fake/hwmon0/pwm1'], '255')
        self.assertEqual(fan.current_pwm, 255)
        self.assertAlmostEqual(fan.current_percent, 100.0)

    def test_inverted_fan_writes_255_minus_pwm(self):
        """
        The actual bug: requesting 100% (255) on an inverted board must
        write 0 to hardware (so the fan actually spins at 100%).
        """
        fan = self._make_fan(inverted=True)
        monitor = self._make_monitor(fan)
        written = {}
        monitor._write_file = lambda p, v: written.update({p: v}) or True
        monitor.set_fan_pwm('test_fan', 255)  # request 100%
        # Hardware byte must be inverted...
        self.assertEqual(written['/fake/hwmon0/pwm1'], '0')
        # ...but the LOGICAL value the rest of Fan Hub sees stays at 100%
        self.assertEqual(fan.current_pwm, 255)
        self.assertAlmostEqual(fan.current_percent, 100.0)

    def test_inverted_fan_0_percent_writes_255_to_hardware(self):
        fan = self._make_fan(inverted=True)
        monitor = self._make_monitor(fan)
        written = {}
        monitor._write_file = lambda p, v: written.update({p: v}) or True
        monitor.set_fan_pwm('test_fan', 0)  # request 0%
        self.assertEqual(written['/fake/hwmon0/pwm1'], '255')
        self.assertEqual(fan.current_pwm, 0)
        self.assertAlmostEqual(fan.current_percent, 0.0)

    def test_inverted_fan_midpoint_symmetric(self):
        fan = self._make_fan(inverted=True)
        monitor = self._make_monitor(fan)
        written = {}
        monitor._write_file = lambda p, v: written.update({p: v}) or True
        monitor.set_fan_pwm('test_fan', 128)  # ~50%
        self.assertEqual(written['/fake/hwmon0/pwm1'], str(255 - 128))
        self.assertEqual(fan.current_pwm, 128)

    def test_inverted_readback_un_inverts_for_display(self):
        """
        When reading PWM back from sysfs, an inverted fan showing raw byte 0
        (hardware at max speed) must be reported as current_percent=100,
        not 0 — otherwise the UI would show the fan as "off" while it's
        actually running at full speed (the exact symptom reported).
        """
        fan = self._make_fan(inverted=True)
        monitor = self._make_monitor(fan)
        # Simulate hardware currently at raw byte 0 (== fan spinning at 100%
        # on this inverted board)
        monitor._read_file = lambda p: '0' if 'pwm1' in p and 'enable' not in p else None
        monitor.fans['test_fan'].fan_input_file = None  # skip RPM read path
        monitor.read_all_fans()
        self.assertEqual(fan.current_pwm, 255)
        self.assertAlmostEqual(fan.current_percent, 100.0)

    def test_non_inverted_readback_matches_raw(self):
        fan = self._make_fan(inverted=False)
        monitor = self._make_monitor(fan)
        monitor._read_file = lambda p: '128' if 'pwm1' in p and 'enable' not in p else None
        monitor.fans['test_fan'].fan_input_file = None
        monitor.read_all_fans()
        self.assertEqual(fan.current_pwm, 128)

    def test_apply_inverted_flags_from_config(self):
        """Config-loaded inversion map correctly sets the flag on matching fans."""
        from core.hardware_monitor import HardwareMonitor
        fan_a = self._make_fan(inverted=False)
        fan_a.id = 'fan_a'
        fan_b = self._make_fan(inverted=False)
        fan_b.id = 'fan_b'
        monitor = object.__new__(HardwareMonitor)
        monitor.fans = {'fan_a': fan_a, 'fan_b': fan_b}
        monitor.apply_inverted_flags({'fan_a': True})
        self.assertTrue(monitor.fans['fan_a'].pwm_inverted)
        self.assertFalse(monitor.fans['fan_b'].pwm_inverted)

    def test_unknown_fan_id_in_flags_ignored_safely(self):
        from core.hardware_monitor import HardwareMonitor
        fan_a = self._make_fan(inverted=False)
        monitor = object.__new__(HardwareMonitor)
        monitor.fans = {'fan_a': fan_a}
        # Should not raise even though 'ghost_fan' doesn't exist
        monitor.apply_inverted_flags({'ghost_fan': True})
        self.assertFalse(monitor.fans['fan_a'].pwm_inverted)

    def test_set_pwm_inverted_toggle(self):
        from core.hardware_monitor import HardwareMonitor
        fan_a = self._make_fan(inverted=False)
        monitor = object.__new__(HardwareMonitor)
        monitor.fans = {'fan_a': fan_a}
        monitor.set_pwm_inverted('fan_a', True)
        self.assertTrue(fan_a.pwm_inverted)
        monitor.set_pwm_inverted('fan_a', False)
        self.assertFalse(fan_a.pwm_inverted)


class TestMirrorChipSuppression(unittest.TestCase):
    """
    Regression tests for duplicate sensor readouts: some boards expose the
    SAME physical EC/SuperIO thermal sensors through TWO hwmon chips (e.g.
    it8686 directly, and gigabyte_wmi mirroring the identical registers for
    Windows-tool compatibility). Without suppression this produced visibly
    duplicate temperature cards with identical values under different labels.
    """

    def _build_fake_hwmon_tree(self, chips: dict):
        """chips: {dirname: (chip_name, {sensor_num: value_celsius})}"""
        import tempfile
        tmpdir = tempfile.mkdtemp()
        hwmon_base = os.path.join(tmpdir, 'hwmon')
        for dirname, (chip_name, temps) in chips.items():
            d = os.path.join(hwmon_base, dirname)
            os.makedirs(d)
            with open(os.path.join(d, 'name'), 'w') as f:
                f.write(chip_name)
            for n, val in temps.items():
                with open(os.path.join(d, f'temp{n}_input'), 'w') as f:
                    f.write(str(int(val * 1000)))
        return tmpdir, hwmon_base

    def _discover(self, hwmon_base):
        import core.hardware_monitor as hwm
        original_base = hwm.HWMON_BASE
        hwm.HWMON_BASE = hwmon_base
        try:
            monitor = object.__new__(hwm.HardwareMonitor)
            monitor.temps = {}
            monitor._discover_hwmon_temps()
            return monitor.temps
        finally:
            hwm.HWMON_BASE = original_base

    def test_gigabyte_wmi_suppressed_when_it8686_present(self):
        tmpdir, base = self._build_fake_hwmon_tree({
            'hwmon0': ('it8686', {1: 30.0, 2: 36.0, 3: 49.0, 4: 17.0}),
            'hwmon1': ('gigabyte_wmi', {1: 30.0, 2: 36.0, 3: 49.0, 4: 17.0}),
        })
        try:
            temps = self._discover(base)
            # Only the primary it8686 chip's 4 sensors should be present —
            # the gigabyte_wmi mirror must be suppressed entirely.
            self.assertEqual(len(temps), 4)
            for sid in temps:
                self.assertTrue(sid.startswith('hwmon0_'),
                                msg=f"Unexpected sensor from mirror chip: {sid}")
        finally:
            shutil.rmtree(tmpdir)

    def test_gigabyte_wmi_kept_when_no_superio_present(self):
        """If gigabyte_wmi is the ONLY thermal source, it must not be suppressed."""
        tmpdir, base = self._build_fake_hwmon_tree({
            'hwmon0': ('gigabyte_wmi', {1: 30.0, 2: 36.0}),
        })
        try:
            temps = self._discover(base)
            self.assertEqual(len(temps), 2)
        finally:
            shutil.rmtree(tmpdir)

    def test_unrelated_chips_not_suppressed(self):
        """A k10temp CPU sensor alongside it8686 must not be affected."""
        tmpdir, base = self._build_fake_hwmon_tree({
            'hwmon0': ('it8686',  {1: 30.0}),
            'hwmon1': ('k10temp', {1: 55.0}),
        })
        try:
            temps = self._discover(base)
            self.assertEqual(len(temps), 2)
        finally:
            shutil.rmtree(tmpdir)

    def test_wifi_adapter_not_split_into_two_line_label(self):
        """
        Regression: mt7921_phy0 had no position-table entry, so it fell
        through to the generic 'Source — Temp N' fallback, which the UI
        splits into two lines ('Wi-Fi Adapter' / 'Temp 1'). It must now
        produce a single clean label with no ' — ' separator.
        """
        from core.hardware_monitor import _friendly_temp_label
        label = _friendly_temp_label('Temp 1', 'mt7921_phy0', 1)
        self.assertNotIn(' — ', label)
        self.assertEqual(label, 'Wi-Fi Adapter Temperature')


class TestNvidiaTempLabelDeduplication(unittest.TestCase):
    """
    Regression test: nvidia-smi's --query-gpu=name often already returns
    "NVIDIA GeForce RTX 2060", and the temp-sensor label builder used to
    blindly prepend "NVIDIA " again, producing
    "NVIDIA NVIDIA GeForce RTX 2060 (GPU 0)".
    """

    def test_name_with_nvidia_prefix_not_doubled(self):
        name = "NVIDIA GeForce RTX 2060"
        clean = name.strip()
        if clean.upper().startswith('NVIDIA '):
            clean = clean[7:].strip()
        label = f"NVIDIA {clean} (GPU 0)"
        self.assertEqual(label, "NVIDIA GeForce RTX 2060 (GPU 0)")
        self.assertEqual(label.count('NVIDIA'), 1)

    def test_name_without_nvidia_prefix_gets_one(self):
        name = "GeForce RTX 3080"
        clean = name.strip()
        if clean.upper().startswith('NVIDIA '):
            clean = clean[7:].strip()
        label = f"NVIDIA {clean} (GPU 0)"
        self.assertEqual(label, "NVIDIA GeForce RTX 3080 (GPU 0)")
        self.assertEqual(label.count('NVIDIA'), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
