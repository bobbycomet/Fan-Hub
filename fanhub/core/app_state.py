"""
Global application state - holds all runtime data and settings.
"""
import json
import os
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger('fanhub.state')

CONFIG_PATH = os.path.expanduser('~/.config/fanhub/config.json')


class AppState:
    """Central state store for Fan Hub."""

    def __init__(self):
        self.fans: Dict[str, dict] = {}          # fan_id -> fan data
        self.sensors: Dict[str, float] = {}       # sensor_key -> temp °C
        self.profiles: Dict[str, dict] = {}       # profile_name -> profile data
        self.active_profile: Optional[str] = None
        self.rgb_devices: List[dict] = []
        self.liquid_devices: List[dict] = []
        self.fan_hubs: List[dict] = []
        self.openrgb_connected: bool = False
        self.liquidctl_available: bool = False
        self.settings: dict = self._default_settings()

        self._load_config()

    def _default_settings(self) -> dict:
        return {
            'poll_interval_ms': 1000,
            'temp_unit': 'C',
            'start_minimized': False,
            'tray_icon': True,
            'openrgb_host': 'localhost',
            'openrgb_port': 6742,
            'theme': 'dark',
            'hysteresis': 2.0,           # °C hysteresis for fan curves
            'safe_mode': True,           # Never go below min RPM
            'emergency_temp': 90.0,      # °C - set fans to 100%
            'daemon_enabled': False,     # fanhub-daemon systemd service
        }

    def _load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    data = json.load(f)
                self.settings.update(data.get('settings', {}))
                self.profiles = data.get('profiles', {})
                self.active_profile = data.get('active_profile')
                logger.info(f"Loaded config with {len(self.profiles)} profiles")
            except Exception as e:
                logger.error(f"Failed to load config: {e}")

    def save_config(self):
        """Atomically write config using tmp + os.replace to prevent corruption."""
        import tempfile
        try:
            data = {
                'settings': self.settings,
                'profiles': self.profiles,
                'active_profile': self.active_profile,
            }
            config_dir = os.path.dirname(CONFIG_PATH)
            os.makedirs(config_dir, exist_ok=True)
            # Write to a temp file in the same directory, then atomically replace
            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_path, CONFIG_PATH)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise
            logger.info("Config saved")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def save_profile(self, name: str, profile_data: dict):
        self.profiles[name] = profile_data
        self.save_config()

    def delete_profile(self, name: str):
        if name in self.profiles:
            del self.profiles[name]
            if self.active_profile == name:
                self.active_profile = None
            self.save_config()

    def get_profile(self, name: str) -> Optional[dict]:
        return self.profiles.get(name)
