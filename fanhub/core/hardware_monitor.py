"""
Hardware sensor reading: temperatures, fan RPMs, voltages.

Fixes in this version:
  - it87 auto-mode: writes '0' for auto (not '2' which is nct6775 convention)
  - nvidia-smi: batched single call for all GPUs instead of per-sensor subprocess
  - safe_mode enforcement: CurveEngine passes min_percent; enforced here in set_fan_pwm
  - signal type annotations on liquid_updated improved (see polling_worker)
"""
import os
import re
import glob
import subprocess
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger('fanhub.sensors')

HWMON_BASE = '/sys/class/hwmon'

FAN_CONN_SYSF    = 'sys_fan'
FAN_CONN_CPU     = 'cpu_fan'
FAN_CONN_CHASSIS = 'chassis_fan'
FAN_CONN_PUMP    = 'pump'
FAN_CONN_LAPTOP  = 'laptop'
FAN_CONN_USB     = 'usb_hub'
FAN_CONN_GENERIC = 'generic'

# Chips that use 0=auto, 1=manual (opposite of nct6775 convention)
_IT87_CHIPS = {'it87', 'it8620', 'it8628', 'it8686', 'it8790', 'it8792', 'it8795'}


@dataclass
class FanEntry:
    id: str
    label: str
    hwmon_path: str
    fan_input_file: str
    pwm_file: Optional[str]
    pwm_enable_file: Optional[str]
    min_file: Optional[str]
    max_file: Optional[str]
    mode: str = 'unknown'
    current_rpm: int = 0
    current_pwm: int = 0
    current_percent: float = 0.0
    min_rpm: int = 0
    max_rpm: int = 3000
    is_hub_channel: bool = False
    hub_type: Optional[str] = None
    child_fans: List[str] = field(default_factory=list)
    connection_type: str = FAN_CONN_SYSF
    chip_name: str = 'unknown'
    zero_rpm_warned: bool = False
    controllable: bool = True
    # it87-style chip: auto=0, manual=1 (inverted from nct6775)
    pwm_auto_value: str = '2'    # value to write for "auto" mode
    pwm_manual_value: str = '1'  # value to write for "manual" mode


@dataclass
class TempSensor:
    id: str
    label: str
    value: float = 0.0
    value_f: float = 32.0       # Fahrenheit mirror, kept in sync
    unit: str = 'C'
    source: str = 'hwmon'
    critical: Optional[float] = None
    high: Optional[float] = None
    input_file: Optional[str] = None


_CPU_KEYWORDS     = ['cpu', 'processor', 'proc']
_PUMP_KEYWORDS    = ['pump', 'aio', 'liquid', 'water']
_CHASSIS_KEYWORDS = ['sys', 'chassis', 'case', 'front', 'rear', 'top', 'bot']
_LAPTOP_CHIPS     = ['thinkpad', 'asus-nb-wmi', 'toshiba', 'dell_smm',
                     'applesmc', 'acpi_cpufreq', 'ideapad', 'hp-wmi']


def _classify_conn(label: str, chip: str) -> str:
    ll, cl = label.lower(), chip.lower()
    if any(k in ll for k in _PUMP_KEYWORDS):    return FAN_CONN_PUMP
    if any(k in ll for k in _CPU_KEYWORDS):     return FAN_CONN_CPU
    if any(k in ll for k in _CHASSIS_KEYWORDS): return FAN_CONN_CHASSIS
    if any(k in cl for k in _LAPTOP_CHIPS):     return FAN_CONN_LAPTOP
    return FAN_CONN_SYSF


def _c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)


# ── Sensor label translation ──────────────────────────────────────────────────
# Maps raw sysfs tempN_label strings → plain-English descriptions.
# Keys are lowercase. Chip context is used to disambiguate when needed.

_LABEL_MAP = {
    # ── SuperIO motherboard sensors (nct6775, nct6798, it87, etc.) ────────────
    'systin':          'Motherboard (System)',
    'systin2':         'Motherboard 2 (System)',
    'cputin':          'CPU Socket (Motherboard)',
    'auxtin':          'Auxiliary',
    'auxtin0':         'Auxiliary 1',
    'auxtin1':         'Auxiliary 2',
    'auxtin2':         'Auxiliary 3',
    'auxtin3':         'Auxiliary 4',
    'peci agent 0':    'CPU (PECI)',
    'peci agent 1':    'CPU 2 (PECI)',
    'peci agent 2':    'CPU 3 (PECI)',
    'peci agent 3':    'CPU 4 (PECI)',
    'pch_cpu_temp':    'Platform Controller Hub (CPU)',
    'pch_chip_temp':   'Platform Controller Hub (Chip)',
    'pch_chip_cpu_max_temp': 'Platform Controller Hub (Max)',
    'agent0 die0':     'CPU Die 0',
    'agent0 die1':     'CPU Die 1',
    'smiovt1':         'SMBus I/O Temp 1',
    'smiovt2':         'SMBus I/O Temp 2',
    # ── AMD CPU (k10temp) ─────────────────────────────────────────────────────
    'tctl':            'CPU Control Temp (Tctl)',
    'tdie':            'CPU Die Temp (Tdie)',
    'tccd1':           'CPU Core Complex 1 (Tccd1)',
    'tccd2':           'CPU Core Complex 2 (Tccd2)',
    'tccd3':           'CPU Core Complex 3 (Tccd3)',
    'tccd4':           'CPU Core Complex 4 (Tccd4)',
    'tccd5':           'CPU Core Complex 5 (Tccd5)',
    'tccd6':           'CPU Core Complex 6 (Tccd6)',
    'tccd7':           'CPU Core Complex 7 (Tccd7)',
    'tccd8':           'CPU Core Complex 8 (Tccd8)',
    'tcore':           'CPU Core Temp',
    'tmem':            'CPU Memory Temp',
    # ── Intel CPU (coretemp) ──────────────────────────────────────────────────
    'package id 0':    'CPU Package (Overall)',
    'package id 1':    'CPU Package 2 (Overall)',
    # Core N handled dynamically below
    # ── NVMe drive (nvme) ─────────────────────────────────────────────────────
    'composite':       'Drive — Composite',
    'sensor 1':        'Drive — Sensor 1',
    'sensor 2':        'Drive — Sensor 2',
    # ── AMD GPU (amdgpu via hwmon) ────────────────────────────────────────────
    'edge':            'GPU Edge Temp',
    'junction':        'GPU Junction (Hotspot)',
    'mem':             'GPU Memory Temp',
    'mem0':            'GPU Memory 0',
    # ── Misc ──────────────────────────────────────────────────────────────────
    'acpitz':          'ACPI Thermal Zone',
    'cpu_thermal':     'CPU Thermal',
    'soc_thermal':     'SoC Thermal',
    'iwlwifi_1':       'Wi-Fi Adapter',
}

# Chip-name → human source name, used when label is generic
_CHIP_SOURCE = {
    'nct6775':  'Motherboard',
    'nct6776':  'Motherboard',
    'nct6779':  'Motherboard',
    'nct6791':  'Motherboard',
    'nct6792':  'Motherboard',
    'nct6793':  'Motherboard',
    'nct6795':  'Motherboard',
    'nct6796':  'Motherboard',
    'nct6798':  'Motherboard',
    'nct6687':  'Motherboard',
    'it87':     'Motherboard',
    'it8620':   'Motherboard',
    'it8628':   'Motherboard',
    'it8686':   'Motherboard',
    'it8790':   'Motherboard',
    'f71858fg': 'Motherboard',
    'f71882fg': 'Motherboard',
    'w83795':   'Motherboard',
    'k10temp':  'CPU (AMD)',
    'coretemp': 'CPU (Intel)',
    'nvme':     'NVMe Drive',
    'amdgpu':   'GPU (AMD)',
    'thinkpad': 'ThinkPad',
    'acpitz':   'ACPI',
    'asus-nb-wmi':  'Laptop (ASUS)',
    'dell_smm':     'Laptop (Dell)',
    'applesmc':     'Laptop (Apple)',
    'iwlwifi':      'Wi-Fi',
    'pch_cannonlake': 'Platform Controller Hub',
    'pch_cometlake':  'Platform Controller Hub',
    'pch_tigerlake':  'Platform Controller Hub',
    'pch_alderlake':  'Platform Controller Hub',
    'pch_raptorlake': 'Platform Controller Hub',
}


def _friendly_temp_label(raw_label: str, chip: str, sensor_num: int) -> str:
    """
    Convert a raw sysfs temp label + chip name into a plain-English string.

    Priority:
      1. Exact match in _LABEL_MAP  (case-insensitive)
      2. Dynamic patterns: "Core N", "Package id N", "Sensor N"
      3. Generic fallback: chip source name + sensor number context
    """
    ll    = raw_label.strip().lower()
    chip_l = chip.strip().lower()

    # 1. Exact map lookup
    if ll in _LABEL_MAP:
        mapped = _LABEL_MAP[ll]
        # Add chip source prefix for generic-sounding names
        if any(mapped.startswith(g) for g in ('Auxiliary', 'Drive', 'GPU')):
            return mapped
        # For motherboard sensors, prepend source for clarity
        src = next((v for k, v in _CHIP_SOURCE.items() if k in chip_l), None)
        if src and src not in mapped:
            return f"{src} — {mapped}"
        return mapped

    # 2. Dynamic patterns
    m = re.match(r'^core\s+(\d+)$', ll)
    if m:
        return f"CPU Core {m.group(1)}"

    m = re.match(r'^package id\s+(\d+)$', ll)
    if m:
        return f"CPU Package {m.group(1)} (Overall)"

    m = re.match(r'^sensor\s+(\d+)$', ll)
    if m:
        src = next((v for k, v in _CHIP_SOURCE.items() if k in chip_l), chip)
        return f"{src} — Sensor {m.group(1)}"

    # 3. Chip-based fallback — use chip source name + sensor index
    src = next((v for k, v in _CHIP_SOURCE.items() if k in chip_l), None)
    if src:
        # If raw label is just "Temp N" or "tempN", use a cleaner form
        if re.match(r'^temp\s*\d*$', ll, re.IGNORECASE):
            return f"{src} — Sensor {sensor_num}"
        # Otherwise keep the raw label but prefix with source
        display = raw_label.strip().title()
        return f"{src} — {display}"

    # Ultimate fallback: chip name : raw label (better than nothing)
    return f"{chip.title()}: {raw_label.strip().title()}"


class HardwareMonitor:

    def __init__(self):
        self.fans:  Dict[str, FanEntry]   = {}
        self.temps: Dict[str, TempSensor] = {}
        # Cache nvidia GPU indices found at discovery so updates are one batched call
        self._nvidia_indices: List[str] = []
        self._discover_all()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _read_file(self, path: str) -> Optional[str]:
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except Exception:
            return None

    def _write_file(self, path: str, value: str) -> bool:
        try:
            with open(path, 'w') as f:
                f.write(str(value))
            return True
        except PermissionError:
            logger.error(f"Permission denied: {path}. Run as root or add udev rules.")
            return False
        except Exception as e:
            logger.error(f"Write error {path}: {e}")
            return False

    def _get_chip_name(self, hwmon_path: str) -> str:
        return self._read_file(os.path.join(hwmon_path, 'name')) or 'unknown'

    # ── discovery ─────────────────────────────────────────────────────────────

    def _discover_all(self):
        self._discover_hwmon_fans()
        self._discover_hwmon_temps()
        self._discover_nvidia_temps()
        self._discover_amd_temps()
        self._detect_fan_modes()
        self._detect_hubs()
        logger.info(f"Discovered {len(self.fans)} fans, {len(self.temps)} sensors")

    def _discover_hwmon_fans(self):
        if not os.path.exists(HWMON_BASE):
            logger.warning("hwmon not found")
            return
        for hwmon_dir in sorted(glob.glob(os.path.join(HWMON_BASE, 'hwmon*'))):
            chip = self._get_chip_name(hwmon_dir)
            for fan_input in sorted(glob.glob(os.path.join(hwmon_dir, 'fan*_input'))):
                m = re.search(r'fan(\d+)_input', os.path.basename(fan_input))
                if not m:
                    continue
                n = m.group(1)
                label = (self._read_file(os.path.join(hwmon_dir, f'fan{n}_label'))
                         or f'{chip} Fan {n}')

                def _opt(p):
                    return p if os.path.exists(p) else None

                pwm_file        = _opt(os.path.join(hwmon_dir, f'pwm{n}'))
                pwm_enable_file = _opt(os.path.join(hwmon_dir, f'pwm{n}_enable'))
                min_file        = _opt(os.path.join(hwmon_dir, f'fan{n}_min'))
                max_file        = _opt(os.path.join(hwmon_dir, f'fan{n}_max'))

                # it87-style chips: auto=0, manual=1
                chip_lower = chip.lower()
                is_it87 = any(c in chip_lower for c in _IT87_CHIPS)
                auto_val   = '0' if is_it87 else '2'
                manual_val = '1'

                fan_id = f"{os.path.basename(hwmon_dir)}_fan{n}"
                self.fans[fan_id] = FanEntry(
                    id=fan_id, label=label,
                    hwmon_path=hwmon_dir, fan_input_file=fan_input,
                    pwm_file=pwm_file, pwm_enable_file=pwm_enable_file,
                    min_file=min_file, max_file=max_file,
                    connection_type=_classify_conn(label, chip),
                    chip_name=chip, controllable=True,
                    pwm_auto_value=auto_val, pwm_manual_value=manual_val,
                )

    def _discover_hwmon_temps(self):
        if not os.path.exists(HWMON_BASE):
            return
        for hwmon_dir in sorted(glob.glob(os.path.join(HWMON_BASE, 'hwmon*'))):
            chip = self._get_chip_name(hwmon_dir)
            for ti in sorted(glob.glob(os.path.join(hwmon_dir, 'temp*_input'))):
                m = re.search(r'temp(\d+)_input', os.path.basename(ti))
                if not m:
                    continue
                n = m.group(1)
                raw_label = (self._read_file(os.path.join(hwmon_dir, f'temp{n}_label'))
                             or f'Temp {n}')
                friendly = _friendly_temp_label(raw_label, chip, int(n))
                crit = high = None
                for f, attr in [
                    (os.path.join(hwmon_dir, f'temp{n}_crit'), 'crit'),
                    (os.path.join(hwmon_dir, f'temp{n}_max'),  'high'),
                ]:
                    v = self._read_file(f)
                    if v:
                        try:
                            val = int(v) / 1000.0
                            if attr == 'crit': crit = val
                            else:              high = val
                        except Exception:
                            pass

                sid = f"{os.path.basename(hwmon_dir)}_temp{n}"
                self.temps[sid] = TempSensor(
                    id=sid, label=friendly,
                    critical=crit, high=high, input_file=ti,
                )

    def _discover_nvidia_temps(self):
        """Single nvidia-smi call discovers all GPUs."""
        try:
            r = subprocess.run(
                ['nvidia-smi',
                 '--query-gpu=index,name,temperature.gpu',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=4)
            if r.returncode != 0:
                return
            for line in r.stdout.strip().split('\n'):
                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 3:
                    continue
                idx, name, temp_s = parts[0], parts[1], parts[2]
                try:
                    temp = float(temp_s)
                except ValueError:
                    continue
                sid = f"nvidia_gpu{idx}"
                self.temps[sid] = TempSensor(
                    id=sid, label=f"NVIDIA {name} (GPU {idx})",
                    value=temp, value_f=_c_to_f(temp),
                    source='nvidia', critical=105.0, high=83.0,
                )
                self._nvidia_indices.append(idx)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug(f"nvidia-smi discovery: {e}")

    def _discover_amd_temps(self):
        try:
            r = subprocess.run(['rocm-smi', '--showtemp', '--json'],
                               capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                import json
                for card, info in json.loads(r.stdout).items():
                    temp = float(info.get('Temperature (Sensor junction) (C)', 0))
                    sid  = f"amd_{card}"
                    self.temps[sid] = TempSensor(
                        id=sid, label=f"AMD GPU {card} Junction",
                        value=temp, value_f=_c_to_f(temp),
                        source='amd', critical=110.0, high=90.0,
                    )
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug(f"rocm-smi: {e}")

    def _detect_fan_modes(self):
        for fan in self.fans.values():
            if fan.pwm_enable_file:
                val = self._read_file(fan.pwm_enable_file)
                # Map the raw value to a mode name
                # For it87: 0=auto, 1=manual
                # For nct6775: 0=dc, 1=manual, 2=auto
                if val == fan.pwm_auto_value:
                    fan.mode = 'pwm_auto'
                elif val == fan.pwm_manual_value:
                    fan.mode = 'pwm_manual'
                elif val == '0' and fan.pwm_auto_value != '0':
                    fan.mode = 'dc'
                else:
                    fan.mode = 'pwm'
            elif fan.pwm_file:
                fan.mode = 'pwm'
            else:
                fan.mode = 'dc'

    def _detect_hubs(self):
        hub_chips = {
            'nct6775': 'superio', 'nct6776': 'superio', 'nct6779': 'superio',
            'nct6796': 'superio', 'nct6798': 'superio', 'nct6687': 'superio',
            'f71858fg': 'fintek', 'f71882fg': 'fintek',
            'corsair': 'corsair', 'nzxt': 'nzxt',
            'smsc': 'smsc', 'w83795': 'winbond',
            'it87': 'ite', 'it8790': 'ite',
        }
        hwmon_fan_count: Dict[str, int] = {}
        for fan in self.fans.values():
            hwmon_fan_count[fan.hwmon_path] = hwmon_fan_count.get(fan.hwmon_path, 0) + 1

        for fan in self.fans.values():
            chip = fan.chip_name.lower()
            for pattern, hub_type in hub_chips.items():
                if pattern in chip:
                    if hwmon_fan_count.get(fan.hwmon_path, 0) >= 3:
                        fan.is_hub_channel = True
                        fan.hub_type = hub_type
                    break

    # ── live reading ──────────────────────────────────────────────────────────

    def read_all_fans(self) -> Dict[str, FanEntry]:
        for fan in self.fans.values():
            try:
                raw = self._read_file(fan.fan_input_file)
                fan.current_rpm = int(raw) if raw else 0
            except Exception:
                fan.current_rpm = 0

            if fan.pwm_file:
                try:
                    raw = self._read_file(fan.pwm_file)
                    fan.current_pwm     = int(raw) if raw else 0
                    fan.current_percent = round(fan.current_pwm / 255.0 * 100.0, 1)
                except Exception:
                    fan.current_pwm, fan.current_percent = 0, 0.0
            elif fan.max_rpm > 0 and fan.current_rpm > 0:
                fan.current_percent = round(
                    min(100.0, fan.current_rpm / fan.max_rpm * 100.0), 1)

            if fan.min_file:
                try:
                    fan.min_rpm = int(self._read_file(fan.min_file) or 0)
                except Exception:
                    pass
        return self.fans

    def read_all_temps(self) -> Dict[str, TempSensor]:
        """
        Read all temperatures.
        nvidia-smi: ONE batched call for all GPUs instead of per-sensor subprocess.
        """
        # hwmon + amd (fast sysfs/rocm reads)
        for sensor in self.temps.values():
            if sensor.source == 'hwmon':
                if sensor.input_file and os.path.exists(sensor.input_file):
                    raw = self._read_file(sensor.input_file)
                    if raw:
                        try:
                            sensor.value   = int(raw) / 1000.0
                            sensor.value_f = _c_to_f(sensor.value)
                        except Exception:
                            pass

        # nvidia: one subprocess call for all discovered GPUs
        if self._nvidia_indices:
            self._update_all_nvidia_temps()

        return self.temps

    def _update_all_nvidia_temps(self):
        """Single nvidia-smi call updates all GPU temperatures at once."""
        try:
            r = subprocess.run(
                ['nvidia-smi',
                 '--query-gpu=index,temperature.gpu',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=2)
            if r.returncode != 0:
                return
            for line in r.stdout.strip().split('\n'):
                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 2:
                    continue
                idx, temp_s = parts[0], parts[1]
                sid = f"nvidia_gpu{idx}"
                if sid in self.temps:
                    try:
                        self.temps[sid].value   = float(temp_s)
                        self.temps[sid].value_f = _c_to_f(self.temps[sid].value)
                    except ValueError:
                        pass
        except Exception:
            pass

    # ── zero-RPM helpers ──────────────────────────────────────────────────────

    def get_zero_rpm_fans(self) -> List[FanEntry]:
        return [f for f in self.fans.values() if f.current_rpm == 0]

    # ── control ───────────────────────────────────────────────────────────────

    def set_fan_pwm(self, fan_id: str, pwm: int,
                    safe_mode: bool = False) -> bool:
        """
        Set fan PWM (0-255).
        safe_mode=True: clamp to fan.min_rpm-equivalent PWM so fan never stalls.
        """
        fan = self.fans.get(fan_id)
        if not fan or not fan.pwm_file:
            return False

        pwm = max(0, min(255, pwm))

        # safe_mode: never go below the fan's minimum PWM
        if safe_mode and fan.min_rpm > 0 and fan.max_rpm > 0:
            min_pwm = int(fan.min_rpm / fan.max_rpm * 255)
            pwm = max(pwm, min_pwm)

        # Enable manual PWM using the chip-correct value
        if fan.pwm_enable_file:
            self._write_file(fan.pwm_enable_file, fan.pwm_manual_value)

        return self._write_file(fan.pwm_file, str(pwm))

    def set_fan_percent(self, fan_id: str, percent: float,
                        safe_mode: bool = False) -> bool:
        return self.set_fan_pwm(fan_id, int(percent / 100.0 * 255), safe_mode)

    def set_fan_dc_percent(self, fan_id: str, percent: float) -> bool:
        fan = self.fans.get(fan_id)
        if not fan:
            return False
        if fan.pwm_enable_file:
            # DC mode: write 0 for nct6775-style; it87 has no DC mode distinction
            dc_val = '0' if fan.pwm_auto_value == '2' else fan.pwm_manual_value
            self._write_file(fan.pwm_enable_file, dc_val)
        if fan.pwm_file:
            return self._write_file(fan.pwm_file, str(int(percent / 100.0 * 255)))
        return False

    def set_fan_auto(self, fan_id: str) -> bool:
        """
        Return fan to motherboard auto control.
        Uses chip-correct auto value: '2' for nct6775, '0' for it87.
        """
        fan = self.fans.get(fan_id)
        if not fan:
            return False
        if fan.pwm_enable_file:
            ok = self._write_file(fan.pwm_enable_file, fan.pwm_auto_value)
            if ok:
                fan.mode = 'pwm_auto'
            return ok
        logger.debug(f"Fan {fan_id}: no pwm_enable_file — cannot set auto")
        return False

    def rescan(self):
        self.fans.clear()
        self.temps.clear()
        self._nvidia_indices.clear()
        self._discover_all()
