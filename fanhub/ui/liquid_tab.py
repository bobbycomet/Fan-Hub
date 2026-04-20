"""
Liquid Cooling Tab - AIO and USB controller management via liquidctl.

FIX: added late_init() so the tab can be created with manager=None and
     receive the manager later (after background init completes).
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QGroupBox,
    QScrollArea, QFrame, QSlider, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QDoubleSpinBox, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal

logger = logging.getLogger('fanhub.liquid')


class LiquidDevicePanel(QFrame):
    """Panel for controlling one liquidctl device."""

    def __init__(self, device, manager):
        super().__init__()
        self.device = device
        self.manager = manager
        self.setObjectName("liquidPanel")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 10)
        layout.setSpacing(8)

        # ── Header ───────────────────────────────────
        header = QHBoxLayout()
        name_lbl = QLabel(f"<b>{self.device.name}</b>")
        name_lbl.setObjectName("liquidDeviceName")
        header.addWidget(name_lbl)

        type_badge = QLabel(self.device.device_type.upper())
        type_badge.setStyleSheet(
            "color: #00ccff; font-size: 10px; padding: 2px 6px; "
            "background: #001133; border-radius: 3px;"
        )
        header.addWidget(type_badge)
        header.addStretch()
        layout.addLayout(header)

        # ── Status display ────────────────────────────
        self.status_group = QGroupBox("Live Status")
        QGridLayout(self.status_group)
        self.status_labels: dict = {}
        layout.addWidget(self.status_group)

        # ── Fan control ───────────────────────────────
        if self.device.supports_fan_control:
            fan_group = QGroupBox("Fan Control")
            fl = QVBoxLayout(fan_group)

            ch_row = QHBoxLayout()
            ch_row.addWidget(QLabel("Channel:"))
            self.fan_channel = QComboBox()
            self.fan_channel.addItems(['fan', 'fans', 'fan1', 'fan2', 'fan3'])
            ch_row.addWidget(self.fan_channel)
            fl.addLayout(ch_row)

            spd_row = QHBoxLayout()
            spd_row.addWidget(QLabel("Speed:"))
            self.fan_slider = QSlider(Qt.Orientation.Horizontal)
            self.fan_slider.setRange(0, 100)
            self.fan_slider.setValue(50)
            spd_row.addWidget(self.fan_slider, 1)
            self.fan_spin = QSpinBox()
            self.fan_spin.setRange(0, 100)
            self.fan_spin.setSuffix("%")
            self.fan_spin.setValue(50)
            self.fan_slider.valueChanged.connect(self.fan_spin.setValue)
            self.fan_spin.valueChanged.connect(self.fan_slider.setValue)
            spd_row.addWidget(self.fan_spin)
            fl.addLayout(spd_row)

            curve_row = QHBoxLayout()
            curve_row.addWidget(QLabel("Curve (temp:speed pairs):"))
            fl.addLayout(curve_row)

            self.curve_table = QTableWidget(4, 2)
            self.curve_table.setHorizontalHeaderLabels(["Temp °C", "Speed %"])
            self.curve_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Stretch)
            self.curve_table.setMaximumHeight(120)
            defaults = [(20, 25), (40, 40), (60, 70), (80, 100)]
            for i, (t, s) in enumerate(defaults):
                self.curve_table.setItem(i, 0, QTableWidgetItem(str(t)))
                self.curve_table.setItem(i, 1, QTableWidgetItem(str(s)))
            fl.addWidget(self.curve_table)

            btn_row = QHBoxLayout()
            apply_fixed = QPushButton("Apply Fixed Speed")
            apply_fixed.setObjectName("applyBtn")
            apply_fixed.clicked.connect(self._apply_fan_fixed)
            btn_row.addWidget(apply_fixed)

            apply_curve = QPushButton("Apply Curve")
            apply_curve.setObjectName("applyBtn")
            apply_curve.clicked.connect(self._apply_fan_curve)
            btn_row.addWidget(apply_curve)
            fl.addLayout(btn_row)

            layout.addWidget(fan_group)

        # ── Pump control ──────────────────────────────
        if self.device.supports_pump_control:
            pump_group = QGroupBox("Pump Control")
            pl = QHBoxLayout(pump_group)

            pl.addWidget(QLabel("Mode:"))
            self.pump_mode = QComboBox()
            self.pump_mode.addItems(['quiet', 'balanced', 'performance', 'extreme'])
            pl.addWidget(self.pump_mode)

            apply_pump = QPushButton("Apply Pump Mode")
            apply_pump.setObjectName("applyBtn")
            apply_pump.clicked.connect(self._apply_pump)
            pl.addWidget(apply_pump)

            pl.addStretch()
            layout.addWidget(pump_group)

        # ── RGB ───────────────────────────────────────
        if self.device.supports_rgb:
            rgb_group = QGroupBox("RGB (liquidctl)")
            rl = QHBoxLayout(rgb_group)

            rl.addWidget(QLabel("Channel:"))
            self.rgb_channel = QComboBox()
            self.rgb_channel.addItems(['logo', 'ring', 'fans', 'sync', 'led'])
            rl.addWidget(self.rgb_channel)

            rl.addWidget(QLabel("Mode:"))
            self.rgb_mode = QComboBox()
            self.rgb_mode.addItems([
                'off', 'fixed', 'fading', 'spectrum-wave',
                'super-fixed', 'breathing', 'pulse', 'marquee-3', 'marquee-4',
                'covering-marquee', 'alternating-3', 'alternating-4',
                'moving-alternating-3', 'moving-alternating-4', 'waterfall',
                'super-breathing', 'candle', 'starry-night', 'rainbow-flow',
                'super-rainbow', 'rainbow-pulse', 'backwards-spectrum-wave',
            ])
            rl.addWidget(self.rgb_mode)

            apply_rgb = QPushButton("Apply")
            apply_rgb.setObjectName("applyBtn")
            apply_rgb.clicked.connect(self._apply_rgb)
            rl.addWidget(apply_rgb)

            rl.addStretch()
            layout.addWidget(rgb_group)

        # ── Initialize ────────────────────────────────
        init_row = QHBoxLayout()
        init_btn = QPushButton("🔌 Initialize Device")
        init_btn.setToolTip("Some devices require initialization after connect")
        init_btn.clicked.connect(self._initialize)
        init_row.addWidget(init_btn)
        init_row.addStretch()
        layout.addLayout(init_row)

    def update_status(self, device):
        self.device = device
        layout = self.status_group.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        row = 0
        for temp in device.temps:
            lbl = QLabel(f"{temp['label']}:")
            val = QLabel(f"{temp['value']:.1f}°C")
            val.setStyleSheet("color: #ff8844; font-weight: bold;")
            layout.addWidget(lbl, row, 0)
            layout.addWidget(val, row, 1)
            row += 1

        for fan in device.fans:
            lbl = QLabel(f"{fan['label']}:")
            val = QLabel(f"{fan.get('rpm', '--')} RPM")
            val.setStyleSheet("color: #44ff88; font-weight: bold;")
            layout.addWidget(lbl, row, 0)
            layout.addWidget(val, row, 1)
            row += 1

        if device.pump:
            lbl = QLabel("Pump:")
            rpm = device.pump.get('rpm', '--')
            duty = device.pump.get('duty', '')
            val = QLabel(f"{rpm} RPM" + (f" ({duty}%)" if duty else ""))
            val.setStyleSheet("color: #44aaff; font-weight: bold;")
            layout.addWidget(lbl, row, 0)
            layout.addWidget(val, row, 1)

    def _apply_fan_fixed(self):
        pct = self.fan_slider.value()
        channel = self.fan_channel.currentText()
        self.manager.set_fan_speed(self.device, channel, pct)
        logger.info(f"Liquid fan {self.device.name}/{channel} -> {pct}%")

    def _apply_fan_curve(self):
        channel = self.fan_channel.currentText()
        points = []
        for row in range(self.curve_table.rowCount()):
            t_item = self.curve_table.item(row, 0)
            s_item = self.curve_table.item(row, 1)
            if t_item and s_item:
                try:
                    points.append((int(t_item.text()), int(s_item.text())))
                except ValueError:
                    pass
        if points:
            self.manager.set_fan_curve(self.device, channel, points)
            logger.info(f"Liquid fan curve applied: {self.device.name}/{channel}")

    def _apply_pump(self):
        mode = self.pump_mode.currentText()
        self.manager.set_pump_speed(self.device, mode)
        logger.info(f"Pump {self.device.name}: {mode}")

    def _apply_rgb(self):
        channel = self.rgb_channel.currentText()
        mode = self.rgb_mode.currentText()
        self.manager.set_rgb(self.device, channel, mode, [(0, 200, 255)])
        logger.info(f"Liquid RGB {self.device.name}/{channel}: {mode}")

    def _initialize(self):
        self.manager.initialize_device(self.device)
        logger.info(f"Initialized {self.device.name}")


class LiquidTab(QWidget):

    def __init__(self, manager, curve_engine, state):
        super().__init__()
        self.manager = manager
        self.curves = curve_engine
        self.state = state
        self._panels: dict = {}
        self._build_ui()

    def late_init(self, manager):
        """Called after background init — wire up the real manager and rebuild."""
        self.manager = manager
        # Rebuild the whole tab now we have a real manager
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._panels.clear()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Manager not yet available (background init in progress)
        if self.manager is None:
            loading_lbl = QLabel("⏳  Liquid cooling devices initialising in the background…")
            loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            loading_lbl.setStyleSheet("color: #556677; font-size: 13px; padding: 40px;")
            layout.addWidget(loading_lbl)
            return

        if not self.manager.available:
            self._build_not_available(layout)
            return

        if not self.manager.devices:
            lbl = QLabel("No liquidctl devices detected. "
                         "Ensure devices are connected and liquidctl is installed.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

            rescan_btn = QPushButton("🔍 Rescan Devices")
            rescan_btn.clicked.connect(self._rescan)
            layout.addWidget(rescan_btn, alignment=Qt.AlignmentFlag.AlignCenter)
            return

        # Top bar
        top = QHBoxLayout()
        top.addWidget(QLabel(f"Detected {len(self.manager.devices)} liquid device(s)"))
        top.addStretch()
        init_all_btn = QPushButton("Initialize All")
        init_all_btn.clicked.connect(self.manager.initialize_all)
        top.addWidget(init_all_btn)
        rescan_btn = QPushButton("🔍 Rescan")
        rescan_btn.clicked.connect(self._rescan)
        top.addWidget(rescan_btn)
        layout.addLayout(top)

        # Panels
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        panels_layout = QVBoxLayout(container)
        panels_layout.setSpacing(12)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        for dev in self.manager.devices:
            panel = LiquidDevicePanel(dev, self.manager)
            self._panels[dev.id] = panel
            panels_layout.addWidget(panel)

        panels_layout.addStretch()

    def _build_not_available(self, layout):
        frame = QFrame()
        fl = QVBoxLayout(frame)
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("💧")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 64px;")
        fl.addWidget(icon)

        msg = QLabel(
            "liquidctl is not installed or no compatible devices found.\n\n"
            "Install liquidctl:\n"
            "  pip install liquidctl\n"
            "  or: sudo apt install liquidctl\n\n"
            "Supported devices: NZXT Kraken, Corsair Hydro/Commander,\n"
            "EVGA CLC, Cooler Master, and many more."
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        fl.addWidget(msg)

        layout.addWidget(frame)

    def update_devices(self, devices: list):
        for dev in devices:
            if dev.id in self._panels:
                self._panels[dev.id].update_status(dev)

    def _rescan(self):
        if self.manager:
            self.manager.rescan()
            self.late_init(self.manager)
