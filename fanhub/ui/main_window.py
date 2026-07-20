"""
Fan Hub — Main Window
Tray icon is owned by QApplication (not the window) so it survives window close.
Worker thread is also independent — keeps curves running while hidden.
Closing the window → hides to tray (app keeps running, settings stay active).
Quitting from tray → asks to restore fans, then truly exits.

FIXES (v1.3.1):
  - Tab names no longer clipped — setElideMode(None) + usesScrollButtons(True)
  - Tray single-click always SHOWS the window (never hides) for discoverability
  - Backend init (liquidctl, OpenRGB) deferred to background thread → faster startup
  - Global font size bumped to 12 px minimum so settings labels are readable
  - Tab bar minimum width enforced so short tabs don't compress long names
"""
import logging
import os
import time
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton,
    QMessageBox, QSystemTrayIcon, QMenu,
    QFrame, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QBrush, QPen, QFont

from core.hardware_monitor import HardwareMonitor
from core.fan_curves import CurveEngine, ProfileManager
from core.rgb_manager import OpenRGBManager
from core.liquidctl_manager import LiquidctlManager
from core.polling_worker import PollingWorker

from ui.dashboard_tab import DashboardTab
from ui.fan_control_tab import FanControlTab
from ui.fan_curves_tab import FanCurvesTab
from ui.rgb_tab import RGBTab
from ui.liquid_tab import LiquidTab
from ui.profiles_tab import ProfilesTab
from ui.settings_tab import SettingsTab
from ui.fan_warning_dialog import FanWarningDialog
from ui.hardware_summary_dialog import HardwareSummaryDialog
from ui.first_run_wizard import FirstRunWizard
from core.daemon_controller import DaemonController
from core.ipc import IPCClient
from core.update_checker import UpdateCheckWorker, is_newer, FANHUB_CURRENT_VERSION, invalidate_cache
from core.app_context import AppContext

logger = logging.getLogger('fanhub.mainwindow')


# ── Module-level tray owner (lives for the process lifetime) ──────────────────

# ── Background backend initialiser ────────────────────────────────────────────

class BackendInitThread(QThread):
    """
    Initialises OpenRGB and liquidctl in a background thread so the UI
    appears immediately without waiting for USB/network discovery.
    """
    done = pyqtSignal(object, object)   # rgb_manager, liquid_manager

    def __init__(self, state):
        super().__init__()
        self.state = state

    def run(self):
        rgb = None
        liquid = None
        try:
            rgb = OpenRGBManager(
                host=self.state.settings.get('openrgb_host', 'localhost'),
                port=self.state.settings.get('openrgb_port', 6742),
            )
        except Exception as e:
            logger.warning(f"RGB init failed: {e}")

        try:
            liquid = LiquidctlManager()
        except Exception as e:
            logger.warning(f"Liquidctl init failed: {e}")

        self.done.emit(rgb, liquid)


class MainWindow(QMainWindow):

    def __init__(self, state, app_icon=None, platform='xcb'):
        super().__init__()
        self.state     = state
        self._app_icon  = app_icon
        self._platform  = platform
        self._tray_icon: QSystemTrayIcon = None  # instance attr, not global

        # Backends — filled synchronously for hw, async for rgb/liquid
        self.rgb_manager    = None
        self.liquid_manager = None

        self.setWindowTitle("Fan Hub — Linux Fan Controller")
        self.setMinimumSize(1100, 750)
        self.resize(1380, 880)
        if app_icon:
            self.setWindowIcon(app_icon)

        # ── Instance flags (must exist before any method can reference them) ──
        self._emergency_manual = False   # True when user manually activated emergency
        self._quitting         = False   # True during the quit sequence

        # ── Boost global font so settings text is always legible ──────────────
        app = QApplication.instance()
        font = app.font()
        if font.pointSize() > 0 and font.pointSize() < 10:
            font.setPointSize(10)
        elif font.pixelSize() > 0 and font.pixelSize() < 13:
            font.setPixelSize(13)
        app.setFont(font)

        self._init_hw_backends()     # fast — only hwmon sysfs
        self._build_ui()
        self._start_polling()
        self._setup_tray()

        if state.active_profile:
            loaded = self.profile_manager.load_profile(
                state.active_profile, self.curve_engine)
            if loaded:
                logger.info(f"Auto-loaded profile on startup: {state.active_profile}")
                # Update the profiles tab UI to show the active profile
                self.profiles_tab._refresh_list()
                self.profiles_tab._update_active_label()

        # Defer slow backends (OpenRGB + liquidctl) to background thread
        self._backend_thread = BackendInitThread(state)
        # MUST connect before start() — thread may finish before event loop
        self._backend_thread.done.connect(self._on_backends_ready)
        self._backend_thread.start()

        # Sleep/resume recovery
        try:
            from core.sleep_monitor import SleepMonitor
            self._sleep_monitor = SleepMonitor(self)
            self._sleep_monitor.resumed.connect(self._rescan_hardware)
        except Exception as e:
            logger.debug(f"SleepMonitor: {e}")

        if not state.settings.get('suppress_fan_warning', False):
            QTimer.singleShot(2500, self._show_fan_warning)

    # ─────────────────────────────────────────────
    #  Backends
    # ─────────────────────────────────────────────

    def _init_hw_backends(self):
        """Fast init — only hwmon (sysfs reads). No USB, no network."""
        logger.info("Initialising hardware monitor…")
        self.hw_monitor   = HardwareMonitor()
        # Restore any saved per-fan PWM inversion overrides
        self.hw_monitor.apply_inverted_flags(
            self.state.settings.get('pwm_inverted_fans', {}))
        self.curve_engine = CurveEngine(
            hysteresis_global=self.state.settings.get('hysteresis', 2.0),
            emergency_temp   =self.state.settings.get('emergency_temp', 90.0),
        )
        self.profile_manager = ProfileManager(self.state)

        # GPU fans: default to 'performance' curve unless the active profile
        # already has an assignment for them
        for fid, fan in self.hw_monitor.fans.items():
            if fan.gpu_vendor and fan.controllable:
                if fid not in self.curve_engine.fan_assignments:
                    self.curve_engine.assign_curve(fid, 'performance')

    @pyqtSlot(object, object)
    def _on_backends_ready(self, rgb, liquid):
        """Called when background init completes."""
        self.rgb_manager    = rgb
        self.liquid_manager = liquid

        self.state.openrgb_connected  = rgb.connected    if rgb    else False
        self.state.liquidctl_available = liquid.available if liquid else False

        self._update_indicator(self.openrgb_indicator,   self.state.openrgb_connected)
        self._update_indicator(self.liquidctl_indicator, self.state.liquidctl_available)

        # Wire up liquid tab now that manager exists
        self.liquid_tab.late_init(self.liquid_manager)
        # Wire up RGB tab
        self.rgb_tab.late_init(self.rgb_manager)
        # Give worker the managers
        self.worker.liquid  = self.liquid_manager
        self.worker.rgb     = self.rgb_manager

        logger.info("Background backends ready: "
                    f"RGB={'ok' if self.state.openrgb_connected else 'off'}, "
                    f"liquidctl={'ok' if self.state.liquidctl_available else 'off'}")

        # Show first-run wizard if system has not been configured yet.
        # system_configure_done is set by AppImageConfigureDialog or install.sh.
        # first_run_done is set by the wizard on completion.
        # The wizard shows every launch until BOTH are satisfied.
        system_done = self.state.settings.get('system_configure_done', False)
        wizard_done = self.state.settings.get('first_run_done', False)
        if not wizard_done or not system_done:
            # If the app was installed via tarball/deb (not AppImage), treat
            # system as already configured — only show wizard for first-run setup.
            if not system_done and not os.environ.get('FANHUB_APPIMAGE'):
                self.state.settings['system_configure_done'] = True
                system_done = True
            self._show_first_run_wizard()
        else:
            self._finish_startup()

    # ─────────────────────────────────────────────
    #  UI
    # ─────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_topbar(root)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # ── FIX: prevent tab labels from being elided / cut off ───────────────
        tab_bar = self.tabs.tabBar()
        tab_bar.setElideMode(Qt.TextElideMode.ElideNone)   # never truncate labels
        tab_bar.setUsesScrollButtons(True)                  # scroll if truly too wide
        tab_bar.setExpanding(False)                         # don't stretch tabs thin
        # Give each tab a comfortable minimum width
        tab_bar.setStyleSheet(
            "QTabBar::tab { min-width: 100px; padding: 6px 14px; font-size: 12px; }"
        )

        root.addWidget(self.tabs)

        self._ctx = AppContext(
            state          = self.state,
            hw_monitor     = self.hw_monitor,
            curve_engine   = self.curve_engine,
            profile_manager= self.profile_manager,
            on_curves_changed    = self._save_curves_to_config,
            on_profile_loaded    = self._tray_load_profile,
            on_tray_menu_refresh = self.refresh_tray_menu,
            # Lazy lambdas — self.worker is created in _start_polling(), which
            # runs AFTER _build_ui(). Binding self.worker.X directly here would
            # fail since the attribute doesn't exist yet at construction time.
            set_fan_manual       = lambda fid, spd: self.worker.set_fan_manual(fid, spd),
            set_fan_auto         = lambda fid: self.worker.set_fan_auto(fid),
            set_all_auto         = lambda: self.worker.set_all_auto(),
            toggle_pwm_inverted  = self.toggle_pwm_inverted,
        )

        self.dashboard_tab   = DashboardTab(self.hw_monitor, self.state)
        self.fan_control_tab = FanControlTab(self.hw_monitor, self.curve_engine,
                                             self.state, ctx=self._ctx)
        self.curves_tab      = FanCurvesTab(self.hw_monitor, self.curve_engine, self.state)
        # Pass None managers initially — they are filled by _on_backends_ready
        self.rgb_tab         = RGBTab(None, self.state)
        self.liquid_tab      = LiquidTab(None, self.curve_engine, self.state)
        self.profiles_tab    = ProfilesTab(
            self.profile_manager, self.curve_engine, None, self.state,
            ctx=self._ctx)
        self.settings_tab    = SettingsTab(self.state, self)

        self.tabs.addTab(self.dashboard_tab,   "Dashboard")
        self.tabs.addTab(self.fan_control_tab, "Fan Control")
        self.tabs.addTab(self.curves_tab,      "Fan Curves")
        self.tabs.addTab(self.rgb_tab,         "RGB Lighting")
        self.tabs.addTab(self.liquid_tab,      "Liquid / AIO")
        self.tabs.addTab(self.profiles_tab,    "Profiles")
        self.tabs.addTab(self.settings_tab,    "Settings")

        self._build_statusbar()

    def _build_topbar(self, layout):
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(54)
        hbox = QHBoxLayout(topbar)
        hbox.setContentsMargins(12, 0, 16, 0)
        hbox.setSpacing(10)

        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'assets', 'icon_48.png')
        if not os.path.exists(icon_path):
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'assets', 'icon.png')
        if os.path.exists(icon_path):
            from PyQt6.QtGui import QPixmap
            icon_lbl = QLabel()
            pix = QPixmap(icon_path).scaled(
                38, 38,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            icon_lbl.setPixmap(pix)
            icon_lbl.setFixedSize(42, 42)
            hbox.addWidget(icon_lbl)

        title = QLabel("FAN HUB")
        title.setObjectName("appTitle")
        hbox.addWidget(title)
        hbox.addStretch()

        # Emergency state indicator — shows NORMAL or EMERGENCY ACTIVE
        self.emergency_state_lbl = QLabel("NORMAL")
        self.emergency_state_lbl.setObjectName("emergencyState")
        self.emergency_state_lbl.setStyleSheet(
            "color: #44dd88; font-size: 10px; font-weight: bold; "
            "padding: 2px 6px; border: 1px solid #1e3a20; border-radius: 3px; "
            "background: #0a1a0e;")
        hbox.addWidget(self.emergency_state_lbl)

        self.emergency_btn = QPushButton("Activate Emergency Mode")
        self.emergency_btn.setObjectName("emergencyBtn")
        self.emergency_btn.setToolTip(
            "Immediately set ALL fans to 100% regardless of curves.\n"
            "Use during thermal emergencies. Click again to deactivate.")
        self.emergency_btn.clicked.connect(self._toggle_emergency)
        hbox.addWidget(self.emergency_btn)

        self.auto_btn = QPushButton("All Auto")
        self.auto_btn.setObjectName("autoBtn")
        self.auto_btn.setToolTip("Return all fans to motherboard auto control")
        self.auto_btn.clicked.connect(self._all_fans_auto)
        hbox.addWidget(self.auto_btn)

        self.openrgb_indicator = QLabel("● OpenRGB")
        self.openrgb_indicator.setObjectName("statusDot")
        self._update_indicator(self.openrgb_indicator, False)   # unknown until async done
        hbox.addWidget(self.openrgb_indicator)

        self.liquidctl_indicator = QLabel("● liquidctl")
        self.liquidctl_indicator.setObjectName("statusDot")
        self._update_indicator(self.liquidctl_indicator, False)
        hbox.addWidget(self.liquidctl_indicator)

        plat_lbl = QLabel(f"[{self._platform.upper()}]")
        plat_lbl.setStyleSheet("color: #334455; font-size: 10px;")
        plat_lbl.setToolTip(f"Display platform: {self._platform}")
        hbox.addWidget(plat_lbl)

        diag_btn = QPushButton("Diagnostics")
        diag_btn.setObjectName("scanBtn")
        diag_btn.setToolTip("Open hardware detection summary and system diagnostics")
        diag_btn.clicked.connect(self._show_diagnostics)
        hbox.addWidget(diag_btn)

        rescan_btn = QPushButton("Rescan")
        rescan_btn.setObjectName("scanBtn")
        rescan_btn.clicked.connect(self._rescan_hardware)
        hbox.addWidget(rescan_btn)

        layout.addWidget(topbar)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.status_label = QLabel("Ready")
        sb.addWidget(self.status_label)

        self.poll_label = QLabel()
        sb.addPermanentWidget(self.poll_label)

        # "Last updated Xs ago" — ticks every second so the user can see at
        # a glance that Fan Hub is alive and actively polling, independent
        # of the poll interval itself.
        self.last_update_label = QLabel("Updated just now")
        self.last_update_label.setStyleSheet("color: #445566; font-size: 11px;")
        sb.addPermanentWidget(self.last_update_label)
        self._last_update_time = time.monotonic()
        self._update_ticker = QTimer(self)
        self._update_ticker.setInterval(1000)
        self._update_ticker.timeout.connect(self._tick_last_update)
        self._update_ticker.start()

        self.emergency_label = QLabel()
        self.emergency_label.setStyleSheet("color: #ff4444; font-weight: bold;")
        sb.addPermanentWidget(self.emergency_label)

        tray_hint = QLabel("Close window → hides to tray  |  Right-click tray → Quit")
        tray_hint.setStyleSheet("color: #334455; font-size: 10px;")
        sb.addPermanentWidget(tray_hint)

    def _tick_last_update(self):
        elapsed = int(time.monotonic() - self._last_update_time)
        if elapsed < 2:
            self.last_update_label.setText("Updated just now")
        elif elapsed < 60:
            self.last_update_label.setText(f"Updated {elapsed}s ago")
        else:
            self.last_update_label.setText(f"Updated {elapsed // 60}m ago")
        # Warn visually if updates have stalled (worker died / hung)
        if elapsed > 10:
            self.last_update_label.setStyleSheet("color: #ff8844; font-size: 11px;")
        else:
            self.last_update_label.setStyleSheet("color: #445566; font-size: 11px;")

    # ─────────────────────────────────────────────
    #  Tray — parented to QApplication, not window
    # ─────────────────────────────────────────────

    def _make_tray_icon(self) -> QIcon:
        if self._app_icon and not self._app_icon.isNull():
            return self._app_icon
        pix = QPixmap(32, 32)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor("#00ccff")))
        p.setPen(QPen(QColor("#0088cc"), 2))
        p.drawEllipse(2, 2, 28, 28)
        p.end()
        return QIcon(pix)

    def _setup_tray(self):
        if not self.state.settings.get('tray_icon', True):
            return

        app = QApplication.instance()

        if self._tray_icon is not None:
            self._tray_icon.hide()
            self._tray_icon = None

        self._tray_icon = QSystemTrayIcon(self._make_tray_icon(), app)
        self._tray_icon.setToolTip("Fan Hub — running in background")

        self._rebuild_tray_menu()

        # FIX: single-click (Trigger) always shows the window — never hides it.
        # Users learn "click tray = open app"; hiding on click is confusing.
        self._tray_icon.activated.connect(self._tray_activated)

        if hasattr(app, '_fanhub_tray_timer'):
            app._fanhub_tray_timer.stop()
        app._fanhub_tray_timer = QTimer(app)
        app._fanhub_tray_timer.setInterval(5000)
        app._fanhub_tray_timer.timeout.connect(self._update_tray_tooltip)
        app._fanhub_tray_timer.start()
        self._tray_timer = app._fanhub_tray_timer

        try:
            self._tray_icon.show()
            if self._tray_icon.isVisible():
                logger.info("System tray icon active")
            else:
                logger.info("Tray not available on this desktop environment")
        except Exception as e:
            logger.warning(f"Tray error: {e}")

    def _rebuild_tray_menu(self):
        if self._tray_icon is None:
            return

        app = QApplication.instance()
        menu = QMenu()

        show_act = QAction("Show Fan Hub", app)
        show_act.triggered.connect(self._show_window)
        menu.addAction(show_act)

        menu.addSeparator()

        profiles = list(self.state.profiles.keys())
        if profiles:
            pm = menu.addMenu("Switch Profile")
            for p in profiles[:10]:
                act = QAction(p, app)
                act.triggered.connect(lambda checked, n=p: self._tray_load_profile(n))
                pm.addAction(act)
            menu.addSeparator()

        status_menu = menu.addMenu("Fan Status")
        fans = self.hw_monitor.fans
        if fans:
            for fan in list(fans.values())[:8]:
                rpm_str = f"{fan.current_rpm:,} RPM" if fan.current_rpm > 0 else "0 RPM ⚠"
                a = status_menu.addAction(f"{fan.label[:28]}: {rpm_str}")
                a.setEnabled(False)
        else:
            a = status_menu.addAction("No fans detected")
            a.setEnabled(False)

        menu.addSeparator()

        em_act = QAction("Activate Emergency Mode (All Fans 100%)", app)
        em_act.triggered.connect(self._toggle_emergency)
        menu.addAction(em_act)

        auto_act = QAction("All Fans — Motherboard Auto", app)
        auto_act.triggered.connect(self._all_fans_auto)
        menu.addAction(auto_act)

        menu.addSeparator()

        quit_act = QAction("Quit Fan Hub", app)
        quit_act.triggered.connect(self._quit_from_tray)
        menu.addAction(quit_act)

        self._tray_icon.setContextMenu(menu)

    def _update_tray_tooltip(self):
        if self._tray_icon is None:
            return

        unit     = self.state.settings.get('temp_unit', 'C')
        unit_sym = '°F' if unit == 'F' else '°C'
        fans     = self.hw_monitor.fans
        sensors  = self.hw_monitor.temps
        profile  = self.state.active_profile or "none"
        active_fans = sum(1 for f in fans.values() if f.current_rpm > 0)

        # Build temperature lines — show every sensor with a real reading,
        # sorted highest first so the most critical values are at the top.
        temp_lines = []
        for sid, sensor in sensors.items():
            val = sensor.value_f if unit == 'F' else sensor.value
            if val <= 0:
                continue
            # Shorten the label for the tooltip — strip source prefix if long
            lbl = sensor.label
            if ' — ' in lbl:
                lbl = lbl.split(' — ', 1)[1]
            elif ': ' in lbl:
                lbl = lbl.split(': ', 1)[1]
            temp_lines.append((val, lbl))

        temp_lines.sort(key=lambda t: t[0], reverse=True)

        # Cap at 8 sensors to keep tooltip readable
        shown   = temp_lines[:8]
        max_val = shown[0][0] if shown else 0

        # Header line: overall max + fan summary
        header  = (f"Fan Hub  —  Max: {max_val:.0f}{unit_sym}  "
                   f"|  {active_fans}/{len(fans)} fans  |  {profile}")

        # Per-sensor lines
        sensor_lines = "\n".join(
            f"  {lbl[:28]:<28}  {val:.1f}{unit_sym}"
            for val, lbl in shown
        )

        tooltip = header
        if sensor_lines:
            tooltip += f"\n{'─' * 48}\n{sensor_lines}"
        if len(temp_lines) > 8:
            tooltip += f"\n  … and {len(temp_lines) - 8} more sensors"

        self._tray_icon.setToolTip(tooltip)

    def refresh_tray_menu(self):
        self._rebuild_tray_menu()

    def _tray_activated(self, reason):
        """
        FIX: Single-click (Trigger) and double-click both show the window.
        The window is never hidden by clicking the tray icon — only by the
        window's own X button. This matches user expectations on Linux desktops.
        To hide the app, the user right-clicks → Quit (which also restores fans).
        """
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.MiddleClick,
        ):
            self._show_window()

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
        # If window was minimised, restore it
        if self.isMinimized():
            self.showNormal()

    def _tray_load_profile(self, name: str):
        self.profile_manager.load_profile(name, self.curve_engine)
        if self._tray_icon:
            self._tray_icon.showMessage(
                "Fan Hub", f"Profile: {name}",
                QSystemTrayIcon.MessageIcon.Information, 2000)
        self._save_curves_to_config()

    def enable_tray(self, enabled: bool):
        if enabled and self._tray_icon is None:
            self._setup_tray()
        elif not enabled and self._tray_icon is not None:
            if hasattr(self, '_tray_timer'):
                self._tray_timer.stop()
            self._tray_icon.hide()
            self._tray_icon = None

    # ─────────────────────────────────────────────
    #  Polling
    # ─────────────────────────────────────────────

    def _start_polling(self):
        interval = self.state.settings.get('poll_interval_ms', 1000)
        self.worker = PollingWorker(
            self.hw_monitor, self.curve_engine,
            None,   # liquid_manager — filled by _on_backends_ready
            None,   # rgb_manager    — filled by _on_backends_ready
            self.state, interval
        )
        self.worker.sensors_updated.connect(self._on_sensors_updated)
        self.worker.fans_updated.connect(self._on_fans_updated)
        self.worker.liquid_updated.connect(self._on_liquid_updated)
        self.worker.emergency_triggered.connect(self._on_emergency)
        self.worker.emergency_cleared.connect(self._on_emergency_cleared)
        self.worker.error_occurred.connect(self._on_error)
        # System stats (CPU/GPU/RAM/storage/network) → dashboard overview strip
        if hasattr(self.dashboard_tab, 'overview'):
            self.worker.stats_updated.connect(self.dashboard_tab.overview.on_stats)
        # IPC client — connects to fanhub-daemon if running. Enables instant
        # per-fan override delivery so the GUI and daemon never fight over
        # the same fan (previously the cause of spurious emergency warnings).
        self._ipc = IPCClient(self)
        self.worker.set_ipc(self._ipc)
        self.worker.start()

    def update_poll_interval(self, ms: int):
        self.worker.set_interval(ms)

    # ─────────────────────────────────────────────
    #  Signal handlers
    # ─────────────────────────────────────────────

    def _update_indicator(self, label: QLabel, ok: bool):
        label.setStyleSheet(
            f"color: {'#44ff88' if ok else '#ff4444'}; font-weight: bold;")

    @pyqtSlot(dict)
    def _on_sensors_updated(self, temps: dict):
        self._last_update_time = time.monotonic()
        self.dashboard_tab.update_temps(temps)
        self.curves_tab.update_temps(temps)
        self.fan_control_tab.update_temps(temps)
        if temps:
            mt       = max(temps.values())
            unit     = self.state.settings.get('temp_unit', 'C')
            unit_sym = '°F' if unit == 'F' else '°C'
            self.poll_label.setText(f"Max: {mt:.1f}{unit_sym}")
            # Emergency threshold is always stored in °C; temps dict is in display unit
            et = self.state.settings.get('emergency_temp', 90.0)  # always °C
            # Convert display-unit temp back to °C for threshold comparison
            mt_c = (mt - 32) * 5 / 9 if unit == 'F' else mt
            if mt_c >= et:
                self.emergency_label.setText(f"EMERGENCY: {mt:.0f}{unit_sym}")
            else:
                self.emergency_label.setText("")
                # Auto-emergency cleared — restore normal state if not manually active
                if not self._emergency_manual and self.curve_engine.emergency_active is False:
                    self._set_emergency_state(False)

    @pyqtSlot(dict)
    def _on_fans_updated(self, fans: dict):
        self.dashboard_tab.update_fans(fans)
        self.fan_control_tab.update_fans(fans)

    @pyqtSlot(list)
    def _on_liquid_updated(self, devices: list):
        self.liquid_tab.update_devices(devices)
        self.dashboard_tab.update_liquid(devices)

    @pyqtSlot()
    def _on_emergency_cleared(self):
        """Temperature dropped below emergency threshold — restore state label.""" 
        if not self._emergency_manual:
            self._set_emergency_state(False)
            self.status_label.setText("Emergency cleared — curves restored")

    def _on_emergency(self, temp: float):
        self.status_label.setText(f"EMERGENCY: {temp:.1f}°C — all fans 100%")
        self._set_emergency_state(True)
        if self._tray_icon:
            self._tray_icon.showMessage(
                "Fan Hub — EMERGENCY",
                f"Temperature {temp:.0f}°C exceeded threshold! Fans at 100%.",
                QSystemTrayIcon.MessageIcon.Critical, 6000)

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        logger.error(f"Worker error: {msg}")

    # ─────────────────────────────────────────────
    #  Actions
    # ─────────────────────────────────────────────



    def _start_bg_update_check(self):
        """Silent background update check on startup. Shows tray alert if update available."""
        worker = UpdateCheckWorker(self)
        worker.fanhub_result.connect(self._on_bg_update_result)
        worker.start()
        self._bg_update_worker = worker   # keep alive

    def _on_bg_update_result(self, info):
        """Called when the background Fan Hub update check finishes."""
        if not info.ok:
            return
        if is_newer(info.version, FANHUB_CURRENT_VERSION):
            logger.info(f"Fan Hub update available: v{info.version}")
            if self._tray_icon and self._tray_icon.isVisible():
                self._tray_icon.showMessage(
                    "Fan Hub Update Available",
                    f"Version {info.version} is available. "
                    "Open Settings \u2192 Software Updates to download.",
                    self._tray_icon.MessageIcon.Information,
                    8000,
                )

    def toggle_pwm_inverted(self, fan_id: str, inverted: bool):
        """
        Called from Fan Control tab when user flags a fan as having
        inverted PWM polarity (100% commanded = fan spins down, and vice versa).
        Persists to config so it survives restarts.
        """
        self.hw_monitor.set_pwm_inverted(fan_id, inverted)
        inv_map = self.state.settings.setdefault('pwm_inverted_fans', {})
        if inverted:
            inv_map[fan_id] = True
        else:
            inv_map.pop(fan_id, None)
        self.state.save_config()
        logger.info(f"Fan {fan_id}: PWM inverted = {inverted}")

    def _finish_startup(self):
        """
        Final startup steps — called after the first-run wizard completes or is skipped.
        The fan warning timer was already scheduled in __init__; update check runs here.
        """
        self._start_bg_update_check()

    def _show_first_run_wizard(self):
        wizard = FirstRunWizard(
            self.hw_monitor, self.curve_engine, self.state,
            parent=self,
            system_configured=self.state.settings.get('system_configure_done', False),
        )
        wizard.setup_complete.connect(self._on_wizard_complete)
        # Skip/close → still proceed to normal startup but don't mark done
        wizard.rejected.connect(self._finish_startup)
        wizard.exec()

    def _on_wizard_complete(self, preset_name: str):
        logger.info(f"First-run wizard complete — preset: {preset_name}")
        self.state.settings['first_run_done'] = True
        self.state.save_config()
        self._finish_startup()

    def _show_diagnostics(self):
        dlg = HardwareSummaryDialog(
            self.hw_monitor, self.state,
            self.rgb_manager, self.liquid_manager,
            parent=self)
        dlg.show()  # non-modal

    def _show_fan_warning(self):
        fans = self.hw_monitor.fans
        # GPU fans often have no tachometer (especially NVIDIA without hwmon).
        # They are expected to show 0 RPM — exclude them from the warning.
        zero_fans = [
            f for f in fans.values()
            if f.current_rpm == 0 and not f.gpu_vendor
        ]
        first_run = not self.state.settings.get('fan_warning_shown', False)
        if not first_run and not zero_fans:
            return
        dlg = FanWarningDialog(zero_fans, fans, parent=self)
        dlg.exec()
        if dlg.should_suppress_future():
            self.state.settings['suppress_fan_warning'] = True
        self.state.settings['fan_warning_shown'] = True
        self.state.save_config()

    def _toggle_emergency(self):
        """Button press: activate if normal, deactivate if already in manual emergency."""
        if self._emergency_manual:
            # Deactivate — restore curves
            self._emergency_manual = False
            self.curve_engine.emergency_active = False
            self._set_emergency_state(False)
            self.status_label.setText("Emergency deactivated — curves restored")
        else:
            self._activate_emergency_all()

    def _activate_emergency_all(self):
        """Set all fans to 100% immediately."""
        self._emergency_manual = True
        for fid in self.hw_monitor.fans:
            self.hw_monitor.set_fan_percent(fid, 100.0)
        if self.liquid_manager:
            for dev in self.liquid_manager.devices:
                if dev.supports_fan_control:
                    self.liquid_manager.set_fan_speed(dev, 'fan', 100)
        self._set_emergency_state(True)
        self.status_label.setText("Emergency active — all fans at 100%")

    def _set_emergency_state(self, active: bool):
        """Update the state label and button text to reflect emergency status."""
        if active:
            self.emergency_state_lbl.setText("EMERGENCY ACTIVE")
            self.emergency_state_lbl.setStyleSheet(
                "color: #ff4444; font-size: 10px; font-weight: bold; "
                "padding: 2px 6px; border: 1px solid #6a1010; border-radius: 3px; "
                "background: #2a0808;")
            self.emergency_btn.setText("Deactivate Emergency")
        else:
            self.emergency_state_lbl.setText("NORMAL")
            self.emergency_state_lbl.setStyleSheet(
                "color: #44dd88; font-size: 10px; font-weight: bold; "
                "padding: 2px 6px; border: 1px solid #1e3a20; border-radius: 3px; "
                "background: #0a1a0e;")
            self.emergency_btn.setText("Activate Emergency Mode")

    def _all_fans_auto(self):
        self.worker.set_all_auto()
        self.curve_engine.fan_assignments.clear()
        self.curve_engine.fixed_speeds.clear()
        self.status_label.setText("All fans: motherboard auto")

    def _rescan_hardware(self):
        self.status_label.setText("Rescanning…")
        self.worker.stop()
        if not self.worker.isFinished():
            logger.warning("Worker did not finish in time — skipping rescan")
            self.status_label.setText("Rescan failed: worker still running")
            return
        self.hw_monitor.rescan()
        if self.liquid_manager:
            self.liquid_manager.rescan()
        if self.rgb_manager:
            self.rgb_manager.reconnect()
            self.state.openrgb_connected = self.rgb_manager.connected
            self._update_indicator(self.openrgb_indicator, self.rgb_manager.connected)
        self.state.liquidctl_available = (
            self.liquid_manager.available if self.liquid_manager else False)
        self._update_indicator(self.liquidctl_indicator, self.state.liquidctl_available)
        self.fan_control_tab.refresh_fans()
        self.curves_tab.refresh()
        # Rebuild dashboard gauges/cards after rescan
        # _init_temp_gauges/_init_fan_cards clear existing widgets themselves
        self.dashboard_tab._init_temp_gauges()
        self.dashboard_tab._init_fan_cards()
        self.worker.start()
        self.status_label.setText(
            f"Rescan done: {len(self.hw_monitor.fans)} fans, "
            f"{len(self.hw_monitor.temps)} sensors")

    # ─────────────────────────────────────────────
    #  Curve persistence + daemon control
    # ─────────────────────────────────────────────

    def _save_curves_to_config(self):
        """
        Persist current curve engine state into config.json so the daemon picks
        up all fan assignments and custom curves on its next reload.
        Also sends SIGHUP to the daemon so it reloads without restarting.
        """
        active = self.state.active_profile or '__current__'
        profile_data = self.state.profiles.get(active, {})
        profile_data['curves'] = self.curve_engine.to_dict()
        if active == '__current__':
            profile_data['name'] = '__current__'
        self.state.profiles[active] = profile_data
        if self.state.active_profile is None:
            self.state.active_profile = '__current__'
        self.state.save_config()
        self._signal_daemon_reload()

    def _signal_daemon_reload(self):
        """Send SIGHUP to fanhub-daemon so it re-reads config mid-run."""
        DaemonController.reload()

    def _daemon_is_active(self) -> bool:
        return DaemonController.is_active()

    def _daemon_is_enabled(self) -> bool:
        return DaemonController.is_enabled()

    def set_daemon_enabled(self, enable: bool):
        """Enable/start or disable/stop fanhub-daemon via systemctl."""
        DaemonController.set_enabled(enable)

    # ─────────────────────────────────────────────
    #  Close / Quit logic
    # ─────────────────────────────────────────────

    def closeEvent(self, event):
        """
        Window X button:
          - If tray is alive → hide to tray, keep running (no dialog).
          - If already quitting (_quitting flag set by _do_quit) → accept
            silently so the in-progress quit sequence completes.
          - Otherwise → real quit via _do_quit.
        """
        # _do_quit already handled everything — just let the window close
        if getattr(self, '_quitting', False):
            event.accept()
            return

        tray_alive = (self._tray_icon is not None and self._tray_icon.isVisible())

        if tray_alive:
            event.ignore()
            self.hide()
            # Save current curve/profile state so the daemon picks it up
            self._save_curves_to_config()
            # Only show the balloon once to avoid nagging
            if not self.state.settings.get('hide_balloon_shown', False):
                self._tray_icon.showMessage(
                    "Fan Hub",
                    "Fan Hub is running in the background.\n"
                    "Click the tray icon to reopen, or right-click → Quit.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000)
                self.state.settings['hide_balloon_shown'] = True
            return

        self._do_quit(event)

    def _quit_from_tray(self):
        """Called from tray 'Quit' — no close_event to accept/ignore."""
        self._do_quit(None)

    def _do_quit(self, close_event):
        """
        Single entry point for all shutdown paths.
        _quitting flag prevents closeEvent from re-entering this method when
        QApplication.quit() sends a synthetic close event to all windows.
        """
        # Already in progress (shouldn't happen, but guard anyway)
        if getattr(self, '_quitting', False):
            if close_event:
                close_event.accept()
            return

        # Show window so the dialog has a proper parent
        was_hidden = not self.isVisible()
        if was_hidden:
            self.show()
            self.raise_()

        reply = QMessageBox.question(
            self, "Quit Fan Hub",
            "Restore all fans to automatic control before quitting?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No  |
            QMessageBox.StandardButton.Cancel
        )

        if reply == QMessageBox.StandardButton.Cancel:
            # User cancelled — put the window back how it was
            if was_hidden:
                self.hide()
            if close_event:
                close_event.ignore()
            return

        if reply == QMessageBox.StandardButton.Yes:
            self._all_fans_auto()

        # ── Set flag BEFORE calling anything that might trigger closeEvent ──
        self._quitting = True

        # Stop the RGB poll timer before tearing down the manager
        if hasattr(self, 'rgb_tab') and hasattr(self.rgb_tab, '_poll_timer'):
            self.rgb_tab._poll_timer.stop()

        self.worker.stop()

        if hasattr(self, '_backend_thread') and self._backend_thread.isRunning():
            self._backend_thread.quit()
            self._backend_thread.wait(2000)

        if self._tray_icon is not None:
            if hasattr(self, '_tray_timer'):
                self._tray_timer.stop()
            self._tray_icon.hide()
            self._tray_icon = None

        app = QApplication.instance()
        if hasattr(app, '_fanhub_tray_timer'):
            app._fanhub_tray_timer.stop()
            del app._fanhub_tray_timer

        self._save_curves_to_config()

        if close_event:
            close_event.accept()

        # quit() posts a QEvent::Quit; closeEvent will be called once more
        # but the _quitting flag makes it a no-op.
        QApplication.instance().quit()
