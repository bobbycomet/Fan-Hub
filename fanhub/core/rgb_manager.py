"""
OpenRGB integration — supports SDK, AppImage (any version name), and .deb install.
Robust connection with live status reporting.
"""
import subprocess
import logging
import socket
import os
import glob
import shutil
from typing import List, Optional, Tuple

logger = logging.getLogger('fanhub.rgb')

# ── SDK import (optional) ─────────────────────────────────────────────────────
_OpenRGBClient = None
_SDK_RGBColor  = None
OPENRGB_SDK    = False

try:
    from openrgb import OpenRGBClient as _OpenRGBClient
    from openrgb.utils import RGBColor as _SDK_RGBColor
    OPENRGB_SDK = True
    logger.info("openrgb-python SDK available")
except ImportError:
    logger.info("openrgb-python not installed; will use CLI fallback")


def _make_rgb(r: int, g: int, b: int):
    if OPENRGB_SDK and _SDK_RGBColor is not None:
        return _SDK_RGBColor(r, g, b)
    class _C:
        def __init__(self, r, g, b): self.red, self.green, self.blue = r, g, b
    return _C(r, g, b)


# ── Presets & effects ─────────────────────────────────────────────────────────
RGB_PRESETS = {
    'off':        (0,   0,   0),
    'white':      (255, 255, 255),
    'red':        (255, 0,   0),
    'green':      (0,   255, 0),
    'blue':       (0,   0,   255),
    'cyan':       (0,   255, 255),
    'magenta':    (255, 0,   255),
    'yellow':     (255, 200, 0),
    'orange':     (255, 100, 0),
    'purple':     (128, 0,   255),
    'warm_white': (255, 180, 100),
    'cool_blue':  (100, 180, 255),
}

RGB_EFFECTS = [
    'Static', 'Breathing', 'Flashing', 'Color Cycle', 'Rainbow Wave',
    'Chase', 'Double Flash', 'Meteor', 'Starlight', 'Running',
    'Visor', 'Marquee', 'Tornado', 'Sparkle',
]

FAN_DEVICE_KEYWORDS = [
    'fan', 'cooler', 'cooling', 'heatsink', 'tower',
    'nzxt', 'corsair', 'noctua', 'be quiet', 'arctic',
    'deepcool', 'thermaltake', 'fractal', 'lian li',
    'phanteks', 'ek', 'alphacool', 'aqua computer',
    'aer', 'hub', 'commander', 'lighting node', 'rgb hub',
    'pump', 'aio', 'h100', 'h115', 'h150', 'kraken', 'elite',
    'mainboard', 'motherboard', 'asus', 'gigabyte', 'msi', 'asrock',
    'aura', 'fusion', 'mystic light', 'polychrome',
]


# ── Binary discovery ──────────────────────────────────────────────────────────

def find_openrgb_binary() -> Optional[str]:
    """
    Find OpenRGB binary from:
    1. System PATH (deb install → /usr/bin/openrgb)
    2. dpkg database (deb installed but not on PATH)
    3. Any AppImage in common user directories (any version name)
    4. Flatpak / snap
    """
    # 1. PATH
    found = shutil.which('openrgb')
    if found:
        logger.info(f"OpenRGB on PATH: {found}")
        return found

    # 2. dpkg — check if .deb is installed
    try:
        r = subprocess.run(['dpkg', '-L', 'openrgb'],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            for line in r.stdout.strip().split('\n'):
                line = line.strip()
                if line and os.path.isfile(line) and os.access(line, os.X_OK):
                    logger.info(f"OpenRGB via dpkg: {line}")
                    return line
    except Exception:
        pass

    # 3. AppImage — search common locations with glob (any version name)
    appimage_dirs = [
        os.path.expanduser('~/Downloads'),
        os.path.expanduser('~/Applications'),
        os.path.expanduser('~/.local/bin'),
        os.path.expanduser('~/bin'),
        os.path.expanduser('~/Desktop'),
        '/opt',
        '/usr/local/bin',
    ]
    for d in appimage_dirs:
        if not os.path.isdir(d):
            continue
        # Match any file with OpenRGB in the name (case-insensitive) that is executable
        for entry in os.listdir(d):
            if 'openrgb' in entry.lower() and not entry.endswith('.deb'):
                full = os.path.join(d, entry)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    logger.info(f"OpenRGB AppImage found: {full}")
                    return full
                # AppImage may not be +x yet — check anyway and note it
                if os.path.isfile(full) and entry.lower().endswith('.appimage'):
                    logger.info(f"OpenRGB AppImage found (not +x): {full}")
                    return full

    # 4. Flatpak
    try:
        r = subprocess.run(['flatpak', 'run', '--command=openrgb',
                            'org.openrgb.OpenRGB', '--version'],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            return 'flatpak:org.openrgb.OpenRGB'
    except Exception:
        pass

    # 5. Snap
    snap_path = '/snap/bin/openrgb'
    if os.path.isfile(snap_path):
        return snap_path

    return None


def is_deb_installed() -> bool:
    """Check if OpenRGB was installed via .deb."""
    try:
        r = subprocess.run(['dpkg', '-s', 'openrgb'],
                           capture_output=True, text=True, timeout=3)
        return r.returncode == 0 and 'Status: install ok installed' in r.stdout
    except Exception:
        return False


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def _run_bin(binary: str, args: List[str], timeout: int = 8) -> Optional[str]:
    """Run the OpenRGB binary (handles AppImage, flatpak, regular)."""
    if not binary:
        return None
    try:
        if binary.startswith('flatpak:'):
            app_id = binary.split(':', 1)[1]
            cmd = ['flatpak', 'run', f'--command=openrgb', app_id] + args
        else:
            # Ensure AppImage is executable
            if binary.endswith('.AppImage') or binary.endswith('.appimage'):
                try:
                    os.chmod(binary, 0o755)
                except Exception:
                    pass
            cmd = [binary] + args

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        logger.warning(f"OpenRGB CLI timed out: {args}")
        return None
    except Exception as e:
        logger.warning(f"OpenRGB CLI error: {e}")
        return None


# ── Main manager ──────────────────────────────────────────────────────────────

class OpenRGBManager:

    def __init__(self, host: str = 'localhost', port: int = 6742):
        self.host   = host
        self.port   = port
        self.client = None
        self.devices: List[dict] = []
        self.connected    = False
        self.server_up    = False
        self.deb_installed = is_deb_installed()
        self._bin: Optional[str] = find_openrgb_binary()
        self.status_text  = "Not connected"
        self.error_detail = ""

        logger.info(f"OpenRGB binary: {self._bin or 'NOT FOUND'}")
        logger.info(f"OpenRGB deb installed: {self.deb_installed}")

        self._connect()

    # ── Connection ────────────────────────────────────────────────────────────

    def _connect(self):
        self.connected = False
        self.client    = None
        self.devices   = []

        self.server_up = _port_open(self.host, self.port)

        if not self.server_up:
            self.status_text  = f"Server not running at {self.host}:{self.port}"
            self.error_detail = (
                "The OpenRGB SDK server is not reachable.\n"
                "Start it with:  openrgb --server --server-port 6742\n"
                "or for AppImage: ./OpenRGB*.AppImage --server --server-port 6742"
            )
            logger.warning(self.status_text)
            # Still try CLI direct (works for --list-devices without server)
            self._try_cli_direct()
            return

        # Server up — try SDK
        if OPENRGB_SDK and self._connect_sdk():
            return
        # Fallback to CLI targeting the running server
        self._connect_cli_server()

    def _connect_sdk(self) -> bool:
        try:
            self.client = _OpenRGBClient(self.host, self.port)
            self._discover_sdk()
            self.connected    = True
            self.server_up    = True
            self.status_text  = f"Connected (SDK) — {len(self.devices)} device(s)"
            self.error_detail = ""
            logger.info(self.status_text)
            return True
        except Exception as e:
            self.error_detail = f"SDK error: {e}"
            logger.warning(f"OpenRGB SDK failed: {e}")
            self.client = None
            return False

    def _connect_cli_server(self) -> bool:
        if not self._bin:
            self.status_text  = "OpenRGB binary not found"
            self.error_detail = "Install OpenRGB or browse to the AppImage below."
            return False

        # Try with explicit server host/port
        out = _run_bin(self._bin, [
            '--server-host', self.host,
            '--server-port', str(self.port),
            '--list-devices'
        ])
        if not out:
            # Older CLI: no server flags
            out = _run_bin(self._bin, ['--list-devices'])

        if out and out.strip():
            self._parse_cli(out)
            self.connected    = True
            self.server_up    = True
            self.status_text  = f"Connected (CLI) — {len(self.devices)} device(s)"
            self.error_detail = ""
            logger.info(self.status_text)
            return True

        self.status_text  = "CLI returned no device data"
        self.error_detail = f"Binary: {self._bin}"
        return False

    def _try_cli_direct(self):
        """Best-effort offline CLI list — works without server for some modes."""
        if not self._bin:
            return
        out = _run_bin(self._bin, ['--list-devices'])
        if out and out.strip():
            self._parse_cli(out)
            if self.devices:
                self.status_text = (
                    f"Offline CLI — {len(self.devices)} device(s) "
                    f"(start server for full control)"
                )

    def reconnect(self, new_host: str = None, new_port: int = None,
                  new_bin: str = None):
        if new_host:
            self.host = new_host
        if new_port:
            self.port = new_port
        if new_bin:
            self._bin = new_bin
        else:
            # Re-scan for binary (user may have just installed)
            self._bin = find_openrgb_binary()
        self.deb_installed = is_deb_installed()
        self._connect()

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _discover_sdk(self):
        self.devices = []
        if not self.client:
            return
        for dev in self.client.devices:
            try:
                modes = [m.name for m in dev.modes] if hasattr(dev, 'modes') else []
                zones = [z.name for z in dev.zones] if hasattr(dev, 'zones') else []
                leds  = len(dev.leds)                if hasattr(dev, 'leds')  else 0
                dtype = str(dev.type)                if hasattr(dev, 'type')  else 'Unknown'
            except Exception:
                modes, zones, leds, dtype = [], [], 0, 'Unknown'

            self.devices.append({
                'id':            dev.id,
                'name':          dev.name,
                'type':          dtype,
                'leds':          leds,
                'zones':         zones,
                'modes':         modes,
                'is_fan_device': self._is_fan(dev.name, dtype),
                'source':        'sdk',
                '_sdk_dev':      dev,
            })

    def _parse_cli(self, output: str):
        """Parse `openrgb --list-devices` in old and new format."""
        import re
        self.devices = []
        cur = None

        for raw in output.split('\n'):
            line = raw.strip()
            if not line:
                continue

            m = re.match(r'^Device\s+(\d+)[:\|]\s*(.+)', line, re.IGNORECASE)
            if m:
                if cur:
                    self.devices.append(cur)
                idx  = int(m.group(1))
                name = m.group(2).strip().strip('|').strip()
                cur  = {
                    'id': idx, 'name': name, 'type': 'Unknown',
                    'leds': 0, 'zones': [], 'modes': [],
                    'is_fan_device': self._is_fan(name, 'Unknown'),
                    'source': 'cli',
                }
                continue

            if cur is None:
                continue
            if 'Type:' in line:
                val = line.split('Type:', 1)[1].strip()
                cur['type'] = val
                cur['is_fan_device'] = self._is_fan(cur['name'], val)
            elif 'LEDs:' in line:
                try:
                    cur['leds'] = int(re.search(r'\d+', line.split('LEDs:')[1]).group())
                except Exception:
                    pass
            elif re.match(r'^\s*Zone\s+\d+', line, re.IGNORECASE):
                m2 = re.search(r'Zone\s+\d+[:\s]+(.+)', line, re.IGNORECASE)
                if m2:
                    cur['zones'].append(m2.group(1).strip())
            elif re.match(r'^\s*Mode\s+\d+', line, re.IGNORECASE):
                m3 = re.search(r'Mode\s+\d+[:\s]+(.+)', line, re.IGNORECASE)
                if m3:
                    cur['modes'].append(m3.group(1).strip())

        if cur:
            self.devices.append(cur)

    def _is_fan(self, name: str, dtype: str) -> bool:
        nl = name.lower()
        tl = dtype.lower()
        for t in ['fan', 'cooler', 'led_strip', 'ledstrip']:
            if t in tl:
                return True
        for kw in FAN_DEVICE_KEYWORDS:
            if kw in nl:
                return True
        return False

    # ── Control ───────────────────────────────────────────────────────────────

    def set_device_color(self, device_id: int, r: int, g: int, b: int) -> bool:
        if OPENRGB_SDK and self.client:
            return self._sdk_color(device_id, r, g, b)
        return self._cli_color(device_id, r, g, b)

    def _sdk_color(self, device_id: int, r: int, g: int, b: int) -> bool:
        try:
            dev = self._sdk_dev(device_id)
            if dev:
                dev.set_color(_make_rgb(r, g, b))
                return True
        except Exception as e:
            logger.error(f"SDK set_color {device_id}: {e}")
            # Try reconnect once
            try:
                self._connect_sdk()
                dev = self._sdk_dev(device_id)
                if dev:
                    dev.set_color(_make_rgb(r, g, b))
                    return True
            except Exception:
                pass
        return False

    def _cli_color(self, device_id: int, r: int, g: int, b: int) -> bool:
        if not self._bin:
            return False
        hex_col = f"{r:02x}{g:02x}{b:02x}"
        out = _run_bin(self._bin, [
            '--server-host', self.host, '--server-port', str(self.port),
            '--device', str(device_id), '--color', hex_col
        ])
        if out is None:
            out = _run_bin(self._bin, [
                '--device', str(device_id), '--color', hex_col
            ])
        return out is not None

    def set_device_mode(self, device_id: int, mode_name: str,
                        r: int = 255, g: int = 255, b: int = 255) -> bool:
        if OPENRGB_SDK and self.client:
            return self._sdk_mode(device_id, mode_name, r, g, b)
        return self._cli_mode(device_id, mode_name, r, g, b)

    def _sdk_mode(self, device_id: int, mode_name: str,
                  r: int, g: int, b: int) -> bool:
        try:
            dev = self._sdk_dev(device_id)
            if not dev:
                return False
            for mode in dev.modes:
                if mode.name.lower() == mode_name.lower():
                    dev.set_mode(mode)
                    try:
                        if hasattr(mode, 'colors') and mode.colors:
                            dev.set_color(_make_rgb(r, g, b))
                    except Exception:
                        pass
                    return True
        except Exception as e:
            logger.error(f"SDK set_mode {device_id}: {e}")
        return False

    def _cli_mode(self, device_id: int, mode_name: str,
                  r: int, g: int, b: int) -> bool:
        if not self._bin:
            return False
        hex_col  = f"{r:02x}{g:02x}{b:02x}"
        mode_arg = mode_name.lower().replace(' ', '-')
        out = _run_bin(self._bin, [
            '--server-host', self.host, '--server-port', str(self.port),
            '--device', str(device_id),
            '--mode', mode_arg, '--color', hex_col
        ])
        return out is not None

    def set_all_fans_color(self, r: int, g: int, b: int):
        for dev in self.devices:
            if dev.get('is_fan_device'):
                self.set_device_color(dev['id'], r, g, b)

    def set_all_devices_color(self, r: int, g: int, b: int):
        for dev in self.devices:
            self.set_device_color(dev['id'], r, g, b)

    def set_temp_reactive(self, device_id: int, temp: float,
                          cold_color: Tuple = (0, 100, 255),
                          hot_color:  Tuple = (255, 50, 0),
                          min_temp: float = 30.0,
                          max_temp: float = 80.0):
        t = max(0.0, min(1.0, (temp - min_temp) / (max_temp - min_temp)))
        r = int(cold_color[0] + t * (hot_color[0] - cold_color[0]))
        g = int(cold_color[1] + t * (hot_color[1] - cold_color[1]))
        b = int(cold_color[2] + t * (hot_color[2] - cold_color[2]))
        self.set_device_color(device_id, r, g, b)

    def _sdk_dev(self, device_id: int):
        for d in self.devices:
            if d['id'] == device_id and '_sdk_dev' in d:
                return d['_sdk_dev']
        if self.client:
            try:
                for d in self.client.devices:
                    if d.id == device_id:
                        return d
            except Exception:
                pass
        return None

    def get_device_modes(self, device_id: int) -> List[str]:
        for d in self.devices:
            if d['id'] == device_id and d.get('modes'):
                return d['modes']
        return RGB_EFFECTS

    def is_server_running(self) -> bool:
        return _port_open(self.host, self.port)

    def get_full_status(self) -> dict:
        """Return full status dict for the UI status bar."""
        return {
            'connected':      self.connected,
            'server_up':      self.server_up,
            'device_count':   len(self.devices),
            'binary':         self._bin,
            'deb_installed':  self.deb_installed,
            'sdk_available':  OPENRGB_SDK,
            'status_text':    self.status_text,
            'error_detail':   self.error_detail,
            'host':           self.host,
            'port':           self.port,
        }
