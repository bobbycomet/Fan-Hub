"""
Hardware sensor reading, temperatures, fan RPMs, voltages.
GPU fan control:
  AMD  — full PWM via amdgpu hwmon (fan1_input / pwm1 / pwm1_enable)
  NVIDIA — hwmon pwm1 when CoolBits allows it, nvidia-settings fallback,
           nvidia-smi read-only for RPM/speed% when neither is available.
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

# Fan connection type constants
FAN_CONN_SYSF    = 'sys_fan'
FAN_CONN_CPU     = 'cpu_fan'
FAN_CONN_CHASSIS = 'chassis_fan'
FAN_CONN_PUMP    = 'pump'
FAN_CONN_LAPTOP  = 'laptop'
FAN_CONN_USB     = 'usb_hub'
FAN_CONN_GENERIC = 'generic'
FAN_CONN_GPU_AMD    = 'gpu_amd'      # AMD GPU fan via amdgpu hwmon
FAN_CONN_GPU_NVIDIA = 'gpu_nvidia'   # NVIDIA GPU fan
FAN_CONN_GPU_INTEL  = 'gpu_intel'    # Intel GPU (i915/xe) — temp only, no fan ctrl

# Chips using 0=auto, 1=manual (it87 family, opposite of nct6775)
_IT87_CHIPS = {'it87', 'it8620', 'it8628', 'it8686', 'it8790', 'it8792', 'it8795'}

# AMD GPU chip names in hwmon
_AMD_GPU_CHIPS = {'amdgpu', 'radeon'}

# NVIDIA GPU chip names in hwmon
_NVIDIA_GPU_CHIPS = {'nvidia'}

# Intel GPU chip names in hwmon (i915, xe driver)
# Intel integrated and Arc GPUs expose a hwmon node via i915/xe drivers
_INTEL_GPU_CHIPS = {'i915', 'xe'}


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
    # PWM mode values (chip-specific)
    pwm_auto_value: str = '2'
    pwm_manual_value: str = '1'
    # GPU-specific fields
    gpu_index: Optional[int] = None      # GPU index (0, 1, …)
    gpu_vendor: Optional[str] = None     # 'amd' | 'nvidia'
    # NVIDIA-specific: can we use hwmon pwm, or must we use nvidia-settings?
    nvidia_use_hwmon: bool = False
    nvidia_use_settings: bool = False    # nvidia-settings fallback available
    fan_index: int = 0                   # fan index within the GPU (multi-fan cards)


@dataclass
class TempSensor:
    id: str
    label: str
    value: float = 0.0
    value_f: float = 32.0
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
    if any(k in cl for k in _AMD_GPU_CHIPS):    return FAN_CONN_GPU_AMD
    if any(k in cl for k in _NVIDIA_GPU_CHIPS): return FAN_CONN_GPU_NVIDIA
    if any(k in cl for k in _INTEL_GPU_CHIPS):  return FAN_CONN_GPU_INTEL
    if any(k in ll for k in _PUMP_KEYWORDS):    return FAN_CONN_PUMP
    if any(k in ll for k in _CPU_KEYWORDS):     return FAN_CONN_CPU
    if any(k in ll for k in _CHASSIS_KEYWORDS): return FAN_CONN_CHASSIS
    if any(k in cl for k in _LAPTOP_CHIPS):     return FAN_CONN_LAPTOP
    return FAN_CONN_SYSF


def _c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)


# ── Sensor label translation ──────────────────────────────────────────────────

_LABEL_MAP = {
    # ── SuperIO motherboard sensors ───────────────────────────────────────────
    # These names come from what the SuperIO chip labels its own inputs.
    # "SYSTIN" means the system/motherboard thermistor; "CPUTIN" is the socket.
    'systin':   'System Temperature',
    'systin2':  'System Temperature 2',
    'cputin':   'CPU Socket Temperature',
    'auxtin':   'Auxiliary Sensor',
    'auxtin0':  'Auxiliary Sensor 1',
    'auxtin1':  'Auxiliary Sensor 2',
    'auxtin2':  'Auxiliary Sensor 3',
    'auxtin3':  'Auxiliary Sensor 4',
    # PECI — Platform Environment Control Interface, Intel's CPU temp bus
    'peci agent 0': 'CPU Temperature',
    'peci agent 1': 'CPU 2 Temperature',
    'peci agent 2': 'CPU 3 Temperature',
    'peci agent 3': 'CPU 4 Temperature',
    # PCH — Platform Controller Hub (the "southbridge" chip on Intel boards)
    'pch_cpu_temp':           'Platform Hub — CPU Side',
    'pch_chip_temp':          'Platform Hub — Chip',
    'pch_chip_cpu_max_temp':  'Platform Hub — Peak',
    # ── AMD CPU (k10temp driver) ───────────────────────────────────────────────
    # Tctl is the reported control temp (may include offset); Tdie is the real die.
    # Tccd = Core Complex Die — one per chiplet on Ryzen/EPYC.
    'tctl':  'CPU Temperature (Control)',
    'tdie':  'CPU Temperature (Die)',
    'tccd1': 'CPU Chiplet 1 Temperature',
    'tccd2': 'CPU Chiplet 2 Temperature',
    'tccd3': 'CPU Chiplet 3 Temperature',
    'tccd4': 'CPU Chiplet 4 Temperature',
    'tccd5': 'CPU Chiplet 5 Temperature',
    'tccd6': 'CPU Chiplet 6 Temperature',
    'tccd7': 'CPU Chiplet 7 Temperature',
    'tccd8': 'CPU Chiplet 8 Temperature',
    # ── Intel CPU (coretemp driver) ───────────────────────────────────────────
    'package id 0': 'CPU Package Temperature',
    'package id 1': 'CPU Package 2 Temperature',
    # ── NVMe drives ───────────────────────────────────────────────────────────
    # "Composite" is the drive's overall reported temperature (usually hottest).
    'composite': 'Drive Temperature',
    'sensor 1':  'Drive Sensor 1',
    'sensor 2':  'Drive Sensor 2',
    # ── AMD GPU (amdgpu driver) ───────────────────────────────────────────────
    # Edge = die surface near output; Junction/Hotspot = hottest measured point.
    'edge':     'GPU Temperature',
    'junction': 'GPU Hotspot Temperature',
    'mem':      'GPU Memory Temperature',
    'mem0':     'GPU Memory Temperature',
    # ── Intel GPU (i915 / xe drivers) ────────────────────────────────────────
    'gpu 0':              'GPU Temperature',
    'gpu 1':              'GPU Temperature 2',
    'pkg power limit max':'GPU Power Limit',
    'card0-acpi-0':       'GPU Temperature',
}

_CHIP_SOURCE = {
    # SuperIO motherboard controllers
    'nct6775': 'Motherboard', 'nct6776': 'Motherboard', 'nct6779': 'Motherboard',
    'nct6791': 'Motherboard', 'nct6792': 'Motherboard', 'nct6793': 'Motherboard',
    'nct6795': 'Motherboard', 'nct6796': 'Motherboard', 'nct6798': 'Motherboard',
    'nct6687': 'Motherboard', 'it87': 'Motherboard', 'it8620': 'Motherboard',
    'it8628': 'Motherboard', 'it8686': 'Motherboard', 'it8790': 'Motherboard',
    'f71858fg': 'Motherboard', 'f71882fg': 'Motherboard', 'w83795': 'Motherboard',
    # CPU thermal drivers
    'k10temp': 'CPU', 'coretemp': 'CPU',
    # Storage
    'nvme': 'SSD',
    # GPU drivers
    'amdgpu': 'GPU (AMD)', 'radeon': 'GPU (AMD)',
    'nvidia': 'GPU (NVIDIA)',
    'i915': 'GPU (Intel)', 'xe': 'GPU (Intel Arc)',
    'i915_thermal_exhaust': 'GPU (Intel)',
    # Intel power/thermal subsystems
    'intel_rapl_msr':  'CPU Power',
    'intel_rapl_mmio': 'CPU Power',
    # Platform controller hubs
    'pch_skylake': 'Platform Hub', 'pch_broxton': 'Platform Hub',
    # Laptops and special devices
    'thinkpad': 'ThinkPad', 'acpitz': 'System',
    'asus-nb-wmi': 'Laptop', 'dell_smm': 'Laptop',
    'applesmc': 'Laptop', 'iwlwifi': 'Wi-Fi Adapter',
}


def _friendly_temp_label(raw_label: str, chip: str, sensor_num: int) -> str:
    """
    Translate a raw hwmon label + chip name into plain-English sensor names.

    Strategy:
      1. Exact match in _LABEL_MAP — use the human name, prefix with chip source
         only when the chip source adds meaningful context (e.g. "CPU" prefix
         for a motherboard PECI sensor).
      2. Pattern match for "Core N" (Intel), "Package id N" (Intel).
      3. Pattern match for generic "Temp N" or bare numbers — use chip source.
      4. Fallback: chip source + title-cased raw label.
    """
    ll      = raw_label.strip().lower()
    chip_l  = chip.strip().lower()
    source  = next((v for k, v in _CHIP_SOURCE.items() if k in chip_l), None)

    # ── 1. Exact label map hit ────────────────────────────────────────────────
    if ll in _LABEL_MAP:
        human = _LABEL_MAP[ll]
        # For sensors whose human name doesn't already encode the source
        # (e.g. "System Temperature" on a SuperIO chip → "Motherboard System Temperature")
        # but skip for GPU/Drive/CPU labels that already contain their context.
        if source and not any(human.startswith(p) for p in
                              ('CPU', 'GPU', 'Drive', 'SSD', 'Platform',
                               'System', 'Laptop', 'ThinkPad', 'Wi-Fi')):
            return f"{source} — {human}"
        return human

    # ── 2. "Core N" — Intel per-core sensor ──────────────────────────────────
    m = re.match(r'^core\s+(\d+)$', ll)
    if m:
        return f"CPU Core {m.group(1)} Temperature"

    # ── 3. "Package id N" ─────────────────────────────────────────────────────
    m = re.match(r'^package id\s+(\d+)$', ll)
    if m:
        n = int(m.group(1))
        return "CPU Package Temperature" if n == 0 else f"CPU Package {n} Temperature"

    # ── 4. Generic "Sensor N" ─────────────────────────────────────────────────
    m = re.match(r'^sensor\s+(\d+)$', ll)
    if m:
        pfx = source or chip.title()
        return f"{pfx} — Sensor {m.group(1)}"

    # ── 5. Bare "Temp" / "Temp N" / just a number ─────────────────────────────
    if source:
        if re.match(r'^temp\s*\d*$', ll, re.IGNORECASE) or re.match(r'^\d+$', ll):
            return f"{source} — Sensor {sensor_num}"
        # Known chip, unknown label: prefix + title-case
        return f"{source} — {raw_label.strip().title()}"

    # ── 6. Unknown chip ───────────────────────────────────────────────────────
    return f"{chip.title()}: {raw_label.strip().title()}"


# ── NVIDIA helpers ────────────────────────────────────────────────────────────

def _nvidia_settings_available() -> bool:
    try:
        r = subprocess.run(['nvidia-settings', '--version'],
                           capture_output=True, timeout=2)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _nvidia_fan_count(gpu_index: int) -> int:
    """Return number of fans on a given GPU via nvidia-smi."""
    try:
        r = subprocess.run(
            ['nvidia-smi', f'--id={gpu_index}',
             '--query-gpu=fan.speed', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip() not in ('N/A', ''):
            return 1   # single fan reported — multi-fan via nvidia-settings
    except Exception:
        pass
    return 1   # default assumption


class HardwareMonitor:

    def __init__(self):
        self.fans:  Dict[str, FanEntry]   = {}
        self.temps: Dict[str, TempSensor] = {}
        self._nvidia_indices: List[str]   = []
        self._nvidia_settings_ok: bool    = False
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
        self._discover_hwmon_fans()     # covers motherboard + AMD GPU + NVIDIA hwmon
        self._discover_hwmon_temps()
        self._discover_nvidia_temps()   # reads GPU indices for batched temp updates
        self._discover_nvidia_fans()    # adds NVIDIA fans not caught by hwmon
        self._discover_amd_temps()
        self._detect_fan_modes()
        self._detect_hubs()
        logger.info(f"Discovered {len(self.fans)} fans "
                    f"({sum(1 for f in self.fans.values() if f.gpu_vendor)} GPU fans), "
                    f"{len(self.temps)} sensors")

    def _discover_hwmon_fans(self):
        if not os.path.exists(HWMON_BASE):
            logger.warning("hwmon not found")
            return
        for hwmon_dir in sorted(glob.glob(os.path.join(HWMON_BASE, 'hwmon*'))):
            chip = self._get_chip_name(hwmon_dir)
            chip_l = chip.lower()

            # Determine chip family
            is_it87    = any(c in chip_l for c in _IT87_CHIPS)
            is_amd_gpu   = any(c in chip_l for c in _AMD_GPU_CHIPS)
            is_nv_gpu    = any(c in chip_l for c in _NVIDIA_GPU_CHIPS)
            is_intel_gpu = any(c in chip_l for c in _INTEL_GPU_CHIPS)

            # GPU index: read from device path symlink
            gpu_index  = self._detect_gpu_index(hwmon_dir)
            gpu_vendor = ('amd' if is_amd_gpu
                          else ('nvidia' if is_nv_gpu
                          else ('intel' if is_intel_gpu else None)))

            auto_val   = '0' if is_it87 else '2'
            manual_val = '1'

            for fan_input in sorted(glob.glob(os.path.join(hwmon_dir, 'fan*_input'))):
                m = re.search(r'fan(\d+)_input', os.path.basename(fan_input))
                if not m:
                    continue
                n = m.group(1)

                # Label
                raw_lbl = (self._read_file(os.path.join(hwmon_dir, f'fan{n}_label'))
                           or f'Fan {n}')
                if is_amd_gpu:
                    label = f"GPU (AMD){f' {gpu_index}' if gpu_index else ''} — Fan {n}"
                elif is_nv_gpu:
                    label = f"GPU (NVIDIA){f' {gpu_index}' if gpu_index else ''} — Fan {n}"
                elif is_intel_gpu:
                    label = f"GPU (Intel){f' {gpu_index}' if gpu_index else ''} — Fan {n}"
                else:
                    label = self._fallback_fan_label(raw_lbl, chip, int(n))

                def _opt(p):
                    return p if os.path.exists(p) else None

                pwm_file        = _opt(os.path.join(hwmon_dir, f'pwm{n}'))
                pwm_enable_file = _opt(os.path.join(hwmon_dir, f'pwm{n}_enable'))
                min_file        = _opt(os.path.join(hwmon_dir, f'fan{n}_min'))
                max_file        = _opt(os.path.join(hwmon_dir, f'fan{n}_max'))

                conn = _classify_conn(raw_lbl, chip)
                fan_id = f"{os.path.basename(hwmon_dir)}_fan{n}"

                # For NVIDIA hwmon: check if pwm is actually writable
                nvidia_use_hwmon = False
                if is_nv_gpu and pwm_file:
                    nvidia_use_hwmon = os.access(pwm_file, os.W_OK)

                self.fans[fan_id] = FanEntry(
                    id=fan_id, label=label,
                    hwmon_path=hwmon_dir, fan_input_file=fan_input,
                    pwm_file=pwm_file, pwm_enable_file=pwm_enable_file,
                    min_file=min_file, max_file=max_file,
                    connection_type=conn, chip_name=chip, controllable=True,
                    pwm_auto_value=auto_val, pwm_manual_value=manual_val,
                    gpu_index=gpu_index, gpu_vendor=gpu_vendor,
                    nvidia_use_hwmon=nvidia_use_hwmon,
                    fan_index=int(n) - 1,
                )

    def _detect_gpu_index(self, hwmon_dir: str) -> Optional[int]:
        """Extract GPU index from the hwmon device path (e.g. /sys/…/card0/…)."""
        try:
            real = os.path.realpath(hwmon_dir)
            m = re.search(r'card(\d+)', real)
            if m:
                return int(m.group(1))
            m = re.search(r'(\d{4}):(\d{2}):(\d{2})\.(\d)', real)
            if m:
                return None   # PCI address — no simple index
        except Exception:
            pass
        return None

    def _fallback_fan_label(self, raw: str, chip: str, n: int) -> str:
        """Simple label for non-GPU fans (used in hwmon fan discovery)."""
        src = next((v for k, v in _CHIP_SOURCE.items() if k in chip.lower()), chip)
        rl = raw.lower()
        if re.match(r'^fan\s*\d*$', rl):
            return f"{src} — Fan {n}"
        return f"{src} — {raw.title()}"

    def _discover_nvidia_fans(self):
        """
        Discover NVIDIA GPU fans that are NOT already covered by an hwmon node.
        Uses nvidia-smi for RPM reading; nvidia-settings for speed control.
        """
        # Check if nvidia-smi is available and returns GPU data
        try:
            r = subprocess.run(
                ['nvidia-smi', '--query-gpu=index,name,fan.speed',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=4)
            if r.returncode != 0:
                return
        except FileNotFoundError:
            return

        # Check nvidia-settings availability once
        self._nvidia_settings_ok = _nvidia_settings_available()

        for line in r.stdout.strip().split('\n'):
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 3:
                continue
            idx_s, name, speed_s = parts[0], parts[1], parts[2]
            if speed_s == 'N/A':
                continue   # GPU has no fan (blower cards without tachometer)

            try:
                gpu_idx = int(idx_s)
            except ValueError:
                continue

            fan_id = f"nvidia_gpu{gpu_idx}_fan0"

            # Skip if already discovered via hwmon
            if fan_id in self.fans:
                continue
            # Also skip if ANY hwmon fan entry already covers this GPU index
            already = any(
                f.gpu_vendor == 'nvidia' and f.gpu_index == gpu_idx
                for f in self.fans.values()
            )
            if already:
                continue

            try:
                speed_pct = float(speed_s)
            except ValueError:
                speed_pct = 0.0

            # Try to read actual RPM via nvidia-settings at discovery time
            initial_rpm = 0
            if self._nvidia_settings_ok:
                try:
                    r2 = subprocess.run(
                        ['nvidia-settings',
                         f'--query=[fan:0]/GPUCurrentFanSpeedRPM'],
                        capture_output=True, text=True, timeout=2)
                    if r2.returncode == 0:
                        m = re.search(r':\s*(\d+)\s*$', r2.stdout.strip(), re.MULTILINE)
                        if m:
                            initial_rpm = int(m.group(1))
                except Exception:
                    pass

            self.fans[fan_id] = FanEntry(
                id=fan_id,
                label=f"GPU (NVIDIA {name}) — Fan",
                hwmon_path='',
                fan_input_file='',
                pwm_file=None,
                pwm_enable_file=None,
                min_file=None, max_file=None,
                connection_type=FAN_CONN_GPU_NVIDIA,
                chip_name='nvidia',
                controllable=self._nvidia_settings_ok,
                gpu_index=gpu_idx, gpu_vendor='nvidia',
                nvidia_use_hwmon=False,
                nvidia_use_settings=self._nvidia_settings_ok,
                current_percent=speed_pct,
                current_rpm=initial_rpm,
                mode='pwm_auto',
            )
            logger.info(f"NVIDIA GPU{gpu_idx} fan: "
                        f"settings={'yes' if self._nvidia_settings_ok else 'no (read-only)'}")

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
            if fan.gpu_vendor == 'nvidia' and not fan.nvidia_use_hwmon:
                # NVIDIA fans without hwmon: mode is always software-controlled
                # leave mode as set during discovery
                continue
            if fan.pwm_enable_file:
                val = self._read_file(fan.pwm_enable_file)
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
            elif fan.gpu_vendor:
                fan.mode = 'pwm_auto'  # GPU default
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
            if fan.hwmon_path:
                hwmon_fan_count[fan.hwmon_path] = (
                    hwmon_fan_count.get(fan.hwmon_path, 0) + 1)
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
            # ── NVIDIA fans: choose the right read path ───────────────────────
            # nvidia_use_hwmon only controls the WRITE path (pwm control).
            # For reading, always prefer the hwmon fan_input_file (gives real RPM)
            # when it exists.  Only fall back to nvidia-smi (returns % only) when
            # there is no hwmon tachometer file at all.
            if fan.gpu_vendor == 'nvidia':
                if fan.fan_input_file and os.path.exists(fan.fan_input_file):
                    # hwmon tachometer present — read RPM the normal way
                    try:
                        raw = self._read_file(fan.fan_input_file)
                        fan.current_rpm = int(raw) if raw else 0
                    except Exception:
                        fan.current_rpm = 0
                    # Read current PWM / percent from hwmon if available
                    if fan.pwm_file and os.path.exists(fan.pwm_file):
                        try:
                            raw = self._read_file(fan.pwm_file)
                            fan.current_pwm     = int(raw) if raw else 0
                            fan.current_percent = round(
                                fan.current_pwm / 255.0 * 100.0, 1)
                        except Exception:
                            fan.current_pwm, fan.current_percent = 0, 0.0
                    elif fan.current_rpm > 0 and fan.max_rpm > 0:
                        fan.current_percent = round(
                            min(100.0, fan.current_rpm / fan.max_rpm * 100.0), 1)
                else:
                    # No hwmon tachometer — use nvidia-smi (returns % only)
                    self._read_nvidia_fan(fan)
                continue

            # ── Standard hwmon read (motherboard fans, AMD GPU fans) ──────────
            if fan.fan_input_file:
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
            # If no PWM readback file: leave current_percent as-is (it was set
            # when we last wrote a speed command).  Only fall back to RPM-based
            # estimation if we have never commanded a speed (current_percent==0).
            elif fan.current_percent == 0.0 and fan.max_rpm > 0 and fan.current_rpm > 0:
                fan.current_percent = round(
                    min(100.0, fan.current_rpm / fan.max_rpm * 100.0), 1)

            if fan.min_file:
                try:
                    fan.min_rpm = int(self._read_file(fan.min_file) or 0)
                except Exception:
                    pass
            if fan.max_file:
                try:
                    v = int(self._read_file(fan.max_file) or 0)
                    if v > 0:
                        fan.max_rpm = v
                except Exception:
                    pass
        return self.fans

    def _read_nvidia_fan(self, fan: FanEntry):
        """
        Read NVIDIA fan data when no hwmon tachometer is present.
        Priority:
          1. nvidia-settings GPUCurrentFanSpeedRPM (actual RPM, best)
          2. nvidia-smi fan.speed (% only, no RPM)
        """
        # Try nvidia-settings for actual RPM first
        if fan.nvidia_use_settings and fan.gpu_index is not None:
            try:
                r = subprocess.run(
                    ['nvidia-settings',
                     f'--query=[fan:{fan.fan_index}]/GPUCurrentFanSpeedRPM'],
                    capture_output=True, text=True, timeout=2)
                if r.returncode == 0:
                    # Output format: "Attribute 'GPUCurrentFanSpeedRPM' (host:0[fan:0]): 1234"
                    m = re.search(r':\s*(\d+)\s*$', r.stdout.strip(), re.MULTILINE)
                    if m:
                        fan.current_rpm = int(m.group(1))
                        # Also update % from RPM if we have a max
                        if fan.max_rpm > 0:
                            fan.current_percent = round(
                                min(100.0, fan.current_rpm / fan.max_rpm * 100.0), 1)
                        return
            except Exception:
                pass

        # Fall back to nvidia-smi fan.speed (gives % only, sets current_percent)
        try:
            r = subprocess.run(
                ['nvidia-smi', f'--id={fan.gpu_index}',
                 '--query-gpu=fan.speed',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                val = r.stdout.strip()
                if val and val != 'N/A':
                    fan.current_percent = float(val)
                    # current_rpm stays 0 — nvidia-smi cannot give RPM
        except Exception:
            pass

    def read_all_temps(self) -> Dict[str, TempSensor]:
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
        if self._nvidia_indices:
            self._update_all_nvidia_temps()
        # Refresh AMD rocm-smi temps (not exposed via hwmon on all systems)
        self._refresh_amd_rocm_temps()
        return self.temps

    def _refresh_amd_rocm_temps(self):
        """Refresh any AMD GPU sensors that were discovered via rocm-smi."""
        amd_rocm = [s for s in self.temps.values() if s.source == 'amd']
        if not amd_rocm:
            return
        try:
            import json as _json
            r = subprocess.run(['rocm-smi', '--showtemp', '--json'],
                               capture_output=True, text=True, timeout=3)
            if r.returncode != 0:
                return
            data = _json.loads(r.stdout)
            for card, info in data.items():
                sid = f'amd_{card}'
                if sid in self.temps:
                    temp = float(info.get('Temperature (Sensor junction) (C)', 0))
                    self.temps[sid].value   = temp
                    self.temps[sid].value_f = _c_to_f(temp)
        except Exception:
            pass

    def _update_all_nvidia_temps(self):
        try:
            r = subprocess.run(
                ['nvidia-smi', '--query-gpu=index,temperature.gpu',
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
        fan = self.fans.get(fan_id)
        if not fan:
            return False

        # ── NVIDIA fan — use nvidia-settings or hwmon ─────────────────────────
        if fan.gpu_vendor == 'nvidia':
            return self._set_nvidia_fan_percent(
                fan, round(pwm / 255.0 * 100), safe_mode)

        if not fan.pwm_file:
            return False

        pwm = max(0, min(255, pwm))
        if safe_mode and fan.min_rpm > 0 and fan.max_rpm > 0:
            min_pwm = int(fan.min_rpm / fan.max_rpm * 255)
            pwm = max(pwm, min_pwm)

        if fan.pwm_enable_file:
            self._write_file(fan.pwm_enable_file, fan.pwm_manual_value)

        ok = self._write_file(fan.pwm_file, str(pwm))
        if ok:
            # Update in-memory state immediately so the UI reflects the new
            # speed before the next poll cycle reads it back from sysfs.
            fan.current_pwm     = pwm
            fan.current_percent = round(pwm / 255.0 * 100.0, 1)
        return ok

    def set_fan_percent(self, fan_id: str, percent: float,
                        safe_mode: bool = False) -> bool:
        fan = self.fans.get(fan_id)
        if not fan:
            return False
        if fan.gpu_vendor == 'nvidia':
            return self._set_nvidia_fan_percent(fan, percent, safe_mode)
        return self.set_fan_pwm(fan_id, int(percent / 100.0 * 255), safe_mode)

    def set_fan_dc_percent(self, fan_id: str, percent: float) -> bool:
        fan = self.fans.get(fan_id)
        if not fan:
            return False
        if fan.gpu_vendor:
            return self.set_fan_percent(fan_id, percent)
        if fan.pwm_enable_file:
            dc_val = '0' if fan.pwm_auto_value == '2' else fan.pwm_manual_value
            self._write_file(fan.pwm_enable_file, dc_val)
        if fan.pwm_file:
            pwm = int(percent / 100.0 * 255)
            ok = self._write_file(fan.pwm_file, str(pwm))
            if ok:
                fan.current_pwm     = pwm
                fan.current_percent = round(percent, 1)
            return ok
        return False

    def _set_nvidia_fan_percent(self, fan: FanEntry,
                                 percent: float, safe_mode: bool = False) -> bool:
        """
        Set NVIDIA GPU fan speed.
        Priority: hwmon pwm1 (if writable) → nvidia-settings → read-only warning.
        """
        percent = max(0.0, min(100.0, percent))
        if safe_mode:
            percent = max(percent, 20.0)   # NVIDIA fans: 20% absolute minimum in safe mode

        # Path A: hwmon pwm1 is writable (CoolBits=4 enables this)
        if fan.nvidia_use_hwmon and fan.pwm_file:
            if fan.pwm_enable_file:
                self._write_file(fan.pwm_enable_file, fan.pwm_manual_value)
            pwm = int(percent / 100.0 * 255)
            ok = self._write_file(fan.pwm_file, str(pwm))
            if ok:
                fan.current_percent = percent
                fan.mode = 'pwm_manual'
            return ok

        # Path B: nvidia-settings (requires X11/Wayland session + CoolBits)
        if fan.nvidia_use_settings and fan.gpu_index is not None:
            ok = self._nvidia_settings_set_fan(fan, percent)
            if ok:
                fan.current_percent = percent
            return ok

        logger.warning(
            f"NVIDIA GPU{fan.gpu_index} fan: no write path available. "
            "Enable CoolBits=4 in xorg.conf, or install nvidia-settings.")
        return False

    def _nvidia_settings_set_fan(self, fan: FanEntry, percent: float) -> bool:
        """Use nvidia-settings to enable manual fan control and set speed."""
        gpu_idx = fan.gpu_index
        fan_idx = fan.fan_index
        try:
            # Step 1: enable manual fan control for this GPU
            r1 = subprocess.run(
                ['nvidia-settings',
                 f'--assign=[gpu:{gpu_idx}]/GPUFanControlState=1'],
                capture_output=True, timeout=4)
            if r1.returncode != 0:
                logger.warning(f"nvidia-settings GPUFanControlState failed for GPU {gpu_idx}")
                return False
            # Step 2: set target fan speed
            r2 = subprocess.run(
                ['nvidia-settings',
                 f'--assign=[fan:{fan_idx}]/GPUTargetFanSpeed={int(percent)}'],
                capture_output=True, timeout=4)
            ok = r2.returncode == 0
            if ok:
                fan.current_percent = percent
                fan.mode = 'pwm_manual'
            return ok
        except FileNotFoundError:
            logger.warning("nvidia-settings not found")
            fan.nvidia_use_settings = False
            return False
        except Exception as e:
            logger.error(f"nvidia-settings error: {e}")
            return False

    def set_fan_auto(self, fan_id: str) -> bool:
        fan = self.fans.get(fan_id)
        if not fan:
            return False

        # ── NVIDIA auto restore ───────────────────────────────────────────────
        if fan.gpu_vendor == 'nvidia':
            return self._set_nvidia_fan_auto(fan)

        if fan.pwm_enable_file:
            ok = self._write_file(fan.pwm_enable_file, fan.pwm_auto_value)
            if ok:
                fan.mode = 'pwm_auto'
            return ok
        logger.debug(f"Fan {fan_id}: no pwm_enable_file — cannot set auto")
        return False

    def _set_nvidia_fan_auto(self, fan: FanEntry) -> bool:
        """Return NVIDIA GPU fan to driver automatic control."""
        # Path A: hwmon
        if fan.nvidia_use_hwmon and fan.pwm_enable_file:
            ok = self._write_file(fan.pwm_enable_file, fan.pwm_auto_value)
            if ok:
                fan.mode = 'pwm_auto'
            return ok
        # Path B: nvidia-settings — set GPUFanControlState=0 (auto)
        if fan.nvidia_use_settings and fan.gpu_index is not None:
            try:
                r = subprocess.run(
                    ['nvidia-settings',
                     f'--assign=[gpu:{fan.gpu_index}]/GPUFanControlState=0'],
                    capture_output=True, timeout=4)
                if r.returncode == 0:
                    fan.mode = 'pwm_auto'
                    return True
            except Exception as e:
                logger.error(f"nvidia-settings auto restore: {e}")
        return False

    def get_gpu_fan_info(self) -> Dict[str, dict]:
        """
        Return a summary of GPU fan control capability for display in the UI.
        """
        result = {}
        for fid, fan in self.fans.items():
            if not fan.gpu_vendor:
                continue
            if fan.gpu_vendor == 'nvidia':
                if fan.nvidia_use_hwmon:
                    method = 'hwmon (full PWM control)'
                elif fan.nvidia_use_settings:
                    method = 'nvidia-settings (requires X/Wayland session)'
                else:
                    method = 'read-only (enable CoolBits=4 for control)'
            else:
                method = 'hwmon (full PWM control)' if fan.pwm_file else 'read-only'
            result[fid] = {
                'label':       fan.label,
                'vendor':      fan.gpu_vendor,
                'gpu_index':   fan.gpu_index,
                'method':      method,
                'controllable': fan.controllable,
            }
        return result

    def rescan(self):
        self.fans.clear()
        self.temps.clear()
        self._nvidia_indices.clear()
        self._nvidia_settings_ok = False
        self._discover_all()
