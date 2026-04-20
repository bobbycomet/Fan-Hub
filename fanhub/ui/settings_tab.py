"""
Settings Tab — application-wide configuration.

Description clipping fix: SettingRow implements hasHeightForWidth() so Qt
recalculates the row height after the actual pixel width is known at layout
time.  Without this, Qt uses sizeHint() (computed before width is known) and
the wrapped description label is clipped to a single-line height.
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QGroupBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit,
    QFrame, QScrollArea, QMessageBox, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt

logger = logging.getLogger('fanhub.settings')

CTRL_W = 220   # fixed width for right-column controls


# ── Helpers ───────────────────────────────────────────────────────────────────

def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet("background-color: #1e2a40; border: none; margin: 0;")
    return f


def _desc_label(text: str) -> QLabel:
    """
    Grey description label.
    setWordWrap(True) alone is not enough — we also need
    setSizePolicy(Expanding, Preferred) so the label can grow taller.
    The parent SettingRow uses hasHeightForWidth to ensure Qt asks for the
    correct height once the actual column width is known.
    """
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    # Expanding horizontally + Preferred vertically: label uses available width
    # and asks for as much height as the wrapped text needs.
    lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    lbl.setStyleSheet(
        "color: #7a8fa8; font-size: 12px; "
        "background: transparent; border: none; padding: 0;"
    )
    return lbl


def _name_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(False)
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    lbl.setStyleSheet(
        "color: #d4e5f7; font-size: 13px; font-weight: bold; "
        "background: transparent; border: none; padding: 0;"
    )
    return lbl


# ── SettingRow ────────────────────────────────────────────────────────────────

class SettingRow(QWidget):
    """
    One row: left block (name + description) | right block (control).

    hasHeightForWidth() returns True so Qt calls heightForWidth(w) to
    recalculate the row height after it knows the actual pixel width.
    This is the key: without it Qt uses sizeHint() computed before wrapping
    and clips the description to a single line.
    """

    def __init__(self, label: str, control: QWidget,
                 description: str = "", parent=None):
        super().__init__(parent)
        # MinimumExpanding so the row never gets shorter than its content
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 14)
        layout.setSpacing(20)

        # ── Left: name + description ──────────────────────────────────────────
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.MinimumExpanding)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        # AlignTop: left widget grows downward — never centred/clipped
        lv.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._name_lbl = _name_label(label)
        lv.addWidget(self._name_lbl)

        self._desc_lbl = None
        if description:
            self._desc_lbl = _desc_label(description)
            lv.addWidget(self._desc_lbl)

        # ── Right: control ────────────────────────────────────────────────────
        right = QWidget()
        right.setSizePolicy(QSizePolicy.Policy.Fixed,
                            QSizePolicy.Policy.Preferred)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        if not isinstance(control, QCheckBox):
            control.setFixedWidth(CTRL_W)
        rv.addWidget(control)

        layout.addWidget(left,  1)   # left expands
        layout.addWidget(right, 0)   # right is fixed

    # ── Height-for-width — the actual fix ────────────────────────────────────

    def hasHeightForWidth(self) -> bool:
        """Tell Qt's layout engine to call heightForWidth() for this widget."""
        return True

    def heightForWidth(self, width: int) -> int:
        """
        Compute the correct row height for the given pixel width.
        We subtract the right column width and spacing to get the width
        available for the left (text) column, then ask each label how tall
        it needs to be at that width.
        """
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()
        v_margin = margins.top() + margins.bottom()

        # Available width for the left column
        left_w = max(50, width
                     - margins.left() - margins.right()
                     - spacing
                     - CTRL_W)

        # Name label: single line, height = fontMetrics lineSpacing
        name_h = self._name_lbl.fontMetrics().lineSpacing() + 2

        # Description label: ask Qt how tall it needs at left_w
        desc_h = 0
        if self._desc_lbl is not None:
            desc_h = self._desc_lbl.heightForWidth(left_w)
            if desc_h < 0:
                # heightForWidth returned -1 (not supported) — use sizeHint
                desc_h = self._desc_lbl.sizeHint().height()
            desc_h += 6   # spacing between name and desc

        content_h = name_h + desc_h
        return content_h + v_margin

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        # Before width is known use a generous default
        return QSize(400, self.heightForWidth(900))

    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(300, self.heightForWidth(500))


# ── SettingsSection ───────────────────────────────────────────────────────────

class SettingsSection(QGroupBox):
    """QGroupBox with a VBox of SettingRows + dividers."""

    def __init__(self, title: str):
        super().__init__(title)
        self.setObjectName("settingsGroup")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)

        self._inner = QVBoxLayout(self)
        self._inner.setContentsMargins(16, 6, 16, 14)
        self._inner.setSpacing(0)
        self._has_rows = False

    def add_row(self, label: str, control: QWidget, description: str = ""):
        if self._has_rows:
            self._inner.addWidget(_divider())
        self._inner.addWidget(SettingRow(label, control, description))
        self._has_rows = True

    def add_full(self, widget: QWidget):
        if self._has_rows:
            self._inner.addWidget(_divider())
        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Preferred)
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 8, 0, 8)
        wl.addWidget(widget)
        self._inner.addWidget(wrapper)
        self._has_rows = True

    def add_buttons(self, *buttons):
        if self._has_rows:
            self._inner.addWidget(_divider())
        bw = QWidget()
        bh = QHBoxLayout(bw)
        bh.setContentsMargins(0, 8, 0, 6)
        bh.setSpacing(10)
        for b in buttons:
            bh.addWidget(b)
        bh.addStretch()
        self._inner.addWidget(bw)
        self._has_rows = True


# ── Main tab ──────────────────────────────────────────────────────────────────

class SettingsTab(QWidget):

    def __init__(self, state, main_window):
        super().__init__()
        self.state       = state
        self.main_window = main_window
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Horizontal scroll off — forces the content to wrap at the scroll width
        # which is what triggers heightForWidth recalculation
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Preferred)
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.setSpacing(16)

        # ── Polling ───────────────────────────────────────────────────────────
        s_poll = SettingsSection("Polling & Performance")

        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(250, 10000)
        self.poll_spin.setSuffix(" ms")
        self.poll_spin.setSingleStep(250)
        s_poll.add_row(
            "Poll interval",
            self.poll_spin,
            "How often Fan Hub reads temperatures and fan speeds from the hardware. "
            "1000 ms (once per second) is recommended. "
            "Lower values are more responsive but use slightly more CPU. "
            "250 ms is the minimum; 5000 ms is fine for background-only use."
        )

        self.temp_unit = QComboBox()
        self.temp_unit.addItems(["Celsius (°C)", "Fahrenheit (°F)"])
        s_poll.add_row(
            "Temperature unit",
            self.temp_unit,
            "The unit used for all temperature displays across every tab. "
            "Changing this takes effect immediately after saving."
        )
        layout.addWidget(s_poll)

        # ── Safety ────────────────────────────────────────────────────────────
        s_safety = SettingsSection("Safety & Limits")

        self.safe_mode = QCheckBox("Enabled (recommended)")
        s_safety.add_row(
            "Safe mode",
            self.safe_mode,
            "When enabled, Fan Hub will never command a fan below its minimum "
            "rated RPM. This protects fans not designed for zero-RPM (fan-stop) "
            "operation — forcing them below stall speed can cause them to stop "
            "and not restart. Disable only if all your fans are rated for zero-RPM."
        )

        self.emergency_temp = QDoubleSpinBox()
        self.emergency_temp.setRange(60.0, 110.0)
        self.emergency_temp.setSuffix(" °C")
        self.emergency_temp.setSingleStep(1.0)
        s_safety.add_row(
            "Emergency temperature",
            self.emergency_temp,
            "If any sensor reaches this temperature, Fan Hub immediately overrides "
            "all curves and sets every fan to 100% speed. "
            "A tray notification is also shown. "
            "90°C is a safe default for most CPUs and GPUs."
        )

        self.hysteresis = QDoubleSpinBox()
        self.hysteresis.setRange(0.0, 10.0)
        self.hysteresis.setSuffix(" °C")
        self.hysteresis.setSingleStep(0.5)
        s_safety.add_row(
            "Global hysteresis",
            self.hysteresis,
            "Temperature must change by at least this many degrees before the fan "
            "speed is adjusted. Prevents rapid oscillation when temperature hovers "
            "near a curve point. 2°C is recommended. "
            "Set to 0 to disable (fans will hunt rapidly — not recommended)."
        )
        layout.addWidget(s_safety)

        # ── Interface / Tray ──────────────────────────────────────────────────
        s_tray = SettingsSection("Interface & System Tray")

        self.tray_icon = QCheckBox("Enable tray icon")
        s_tray.add_row(
            "System tray",
            self.tray_icon,
            "When enabled, closing the main window hides Fan Hub to the system "
            "tray instead of quitting. Fan curves and all settings remain active "
            "in the background. Right-click the tray icon to show the window, "
            "switch profiles, or quit. "
            "On Wayland, tray availability depends on your compositor."
        )

        self.start_minimized = QCheckBox("Start hidden")
        s_tray.add_row(
            "Start minimized",
            self.start_minimized,
            "Launch Fan Hub without showing the main window — tray icon only. "
            "Requires the system tray option above to be enabled."
        )
        layout.addWidget(s_tray)

        # ── OpenRGB ───────────────────────────────────────────────────────────
        s_rgb = SettingsSection("OpenRGB Server Connection")

        self.openrgb_host = QLineEdit()
        self.openrgb_host.setPlaceholderText("localhost")
        s_rgb.add_row(
            "Server host",
            self.openrgb_host,
            "The hostname or IP address of the OpenRGB SDK server. "
            "Use 'localhost' when the server runs on this machine. "
            "Change to a LAN IP to control OpenRGB on a different computer."
        )

        self.openrgb_port = QSpinBox()
        self.openrgb_port.setRange(1024, 65535)
        s_rgb.add_row(
            "Server port",
            self.openrgb_port,
            "The TCP port the OpenRGB SDK server listens on. "
            "The default is 6742. Only change this if you started OpenRGB "
            "with a custom --server-port argument."
        )
        layout.addWidget(s_rgb)

        # ── Fan Detection Notes ───────────────────────────────────────────────
        s_detect = SettingsSection("Fan Detection Notes")

        for nm, desc in [
            ("Hub channel detection",
             "Fan Hub identifies hub channels by the chip name in sysfs "
             "(nct6775, nct6796, it87, etc.) and by counting how many fans share "
             "the same controller chip. Hub channels are marked [HUB] in Fan Control."),
            ("Daisy-chained fans",
             "Multiple fans on a single header appear as one channel and are "
             "controlled together at the same speed — this is correct behaviour."),
            ("PWM vs DC mode",
             "Detected from pwmX_enable in sysfs: 0 = DC voltage, "
             "1 = PWM manual, 2 = PWM auto (motherboard). "
             "Some boards do not report this accurately."),
            ("Generic fans with internal controllers",
             "Budget fans (Apevia, Rosewill, no-name RGB) often have an internal "
             "controller and do NOT connect to SYS_FAN for speed control. "
             "These cannot be controlled by Fan Hub."),
        ]:
            blk = QWidget()
            blk.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Preferred)
            bl = QVBoxLayout(blk)
            bl.setContentsMargins(0, 8, 0, 8)
            bl.setSpacing(5)
            bl.setAlignment(Qt.AlignmentFlag.AlignTop)
            bl.addWidget(_name_label(nm))
            bl.addWidget(_desc_label(desc))
            s_detect.add_full(blk)

        layout.addWidget(s_detect)

        # ── Permissions ───────────────────────────────────────────────────────
        s_perm = SettingsSection("Permissions & Hardware Access")

        s_perm.add_full(_desc_label(
            "Writing fan speeds requires root access or a udev rule granting "
            "your user write permission to hwmon sysfs nodes. "
            "The installer creates this rule automatically. "
            "If fan speed writes fail with a permission error, apply the rule below."
        ))

        rule_box = QLabel(
            '<code style="color:#88ddff; font-size:11px; line-height:1.8;">'
            'KERNEL=="hwmon*", SUBSYSTEM=="hwmon", ACTION=="add",<br>'
            'RUN+="/bin/chmod -R a+w /sys%p"'
            '</code>'
        )
        rule_box.setTextFormat(Qt.TextFormat.RichText)
        rule_box.setWordWrap(True)
        rule_box.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Preferred)
        rule_box.setStyleSheet(
            "background:#080d18; border:1px solid #1e2a40; "
            "border-radius:4px; padding:10px 12px;"
        )
        s_perm.add_full(rule_box)

        s_perm.add_full(_desc_label(
            "Save that rule to /etc/udev/rules.d/99-fanhub.rules, then run:\n"
            "  sudo udevadm control --reload-rules && sudo udevadm trigger\n"
            "For liquidctl: sudo usermod -aG plugdev $USER  (then log out/in)."
        ))

        copy_btn = QPushButton("Copy udev rule to clipboard")
        copy_btn.clicked.connect(self._copy_udev_rule)
        open_btn = QPushButton("Open rules folder")
        open_btn.clicked.connect(self._open_rules_dir)
        s_perm.add_buttons(copy_btn, open_btn)
        layout.addWidget(s_perm)

        # ── Save ──────────────────────────────────────────────────────────────
        save_row = QHBoxLayout()
        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("applyBtn")
        save_btn.setFixedWidth(180)
        save_btn.clicked.connect(self._save_settings)
        save_row.addWidget(save_btn)
        save_row.addStretch()
        layout.addLayout(save_row)
        layout.addStretch()

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load_settings(self):
        s = self.state.settings
        self.poll_spin.setValue(s.get("poll_interval_ms", 1000))
        self.emergency_temp.setValue(s.get("emergency_temp", 90.0))
        self.hysteresis.setValue(s.get("hysteresis", 2.0))
        self.safe_mode.setChecked(s.get("safe_mode", True))
        self.openrgb_host.setText(s.get("openrgb_host", "localhost"))
        self.openrgb_port.setValue(s.get("openrgb_port", 6742))
        self.tray_icon.setChecked(s.get("tray_icon", True))
        self.start_minimized.setChecked(s.get("start_minimized", False))
        self.temp_unit.setCurrentIndex(
            0 if s.get("temp_unit", "C") == "C" else 1)

    def _save_settings(self):
        self.state.settings["poll_interval_ms"] = self.poll_spin.value()
        self.state.settings["emergency_temp"]   = self.emergency_temp.value()
        self.state.settings["hysteresis"]       = self.hysteresis.value()
        self.state.settings["safe_mode"]        = self.safe_mode.isChecked()
        self.state.settings["openrgb_host"] = (
            self.openrgb_host.text().strip() or "localhost")
        self.state.settings["openrgb_port"]     = self.openrgb_port.value()
        self.state.settings["tray_icon"]        = self.tray_icon.isChecked()
        self.state.settings["start_minimized"]  = self.start_minimized.isChecked()
        self.state.settings["temp_unit"] = (
            "C" if self.temp_unit.currentIndex() == 0 else "F")

        self.state.save_config()
        self.main_window.update_poll_interval(self.poll_spin.value())
        self.main_window.curve_engine.hysteresis_global = self.hysteresis.value()
        self.main_window.curve_engine.emergency_temp    = self.emergency_temp.value()
        self.main_window.enable_tray(self.tray_icon.isChecked())

        QMessageBox.information(self, "Settings Saved", "All settings have been saved.")

    def _copy_udev_rule(self):
        rule = (
            'KERNEL=="hwmon*", SUBSYSTEM=="hwmon", ACTION=="add", '
            'RUN+="/bin/chmod -R a+w /sys%p"'
        )
        QApplication.clipboard().setText(rule)
        QMessageBox.information(
            self, "Copied",
            "udev rule copied to clipboard.\n\n"
            "Save to: /etc/udev/rules.d/99-fanhub.rules\n\n"
            "Then run:\n"
            "  sudo udevadm control --reload-rules\n"
            "  sudo udevadm trigger"
        )

    def _open_rules_dir(self):
        import subprocess
        d = "/etc/udev/rules.d"
        for cmd in [["xdg-open", d], ["nautilus", d],
                    ["dolphin", d], ["thunar", d]]:
            try:
                subprocess.Popen(cmd)
                return
            except FileNotFoundError:
                continue
        QMessageBox.information(
            self, "Rules Folder",
            f"Open this folder in your file manager:\n{d}"
        )
