#!/usr/bin/env python3
"""
Fan Hub - Comprehensive Linux Fan Control Application
Wayland + X11 compatible.
"""

import sys
import os
import logging

# ── Wayland / X11 detection ───────────────────────────────────────────────────
def _setup_platform():
    if 'QT_QPA_PLATFORM' in os.environ:
        return os.environ['QT_QPA_PLATFORM']

    wayland_display = os.environ.get('WAYLAND_DISPLAY', '')
    xdg_session     = os.environ.get('XDG_SESSION_TYPE', '').lower()

    if wayland_display or xdg_session == 'wayland':
        os.environ.setdefault('QT_QPA_PLATFORM', 'wayland;xcb')
        return 'wayland'

    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
    return 'xcb'

_detected_platform = _setup_platform()

os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.main_window import MainWindow
from core.app_state import AppState

CONFIG_DIR = os.path.expanduser('~/.config/fanhub')
LOG_PATH   = os.path.join(CONFIG_DIR, 'fanhub.log')


def ensure_config_dir():
    os.makedirs(os.path.join(CONFIG_DIR, 'profiles'), exist_ok=True)


def setup_logging():
    ensure_config_dir()
    handlers = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(LOG_PATH, mode='a'))
    except Exception:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=handlers,
    )


def load_icon() -> QIcon:
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
    icon = QIcon()
    for size in [256, 128, 64, 48, 32, 16]:
        path = os.path.join(assets_dir, f'icon_{size}.png')
        if os.path.exists(path):
            icon.addFile(path)
    main_icon = os.path.join(assets_dir, 'icon.png')
    if os.path.exists(main_icon) and icon.isNull():
        icon = QIcon(main_icon)
    if icon.isNull():
        from PyQt6.QtGui import QPixmap, QPainter, QColor, QBrush, QPen
        pix = QPixmap(64, 64)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor("#00ccff")))
        p.setPen(QPen(QColor("#0088cc"), 2))
        p.drawEllipse(4, 4, 56, 56)
        p.end()
        icon = QIcon(pix)
    return icon


def _apply_base_font(app: QApplication):
    """
    Ensure a legible base font size.
    Qt on some Linux distros defaults to 9-10 pt which is too small.
    We bump to 10 pt minimum without overriding a user's custom DPI font.
    """
    font = app.font()
    # Only touch the size if it's suspiciously small
    if font.pointSize() > 0:
        if font.pointSize() < 10:
            font.setPointSize(10)
    elif font.pixelSize() > 0:
        if font.pixelSize() < 14:
            font.setPixelSize(14)
    app.setFont(font)


def main():
    ensure_config_dir()
    setup_logging()
    logger = logging.getLogger('fanhub')
    logger.info(f"Display platform: {_detected_platform} "
                f"(QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM', 'unset')})")

    # ── Audio fix ─────────────────────────────────────────────────────────────
    # Qt6 on some Linux systems (PulseAudio / PipeWire) probes audio devices
    # during QApplication init, which can cause the default audio output to
    # switch momentarily (heard as a brief audio glitch or device swap).
    #
    # Root cause: Qt multimedia plugin (libQt6Multimedia) or the xcb platform
    # plugin enumerates PulseAudio sinks as part of QAudioDevice discovery.
    # Fan Hub does not use audio at all — disable every multimedia plugin.
    #
    # QT_MULTIMEDIA_BACKEND=dummy silences the audio backend completely.
    # QT_STYLE_OVERRIDE is unset so we don't accidentally load a style that
    # triggers additional plugin probing.
    os.environ.setdefault('QT_MULTIMEDIA_BACKEND', 'dummy')
    # Pass only the executable name to QApplication — strip any shell args
    # that could be misinterpreted by Qt's own argument parser (Qt eats
    # -style, -qmljsdebugger, etc. from argv and can load unrelated plugins).
    _qt_argv = [sys.argv[0]]

    app = QApplication(_qt_argv)
    app.setApplicationName("Fan Hub")
    app.setApplicationVersion("1.6.0")
    app.setOrganizationName("FanHub")
    app.setDesktopFileName("fanhub")

    # Keep running when all windows are closed (tray mode)
    app.setQuitOnLastWindowClosed(False)

    # FIX: set a readable base font before any widgets are created
    _apply_base_font(app)

    app_icon = load_icon()
    app.setWindowIcon(app_icon)

    style_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'style.qss')
    if os.path.exists(style_path):
        with open(style_path, 'r') as f:
            app.setStyleSheet(f.read())

    # AppState is fast (just JSON load) — keep synchronous
    state = AppState()

    # MainWindow now shows immediately; slow backends init in background thread
    window = MainWindow(state, app_icon, platform=_detected_platform)

    if state.settings.get('start_minimized', False):
        window.hide()
    else:
        window.show()

    logger.info("Fan Hub started (v1.6.0)")
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
