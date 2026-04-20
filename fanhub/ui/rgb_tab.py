"""
RGB Lighting Tab — OpenRGB device control with live connection status.
Supports SDK, AppImage (any version name), and .deb installs.

FIX: added late_init() so the tab can be created with manager=None and
     receive the manager later (after background init completes).
"""
import logging
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QGroupBox,
    QScrollArea, QFrame, QCheckBox, QFileDialog,
    QColorDialog, QLineEdit, QSpinBox, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QPixmap, QPainter, QBrush, QPen

from core.rgb_manager import RGB_PRESETS, RGB_EFFECTS

logger = logging.getLogger('fanhub.rgb')


# ── Color Button ──────────────────────────────────────────────────────────────

class ColorButton(QPushButton):
    color_changed = pyqtSignal(QColor)

    def __init__(self, initial: QColor = None):
        super().__init__()
        self._color = initial or QColor(255, 255, 255)
        self.setFixedSize(48, 28)
        self._paint()
        self.clicked.connect(self._pick)

    def _paint(self):
        self.setStyleSheet(
            f"background-color: {self._color.name()}; "
            f"border-radius: 4px; border: 1px solid #334455;"
        )

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, "Pick Color")
        if c.isValid():
            self._color = c
            self._paint()
            self.color_changed.emit(c)

    def color(self) -> QColor:
        return self._color

    def set_color(self, c: QColor):
        self._color = c
        self._paint()


# ── Status Bar ────────────────────────────────────────────────────────────────

class OpenRGBStatusBar(QFrame):
    """Persistent status bar shown at the top of the RGB tab always."""

    reconnect_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("rgbStatusBar")
        self.setFixedHeight(42)
        self.setStyleSheet(
            "QFrame#rgbStatusBar { background: #0c0c18; "
            "border-bottom: 1px solid #1a2040; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(18)
        layout.addWidget(self._dot)

        self._status = QLabel("Initialising…")
        self._status.setStyleSheet("font-size: 12px;")
        layout.addWidget(self._status, 1)

        self._devices = QLabel("")
        self._devices.setStyleSheet("color: #556677; font-size: 11px;")
        layout.addWidget(self._devices)

        self._recon_btn = QPushButton("Reconnect")
        self._recon_btn.setFixedWidth(90)
        self._recon_btn.clicked.connect(self.reconnect_requested)
        layout.addWidget(self._recon_btn)

    def update_status(self, status: dict):
        connected = status.get('connected', False)
        server_up = status.get('server_up', False)
        devcount  = status.get('device_count', 0)
        text      = status.get('status_text', '')

        if connected:
            dot_color = "#44ff88"
            bg_color  = "#001a08"
        elif server_up:
            dot_color = "#ffaa00"
            bg_color  = "#1a1000"
        else:
            dot_color = "#ff4444"
            bg_color  = "#1a0008"

        self.setStyleSheet(
            f"QFrame#rgbStatusBar {{ background: {bg_color}; "
            f"border-bottom: 1px solid #1a2040; }}"
        )
        self._dot.setStyleSheet(f"color: {dot_color}; font-size: 16px;")
        self._status.setText(text or ("Connected" if connected else "Not connected"))
        self._status.setStyleSheet(f"color: {dot_color}; font-size: 12px;")

        if devcount > 0:
            self._devices.setText(f"{devcount} device(s)")
        else:
            self._devices.setText("")


# ── Device widget ─────────────────────────────────────────────────────────────

class DeviceRGBWidget(QFrame):

    def __init__(self, device: dict, manager):
        super().__init__()
        self.device  = device
        self.manager = manager
        self.setObjectName("rgbDeviceCard")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        # Header row
        hdr = QHBoxLayout()
        name_lbl = QLabel(f"<b>{self.device['name']}</b>")
        name_lbl.setObjectName("rgbDeviceName")
        hdr.addWidget(name_lbl)

        if self.device.get('is_fan_device'):
            badge = QLabel("FAN")
            badge.setStyleSheet(
                "color:#00ccff; font-size:9px; padding:1px 5px; "
                "background:#002244; border-radius:3px;"
            )
            hdr.addWidget(badge)

        src = self.device.get('source', '')
        src_lbl = QLabel(f"[{src.upper()}]")
        src_lbl.setStyleSheet("color:#445566; font-size:9px;")
        hdr.addWidget(src_lbl)

        type_lbl = QLabel(self.device.get('type', ''))
        type_lbl.setStyleSheet("color:#334455; font-size:10px;")
        hdr.addWidget(type_lbl)
        hdr.addStretch()

        if self.device.get('leds'):
            hdr.addWidget(QLabel(f"{self.device['leds']} LEDs"))
        layout.addLayout(hdr)

        # Mode row
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_cb = QComboBox()
        modes = self.manager.get_device_modes(self.device['id'])
        self.mode_cb.addItems(modes if modes else RGB_EFFECTS)
        mode_row.addWidget(self.mode_cb, 1)
        layout.addLayout(mode_row)

        # Color row
        col_row = QHBoxLayout()
        col_row.addWidget(QLabel("Color:"))
        self.color_btn = ColorButton(QColor(0, 200, 255))
        col_row.addWidget(self.color_btn)

        for name, (r, g, b) in list(RGB_PRESETS.items())[:7]:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setToolTip(name)
            btn.setStyleSheet(
                f"background:rgb({r},{g},{b}); border-radius:11px; border:1px solid #333;"
            )
            btn.clicked.connect(
                lambda _, rv=r, gv=g, bv=b: self._quick(rv, gv, bv))
            col_row.addWidget(btn)
        col_row.addStretch()
        layout.addLayout(col_row)

        # Apply / off
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("applyBtn")
        apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(apply_btn)
        off_btn = QPushButton("Off")
        off_btn.clicked.connect(lambda: self._quick(0, 0, 0))
        btn_row.addWidget(off_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _apply(self):
        c    = self.color_btn.color()
        mode = self.mode_cb.currentText()
        did  = self.device['id']
        if mode.lower() == 'static':
            self.manager.set_device_color(did, c.red(), c.green(), c.blue())
        else:
            self.manager.set_device_mode(did, mode, c.red(), c.green(), c.blue())

    def _quick(self, r, g, b):
        self.color_btn.set_color(QColor(r, g, b))
        self.manager.set_device_color(self.device['id'], r, g, b)


# ── Main RGB Tab ──────────────────────────────────────────────────────────────

class RGBTab(QWidget):

    def __init__(self, rgb_manager, state):
        super().__init__()
        self.manager = rgb_manager
        self.state   = state
        self._device_widgets: list = []

        # Status poll timer — parented to self so Qt stops it on widget destruction
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._poll_status)

        self._build_ui()
        self._poll_timer.start()

    def late_init(self, rgb_manager):
        """Called after background init — wire up the real manager."""
        self.manager = rgb_manager
        self._rebuild()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Always-visible status bar ─────────────────
        self._status_bar = OpenRGBStatusBar()
        self._status_bar.reconnect_requested.connect(self._do_reconnect)
        root.addWidget(self._status_bar)

        if self.manager:
            self._status_bar.update_status(self.manager.get_full_status())

        # ── Scrollable main area ──────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(12, 10, 12, 10)
        self._content_layout.setSpacing(10)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        if self.manager and self.manager.connected:
            self._build_connected()
        else:
            self._build_not_connected()

    def _build_connected(self):
        cl = self._content_layout

        # Global controls
        g_group = QGroupBox("Global RGB Control")
        g_group.setObjectName("controlGroup")
        gl = QHBoxLayout(g_group)

        gl.addWidget(QLabel("All devices:"))
        self.global_mode = QComboBox()
        self.global_mode.addItems(RGB_EFFECTS)
        gl.addWidget(self.global_mode)

        self.global_color = ColorButton(QColor(0, 200, 255))
        gl.addWidget(self.global_color)

        for name, (r, g, b) in list(RGB_PRESETS.items())[:9]:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setToolTip(name)
            btn.setStyleSheet(
                f"background:rgb({r},{g},{b}); border-radius:11px; border:1px solid #333;"
            )
            btn.clicked.connect(
                lambda _, rv=r, gv=g, bv=b: self._global_color_quick(rv, gv, bv))
            gl.addWidget(btn)

        apply_all = QPushButton("Apply All")
        apply_all.setObjectName("applyBtn")
        apply_all.clicked.connect(self._apply_global)
        gl.addWidget(apply_all)

        all_off = QPushButton("All Off")
        all_off.clicked.connect(lambda: self._global_color_quick(0, 0, 0))
        gl.addWidget(all_off)
        gl.addStretch()
        cl.addWidget(g_group)

        # Temp-reactive
        react_group = QGroupBox("Temperature-Reactive RGB")
        react_group.setObjectName("controlGroup")
        rl = QHBoxLayout(react_group)
        self.reactive_check = QCheckBox("Enable")
        rl.addWidget(self.reactive_check)
        rl.addWidget(QLabel("Cool color:"))
        self.cold_color = ColorButton(QColor(0, 100, 255))
        rl.addWidget(self.cold_color)
        rl.addWidget(QLabel("Hot color:"))
        self.hot_color = ColorButton(QColor(255, 50, 0))
        rl.addWidget(self.hot_color)
        rl.addWidget(QLabel("Min °C:"))
        self.min_temp_spin = QSpinBox()
        self.min_temp_spin.setRange(20, 80)
        self.min_temp_spin.setValue(30)
        rl.addWidget(self.min_temp_spin)
        rl.addWidget(QLabel("Max °C:"))
        self.max_temp_spin = QSpinBox()
        self.max_temp_spin.setRange(40, 110)
        self.max_temp_spin.setValue(80)
        rl.addWidget(self.max_temp_spin)
        rl.addStretch()
        cl.addWidget(react_group)

        # Device grid
        dev_group = QGroupBox(f"Devices ({len(self.manager.devices)})")
        dev_group.setObjectName("controlGroup")
        dev_grid = QGridLayout(dev_group)
        dev_grid.setSpacing(8)
        for i, dev in enumerate(self.manager.devices):
            w = DeviceRGBWidget(dev, self.manager)
            self._device_widgets.append(w)
            dev_grid.addWidget(w, i // 2, i % 2)
        cl.addWidget(dev_group)
        cl.addStretch()

    def _build_not_connected(self):
        cl = self._content_layout

        # If manager not yet available, show "loading" card
        if self.manager is None:
            loading_lbl = QLabel("⏳  OpenRGB initialising in the background…")
            loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            loading_lbl.setStyleSheet("color: #556677; font-size: 13px; padding: 40px;")
            cl.addWidget(loading_lbl)
            cl.addStretch()
            return

        # Connection setup panel
        setup_group = QGroupBox("OpenRGB Setup")
        setup_group.setObjectName("controlGroup")
        sl = QVBoxLayout(setup_group)

        s = self.manager.get_full_status()
        err_lbl = QLabel(s.get('error_detail') or s.get('status_text', ''))
        err_lbl.setWordWrap(True)
        err_lbl.setStyleSheet("color: #ff8844; padding: 6px; "
                              "background: #110800; border-radius: 4px;")
        sl.addWidget(err_lbl)

        bin_path = s.get('binary')
        deb      = s.get('deb_installed', False)
        sdk      = s.get('sdk_available', False)

        info_rows = [
            ("openrgb-python SDK",  "✓ Installed" if sdk  else "✗ Not installed (pip install openrgb-python)", sdk),
            ("OpenRGB .deb",        "✓ Installed" if deb  else "✗ Not detected",  deb),
            ("OpenRGB binary/AppImage",
             f"✓ {bin_path}" if bin_path else "✗ Not found",   bool(bin_path)),
            ("Server port",
             f"✓ {s['host']}:{s['port']} is OPEN" if s.get('server_up')
             else f"✗ {s['host']}:{s['port']} not reachable", s.get('server_up', False)),
        ]
        for label, val, ok in info_rows:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"<b>{label}:</b>"))
            v = QLabel(val)
            v.setStyleSheet(f"color: {'#44ff88' if ok else '#ff6644'}; font-size:11px;")
            v.setWordWrap(True)
            row.addWidget(v, 1)
            sl.addLayout(row)

        sl.addWidget(_hr())

        instr = QLabel(
            "<b>How to connect OpenRGB:</b><br><br>"
            "<b>Option A — AppImage (any version):</b><br>"
            "1. Download from <a href='https://openrgb.org' style='color:#44aaff'>openrgb.org</a><br>"
            "2. <code>chmod +x OpenRGB*.AppImage</code><br>"
            "3. <code>./OpenRGB*.AppImage --server --server-port 6742 &amp;</code><br>"
            "4. Browse to the AppImage below and click Reconnect<br><br>"
            "<b>Option B — .deb package:</b><br>"
            "1. Download .deb from openrgb.org<br>"
            "2. <code>sudo dpkg -i openrgb_*.deb</code><br>"
            "3. <code>openrgb --server --server-port 6742 &amp;</code><br>"
            "4. Click Reconnect<br><br>"
            "<b>Option C — pip SDK only:</b><br>"
            "<code>pip install openrgb-python</code> (still needs the server running)"
        )
        instr.setWordWrap(True)
        instr.setTextFormat(Qt.TextFormat.RichText)
        instr.setOpenExternalLinks(True)
        instr.setStyleSheet("font-size: 11px; color: #aabbcc;")
        sl.addWidget(instr)

        sl.addWidget(_hr())

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("AppImage / binary path:"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(
            "Browse to OpenRGB*.AppImage or leave blank to auto-detect")
        if self.manager and self.manager._bin:
            self._path_edit.setText(self.manager._bin)
        path_row.addWidget(self._path_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)
        sl.addLayout(path_row)

        conn_row = QHBoxLayout()
        conn_row.addWidget(QLabel("Server host:"))
        self._host_edit = QLineEdit()
        self._host_edit.setText(self.manager.host if self.manager else 'localhost')
        self._host_edit.setFixedWidth(120)
        conn_row.addWidget(self._host_edit)
        conn_row.addWidget(QLabel("Port:"))
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(self.manager.port if self.manager else 6742)
        conn_row.addWidget(self._port_spin)
        conn_row.addStretch()
        sl.addLayout(conn_row)

        recon_btn = QPushButton("Reconnect to OpenRGB")
        recon_btn.setObjectName("applyBtn")
        recon_btn.clicked.connect(self._do_reconnect)
        sl.addWidget(recon_btn)

        cl.addWidget(setup_group)
        cl.addStretch()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Find OpenRGB AppImage or Binary",
            os.path.expanduser("~/Downloads"),
            "All Files (*)"
        )
        if path and hasattr(self, '_path_edit'):
            self._path_edit.setText(path)

    def _do_reconnect(self):
        if not self.manager:
            return

        new_bin  = None
        new_host = None
        new_port = None

        if hasattr(self, '_path_edit'):
            p = self._path_edit.text().strip()
            if p and os.path.isfile(p):
                try:
                    os.chmod(p, 0o755)
                except Exception:
                    pass
                new_bin = p

        if hasattr(self, '_host_edit'):
            new_host = self._host_edit.text().strip() or None
        if hasattr(self, '_port_spin'):
            new_port = self._port_spin.value() or None

        self.manager.reconnect(new_host=new_host, new_port=new_port, new_bin=new_bin)
        self.state.openrgb_connected = self.manager.connected
        self._rebuild()

    def _poll_status(self):
        if not self.manager:
            return
        still_up = self.manager.is_server_running()
        if still_up and not self.manager.connected:
            self.manager.reconnect()
            self.state.openrgb_connected = self.manager.connected
            self._rebuild()
        elif not still_up and self.manager.connected:
            self.manager.connected = False
            self.manager.server_up = False
            self.manager.status_text = f"Server stopped at {self.manager.host}:{self.manager.port}"
            self._rebuild()

        self._status_bar.update_status(self.manager.get_full_status())

    def _rebuild(self):
        self._device_widgets = []
        layout = self._content_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self.manager and self.manager.connected:
            self._build_connected()
        else:
            self._build_not_connected()
        self._status_bar.update_status(
            self.manager.get_full_status() if self.manager
            else {'connected': False, 'status_text': 'Initialising…'})

    def _apply_global(self):
        if not self.manager:
            return
        c    = self.global_color.color()
        mode = self.global_mode.currentText()
        for dev in self.manager.devices:
            if mode.lower() == 'static':
                self.manager.set_device_color(dev['id'], c.red(), c.green(), c.blue())
            else:
                self.manager.set_device_mode(dev['id'], mode, c.red(), c.green(), c.blue())

    def _global_color_quick(self, r, g, b):
        if self.manager:
            self.manager.set_all_devices_color(r, g, b)

    def is_reactive_enabled(self) -> bool:
        return hasattr(self, 'reactive_check') and self.reactive_check.isChecked()

    def get_reactive_params(self) -> dict:
        return {
            'cold':     (self.cold_color.color().red(),
                         self.cold_color.color().green(),
                         self.cold_color.color().blue()),
            'hot':      (self.hot_color.color().red(),
                         self.hot_color.color().green(),
                         self.hot_color.color().blue()),
            'min_temp': self.min_temp_spin.value()  if hasattr(self, 'min_temp_spin') else 30,
            'max_temp': self.max_temp_spin.value()  if hasattr(self, 'max_temp_spin') else 80,
        }


def _hr() -> QFrame:
    """Horizontal rule separator."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color: #1a2040;")
    return f
