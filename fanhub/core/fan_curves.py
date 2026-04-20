"""
Fan Curve Engine
- Interpolated fan curves (temp -> % speed)
- Hysteresis to prevent rapid oscillation
- Heuristic presets (silent, balanced, performance, gaming)
- Profile persistence
- Emergency override
"""
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger('fanhub.curves')


@dataclass
class CurvePoint:
    temp: float   # °C
    speed: float  # % (0-100)


@dataclass
class FanCurve:
    """A fan curve is a list of (temp, speed%) points, interpolated."""
    name: str
    points: List[CurvePoint] = field(default_factory=list)
    sensor_id: Optional[str] = None    # Which temp sensor drives this curve
    hysteresis: float = 2.0            # °C
    min_speed: float = 0.0             # Minimum allowed % (safety)
    max_speed: float = 100.0
    stop_below: Optional[float] = None # °C below which fan fully stops (0-RPM)

    def interpolate(self, temp: float) -> float:
        """Return interpolated speed % for given temperature."""
        if not self.points:
            return 50.0

        sorted_pts = sorted(self.points, key=lambda p: p.temp)

        if temp <= sorted_pts[0].temp:
            speed = sorted_pts[0].speed
        elif temp >= sorted_pts[-1].temp:
            speed = sorted_pts[-1].speed
        else:
            for i in range(len(sorted_pts) - 1):
                p1, p2 = sorted_pts[i], sorted_pts[i + 1]
                if p1.temp <= temp <= p2.temp:
                    ratio = (temp - p1.temp) / (p2.temp - p1.temp)
                    speed = p1.speed + ratio * (p2.speed - p1.speed)
                    break
            else:
                speed = 50.0

        # Apply stop-below
        if self.stop_below is not None and temp < self.stop_below:
            speed = 0.0

        return max(self.min_speed, min(self.max_speed, speed))

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'points': [{'temp': p.temp, 'speed': p.speed} for p in self.points],
            'sensor_id': self.sensor_id,
            'hysteresis': self.hysteresis,
            'min_speed': self.min_speed,
            'max_speed': self.max_speed,
            'stop_below': self.stop_below,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'FanCurve':
        curve = cls(
            name=d.get('name', 'Custom'),
            sensor_id=d.get('sensor_id'),
            hysteresis=d.get('hysteresis', 2.0),
            min_speed=d.get('min_speed', 0.0),
            max_speed=d.get('max_speed', 100.0),
            stop_below=d.get('stop_below'),
        )
        for p in d.get('points', []):
            curve.points.append(CurvePoint(p['temp'], p['speed']))
        return curve


# ── Preset curves ─────────────────────────────────────────────────────────────

PRESET_CURVES = {
    'silent': FanCurve(
        name='Silent',
        points=[
            CurvePoint(30, 0),
            CurvePoint(40, 15),
            CurvePoint(55, 30),
            CurvePoint(65, 50),
            CurvePoint(75, 75),
            CurvePoint(85, 100),
        ],
        hysteresis=3.0,
        min_speed=0.0,
        stop_below=35.0,
    ),
    'balanced': FanCurve(
        name='Balanced',
        points=[
            CurvePoint(30, 20),
            CurvePoint(45, 30),
            CurvePoint(60, 50),
            CurvePoint(70, 70),
            CurvePoint(80, 90),
            CurvePoint(85, 100),
        ],
        hysteresis=2.0,
        min_speed=20.0,
    ),
    'performance': FanCurve(
        name='Performance',
        points=[
            CurvePoint(30, 40),
            CurvePoint(50, 55),
            CurvePoint(65, 75),
            CurvePoint(75, 90),
            CurvePoint(80, 100),
        ],
        hysteresis=1.0,
        min_speed=40.0,
    ),
    'gaming': FanCurve(
        name='Gaming',
        points=[
            CurvePoint(30, 30),
            CurvePoint(55, 50),
            CurvePoint(70, 80),
            CurvePoint(80, 100),
        ],
        hysteresis=2.0,
        min_speed=30.0,
    ),
    'full_speed': FanCurve(
        name='Full Speed',
        points=[
            CurvePoint(0, 100),
            CurvePoint(100, 100),
        ],
        hysteresis=0.0,
        min_speed=100.0,
    ),
    'fixed_30': FanCurve(
        name='Fixed 30%',
        points=[CurvePoint(0, 30), CurvePoint(100, 30)],
        min_speed=30.0,
        max_speed=30.0,
    ),
    'fixed_50': FanCurve(
        name='Fixed 50%',
        points=[CurvePoint(0, 50), CurvePoint(100, 50)],
        min_speed=50.0,
        max_speed=50.0,
    ),
}


class CurveEngine:
    """
    Manages fan curve assignments and applies them.
    Handles hysteresis, emergency overrides, and profile-level logic.
    """

    def __init__(self, hysteresis_global: float = 2.0, emergency_temp: float = 90.0):
        self.curves: Dict[str, FanCurve] = {}         # curve_id -> FanCurve
        self.fan_assignments: Dict[str, str] = {}      # fan_id -> curve_id
        self.fixed_speeds: Dict[str, float] = {}       # fan_id -> fixed %
        self._last_speed: Dict[str, float] = {}        # fan_id -> last applied %
        self._last_temp: Dict[str, float] = {}         # sensor_id -> last temp
        self.hysteresis_global = hysteresis_global
        self.emergency_temp = emergency_temp
        self.emergency_active = False

        # Load presets
        for k, v in PRESET_CURVES.items():
            self.curves[k] = v

    def assign_curve(self, fan_id: str, curve_id: str):
        self.fan_assignments[fan_id] = curve_id
        self.fixed_speeds.pop(fan_id, None)

    def assign_fixed(self, fan_id: str, percent: float):
        self.fixed_speeds[fan_id] = max(0.0, min(100.0, percent))
        self.fan_assignments.pop(fan_id, None)

    def add_custom_curve(self, curve: FanCurve):
        self.curves[curve.name] = curve

    def compute_speed(self, fan_id: str, temps: Dict[str, float]) -> Optional[float]:
        """
        Compute the target speed % for a fan given current temperatures.
        Returns None if fan should be in auto mode.
        """
        # Emergency override
        max_temp = max(temps.values()) if temps else 0
        if max_temp >= self.emergency_temp:
            self.emergency_active = True
            logger.warning(f"EMERGENCY: temp {max_temp}°C >= {self.emergency_temp}°C — 100% fans")
            return 100.0
        else:
            self.emergency_active = False

        # Fixed speed
        if fan_id in self.fixed_speeds:
            return self.fixed_speeds[fan_id]

        # Curve assignment
        curve_id = self.fan_assignments.get(fan_id)
        if not curve_id:
            return None  # No assignment = auto

        curve = self.curves.get(curve_id)
        if not curve:
            return None

        # Get driving sensor temp
        sensor_id = curve.sensor_id
        if sensor_id and sensor_id in temps:
            temp = temps[sensor_id]
        else:
            # Use highest temp
            temp = max(temps.values()) if temps else 25.0

        target = curve.interpolate(temp)

        # Apply hysteresis
        hysteresis = curve.hysteresis or self.hysteresis_global
        last = self._last_speed.get(fan_id)
        if last is not None:
            if abs(target - last) < hysteresis * 0.5:
                # Small change — hold current speed
                target = last
            elif target > last:
                # Increasing — respond fully
                pass
            else:
                # Decreasing — apply hysteresis (only decrease if diff > threshold)
                if (last - target) < hysteresis:
                    target = last

        self._last_speed[fan_id] = target
        return target

    def to_dict(self) -> dict:
        return {
            'custom_curves': {
                k: v.to_dict() for k, v in self.curves.items()
                if k not in PRESET_CURVES
            },
            'fan_assignments': self.fan_assignments,
            'fixed_speeds': self.fixed_speeds,
        }

    def load_dict(self, d: dict):
        for k, v in d.get('custom_curves', {}).items():
            self.curves[k] = FanCurve.from_dict(v)
        self.fan_assignments = d.get('fan_assignments', {})
        self.fixed_speeds = d.get('fixed_speeds', {})


class ProfileManager:
    """Manages named profiles that capture all fan + RGB + curve settings."""

    def __init__(self, state):
        self.state = state

    def save_profile(self, name: str, engine: CurveEngine, rgb_settings: dict = None) -> dict:
        profile = {
            'name': name,
            'curves': engine.to_dict(),
            'rgb': rgb_settings or {},
        }
        self.state.save_profile(name, profile)
        return profile

    def load_profile(self, name: str, engine: CurveEngine) -> bool:
        profile = self.state.get_profile(name)
        if not profile:
            return False
        engine.load_dict(profile.get('curves', {}))
        self.state.active_profile = name
        self.state.save_config()
        logger.info(f"Loaded profile: {name}")
        return True

    def list_profiles(self) -> List[str]:
        return list(self.state.profiles.keys())

    def delete_profile(self, name: str):
        self.state.delete_profile(name)
