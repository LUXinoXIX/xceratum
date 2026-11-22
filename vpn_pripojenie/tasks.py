"""Práca na pozadí, aby GUI nezamrzlo (Cisco CLI, pkexec, openssl)."""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from .cisco import CiscoCli, Outcome, Result
from .profiles import VpnProfile


class Task(QThread):
    done = pyqtSignal(object)

    def __init__(self, fn: Callable, parent: QObject):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            res = self._fn()
        except Exception as e:     # chyba sa odovzdá do GUI, nepadne vlákno
            res = e
        self.done.emit(res)


_running: set = set()


def run_task(parent: QObject, fn: Callable, callback: Optional[Callable] = None) -> Task:
    t = Task(fn, parent)
    if callback:
        t.done.connect(callback)
    _running.add(t)

    def _cleanup():
        _running.discard(t)
        t.deleteLater()

    t.finished.connect(_cleanup)
    t.start()
    return t


class ConnectThread(QThread):
    """Pripájanie v samostatnom vlákne. Otázky (banner, nedôveryhodný server) idú cez signál `ask`
    do GUI a vlákno čaká na odpoveď (`answer`)."""
    progress = pyqtSignal(int, str)
    output = pyqtSignal(str)
    ask = pyqtSignal(str, str)
    done = pyqtSignal(object)

    def __init__(self, cli: CiscoCli, prof: VpnProfile, user: str, password: str, second: str,
                 auto_banner: bool, parent: QObject):
        super().__init__(parent)
        self._cli, self._prof, self._user = cli, prof, user
        self._password, self._second = password, second
        self._auto_banner = auto_banner
        self._cancel = False
        self._event = threading.Event()
        self._answer: Optional[bool] = None

    def cancel(self):
        self._cancel = True
        self._answer = None
        self._event.set()

    @property
    def cancelling(self) -> bool:
        return self._cancel

    def answer(self, value: Optional[bool]):
        self._answer = value
        self._event.set()

    def _ask(self, kind: str, text: str) -> Optional[bool]:
        self._answer = None
        self._event.clear()
        self.ask.emit(kind, text)
        while not self._event.wait(0.2):
            if self._cancel:
                return None
        return None if self._cancel else self._answer

    def run(self):
        try:
            out = self._cli.connect(
                self._prof, self._user, self._password, self._second,
                progress=self.progress.emit, output=self.output.emit, ask=self._ask,
                cancelled=lambda: self._cancel, auto_banner=self._auto_banner)
        except Exception as e:
            out = Outcome(Result.FAILED, "Neočakávaná chyba pri pripájaní.", str(e))
        finally:
            self._password = self._second = ""
        self.done.emit(out)
