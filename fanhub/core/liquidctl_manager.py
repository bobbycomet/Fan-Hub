"""
Liquidctl integration for AIOs, USB fan controllers, and liquid cooling.
Supports: NZXT Kraken, Corsair Hydro, EVGA CLC, Cooler Master, and more.
"""
import subprocess
import json
import logging
import re
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger('fanhub.liquidctl')


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
    device_type: str = 'unknown'   # 'aio', 'hub', 'psu', 'reservoir', 'gpu_block'

    # Liquidctl address string for CLI
    address: str = ''


# Device capability database (known liquidctl devices)
KNOWN_DEVICES = {
    'kraken':      {'type': 'aio', 'fan_ctrl': True, 'pump_ctrl': True, 'rgb': True},
    'hydro':       {'type': 'aio', 'fan_ctrl': True, 'pump_ctrl': False, 'rgb': True},
    'h100':        {'type': 'aio', 'fan_ctrl': True, 'pump_ctrl': False, 'rgb': True},
    'h115':        {'type': 'aio', 'fan_ctrl': True, 'pump_ctrl': False, 'rgb': True},
    'h150':        {'type': 'aio', 'fan_ctrl': True, 'pump_ctrl': False, 'rgb': True},
    'elite':       {'type': 'aio', 'fan_ctrl': True, 'pump_ctrl': True, 'rgb': True},
    'commander':   {'type': 'hub', 'fan_ctrl': True, 'pump_ctrl': False, 'rgb': True},
    'lighting node': {'type': 'hub', 'fan_ctrl': False, 'pump_ctrl': False, 'rgb': True},
    'smart device': {'type': 'hub', 'fan_ctrl': True, 'pump_ctrl': False, 'rgb': True},
    'grid':        {'type': 'hub', 'fan_ctrl': True, 'pump_ctrl': False, 'rgb': False},
    'rm':          {'type': 'psu', 'fan_ctrl': False, 'pump_ctrl': False, 'rgb': True},
    'hx':          {'type': 'psu', 'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False},
    'ax':          {'type': 'psu', 'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False},
}


def _classify_device(name: str) -> dict:
    name_lower = name.lower()
    for keyword, caps in KNOWN_DEVICES.items():
        if keyword in name_lower:
            return caps
    return {'type': 'unknown', 'fan_ctrl': False, 'pump_ctrl': False, 'rgb': False}


class LiquidctlManager:
    """
    Manages all liquidctl-compatible devices.
    Uses the liquidctl CLI for maximum compatibility.
    """

    def __init__(self):
        self.devices: List[LiquidDevice] = []
        self.available = self._check_available()
        if self.available:
            self.discover()

    def _check_available(self) -> bool:
        try:
            result = subprocess.run(['liquidctl', '--version'],
                                    capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                logger.info(f"liquidctl available: {result.stdout.strip()}")
                return True
        except FileNotFoundError:
            logger.warning("liquidctl not found. Install: pip install liquidctl")
        except Exception as e:
            logger.warning(f"liquidctl check failed: {e}")
        return False

    def _run(self, *args, timeout=10) -> Optional[str]:
        try:
            result = subprocess.run(
                ['liquidctl'] + list(args),
                capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return result.stdout
            else:
                logger.debug(f"liquidctl error: {result.stderr}")
        except subprocess.TimeoutExpired:
            logger.warning("liquidctl command timed out")
        except Exception as e:
            logger.error(f"liquidctl run error: {e}")
        return None

    def discover(self):
        self.devices = []
        output = self._run('list', '--json')
        if output:
            try:
                device_list = json.loads(output)
                for dev_data in device_list:
                    self._process_device(dev_data)
                logger.info(f"liquidctl: found {len(self.devices)} devices")
                return
            except json.JSONDecodeError:
                pass

        # Fallback: parse text output
        output = self._run('list')
        if output:
            self._parse_text_list(output)

    def _process_device(self, data: dict):
        name = data.get('description', data.get('vendor', 'Unknown'))
        addr = data.get('bus', '') + ':' + str(data.get('port', ''))
        caps = _classify_device(name)

        dev = LiquidDevice(
            id=f"lc_{len(self.devices)}",
            name=name,
            description=name,
            vendor_id=str(data.get('vendor_id', '')),
            product_id=str(data.get('product_id', '')),
            bus=str(data.get('bus', '')),
            port=str(data.get('port', '')),
            address=addr,
            device_type=caps['type'],
            supports_fan_control=caps['fan_ctrl'],
            supports_pump_control=caps['pump_ctrl'],
            supports_rgb=caps['rgb'],
        )
        self.devices.append(dev)

    def _parse_text_list(self, output: str):
        """Parse text output of `liquidctl list`."""
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Format: "Device #N, <description>"
            # Or: "#N: <vendor> <product>"
            match = re.search(r'(?:Device #?\d+[,:]?\s*)(.+)', line, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
            else:
                name = line

            caps = _classify_device(name)
            dev = LiquidDevice(
                id=f"lc_{len(self.devices)}",
                name=name,
                description=name,
                device_type=caps['type'],
                supports_fan_control=caps['fan_ctrl'],
                supports_pump_control=caps['pump_ctrl'],
                supports_rgb=caps['rgb'],
                address=str(len(self.devices)),
            )
            self.devices.append(dev)

    def read_status(self, device: LiquidDevice) -> Dict[str, Any]:
        """Read device status (temperatures, fan RPMs, pump RPM, etc.)"""
        status = {}

        # Try JSON output first
        output = self._run('--match', device.description, 'status', '--json')
        if output:
            try:
                data = json.loads(output)
                if isinstance(data, list) and data:
                    entries = data[0].get('status', [])
                    for entry in entries:
                        key = entry.get('key', '')
                        val = entry.get('value', None)
                        unit = entry.get('unit', '')
                        status[key] = {'value': val, 'unit': unit}
                    device.status = status
                    self._parse_status_to_sensors(device, status)
                    return status
            except json.JSONDecodeError:
                pass

        # Fallback: text parsing
        output = self._run('--match', device.description, 'status')
        if output:
            status = self._parse_text_status(output)
            device.status = status
            self._parse_status_to_sensors(device, status)

        return status

    def _parse_text_status(self, output: str) -> Dict[str, Any]:
        status = {}
        for line in output.strip().split('\n'):
            if ':' in line:
                key, _, val = line.partition(':')
                key = key.strip()
                val = val.strip()
                # Extract numeric value and unit
                m = re.match(r'([\d.]+)\s*([°CRPMVWA%]*)', val)
                if m:
                    try:
                        status[key] = {'value': float(m.group(1)), 'unit': m.group(2)}
                    except ValueError:
                        status[key] = {'value': val, 'unit': ''}
                else:
                    status[key] = {'value': val, 'unit': ''}
        return status

    def _parse_status_to_sensors(self, device: LiquidDevice, status: dict):
        """Extract structured fan/temp/pump data from status."""
        device.fans = []
        device.temps = []
        device.pump = None

        for key, entry in status.items():
            key_lower = key.lower()
            val = entry.get('value', 0)
            unit = entry.get('unit', '')

            if 'temp' in key_lower or '°c' in unit.lower() or 'c' == unit.strip():
                device.temps.append({'label': key, 'value': val, 'unit': 'C'})
            elif 'fan' in key_lower and ('rpm' in unit.lower() or 'rpm' in key_lower):
                device.fans.append({'label': key, 'rpm': val})
            elif 'pump' in key_lower and 'rpm' in unit.lower():
                device.pump = {'label': key, 'rpm': val}
            elif 'pump' in key_lower and 'duty' in key_lower:
                if device.pump:
                    device.pump['duty'] = val
                else:
                    device.pump = {'label': key, 'duty': val}

    def read_all_status(self) -> List[LiquidDevice]:
        for dev in self.devices:
            self.read_status(dev)
        return self.devices

    # ─────────────────────────────────────────────
    #  Control
    # ─────────────────────────────────────────────

    def set_fan_speed(self, device: LiquidDevice, channel: str, percent: int) -> bool:
        """Set fan speed on a liquidctl device. Percent: 0-100."""
        if not device.supports_fan_control:
            return False
        percent = max(0, min(100, percent))
        output = self._run('--match', device.description,
                           'set', channel, 'speed', str(percent))
        return output is not None

    def set_fan_curve(self, device: LiquidDevice, channel: str,
                      curve_points: List[Tuple[int, int]]) -> bool:
        """
        Set fan curve on device. curve_points: list of (temp_C, speed_pct).
        Format for liquidctl: 'set fan speed 20 30 30 50 40 70 ...'
        """
        if not device.supports_fan_control:
            return False
        args = ['--match', device.description, 'set', channel, 'speed']
        for temp, speed in curve_points:
            args.extend([str(temp), str(speed)])
        output = self._run(*args)
        return output is not None

    def set_pump_speed(self, device: LiquidDevice, mode: str) -> bool:
        """
        Set pump mode: 'quiet', 'balanced', 'performance', or integer percent.
        """
        if not device.supports_pump_control:
            return False
        output = self._run('--match', device.description, 'set', 'pump', 'speed', mode)
        return output is not None

    def set_rgb(self, device: LiquidDevice, channel: str,
                mode: str, colors: List[Tuple[int, int, int]] = None) -> bool:
        """Set RGB on liquidctl device."""
        if not device.supports_rgb:
            return False
        args = ['--match', device.description, 'set', channel, 'color', mode]
        if colors:
            for r, g, b in colors:
                args.append(f'{r:02x}{g:02x}{b:02x}')
        output = self._run(*args)
        return output is not None

    def initialize_device(self, device: LiquidDevice) -> bool:
        """Initialize device (required after connect for some devices)."""
        output = self._run('--match', device.description, 'initialize')
        return output is not None

    def initialize_all(self):
        for dev in self.devices:
            self.initialize_device(dev)

    def rescan(self):
        self.devices = []
        if self.available:
            self.discover()
