"""
Hardware Detection Summary Dialog — shown on startup or via Help > System Diagnostics.

Gives the user immediate confidence that Fan Hub detected their hardware correctly:
  - Motherboard chip name and fan controller type
  - All detected fans with controllability status
  - Temperature sensors
  - GPU fan control method
  - OpenRGB / liquidctl availability
  - Permission status
  - Any warnings or missing kernel modules

"Test My System" automates discovery + permission checks in one place.
"""
import os
import glob
import subprocess
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame,
    QGroupBox, QProgressBar, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QFont

logger = logging.getLogger('fanhub.hwsummary')

HWMON_BASE = '/sys/class/hwmon'


def _icon(ok: bool) -> str:
    return "●" if ok else "○"


def _chip_friendly(chip: str) -> str:
    """Map hwmon chip name to a friendly description."""
    table = {
        'nct6775': 'Nuvoton NCT6775 (SuperIO)',
        'nct6776': 'Nuvoton NCT6776 (SuperIO)',
        'nct6779': 'Nuvoton NCT6779 (SuperIO)',
        'nct6791': 'Nuvoton NCT6791 (SuperIO)',
        'nct6796': 'Nuvoton NCT6796 (SuperIO)',
        'nct6798': 'Nuvoton NCT6798 (SuperIO)',
        'nct6687': 'Nuvoton NCT6687 (SuperIO)',
        'it87':    'ITE IT87xx (SuperIO)',
        'it8620':  'ITE IT8620 (SuperIO)',
        'it8628':  'ITE IT8628 (SuperIO)',
        'it8686':  'ITE IT8686 (SuperIO)',
        'it8790':  'ITE IT8790 (SuperIO)',
        'f71858fg':'Fintek F71858FG (SuperIO)',
        'w83795':  'Winbond W83795 (SuperIO)',
        'k10temp': 'AMD CPU Temperature (k10temp)',
        'coretemp':'Intel CPU Temperature (coretemp)',
        'amdgpu':  'AMD GPU (amdgpu driver)',
        'radeon':  'AMD GPU (radeon driver)',
        'nvidia':  'NVIDIA GPU (nvidia driver)',
        'i915':    'Intel GPU (i915 driver)',
        'xe':      'Intel Arc GPU (xe driver)',
        'nvme':    'NVMe SSD',
        'acpitz':  'ACPI Thermal Zone',
        'iwlwifi': 'Intel Wi-Fi',
    }
    return table.get(chip.lower(), chip.title())


class DiagnosticWorker(QThread):
    """Run diagnostics off the UI thread so the dialog stays responsive."""
    result_ready = pyqtSignal(dict)

    def __init__(self, hw_monitor, state, rgb_manager, liquid_manager):
        super().__init__()
        self.hw     = hw_monitor
        self.state  = state
        self.rgb    = rgb_manager
        self.liquid = liquid_manager

    def run(self):
        result = {}
        try:
            result = self._collect()
        except Exception as e:
            logger.error(f"Diagnostic worker: {e}")
            result['error'] = str(e)
        self.result_ready.emit(result)

    def _collect(self) -> dict:
        r = {}

        # ── Chip discovery ────────────────────────────────────────────────────
        chips = {}
        if os.path.exists(HWMON_BASE):
            for d in sorted(glob.glob(os.path.join(HWMON_BASE, 'hwmon*'))):
                try:
                    chip = open(os.path.join(d, 'name')).read().strip()
                    fans = glob.glob(os.path.join(d, 'fan*_input'))
                    pwms = glob.glob(os.path.join(d, 'pwm*'))
                    temps = glob.glob(os.path.join(d, 'temp*_input'))
                    chips[chip] = {
                        'path': d, 'fans': len(fans),
                        'pwms': len([p for p in pwms if not p.endswith('_enable')
                                     and not p.endswith('_mode')]),
                        'temps': len(temps),
                        'friendly': _chip_friendly(chip),
                    }
                except Exception:
                    pass
        r['chips'] = chips

        # ── Fan summary ───────────────────────────────────────────────────────
        fan_rows = []
        for fid, fan in self.hw.fans.items():
            # Check PWM writability
            pwm_ok = False
            if fan.pwm_file:
                pwm_ok = os.access(fan.pwm_file, os.W_OK)
            elif fan.gpu_vendor == 'nvidia':
                pwm_ok = fan.nvidia_use_hwmon or fan.nvidia_use_settings
            elif fan.gpu_vendor in ('amd', 'intel'):
                pwm_ok = bool(fan.pwm_file and os.access(fan.pwm_file, os.W_OK))

            fan_rows.append({
                'label':       fan.label,
                'rpm':         fan.current_rpm,
                'percent':     fan.current_percent,
                'controllable': fan.controllable and pwm_ok,
                'gpu_vendor':  fan.gpu_vendor,
                'chip':        fan.chip_name,
                'pwm_file':    fan.pwm_file,
                'pwm_writable': pwm_ok,
            })
        r['fans'] = fan_rows

        # ── Temperature sensors ───────────────────────────────────────────────
        r['temps'] = [
            {'label': s.label, 'value': s.value, 'source': s.source}
            for s in self.hw.temps.values()
            if s.value > 0
        ]

        # ── Kernel modules ────────────────────────────────────────────────────
        modules_needed = ['nct6775', 'coretemp', 'it87', 'i2c-dev']
        loaded = set()
        try:
            out = subprocess.run(['lsmod'], capture_output=True, text=True, timeout=3)
            if out.returncode == 0:
                for line in out.stdout.splitlines():
                    loaded.add(line.split()[0] if line.split() else '')
        except Exception:
            pass
        r['modules'] = {m: (m in loaded or m.replace('-', '_') in loaded)
                        for m in modules_needed}

        # ── Permissions ───────────────────────────────────────────────────────
        r['running_as_root'] = (os.geteuid() == 0)
        # Check if fanhub group exists and user is in it
        try:
            import grp, pwd
            fanhub_group = grp.getgrnam('fanhub')
            cur_user = pwd.getpwuid(os.getuid()).pw_name
            r['in_fanhub_group'] = cur_user in fanhub_group.gr_mem
            r['fanhub_group_exists'] = True
        except KeyError:
            r['fanhub_group_exists'] = False
            r['in_fanhub_group'] = False

        # ── External tools ────────────────────────────────────────────────────
        r['openrgb_connected']  = bool(self.rgb and getattr(self.rgb, 'connected', False))
        r['liquidctl_available'] = bool(self.liquid and getattr(self.liquid, 'available', False))
        r['liquidctl_devices']   = len(self.liquid.devices) if self.liquid else 0

        try:
            subprocess.run(['nvidia-smi', '--version'],
                           capture_output=True, timeout=2)
            r['nvidia_smi'] = True
        except Exception:
            r['nvidia_smi'] = False

        r['nvidia_fans'] = [f for f in self.hw.fans.values() if f.gpu_vendor == 'nvidia']
        r['amd_fans']    = [f for f in self.hw.fans.values() if f.gpu_vendor == 'amd']

        return r




class _FixWorker(QThread):
    """Run a privileged fix command off the UI thread."""
    finished = pyqtSignal(bool, str)  # (success, output)

    def __init__(self, cmd: list):
        super().__init__()
        self._cmd = cmd

    def run(self):
        try:
            r = subprocess.run(self._cmd, capture_output=True,
                               text=True, timeout=30)
            self.finished.emit(r.returncode == 0, r.stderr or r.stdout)
        except Exception as e:
            self.finished.emit(False, str(e))


class HardwareSummaryDialog(QDialog):
    """
    Hardware Detection Summary — one-click system diagnostics.
    Opens automatically on first run; also accessible from the main toolbar.
    """

    def __init__(self, hw_monitor, state, rgb_manager=None,
                 liquid_manager=None, parent=None):
        super().__init__(parent)
        self.hw     = hw_monitor
        self.state  = state
        self.rgb    = rgb_manager
        self.liquid = liquid_manager
        self._worker = None

        self.setWindowTitle("Fan Hub — System Diagnostics")
        self.setMinimumSize(720, 600)
        self.setModal(False)   # non-modal so user can interact with main window

        self._build_ui()
        self._run_diagnostics()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame { background:#0d1428; border:1px solid #1a3060; border-radius:6px; }")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 10, 14, 10)
        icon = QLabel("🖥")
        icon.setStyleSheet("font-size:32px;")
        icon.setFixedWidth(46)
        hl.addWidget(icon)
        title_col = QVBoxLayout()
        title = QLabel("System Diagnostics")
        title.setStyleSheet("color:#00ddff; font-size:16px; font-weight:bold;")
        title_col.addWidget(title)
        self._sub = QLabel("Running hardware scan…")
        self._sub.setStyleSheet("color:#667788; font-size:12px;")
        title_col.addWidget(self._sub)
        hl.addLayout(title_col, 1)

        # Rescan button
        self._rescan_btn = QPushButton("🔍 Rescan")
        self._rescan_btn.clicked.connect(self._run_diagnostics)
        hl.addWidget(self._rescan_btn)
        layout.addWidget(hdr)

        # Progress bar (shown while scanning)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        # Scroll area for results
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setSpacing(10)
        self._content_layout.addStretch()
        scroll.setWidget(self._content)
        layout.addWidget(scroll, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setObjectName("applyBtn")
        close_btn.setFixedWidth(100)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def _run_diagnostics(self):
        self._progress.setVisible(True)
        self._sub.setText("Scanning hardware…")
        self._rescan_btn.setEnabled(False)
        self._clear_content()

        if self._worker and self._worker.isRunning():
            self._worker.wait(1000)

        self._worker = DiagnosticWorker(self.hw, self.state, self.rgb, self.liquid)
        self._worker.result_ready.connect(self._on_result)
        self._worker.start()

    def _clear_content(self):
        while self._content_layout.count() > 1:   # keep the trailing stretch
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_result(self, result: dict):
        self._progress.setVisible(False)
        self._rescan_btn.setEnabled(True)

        if 'error' in result:
            self._sub.setText(f"⚠ Scan error: {result['error']}")
            return

        fans   = result.get('fans', [])
        ctrl   = [f for f in fans if f['controllable']]
        issues = self._collect_issues(result)

        if issues:
            self._sub.setText(
                f"Found {len(fans)} fans, {len(ctrl)} controllable  |  "
                f"⚠ {len(issues)} issue(s) detected")
        else:
            self._sub.setText(
                f"✓ {len(fans)} fans detected, {len(ctrl)} controllable  |  "
                "All systems nominal")

        self._render_result(result)

    def _collect_issues(self, r: dict) -> list:
        issues = []
        if not r.get('running_as_root') and not r.get('in_fanhub_group'):
            issues.append("Not running as root and not in fanhub group — fan writes may fail")
        for fan in r.get('fans', []):
            if fan['pwm_file'] and not fan['pwm_writable']:
                issues.append(f"{fan['label']}: PWM file not writable")
        if not any(r.get('modules', {}).values()):
            issues.append("No hwmon kernel modules detected")
        return issues

    def _render_result(self, r: dict):
        cl = self._content_layout
        insert_at = max(0, cl.count() - 1)  # before the stretch

        def _add(w):
            cl.insertWidget(insert_at, w)

        # ── Permissions ───────────────────────────────────────────────────────
        perm = self._make_section("Permissions")
        root_ok = r.get('running_as_root', False)
        group_ok = r.get('in_fanhub_group', False)
        if root_ok:
            self._add_row(perm, "✓ Running as root", "#44ff88",
                          "Full hardware access — all fans controllable")
        elif group_ok:
            self._add_row(perm, "✓ In fanhub group", "#44ff88",
                          "PWM files accessible via group permissions")
        else:
            self._add_action_row(
                perm, "⚠ Limited permissions", "#ff8844",
                "Fan writes may fail — udev rules or root needed",
                "Apply udev Rules",
                self._fix_permissions
            )
        _add(perm)

        # ── Motherboard chips ─────────────────────────────────────────────────
        chips = r.get('chips', {})
        if chips:
            sec = self._make_section("Detected Hardware Controllers")
            for chip, info in chips.items():
                fans_s  = f"{info['fans']} fan input(s)"
                temps_s = f"{info['temps']} temp sensor(s)"
                pwms_s  = f"{info['pwms']} PWM output(s)"
                self._add_row(sec, info['friendly'], "#aabbdd",
                              f"{fans_s}  •  {pwms_s}  •  {temps_s}")
            _add(sec)

        # ── Fans ──────────────────────────────────────────────────────────────
        fans = r.get('fans', [])
        if fans:
            sec = self._make_section(f"Fan Channels ({len(fans)} detected)")
            for fan in fans:
                is_nvidia = (fan.get('gpu_vendor') == 'nvidia')
                if is_nvidia and fan['rpm'] == 0:
                    # NVIDIA 0 RPM is expected — show info, not warning
                    icon, color = "ℹ", "#4499bb"
                    pct = fan.get('percent', 0)
                    note = (f"{pct:.0f}% — RPM not available (normal for NVIDIA on Linux)"
                            if pct > 0 else
                            "RPM not available — normal for NVIDIA. Check % in Fan Control tab.")
                elif fan['controllable'] and fan['pwm_writable']:
                    icon, color = "✓", "#44ff88"
                    note = f"{fan['rpm']:,} RPM" if fan['rpm'] > 0 else "0 RPM (may be stopped)"
                elif fan['pwm_file'] and not fan['pwm_writable']:
                    icon, color = "⚠", "#ff8844"
                    note = "PWM not writable — check permissions"
                elif not fan['pwm_file']:
                    icon, color = "○", "#667788"
                    note = "Read-only (no PWM control file)"
                else:
                    icon, color = "○", "#667788"
                    note = f"{fan['rpm']:,} RPM" if fan['rpm'] > 0 else "Stopped"
                vendor = f"  [{fan['gpu_vendor'].upper()} GPU]" if fan['gpu_vendor'] else ""
                self._add_row(sec, f"{icon} {fan['label']}{vendor}", color, note)
            _add(sec)

        # ── Temperature sensors ───────────────────────────────────────────────
        temps = r.get('temps', [])
        if temps:
            sec = self._make_section(f"Temperature Sensors ({len(temps)} active)")
            # No cap — the dialog already scrolls, so a "… and N more" dead
            # end just hides real data behind an unclickable label.
            for t in sorted(temps, key=lambda x: x['value'], reverse=True):
                val = f"{t['value']:.1f}°C"
                self._add_row(sec, f"● {t['label']}", "#aabbdd", val)
            _add(sec)

        # ── Kernel modules ────────────────────────────────────────────────────
        mods = r.get('modules', {})
        if mods:
            sec = self._make_section("Kernel Modules")
            for mod, loaded in mods.items():
                icon  = "✓" if loaded else "○"
                color = "#44ff88" if loaded else "#667788"
                if loaded:
                    self._add_row(sec, f"{icon} {mod}", color, "Loaded")
                else:
                    self._add_action_row(
                        sec, f"{icon} {mod}", color,
                        "Not loaded",
                        "Load Module",
                        lambda m=mod: self._run_fix(
                            f"Loading {m}…",
                            ['pkexec', 'modprobe', m],
                        )
                    )
            _add(sec)

        # ── External integrations ─────────────────────────────────────────────
        sec = self._make_section("External Integrations")
        rgb_ok = r.get('openrgb_connected', False)
        self._add_row(sec,
                      f"{'✓' if rgb_ok else '○'} OpenRGB",
                      "#44ff88" if rgb_ok else "#667788",
                      "Connected" if rgb_ok else "Not connected — start the OpenRGB SDK server")
        lc_ok  = r.get('liquidctl_available', False)
        lc_devs = r.get('liquidctl_devices', 0)
        self._add_row(sec,
                      f"{'✓' if lc_ok else '○'} liquidctl",
                      "#44ff88" if lc_ok else "#667788",
                      f"{lc_devs} device(s) found" if lc_ok else "Not installed (pip install liquidctl)")
        nv_ok  = r.get('nvidia_smi', False)
        self._add_row(sec,
                      f"{'✓' if nv_ok else '○'} nvidia-smi",
                      "#44ff88" if nv_ok else "#667788",
                      "Available" if nv_ok else "Not found (install NVIDIA driver)")
        _add(sec)


    def _add_action_row(self, section, label: str, color: str,
                        note: str, btn_text: str, callback):
        """A row with a label, note, and an action button."""
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{color}; font-size:12px;")
        row.addWidget(lbl, 1)
        if note:
            nlbl = QLabel(note)
            nlbl.setStyleSheet("color:#556677; font-size:11px;")
            row.addWidget(nlbl)
        btn = QPushButton(btn_text)
        btn.setFixedWidth(130)
        btn.setStyleSheet(
            "QPushButton { color:#00ddff; background:#0d1f33; border:1px solid #1a3a5c; "
            "border-radius:3px; padding:2px 6px; font-size:11px; }"
            "QPushButton:hover { background:#1a3050; }"
        )
        btn.clicked.connect(callback)
        row.addWidget(btn)
        section._inner.addLayout(row)

    def _run_fix(self, status_msg: str, cmd: list):
        """Run a fix command (pkexec/sudo) and rescan on completion."""
        self._sub.setText(status_msg)
        self._progress.setVisible(True)
        worker = _FixWorker(cmd)
        worker.finished.connect(lambda ok, out: self._on_fix_done(ok, out))
        self._fix_worker = worker  # keep reference
        worker.start()

    def _on_fix_done(self, ok: bool, output: str):
        self._progress.setVisible(False)
        if ok:
            self._sub.setText("✓ Done — rescanning…")
            self._run_diagnostics()
        else:
            self._sub.setText(f"⚠ Command failed: {output[:80]}")

    def _fix_permissions(self):
        """Apply the targeted udev rule using pkexec."""
        rule = (
            "KERNEL==\"pwm[0-9]*\", SUBSYSTEM==\"hwmon\", "
            "ACTION==\"add\", GROUP=\"fanhub\", MODE=\"0660\""
        )
        script = (
            f"groupadd -f fanhub && "
            f"usermod -aG fanhub $(logname || echo $SUDO_USER) && "
            f"echo '{rule}' > /etc/udev/rules.d/99-fanhub.rules && "
            f"udevadm control --reload-rules && udevadm trigger"
        )
        self._run_fix("Applying udev rules…", ['pkexec', 'bash', '-c', script])

    def _make_section(self, title: str) -> QGroupBox:
        gb = QGroupBox(title)
        gb.setObjectName("settingsGroup")
        gb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        gb._inner = QVBoxLayout(gb)
        gb._inner.setContentsMargins(14, 6, 14, 10)
        gb._inner.setSpacing(4)
        return gb

    def _add_row(self, section: QGroupBox, label: str, color: str, note: str):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{color}; font-size:12px;")
        row.addWidget(lbl, 1)
        if note:
            nlbl = QLabel(note)
            nlbl.setStyleSheet("color:#556677; font-size:11px;")
            nlbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(nlbl)
        section._inner.addLayout(row)
