"""
Fan Control Tab - per-fan speed control, mode selection, hub detection.
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSlider, QComboBox, QPushButton, QGroupBox,
    QScrollArea, QFrame, QSpinBox, QDoubleSpinBox,
    QCheckBox, QSizePolicy, QToolButton, QLineEdit,
    QTabWidget, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
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
    calibrate_requested = pyqtSignal(str)      # fan_id — run auto PWM-polarity test

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

        # GPU badge
        if self.fan.gpu_vendor:
            vendor_upper = self.fan.gpu_vendor.upper()
            if self.fan.gpu_vendor == 'nvidia':
                gpu_color = '#76b900'
            elif self.fan.gpu_vendor == 'intel':
                gpu_color = '#0071c5'
            else:
                gpu_color = '#ed1c24'
            gpu_badge = QLabel(f"[{vendor_upper} GPU]")
            gpu_badge.setStyleSheet(
                f"color: {gpu_color}; font-size: 10px; padding: 1px 5px; "
                f"background: #111; border-radius: 3px; border: 1px solid {gpu_color};")
            header.addWidget(gpu_badge)

        header.addStretch()

        # Auto-calibration button — replaces the old manual "Invert" checkbox.
        # Nobody intuitively knows that "invert=100%" means "spins slower" —
        # instead of asking the user to understand PWM polarity, this runs a
        # short automatic test (100% → read RPM, low% → read RPM, compare)
        # and self-corrects if the fan turns out to be wired backwards.
        # Hidden for GPU fans since those use a different, non-PWM control path.
        self.calibrate_btn = None
        if self.fan.pwm_file and not self.fan.gpu_vendor:
            self.calibrate_btn = QPushButton("⚙ Calibrate")
            self.calibrate_btn.setToolTip(
                "Briefly tests this fan at high and low speed to confirm "
                "100% actually means full speed. Takes about 6 seconds. "
                "Only needed if this fan seems to run backwards (loud at "
                "low %, quiet at 100%).")
            self.calibrate_btn.setFixedHeight(22)
            self.calibrate_btn.setStyleSheet(
                "QPushButton { color:#8899aa; font-size:10px; padding:2px 8px; }")
            self.calibrate_btn.clicked.connect(
                lambda: self.calibrate_requested.emit(self.fan_id))
            header.addWidget(self.calibrate_btn)

        self.rpm_lbl = QLabel("-- RPM")
        self.rpm_lbl.setObjectName("channelRPM")
        header.addWidget(self.rpm_lbl)

        layout.addLayout(header)

        # ── Mode + Curve assignment ──────────────────
        row1 = QHBoxLayout()

        row1.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        # GPU fans: no DC mode
        if self.fan.gpu_vendor:
            self.mode_combo.addItems(['auto', 'pwm_manual', 'curve', 'fixed'])
        else:
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

        # ── Control method badge + limits ────────────
        info_row = QHBoxLayout()

        if self.fan.gpu_vendor == 'nvidia':
            if self.fan.nvidia_use_hwmon:
                ctrl_text, ctrl_color = "NVIDIA hwmon", "#76b900"
            elif self.fan.nvidia_use_settings:
                ctrl_text, ctrl_color = "nvidia-settings", "#ffaa44"
            else:
                ctrl_text, ctrl_color = "Read-only", "#ff4444"
        elif self.fan.gpu_vendor == 'amd':
            ctrl_text  = "AMD PWM" if self.fan.pwm_file else "Read-only"
            ctrl_color = "#ed1c24" if self.fan.pwm_file else "#ff4444"
        elif self.fan.gpu_vendor == 'intel':
            ctrl_text  = "Intel iGPU" if self.fan.pwm_file else "Read-only"
            ctrl_color = "#0071c5" if self.fan.pwm_file else "#ff4444"
        else:
            ctrl_text  = "PWM" if self.fan.pwm_file else "DC"
            ctrl_color = "#44ccff" if self.fan.pwm_file else "#ffaa44"

        mode_badge = QLabel(ctrl_text)
        mode_badge.setStyleSheet(
            f"color: {ctrl_color}; font-size: 10px; padding: 2px 6px; "
            f"background: #111; border-radius: 3px; border: 1px solid {ctrl_color};"
        )
        info_row.addWidget(mode_badge)

        if self.fan.min_rpm > 0:
            info_row.addWidget(QLabel(f"Min: {self.fan.min_rpm} RPM"))

        # For NVIDIA read-only fans, show setup hint instead of Auto button
        if self.fan.gpu_vendor == 'nvidia' and not self.fan.controllable:
            hint = QLabel("Enable CoolBits=4 for control")
            hint.setStyleSheet("color: #665533; font-size: 10px; font-style: italic;")
            info_row.addWidget(hint)
        else:
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


    def _show_why_uncontrollable(self):
        """Explain why this fan cannot be controlled."""
        from PyQt6.QtWidgets import QMessageBox
        fan = self.fan
        lines = [f"<b>{fan.label}</b><br><br>"]

        if fan.gpu_vendor == 'nvidia':
            if not fan.nvidia_use_hwmon and not fan.nvidia_use_settings:
                lines.append(
                    "NVIDIA GPU fans require either:<br>"
                    "• <b>CoolBits=4</b> in your Xorg config (enables hwmon PWM writes)<br>"
                    "• <b>nvidia-settings</b> installed and DISPLAY set<br><br>"
                    "Add to /etc/X11/xorg.conf.d/20-nvidia.conf:<br>"
                    "<code>Option &quot;Coolbits&quot; &quot;4&quot;</code>"
                )
        elif fan.gpu_vendor == 'intel':
            lines.append(
                "Intel integrated GPU fans are managed entirely by the GPU driver "
                "and firmware. They are not exposed for user control via sysfs. "
                "Temperature monitoring still works."
            )
        elif fan.gpu_vendor == 'amd':
            if not fan.pwm_file:
                lines.append(
                    "AMD GPU fan control requires the <b>amdgpu</b> kernel driver "
                    "and the PWM sysfs file to be present.<br><br>"
                    "Check: <code>ls /sys/class/hwmon/*/pwm*</code><br>"
                    "Try: <code>sudo modprobe amdgpu</code>"
                )
        elif not fan.pwm_file:
            lines.append(
                "No PWM control file found for this fan.<br><br>"
                "Possible reasons:<br>"
                "• Fan is connected to a header Fan Hub cannot write to<br>"
                "• Kernel module not loaded — try: <code>sudo modprobe nct6775</code> "
                "or <code>sudo modprobe it87</code><br>"
                "• Generic/budget fan with an internal controller (no SYS_FAN connection)<br>"
                "• Daisy-chained fans — only the first header is controllable"
            )
        else:
            lines.append(
                "PWM file exists but is not writable.<br><br>"
                "Fix: run <b>sudo ./install.sh</b> to apply the udev rules, "
                "then log out and back in."
            )

        msg = QMessageBox(self)
        msg.setWindowTitle("Why can't I control this fan?")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText("".join(lines))
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

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

    def update_live(self, data):
        """
        data is a FanEntry object (from PollingWorker.fans_updated —
        pyqtSignal(dict) of {fid: FanEntry}), not a plain dict.
        """
        if isinstance(data, dict):
            rpm    = data.get('rpm', 0)
            pct    = data.get('percent', 0.0)
            vendor = data.get('gpu_vendor')
        else:
            rpm    = getattr(data, 'current_rpm', 0)
            pct    = getattr(data, 'current_percent', 0.0)
            vendor = getattr(data, 'gpu_vendor', None)

        # Show RPM when we have it (hwmon tachometer — covers AMD and NVIDIA hwmon)
        if rpm > 0:
            self.rpm_lbl.setText(f"{rpm:,} RPM")
            color = "#44ff88"
        elif pct > 0 and vendor:
            # NVIDIA without hwmon tachometer: nvidia-smi only gives %, show that
            self.rpm_lbl.setText(f"{pct:.0f}%  (no RPM tach)")
            color = "#44ff88"
        elif pct > 0:
            # Fan running but no RPM reading (e.g. DC fan without tachometer)
            self.rpm_lbl.setText(f"~{pct:.0f}%")
            color = "#aaaaaa"
        else:
            self.rpm_lbl.setText("-- RPM")
            color = "#666666"

        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        self.live_bar.setText(f"{bar} {pct:.0f}%")
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

    def __init__(self, hw_monitor, curve_engine, state, ctx=None):
        super().__init__()
        self.hw   = hw_monitor
        self.curves = curve_engine
        self.state  = state
        self._ctx   = ctx   # AppContext — routes overrides through FanOverrideRegistry + IPC
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
            widget.calibrate_requested.connect(self._on_calibrate_requested)
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
        """
        User dragged a slider — this is a MANUAL override.
        Route through ctx.set_fan_manual which:
          1. Marks the fan MANUAL in the shared FanOverrideRegistry
             (so the local PollingWorker skips curve computation for it)
          2. Applies the speed immediately
          3. Sends an IPC override message to fanhub-daemon (if running)
             so the daemon ALSO skips this fan instead of fighting the GUI
             with its own curve target on the next poll cycle.
        This is what eliminates the GUI/daemon race condition — previously
        this called self.hw.set_fan_percent() AND curves.assign_fixed(),
        but the daemon's own CurveEngine copy never saw assign_fixed() until
        the next SIGHUP reload, so in between the daemon kept writing its
        old curve target while the GUI wrote the user's chosen speed —
        the fan would flap between the two, sometimes triggering emergency
        mode when the resulting oscillation looked like an uncontrolled fan.
        """
        if self._ctx is not None:
            self._ctx.set_fan_manual(fan_id, pct)
        else:
            # Fallback for legacy callers without ctx (should not happen in
            # normal operation — MainWindow always passes ctx)
            self.hw.set_fan_percent(fan_id, pct)
            self.curves.assign_fixed(fan_id, pct)
        logger.info(f"Fan {fan_id} manually set to {pct:.0f}%")

    def _on_mode_changed(self, fan_id: str, mode: str):
        if mode == 'auto':
            if self._ctx is not None:
                self._ctx.set_fan_auto(fan_id)
            else:
                self.hw.set_fan_auto(fan_id)
            self.curves.fan_assignments.pop(fan_id, None)
            self.curves.fixed_speeds.pop(fan_id, None)
        elif mode == 'dc':
            if fan_id in self.hw.fans:
                fan = self.hw.fans[fan_id]
                if fan.pwm_enable_file:
                    self.hw._write_file(fan.pwm_enable_file, '0')

    def _on_curve_assigned(self, fan_id: str, curve_name: str):
        # Assigning a curve returns the fan to AUTO — release any manual override
        if self._ctx is not None:
            self._ctx.set_fan_auto(fan_id)
        self.curves.assign_curve(fan_id, curve_name)
        logger.info(f"Fan {fan_id} assigned to curve '{curve_name}'")

    def _on_auto_requested(self, fan_id: str):
        if self._ctx is not None:
            self._ctx.set_fan_auto(fan_id)
        else:
            self.hw.set_fan_auto(fan_id)
        self.curves.fan_assignments.pop(fan_id, None)
        self.curves.fixed_speeds.pop(fan_id, None)

    def _on_calibrate_requested(self, fan_id: str):
        """
        Auto-detect PWM polarity without asking the user to understand what
        "inverted" means. Runs a short 2-step test:
          1. Command 100%, wait for it to settle, read RPM.
          2. Command a low speed, wait for it to settle, read RPM.
          3. If the "100%" command produced a LOWER RPM than the low-speed
             command, the fan's PWM is wired backwards — corrected
             automatically. Otherwise, confirm it's already correct.
        The fan is temporarily forced to raw (uninverted) writes during the
        test so the true hardware response is observed, then returned to
        Auto mode when finished.
        """
        fan = self.hw.fans.get(fan_id)
        if not fan or not fan.pwm_file:
            return

        widget = self._widgets.get(fan_id)
        if widget and widget.calibrate_btn:
            widget.calibrate_btn.setEnabled(False)
            widget.calibrate_btn.setText("Calibrating…")

        # Wait long enough to cover the configured poll interval several
        # times over, so current_rpm reflects the settled, post-command speed.
        poll_ms  = self.state.settings.get('poll_interval_ms', 1000)
        settle_ms = max(3500, poll_ms * 3)

        # Remove any manual override so calibration writes aren't fought
        if self._ctx is not None:
            self._ctx.set_fan_auto(fan_id)
        self.curves.fan_assignments.pop(fan_id, None)
        self.curves.fixed_speeds.pop(fan_id, None)

        # Test with raw, uninverted writes to observe true hardware behaviour
        original_inverted = fan.pwm_inverted
        fan.pwm_inverted = False

        self.hw.set_fan_pwm(fan_id, 255)   # command 100%, raw
        QTimer.singleShot(
            settle_ms,
            lambda: self._calibrate_step2(fan_id, original_inverted, settle_ms))

    def _calibrate_step2(self, fan_id: str, original_inverted: bool, settle_ms: int):
        fan = self.hw.fans.get(fan_id)
        if not fan:
            return
        rpm_at_100 = fan.current_rpm

        self.hw.set_fan_pwm(fan_id, 51)    # command ~20%, raw
        QTimer.singleShot(
            settle_ms,
            lambda: self._calibrate_finish(fan_id, original_inverted, rpm_at_100))

    def _calibrate_finish(self, fan_id: str, original_inverted: bool, rpm_at_100: int):
        fan = self.hw.fans.get(fan_id)
        widget = self._widgets.get(fan_id)
        if not fan:
            return

        rpm_at_20 = fan.current_rpm

        if rpm_at_100 == 0 and rpm_at_20 == 0:
            # No tachometer feedback — cannot determine automatically
            fan.pwm_inverted = original_inverted
            result_text = (
                f"Couldn't measure RPM for {fan.label} — this fan may not "
                "report a tachometer signal. If it sounds backwards "
                "(quieter at 100%, louder at low %), let us know in "
                "Settings → report an issue.")
        else:
            # Require a meaningful gap (not just measurement noise) before
            # concluding the fan is actually reversed
            inverted = rpm_at_100 < (rpm_at_20 * 0.85)
            fan.pwm_inverted = inverted
            if self._ctx is not None:
                self._ctx.toggle_pwm_inverted(fan_id, inverted)
            else:
                self.hw.set_pwm_inverted(fan_id, inverted)

            if inverted:
                result_text = (
                    f"{fan.label}: this fan's PWM was wired backwards — "
                    f"100% was producing {rpm_at_100:,} RPM while a lower "
                    f"speed produced {rpm_at_20:,} RPM. Fan Hub has "
                    "corrected it automatically. 100% will now spin the "
                    "fan at full speed as expected.")
            else:
                result_text = (
                    f"{fan.label}: working correctly. 100% produced "
                    f"{rpm_at_100:,} RPM (higher than {rpm_at_20:,} RPM at "
                    "low speed), as expected. No changes needed.")
            logger.info(f"Fan {fan_id} calibration: inverted={inverted} "
                       f"(100%→{rpm_at_100}rpm, 20%→{rpm_at_20}rpm)")

        # Return to Auto — safe default after a calibration test
        if self._ctx is not None:
            self._ctx.set_fan_auto(fan_id)
        else:
            self.hw.set_fan_auto(fan_id)

        if widget and widget.calibrate_btn:
            widget.calibrate_btn.setEnabled(True)
            widget.calibrate_btn.setText("⚙ Calibrate")

        QMessageBox.information(self, "Fan Calibration", result_text)

    def _apply_to_all(self):
        pct = self.global_slider.value()
        for fan_id in self.hw.fans:
            if self._ctx is not None:
                self._ctx.set_fan_manual(fan_id, float(pct))
            else:
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
