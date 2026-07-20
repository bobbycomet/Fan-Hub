"""
Settings Tab — application-wide configuration.
Includes daemon management section.
"""
import logging
import subprocess
import webbrowser
from core.daemon_controller import DaemonController, DaemonStatus
from core.update_checker import (
    UpdateCheckWorker, ReleaseInfo, is_newer,
    FANHUB_CURRENT_VERSION, OPENRGB_SITE, OPENRGB_RELEASES,
    invalidate_cache,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QGroupBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit,
    QFrame, QScrollArea, QMessageBox, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt

logger = logging.getLogger('fanhub.settings')

CTRL_W = 220


# ── Helpers ───────────────────────────────────────────────────────────────────

def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet("background-color: #1e2a40; border: none; margin: 0;")
    return f


def _desc_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
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
    def __init__(self, label: str, control: QWidget,
                 description: str = "", parent=None):
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 14)
        layout.setSpacing(20)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.MinimumExpanding)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        lv.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._name_lbl = _name_label(label)
        lv.addWidget(self._name_lbl)

        self._desc_lbl = None
        if description:
            self._desc_lbl = _desc_label(description)
            self._desc_lbl.setMinimumWidth(0)   # allow shrinking in narrow windows
            lv.addWidget(self._desc_lbl)

        right = QWidget()
        right.setSizePolicy(QSizePolicy.Policy.Fixed,
                            QSizePolicy.Policy.Preferred)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        if not isinstance(control, QCheckBox):
            control.setFixedWidth(CTRL_W)
        control.setSizePolicy(QSizePolicy.Policy.Fixed,
                              QSizePolicy.Policy.Preferred)
        rv.addWidget(control)

        layout.addWidget(left,  1)
        layout.addWidget(right, 0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()
        v_margin = margins.top() + margins.bottom()
        left_w   = max(50, width - margins.left() - margins.right()
                       - spacing - CTRL_W)
        name_h   = self._name_lbl.fontMetrics().lineSpacing() + 2
        desc_h   = 0
        if self._desc_lbl is not None:
            desc_h = self._desc_lbl.heightForWidth(left_w)
            if desc_h < 0:
                desc_h = self._desc_lbl.sizeHint().height()
            desc_h += 6
        return name_h + desc_h + v_margin

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(400, self.heightForWidth(900))

    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(300, self.heightForWidth(500))


# ── SettingsSection ───────────────────────────────────────────────────────────

class SettingsSection(QGroupBox):
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
        # Create all widgets first, THEN load settings
        self._build_ui()
        self._load_settings()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Preferred)
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.setSpacing(16)

        # ── System Configuration ──────────────────────────────────────────────
        s_sysconf = SettingsSection("System Configuration")
        from core.init_system import detect_init, init_name as _init_name_fn
        from ui.appimage_configure_dialog import _detect_distro, _PM_NAMES, _INIT_NAMES
        _did, _dpretty, _pm = _detect_distro()
        _init = detect_init()
        _pm_label   = _PM_NAMES.get(_pm,   _pm   or 'Unknown')
        _init_label = _INIT_NAMES.get(_init, _init or 'Unknown')
        sysinfo_lbl = QLabel(
            f"Distribution: <b>{_dpretty}</b><br>"
            f"Package manager: <b>{_pm_label}</b>&nbsp;&nbsp;"
            f"Init system: <b>{_init_label}</b>"
        )
        sysinfo_lbl.setTextFormat(Qt.TextFormat.RichText)
        sysinfo_lbl.setStyleSheet("color:#8899aa; font-size:12px;")
        sysinfo_lbl.setWordWrap(True)
        s_sysconf.add_full(sysinfo_lbl)
        cfg_btn = QPushButton("⚙ Configure Fan Hub for This System")
        cfg_btn.setToolTip(
            "Installs system dependencies, udev rules, groups, kernel modules "
            "and the daemon service for your distro and init system via pkexec.")
        cfg_btn.clicked.connect(self._open_configure_dialog)
        s_sysconf.add_buttons(cfg_btn)
        layout.addWidget(s_sysconf)

        # ── Polling ───────────────────────────────────────────────────────────
        s_poll = SettingsSection("Polling & Performance")

        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(250, 10000)
        self.poll_spin.setSuffix(" ms")
        self.poll_spin.setSingleStep(250)
        s_poll.add_row("Poll interval", self.poll_spin,
            "How often Fan Hub reads temperatures and fan speeds. "
            "1000 ms is recommended. Lower = more responsive, higher = less CPU.")

        self.temp_unit = QComboBox()
        self.temp_unit.addItems(["Celsius (°C)", "Fahrenheit (°F)"])
        s_poll.add_row("Temperature unit", self.temp_unit,
            "Unit used for all temperature displays. Takes effect after saving.")

        layout.addWidget(s_poll)

        # ── Safety ────────────────────────────────────────────────────────────
        s_safety = SettingsSection("Safety & Limits")

        self.safe_mode = QCheckBox("Enabled (recommended)")
        s_safety.add_row("Safe mode", self.safe_mode,
            "Never command a fan below its minimum rated RPM. "
            "Protects fans not designed for zero-RPM (fan-stop) operation.")

        self.emergency_temp = QDoubleSpinBox()
        self.emergency_temp.setRange(60.0, 110.0)
        self.emergency_temp.setSuffix(" °C")
        self.emergency_temp.setSingleStep(1.0)
        s_safety.add_row("Emergency temperature", self.emergency_temp,
            "If any sensor reaches this value, all fans jump to 100% "
            "and a tray alert fires. 90°C is safe for most hardware.")

        self.hysteresis = QDoubleSpinBox()
        self.hysteresis.setRange(0.0, 10.0)
        self.hysteresis.setSuffix(" °C")
        self.hysteresis.setSingleStep(0.5)
        s_safety.add_row("Global hysteresis", self.hysteresis,
            "Temperature must change by at least this many degrees before fan "
            "speed adjusts. Prevents rapid oscillation near curve points. "
            "2°C is recommended.")

        layout.addWidget(s_safety)

        # ── Interface / Tray ──────────────────────────────────────────────────
        s_tray = SettingsSection("Interface & System Tray")

        self.tray_icon = QCheckBox("Enable tray icon")
        s_tray.add_row("System tray", self.tray_icon,
            "Closing the window hides Fan Hub to the tray instead of quitting. "
            "Fan curves stay active. Right-click the tray icon to show the window, "
            "switch profiles, or quit. On Wayland, depends on your compositor.")

        self.start_minimized = QCheckBox("Start hidden")
        s_tray.add_row("Start minimized", self.start_minimized,
            "Launch without showing the main window — tray icon only. "
            "Requires the system tray option above to be enabled.")

        layout.addWidget(s_tray)

        # ── OpenRGB ───────────────────────────────────────────────────────────
        s_rgb = SettingsSection("OpenRGB Server Connection")

        self.openrgb_host = QLineEdit()
        self.openrgb_host.setPlaceholderText("localhost")
        s_rgb.add_row("Server host", self.openrgb_host,
            "Hostname or IP of the OpenRGB SDK server. "
            "Use 'localhost' when it runs on this machine.")

        self.openrgb_port = QSpinBox()
        self.openrgb_port.setRange(1024, 65535)
        s_rgb.add_row("Server port", self.openrgb_port,
            "TCP port the OpenRGB SDK server listens on. Default is 6742.")

        layout.addWidget(s_rgb)

        # ── Background Daemon ─────────────────────────────────────────────────
        s_daemon = SettingsSection("Background Daemon (fanhub-daemon)")

        self.daemon_enabled = QCheckBox("Run fan curves at boot")
        # Build description dynamically based on detected init system
        from core.init_system import detect_init, init_name as _init_name
        _init = detect_init()
        _init_label = {
            "systemd": "systemd service",
            "runit":   "runit service (sv)",
            "openrc":  "OpenRC service (rc-service)",
        }.get(_init, "background process")
        s_daemon.add_row("Enable daemon", self.daemon_enabled,
            f"When enabled, fanhub-daemon runs as a {_init_label} and applies "
            "your active fan curves at every boot — even without opening the GUI. "
            "Curves are saved to config automatically whenever you change them. "
            "Requires the daemon to be installed (sudo ./install.sh).")

        # Live status label — created here so _refresh_daemon_status always finds it
        self._daemon_status_lbl = QLabel("Checking…")
        self._daemon_status_lbl.setWordWrap(True)
        self._daemon_status_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._daemon_status_lbl.setStyleSheet("color: #667788; font-size: 12px;")
        s_daemon.add_full(self._daemon_status_lbl)

        # Row 1: Enable / Disable at boot
        daemon_enable_btn  = QPushButton("✓ Enable at boot")
        daemon_disable_btn = QPushButton("✗ Disable at boot")
        daemon_enable_btn.setToolTip(
            "Register the daemon with your init system so it starts automatically "
            "at every boot. Also starts it immediately if not already running.")
        daemon_disable_btn.setToolTip(
            "Remove the daemon from boot startup. "
            "Also stops it if currently running.")
        daemon_enable_btn.clicked.connect(self._daemon_enable_now)
        daemon_disable_btn.clicked.connect(self._daemon_disable_now)
        s_daemon.add_buttons(daemon_enable_btn, daemon_disable_btn)

        # Row 2: Start / Stop / Restart / Reload
        daemon_start_btn   = QPushButton("▶ Start")
        daemon_stop_btn    = QPushButton("■ Stop")
        daemon_restart_btn = QPushButton("↺ Restart")
        daemon_reload_btn  = QPushButton("⟳ Reload curves")
        daemon_restart_btn.setToolTip(
            "Stop the daemon and start it again. Use this after manual config changes.")
        daemon_reload_btn.setToolTip(
            "Save current fan curves and send SIGHUP to the daemon "
            "so it applies them immediately without a full restart.")
        daemon_start_btn.clicked.connect(self._daemon_start_now)
        daemon_stop_btn.clicked.connect(self._daemon_stop_now)
        daemon_restart_btn.clicked.connect(self._daemon_restart_now)
        daemon_reload_btn.clicked.connect(self._daemon_reload_now)
        s_daemon.add_buttons(
            daemon_start_btn, daemon_stop_btn,
            daemon_restart_btn, daemon_reload_btn)

        from core.init_system import detect_init as _di
        _init_hint = {
            "systemd": "systemctl status fanhub-daemon",
            "runit":   "sv status fanhub-daemon",
            "openrc":  "rc-service fanhub-daemon status",
        }.get(_di(), "check your init system")
        s_daemon.add_full(_desc_label(
            "The daemon runs as root and reads the same config.json as the GUI. "
            "Whenever you save settings, load a profile, or apply a preset, "
            "Fan Hub automatically saves curves and signals the daemon to reload. "
            f"Log: ~/.config/fanhub/fanhub-daemon.log  |  Status: {_init_hint}"
        ))
        layout.addWidget(s_daemon)

        # ── Fan Detection Notes ───────────────────────────────────────────────
        s_detect = SettingsSection("Fan Detection Notes")

        for nm, desc in [
            ("Hub channel detection",
             "Identified by chip name (nct6775, nct6796, it87, etc.) and number of "
             "fans sharing the same controller. Hub channels are marked [HUB]."),
            ("Daisy-chained fans",
             "Multiple fans on one header appear as a single channel — "
             "all controlled at the same speed. This is correct behaviour."),
            ("PWM vs DC mode",
             "Detected from pwmX_enable in sysfs: 0=DC, 1=PWM manual, 2=PWM auto. "
             "Some boards report this inaccurately."),
            ("Generic fans with internal controllers",
             "Budget fans (Apevia, Rosewill, no-name RGB) have internal controllers "
             "and do NOT connect to SYS_FAN for speed control — "
             "Fan Hub cannot control these."),
            ("GPU fans",
             "AMD GPU fans are fully controllable via amdgpu hwmon. "
             "NVIDIA fans require CoolBits=4 or nvidia-settings. "
             "GPU fans default to the Performance curve unless a profile overrides them. "
             "GPU fans showing 0 RPM is normal — they only expose % speed, not RPM tachometer, "
             "unless CoolBits is enabled."),
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
        polkit_btn = QPushButton("Install polkit policy")
        polkit_btn.setToolTip(
            "Install the Fan Hub polkit policy so pkexec can launch "
            "Fan Hub without a password prompt every time.")
        polkit_btn.clicked.connect(self._install_polkit)
        s_perm.add_buttons(copy_btn, open_btn, polkit_btn)
        layout.addWidget(s_perm)

        # ── Updates ──────────────────────────────────────────────────────────
        s_updates = SettingsSection("Software Updates")

        # Fan Hub row
        self._fh_version_lbl = QLabel(f"Current version: {FANHUB_CURRENT_VERSION}")
        self._fh_version_lbl.setStyleSheet("color:#aabbcc; font-size:12px;")
        s_updates.add_full(self._fh_version_lbl)

        self._fh_status_lbl = QLabel("Latest: checking…")
        self._fh_status_lbl.setStyleSheet("color:#556677; font-size:12px;")
        s_updates.add_full(self._fh_status_lbl)

        self._fh_asset_layout = QHBoxLayout()
        self._fh_asset_layout.setSpacing(8)
        fh_asset_w = QWidget()
        fh_asset_w.setLayout(self._fh_asset_layout)
        s_updates.add_full(fh_asset_w)

        # OpenRGB row
        self._rgb_status_lbl = QLabel("OpenRGB — checking…")
        self._rgb_status_lbl.setStyleSheet("color:#556677; font-size:12px;")
        s_updates.add_full(self._rgb_status_lbl)

        # Wrap OpenRGB buttons in a scroll area — there can be many assets
        self._rgb_asset_layout = QHBoxLayout()
        self._rgb_asset_layout.setSpacing(6)
        self._rgb_asset_layout.setContentsMargins(0, 0, 0, 0)
        rgb_asset_inner = QWidget()
        rgb_asset_inner.setLayout(self._rgb_asset_layout)
        rgb_asset_scroll = QScrollArea()
        rgb_asset_scroll.setWidget(rgb_asset_inner)
        rgb_asset_scroll.setWidgetResizable(True)
        rgb_asset_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        rgb_asset_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rgb_asset_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rgb_asset_scroll.setFixedHeight(38)
        s_updates.add_full(rgb_asset_scroll)

        check_btn = QPushButton("🔄 Check for Updates")
        check_btn.clicked.connect(self._run_update_check)
        s_updates.add_buttons(check_btn)
        layout.addWidget(s_updates)

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
        # Daemon: reflect real systemd state, not just saved setting
        self._refresh_daemon_status()
        # Kick off update check in background
        self._run_update_check()

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
        self.state.settings["daemon_enabled"]   = self.daemon_enabled.isChecked()

        self.state.save_config()
        self.main_window.update_poll_interval(self.poll_spin.value())
        self.main_window.curve_engine.hysteresis_global = self.hysteresis.value()
        self.main_window.curve_engine.emergency_temp    = self.emergency_temp.value()
        self.main_window.enable_tray(self.tray_icon.isChecked())

        # Apply daemon enable/disable via DaemonController (init-system aware)
        if self.daemon_enabled.isChecked():
            DaemonController.enable()
        else:
            DaemonController.disable()
        self._refresh_daemon_status()

        QMessageBox.information(self, "Settings Saved", "All settings have been saved.")

    # ── Daemon helpers ────────────────────────────────────────────────────────

    def _refresh_daemon_status(self):
        """Query the init system via DaemonController and update the status label."""
        st = DaemonController.status()
        text, color = st.summary()
        self._daemon_status_lbl.setText(text)
        self._daemon_status_lbl.setStyleSheet(f"color: {color}; font-size: 12px;")

        can_manage = st.installed and not st.no_init_support
        self.daemon_enabled.setEnabled(can_manage)
        if can_manage:
            self.daemon_enabled.blockSignals(True)
            self.daemon_enabled.setChecked(st.enabled)
            self.daemon_enabled.blockSignals(False)
        else:
            self.daemon_enabled.setChecked(False)

    def _daemon_enable_now(self):
        """Enable daemon at boot AND start it immediately."""
        DaemonController.enable()
        self._refresh_daemon_status()

    def _daemon_disable_now(self):
        """Disable daemon from boot AND stop it immediately."""
        DaemonController.disable()
        self._refresh_daemon_status()

    def _daemon_start_now(self):
        DaemonController.start()
        self._refresh_daemon_status()

    def _daemon_stop_now(self):
        DaemonController.stop()
        self._refresh_daemon_status()

    def _daemon_restart_now(self):
        """Stop then start the daemon."""
        from core.init_system import detect_init
        init = detect_init()
        if init == 'systemd':
            DaemonController._run('restart', 'fanhub-daemon', timeout=10)
        else:
            DaemonController.stop()
            import time; time.sleep(1)
            DaemonController.start()
        self._refresh_daemon_status()

    def _daemon_reload_now(self):
        """Save current curves and SIGHUP the daemon."""
        try:
            self.main_window._save_curves_to_config()
            QMessageBox.information(
                self, "Reloaded",
                "Current fan curves saved.\n"
                "The daemon will apply them on its next poll cycle.")
        except Exception as e:
            QMessageBox.warning(self, "Daemon", f"Reload failed:\n{e}")
        self._refresh_daemon_status()

    # ── Permissions helpers ───────────────────────────────────────────────────


    # ── Update checker ────────────────────────────────────────────────────────

    def _run_update_check(self, force: bool = False):
        """Start background update check. Called on tab load and by button."""
        if force:
            invalidate_cache()
        self._fh_status_lbl.setText("Latest: checking…")
        self._fh_status_lbl.setStyleSheet("color:#556677; font-size:12px;")
        self._rgb_status_lbl.setText("OpenRGB — checking…")
        self._rgb_status_lbl.setStyleSheet("color:#556677; font-size:12px;")
        self._clear_asset_buttons(self._fh_asset_layout)
        self._clear_asset_buttons(self._rgb_asset_layout)

        worker = UpdateCheckWorker(self)
        worker.fanhub_result.connect(self._on_fanhub_result)
        worker.openrgb_result.connect(self._on_openrgb_result)
        worker.start()
        self._update_worker = worker   # keep reference alive

    def _on_fanhub_result(self, info: ReleaseInfo):
        self._clear_asset_buttons(self._fh_asset_layout)
        if not info.ok:
            self._fh_status_lbl.setText(f"Latest: unavailable ({info.error})")
            self._fh_status_lbl.setStyleSheet("color:#556677; font-size:12px;")
            return

        if is_newer(info.version, FANHUB_CURRENT_VERSION):
            self._fh_status_lbl.setText(
                f"⬆  Update available: v{info.version}")
            self._fh_status_lbl.setStyleSheet("color:#44ff88; font-size:12px;")
        else:
            self._fh_status_lbl.setText(
                f"✓  Up to date  (latest: v{info.version})")
            self._fh_status_lbl.setStyleSheet("color:#44dd88; font-size:12px;")

        # Show one download button per asset type
        for label, url in info.assets.items():
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                "QPushButton { color:#00ddff; background:#0d1f33; "
                "border:1px solid #1a3a5c; border-radius:3px; "
                "font-size:11px; padding:0 8px; }"
                "QPushButton:hover { background:#1a3050; }")
            btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
            self._fh_asset_layout.addWidget(btn)
        self._fh_asset_layout.addStretch()

    def _on_openrgb_result(self, info: ReleaseInfo):
        self._clear_asset_buttons(self._rgb_asset_layout)
        if info.error and not info.version:
            self._rgb_status_lbl.setText(f"OpenRGB — unavailable ({info.error})")
            self._rgb_status_lbl.setStyleSheet("color:#556677; font-size:12px;")
        elif info.error:
            # Partial result — show version but note the error
            self._rgb_status_lbl.setText(
                f"OpenRGB — latest known: v{info.version}  ({info.error})")
            self._rgb_status_lbl.setStyleSheet("color:#ffaa44; font-size:12px;")
        else:
            self._rgb_status_lbl.setText(
                f"OpenRGB — latest: v{info.version}")
            self._rgb_status_lbl.setStyleSheet("color:#aabbcc; font-size:12px;")

        for label, url in info.assets.items():
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                "QPushButton { color:#00ddff; background:#0d1f33; "
                "border:1px solid #1a3a5c; border-radius:3px; "
                "font-size:11px; padding:0 8px; }"
                "QPushButton:hover { background:#1a3050; }")
            btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
            self._rgb_asset_layout.addWidget(btn)
        self._rgb_asset_layout.addStretch()

    @staticmethod
    def _clear_asset_buttons(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()



    def _open_configure_dialog(self):
        """Open the full system configuration dialog."""
        from ui.appimage_configure_dialog import AppImageConfigureDialog
        import os
        appdir = os.environ.get('FANHUB_APPDIR', '')
        dlg = AppImageConfigureDialog(appdir=appdir, parent=self)
        dlg.configured.connect(lambda: self._refresh_daemon_status())
        dlg.exec()

    def _install_polkit(self):
        """Install the polkit policy via pkexec."""
        import os
        policy_src = os.path.join('/opt/fanhub/assets', 'org.fanhub.policy')
        # Also try AppImage path
        if not os.path.exists(policy_src):
            appdir = os.environ.get('FANHUB_APPDIR', '')
            policy_src = os.path.join(appdir, 'usr/share/fanhub/assets/org.fanhub.policy')
        if not os.path.exists(policy_src):
            QMessageBox.warning(self, "polkit",
                "org.fanhub.policy not found.\n"
                "Run sudo ./install.sh to install it.")
            return
        try:
            subprocess.run(
                ['pkexec', 'cp', policy_src,
                 '/usr/share/polkit-1/actions/org.fanhub.policy'],
                timeout=15)
            QMessageBox.information(self, "polkit",
                "polkit policy installed.\n"
                "Fan Hub can now launch via pkexec without repeated password prompts.")
        except Exception as e:
            QMessageBox.warning(self, "polkit", f"Failed to install polkit policy:\n{e}")

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
        import subprocess as sp
        d = "/etc/udev/rules.d"
        for cmd in [["xdg-open", d], ["nautilus", d],
                    ["dolphin", d], ["thunar", d]]:
            try:
                sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL,
                         start_new_session=True)
                return
            except FileNotFoundError:
                continue
        QMessageBox.information(
            self, "Rules Folder",
            f"Open this folder in your file manager:\n{d}"
        )
