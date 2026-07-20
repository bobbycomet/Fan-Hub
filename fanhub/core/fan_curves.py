"""
Fan Curve Engine v1.5.4
- Multi-sensor input: max, average, or weighted blend
- Interpolated fan curves (temp -> % speed)
- Hysteresis to prevent rapid oscillation
- Heuristic presets (silent, balanced, performance, gaming)
- Profile persistence
- Emergency override
"""
import logging
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger('fanhub.curves')


class BlendMode(str, Enum):
    HIGHEST  = 'highest'   # use the single hottest sensor (original behaviour)
    AVERAGE  = 'average'   # arithmetic mean of selected sensors
    WEIGHTED = 'weighted'  # weighted average (weights sum to 1.0)


@dataclass
class CurvePoint:
    temp: float   # °C
    speed: float  # % (0-100)


@dataclass
class FanCurve:
    """A fan curve is a list of (temp, speed%) points, interpolated."""
    name: str
    points: List[CurvePoint] = field(default_factory=list)

    # ── Single-sensor mode (backward-compatible) ──────────────────────────────
    sensor_id: Optional[str] = None    # None → use blend / highest

    # ── Multi-sensor blend (new in 1.5.4) ─────────────────────────────────────
    sensor_ids: List[str]     = field(default_factory=list)   # empty = all
    sensor_weights: List[float] = field(default_factory=list) # parallel to sensor_ids
    blend_mode: BlendMode     = BlendMode.HIGHEST

    hysteresis: float = 2.0
    min_speed: float  = 0.0
    max_speed: float  = 100.0
    stop_below: Optional[float] = None

    def _drive_temp(self, temps: Dict[str, float]) -> float:
        """Return the temperature value that drives this curve."""
        if not temps:
            return 25.0

        # Legacy single-sensor path
        if self.sensor_id and not self.sensor_ids:
            if self.sensor_id in temps:
                return temps[self.sensor_id]
            # Sensor no longer present — fall through to highest
            return max(temps.values())

        # Multi-sensor blend
        pool = {sid: v for sid, v in temps.items()
                if not self.sensor_ids or sid in self.sensor_ids}
        if not pool:
            return max(temps.values())

        if self.blend_mode == BlendMode.AVERAGE:
            return sum(pool.values()) / len(pool)

        if self.blend_mode == BlendMode.WEIGHTED and self.sensor_weights:
            total_w = total_v = 0.0
            for sid, v in pool.items():
                try:
                    idx = self.sensor_ids.index(sid)
                    w   = self.sensor_weights[idx]
                except (ValueError, IndexError):
                    w = 1.0
                total_w += w
                total_v += v * w
            return total_v / total_w if total_w > 0 else max(pool.values())

        # HIGHEST (default)
        return max(pool.values())

    def interpolate(self, temp: float) -> float:
        if not self.points:
            return 50.0
        sorted_pts = sorted(self.points, key=lambda p: p.temp)
        if temp <= sorted_pts[0].temp:
            speed = sorted_pts[0].speed
        elif temp >= sorted_pts[-1].temp:
            speed = sorted_pts[-1].speed
        else:
            speed = 50.0
            for i in range(len(sorted_pts) - 1):
                p1, p2 = sorted_pts[i], sorted_pts[i + 1]
                if p1.temp <= temp <= p2.temp:
                    ratio = (temp - p1.temp) / (p2.temp - p1.temp)
                    speed = p1.speed + ratio * (p2.speed - p1.speed)
                    break
        # stop_below overrides min_speed — fan fully stops below threshold
        if self.stop_below is not None and temp < self.stop_below:
            return 0.0
        return max(self.min_speed, min(self.max_speed, speed))

    def compute(self, temps: Dict[str, float]) -> float:
        """Full pipeline: blend sensors → interpolate curve."""
        return self.interpolate(self._drive_temp(temps))

    def to_dict(self) -> dict:
        return {
            'name':           self.name,
            'points':         [{'temp': p.temp, 'speed': p.speed} for p in self.points],
            'sensor_id':      self.sensor_id,
            'sensor_ids':     self.sensor_ids,
            'sensor_weights': self.sensor_weights,
            'blend_mode':     self.blend_mode.value,
            'hysteresis':     self.hysteresis,
            'min_speed':      self.min_speed,
            'max_speed':      self.max_speed,
            'stop_below':     self.stop_below,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'FanCurve':
        try:
            bm = BlendMode(d.get('blend_mode', 'highest'))
        except ValueError:
            bm = BlendMode.HIGHEST
        curve = cls(
            name           = d.get('name', 'Custom'),
            sensor_id      = d.get('sensor_id'),
            sensor_ids     = d.get('sensor_ids', []),
            sensor_weights = d.get('sensor_weights', []),
            blend_mode     = bm,
            hysteresis     = d.get('hysteresis', 2.0),
            min_speed      = d.get('min_speed', 0.0),
            max_speed      = d.get('max_speed', 100.0),
            stop_below     = d.get('stop_below'),
        )
        for p in d.get('points', []):
            curve.points.append(CurvePoint(p['temp'], p['speed']))
        return curve


# ── Preset curves ─────────────────────────────────────────────────────────────

PRESET_CURVES = {
    'silent': FanCurve(
        name='Silent',
        points=[
            CurvePoint(30, 0), CurvePoint(40, 15), CurvePoint(55, 30),
            CurvePoint(65, 50), CurvePoint(75, 75), CurvePoint(85, 100),
        ],
        hysteresis=3.0, min_speed=0.0, stop_below=35.0,
    ),
    'balanced': FanCurve(
        name='Balanced',
        points=[
            CurvePoint(30, 20), CurvePoint(45, 30), CurvePoint(60, 50),
            CurvePoint(70, 70), CurvePoint(80, 90), CurvePoint(85, 100),
        ],
        hysteresis=2.0, min_speed=20.0,
    ),
    'performance': FanCurve(
        name='Performance',
        points=[
            CurvePoint(30, 40), CurvePoint(50, 55), CurvePoint(65, 75),
            CurvePoint(75, 90), CurvePoint(80, 100),
        ],
        hysteresis=1.0, min_speed=40.0,
    ),
    'gaming': FanCurve(
        name='Gaming',
        points=[
            CurvePoint(30, 30), CurvePoint(55, 50),
            CurvePoint(70, 80), CurvePoint(80, 100),
        ],
        hysteresis=2.0, min_speed=30.0,
    ),
    'full_speed': FanCurve(
        name='Full Speed',
        points=[CurvePoint(0, 100), CurvePoint(100, 100)],
        hysteresis=0.0, min_speed=100.0,
    ),
    'fixed_30': FanCurve(
        name='Fixed 30%',
        points=[CurvePoint(0, 30), CurvePoint(100, 30)],
        min_speed=30.0, max_speed=30.0,
    ),
    'fixed_50': FanCurve(
        name='Fixed 50%',
        points=[CurvePoint(0, 50), CurvePoint(100, 50)],
        min_speed=50.0, max_speed=50.0,
    ),
}


class CurveEngine:
    """Manages fan curve assignments and applies them."""

    def __init__(self, hysteresis_global: float = 2.0, emergency_temp: float = 90.0):
        self.curves: Dict[str, FanCurve]       = {}
        self.fan_assignments: Dict[str, str]   = {}   # fan_id -> curve_id
        self.fixed_speeds: Dict[str, float]    = {}   # fan_id -> fixed %
        self._last_speed: Dict[str, float]     = {}
        self.hysteresis_global = hysteresis_global
        self.emergency_temp    = emergency_temp
        self.emergency_active  = False
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
        """Return target speed % or None (auto)."""
        max_temp = max(temps.values()) if temps else 0
        if max_temp >= self.emergency_temp:
            self.emergency_active = True
            return 100.0
        self.emergency_active = False

        if fan_id in self.fixed_speeds:
            return self.fixed_speeds[fan_id]

        curve_id = self.fan_assignments.get(fan_id)
        if not curve_id:
            return None
        curve = self.curves.get(curve_id)
        if not curve:
            return None

        target = curve.compute(temps)

        # Hysteresis
        hysteresis = curve.hysteresis if curve.hysteresis > 0 else self.hysteresis_global
        last = self._last_speed.get(fan_id)
        if last is not None:
            if abs(target - last) < hysteresis * 0.5:
                target = last
            elif target < last and (last - target) < hysteresis:
                target = last

        self._last_speed[fan_id] = target
        return target

    def to_dict(self) -> dict:
        return {
            'custom_curves':   {k: v.to_dict() for k, v in self.curves.items()
                                if k not in PRESET_CURVES},
            'fan_assignments': self.fan_assignments,
            'fixed_speeds':    self.fixed_speeds,
        }

    def load_dict(self, d: dict):
        """Update engine state in-place — preserves external dict references."""
        for k, v in d.get('custom_curves', {}).items():
            self.curves[k] = FanCurve.from_dict(v)
        # Update dicts in-place so any code holding a reference to the old
        # dict (e.g. ProfilesTab._apply_quick_preset) still sees the new data
        self.fan_assignments.clear()
        self.fan_assignments.update(d.get('fan_assignments', {}))
        self.fixed_speeds.clear()
        self.fixed_speeds.update(d.get('fixed_speeds', {}))


class ProfileManager:
    def __init__(self, state):
        self.state = state

    def save_profile(self, name: str, engine: CurveEngine,
                     rgb_settings: dict = None) -> dict:
        profile = {'name': name, 'curves': engine.to_dict(), 'rgb': rgb_settings or {}}
        self.state.save_profile(name, profile)
        return profile

    def load_profile(self, name: str, engine: CurveEngine) -> bool:
        profile = self.state.get_profile(name)
        if not profile:
            return False
        engine.load_dict(profile.get('curves', {}))
        self.state.active_profile = name
        self.state.save_config()
        return True

    def list_profiles(self) -> List[str]:
        return list(self.state.profiles.keys())

    def delete_profile(self, name: str):
        self.state.delete_profile(name)
