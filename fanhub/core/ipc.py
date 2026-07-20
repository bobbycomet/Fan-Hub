"""
IPC (Inter-Process Communication) between Fan Hub GUI and fanhub-daemon.

Uses Qt's QLocalSocket / QLocalServer (UNIX domain sockets) so messages
are delivered instantly to the daemon's asyncio event loop without polling
the config file on every cycle.

Protocol: newline-delimited JSON messages.

Message types (GUI → Daemon):
  {"type": "override",  "fan_id": "...", "speed": 45.0}   # set MANUAL
  {"type": "release",   "fan_id": "..."}                   # back to AUTO
  {"type": "release_all"}                                   # all fans → AUTO
  {"type": "reload"}                                        # re-read config

Message types (Daemon → GUI): (future — for status push)
  {"type": "status", "fan_id": "...", "speed": 45.0, "mode": "manual"}
"""
import json
import logging
import os

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtNetwork import QLocalSocket, QLocalServer

logger = logging.getLogger('fanhub.ipc')

SOCKET_NAME = 'fanhub-daemon'


# ── Client (GUI side) ─────────────────────────────────────────────────────────

class IPCClient(QObject):
    """
    Thin wrapper around QLocalSocket.
    The GUI uses this to send instant override commands to the daemon
    without writing to config.json and waiting for SIGHUP.
    """
    connected_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sock = QLocalSocket(self)
        self._sock.connected.connect(lambda: self.connected_changed.emit(True))
        self._sock.disconnected.connect(self._on_disconnect)
        self._sock.errorOccurred.connect(self._on_error)
        self._retry = QTimer(self)
        self._retry.setInterval(5000)
        self._retry.timeout.connect(self._try_connect)
        self._retry.start()
        self._try_connect()

    def _try_connect(self):
        if self._sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
            return
        self._sock.connectToServer(SOCKET_NAME)

    def _on_disconnect(self):
        self.connected_changed.emit(False)
        self._retry.start()

    def _on_error(self, _err):
        # Daemon not running — silently retry
        pass

    @property
    def is_connected(self) -> bool:
        return self._sock.state() == QLocalSocket.LocalSocketState.ConnectedState

    def _send(self, msg: dict) -> bool:
        if not self.is_connected:
            return False
        try:
            data = (json.dumps(msg) + '\n').encode()
            self._sock.write(data)
            self._sock.flush()
            return True
        except Exception as e:
            logger.debug(f"IPC send error: {e}")
            return False

    def send_override(self, fan_id: str, speed_pct: float) -> bool:
        """Tell daemon to hold this fan at speed_pct% (MANUAL mode)."""
        return self._send({'type': 'override', 'fan_id': fan_id,
                           'speed': round(speed_pct, 1)})

    def send_release(self, fan_id: str) -> bool:
        """Tell daemon to return this fan to curve control (AUTO mode)."""
        return self._send({'type': 'release', 'fan_id': fan_id})

    def send_release_all(self) -> bool:
        """Tell daemon all fans → AUTO."""
        return self._send({'type': 'release_all'})

    def send_reload(self) -> bool:
        """Tell daemon to re-read config (equivalent to SIGHUP)."""
        return self._send({'type': 'reload'})


# ── Server (daemon side) ──────────────────────────────────────────────────────

class IPCServer(QObject):
    """
    QLocalServer that the daemon uses to receive override commands.
    Runs inside the daemon's QCoreApplication event loop.
    """
    override_received  = pyqtSignal(str, float)   # fan_id, speed_pct
    release_received   = pyqtSignal(str)           # fan_id
    release_all        = pyqtSignal()
    reload_requested   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server   = QLocalServer(self)
        self._clients  = []
        self._buffers  = {}

    def start(self) -> bool:
        # Remove stale socket file if daemon was killed uncleanly
        QLocalServer.removeServer(SOCKET_NAME)
        ok = self._server.listen(SOCKET_NAME)
        if ok:
            self._server.newConnection.connect(self._on_new_connection)
            logger.info(f"IPC server listening on {SOCKET_NAME}")
        else:
            logger.warning(f"IPC server failed to start: {self._server.errorString()}")
        return ok

    def stop(self):
        self._server.close()
        QLocalServer.removeServer(SOCKET_NAME)

    def _on_new_connection(self):
        sock = self._server.nextPendingConnection()
        if not sock:
            return
        self._clients.append(sock)
        self._buffers[id(sock)] = b''
        sock.readyRead.connect(lambda s=sock: self._on_data(s))
        sock.disconnected.connect(lambda s=sock: self._on_disconnect(s))

    def _on_disconnect(self, sock):
        self._clients = [c for c in self._clients if c is not sock]
        self._buffers.pop(id(sock), None)
        sock.deleteLater()

    def _on_data(self, sock):
        self._buffers[id(sock)] += bytes(sock.readAll())
        buf = self._buffers[id(sock)]
        while b'\n' in buf:
            line, buf = buf.split(b'\n', 1)
            self._buffers[id(sock)] = buf
            try:
                msg = json.loads(line.decode())
                self._dispatch(msg)
            except Exception as e:
                logger.debug(f"IPC bad message: {e}")

    def _dispatch(self, msg: dict):
        t = msg.get('type', '')
        if t == 'override':
            self.override_received.emit(
                msg['fan_id'], float(msg.get('speed', 0)))
        elif t == 'release':
            self.release_received.emit(msg['fan_id'])
        elif t == 'release_all':
            self.release_all.emit()
        elif t == 'reload':
            self.reload_requested.emit()
