from ._base import Dummy, EnumNS, QObject, pyqtSignal  # noqa: F401

Qt = EnumNS("Qt")
PYQT_VERSION_STR = "stub"
QT_VERSION_STR = "stub"

_single_shots = []


class QTimer(QObject):
    timeout = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._interval = 0

    def setInterval(self, ms):
        self._interval = ms

    def interval(self):
        return self._interval

    def start(self, *a):
        self._active = True

    def stop(self):
        self._active = False

    def isActive(self):
        return self._active

    def fire(self):
        self.timeout.emit()

    @staticmethod
    def singleShot(ms, fn):
        _single_shots.append(fn)


def run_single_shots():
    while _single_shots:
        _single_shots.pop(0)()


class QThread(QObject):
    finished = pyqtSignal()

    def start(self):
        self.run()            # synchrónne – na testy logiky stačí
        self.finished.emit()

    def wait(self, *a):
        return True

    def isRunning(self):
        return False


class _Pt:
    def __init__(self, x=0, y=0, *a):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


QPoint = QPointF = _Pt


class QRectF(Dummy):
    def __init__(self, *a):
        self._a = a

    def x(self):
        return 0

    y = x

    def width(self):
        return 10

    height = width


QRect = QRectF


class QSize(Dummy):
    pass


class QEvent(Dummy):
    Type = EnumNS("QEvent.Type")
