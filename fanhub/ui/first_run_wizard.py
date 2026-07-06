"""
First-Run Guided Setup — shown once when no config exists.

Walks the user through four steps so they reach a working configuration
without reading any documentation:
  1. Hardware scan — detect controllable fans
  2. Confirm controllability — show what Fan Hub can/cannot control
  3. Apply a safe default curve — one click to be protected
  4. Done — remind about tray, daemon, and profiles

Does NOT replace the main window. After completion the main window opens
normally with curves already applied.
"""
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QWidget, QFrame, QListWidget, QListWidgetItem,
    QGroupBox, QButtonGroup, QRadioButton, QSizePolicy, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

logger = logging.getLogger('fanhub.firstrun')


class FirstRunWizard(QDialog):
    """
    Four-page wizard. Emits setup_complete(preset_name) when the user
    finishes. Caller applies the chosen preset to the CurveEngine.
    """
    setup_complete = pyqtSignal(str)   # preset name chosen

    def __init__(self, hw_monitor, curve_engine, state, parent=None):
        super().__init__(parent)
        self.hw     = hw_monitor
        self.engine = curve_engine
        self.state  = state
        self._chosen_preset = 'balanced'

        self.setWindowTitle("Fan Hub — First Run Setup")
        self.setMinimumWidth(600)
        self.setMinimumHeight(480)
        self.setModal(True)

        self._build_ui()
        self._go_to(0)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Title bar
        bar = QFrame()
        bar.setFixedHeight(60)
        bar.setStyleSheet("background:#0d1428; border-bottom:1px solid #1a3060;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(20, 0, 20, 0)
        self._step_label = QLabel("Step 1 of 4")
        self._step_label.setStyleSheet("color:#667788; font-size:11px;")
        self._title_label = QLabel("Welcome to Fan Hub")
        self._title_label.setStyleSheet(
            "color:#00ddff; font-size:15px; font-weight:bold;")
        bl.addWidget(self._title_label)
        bl.addStretch()
        bl.addWidget(self._step_label)
        layout.addWidget(bar)

        # Progress bar
        self._prog = QProgressBar()
        self._prog.setRange(0, 4)
        self._prog.setValue(0)
        self._prog.setTextVisible(False)
        self._prog.setFixedHeight(3)
        layout.addWidget(self._prog)

        # Stacked pages
        self._stack = QStackedWidget()
        self._stack.setContentsMargins(24, 18, 24, 12)
        self._stack.addWidget(self._page_welcome())
        self._stack.addWidget(self._page_fans())
        self._stack.addWidget(self._page_preset())
        self._stack.addWidget(self._page_done())
        layout.addWidget(self._stack, 1)

        # Nav row
        nav = QFrame()
        nav.setFixedHeight(60)
        nav.setStyleSheet("background:#0a0e1a; border-top:1px solid #1a2840;")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(20, 0, 20, 0)

        self._skip_btn = QPushButton("Skip Setup")
        self._skip_btn.setStyleSheet("color:#445566; border:none; background:transparent;")
        self._skip_btn.clicked.connect(self._skip)
        nl.addWidget(self._skip_btn)
        nl.addStretch()

        self._back_btn = QPushButton("← Back")
        self._back_btn.clicked.connect(self._go_back)
        nl.addWidget(self._back_btn)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("applyBtn")
        self._next_btn.setFixedWidth(120)
        self._next_btn.clicked.connect(self._go_next)
        nl.addWidget(self._next_btn)
        layout.addWidget(nav)

    # ── Pages ─────────────────────────────────────────────────────────────────

    def _page_welcome(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(16)
        l.addSpacing(8)

        logo = QLabel("🌀")
        logo.setStyleSheet("font-size:48px;")
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        l.addWidget(logo)

        h1 = QLabel("Welcome to Fan Hub")
        h1.setStyleSheet("color:#e0eeff; font-size:20px; font-weight:bold;")
        h1.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        l.addWidget(h1)

        body = QLabel(
            "This setup wizard will take you through three quick steps to get Fan Hub working:\n\n"
            "1.  Scan your hardware and show which fans can be controlled\n"
            "2.  Confirm what Fan Hub found on your system\n"
            "3.  Apply a safe default fan curve so your fans are managed immediately\n\n"
            "The whole process takes about 30 seconds. "
            "You can skip it and configure everything manually if you prefer."
        )
        body.setWordWrap(True)
        body.setStyleSheet("color:#889aaa; font-size:13px; line-height:1.6;")
        body.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        l.addWidget(body)
        l.addStretch()
        return w

    def _page_fans(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(10)

        h1 = QLabel("Hardware Scan Results")
        h1.setStyleSheet("color:#e0eeff; font-size:15px; font-weight:bold;")
        l.addWidget(h1)

        desc = QLabel(
            "Fan Hub found the following fans on your system. "
            "Fans marked ✓ can be controlled with custom curves. "
            "Fans marked ○ are read-only — you can see their speed but not control them."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#667788; font-size:12px;")
        l.addWidget(desc)

        self._fan_list = QListWidget()
        self._fan_list.setStyleSheet(
            "QListWidget { background:#080e1c; border:1px solid #1a2840; "
            "border-radius:4px; color:#aabbcc; font-size:12px; }"
            "QListWidget::item { padding:6px 10px; }"
            "QListWidget::item:selected { background:#1a3050; }"
        )
        self._fan_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._populate_fan_list()
        l.addWidget(self._fan_list, 1)

        self._fan_summary = QLabel("")
        self._fan_summary.setStyleSheet("color:#44ff88; font-size:12px;")
        l.addWidget(self._fan_summary)
        self._update_fan_summary()
        return w

    def _populate_fan_list(self):
        self._fan_list.clear()
        for fid, fan in self.hw.fans.items():
            ctrl = fan.controllable and bool(fan.pwm_file)
            icon = "✓" if ctrl else "○"
            color = "#44ff88" if ctrl else "#445566"
            rpm = f"  {fan.current_rpm:,} RPM" if fan.current_rpm else ""
            item = QListWidgetItem(f"{icon}  {fan.label}{rpm}")
            item.setForeground(__import__('PyQt6.QtGui', fromlist=['QColor']).QColor(color))
            self._fan_list.addItem(item)

    def _update_fan_summary(self):
        ctrl = sum(1 for f in self.hw.fans.values()
                   if f.controllable and f.pwm_file)
        total = len(self.hw.fans)
        self._fan_summary.setText(
            f"{ctrl} of {total} fans are fully controllable"
        )

    def _page_preset(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(12)

        h1 = QLabel("Choose a Starting Fan Curve")
        h1.setStyleSheet("color:#e0eeff; font-size:15px; font-weight:bold;")
        l.addWidget(h1)

        desc = QLabel(
            "Select a preset fan curve to apply to all controllable fans right now. "
            "You can change individual fans and draw custom curves at any time from the "
            "Fan Curves tab."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#667788; font-size:12px;")
        l.addWidget(desc)

        presets = [
            ("balanced",    "Balanced (recommended)",
             "Quiet at idle, ramps up smoothly as load increases. Good for everyday use."),
            ("silent",      "Silent",
             "Fans off below 35°C, very quiet below 55°C. Prioritises silence."),
            ("performance", "Performance",
             "Fans start sooner and ramp harder. Cooler temps, more noise."),
            ("gaming",      "Gaming",
             "High baseline speed, aggressive ramp at 70°C+. Best for sustained load."),
        ]

        self._preset_group = QButtonGroup(w)
        for value, label, hint in presets:
            rb = QRadioButton()
            rb.setProperty('preset_value', value)
            self._preset_group.addButton(rb)

            row = QFrame()
            row.setStyleSheet(
                "QFrame { background:#080e1c; border:1px solid #1a2840; "
                "border-radius:5px; }"
                "QFrame:hover { border-color:#1a4070; }"
            )
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(12, 10, 12, 10)
            row_l.addWidget(rb)
            col = QVBoxLayout()
            name_lbl = QLabel(label)
            name_lbl.setStyleSheet("color:#d4e5f7; font-size:13px; font-weight:bold;")
            hint_lbl = QLabel(hint)
            hint_lbl.setStyleSheet("color:#556677; font-size:11px;")
            col.addWidget(name_lbl)
            col.addWidget(hint_lbl)
            row_l.addLayout(col, 1)

            # Make the whole row click the radio button
            row.mousePressEvent = lambda e, b=rb: b.setChecked(True)
            l.addWidget(row)

            if value == 'balanced':
                rb.setChecked(True)

        self._preset_group.buttonClicked.connect(self._on_preset_selected)
        l.addStretch()
        return w

    def _on_preset_selected(self, btn):
        self._chosen_preset = btn.property('preset_value')

    def _page_done(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(16)
        l.addSpacing(16)

        check = QLabel("✓")
        check.setStyleSheet("color:#44ff88; font-size:48px;")
        check.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        l.addWidget(check)

        h1 = QLabel("Fan Hub is Ready")
        h1.setStyleSheet("color:#e0eeff; font-size:20px; font-weight:bold;")
        h1.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        l.addWidget(h1)

        self._done_label = QLabel("")
        self._done_label.setWordWrap(True)
        self._done_label.setStyleSheet("color:#889aaa; font-size:12px;")
        self._done_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        l.addWidget(self._done_label)

        tips = QLabel(
            "<b>Tips to explore next:</b><br>"
            "• <b>Fan Curves tab</b> — draw custom temperature-to-speed curves per fan<br>"
            "• <b>Profiles tab</b> — save your setup as named profiles (Gaming, Silent, etc.)<br>"
            "• <b>Settings → Background Daemon</b> — keep curves running after the app closes<br>"
            "• <b>Diagnostics button</b> — run a full system check at any time"
        )
        tips.setWordWrap(True)
        tips.setTextFormat(Qt.TextFormat.RichText)
        tips.setStyleSheet(
            "color:#667788; font-size:12px; background:#080e1c; "
            "border:1px solid #1a2840; border-radius:4px; padding:12px 14px;"
        )
        l.addWidget(tips)
        l.addStretch()
        return w

    # ── Navigation ────────────────────────────────────────────────────────────

    def _go_to(self, index: int):
        self._stack.setCurrentIndex(index)
        self._prog.setValue(index + 1)
        titles = [
            "Welcome", "Hardware Scan", "Choose Fan Curve", "Setup Complete"
        ]
        self._title_label.setText(titles[index])
        self._step_label.setText(f"Step {index+1} of 4")
        self._back_btn.setEnabled(index > 0)
        self._skip_btn.setVisible(index < 3)
        if index == 3:
            self._next_btn.setText("Open Fan Hub →")
        else:
            self._next_btn.setText("Next →")

    def _go_next(self):
        idx = self._stack.currentIndex()
        if idx == 2:
            # Apply preset before showing done page
            self._apply_preset()
            ctrl = sum(1 for f in self.hw.fans.values()
                       if f.controllable and f.pwm_file)
            self._done_label.setText(
                f"Applied the <b>{self._chosen_preset}</b> curve to "
                f"{ctrl} controllable fan(s).\n\n"
                "Your fans will now adjust automatically based on temperature. "
                "You can fine-tune everything from the main window."
            )
        if idx == 3:
            self._finish()
            return
        self._go_to(idx + 1)

    def _go_back(self):
        self._go_to(max(0, self._stack.currentIndex() - 1))

    def _apply_preset(self):
        for fid, fan in self.hw.fans.items():
            if fan.controllable:
                self.engine.assign_curve(fid, self._chosen_preset)
        self.state.settings['first_run_done'] = True
        self.state.save_config()

    def _finish(self):
        self.setup_complete.emit(self._chosen_preset)
        self.accept()

    def _skip(self):
        self.state.settings['first_run_done'] = True
        self.state.save_config()
        self.reject()
