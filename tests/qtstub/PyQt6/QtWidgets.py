from ._base import Dummy, EnumNS, QObject, pyqtSignal
from .QtGui import QGuiApplication


class QWidget(QObject):
    def __init__(self, parent=None, *a, **k):
        super().__init__(parent)
        self._visible = False
        self._explicit_hidden = False
        self._enabled = True
        self._focus = False
        self._w, self._h = 100, 30
        self._layout = None
        self._is_window = parent is None

    def show(self):
        self.setVisible(True)

    def hide(self):
        self.setVisible(False)

    def setVisible(self, v):
        self._visible = bool(v)
        self._explicit_hidden = not v

    def isVisible(self):
        if not self._visible and self._is_window:
            return False
        if self._explicit_hidden:
            return False
        p = self._parent
        return p.isVisible() if isinstance(p, QWidget) else self._visible

    def isHidden(self):
        return self._explicit_hidden

    def isVisibleTo(self, *a):
        return not self._explicit_hidden

    def setEnabled(self, e):
        self._enabled = bool(e)

    def isEnabled(self):
        return self._enabled

    def setFocus(self, *a):
        for w in QObject._all:
            if isinstance(w, QWidget):
                w._focus = False
        self._focus = True

    def hasFocus(self):
        return self._focus

    def width(self):
        return self._w

    def height(self):
        return self._h

    def setFixedWidth(self, w):
        self._w = w

    def setFixedHeight(self, h):
        self._h = h

    def setFixedSize(self, w, h=None):
        if h is not None:
            self._w, self._h = w, h

    def rect(self):
        return Dummy()

    def window(self):
        return self

    def isMinimized(self):
        return False

    def windowState(self):
        return 0

    def setLayout(self, lay):
        self._layout = lay

    def update(self, *a):
        pass

    def close(self):
        ev = _CloseEvent()
        self.closeEvent(ev)
        if ev.accepted:
            self.hide()
        return ev.accepted

    def closeEvent(self, e):
        e.accept()

    def mapToGlobal(self, p):
        return p


class _CloseEvent:
    def __init__(self):
        self.accepted = True

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class QLayout(QObject):
    SizeConstraint = EnumNS("SizeConstraint")

    def __init__(self, parent=None, *a):
        super().__init__(parent)
        self._owner = parent if isinstance(parent, QWidget) else None
        if self._owner is not None:
            self._owner._layout = self

    def addWidget(self, w, *a, **k):
        if self._owner is not None:
            w.setParent(self._owner)
            w._is_window = False
            if not w._explicit_hidden:
                w._visible = True

    def addLayout(self, lay, *a):
        lay._owner = self._owner

    def addRow(self, *a):
        for w in a:
            if isinstance(w, QWidget):
                self.addWidget(w)


QVBoxLayout = QHBoxLayout = QFormLayout = QLayout


class QApplication(QGuiApplication):
    def __init__(self, *a):
        super().__init__(*a)
        self._style = ""

    def setStyleSheet(self, s):
        self._style = s

    def quit(self):
        self._quit = True

    @staticmethod
    def clipboard():
        return Dummy()


class QLabel(QWidget):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = text

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text


class QLineEdit(QWidget):
    textChanged = pyqtSignal(str)
    returnPressed = pyqtSignal()
    EchoMode = EnumNS("EchoMode")

    def __init__(self, *a):
        super().__init__()
        self._text = ""
        self._echo = QLineEdit.EchoMode.Normal
        self._max = 32767

    def setText(self, t):
        t = t[: self._max]
        if t != self._text:
            self._text = t
            self.textChanged.emit(t)

    def text(self):
        return self._text

    def clear(self):
        self.setText("")

    def setMaxLength(self, n):
        self._max = n

    def setEchoMode(self, m):
        self._echo = m

    def echoMode(self):
        return self._echo


class QAbstractButton(QWidget):
    clicked = pyqtSignal(bool)
    toggled = pyqtSignal(bool)

    def __init__(self, text="", parent=None):
        super().__init__(parent if isinstance(parent, QObject) else None)
        self._text = text if isinstance(text, str) else ""
        self._checkable = False
        self._checked = False

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text

    def setCheckable(self, c):
        self._checkable = c

    def setChecked(self, c):
        if c != self._checked:
            self._checked = c
            self.toggled.emit(c)

    def isChecked(self):
        return self._checked

    def isDown(self):
        return False

    def click(self):
        if self._enabled:
            if self._checkable:
                self.setChecked(not self._checked)
            self.clicked.emit(self._checked)


QPushButton = QCheckBox = QAbstractButton


class QMenu(QWidget):
    def __init__(self, *a):
        super().__init__(a[0] if a and isinstance(a[0], QObject) else None)
        self.actions = []

    def addAction(self, a):
        from .QtGui import QAction
        if isinstance(a, str):
            a = QAction(a, self)
        self.actions.append(a)
        return a

    def addMenu(self, title):
        m = QMenu(self)
        self.actions.append(m)
        return m

    def addSeparator(self):
        pass

    def exec(self, *a):
        QMenu.last = self
        return None

    def sizeHint(self):
        return Dummy()


class QMessageBox(QWidget):
    StandardButton = EnumNS("StandardButton")
    ButtonRole = EnumNS("ButtonRole")
    Icon = EnumNS("Icon")
    answers = []          # odpovede pre question()
    choose = []           # index tlačidla pre exec()
    log = []

    def __init__(self, *a):
        super().__init__()
        self._buttons = []
        self._clicked = None

    def addButton(self, text, role=None):
        b = QPushButton(text)
        self._buttons.append(b)
        return b

    def exec(self):
        i = QMessageBox.choose.pop(0) if QMessageBox.choose else 0
        self._clicked = self._buttons[i] if self._buttons else None
        QMessageBox.log.append(("exec", [b.text() for b in self._buttons], i))
        return 0

    def clickedButton(self):
        return self._clicked

    @staticmethod
    def question(*a, **k):
        QMessageBox.log.append(("question", a[2] if len(a) > 2 else ""))
        return QMessageBox.answers.pop(0) if QMessageBox.answers else QMessageBox.StandardButton.Yes

    @staticmethod
    def information(*a, **k):
        QMessageBox.log.append(("information", a[2] if len(a) > 2 else ""))

    warning = about = information


class QDialog(QWidget):
    DialogCode = EnumNS("DialogCode")
    result_code = None

    def exec(self):
        return QDialog.result_code if QDialog.result_code is not None else QDialog.DialogCode.Accepted

    def accept(self):
        pass

    reject = accept


class QDialogButtonBox(QWidget):
    StandardButton = EnumNS("DBB.StandardButton")
    ButtonRole = EnumNS("DBB.ButtonRole")
    accepted = pyqtSignal()
    rejected = pyqtSignal()

    def addButton(self, *a):
        return QPushButton(a[0] if a and isinstance(a[0], str) else "")


class QInputDialog:
    answers = []

    @staticmethod
    def getText(*a, **k):
        return QInputDialog.answers.pop(0) if QInputDialog.answers else ("", False)


class QSystemTrayIcon(QWidget):
    available = True
    ActivationReason = EnumNS("ActivationReason")
    activated = pyqtSignal(int)
    messages = []

    @staticmethod
    def isSystemTrayAvailable():
        return QSystemTrayIcon.available

    def supportsMessages(self):
        return True

    def showMessage(self, title, body, *a):
        QSystemTrayIcon.messages.append((title, body))

    def setContextMenu(self, m):
        self._menu = m


class QPlainTextEdit(QWidget):
    LineWrapMode = EnumNS("LineWrapMode")

    def __init__(self, *a):
        super().__init__()
        self._text = ""

    def setPlainText(self, t):
        self._text = t

    def toPlainText(self):
        return self._text

    def clear(self):
        self._text = ""

    def textCursor(self):
        ed = self

        class Cur(Dummy):
            def insertText(self, t):
                ed._text += t
        return Cur()


QTextBrowser = QPlainTextEdit


class QSizePolicy(Dummy):
    Policy = EnumNS("Policy")


class QAbstractItemView(Dummy):
    SelectionBehavior = EnumNS("SelectionBehavior")
    SelectionMode = EnumNS("SelectionMode")
    EditTrigger = EnumNS("EditTrigger")


class QHeaderView(Dummy):
    ResizeMode = EnumNS("ResizeMode")


class QTableWidgetItem:
    def __init__(self, text=""):
        self._text, self._data, self._check = text, {}, None

    def text(self):
        return self._text

    def setData(self, role, v):
        self._data[role] = v

    def data(self, role):
        return self._data.get(role)

    def setFlags(self, *a):
        pass

    def setCheckState(self, s):
        self._check = s

    def checkState(self):
        return self._check


class QTableWidget(QWidget):
    def __init__(self, rows=0, cols=0, *a):
        super().__init__()
        self._rows = []
        self._cols = cols
        self._cur = -1

    def rowCount(self):
        return len(self._rows)

    def insertRow(self, r):
        self._rows.insert(r, {})

    def removeRow(self, r):
        del self._rows[r]

    def setRowCount(self, n):
        self._rows = self._rows[:n] + [{} for _ in range(n - len(self._rows))]

    def setItem(self, r, c, it):
        self._rows[r][c] = it

    def item(self, r, c):
        return self._rows[r].get(c)

    def setCellWidget(self, r, c, w):
        self._rows[r][("w", c)] = w
        w.setParent(self)

    def cellWidget(self, r, c):
        return self._rows[r].get(("w", c))

    def currentRow(self):
        return self._cur

    def selectRow(self, r):
        self._cur = r

    def horizontalHeader(self):
        return Dummy()

    verticalHeader = horizontalHeader


class QComboBox(QWidget):
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, *a):
        super().__init__()
        self._items, self._i = [], -1

    def addItems(self, items):
        self._items += list(items)
        if self._i < 0 and self._items:
            self._i = 0

    def setCurrentIndex(self, i):
        self._i = i
        self.currentIndexChanged.emit(i)

    def currentIndex(self):
        return self._i

    def setCurrentText(self, t):
        if t in self._items:
            self._i = self._items.index(t)

    def currentText(self):
        return self._items[self._i] if 0 <= self._i < len(self._items) else ""


class QSpinBox(QWidget):
    def __init__(self, *a):
        super().__init__()
        self._v = 0

    def setValue(self, v):
        self._v = v

    def value(self):
        return self._v


class QTabWidget(QWidget):
    currentChanged = pyqtSignal(int)

    def __init__(self, *a):
        super().__init__()
        self._tabs, self._i = [], 0

    def addTab(self, w, title):
        self._tabs.append(w)
        w.setParent(self)

    def count(self):
        return len(self._tabs)

    def widget(self, i):
        return self._tabs[i]

    def setCurrentIndex(self, i):
        self._i = i

    def currentIndex(self):
        return self._i


QGroupBox = QWidget


class QFileDialog:
    open_answer = ("", "")

    @staticmethod
    def getOpenFileName(*a, **k):
        return QFileDialog.open_answer

    @staticmethod
    def getSaveFileName(*a, **k):
        return QFileDialog.open_answer


def __getattr__(name):
    return type(name, (QWidget,), {})
