"""
AppImage system integration dialog.

Shown automatically when Fan Hub detects it is running as an AppImage
and required system components are missing:
  - fanhub group (for PWM write access)
  - udev rules   (99-fanhub.rules)
  - systemd daemon service (optional but recommended)

The dialog runs install.sh via pkexec so the user never needs a terminal.
"""
import os
import subprocess
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFrame, QProgressBar, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

logger = logging.getLogger('fanhub.appimage_setup')


def is_appimage() -> bool:
    """True when running inside an AppImage."""
    return bool(os.environ.get('FANHUB_APPIMAGE'))


def needs_system_setup() -> bool:
    """
    True when essential system components are missing.
    Checks udev rule and fanhub group — the minimum needed for fan control.
    """
    if not os.path.exists('/etc/udev/rules.d/99-fanhub.rules'):
        return True
    try:
        import grp, pwd
        grp.getgrnam('fanhub')
        user = pwd.getpwuid(os.getuid()).pw_name
        if user not in grp.getgrnam('fanhub').gr_mem:
            return True
    except KeyError:
        return True
    return False


class _InstallWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, install_sh: str, install_daemon: bool):
        super().__init__()
        self._install_sh = install_sh
        self._daemon     = install_daemon

    def run(self):
        try:
            cmd = ['pkexec', 'bash', self._install_sh]
            if not self._daemon:
                cmd.append('--no-daemon')
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ok = r.returncode == 0
            self.finished.emit(ok, r.stderr if not ok else r.stdout[-300:])
        except Exception as e:
            self.finished.emit(False, str(e))


class AppImageSetupDialog(QDialog):
    """
    Shown on first launch from an AppImage when system components are missing.
    One-click install via pkexec — no terminal needed.
    """

    setup_done = pyqtSignal()

    def __init__(self, appdir: str, parent=None):
        super().__init__(parent)
        self._appdir     = appdir
        self._install_sh = os.path.join(appdir, 'usr', 'share', 'fanhub', 'install.sh')
        self._worker     = None

        self.setWindowTitle("Fan Hub — System Setup")
        self.setMinimumWidth(540)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        # Header
        icon_row = QHBoxLayout()
        icon = QLabel("🔧")
        icon.setStyleSheet("font-size:36px;")
        icon_row.addWidget(icon)
        hcol = QVBoxLayout()
        title = QLabel("System Setup Required")
        title.setStyleSheet("color:#00ddff; font-size:16px; font-weight:bold;")
        hcol.addWidget(title)
        sub = QLabel("Fan control needs a few system-level components.")
        sub.setStyleSheet("color:#667788; font-size:12px;")
        hcol.addWidget(sub)
        icon_row.addLayout(hcol, 1)
        layout.addLayout(icon_row)

        # Explanation
        body = QLabel(
            "Fan Hub needs to:\n\n"
            "  • Create a <b>fanhub</b> group and add your user to it\n"
            "  • Install targeted <b>udev rules</b> granting that group write\n"
            "    access to fan speed (PWM) sysfs files — nothing else\n"
            "  • Load kernel modules (<code>nct6775</code>, <code>it87</code>, "
            "<code>coretemp</code>)\n\n"
            "This is a one-time step. Click <b>Install System Components</b> and "
            "authenticate with your password."
        )
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet("color:#889aaa; font-size:12px; line-height:1.5;")
        layout.addWidget(body)

        # Daemon checkbox
        self._daemon_cb = QCheckBox(
            "Also install and enable the background daemon\n"
            "(keeps fan curves running at boot and when the app is closed)")
        self._daemon_cb.setChecked(True)
        self._daemon_cb.setStyleSheet("color:#aabbcc; font-size:12px;")
        layout.addWidget(self._daemon_cb)

        # Progress
        self._prog = QProgressBar()
        self._prog.setRange(0, 0)
        self._prog.setFixedHeight(4)
        self._prog.setTextVisible(False)
        self._prog.setVisible(False)
        layout.addWidget(self._prog)

        # Status label
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#667788; font-size:11px;")
        layout.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        skip_btn = QPushButton("Skip for now (fan control may not work)")
        skip_btn.setStyleSheet(
            "color:#445566; background:transparent; border:none; font-size:11px;")
        skip_btn.clicked.connect(self._skip)
        btn_row.addWidget(skip_btn)
        btn_row.addStretch()

        self._install_btn = QPushButton("Install System Components")
        self._install_btn.setObjectName("applyBtn")
        self._install_btn.setFixedWidth(220)
        self._install_btn.clicked.connect(self._run_install)
        btn_row.addWidget(self._install_btn)
        layout.addLayout(btn_row)

    def _run_install(self):
        if not os.path.exists(self._install_sh):
            self._status.setText(
                f"⚠  install.sh not found at {self._install_sh}\n"
                "Please run the installer manually from a terminal.")
            return

        self._install_btn.setEnabled(False)
        self._prog.setVisible(True)
        self._status.setText("Waiting for authentication…")

        self._worker = _InstallWorker(self._install_sh, self._daemon_cb.isChecked())
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok: bool, output: str):
        self._prog.setVisible(False)
        if ok:
            self._status.setText(
                "✓ System components installed successfully.\n"
                "Log out and back in for group membership to take effect "
                "(or run: newgrp fanhub)")
            self._status.setStyleSheet("color:#44ff88; font-size:11px;")
            self._install_btn.setText("Done — Close")
            self._install_btn.setEnabled(True)
            self._install_btn.clicked.disconnect()
            self._install_btn.clicked.connect(self._finish)
        else:
            self._status.setText(f"⚠  Installation failed:\n{output[-200:]}")
            self._status.setStyleSheet("color:#ff8844; font-size:11px;")
            self._install_btn.setEnabled(True)

    def _finish(self):
        self.setup_done.emit()
        self.accept()

    def _skip(self):
        self.reject()
