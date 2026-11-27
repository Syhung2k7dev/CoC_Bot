"""One COCFARM open at a time for Close COCFARM between upgrades
(``farmbot/wakeup.py``): the open window listens on a local pipe, and a
COCFARM that Windows opens to start (``--start``) while one is open tells
that one to start, then closes. Kept apart from gui.py so that check runs
before the window's (slow) imports."""

from __future__ import annotations

import hashlib
from pathlib import Path


def wake_pipe() -> str:
    """The name the open COCFARM listens on (one per Windows user)."""
    return "cocfarm-" + hashlib.sha1(str(Path.home()).encode()).hexdigest()[:12]


def hand_over_start(name: str | None = None) -> bool:
    """Opened to start while a COCFARM is open: that one is told to start
    instead. True if it was."""
    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError:  # (a build without Qt's networking: this one opens instead)
        return False

    sock = QLocalSocket()
    sock.connectToServer(name or wake_pipe())
    if not sock.waitForConnected(1000):
        return False
    sock.write(b"start")
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True
