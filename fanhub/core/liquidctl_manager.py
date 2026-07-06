"""
Liquidctl integration for AIOs, USB fan controllers, and liquid cooling.

Backend strategy (v1.5.4):
  PRIMARY   — liquidctl Python API (find_liquidctl_devices, dev.get_status, …)
              Uses unique bus:address addressing; type-safe status tuples; no JSON
              parsing; no subprocess overhead; correct --match ambiguity avoided.
  FALLBACK  — liquidctl CLI (subprocess) when the Python library is not installed
              or an import fails.  All existing behaviour preserved exactly.

The public interface (LiquidDevice, LiquidctlManager) is unchanged.
"""
import logging
import re
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger('fanhub.liquidctl')

# ── Try to import the Python API ─────────────────────────────────────────────
try:
    from liquidctl import find_liquidctl_devices as _lc_find
    import liquidctl as _lc_mod
    _HAVE_PYAPI = True
    logger.debug(f"liquidctl Python API available: {_lc_mod.__version__}")
except ImportError:
    _HAVE_PYAPI = False
    logger.debug("liquidctl Python API not found; will use CLI fallback")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LiquidDevice:
    id: str
    name: str
    description: str
    vendor_id: str = ''
    product_id: str = ''
    bus: str = ''
    port: str = ''
    status: Dict[str, Any] = field(default_factory=dict)
    fans: List[dict] = field(default_factory=list)
    temps: List[dict] = field(default_factory=list)
    pump: Optional[dict] = None
    supports_fan_control: bool = False
    supports_pump_control: bool = False
    supports_rgb: bool = False
    device_type: str = 'unknown'

    # CLI addressing (fallback path)
    address: str = ''
    # Python API device object (primary path) — not serialised
    _api_dev: Any = field(default=None, repr=False, compare=False)


# ── Capability table ──────────────────────────────────────────────────────────

KNOWN_DEVICES = {
    # AIO liquid coolers
    'kraken':        {'type': 'aio',  'fan_ctrl': True,  'pump_ctrl': True,  'rgb': True},
    'hydro':         {'type': 'aio',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'h100':          {'type': 'aio',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'h115':          {'type': 'aio',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'h150':          {'type': 'aio',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'elite':         {'type': 'aio',  'fan_ctrl': True,  'pump_ctrl': True,  'rgb': True},
    'ga ii':         {'type': 'aio',  'fan_ctrl': True,  'pump_ctrl': True,  'rgb': True},
    'ryujin':        {'type': 'aio',  'fan_ctrl': True,  'pump_ctrl': True,  'rgb': True},
    # Fan/LED hubs
    'commander':     {'type': 'hub',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'lighting node': {'type': 'hub',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': True},
    'smart device':  {'type': 'hub',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'rgb & fan':     {'type': 'hub',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'grid':          {'type': 'hub',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': False},
    'uni sl':        {'type': 'hub',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'uni al':        {'type': 'hub',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'octo':          {'type': 'hub',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'quadro':        {'type': 'hub',  'fan_ctrl': True,  'pump_ctrl': False, 'rgb': True},
    'farbwerk':      {'type': 'hub',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': True},
    'hue 2':         {'type': 'hub',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': True},
    # PSUs
    'rm':            {'type': 'psu',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': True},
    'hx':            {'type': 'psu',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False},
    'ax':            {'type': 'psu',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False},
    'e500':          {'type': 'psu',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False},
    'e650':          {'type': 'psu',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False},
    'e850':          {'type': 'psu',  'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False},
}


def _classify(name: str) -> dict:
    nl = name.lower()
    for kw, caps in KNOWN_DEVICES.items():
        if kw in nl:
            return caps
    return {'type': 'unknown', 'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False}


# ── Status parsing ────────────────────────────────────────────────────────────

def _parse_status_tuples(device: LiquidDevice, status_list: list):
    """
    Parse a list of (key, value, unit) tuples from the Python API into the
    device.fans / device.temps / device.pump structured fields.
    """
    device.fans  = []
    device.temps = []
    device.pump  = None
    raw = {}

    for key, value, unit in status_list:
        kl = key.lower()
        ul = (unit or '').lower()

        raw[key] = {'value': value, 'unit': unit}

        if 'liquid temp' in kl or 'coolant temp' in kl or 'water temp' in kl:
            device.temps.append({'label': key, 'value': float(value or 0), 'unit': 'C'})
        elif 'temp' in kl and ('°c' in ul or ul == 'c' or ul == '°c'):
            device.temps.append({'label': key, 'value': float(value or 0), 'unit': 'C'})
        elif 'fan' in kl and 'speed' in kl and 'rpm' in ul:
            device.fans.append({'label': key, 'rpm': int(value or 0)})
        elif 'pump speed' in kl and 'rpm' in ul:
            if device.pump is None:
                device.pump = {'label': key, 'rpm': int(value or 0)}
            else:
                device.pump['rpm'] = int(value or 0)
        elif 'pump duty' in kl:
            if device.pump is None:
                device.pump = {'label': key, 'duty': value}
            else:
                device.pump['duty'] = value

    device.status = raw


# ── Main manager ──────────────────────────────────────────────────────────────

class LiquidctlManager:
    """
    Manages all liquidctl-compatible devices.

    Uses the liquidctl Python API when available for type safety and correct
    addressing.  Falls back to the CLI (subprocess) automatically when the
    Python library is not installed.
    """

    def __init__(self):
        self.devices: List[LiquidDevice] = []
        self._use_api = _HAVE_PYAPI
        self.available = self._check_available()
        if self.available:
            self.discover()

    # ── Availability ──────────────────────────────────────────────────────────

    def _check_available(self) -> bool:
        if self._use_api:
            logger.info("liquidctl: using Python API")
            return True
        # Fallback: check CLI
        import subprocess
        try:
            r = subprocess.run(['liquidctl', '--version'],
                               capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                logger.info(f"liquidctl CLI: {r.stdout.strip()}")
                return True
        except FileNotFoundError:
            logger.warning("liquidctl not found — install: pip install liquidctl")
        except Exception as e:
            logger.warning(f"liquidctl check failed: {e}")
        return False

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover(self):
        self.devices = []
        if self._use_api:
            self._discover_api()
        else:
            self._discover_cli()
        logger.info(f"liquidctl: found {len(self.devices)} device(s)")

    def _discover_api(self):
        """Discover devices via the Python API (primary path)."""
        try:
            for dev in _lc_find():
                caps = _classify(dev.description)
                ld = LiquidDevice(
                    id=f"lc_{len(self.devices)}",
                    name=dev.description,
                    description=dev.description,
                    vendor_id=str(getattr(dev, 'vendor_id', '') or ''),
                    product_id=str(getattr(dev, 'product_id', '') or ''),
                    bus=str(getattr(dev, 'bus', '') or ''),
                    port=str(getattr(dev, 'port', '') or ''),
                    address=f"{getattr(dev, 'bus', '')}:{getattr(dev, 'port', '')}",
                    device_type=caps['type'],
                    supports_fan_control=caps['fan_ctrl'],
                    supports_pump_control=caps['pump_ctrl'],
                    supports_rgb=caps['rgb'],
                    _api_dev=dev,
                )
                self.devices.append(ld)
        except Exception as e:
            logger.error(f"liquidctl API discovery failed: {e}")
            logger.info("Falling back to CLI")
            self._use_api = False
            self._discover_cli()

    def _discover_cli(self):
        """Discover devices via the CLI (fallback path)."""
        import subprocess, json as _json
        out = self._cli('list', '--json')
        if out:
            try:
                for d in _json.loads(out):
                    self._process_cli_device(d)
                return
            except Exception:
                pass
        out = self._cli('list')
        if out:
            self._parse_text_list(out)

    def _process_cli_device(self, data: dict):
        name = data.get('description', data.get('vendor', 'Unknown'))
        caps = _classify(name)
        self.devices.append(LiquidDevice(
            id=f"lc_{len(self.devices)}", name=name, description=name,
            vendor_id=str(data.get('vendor_id', '')),
            product_id=str(data.get('product_id', '')),
            bus=str(data.get('bus', '')), port=str(data.get('port', '')),
            address=f"{data.get('bus','')}:{data.get('port','')}",
            device_type=caps['type'],
            supports_fan_control=caps['fan_ctrl'],
            supports_pump_control=caps['pump_ctrl'],
            supports_rgb=caps['rgb'],
        ))

    def _parse_text_list(self, output: str):
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.search(r'(?:Device #?\d+[,:]?\s*)(.+)', line, re.IGNORECASE)
            name = m.group(1).strip() if m else line
            caps = _classify(name)
            self.devices.append(LiquidDevice(
                id=f"lc_{len(self.devices)}", name=name, description=name,
                address=str(len(self.devices)),
                device_type=caps['type'],
                supports_fan_control=caps['fan_ctrl'],
                supports_pump_control=caps['pump_ctrl'],
                supports_rgb=caps['rgb'],
            ))

    # ── Status reading ────────────────────────────────────────────────────────

    def read_status(self, device: LiquidDevice) -> Dict[str, Any]:
        if self._use_api and device._api_dev is not None:
            return self._read_status_api(device)
        return self._read_status_cli(device)

    def _read_status_api(self, device: LiquidDevice) -> Dict[str, Any]:
        """Read status via the Python API — returns (key, value, unit) tuples."""
        try:
            with device._api_dev.connect():
                status = device._api_dev.get_status()
            _parse_status_tuples(device, status)
            return device.status
        except Exception as e:
            logger.debug(f"API read_status failed for {device.name}: {e}")
            return {}

    def _read_status_cli(self, device: LiquidDevice) -> Dict[str, Any]:
        import json as _json
        out = self._cli('--match', device.description, 'status', '--json')
        if out:
            try:
                data = _json.loads(out)
                if isinstance(data, list) and data:
                    tuples = [(e['key'], e['value'], e.get('unit', ''))
                              for e in data[0].get('status', [])]
                    _parse_status_tuples(device, tuples)
                    return device.status
            except Exception:
                pass
        # Text fallback
        out = self._cli('--match', device.description, 'status')
        if out:
            status = self._parse_text_status(out)
            tuples = [(k, v['value'], v['unit']) for k, v in status.items()]
            _parse_status_tuples(device, tuples)
        return device.status

    def _parse_text_status(self, output: str) -> Dict[str, Any]:
        status = {}
        for line in output.strip().split('\n'):
            if ':' in line:
                key, _, val = line.partition(':')
                key, val = key.strip(), val.strip()
                m = re.match(r'([\d.]+)\s*([°CRPMVWA%dB]*)', val)
                if m:
                    try:
                        status[key] = {'value': float(m.group(1)), 'unit': m.group(2)}
                    except ValueError:
                        status[key] = {'value': val, 'unit': ''}
                else:
                    status[key] = {'value': val, 'unit': ''}
        return status

    def read_all_status(self) -> List[LiquidDevice]:
        for dev in self.devices:
            self.read_status(dev)
        return self.devices

    # ── Control ───────────────────────────────────────────────────────────────

    def set_fan_speed(self, device: LiquidDevice, channel: str,
                      percent: int) -> bool:
        if not device.supports_fan_control:
            return False
        percent = max(0, min(100, percent))
        if self._use_api and device._api_dev is not None:
            try:
                with device._api_dev.connect():
                    device._api_dev.set_fixed_speed(channel, percent)
                return True
            except Exception as e:
                logger.debug(f"API set_fan_speed failed: {e}")
        return self._cli('--match', device.description,
                         'set', channel, 'speed', str(percent)) is not None

    def set_fan_curve(self, device: LiquidDevice, channel: str,
                      curve_points: List[Tuple[int, int]]) -> bool:
        """curve_points: list of (temp_C, duty_pct)."""
        if not device.supports_fan_control:
            return False
        if self._use_api and device._api_dev is not None:
            try:
                with device._api_dev.connect():
                    device._api_dev.set_speed_profile(channel, curve_points)
                return True
            except Exception as e:
                logger.debug(f"API set_fan_curve failed: {e}")
        args = ['--match', device.description, 'set', channel, 'speed']
        for temp, speed in curve_points:
            args += [str(temp), str(speed)]
        return self._cli(*args) is not None

    def set_pump_speed(self, device: LiquidDevice, mode: str) -> bool:
        if not device.supports_pump_control:
            return False
        if self._use_api and device._api_dev is not None:
            try:
                with device._api_dev.connect():
                    # Try integer percent first, then mode string
                    try:
                        pct = int(mode)
                        device._api_dev.set_fixed_speed('pump', pct)
                    except ValueError:
                        device._api_dev.set_fixed_speed('pump', mode)
                return True
            except Exception as e:
                logger.debug(f"API set_pump_speed failed: {e}")
        return self._cli('--match', device.description,
                         'set', 'pump', 'speed', str(mode)) is not None

    def set_rgb(self, device: LiquidDevice, channel: str,
                mode: str, colors: List[Tuple[int, int, int]] = None) -> bool:
        if not device.supports_rgb:
            return False
        if self._use_api and device._api_dev is not None:
            try:
                color_list = [list(c) for c in colors] if colors else []
                with device._api_dev.connect():
                    device._api_dev.set_color(channel, mode, color_list)
                return True
            except Exception as e:
                logger.debug(f"API set_rgb failed: {e}")
        args = ['--match', device.description, 'set', channel, 'color', mode]
        if colors:
            for r, g, b in colors:
                args.append(f'{r:02x}{g:02x}{b:02x}')
        return self._cli(*args) is not None

    def initialize_device(self, device: LiquidDevice) -> bool:
        if self._use_api and device._api_dev is not None:
            try:
                with device._api_dev.connect():
                    device._api_dev.initialize()
                return True
            except Exception as e:
                logger.debug(f"API initialize failed: {e}")
        return self._cli('--match', device.description, 'initialize') is not None

    def initialize_all(self):
        for dev in self.devices:
            self.initialize_device(dev)

    def rescan(self):
        self.devices = []
        if self.available:
            self.discover()

    # ── CLI helper (fallback only) ────────────────────────────────────────────

    def _cli(self, *args, timeout: int = 10) -> Optional[str]:
        import subprocess
        try:
            r = subprocess.run(
                ['liquidctl'] + list(args),
                capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return r.stdout
            logger.debug(f"liquidctl CLI error: {r.stderr.strip()}")
        except subprocess.TimeoutExpired:
            logger.warning("liquidctl CLI command timed out")
        except Exception as e:
            logger.error(f"liquidctl CLI error: {e}")
        return None
