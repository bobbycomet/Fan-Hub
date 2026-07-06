"""
Unit tests for CurveEngine, FanCurve, and BlendMode.
Run with:  python3 -m pytest tests/  (from the fanhub/ directory)
           python3 -m unittest tests.test_fan_curves  (no pytest needed)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from core.fan_curves import (
    FanCurve, CurvePoint, CurveEngine, ProfileManager,
    PRESET_CURVES, BlendMode
)


class TestFanCurveInterpolate(unittest.TestCase):
    """FanCurve.interpolate() — pure arithmetic, no I/O."""

    def _curve(self, points, min_speed=0.0, max_speed=100.0, stop_below=None):
        c = FanCurve(name='test', min_speed=min_speed,
                     max_speed=max_speed, stop_below=stop_below)
        c.points = [CurvePoint(t, s) for t, s in points]
        return c

    def test_below_first_point_returns_first_speed(self):
        c = self._curve([(30, 20), (60, 80)])
        self.assertAlmostEqual(c.interpolate(10), 20.0)

    def test_above_last_point_returns_last_speed(self):
        c = self._curve([(30, 20), (60, 80)])
        self.assertAlmostEqual(c.interpolate(90), 80.0)

    def test_exact_point_returns_that_speed(self):
        c = self._curve([(30, 20), (60, 80)])
        self.assertAlmostEqual(c.interpolate(30), 20.0)
        self.assertAlmostEqual(c.interpolate(60), 80.0)

    def test_midpoint_is_linearly_interpolated(self):
        c = self._curve([(0, 0), (100, 100)])
        self.assertAlmostEqual(c.interpolate(50), 50.0, places=1)

    def test_interpolation_between_arbitrary_points(self):
        c = self._curve([(40, 20), (80, 60)])
        # At temp 60 (midpoint): speed = 20 + (60-40)/(80-40) * (60-20) = 40
        self.assertAlmostEqual(c.interpolate(60), 40.0, places=1)

    def test_min_speed_clamps_output(self):
        c = self._curve([(0, 0), (100, 100)], min_speed=30.0)
        self.assertAlmostEqual(c.interpolate(10), 30.0)

    def test_max_speed_clamps_output(self):
        c = self._curve([(0, 50), (100, 100)], max_speed=70.0)
        self.assertAlmostEqual(c.interpolate(100), 70.0)

    def test_stop_below_overrides_min_speed(self):
        """stop_below must return 0 even when min_speed > 0 — the fix from v1.5.4."""
        c = self._curve([(20, 30), (80, 100)], min_speed=20.0, stop_below=35.0)
        # Below stop_below threshold → should be 0, not clamped by min_speed
        self.assertAlmostEqual(c.interpolate(30), 0.0)

    def test_above_stop_below_uses_curve(self):
        c = self._curve([(20, 30), (80, 100)], min_speed=20.0, stop_below=25.0)
        self.assertGreater(c.interpolate(50), 0.0)

    def test_empty_points_returns_fallback(self):
        c = FanCurve(name='empty')
        self.assertAlmostEqual(c.interpolate(50), 50.0)

    def test_single_point_curve_extrapolates_flat(self):
        c = self._curve([(50, 75)])
        self.assertAlmostEqual(c.interpolate(10), 75.0)
        self.assertAlmostEqual(c.interpolate(90), 75.0)

    def test_unsorted_points_are_handled(self):
        c = FanCurve(name='unsorted')
        c.points = [CurvePoint(80, 100), CurvePoint(30, 20), CurvePoint(55, 60)]
        self.assertAlmostEqual(c.interpolate(30), 20.0)
        self.assertAlmostEqual(c.interpolate(80), 100.0)
        # Midpoint 55 → 60
        self.assertAlmostEqual(c.interpolate(55), 60.0, places=1)

    def test_preset_curves_are_monotone(self):
        """All preset curves must produce non-decreasing speed as temp rises."""
        for name, curve in PRESET_CURVES.items():
            speeds = [curve.interpolate(t) for t in range(20, 101, 5)]
            for i in range(len(speeds) - 1):
                self.assertLessEqual(
                    speeds[i], speeds[i + 1] + 0.5,
                    msg=f"Preset '{name}' is not monotone at index {i}: "
                        f"{speeds[i]:.1f} > {speeds[i+1]:.1f}"
                )


class TestFanCurveBlendMode(unittest.TestCase):
    """FanCurve._drive_temp() blend mode logic."""

    def _curve_with_sensors(self, sensor_ids=None, weights=None,
                             blend=BlendMode.HIGHEST, single_sensor=None):
        c = FanCurve(name='blend_test',
                     points=[CurvePoint(0, 0), CurvePoint(100, 100)])
        c.sensor_id      = single_sensor
        c.sensor_ids     = sensor_ids or []
        c.sensor_weights = weights or []
        c.blend_mode     = blend
        return c

    def test_highest_selects_max(self):
        c = self._curve_with_sensors(blend=BlendMode.HIGHEST)
        temps = {'cpu': 70.0, 'gpu': 85.0, 'mb': 40.0}
        self.assertAlmostEqual(c._drive_temp(temps), 85.0)

    def test_average_returns_mean(self):
        c = self._curve_with_sensors(blend=BlendMode.AVERAGE)
        temps = {'a': 60.0, 'b': 80.0}
        self.assertAlmostEqual(c._drive_temp(temps), 70.0)

    def test_single_sensor_used_when_specified(self):
        c = self._curve_with_sensors(single_sensor='gpu')
        temps = {'cpu': 90.0, 'gpu': 55.0}
        self.assertAlmostEqual(c._drive_temp(temps), 55.0)

    def test_single_sensor_falls_back_to_highest_when_missing(self):
        c = self._curve_with_sensors(single_sensor='missing_sensor')
        temps = {'cpu': 70.0, 'gpu': 80.0}
        self.assertAlmostEqual(c._drive_temp(temps), 80.0)

    def test_sensor_ids_filter_pool(self):
        c = self._curve_with_sensors(
            sensor_ids=['a', 'b'], blend=BlendMode.HIGHEST)
        temps = {'a': 60.0, 'b': 50.0, 'c': 99.0}
        # 'c' excluded from pool → max of a,b = 60
        self.assertAlmostEqual(c._drive_temp(temps), 60.0)

    def test_empty_temps_returns_fallback(self):
        c = self._curve_with_sensors()
        self.assertAlmostEqual(c._drive_temp({}), 25.0)

    def test_weighted_blend(self):
        c = self._curve_with_sensors(
            sensor_ids=['cpu', 'gpu'],
            weights=[0.3, 0.7],
            blend=BlendMode.WEIGHTED)
        temps = {'cpu': 60.0, 'gpu': 80.0}
        # 60*0.3 + 80*0.7 = 18 + 56 = 74
        self.assertAlmostEqual(c._drive_temp(temps), 74.0, places=1)


class TestCurveEngine(unittest.TestCase):
    """CurveEngine.compute_speed() — assignment, hysteresis, emergency."""

    def setUp(self):
        self.engine = CurveEngine(hysteresis_global=2.0, emergency_temp=90.0)

    def test_no_assignment_returns_none(self):
        result = self.engine.compute_speed('fan1', {'cpu': 50.0})
        self.assertIsNone(result)

    def test_fixed_speed_returned_directly(self):
        self.engine.assign_fixed('fan1', 55.0)
        result = self.engine.compute_speed('fan1', {'cpu': 50.0})
        self.assertAlmostEqual(result, 55.0)

    def test_curve_assignment_drives_from_temp(self):
        self.engine.assign_curve('fan1', 'full_speed')
        result = self.engine.compute_speed('fan1', {'cpu': 50.0})
        self.assertAlmostEqual(result, 100.0)

    def test_emergency_override_at_threshold(self):
        # No assignment — but emergency kicks in
        result = self.engine.compute_speed('fan1', {'cpu': 90.0})
        self.assertAlmostEqual(result, 100.0)

    def test_emergency_active_flag_set(self):
        self.engine.compute_speed('fan1', {'cpu': 95.0})
        self.assertTrue(self.engine.emergency_active)

    def test_emergency_active_flag_cleared_below(self):
        self.engine.compute_speed('fan1', {'cpu': 95.0})
        self.engine.assign_curve('fan1', 'balanced')
        self.engine.compute_speed('fan1', {'cpu': 50.0})
        self.assertFalse(self.engine.emergency_active)

    def test_hysteresis_holds_speed_on_small_increase(self):
        self.engine.assign_curve('fan1', 'balanced')
        # Warm up _last_speed at a flat part of the curve
        self.engine.compute_speed('fan1', {'cpu': 60.0})
        speed1 = self.engine._last_speed.get('fan1', 0)
        # A 0.3°C rise is < hysteresis*0.5 (1.0°C gate) → speed held
        speed2 = self.engine.compute_speed('fan1', {'cpu': 60.3})
        self.assertAlmostEqual(speed1, speed2, places=1)

    def test_hysteresis_blocks_small_decrease(self):
        self.engine.assign_curve('fan1', 'balanced')
        self.engine.compute_speed('fan1', {'cpu': 70.0})
        last = self.engine._last_speed['fan1']
        # A 0.5°C drop is < hysteresis (2.0°C) → speed must be held
        result = self.engine.compute_speed('fan1', {'cpu': 69.5})
        self.assertAlmostEqual(result, last, places=1)

    def test_assign_fixed_clears_curve(self):
        self.engine.assign_curve('fan1', 'balanced')
        self.engine.assign_fixed('fan1', 42.0)
        self.assertNotIn('fan1', self.engine.fan_assignments)
        self.assertIn('fan1', self.engine.fixed_speeds)

    def test_assign_curve_clears_fixed(self):
        self.engine.assign_fixed('fan1', 42.0)
        self.engine.assign_curve('fan1', 'balanced')
        self.assertNotIn('fan1', self.engine.fixed_speeds)
        self.assertIn('fan1', self.engine.fan_assignments)

    def test_unknown_curve_id_returns_none(self):
        self.engine.fan_assignments['fan1'] = 'nonexistent_curve'
        result = self.engine.compute_speed('fan1', {'cpu': 50.0})
        self.assertIsNone(result)

    def test_to_dict_round_trips(self):
        self.engine.assign_curve('fan1', 'balanced')
        self.engine.assign_fixed('fan2', 75.0)
        d = self.engine.to_dict()
        e2 = CurveEngine()
        e2.load_dict(d)
        self.assertEqual(e2.fan_assignments.get('fan1'), 'balanced')
        self.assertAlmostEqual(e2.fixed_speeds.get('fan2'), 75.0)

    def test_load_dict_updates_in_place(self):
        """load_dict must update dicts in-place, not replace references."""
        old_assignments = self.engine.fan_assignments
        old_fixed       = self.engine.fixed_speeds
        self.engine.load_dict({'fan_assignments': {'fan1': 'gaming'},
                               'fixed_speeds':    {'fan2': 30.0}})
        # Same object identity — external references still valid
        self.assertIs(self.engine.fan_assignments, old_assignments)
        self.assertIs(self.engine.fixed_speeds, old_fixed)
        self.assertEqual(old_assignments.get('fan1'), 'gaming')


class TestFanCurveSerialization(unittest.TestCase):
    """FanCurve.to_dict() / from_dict() round-trips."""

    def _make_curve(self):
        c = FanCurve(
            name='roundtrip_test',
            sensor_id='cpu_sensor',
            sensor_ids=['cpu_sensor', 'gpu_sensor'],
            sensor_weights=[0.4, 0.6],
            blend_mode=BlendMode.WEIGHTED,
            hysteresis=3.0,
            min_speed=15.0,
            max_speed=95.0,
            stop_below=30.0,
        )
        c.points = [CurvePoint(30, 20), CurvePoint(70, 80), CurvePoint(90, 100)]
        return c

    def test_round_trip_preserves_all_fields(self):
        original = self._make_curve()
        restored = FanCurve.from_dict(original.to_dict())

        self.assertEqual(restored.name, original.name)
        self.assertEqual(restored.sensor_id, original.sensor_id)
        self.assertEqual(restored.sensor_ids, original.sensor_ids)
        self.assertAlmostEqual(restored.sensor_weights[0], original.sensor_weights[0])
        self.assertEqual(restored.blend_mode, original.blend_mode)
        self.assertAlmostEqual(restored.hysteresis, original.hysteresis)
        self.assertAlmostEqual(restored.min_speed, original.min_speed)
        self.assertAlmostEqual(restored.max_speed, original.max_speed)
        self.assertAlmostEqual(restored.stop_below, original.stop_below)
        self.assertEqual(len(restored.points), len(original.points))
        for op, rp in zip(original.points, restored.points):
            self.assertAlmostEqual(op.temp, rp.temp)
            self.assertAlmostEqual(op.speed, rp.speed)

    def test_from_dict_handles_missing_blend_fields(self):
        """Old profiles without blend_mode/sensor_ids load safely."""
        d = {
            'name': 'legacy',
            'points': [{'temp': 30, 'speed': 20}],
            'sensor_id': 'cpu',
            'hysteresis': 2.0,
            'min_speed': 0.0,
            'max_speed': 100.0,
        }
        c = FanCurve.from_dict(d)
        self.assertEqual(c.blend_mode, BlendMode.HIGHEST)
        self.assertEqual(c.sensor_ids, [])
        self.assertEqual(c.sensor_id, 'cpu')

    def test_from_dict_handles_invalid_blend_mode(self):
        d = {'name': 'bad_blend', 'blend_mode': 'invalid_value', 'points': []}
        c = FanCurve.from_dict(d)
        self.assertEqual(c.blend_mode, BlendMode.HIGHEST)


if __name__ == '__main__':
    unittest.main(verbosity=2)
