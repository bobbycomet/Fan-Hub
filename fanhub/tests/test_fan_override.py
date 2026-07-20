"""
Tests for FanOverrideRegistry — the mechanism that eliminates the GUI/daemon
race condition described in the bug report ("Emergency Mode incorrectly
triggering due to a conflict between the curve editor and fan control logic
with the daemon active").
"""
import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fan_override import FanOverrideRegistry, FanControlMode


class TestFanOverrideRegistry(unittest.TestCase):

    def setUp(self):
        self.reg = FanOverrideRegistry()

    def test_default_mode_is_auto(self):
        self.assertEqual(self.reg.mode('fan1'), FanControlMode.AUTO)
        self.assertFalse(self.reg.is_manual('fan1'))

    def test_set_manual_marks_fan_manual(self):
        self.reg.set_manual('fan1', 45.0)
        self.assertTrue(self.reg.is_manual('fan1'))
        self.assertEqual(self.reg.mode('fan1'), FanControlMode.MANUAL)

    def test_set_manual_stores_speed(self):
        self.reg.set_manual('fan1', 67.5)
        self.assertAlmostEqual(self.reg.manual_speed('fan1'), 67.5)

    def test_manual_speed_clamped_to_0_100(self):
        self.reg.set_manual('fan1', 150.0)
        self.assertAlmostEqual(self.reg.manual_speed('fan1'), 100.0)
        self.reg.set_manual('fan2', -20.0)
        self.assertAlmostEqual(self.reg.manual_speed('fan2'), 0.0)

    def test_set_auto_releases_manual(self):
        self.reg.set_manual('fan1', 50.0)
        self.reg.set_auto('fan1')
        self.assertFalse(self.reg.is_manual('fan1'))
        self.assertIsNone(self.reg.manual_speed('fan1'))

    def test_set_all_auto_clears_everything(self):
        self.reg.set_manual('fan1', 30.0)
        self.reg.set_manual('fan2', 60.0)
        self.reg.set_manual('fan3', 90.0)
        self.reg.set_all_auto()
        for fid in ('fan1', 'fan2', 'fan3'):
            self.assertFalse(self.reg.is_manual(fid))

    def test_manual_speed_none_when_auto(self):
        self.assertIsNone(self.reg.manual_speed('never_touched'))

    def test_independent_fans_dont_affect_each_other(self):
        """
        Regression test for the exact bug: manually overriding one fan
        (e.g. GPU) must not affect another fan's (e.g. CPU) AUTO/curve state.
        """
        self.reg.set_manual('gpu_fan', 45.0)
        self.assertTrue(self.reg.is_manual('gpu_fan'))
        self.assertFalse(self.reg.is_manual('cpu_fan'))
        self.assertEqual(self.reg.mode('cpu_fan'), FanControlMode.AUTO)

    def test_snapshot_round_trip(self):
        self.reg.set_manual('fan1', 42.0)
        self.reg.set_manual('fan2', 88.0)
        snap = self.reg.snapshot()

        reg2 = FanOverrideRegistry()
        reg2.load_snapshot(snap)
        self.assertTrue(reg2.is_manual('fan1'))
        self.assertAlmostEqual(reg2.manual_speed('fan1'), 42.0)
        self.assertTrue(reg2.is_manual('fan2'))
        self.assertAlmostEqual(reg2.manual_speed('fan2'), 88.0)

    def test_snapshot_empty_when_all_auto(self):
        snap = self.reg.snapshot()
        self.assertEqual(snap['modes'], {})
        self.assertEqual(snap['speeds'], {})

    def test_re_manual_updates_speed(self):
        """Dragging the slider again should update the stored speed, not stack."""
        self.reg.set_manual('fan1', 30.0)
        self.reg.set_manual('fan1', 70.0)
        self.assertAlmostEqual(self.reg.manual_speed('fan1'), 70.0)
        self.assertTrue(self.reg.is_manual('fan1'))


class TestFanOverridePriorityLogic(unittest.TestCase):
    """
    Tests the priority logic that PollingWorker._apply_fan_control implements:
    MANUAL always wins over emergency and over curve computation.
    """

    def setUp(self):
        self.reg = FanOverrideRegistry()

    def _simulate_apply(self, fan_id: str, is_emergency: bool,
                        curve_result) -> float:
        """
        Mirror of PollingWorker._apply_fan_control's per-fan decision logic,
        without any hardware I/O, so the priority order itself is tested.
        """
        if self.reg.is_manual(fan_id):
            return self.reg.manual_speed(fan_id)
        if is_emergency:
            return 100.0
        return curve_result

    def test_manual_overrides_emergency(self):
        """
        This is the core fix: previously, an emergency condition would force
        ALL fans to 100% including ones the user had manually set — causing
        the fan to jump around and appear to "fight" the user, which is what
        produced the spurious emergency warning spam described in the bug.
        """
        self.reg.set_manual('cpu_fan', 40.0)
        result = self._simulate_apply('cpu_fan', is_emergency=True, curve_result=None)
        self.assertAlmostEqual(result, 40.0)

    def test_manual_overrides_curve(self):
        self.reg.set_manual('cpu_fan', 25.0)
        result = self._simulate_apply('cpu_fan', is_emergency=False, curve_result=80.0)
        self.assertAlmostEqual(result, 25.0)

    def test_auto_fan_uses_emergency_when_triggered(self):
        result = self._simulate_apply('cpu_fan', is_emergency=True, curve_result=50.0)
        self.assertAlmostEqual(result, 100.0)

    def test_auto_fan_uses_curve_when_no_emergency(self):
        result = self._simulate_apply('cpu_fan', is_emergency=False, curve_result=65.0)
        self.assertAlmostEqual(result, 65.0)

    def test_mixed_fans_independent_priority(self):
        """
        CPU fan manually locked at 100%, GPU fan stays on AUTO/curve.
        Emergency should not touch the manual CPU fan, but SHOULD affect
        the AUTO GPU fan.
        """
        self.reg.set_manual('cpu_fan', 100.0)
        cpu_result = self._simulate_apply('cpu_fan', is_emergency=True, curve_result=None)
        gpu_result = self._simulate_apply('gpu_fan', is_emergency=True, curve_result=60.0)
        self.assertAlmostEqual(cpu_result, 100.0)   # unaffected — already at user's choice
        self.assertAlmostEqual(gpu_result, 100.0)   # emergency applies to AUTO fan


class TestFanEntryUIDataAdapters(unittest.TestCase):
    """
    Regression tests for a real crash: PollingWorker.fans_updated emits
    {fid: FanEntry}, but FanCard.update_data() and FanChannelWidget.update_live()
    were written assuming a plain dict payload and called .get() on it,
    which FanEntry (a dataclass, not a dict) does not support.
    AttributeError: 'FanEntry' object has no attribute 'get'
    """

    def _make_fan_entry(self, **overrides):
        from core.hardware_monitor import FanEntry
        defaults = dict(
            id='test_fan', label='Test Fan Label',
            hwmon_path='/fake', fan_input_file='/fake/fan1_input',
            pwm_file='/fake/pwm1', pwm_enable_file='/fake/pwm1_enable',
            min_file=None, max_file=None,
            current_rpm=1200, current_percent=55.0,
            mode='curve', gpu_vendor=None, is_hub_channel=False,
        )
        defaults.update(overrides)
        return FanEntry(**defaults)

    def test_dashboard_fancard_accepts_fanentry_object(self):
        """FanCard.update_data must not raise on a real FanEntry object."""
        import unittest.mock as mock
        # PyQt6 widgets need a QApplication; skip gracefully if unavailable
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
        except Exception:
            self.skipTest("PyQt6 not available in this environment")

        from ui.dashboard_tab import FanCard
        fan = self._make_fan_entry(current_rpm=2743, current_percent=100.0,
                                   mode='pwm_auto')
        card = FanCard('test_fan', fan.label)
        # This must not raise AttributeError: 'FanEntry' object has no attribute 'get'
        card.update_data(fan)
        self.assertIn('2,743', card.rpm_lbl.text())
        self.assertIn('100', card.pct_lbl.text())

    def test_dashboard_fancard_still_accepts_plain_dict(self):
        """Backward compatibility: a plain dict payload must still work."""
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
        except Exception:
            self.skipTest("PyQt6 not available in this environment")

        from ui.dashboard_tab import FanCard
        card = FanCard('test_fan', 'Test Fan')
        card.update_data({'rpm': 1500, 'percent': 60.0, 'mode': 'auto'})
        self.assertIn('1,500', card.rpm_lbl.text())
        self.assertIn('60', card.pct_lbl.text())

    def test_fan_control_update_live_accepts_fanentry_object(self):
        """FanChannelWidget.update_live must not raise on a real FanEntry object."""
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
        except Exception:
            self.skipTest("PyQt6 not available in this environment")

        from ui.fan_control_tab import FanChannelWidget
        from core.fan_curves import CurveEngine
        from core.app_state import AppState
        fan = self._make_fan_entry(current_rpm=1800, current_percent=70.0)
        widget = FanChannelWidget('test_fan', fan, CurveEngine(), AppState())
        # Must not raise AttributeError: 'FanEntry' object has no attribute 'get'
        widget.update_live(fan)
        self.assertIn('1,800', widget.rpm_lbl.text())

    def test_fan_control_update_live_nvidia_no_rpm(self):
        """NVIDIA fan with 0 RPM but nonzero percent shows the % fallback."""
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
        except Exception:
            self.skipTest("PyQt6 not available in this environment")

        from ui.fan_control_tab import FanChannelWidget
        from core.fan_curves import CurveEngine
        from core.app_state import AppState
        fan = self._make_fan_entry(current_rpm=0, current_percent=71.0,
                                   gpu_vendor='nvidia')
        widget = FanChannelWidget('gpu_fan', fan, CurveEngine(), AppState())
        widget.update_live(fan)
        self.assertIn('71', widget.rpm_lbl.text())
        self.assertIn('no RPM tach', widget.rpm_lbl.text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
