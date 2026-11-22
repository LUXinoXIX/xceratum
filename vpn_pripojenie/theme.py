"""Farby podľa dizajnu v2 (claude/dizajn-okna-v2.md): A – svetlé, B – tmavé, prepínanie podľa systému."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PyQt6.QtCore import Qt


@dataclass(frozen=True)
class Theme:
    is_dark: bool
    window_bg: str
    header_bg: str
    header_text: str
    header_sub: str
    header_line: str
    header_line_w: int
    field_bg: str
    field_border: str
    field_focus: str
    muted: str
    text: str
    accent: str
    accent_text: str
    disabled_bg: str
    disabled_text: str
    toggle_off: str
    err_bg: str
    err_border: str
    err_text: str
    err_icon: str
    ok_bg: str
    ok_border: str
    ok_text: str
    ok_icon: str
    on_ok: str
    info_bg: str
    info_border: str
    info_text: str
    info_icon: str
    warn_bg: str
    warn_border: str
    warn_text: str
    warn_icon: str
    secondary_bg: str
    secondary_border: str
    footer_line: str
    footer_text: str
    divider: str
    menu_bg: str
    menu_hover: str

    def c(self, name: str) -> QColor:
        return QColor(getattr(self, name))


LIGHT = Theme(
    is_dark=False, window_bg="#FFFFFF", header_bg="#1F4A86", header_text="#FFFFFF", header_sub="#D5E0F0",
    header_line="#1F4A86", header_line_w=0, field_bg="#F4F7FB", field_border="#CDD6E3", field_focus="#1F4A86",
    muted="#4F5F75", text="#0F1E33", accent="#1F4A86", accent_text="#FFFFFF", disabled_bg="#E3E8EF",
    disabled_text="#5C6878", toggle_off="#B4BFCD",
    err_bg="#FDF3F4", err_border="#EEACB2", err_text="#8A0B16", err_icon="#B10E1C",
    ok_bg="#F1FAF1", ok_border="#9FD89F", ok_text="#0E5C0D", ok_icon="#0E7A0D", on_ok="#FFFFFF",
    info_bg="#F4F7FB", info_border="#CDD6E3", info_text="#0F1E33", info_icon="#1F4A86",
    warn_bg="#FFF6E5", warn_border="#F2C779", warn_text="#6B4700", warn_icon="#C77700",
    secondary_bg="#FFFFFF", secondary_border="#CDD6E3", footer_line="#EDEDED", footer_text="#5C6878",
    divider="#DFE5EE", menu_bg="#FFFFFF", menu_hover="#EEF2F8",
)

DARK = Theme(
    is_dark=True, window_bg="#102C54", header_bg="#102C54", header_text="#FFFFFF", header_sub="#A9BCD6",
    header_line="#34588C", header_line_w=2, field_bg="#1A3A68", field_border="#34588C", field_focus="#6CC3BD",
    muted="#A9BCD6", text="#FFFFFF", accent="#6CC3BD", accent_text="#0B1F3A", disabled_bg="#23426F",
    disabled_text="#A9BCD6", toggle_off="#4A6894",
    err_bg="#4A1A2C", err_border="#D04462", err_text="#FFD9E0", err_icon="#FF8FA3",
    ok_bg="#12424A", ok_border="#4BA39E", ok_text="#D4F2EF", ok_icon="#6CC3BD", on_ok="#0B1F3A",
    info_bg="#1A3A68", info_border="#34588C", info_text="#FFFFFF", info_icon="#6CC3BD",
    warn_bg="#4A3A14", warn_border="#C9A13B", warn_text="#FFE9B8", warn_icon="#FFC857",
    secondary_bg="#102C54", secondary_border="#34588C", footer_line="#23426F", footer_text="#A9BCD6",
    divider="#2A4C7E", menu_bg="#1A3A68", menu_hover="#23426F",
)

_current: Theme = LIGHT


def current() -> Theme:
    return _current


def system_is_dark() -> bool:
    app = QGuiApplication.instance()
    if app is None:
        return False
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)          # Qt 6.5+
    if scheme is not None:
        try:
            val = scheme()
            if val == Qt.ColorScheme.Dark:
                return True
            if val == Qt.ColorScheme.Light:
                return False
        except (AttributeError, TypeError):
            pass
    return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def resolve(pref: str) -> Theme:
    p = (pref or "").strip().lower()
    if p in ("tmavy", "tmavý", "dark"):
        return DARK
    if p in ("svetly", "svetlý", "light"):
        return LIGHT
    return DARK if system_is_dark() else LIGHT


def set_current(t: Theme) -> None:
    global _current
    _current = t


# ------------------------------------------------------------------ písma

def ui_font(px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(QGuiApplication.font())
    f.setPixelSize(max(8, round(px)))
    f.setWeight(weight)
    return f


def mono_font(px: float) -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    f.setPixelSize(max(8, round(px)))
    return f


# ------------------------------------------------------------------ štýly štandardných prvkov (správca, dialógy)

def stylesheet(t: Theme) -> str:
    return f"""
    QWidget#VpnRoot, QDialog, QTabWidget::pane, QWidget#Page {{ background: {t.window_bg}; color: {t.text}; }}
    QLabel {{ color: {t.text}; background: transparent; }}
    QLabel[muted="true"] {{ color: {t.muted}; }}
    QToolTip {{ background: {t.menu_bg}; color: {t.text}; border: 1px solid {t.field_border}; }}
    QMenu {{ background: {t.menu_bg}; color: {t.text}; border: 1px solid {t.field_border}; padding: 4px; }}
    QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {t.menu_hover}; }}
    QMenu::item:disabled {{ color: {t.muted}; }}
    QMenu::separator {{ height: 1px; background: {t.divider}; margin: 4px 8px; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextBrowser {{
        background: {t.field_bg}; color: {t.text}; border: 1px solid {t.field_border};
        border-radius: 6px; padding: 5px 8px; selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {t.field_focus}; padding: 4px 7px; }}
    QComboBox QAbstractItemView {{ background: {t.menu_bg}; color: {t.text}; selection-background-color: {t.menu_hover}; selection-color: {t.text}; }}
    QPushButton {{ background: {t.secondary_bg}; color: {t.text}; border: 1px solid {t.secondary_border};
        border-radius: 8px; padding: 8px 16px; }}
    QPushButton:hover {{ background: {t.field_bg}; }}
    QPushButton:disabled {{ color: {t.disabled_text}; background: {t.disabled_bg}; border-color: {t.disabled_bg}; }}
    QPushButton[primary="true"] {{ background: {t.accent}; color: {t.accent_text}; border: 1px solid {t.accent}; font-weight: 600; }}
    QPushButton[primary="true"]:disabled {{ background: {t.disabled_bg}; color: {t.disabled_text}; border-color: {t.disabled_bg}; }}
    QCheckBox {{ color: {t.text}; spacing: 8px; }}
    QLineEdit#FieldEdit {{ background: transparent; border: none; padding: 0; color: {t.text}; }}
    QPushButton[link="true"] {{ background: transparent; border: none; color: {t.accent}; padding: 2px 0;
        text-align: left; }}
    QPushButton[link="true"]:hover {{ text-decoration: underline; background: transparent; }}
    QPlainTextEdit#Log {{ font-size: 11px; }}
    QTabBar::tab {{ background: transparent; color: {t.muted}; padding: 10px 16px; border: none;
        border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; font-weight: 600; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {t.divider}; }}
    QTableWidget, QTreeWidget {{ background: {t.window_bg}; alternate-background-color: {t.field_bg}; color: {t.text};
        gridline-color: {t.divider}; border: 1px solid {t.field_border}; border-radius: 8px;
        selection-background-color: {t.menu_hover}; selection-color: {t.text}; }}
    QHeaderView::section {{ background: {t.field_bg}; color: {t.muted}; border: none;
        border-bottom: 1px solid {t.divider}; padding: 6px 8px; font-weight: 600; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {t.field_border}; border-radius: 5px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QGroupBox {{ color: {t.text}; border: 1px solid {t.divider}; border-radius: 8px; margin-top: 14px; padding: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {t.muted}; font-weight: 600; }}
    """
