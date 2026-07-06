"""
AppContext — shared context object passed to every tab at construction.

Replaces the fragile parent-walking pattern used by ProfilesTab and others
to reach MainWindow attributes. Instead of `while w: if hasattr(w, 'hw_monitor')`,
every tab receives a single context object with stable references.
"""
from dataclasses import dataclass, field
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from core.hardware_monitor import HardwareMonitor
    from core.fan_curves import CurveEngine, ProfileManager
    from core.app_state import AppState


@dataclass
class AppContext:
    """
    Shared references injected into every tab at construction.
    All fields are set by MainWindow after backends are initialised.
    Tabs should treat this as read-only except for the callbacks.
    """
    state:           'AppState'
    hw_monitor:      Optional['HardwareMonitor']  = None
    curve_engine:    Optional['CurveEngine']       = None
    profile_manager: Optional['ProfileManager']    = None

    # Callbacks provided by MainWindow — tabs call these instead of
    # walking the widget tree to find the window
    on_curves_changed:    Callable[[], None] = field(default=lambda: None)
    on_profile_loaded:    Callable[[str], None] = field(default=lambda name: None)
    on_tray_menu_refresh: Callable[[], None] = field(default=lambda: None)
