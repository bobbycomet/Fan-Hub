"""
AppImage System Configuration Dialog.

Shown on first launch from an AppImage (or when the user clicks
"Configure Fan Hub for this system" in Settings).

Detects the distro, package manager, and init system, shows them to
the user for confirmation, then runs install.sh via pkexec to set up
udev rules, groups, kernel modules, and the daemon service — all
without a terminal.

If detection is wrong the user is directed to open a Discord/GitHub issue.
"""
import os
import subprocess
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QProgressBar, QSizePolicy, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl

logger = logging.getLogger('fanhub.appconfigure')

DISCORD_URL = 'https://discord.gg/CqEWWp4N2a'
GITHUB_ISSUES = 'https://github.com/bobbycomet/Fan-Hub/issues/new'


# ── Detection helpers ─────────────────────────────────────────────────────────

def _detect_distro() -> tuple[str, str, str]:
    """Return (distro_id, distro_pretty, package_manager)."""
    distro_id     = 'unknown'
    distro_pretty = 'Unknown Linux'
    try:
        with open('/etc/os-release') as f:
            lines = dict(
                line.strip().split('=', 1)
                for line in f if '=' in line
            )
        distro_id     = lines.get('ID', 'unknown').strip('"').lower()
        distro_pretty = lines.get('PRETTY_NAME', distro_id).strip('"')
    except Exception:
        pass

    pm_map = {
        'ubuntu': 'apt', 'debian': 'apt', 'linuxmint': 'apt',
        'pop': 'apt', 'elementary': 'apt', 'kali': 'apt',
        'raspbian': 'apt', 'zorin': 'apt', 'armbian': 'apt',
        'arch': 'pacman', 'manjaro': 'pacman', 'endeavouros': 'pacman',
        'garuda': 'pacman', 'artix': 'pacman', 'cachyos': 'pacman',
        'fedora': 'dnf', 'rhel': 'dnf', 'centos': 'dnf',
        'rocky': 'dnf', 'almalinux': 'dnf', 'nobara': 'dnf',
        'opensuse-tumbleweed': 'zypper', 'opensuse-leap': 'zypper',
        'void': 'xbps', 'alpine': 'apk',
        'gentoo': 'emerge', 'nixos': 'nix',
    }
    # Check ID first, then ID_LIKE
    pkg_mgr = pm_map.get(distro_id, '')
    if not pkg_mgr:
        try:
            with open('/etc/os-release') as f:
                content = f.read().lower()
            for keyword, pm in [
                ('debian', 'apt'), ('ubuntu', 'apt'),
                ('arch', 'pacman'), ('fedora', 'dnf'),
                ('rhel', 'dnf'), ('suse', 'zypper'),
            ]:
                if keyword in content:
                    pkg_mgr = pm
                    break
        except Exception:
            pass
    if not pkg_mgr:
        # Last resort: check which binary exists
        for binary, pm in [
            ('apt-get', 'apt'), ('pacman', 'pacman'),
            ('dnf', 'dnf'), ('zypper', 'zypper'),
            ('xbps-install', 'xbps'), ('apk', 'apk'),
        ]:
            if subprocess.run(['which', binary],
                              capture_output=True).returncode == 0:
                pkg_mgr = pm
                break

    return distro_id, distro_pretty, pkg_mgr or 'unknown'


def _detect_init() -> str:
    """Return 'systemd', 'runit', 'openrc', or 'unknown'."""
    try:
        with open('/proc/1/comm') as f:
            pid1 = f.read().strip().lower()
        if 'systemd' in pid1:  return 'systemd'
        if 'runit'   in pid1:  return 'runit'
        if 'openrc'  in pid1:  return 'openrc'
    except Exception:
        pass
    if os.path.isdir('/run/systemd/private'): return 'systemd'
    if os.path.isdir('/etc/sv'):              return 'runit'
    if os.path.isdir('/run/openrc'):          return 'openrc'
    for cmd, result in [
        (['systemctl', '--version'], 'systemd'),
        (['sv', '--version'],        'runit'),
        (['rc-service', '--version'],'openrc'),
    ]:
        try:
            if subprocess.run(cmd, capture_output=True, timeout=2).returncode == 0:
                return result
        except Exception:
            pass
    return 'unknown'


_PM_NAMES = {
    'apt': 'apt (Debian/Ubuntu)', 'pacman': 'pacman (Arch)',
    'dnf': 'dnf (Fedora/RHEL)',  'zypper': 'zypper (openSUSE)',
    'xbps': 'xbps (Void)',       'apk': 'apk (Alpine)',
    'emerge': 'emerge (Gentoo)', 'nix': 'nix (NixOS)',
}
_INIT_NAMES = {
    'systemd': 'systemd', 'runit': 'runit (Void Linux)',
    'openrc':  'OpenRC (Alpine / Gentoo)',
}


# ── Install worker ─────────────────────────────────────────────────────────────

class _ConfigureWorker(QThread):
    progress  = pyqtSignal(str)
    finished  = pyqtSignal(bool, str)

    def __init__(self, install_sh: str):
        super().__init__()
        self._install_sh = install_sh

    def run(self):
        import tempfile, shutil, stat, os
        tmp_script = None
        tmp_srcdir = None
        try:
            self.progress.emit("[FanHub] Preparing installer…")

            # ── Extract install.sh to /tmp ────────────────────────────────────
            with tempfile.NamedTemporaryFile(
                    prefix='fanhub_install_', suffix='.sh',
                    delete=False, mode='w') as tmp:
                with open(self._install_sh) as src_f:
                    tmp.write(src_f.read())
                tmp_script = tmp.name
            os.chmod(tmp_script,
                     stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP |
                     stat.S_IROTH | stat.S_IXOTH)

            # ── Copy only the application SOURCE to /tmp (NOT the venv) ──────
            # The AppImage venv is hundreds of MB — copying it would freeze the
            # UI for minutes. install.sh only needs the source code to copy to
            # /opt/fanhub/; it builds its own venv there from scratch.
            src_dir = os.path.dirname(self._install_sh)

            # Exclude the venv directory to keep the copy fast
            def _ignore_venv(directory, contents):
                return [f for f in contents
                        if f in ('venv', '__pycache__', '.git',
                                 '.appimage_build', '.deb_build')
                        or f.endswith('.pyc')]

            self.progress.emit("[FanHub] Copying source files to /tmp…")
            tmp_srcdir = tempfile.mkdtemp(prefix='fanhub_src_')
            dst = os.path.join(tmp_srcdir, 'fanhub')
            shutil.copytree(src_dir, dst, ignore=_ignore_venv)

            # Make world-readable so root can read the files
            for dirpath, dirnames, filenames in os.walk(tmp_srcdir):
                os.chmod(dirpath, 0o755)
                for fn in filenames:
                    os.chmod(os.path.join(dirpath, fn), 0o644)
            # Make shell scripts executable
            for dirpath, _, filenames in os.walk(tmp_srcdir):
                for fn in filenames:
                    if fn.endswith('.sh') or fn == 'fanhub_daemon.py' or fn == 'main.py':
                        os.chmod(os.path.join(dirpath, fn), 0o755)

            fanhub_source = dst
            self.progress.emit(
                f"[FanHub] Source ready at {fanhub_source}")
            self.progress.emit(
                "[FanHub] Running installer via pkexec (password prompt will appear)…")

            proc = subprocess.Popen(
                ['pkexec', 'env',
                 f'FANHUB_SOURCE_DIR={fanhub_source}',
                 'bash', tmp_script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            output_lines = []
            for line in proc.stdout:
                line = line.rstrip()
                output_lines.append(line)
                self.progress.emit(line)
            proc.wait(timeout=300)
            ok = (proc.returncode == 0)
        except Exception as e:
            ok = False
            output_lines = [str(e)]
            self.progress.emit(f"[FanHub] Error: {e}")
        finally:
            if tmp_script:
                try: os.unlink(tmp_script)
                except Exception: pass
            if tmp_srcdir:
                try: shutil.rmtree(tmp_srcdir, ignore_errors=True)
                except Exception: pass
        self.finished.emit(ok, '\n'.join(output_lines[-20:]))


# ── Main dialog ────────────────────────────────────────────────────────────────

class AppImageConfigureDialog(QDialog):
    """
    Shown on first AppImage launch OR from Settings → Configure System.
    Detects distro/package-manager/init, confirms with user, then runs install.sh.
    """
    configured = pyqtSignal()

    def __init__(self, appdir: str = '', parent=None, force_show: bool = False):
        super().__init__(parent)
        self._appdir  = appdir
        self._worker  = None
        self._install_sh = self._find_install_sh()

        self.setWindowTitle("Fan Hub — System Configuration")
        self.setMinimumWidth(620)
        self.setMinimumHeight(480)
        self.setModal(True)

        # Detect
        self._distro_id, self._distro_pretty, self._pkg_mgr = _detect_distro()
        self._init_sys = _detect_init()

        self._build_ui()

    def _find_install_sh(self) -> str:
        candidates = [
            os.path.join(self._appdir, 'usr/share/fanhub/install.sh'),
            '/opt/fanhub/install.sh',
            os.path.join(os.path.dirname(__file__), '..', 'install.sh'),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.abspath(c)
        return ''

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame { background:#0d1428; border:1px solid #1a3060; border-radius:6px; }")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 12, 14, 12)
        icon = QLabel("⚙")
        icon.setStyleSheet("font-size:32px;")
        hl.addWidget(icon)
        tcol = QVBoxLayout()
        t = QLabel("Configure Fan Hub for Your System")
        t.setStyleSheet("color:#00ddff; font-size:15px; font-weight:bold;")
        tcol.addWidget(t)
        s = QLabel("Fan Hub has detected your system configuration.")
        s.setStyleSheet("color:#667788; font-size:12px;")
        tcol.addWidget(s)
        hl.addLayout(tcol, 1)
        layout.addWidget(hdr)

        pm_name   = _PM_NAMES.get(self._pkg_mgr,  self._pkg_mgr  or 'Unknown')
        init_name = _INIT_NAMES.get(self._init_sys, self._init_sys or 'Unknown')

        body = QLabel(
            f"<b>Detected:</b><br><br>"
            f"&nbsp;&nbsp;Distribution: &nbsp;<b>{self._distro_pretty}</b><br>"
            f"&nbsp;&nbsp;Package manager: <b>{pm_name}</b><br>"
            f"&nbsp;&nbsp;Init system: &nbsp;&nbsp;&nbsp;<b>{init_name}</b><br><br>"
            "If this is correct, click <b>Yes, Configure My System</b> and "
            "authenticate with your password. Fan Hub will:<br><br>"
            "&nbsp;&nbsp;• Install system dependencies via your package manager<br>"
            "&nbsp;&nbsp;• Create the <code>fanhub</code> group and add your user<br>"
            "&nbsp;&nbsp;• Install targeted udev rules for fan PWM access<br>"
            "&nbsp;&nbsp;• Load required kernel modules (nct6775, it87, coretemp…)<br>"
            "&nbsp;&nbsp;• Install and configure the background daemon for your init system<br><br>"
            "This is a one-time step. You can re-run it at any time from "
            "<b>Settings → Configure System</b>."
        )
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet("color:#889aaa; font-size:12px; line-height:1.5;")
        layout.addWidget(body)

        # Progress output (hidden until install starts)
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setVisible(False)
        self._output.setMaximumHeight(160)
        self._output.setStyleSheet(
            "QTextEdit { background:#050a14; color:#88bbcc; "
            "font-family:monospace; font-size:11px; border:1px solid #1a2840; }")
        layout.addWidget(self._output)

        self._prog = QProgressBar()
        self._prog.setRange(0, 0)
        self._prog.setFixedHeight(4)
        self._prog.setTextVisible(False)
        self._prog.setVisible(False)
        layout.addWidget(self._prog)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#667788; font-size:11px;")
        layout.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()

        wrong_btn = QPushButton("Something's Wrong — Report an Issue")
        wrong_btn.setStyleSheet(
            "color:#667788; background:transparent; border:none; font-size:11px;")
        wrong_btn.clicked.connect(self._report_issue)
        btn_row.addWidget(wrong_btn)
        btn_row.addStretch()

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setStyleSheet("color:#445566; background:transparent; border:1px solid #2a3a4a; border-radius:4px; padding:4px 12px;")
        self._skip_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._skip_btn)

        self._yes_btn = QPushButton("Yes, Configure My System")
        self._yes_btn.setObjectName("applyBtn")
        self._yes_btn.setFixedWidth(230)
        self._yes_btn.clicked.connect(self._run_configure)
        btn_row.addWidget(self._yes_btn)
        layout.addLayout(btn_row)

        self._warn_no_script = not bool(self._install_sh)
        if self._warn_no_script:
            self._yes_btn.setEnabled(False)
            self._status.setText("⚠  install.sh not found — cannot auto-configure.")

    def _run_configure(self):
        if not self._install_sh:
            return
        self._yes_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._output.setVisible(True)
        self._prog.setVisible(True)
        self._status.setText("Preparing installer — password prompt will appear shortly…")

        # Mark configure as started in config immediately.
        # If the user cancels the password prompt or it fails, the wizard
        # won't loop forever — they can retry from Settings → Configure System.
        try:
            from core.app_state import AppState
            import json, os
            config_path = os.path.expanduser('~/.config/fanhub/config.json')
            if os.path.exists(config_path):
                with open(config_path) as f:
                    cfg = json.load(f)
                cfg.setdefault('settings', {})['system_configure_done'] = True
                import tempfile
                d = os.path.dirname(config_path)
                fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
                with os.fdopen(fd, 'w') as f:
                    json.dump(cfg, f, indent=2)
                os.replace(tmp, config_path)
        except Exception:
            pass

        self._worker = _ConfigureWorker(self._install_sh)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, line: str):
        self._output.append(line)

    def _on_done(self, ok: bool, last_output: str):
        self._prog.setVisible(False)
        if ok:
            self._status.setText(
                "✓ Configuration complete. Log out and back in for group "
                "membership to take effect (or run: newgrp fanhub).")
            self._status.setStyleSheet("color:#44ff88; font-size:11px;")
            self._yes_btn.setText("Done — Close")
            self._yes_btn.setEnabled(True)
            self._yes_btn.clicked.disconnect()
            self._yes_btn.clicked.connect(self._finish)
        else:
            self._status.setText(
                f"⚠  Configuration failed. Check the output above.\n{last_output[-120:]}")
            self._status.setStyleSheet("color:#ff8844; font-size:11px;")
            self._yes_btn.setText("Retry")
            self._yes_btn.setEnabled(True)
            self._skip_btn.setEnabled(True)

    def _finish(self):
        self.configured.emit()
        self.accept()

    def _report_issue(self):
        pm   = _PM_NAMES.get(self._pkg_mgr, self._pkg_mgr)
        init = _INIT_NAMES.get(self._init_sys, self._init_sys)
        body = (
            f"**Distro:** {self._distro_pretty}\n"
            f"**Package manager:** {pm}\n"
            f"**Init system:** {init}\n\n"
            "**Problem:** (describe what was detected incorrectly)\n"
        )
        import urllib.parse
        params = urllib.parse.urlencode({
            'title': f'System detection issue: {self._distro_pretty}',
            'body':  body,
            'labels':'system-detection',
        })
        # Try GitHub first, fall back to Discord
        try:
            QDesktopServices.openUrl(QUrl(f"{GITHUB_ISSUES}?{params}"))
        except Exception:
            QDesktopServices.openUrl(QUrl(DISCORD_URL))

        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Report an Issue",
            "Your browser has opened the issue tracker.\n\n"
            "Please include:\n"
            f"  • Your distro: {self._distro_pretty}\n"
            f"  • Package manager: {pm}\n"
            f"  • Init system: {init}\n\n"
            "You can also reach us on Discord:\n"
            f"  {DISCORD_URL}"
        )
