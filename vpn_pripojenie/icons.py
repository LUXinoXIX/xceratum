"""Ikony kreslené čiarou na mriežke 24 × 24 (ako v návrhu a vo Windows verzii) a ikona aplikácie/lišty."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def shield_path(x: float, y: float, size: float) -> QPainterPath:
    k = size / 24.0
    p = QPainterPath()
    p.moveTo(x + 12 * k, y + 2.5 * k)
    p.lineTo(x + 20 * k, y + 5.5 * k)
    p.lineTo(x + 20 * k, y + 12 * k)
    p.cubicTo(x + 20 * k, y + 17 * k, x + 16.5 * k, y + 20.3 * k, x + 12 * k, y + 21.5 * k)
    p.cubicTo(x + 7.5 * k, y + 20.3 * k, x + 4 * k, y + 17 * k, x + 4 * k, y + 12 * k)
    p.lineTo(x + 4 * k, y + 5.5 * k)
    p.closeSubpath()
    return p


def draw(p: QPainter, name: str, r: QRectF, color: QColor, stroke: float = 1.8) -> None:
    k = min(r.width(), r.height()) / 24.0
    ox = r.x() + (r.width() - 24 * k) / 2
    oy = r.y() + (r.height() - 24 * k) / 2

    def P(x, y):
        return QPointF(ox + x * k, oy + y * k)

    def R(x, y, w, h):
        return QRectF(ox + x * k, oy + y * k, w * k, h * k)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, stroke * k)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def arc_top(rect: QRectF):
        p.drawArc(rect, 0, 180 * 16)

    if name == "shield_lock":
        p.drawPath(shield_path(ox, oy, 24 * k))
        p.drawRoundedRect(R(8.5, 11, 7, 5.5), 1 * k, 1 * k)
        arc_top(R(10, 7.5, 4, 4))
        p.drawLine(P(10, 9.5), P(10, 11))
        p.drawLine(P(14, 9.5), P(14, 11))
    elif name == "shield_check":
        p.drawPath(shield_path(ox, oy, 24 * k))
        p.drawPolyline(QPolygonF([P(9, 12), P(11, 14), P(15, 10)]))
    elif name == "globe":
        p.drawEllipse(R(3, 3, 18, 18))
        p.drawEllipse(R(8.2, 3, 7.6, 18))
        p.drawLine(P(3, 12), P(21, 12))
    elif name == "person":
        p.drawEllipse(R(8, 4, 8, 8))
        arc_top(R(4, 14, 16, 14))
    elif name == "lock":
        p.drawRoundedRect(R(5, 11, 14, 10), 2 * k, 2 * k)
        arc_top(R(8, 3, 8, 8))
        p.drawLine(P(8, 7), P(8, 11))
        p.drawLine(P(16, 7), P(16, 11))
    elif name in ("eye", "eye_off"):
        path = QPainterPath(P(2, 12))
        path.cubicTo(P(5, 6.5), P(19, 6.5), P(22, 12))
        path.cubicTo(P(19, 17.5), P(5, 17.5), P(2, 12))
        p.drawPath(path)
        p.drawEllipse(R(9, 9, 6, 6))
        if name == "eye_off":
            p.drawLine(P(4, 4), P(20, 20))
    elif name == "gear":
        p.drawEllipse(R(9, 9, 6, 6))
        p.drawEllipse(R(5, 5, 14, 14))
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(P(12 + 7 * math.cos(a), 12 + 7 * math.sin(a)), P(12 + 9.6 * math.cos(a), 12 + 9.6 * math.sin(a)))
    elif name == "menu":
        for y in (7, 12, 17):
            p.drawLine(P(5, y), P(19, y))
    elif name == "close":
        p.drawLine(P(7, 7), P(17, 17))
        p.drawLine(P(17, 7), P(7, 17))
    elif name == "minimize":
        p.drawLine(P(7, 16), P(17, 16))
    elif name == "check":
        p.drawPolyline(QPolygonF([P(5, 12.5), P(10, 17), P(19, 7)]))
    elif name == "arrow_down_bar":
        p.drawLine(P(12, 4), P(12, 15))
        p.drawPolyline(QPolygonF([P(7, 10), P(12, 15), P(17, 10)]))
        p.drawLine(P(5, 20), P(19, 20))
    elif name == "chevron":
        p.drawPolyline(QPolygonF([P(6, 9), P(12, 15), P(18, 9)]))
    elif name == "chevron_right":
        p.drawPolyline(QPolygonF([P(9, 6), P(15, 12), P(9, 18)]))
    elif name in ("alert", "info"):
        p.drawEllipse(R(2.5, 2.5, 19, 19))
        p.setBrush(QBrush(color))
        if name == "alert":
            p.drawLine(P(12, 7), P(12, 13))
            p.drawEllipse(R(10.8, 16, 2.4, 2.4))
        else:
            p.drawLine(P(12, 11), P(12, 17))
            p.drawEllipse(R(10.8, 6, 2.4, 2.4))
    elif name == "warning":
        path = QPainterPath(P(12, 3))
        path.lineTo(P(22, 20.5))
        path.lineTo(P(2, 20.5))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(P(12, 9.5), P(12, 14))
        p.setBrush(QBrush(color))
        p.drawEllipse(R(10.9, 16.3, 2.2, 2.2))
    elif name == "certificate":
        p.drawRoundedRect(R(3, 4, 18, 13), 1.5 * k, 1.5 * k)
        p.drawLine(P(7, 8.5), P(17, 8.5))
        p.drawLine(P(7, 12), P(12, 12))
        p.drawEllipse(R(14, 13, 5, 5))
        p.drawPolyline(QPolygonF([P(15, 17.5), P(15, 21), P(16.5, 20), P(18, 21), P(18, 17.5)]))
    p.restore()


def pixmap(name: str, size: int, color: QColor, dpr: float = 1.0, stroke: float = 1.8) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw(p, name, QRectF(0, 0, size, size), color, stroke)
    p.end()
    return pm


# stav: 0 = nepripojené (sivá bodka), 1 = pripojené (zelená), 2 = pripájam / obnovujem (oranžová)
DOT = {0: "#9A9A9A", 1: "#16A314", 2: "#F09A1A"}


def app_pixmap(size: int, state: int = 0, dot: bool = True) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1F4A86"))
    p.drawPath(shield_path(-s * 0.02, 0, s * 1.04))
    # zámka v štíte
    k = s / 24.0
    pen = QPen(QColor("#FFFFFF"), max(1.0, 1.7 * k))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(8.6 * k, 10.8 * k, 6.8 * k, 5.6 * k), 1 * k, 1 * k)
    p.drawArc(QRectF(9.9 * k, 7.2 * k, 4.2 * k, 4.4 * k), 0, 180 * 16)
    if dot:
        d = s * 0.42
        p.setPen(QPen(QColor("#FFFFFF"), max(1.5, s * 0.07)))
        p.setBrush(QColor(DOT.get(state, DOT[0])))
        p.drawEllipse(QRectF(s - d - s * 0.02, s - d - s * 0.02, d, d))
    p.end()
    return pm


def app_icon(state: int = 0, dot: bool = True) -> QIcon:
    icon = QIcon()
    for sz in (16, 22, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(sz, state, dot))
    return icon
