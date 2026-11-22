"""Spustenie aplikácie.

  vpn-pripojenie                  otvorí okno (ak už beží, prenesie ho dopredu)
  vpn-pripojenie --skryte         štart po prihlásení: len ikona v lište (ak lišta nie je, otvorí okno)
  vpn-pripojenie --nastavenia     otvorí Profily a certifikáty
  vpn-pripojenie --verzia
"""
from __future__ import annotations

import os
import signal
import sys

from . import APP_ID, __version__


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = [a.lstrip("-/").lower() for a in argv[1:]]
    if "verzia" in args or "version" in args:
        print(f"VPN Pripojenie {__version__}")
        return 0

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write("Chýba PyQt6. Ubuntu: sudo apt install python3-pyqt6 · Fedora: sudo dnf install python3-pyqt6\n")
        return 1

    app = QApplication(["vpn-pripojenie", *argv[1:]])   # názov procesu/okna = vpn-pripojenie (X11 WM_CLASS)
    app.setApplicationName("VPN Pripojenie")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)            # Wayland: priradí okno k .desktop súboru (ikona v doku)
    app.setQuitOnLastWindowClosed(False)      # beží ďalej v lište
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from . import icons
    app.setWindowIcon(icons.app_icon(0, dot=False))

    command = "settings" if ("nastavenia" in args or "settings" in args) else "show"
    server = _single_instance(command)
    if server is False:
        return 0          # už beží – správu dostala bežiaca inštancia

    from .main_window import MainWindow
    win = MainWindow(start_hidden=("skryte" in args or "hidden" in args))
    if server is not None:
        def on_message(msg: str):
            if msg == "settings":
                win.show_from_tray()
                win.open_manager(0)
            else:
                win.show_from_tray()
        server.message.connect(on_message)
    if command == "settings":
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(300, lambda: win.open_manager(0))
    return app.exec()


def _single_instance(command: str):
    """Vráti server (prvá inštancia), False (iná inštancia beží) alebo None (QtNetwork chýba)."""
    try:
        from PyQt6.QtCore import QObject, pyqtSignal
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    except ImportError:
        return None

    name = f"{APP_ID}-{os.getuid()}"
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(command.encode())
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return False

    class Server(QObject):
        message = pyqtSignal(str)

        def __init__(self):
            super().__init__()
            self.srv = QLocalServer(self)
            QLocalServer.removeServer(name)      # po páde môže ostať starý socket
            self.srv.listen(name)
            self.srv.newConnection.connect(self._conn)

        def _conn(self):
            c = self.srv.nextPendingConnection()
            if c is None:
                return
            c.readyRead.connect(lambda c=c: self.message.emit(bytes(c.readAll()).decode(errors="replace").strip()))
            c.disconnected.connect(c.deleteLater)

    return Server()


if __name__ == "__main__":
    raise SystemExit(main())
