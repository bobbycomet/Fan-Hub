"""
System stats collector using psutil.
Provides CPU, GPU, RAM, storage, network data for the System Overview panel.
Runs in PollingWorker thread — results emitted as a dict every poll cycle.
"""
import logging
import os
import time
from typing import Dict, Any, Optional

logger = logging.getLogger('fanhub.sysinfo')

try:
    import psutil
    _HAVE_PSUTIL = True
except ImportError:
    _HAVE_PSUTIL = False
    logger.warning("psutil not installed — system stats unavailable")


class SystemStatsCollector:
    """Lightweight collector; call .collect() once per poll cycle."""

    def __init__(self):
        self._last_net_time  = time.monotonic()
        self._last_net_bytes = {'sent': 0, 'recv': 0}
        self._last_disk_time = time.monotonic()
        self._last_disk_io   = {'read': 0, 'write': 0}
        self._cpu_cycle      = 0
        # Prime psutil CPU counter
        if _HAVE_PSUTIL:
            try:
                psutil.cpu_percent(interval=None)
                psutil.cpu_percent(percpu=True, interval=None)
            except Exception:
                pass

    def collect(self) -> Dict[str, Any]:
        if not _HAVE_PSUTIL:
            return {'available': False}

        out: Dict[str, Any] = {'available': True}
        self._cpu_cycle += 1

        # ── CPU ───────────────────────────────────────────────────────────────
        try:
            out['cpu_pct']       = psutil.cpu_percent(interval=None)
            out['cpu_pct_core']  = psutil.cpu_percent(percpu=True, interval=None)
            freq = psutil.cpu_freq()
            out['cpu_freq_mhz']  = freq.current if freq else 0.0
            out['cpu_freq_max']  = freq.max     if freq else 0.0
            out['cpu_cores']     = psutil.cpu_count(logical=False) or 1
            out['cpu_threads']   = psutil.cpu_count(logical=True)  or 1
        except Exception as e:
            logger.debug(f"CPU stats: {e}")

        # ── Memory ────────────────────────────────────────────────────────────
        try:
            vm = psutil.virtual_memory()
            out['ram_total_gb']  = vm.total  / 1e9
            out['ram_used_gb']   = vm.used   / 1e9
            out['ram_pct']       = vm.percent
            sw = psutil.swap_memory()
            out['swap_total_gb'] = sw.total / 1e9
            out['swap_used_gb']  = sw.used  / 1e9
            out['swap_pct']      = sw.percent
        except Exception as e:
            logger.debug(f"Memory stats: {e}")

        # ── Storage ───────────────────────────────────────────────────────────
        try:
            partitions = []
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    partitions.append({
                        'mountpoint': part.mountpoint,
                        'total_gb':   usage.total / 1e9,
                        'used_gb':    usage.used  / 1e9,
                        'pct':        usage.percent,
                        'fstype':     part.fstype,
                    })
                except PermissionError:
                    pass
            out['partitions'] = partitions

            now = time.monotonic()
            dt  = now - self._last_disk_time
            if dt >= 0.5:
                dio = psutil.disk_io_counters()
                if dio:
                    dr = dio.read_bytes  - self._last_disk_io['read']
                    dw = dio.write_bytes - self._last_disk_io['write']
                    out['disk_read_mb_s']  = max(0.0, dr / dt / 1e6)
                    out['disk_write_mb_s'] = max(0.0, dw / dt / 1e6)
                    self._last_disk_io  = {'read': dio.read_bytes, 'write': dio.write_bytes}
                    self._last_disk_time = now
        except Exception as e:
            logger.debug(f"Disk stats: {e}")

        # ── Network ───────────────────────────────────────────────────────────
        try:
            now = time.monotonic()
            dt  = now - self._last_net_time
            nio = psutil.net_io_counters()
            if nio and dt >= 0.5:
                ds = nio.bytes_sent - self._last_net_bytes['sent']
                dr = nio.bytes_recv - self._last_net_bytes['recv']
                out['net_up_mb_s']   = max(0.0, ds / dt / 1e6)
                out['net_down_mb_s'] = max(0.0, dr / dt / 1e6)
                self._last_net_bytes = {'sent': nio.bytes_sent, 'recv': nio.bytes_recv}
                self._last_net_time  = now

            # Active interface info
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            ifaces = []
            for name, st in stats.items():
                if st.isup and name != 'lo':
                    addr_info = addrs.get(name, [])
                    ipv4 = next((a.address for a in addr_info
                                 if a.family.name == 'AF_INET'), '')
                    ifaces.append({
                        'name':  name,
                        'ip':    ipv4,
                        'speed': st.speed,   # Mbps
                    })
            out['net_interfaces'] = ifaces
        except Exception as e:
            logger.debug(f"Net stats: {e}")

        # ── GPU (via nvidia-smi / rocm-smi if available) ─────────────────────
        if self._cpu_cycle % 3 == 0:   # don't hammer on every cycle
            out.update(self._gpu_stats())

        return out

    def _gpu_stats(self) -> Dict[str, Any]:
        g: Dict[str, Any] = {}
        # NVIDIA
        try:
            import subprocess
            r = subprocess.run(
                ['nvidia-smi',
                 '--query-gpu=utilization.gpu,memory.used,memory.total,power.draw,clocks.current.graphics,clocks.current.memory',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                parts = [p.strip() for p in r.stdout.strip().split(',')]
                if len(parts) >= 6:
                    g['gpu_util_pct']    = _float(parts[0])
                    g['gpu_vram_used_mb']= _float(parts[1])
                    g['gpu_vram_total_mb']=_float(parts[2])
                    g['gpu_power_w']     = _float(parts[3])
                    g['gpu_core_mhz']    = _float(parts[4])
                    g['gpu_mem_mhz']     = _float(parts[5])
                    g['gpu_vendor']      = 'nvidia'
                    return g
        except Exception:
            pass

        # AMD
        try:
            import subprocess
            r = subprocess.run(
                ['rocm-smi', '--showuse', '--showmemuse',
                 '--showpower', '--showclocks', '--json'],
                capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                import json
                data = json.loads(r.stdout)
                card = next(iter(data.values()), {})
                g['gpu_util_pct']     = _float(card.get('GPU use (%)', 0))
                g['gpu_vram_used_mb'] = _float(card.get('VRAM Total Used Memory (B)', 0)) / 1e6
                g['gpu_vram_total_mb']= _float(card.get('VRAM Total Memory (B)', 0)) / 1e6
                g['gpu_power_w']      = _float(card.get('Average Graphics Package Power (W)', 0))
                g['gpu_vendor']       = 'amd'
        except Exception:
            pass

        return g


def _float(v) -> float:
    try:
        return float(str(v).replace('[Not Supported]', '0').strip())
    except Exception:
        return 0.0
