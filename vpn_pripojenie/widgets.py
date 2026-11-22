"""Ovládacie prvky podľa dizajnu v2: hlavička, polia s ikonou, prepínač, hlásenia, kroky, tlačidlá."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QTextCursor
from PyQt6.QtWidgets import (QAbstractButton, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from . import icons
from . import theme as TH
from .theme import mono_font, ui_font

DEMI = QFont.Weight.DemiBold


def T():
    return TH.current()


class Spinner:
    """Spoločný uhol pre točiace sa kruhy (jeden časovač na prvok)."""

    def __init__(self, widget: QWidget, step: int = 24):
        self.angle = 0
        self._w = widget
        self._step = step
        self._timer = QTimer(widget)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self.angle = (self.angle + self._step) % 360
        self._w.update()

    def start(self):
        if not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._timer.stop()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def draw(self, p: QPainter, rect: QRectF, color: QColor, width: float):
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, int(-self.angle * 16), 270 * 16)


# ------------------------------------------------------------------ tlačidlo s ikonou

class IconButton(QAbstractButton):
    def __init__(self, icon: str, tooltip: str = "", on_header: bool = False, size: int = 40, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.on_header = on_header
        self._hover = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)

    def set_icon(self, name: str, tooltip: str = ""):
        self.icon_name = name
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fg = QColor(t.header_text if self.on_header else t.muted)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._hover or self.isDown():
            bg = QColor(255, 255, 255, 40) if self.on_header else QColor(t.disabled_bg)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 6, 6)
        if self.hasFocus():
            p.setPen(QPen(fg, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
        s = 20
        icons.draw(p, self.icon_name, QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s), fg, 1.8)
        p.end()


# ------------------------------------------------------------------ hlavička

class HeaderBar(QWidget):
    HEIGHT = 88

    def __init__(self, frameless: bool, parent=None):
        super().__init__(parent)
        self.title = "VPN Pripojenie"
        self.subtitle = "Cisco Secure Client"
        self.caption = "Pripojenie k"
        self.profile = ""
        self.setFixedHeight(self.HEIGHT)
        self.btn_menu = IconButton("menu", "Ponuka", on_header=True)
        self.btn_min = IconButton("minimize", "Minimalizovať", on_header=True)
        self.btn_close = IconButton("close", "Zavrieť", on_header=True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(2)
        lay.addStretch(1)
        for b in (self.btn_menu, self.btn_min, self.btn_close):
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_min.setVisible(frameless)
        self.btn_close.setVisible(frameless)
        self._frameless = frameless

    def set_texts(self, title=None, caption=None, profile=None):
        if title is not None:
            self.title = title
        if caption is not None:
            self.caption = caption
        if profile is not None:
            self.profile = profile
        self.setAccessibleName(f"{self.title} – {self.caption} {self.profile}")
        self.update()

    def mousePressEvent(self, e):
        if self._frameless and e.button() == Qt.MouseButton.LeftButton:
            wh = self.window().windowHandle()
            if wh is not None:
                wh.startSystemMove()
                return
        super().mousePressEvent(e)

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(t.header_bg))
        if t.header_line_w:
            p.fillRect(0, self.height() - t.header_line_w, self.width(), t.header_line_w, QColor(t.header_line))
        white, sub = QColor(t.header_text), QColor(t.header_sub)
        x = 20.0
        icons.draw(p, "shield_lock", QRectF(x - 2, (self.height() - 44) / 2, 44, 44), white, 1.6)
        x += 44 + 12
        f_title = ui_font(15, QFont.Weight.Bold)
        f_small = ui_font(11)
        f_prof = ui_font(14, DEMI)
        fm_t, fm_s, fm_p = QFontMetrics(f_title), QFontMetrics(f_small), QFontMetrics(f_prof)
        top = (self.height() - fm_t.height() - fm_s.height()) / 2
        p.setFont(f_title)
        p.setPen(white)
        p.drawText(QRectF(x, top, 200, fm_t.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.title)
        p.setFont(f_small)
        p.setPen(sub)
        p.drawText(QRectF(x, top + fm_t.height() - 1, 200, fm_s.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.subtitle)
        x += max(fm_t.horizontalAdvance(self.title), fm_s.horizontalAdvance(self.subtitle)) + 12
        p.fillRect(QRectF(x, (self.height() - 40) / 2, 1, 40), QColor(255, 255, 255, 110 if t.is_dark else 140))
        x += 12
        right = self.btn_menu.x() - 8
        top = (self.height() - fm_s.height() - fm_p.height()) / 2
        p.setPen(sub)
        p.setFont(f_small)
        p.drawText(QRectF(x, top, max(10, right - x), fm_s.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.caption)
        p.setPen(white)
        p.setFont(f_prof)
        prof = fm_p.elidedText(self.profile, Qt.TextElideMode.ElideRight, int(max(10, right - x)))
        p.drawText(QRectF(x, top + fm_s.height(), max(10, right - x), fm_p.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, prof)
        p.end()


# ------------------------------------------------------------------ pole s ikonou

class FieldBox(QWidget):
    """Zaoblený box: ikona vľavo, malý popis nad hodnotou; textové pole alebo roletka."""
    clicked = pyqtSignal()

    def __init__(self, icon: str, caption: str, dropdown: bool = False, password: bool = False,
                 mono: bool = False, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.dropdown = dropdown
        self._hover = False
        self._mono = mono
        self.setFixedHeight(58)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14 + 20 + 12, 7, 8 if password else 14, 7)
        lay.setSpacing(4)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel(caption)
        self.caption.setFont(ui_font(12))
        self.caption.setProperty("muted", True)
        col.addWidget(self.caption)
        self.edit: Optional[QLineEdit] = None
        self.value: Optional[QLabel] = None
        self.eye: Optional[IconButton] = None
        if dropdown:
            self.value = QLabel("")
            self.value.setFont(ui_font(16))
            self.value.setTextFormat(Qt.TextFormat.RichText)
            col.addWidget(self.value)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setAccessibleName(caption)
        else:
            self.edit = QLineEdit()
            self.edit.setObjectName("FieldEdit")
            self.edit.setFrame(False)
            self.edit.setFont(mono_font(18) if mono else ui_font(16))
            self.edit.setAccessibleName(caption)
            self.edit.installEventFilter(self)
            col.addWidget(self.edit)
            self.setFocusProxy(self.edit)
            self.setCursor(Qt.CursorShape.IBeamCursor)
        lay.addLayout(col, 1)
        if password and self.edit is not None:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.eye = IconButton("eye", "Zobraziť heslo", size=40)
            self.eye.clicked.connect(self._toggle_eye)
            lay.addWidget(self.eye, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_caption(self, text: str):
        self.caption.setText(text)
        if self.edit:
            self.edit.setAccessibleName(text)

    def set_value(self, main: str, extra: str = ""):
        if self.value is None:
            return
        t = T()
        from html import escape
        html = escape(main)
        if extra:
            html += f' <span style="color:{t.muted}; font-size:12px;">· {escape(extra)}</span>'
        self.value.setText(html)
        self.setAccessibleDescription(f"{main} {extra}")

    def set_password_mode(self, on: bool):
        if self.edit:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password if on else QLineEdit.EchoMode.Normal)

    def _toggle_eye(self):
        hidden = self.edit.echoMode() == QLineEdit.EchoMode.Password
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.eye.set_icon("eye_off" if hidden else "eye", "Skryť heslo" if hidden else "Zobraziť heslo")
        self.edit.setFocus()

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.update()
        return False

    def _focused(self) -> bool:
        return self.edit.hasFocus() if self.edit else self.hasFocus()

    def focusInEvent(self, e):
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if self.dropdown and self.isEnabled():
            self.setFocus()
            self.clicked.emit()
        elif self.edit:
            self.edit.setFocus()
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if self.dropdown and e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
            self.clicked.emit()
            return
        super().keyPressEvent(e)

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        focused = self._focused()
        bw = 2.0 if focused else 1.0
        r = QRectF(self.rect()).adjusted(bw / 2, bw / 2, -bw / 2, -bw / 2)
        border = t.field_focus if focused else (t.muted if self._hover and self.dropdown and self.isEnabled()
                                                else t.field_border)
        p.setPen(QPen(QColor(border), bw))
        p.setBrush(QColor(t.field_bg))
        p.drawRoundedRect(r, 8, 8)
        col = QColor(t.muted if self.isEnabled() else t.disabled_text)
        icons.draw(p, self.icon_name, QRectF(14, (self.height() - 20) / 2, 20, 20), col, 1.8)
        if self.dropdown:
            icons.draw(p, "chevron", QRectF(self.width() - 14 - 18, (self.height() - 18) / 2, 18, 18), col, 2.0)
        p.end()


# ------------------------------------------------------------------ prepínač

class Toggle(QAbstractButton):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(text)
        self.setFixedHeight(40)

    def sizeHint(self):
        return QSize(40 + 12 + QFontMetrics(ui_font(14)).horizontalAdvance(self.text()) + 8, 40)

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, (self.height() - 22) / 2, 40, 22)
        on = self.isChecked()
        col = t.accent if on else t.toggle_off
        if not self.isEnabled():
            col = t.disabled_bg
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        p.drawRoundedRect(track, 11, 11)
        p.setBrush(QColor("#FFFFFF"))
        kx = track.x() + (21 if on else 3)
        p.drawEllipse(QRectF(kx, track.y() + 3, 16, 16))
        if self.hasFocus():
            p.setPen(QPen(QColor(t.accent), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-2.5, -2.5, 2.5, 2.5), 13, 13)
        p.setPen(QColor(t.text if self.isEnabled() else t.disabled_text))
        p.setFont(ui_font(14))
        p.drawText(QRectF(52, 0, self.width() - 52, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        p.end()


# ------------------------------------------------------------------ stav (Odpojené / Pripájam sa / Pripojené)

class StatusPill(QWidget):
    TEXTS = {"off": "Odpojené", "busy": "Pripájam sa…", "on": "Pripojené", "reconnect": "Obnovujem spojenie…",
             "error": "Nepripojené – chyba", "check": "Zisťujem stav…"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "off"
        self.text = self.TEXTS["off"]
        self.spin = Spinner(self)
        self.setFixedHeight(28)
        self.setAccessibleName(self.text)

    def set_state(self, state: str, text: Optional[str] = None):
        self.state = state
        self.text = text or self.TEXTS.get(state, state)
        self.setAccessibleName(self.text)
        if state in ("busy", "reconnect", "check"):
            self.spin.start()
        else:
            self.spin.stop()
        self.update()

    def sizeHint(self):
        return QSize(QFontMetrics(ui_font(13, DEMI)).horizontalAdvance(self.text) + 50, 28)

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = {"off": t.toggle_off, "busy": t.warn_icon, "reconnect": t.warn_icon, "on": t.ok_icon,
                  "error": t.err_icon, "check": t.muted}
        c = QColor(colors.get(self.state, t.muted))
        w = QFontMetrics(ui_font(13, DEMI)).horizontalAdvance(self.text) + 40
        pill = QRectF(0.5, 0.5, w, self.height() - 1)
        bg = QColor(c)
        bg.setAlpha(36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 14, 14)
        dot = QRectF(12, (self.height() - 12) / 2, 12, 12)
        if self.spin.running:
            self.spin.draw(p, dot, c, 2.2)
        else:
            p.setBrush(c)
            p.drawEllipse(dot.adjusted(1, 1, -1, -1))
        p.setPen(QColor(t.text))
        p.setFont(ui_font(13, DEMI))
        p.drawText(QRectF(30, 0, w - 30, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text)
        p.end()


# ------------------------------------------------------------------ hlásenie

class Notice(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = "info"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12 + 16 + 10, 9, 12, 9)
        lay.setSpacing(3)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setFont(ui_font(13))
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.original = QLabel()
        self.original.setWordWrap(True)
        self.original.setFont(ui_font(11))
        self.original.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.label)
        lay.addWidget(self.original)
        self.hide()

    def show_msg(self, kind: str, text: str, original: str = ""):
        self.kind = kind
        self.label.setText(text)
        self.original.setText(original)
        self.original.setVisible(bool(original))
        self.setAccessibleName(text)
        self._colors()
        self.show()

    def _colors(self):
        t = T()
        fg = {"error": t.err_text, "success": t.ok_text, "warn": t.warn_text}.get(self.kind, t.info_text)
        self.label.setStyleSheet(f"color: {fg};")
        self.original.setStyleSheet(f"color: {fg};")

    def refresh_theme(self):
        self._colors()
        self.update()

    def paintEvent(self, e):
        t = T()
        bg, border, icon, name = {
            "error": (t.err_bg, t.err_border, t.err_icon, "alert"),
            "success": (t.ok_bg, t.ok_border, t.ok_icon, "check"),
            "warn": (t.warn_bg, t.warn_border, t.warn_icon, "warning"),
        }.get(self.kind, (t.info_bg, t.info_border, t.info_icon, "info"))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(border), 1))
        p.setBrush(QColor(bg))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        icons.draw(p, name, QRectF(12, 11, 16, 16), QColor(icon), 2.0)
        p.end()


# ------------------------------------------------------------------ kroky pripájania

class StepIcon(QWidget):
    def __init__(self, spinner_owner: "StepsView"):
        super().__init__()
        self.state = "pending"     # pending | active | done | failed
        self._owner = spinner_owner
        self.setFixedSize(22, 22)

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, 20, 20)
        if self.state == "done":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.ok_icon))
            p.drawEllipse(r)
            icons.draw(p, "check", QRectF(5, 5, 12, 12), QColor(t.on_ok), 3.2)
        elif self.state == "failed":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.err_icon))
            p.drawEllipse(r)
            icons.draw(p, "close", QRectF(4, 4, 14, 14), QColor("#FFFFFF"), 3.0)
        elif self.state == "active":
            p.setPen(QPen(QColor(t.field_border), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(1, 1, -1, -1))
            self._owner.spin.draw(p, r.adjusted(1, 1, -1, -1), QColor(t.accent), 2.4)
        else:
            p.setPen(QPen(QColor(t.field_border), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(1, 1, -1, -1))
        p.end()


class StepsView(QWidget):
    def __init__(self, labels: list, parent=None):
        super().__init__(parent)
        self.spin = Spinner(self)
        self.current = 0
        self.failed = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)
        self.rows = []
        for text in labels:
            row = QHBoxLayout()
            row.setSpacing(10)
            ic = StepIcon(self)
            lb = QLabel(text)
            lb.setFont(ui_font(14))
            row.addWidget(ic)
            row.addWidget(lb, 1)
            lay.addLayout(row)
            self.rows.append((ic, lb))
        self.message = QLabel()
        self.message.setFont(mono_font(11))
        self.message.setProperty("muted", True)
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self.spin._w = self       # prekresľovať celý blok (ikony sú deti)
        self.spin._timer.timeout.connect(lambda: [ic.update() for ic, _ in self.rows])

    def start(self, first: int = 0):
        self.current = first
        self.failed = False
        self.message.setText("")
        self._apply()
        self.spin.start()
        self.show()

    def set_step(self, step: int, msg: str = ""):
        if step > self.current:
            self.current = step
        if msg:
            self.message.setText("Cisco: " + msg)
        self._apply()
        if self.current >= len(self.rows):
            self.spin.stop()

    def fail(self):
        self.failed = True
        self.spin.stop()
        self._apply()

    def stop(self):
        self.spin.stop()
        self.hide()

    def _apply(self):
        t = T()
        for i, (ic, lb) in enumerate(self.rows):
            if i < self.current or self.current >= len(self.rows):
                ic.state, color, weight = "done", t.ok_text, QFont.Weight.Normal
            elif i == self.current:
                ic.state = "failed" if self.failed else "active"
                color, weight = (t.err_text if self.failed else t.text), DEMI
            else:
                ic.state, color, weight = "pending", t.muted, QFont.Weight.Normal
            lb.setFont(ui_font(14, weight))
            lb.setStyleSheet(f"color: {color};")
            ic.update()
        label = self.rows[min(self.current, len(self.rows) - 1)][1].text()
        self.setAccessibleName(("Zlyhalo: " if self.failed else "") + label)


# ------------------------------------------------------------------ výpis z Cisco CLI

class LogView(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(mono_font(11))
        self.setMaximumBlockCount(2000)
        self.setFixedHeight(140)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setAccessibleName("Priebeh – výpis z Cisco CLI")
        self._line_start = True

    def append_text(self, text: str):
        if not text:
            return
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        out = []
        for ch in text:
            if self._line_start and ch != "\n":
                out.append(datetime.now().strftime("%H:%M:%S  "))
                self._line_start = False
            out.append(ch)
            if ch == "\n":
                self._line_start = True
        cur.insertText("".join(out))
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def clear_log(self):
        self.clear()
        self._line_start = True


# ------------------------------------------------------------------ tlačidlo (plné / sekundárne)

class FlatButton(QPushButton):
    def __init__(self, text: str, primary: bool = True, parent=None):
        super().__init__(text, parent)
        self.primary = primary
        self.lead_icon: Optional[str] = None
        self._busy = False
        self._hover = False
        self.spin = Spinner(self)
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_busy(self, busy: bool):
        self._busy = busy
        (self.spin.start if busy else self.spin.stop)()
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isEnabled() or self._busy
        if self.primary:
            bg = QColor(t.accent if active else t.disabled_bg)
            if active and (self._hover or self.isDown()):
                bg = bg.darker(125 if self.isDown() else 110)
            fg = QColor(t.accent_text if active else t.disabled_text)
            border = bg
        else:
            bg = QColor(t.field_bg if self._hover and self.isEnabled() else t.secondary_bg)
            fg = QColor(t.text if self.isEnabled() else t.disabled_text)
            border = QColor(t.secondary_border)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 8, 8)
        if self.hasFocus():
            p.setPen(QPen(QColor(t.accent_text if self.primary else t.accent), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 6, 6)
        f = ui_font(16, DEMI)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(self.text())
        iw = 28 if (self._busy or self.lead_icon) else 0
        x = (self.width() - tw - iw) / 2
        cy = self.height() / 2
        if self._busy:
            self.spin.draw(p, QRectF(x + 1, cy - 8, 16, 16), fg, 2.5)
        elif self.lead_icon:
            icons.draw(p, self.lead_icon, QRectF(x, cy - 9, 18, 18), fg, 2.0)
        p.setPen(fg)
        p.setFont(f)
        p.drawText(QRectF(x + iw, 0, tw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        p.end()


class LinkButton(QPushButton):
    """Text ako odkaz („▸ Zobraziť priebeh“)."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("link", True)
        self.setFont(ui_font(13))


# ------------------------------------------------------------------ kruh s fajkou

class CheckCircle(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.reconnecting = False
        self.spin = Spinner(self, 20)
        self.setFixedSize(76, 76)

    def set_reconnecting(self, on: bool):
        self.reconnecting = on
        (self.spin.start if on else self.spin.stop)()
        self.update()

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setPen(QPen(QColor(t.warn_border if self.reconnecting else t.ok_border), 2))
        p.setBrush(QColor(t.warn_bg if self.reconnecting else t.ok_bg))
        p.drawEllipse(r)
        s = 36
        inner = QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s)
        if self.reconnecting:
            self.spin.draw(p, inner, QColor(t.warn_icon), 4)
        else:
            icons.draw(p, "check", inner, QColor(t.ok_icon), 2.2)
        p.end()


# ------------------------------------------------------------------ tabuľka údajov

class DetailsTable(QWidget):
    ROW_H = 40

    def __init__(self, labels: list, parent=None):
        super().__init__(parent)
        self.rows = [[l, "–"] for l in labels]
        self.setFixedHeight(self.ROW_H * len(self.rows))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, i: int, value: str):
        if i < len(self.rows) and self.rows[i][1] != value:
            self.rows[i][1] = value or "–"
            self.setAccessibleDescription("; ".join(f"{a}: {b}" for a, b in self.rows))
            self.update()

    def paintEvent(self, e):
        t = T()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(t.field_border), 1))
        p.setBrush(QColor(t.field_bg))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        f, fv = ui_font(14), ui_font(14, DEMI)
        fmv = QFontMetrics(fv)
        for i, (label, value) in enumerate(self.rows):
            y = i * self.ROW_H
            if i:
                p.setPen(QPen(QColor(t.divider), 1))
                p.drawLine(1, y, self.width() - 2, y)
            p.setPen(QColor(t.muted))
            p.setFont(f)
            p.drawText(QRectF(14, y, 140, self.ROW_H), Qt.AlignmentFlag.AlignVCenter, label)
            p.setPen(QColor(t.text))
            p.setFont(fv)
            w = self.width() - 150 - 14
            p.drawText(QRectF(150, y, w, self.ROW_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       fmv.elidedText(value, Qt.TextElideMode.ElideMiddle, int(w)))
        p.end()
