"""
Fan Warning Dialog — shown on startup if 0-RPM fans are detected.
Educates users about:
  - Generic fans with internal controllers (Apevia, etc.)
  - Molex fans
  - Daisy-chained fans
  - Laptop fans
  - Proper SYS_FAN wiring requirements
"""
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame,
    QCheckBox, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap, QColor

logger = logging.getLogger('fanhub.warning')


# ── Compatibility info per fan/brand type ─────────────────────────────────────

GENERIC_BRANDS_WARNING = """
<b>Generic / Budget Case Fans (Apevia, Rosewill, Insignia, no-name RGB, etc.)</b><br>
These fans often have their own internal RGB/speed controller built into the fan hub.
They do NOT connect to your motherboard's SYS_FAN header for speed control —
they use a proprietary 2-pin or USB connection and cannot be controlled by Fan Hub.
<br><br>
<b>What you can do:</b>
<ul>
<li>Verify each fan is physically plugged into a SYS_FAN or CPU_FAN header on the motherboard</li>
<li>If your case fans plug into a hub that plugs into a USB header, use the Liquid/AIO tab (liquidctl)</li>
<li>If fans only show a 2-pin Molex connector, they run at full speed and cannot be controlled</li>
</ul>
"""

CONNECTION_GUIDE = """
<b>Fan Compatibility & Wiring Guide</b><br><br>

<b style='color:#44ff88'>✓ Fully controllable (Fan Hub can control these):</b>
<ul>
<li><b>3-pin fans</b> plugged into SYS_FAN/CPU_FAN — DC voltage control</li>
<li><b>4-pin PWM fans</b> plugged into SYS_FAN/CPU_FAN — PWM control (best)</li>
<li><b>Corsair fans</b> via Commander Pro / USB hub — liquidctl tab</li>
<li><b>NZXT fans</b> via Smart Device 2 / USB hub — liquidctl tab</li>
<li><b>Thermaltake fans</b> via TT RGB Plus hub (some) — liquidctl</li>
<li><b>AIO cooler pump+fans</b> (Kraken, H100i, etc.) — liquidctl tab</li>
<li><b>Laptop fans</b> (some) — via hwmon thinkpad_acpi / asus-nb-wmi</li>
<li><b>Molex 4-pin → 3/4-pin adapter</b> plugged into SYS_FAN — controllable</li>
</ul>

<b style='color:#ff8844'>⚠ Partially controllable:</b>
<ul>
<li><b>Daisy-chained fans</b> — all fans on one header move together at the same speed</li>
<li><b>Molex-only fans</b> (2-pin power) — run at full voltage, no speed control</li>
<li><b>Fan splitters</b> (Y-adapters) — all fans on one header, single RPM reading</li>
</ul>

<b style='color:#ff4444'>✗ Not controllable by Fan Hub:</b>
<ul>
<li><b>Generic RGB fans with internal hub/controller</b> (Apevia Cosmos, many budget brands)
    — they use proprietary USB or 2-pin control, not SYS_FAN</li>
<li><b>Fans only connected to RGB/ARGB headers</b> — only LED control, not speed</li>
<li><b>Fans with no motherboard connection</b> — no control possible</li>
</ul>

<b>To check your fan connections:</b><br>
Open your case and trace each fan cable. For software control, the fan's speed wire
(3-pin or 4-pin) MUST go to a motherboard SYS_FAN/CPU_FAN header, directly or via
a supported USB hub (Corsair, NZXT, etc.).
"""

ZERO_RPM_CAUSES = """
<b>Possible reasons for 0 RPM reading:</b>
<ul>
<li>Fan is not connected to a motherboard header (connected only to power/RGB)</li>
<li>Fan is stopped (fan-stop feature active below temperature threshold)</li>
<li>Fan header is not detected by the kernel module — try loading it:
    <code>sudo modprobe nct6775</code> or <code>sudo modprobe it87</code></li>
<li>Fan is generic with internal controller (cannot be read by motherboard)</li>
<li>Fan has failed</li>
<li>Kernel module needs time to detect the fan after plugging in</li>
</ul>
"""


class FanWarningDialog(QDialog):
    """
    Startup dialog warning about 0-RPM fans and compatibility.
    Shows which fans are at 0 RPM and educates the user.
    """

    def __init__(self, zero_rpm_fans: list, all_fans: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fan Hub — Fan Check")
        self.setMinimumSize(700, 600)
        self.setModal(True)
        self._build_ui(zero_rpm_fans, all_fans)

    def _build_ui(self, zero_rpm_fans: list, all_fans: dict):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── Header ──────────────────────────────────
        header_frame = QFrame()
        header_frame.setObjectName("warningHeader")
        header_frame.setStyleSheet(
            "QFrame#warningHeader { background: #1a0a00; border: 1px solid #ff6600; "
            "border-radius: 8px; padding: 8px; }"
        )
        hl = QHBoxLayout(header_frame)

        icon_lbl = QLabel("⚠")
        icon_lbl.setStyleSheet("font-size: 40px;")
        icon_lbl.setFixedWidth(56)
        hl.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_lbl = QLabel("Fan Check Required")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #ff8844;")
        title_col.addWidget(title_lbl)

        if zero_rpm_fans:
            sub_lbl = QLabel(
                f"{len(zero_rpm_fans)} fan channel(s) reading 0 RPM. "
                "Please verify your fans are spinning and properly connected."
            )
        else:
            sub_lbl = QLabel(
                "All detected fans are reporting RPM. "
                "Please review compatibility information below."
            )
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet("color: #ccbbaa;")
        title_col.addWidget(sub_lbl)
        hl.addLayout(title_col, 1)
        layout.addWidget(header_frame)

        # ── Scroll area for content ──────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setSpacing(12)

        # 0-RPM fan list
        if zero_rpm_fans:
            zero_group = QGroupBox(f"Fans Showing 0 RPM ({len(zero_rpm_fans)})")
            zero_group.setStyleSheet(
                "QGroupBox { border: 1px solid #ff4400; color: #ff8844; "
                "margin-top: 22px; padding-top: 12px; } QGroupBox::title { top: 4px; left: 10px; }"
            )
            zl = QVBoxLayout(zero_group)

            for fan in zero_rpm_fans:
                row = QHBoxLayout()
                dot = QLabel("●")
                dot.setStyleSheet("color: #ff4444; font-size: 14px;")
                dot.setFixedWidth(20)
                row.addWidget(dot)
                info = QLabel(
                    f"<b>{fan.label}</b> — {fan.chip_name} "
                    f"(type: {fan.connection_type}, "
                    f"{'PWM' if fan.pwm_file else 'DC/No-control'})"
                )
                info.setWordWrap(True)
                row.addWidget(info, 1)
                zl.addLayout(row)

            zl.addWidget(QLabel(
                "<small style='color:#aa8866'>These may be generic fans, stopped fans, "
                "or fans not connected to a motherboard header.</small>"
            ))
            cl.addWidget(zero_group)

        # All detected fans summary
        all_group = QGroupBox(f"All Detected Fan Channels ({len(all_fans)})")
        all_group.setStyleSheet(
            "QGroupBox { border: 1px solid #224466; color: #8899bb; "
            "margin-top: 22px; padding-top: 12px; } QGroupBox::title { top: 4px; left: 10px; }"
        )
        al = QVBoxLayout(all_group)
        for fid, fan in all_fans.items():
            rpm_color = "#44ff88" if fan.current_rpm > 0 else "#ff4444"
            status = "●" if fan.current_rpm > 0 else "○"
            row_lbl = QLabel(
                f"<span style='color:{rpm_color}'>{status}</span> "
                f"<b>{fan.label}</b> — "
                f"<span style='color:{rpm_color}'>{fan.current_rpm} RPM</span> | "
                f"{fan.chip_name} | "
                f"{'PWM' if fan.pwm_file else 'DC'} | "
                f"{fan.connection_type}"
            )
            row_lbl.setTextFormat(Qt.TextFormat.RichText)
            al.addWidget(row_lbl)
        cl.addWidget(all_group)

        # Compatibility guide
        compat_group = QGroupBox("Fan Compatibility & Wiring Guide")
        compat_group.setStyleSheet(
            "QGroupBox { border: 1px solid #223344; color: #8899bb; "
            "margin-top: 22px; padding-top: 12px; } QGroupBox::title { top: 4px; left: 10px; }"
        )
        ql = QVBoxLayout(compat_group)
        guide_lbl = QLabel(CONNECTION_GUIDE)
        guide_lbl.setWordWrap(True)
        guide_lbl.setTextFormat(Qt.TextFormat.RichText)
        guide_lbl.setStyleSheet("font-size: 11px; color: #aabbcc; padding: 4px;")
        ql.addWidget(guide_lbl)
        cl.addWidget(compat_group)

        # 0-RPM causes
        causes_group = QGroupBox("Why Might a Fan Show 0 RPM?")
        causes_group.setStyleSheet(
            "QGroupBox { border: 1px solid #223344; color: #8899bb; "
            "margin-top: 22px; padding-top: 12px; } QGroupBox::title { top: 4px; left: 10px; }"
        )
        ql2 = QVBoxLayout(causes_group)
        causes_lbl = QLabel(ZERO_RPM_CAUSES)
        causes_lbl.setWordWrap(True)
        causes_lbl.setTextFormat(Qt.TextFormat.RichText)
        causes_lbl.setStyleSheet("font-size: 11px; color: #aabbcc; padding: 4px;")
        ql2.addWidget(causes_lbl)
        cl.addWidget(causes_group)

        # Generic brands warning
        generic_group = QGroupBox("Generic / Budget Brand Warning")
        generic_group.setStyleSheet(
            "QGroupBox { border: 1px solid #442200; color: #cc8844; "
            "margin-top: 22px; padding-top: 12px; } QGroupBox::title { top: 4px; left: 10px; }"
        )
        gl = QVBoxLayout(generic_group)
        gen_lbl = QLabel(GENERIC_BRANDS_WARNING)
        gen_lbl.setWordWrap(True)
        gen_lbl.setTextFormat(Qt.TextFormat.RichText)
        gen_lbl.setStyleSheet("font-size: 11px; color: #bbaa88; padding: 4px;")
        gl.addWidget(gen_lbl)
        cl.addWidget(generic_group)

        cl.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # ── Bottom bar ────────────────────────────────
        self.dont_show = QCheckBox("Don't show this again on startup")
        self.dont_show.setStyleSheet("color: #667788;")
        layout.addWidget(self.dont_show)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        if zero_rpm_fans:
            self.fans_ok_btn = QPushButton("My Fans Are Spinning — Continue Anyway")
            self.fans_ok_btn.setObjectName("applyBtn")
            self.fans_ok_btn.setToolTip(
                "Acknowledge that fans may be generic/uncontrollable and continue")
            self.fans_ok_btn.clicked.connect(self.accept)
            btn_row.addWidget(self.fans_ok_btn)

        close_btn = QPushButton("I Understand — Open Fan Hub")
        close_btn.setObjectName("applyBtn")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def should_suppress_future(self) -> bool:
        return self.dont_show.isChecked()
