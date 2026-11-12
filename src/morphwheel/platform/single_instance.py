"""One Morphwheel per session (phase-4 §2): a named mutex, and a named pipe the second start
knocks on so the first opens its settings. The third Qt adapter in this package (P1).

Rules:

- **The mutex is the guard, the pipe is only the message.** ``Local\\Morphwheel`` is per session
  (two sessions of one user get two instances, by design) and fixed, so the installer can name it
  (``AppMutex``) and refuse to install over a running app. A refused name is reported as "already
  running" also when Windows answers *access denied*: an elevated first instance's mutex can't be
  opened by a normal second one, which is the same situation. Any other refusal fails open: a
  constant name can't be invalid, and a silent non-start would have no UI to explain itself.
- **A connection is the whole message.** The pipe's bytes aren't there when the connection
  arrives, so nothing is read: each accepted connection means "open the settings". Pipe names are
  machine-wide, so the pipe carries the session id, and it is opened for this user only
  (``UserAccessOption``): Windows' default pipe security would let every local account connect,
  and a connection is a knock. An elevated server still refuses a normal client.
- **Nothing stale.** A mutex and a pipe die with their process; there is no cleanup to do. A
  second start before the first instance listens knocks on nothing and exits anyway: the first is
  visibly on its way.
- ``release`` is idempotent and runs at every exit, including the ones before ``start``.
"""

from __future__ import annotations

import logging
import os
from ctypes import byref
from ctypes import wintypes as wt

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from morphwheel.platform import _win32 as w

log = logging.getLogger("morphwheel.platform.single_instance")

MUTEX_NAME = "Local\\Morphwheel"
ERROR_ACCESS_DENIED = 5


def session_id() -> int:
    """The Windows session this process runs in (0 when unknown)."""
    session = wt.DWORD()
    if not w.kernel32.ProcessIdToSessionId(os.getpid(), byref(session)):
        return 0
    return int(session.value)


def pipe_name() -> str:
    return f"morphwheel-{session_id()}"


class SingleInstance(QObject):
    settings_requested = Signal()  # another start knocked: open the settings

    def __init__(
        self,
        mutex_name: str = MUTEX_NAME,
        pipe: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._mutex_name = mutex_name
        self._pipe = pipe if pipe is not None else pipe_name()
        self._mutex: int | None = None
        self._server: QLocalServer | None = None

    @property
    def held(self) -> bool:
        return self._mutex is not None

    def acquire(self) -> bool:
        """Take the name. ``False`` when another instance holds it (or holds it elevated)."""
        handle = w.kernel32.CreateMutexW(None, False, self._mutex_name)
        error = w.last_error()
        if not handle:
            if error == ERROR_ACCESS_DENIED:
                log.info("single instance: %s is held by an elevated instance", self._mutex_name)
                return False
            log.warning("single instance: CreateMutexW failed (%d); starting anyway", error)
            return True
        if error == w.ERROR_ALREADY_EXISTS:
            w.kernel32.CloseHandle(handle)  # ours would keep the name alive after the owner
            log.info("single instance: %s is held by another instance", self._mutex_name)
            return False
        self._mutex = int(handle)
        return True

    def listen(self) -> bool:
        """Open the pipe for the knocks of later starts. Idempotent."""
        if self._server is not None:
            return True  # set only by a successful listen, cleared by release
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)  # this user only
        server.newConnection.connect(self._on_connection)
        if not server.listen(self._pipe):
            log.warning("single instance: can't listen on %s: %s", self._pipe, server.errorString())
            server.deleteLater()
            return False
        self._server = server
        return True

    def ping(self, timeout_ms: int = 1000) -> bool:
        """Knock on the running instance's pipe. ``False`` when nobody listens (yet)."""
        socket = QLocalSocket()
        socket.connectToServer(self._pipe)
        reached = socket.waitForConnected(timeout_ms)
        if reached:
            socket.disconnectFromServer()
        else:
            log.info("single instance: nobody listens on %s (%s)", self._pipe, socket.errorString())
        return reached

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        if self._mutex is not None:
            w.kernel32.CloseHandle(self._mutex)
            self._mutex = None

    def _on_connection(self) -> None:
        server = self._server
        if server is None:
            return
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            if socket is not None:
                socket.abort()  # the message was the connection: nothing stays open
                socket.deleteLater()
            self.settings_requested.emit()
