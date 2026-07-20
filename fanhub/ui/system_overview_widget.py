"""
System Overview widget — shown at the top of the Dashboard tab.

Displays a compact row of stat cards: CPU, GPU, RAM, Storage, Network.
Updates via the stats_updated signal from PollingWorker (every 2 cycles).
"""
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt


def _pct_color(pct: float) -> str:
    if pct >= 90: return '#ff4444'
    if pct >= 70: return '#ffaa44'
    return '#44ddaa'


class _StatCard(QFrame):
    """Single metric card: icon + title + primary value + secondary."""

    def __init__(self, icon: str, title: str):
        super().__init__()
        self.setObjectName('statCard')
        self.setStyleSheet(
            'QFrame#statCard { background:#0a0e1a; border:1px solid #1a2840; '
            'border-radius:6px; }')
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setFixedHeight(80)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)

        hdr = QHBoxLayout()
        hdr.setSpacing(5)
        ico = QLabel(icon)
        ico.setStyleSheet('font-size:14px; background:transparent;')
        hdr.addWidget(ico)
        ttl = QLabel(title)
        ttl.setStyleSheet('color:#556677; font-size:10px; background:transparent;')
        hdr.addWidget(ttl)
        hdr.addStretch()
        lay.addLayout(hdr)

        self._val = QLabel('—')
        self._val.setStyleSheet(
            'color:#d4e5f7; font-size:15px; font-weight:bold; background:transparent;')
        lay.addWidget(self._val)

        self._sub = QLabel('')
        self._sub.setStyleSheet('color:#445566; font-size:10px; background:transparent;')
        self._sub.setWordWrap(False)
        lay.addWidget(self._sub)

    def update(self, value: str, sub: str = '', color: str = '#d4e5f7'):
        self._val.setText(value)
        self._val.setStyleSheet(
            f'color:{color}; font-size:15px; font-weight:bold; background:transparent;')
        self._sub.setText(sub)


class SystemOverviewWidget(QWidget):
    """Horizontal strip of stat cards shown above the temperature grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(8)

        self._cpu  = _StatCard('🔲', 'CPU')
        self._gpu  = _StatCard('🎮', 'GPU')
        self._ram  = _StatCard('💾', 'Memory')
        self._disk = _StatCard('💿', 'Storage')
        self._net  = _StatCard('🌐', 'Network')

        for card in (self._cpu, self._gpu, self._ram, self._disk, self._net):
            lay.addWidget(card)

    def on_stats(self, stats: dict):
        if not stats.get('available'):
            return

        # ── CPU ───────────────────────────────────────────────────────────────
        cpu = stats.get('cpu_pct', 0.0)
        freq = stats.get('cpu_freq_mhz', 0.0)
        cores = stats.get('cpu_cores', 0)
        self._cpu.update(
            f"{cpu:.0f}%",
            f"{freq/1000:.2f} GHz  •  {cores}C/{stats.get('cpu_threads',0)}T",
            _pct_color(cpu)
        )

        # ── GPU ───────────────────────────────────────────────────────────────
        gpu_u = stats.get('gpu_util_pct', 0.0)
        vused = stats.get('gpu_vram_used_mb', 0.0)
        vtot  = stats.get('gpu_vram_total_mb', 0.0)
        gpow  = stats.get('gpu_power_w', 0.0)
        if vtot > 0:
            vram_s = f"{vused/1024:.1f}/{vtot/1024:.1f} GB"
        else:
            vram_s = ''
        pwr_s = f"{gpow:.0f} W" if gpow > 0 else ''
        sub_parts = [s for s in [vram_s, pwr_s] if s]
        self._gpu.update(
            f"{gpu_u:.0f}%",
            '  •  '.join(sub_parts) if sub_parts else 'No data',
            _pct_color(gpu_u)
        )

        # ── RAM ───────────────────────────────────────────────────────────────
        rused = stats.get('ram_used_gb', 0.0)
        rtot  = stats.get('ram_total_gb', 0.0)
        rpct  = stats.get('ram_pct', 0.0)
        swap  = stats.get('swap_used_gb', 0.0)
        swap_s = f"Swap {swap:.1f} GB" if swap > 0.1 else ''
        self._ram.update(
            f"{rused:.1f} / {rtot:.0f} GB",
            swap_s or f"{rpct:.0f}% used",
            _pct_color(rpct)
        )

        # ── Storage ───────────────────────────────────────────────────────────
        parts = stats.get('partitions', [])
        root  = next((p for p in parts if p['mountpoint'] == '/'), None)
        if root:
            dr = stats.get('disk_read_mb_s', 0.0)
            dw = stats.get('disk_write_mb_s', 0.0)
            io_s = f"↓{dr:.1f}  ↑{dw:.1f} MB/s" if (dr + dw) > 0.05 else ''
            self._disk.update(
                f"{root['used_gb']:.0f} / {root['total_gb']:.0f} GB",
                io_s or f"{root['pct']:.0f}% used",
                _pct_color(root['pct'])
            )

        # ── Network ───────────────────────────────────────────────────────────
        down = stats.get('net_down_mb_s', 0.0)
        up   = stats.get('net_up_mb_s', 0.0)
        ifaces = stats.get('net_interfaces', [])
        iface_name = ifaces[0]['name'] if ifaces else ''
        ip         = ifaces[0].get('ip', '') if ifaces else ''
        self._net.update(
            f"↓{down:.1f}  ↑{up:.1f} MB/s",
            f"{iface_name}  {ip}" if iface_name else 'No interface',
            '#44ddaa'
        )
