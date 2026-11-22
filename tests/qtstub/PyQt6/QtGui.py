from ._base import Dummy, EnumNS, QObject, pyqtSignal


class QColor(Dummy):
    def __init__(self, *a):
        self._a = a

    def lightness(self):
        return 255


class QFont(Dummy):
    Weight = EnumNS("QFont.Weight")


class QFontMetrics(Dummy):
    def horizontalAdvance(self, s):
        return 7 * len(str(s))

    def height(self):
        return 16

    def elidedText(self, s, *a):
        return s


class QFontDatabase(Dummy):
    SystemFont = EnumNS("SystemFont")

    @staticmethod
    def systemFont(*a):
        return QFont()


class _Hints(QObject):
    colorSchemeChanged = pyqtSignal()

    def colorScheme(self):
        return EnumNS("Qt").ColorScheme.Light


_hints = _Hints()


class QGuiApplication(QObject):
    _inst = None

    def __init__(self, *a):
        super().__init__()
        QGuiApplication._inst = self

    @classmethod
    def instance(cls):
        return QGuiApplication._inst

    @staticmethod
    def styleHints():
        return _hints

    @staticmethod
    def platformName():
        return "xcb"

    @staticmethod
    def font():
        return QFont()

    @staticmethod
    def palette():
        return QPalette()


class QPalette(Dummy):
    ColorRole = EnumNS("ColorRole")

    def color(self, *a):
        return QColor()


class QAction(QObject):
    triggered = pyqtSignal(bool)

    def __init__(self, text="", parent=None):
        super().__init__(parent if isinstance(parent, QObject) else None)
        self._text, self._enabled, self._checked = text, True, False

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text

    def setEnabled(self, e):
        self._enabled = e

    def isEnabled(self):
        return self._enabled

    def setCheckable(self, c):
        pass

    def setChecked(self, c):
        self._checked = c

    def isChecked(self):
        return self._checked

    def font(self):
        return QFont()

    def trigger(self):
        self.triggered.emit(self._checked)


class QActionGroup(QObject):
    pass


class QTextCursor(Dummy):
    MoveOperation = EnumNS("MoveOperation")


def __getattr__(name):
    return type(name, (Dummy,), {})
