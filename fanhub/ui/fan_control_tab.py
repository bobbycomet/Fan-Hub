"""
Fan Control Tab - per-fan speed control, mode selection, hub detection.
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSlider, QComboBox, QPushButton, QGroupBox,
    QScrollArea, QFrame, QSpinBox, QDoubleSpinBox,
    QCheckBox, QSizePolicy, QToolButton, QLineEdit,
    QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor

from core.fan_curves import PRESET_CURVES

logger = logging.getLogger('fanhub.fancontrol')


class FanChannelWidget(QFrame):
    """
    Widget for controlling a single fan channel.
    Handles PWM/DC mode, speed sliders, curve assignment, and hub info.
    """
    speed_changed = pyqtSignal(str, float)   # fan_id, percent
    mode_changed = pyqtSignal(str, str)       # fan_id, mode
    curve_assigned = pyqtSignal(str, str)     # fan_id, curve_name
    auto_requested = pyqtSignal(str)          # fan_id

    def __init__(self, fan_id: str, fan_entry, curve_engine, state):
        super().__init__()
        self.fan_id = fan_id
        self.fan = fan_entry
        self.curves = curve_engine
        self.state = state
        self._suppress_signals = False
        self.setObjectName("fanChannel")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # ── Header ──────────────────────────────────
        header = QHBoxLayout()

        self.name_lbl = QLabel(f"<b>{self.fan.label}</b>")
        self.name_lbl.setObjectName("fanChannelName")
        header.addWidget(self.name_lbl)

        if self.fan.is_hub_channel:
            hub_badge = QLabel(f"[{(self.fan.hub_type or 'HUB').upper()}]")
            hub_badge.setObjectName("hubBadge")
            hub_badge.setStyleSheet("color: #ffaa00; font-size: 10px; padding: 1px 5px; "
                                    "background: #332200; border-radius: 3px;")
            header.addWidget(hub_badge)

        header.addStretch()

        self.rpm_lbl = QLabel("-- RPM")
        self.rpm_lbl.setObjectName("channelRPM")
        header.addWidget(self.rpm_lbl)

        layout.addLayout(header)

        # ── Mode + Curve assignment ──────────────────
        row1 = QHBoxLayout()

        row1.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['auto', 'pwm_manual', 'dc', 'curve', 'fixed'])
        self.mode_combo.setCurrentText(self.fan.mode if self.fan.mode != 'unknown' else 'auto')
        self.mode_combo.currentTextChanged.connect(self._on_mode_change)
        row1.addWidget(self.mode_combo)

        row1.addWidget(QLabel("Curve:"))
        self.curve_combo = QComboBox()
        curve_names = list(PRESET_CURVES.keys()) + [
            k for k in self.curves.curves if k not in PRESET_CURVES
        ]
        self.curve_combo.addItems(curve_names)
        # Check if already assigned
        assigned = self.curves.fan_assignments.get(self.fan_id)
        if assigned and assigned in curve_names:
            self.curve_combo.setCurrentText(assigned)
        self.curve_combo.currentTextChanged.connect(self._on_curve_change)
        row1.addWidget(self.curve_combo)

        layout.addLayout(row1)

        # ── Speed slider ─────────────────────────────
        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Speed:"))

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(self.fan.current_percent))
        self.slider.setTickInterval(10)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.valueChanged.connect(self._on_slider_change)
        slider_row.addWidget(self.slider, 1)

        self.pct_spin = QSpinBox()
        self.pct_spin.setRange(0, 100)
        self.pct_spin.setSuffix("%")
        self.pct_spin.setValue(int(self.fan.current_percent))
        self.pct_spin.setFixedWidth(70)
        self.pct_spin.valueChanged.connect(self._on_spin_change)
        slider_row.addWidget(self.pct_spin)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("applyBtn")
        self.apply_btn.clicked.connect(self._apply_speed)
        slider_row.addWidget(self.apply_btn)

        layout.addLayout(slider_row)

        # ── PWM type indicator + limits ──────────────
        info_row = QHBoxLayout()

        mode_text = "PWM" if self.fan.pwm_file else "DC"
        mode_color = "#44ccff" if self.fan.pwm_file else "#ffaa44"
        mode_badge = QLabel(mode_text)
        mode_badge.setStyleSheet(
            f"color: {mode_color}; font-size: 10px; padding: 2px 6px; "
            f"background: #111; border-radius: 3px; border: 1px solid {mode_color};"
        )
        info_row.addWidget(mode_badge)

        if self.fan.min_rpm > 0:
            info_row.addWidget(QLabel(f"Min: {self.fan.min_rpm} RPM"))

        self.auto_btn = QPushButton("🔄 Auto")
        self.auto_btn.setObjectName("smallBtn")
        self.auto_btn.clicked.connect(lambda: self.auto_requested.emit(self.fan_id))
        info_row.addWidget(self.auto_btn)

        # Child fans (daisy chain / hub)
        if self.fan.child_fans:
            info_row.addWidget(QLabel(f"↳ {len(self.fan.child_fans)} chained fans"))

        info_row.addStretch()
        layout.addLayout(info_row)

        # ── Current reading bar ──────────────────────
        bar_row = QHBoxLayout()
        bar_row.addWidget(QLabel("Current:"))
        self.live_bar = QLabel("|||||||||| 0%")
        self.live_bar.setObjectName("liveBar")
        bar_row.addWidget(self.live_bar)
        layout.addLayout(bar_row)

    def _on_mode_change(self, mode: str):
        if not self._suppress_signals:
            self.mode_changed.emit(self.fan_id, mode)
            # Enable/disable slider
            manual = mode in ('pwm_manual', 'dc', 'fixed')
            self.slider.setEnabled(manual)
            self.pct_spin.setEnabled(manual)
            self.apply_btn.setEnabled(manual)

    def _on_curve_change(self, curve: str):
        if not self._suppress_signals:
            self.curve_assigned.emit(self.fan_id, curve)

    def _on_slider_change(self, val: int):
        if not self._suppress_signals:
            self._suppress_signals = True
            self.pct_spin.setValue(val)
            self._suppress_signals = False

    def _on_spin_change(self, val: int):
        if not self._suppress_signals:
            self._suppress_signals = True
            self.slider.setValue(val)
            self._suppress_signals = False

    def _apply_speed(self):
        pct = self.slider.value()
        self.speed_changed.emit(self.fan_id, float(pct))

    def update_live(self, data: dict):
        rpm = data.get('rpm', 0)
        pct = data.get('percent', 0.0)
        self.rpm_lbl.setText(f"{rpm:,} RPM")

        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        self.live_bar.setText(f"{bar} {pct:.0f}%")

        color = "#44ff88" if rpm > 0 else "#666666"
        self.rpm_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

    def refresh_curves(self, curve_names: list):
        self._suppress_signals = True
        current = self.curve_combo.currentText()
        self.curve_combo.clear()
        self.curve_combo.addItems(curve_names)
        if current in curve_names:
            self.curve_combo.setCurrentText(current)
        self._suppress_signals = False


class FanControlTab(QWidget):

    def __init__(self, hw_monitor, curve_engine, state):
        super().__init__()
        self.hw = hw_monitor
        self.curves = curve_engine
        self.state = state
        self._widgets: dict = {}   # fan_id -> FanChannelWidget
        self._build_ui()
        self.refresh_fans()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── Global controls ──────────────────────────
        global_group = QGroupBox("🌐 Global Controls")
        global_group.setObjectName("controlGroup")
        gl = QHBoxLayout(global_group)

        gl.addWidget(QLabel("Set ALL fans:"))

        self.global_slider = QSlider(Qt.Orientation.Horizontal)
        self.global_slider.setRange(0, 100)
        self.global_slider.setValue(50)
        gl.addWidget(self.global_slider, 1)

        self.global_spin = QSpinBox()
        self.global_spin.setRange(0, 100)
        self.global_spin.setSuffix("%")
        self.global_spin.setValue(50)
        gl.addWidget(self.global_spin)

        apply_all = QPushButton("Apply to All")
        apply_all.setObjectName("applyBtn")
        apply_all.clicked.connect(self._apply_to_all)
        gl.addWidget(apply_all)

        gl.addWidget(QLabel("  Preset:"))
        self.global_preset = QComboBox()
        self.global_preset.addItems(list(PRESET_CURVES.keys()))
        gl.addWidget(self.global_preset)

        assign_preset = QPushButton("Assign Preset to All")
        assign_preset.clicked.connect(self._assign_preset_all)
        gl.addWidget(assign_preset)

        # Link slider and spin
        self.global_slider.valueChanged.connect(self.global_spin.setValue)
        self.global_spin.valueChanged.connect(self.global_slider.setValue)

        layout.addWidget(global_group)

        # ── Filters ──────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Search fans...")
        self.filter_edit.textChanged.connect(self._filter_fans)
        filter_row.addWidget(self.filter_edit)

        self.show_hubs = QCheckBox("Show hub info")
        self.show_hubs.setChecked(True)
        filter_row.addWidget(self.show_hubs)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # ── Fan grid ─────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("fanScroll")

        self.fan_container = QWidget()
        self.fan_grid = QGridLayout(self.fan_container)
        self.fan_grid.setSpacing(8)
        scroll.setWidget(self.fan_container)
        layout.addWidget(scroll, 1)

    def refresh_fans(self):
        # Clear existing widgets
        for w in self._widgets.values():
            self.fan_grid.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()

        fans = self.hw.fans
        cols = 2
        row, col = 0, 0

        for fid, fan in fans.items():
            widget = FanChannelWidget(fid, fan, self.curves, self.state)
            widget.speed_changed.connect(self._on_speed_changed)
            widget.mode_changed.connect(self._on_mode_changed)
            widget.curve_assigned.connect(self._on_curve_assigned)
            widget.auto_requested.connect(self._on_auto_requested)
            self._widgets[fid] = widget
            self.fan_grid.addWidget(widget, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1

        # Fill remaining columns
        if col > 0:
            self.fan_grid.setColumnStretch(col, 1)

    def update_fans(self, fans: dict):
        for fid, data in fans.items():
            if fid in self._widgets:
                self._widgets[fid].update_live(data)

    def update_temps(self, temps: dict):
        pass  # Could show sensor selector per fan

    def _on_speed_changed(self, fan_id: str, pct: float):
        self.hw.set_fan_percent(fan_id, pct)
        self.curves.assign_fixed(fan_id, pct)
        logger.info(f"Fan {fan_id} set to {pct:.0f}%")

    def _on_mode_changed(self, fan_id: str, mode: str):
        if mode == 'auto':
            self.hw.set_fan_auto(fan_id)
            self.curves.fan_assignments.pop(fan_id, None)
            self.curves.fixed_speeds.pop(fan_id, None)
        elif mode == 'dc':
            if fan_id in self.hw.fans:
                fan = self.hw.fans[fan_id]
                if fan.pwm_enable_file:
                    self.hw._write_file(fan.pwm_enable_file, '0')

    def _on_curve_assigned(self, fan_id: str, curve_name: str):
        self.curves.assign_curve(fan_id, curve_name)
        logger.info(f"Fan {fan_id} assigned to curve '{curve_name}'")

    def _on_auto_requested(self, fan_id: str):
        self.hw.set_fan_auto(fan_id)
        self.curves.fan_assignments.pop(fan_id, None)
        self.curves.fixed_speeds.pop(fan_id, None)

    def _apply_to_all(self):
        pct = self.global_slider.value()
        for fan_id in self.hw.fans:
            self.hw.set_fan_percent(fan_id, float(pct))
            self.curves.assign_fixed(fan_id, float(pct))

    def _assign_preset_all(self):
        preset = self.global_preset.currentText()
        for fan_id in self.hw.fans:
            self.curves.assign_curve(fan_id, preset)

    def _filter_fans(self, text: str):
        text = text.lower()
        for fid, widget in self._widgets.items():
            label = self.hw.fans[fid].label.lower()
            visible = (not text) or (text in label) or (text in fid.lower())
            widget.setVisible(visible)
