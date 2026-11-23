"""Hlavné okno: Prihlásenie → Pripájam sa → Pripojené (→ Obnovujem spojenie)."""
from __future__ import annotations

import time
from html import escape
from typing import Optional

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QFont, QGuiApplication, QPainter, QPen, QTextCursor
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel,
                             QLayout, QMenu, QMessageBox, QPlainTextEdit, QSystemTrayIcon,
                             QTextBrowser, QVBoxLayout, QWidget)

from . import __version__, certs, icons, system
from . import config as C
from . import theme as TH
from .cisco import STEP_LABELS, CiscoCli, Outcome, Result, Stats, find_cli, format_bytes, format_duration
from .profiles import VpnProfile, build_items, changes, describe, manual_item, merge_hosts, read_xml_hosts
from .tasks import ConnectThread, run_task
from .theme import ui_font
from .widgets import (CheckCircle, DetailsTable, FieldBox, FlatButton, HeaderBar, LinkButton, LogView, Notice,
                      StatusPill, StepsView, Toggle)

W = 440
DEMI = QFont.Weight.DemiBold


class MainWindow(QWidget):
    reload_requested = pyqtSignal()

    def __init__(self, start_hidden: bool = False):
        cfg = C.AdminConfig.load()
        user = C.UserState.load()
        frameless = not user.SystemovyRam and QGuiApplication.platformName() not in ("offscreen", "minimal")
        super().__init__(None, Qt.WindowType.FramelessWindowHint if frameless else Qt.WindowType.Window)
        self.cfg, self.user, self.frameless = cfg, user, frameless
        self._pending_pw = ""
        self._pw_was_keyring = False
        self.setObjectName("VpnRoot")
        self.setWindowTitle(self.cfg.NazovAplikacie)
        self.setWindowIcon(icons.app_icon(0))

        self.cli = CiscoCli(find_cli(self.cfg.VpnCliPath), self.cfg.PouzitPty, self.cfg.ConnectTimeoutSeconds)
        self.cisco_version = ""
        self.items: list[VpnProfile] = []
        self.selected: Optional[VpnProfile] = None
        self.connected_profile: Optional[VpnProfile] = None
        self.connected_user = ""
        self.connected = False
        self.reconnecting = False
        self.connecting = False
        self.busy = False
        self.exiting = False
        self.pending_reload = False
        self.client_certs: list = []          # osobné certifikáty (PEM) pri poslednom načítaní
        self.firefox_certs = None             # osobné certifikáty vo Firefoxe; None = nedá sa zistiť
        self._cert_notified = False
        self.connected_since = 0.0
        self.countdown_left = 0
        self.worker: Optional[ConnectThread] = None
        self.password_from_keyring = False
        self.polling = False
        self.notified_hidden = False
        self.manager = None
        self._start_hidden = start_hidden

        self._build()
        self._build_tray()
        self.apply_theme()
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self.apply_theme())

        self.sec_timer = QTimer(self)
        self.sec_timer.setInterval(1000)
        self.sec_timer.timeout.connect(self._tick)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(15000)
        self.poll_timer.timeout.connect(self._poll)
        self.cd_timer = QTimer(self)
        self.cd_timer.setInterval(1000)
        self.cd_timer.timeout.connect(self._countdown_tick)

        QTimer.singleShot(0, self._startup)

    # ================================================================== stavba okna

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        self.header = HeaderBar(self.frameless)
        self.header.setFixedWidth(W)
        self.header.set_texts(title=self.cfg.NazovAplikacie, caption="Pripojenie k", profile="")
        self.header.btn_menu.clicked.connect(self._show_main_menu)
        self.header.btn_min.clicked.connect(self.showMinimized)
        self.header.btn_close.clicked.connect(self.close)
        root.addWidget(self.header)

        # ---------- prihlásenie
        self.login = QWidget()
        self.login.setObjectName("Page")
        self.login.setFixedWidth(W)
        lay = QVBoxLayout(self.login)
        lay.setContentsMargins(28, 18, 28, 16)
        lay.setSpacing(12)

        self.pill = StatusPill()
        lay.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignLeft)

        self.f_profile = FieldBox("globe", "Pripojenie (profil)", dropdown=True)
        self.f_profile.set_value("Načítavam pripojenia…")
        self.f_profile.clicked.connect(self._show_profile_menu)
        self.f_user = FieldBox("person", "Používateľ")
        self.f_user.edit.textChanged.connect(self._on_user_changed)
        self.f_pw = FieldBox("lock", "Heslo", password=True)
        self.f_pw.edit.textChanged.connect(self._on_pw_changed)
        self.f_code = FieldBox("shield_check", "Kód z autentifikátora", mono=True)
        self.f_code.edit.setMaxLength(12)        # dovolí vložiť aj „123 456“; ponechá sa 6 číslic
        self.f_code.edit.textChanged.connect(self._on_code_changed)
        self.code_hint = QLabel("6 číslic z aplikácie Authenticator, mení sa každých 30 s.")
        self.code_hint.setFont(ui_font(12))
        self.code_hint.setProperty("muted", True)
        for w in (self.f_profile, self.f_user, self.f_pw, self.f_code):
            lay.addWidget(w)
        lay.addWidget(self.code_hint)
        lay.setSpacing(10)

        self.t_remember = Toggle("Zapamätať si meno")
        self.t_remember.setChecked(self.user.Zapamatat)
        self.t_keyring = Toggle("Uložiť heslo v kľúčenke")
        self.t_keyring.setChecked(self.user.UlozitHeslo)
        self.t_keyring.toggled.connect(self._on_keyring_toggled)
        lay.addWidget(self.t_remember, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.t_keyring, 0, Qt.AlignmentFlag.AlignLeft)

        self.steps = StepsView(STEP_LABELS)
        self.steps.hide()
        lay.addWidget(self.steps)
        self.notice = Notice()
        lay.addWidget(self.notice)
        lay.addSpacing(6)

        self.btn_connect = FlatButton("Pripojiť", primary=True)
        self.btn_connect.clicked.connect(self._on_connect_clicked)
        lay.addWidget(self.btn_connect)
        self.lnk_log = LinkButton("▸ Zobraziť priebeh")
        self.lnk_log.clicked.connect(self._toggle_log)
        lay.addWidget(self.lnk_log, 0, Qt.AlignmentFlag.AlignLeft)
        self.log = LogView()
        self.log.setObjectName("Log")
        self.log.hide()
        lay.addWidget(self.log)
        root.addWidget(self.login)

        # ---------- pripojené
        self.conn = QWidget()
        self.conn.setObjectName("Page")
        self.conn.setFixedWidth(W)
        cl = QVBoxLayout(self.conn)
        cl.setContentsMargins(28, 18, 28, 16)
        cl.setSpacing(10)
        self.pill2 = StatusPill()
        cl.addWidget(self.pill2, 0, Qt.AlignmentFlag.AlignHCenter)
        self.badge = CheckCircle()
        cl.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignHCenter)
        self.conn_title = QLabel("Pripojené")
        self.conn_title.setFont(ui_font(24, DEMI))
        self.conn_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cl.addWidget(self.conn_title)
        self.conn_text = QLabel()
        self.conn_text.setFont(ui_font(14))
        self.conn_text.setProperty("muted", True)
        self.conn_text.setWordWrap(True)
        self.conn_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cl.addWidget(self.conn_text)
        self.details = DetailsTable(["Pripojenie", "Server", "Používateľ", "Pridelená IP", "Pripojené", "Prenesené"])
        cl.addWidget(self.details)
        self.lnk_more = LinkButton("▸ Podrobnosti (protokol, trasy)")
        self.lnk_more.clicked.connect(self._toggle_more)
        cl.addWidget(self.lnk_more, 0, Qt.AlignmentFlag.AlignLeft)
        self.more = QLabel()
        self.more.setFont(ui_font(12))
        self.more.setWordWrap(True)
        self.more.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.more.hide()
        cl.addWidget(self.more)
        self.conn_notice = Notice()
        cl.addWidget(self.conn_notice)
        cl.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.btn_hide = FlatButton("Skryť do lišty", primary=True)
        self.btn_hide.lead_icon = "arrow_down_bar"
        self.btn_hide.clicked.connect(self.hide_to_tray)
        self.btn_disconnect = FlatButton("Odpojiť", primary=False)
        self.btn_disconnect.clicked.connect(self.do_disconnect)
        row.addWidget(self.btn_hide)
        row.addWidget(self.btn_disconnect)
        cl.addLayout(row)
        cdrow = QHBoxLayout()
        self.cd_label = QLabel()
        self.cd_label.setFont(ui_font(12))
        self.cd_label.setProperty("muted", True)
        self.cd_keep = LinkButton("Nechať otvorené")
        self.cd_keep.setFont(ui_font(12))
        self.cd_keep.clicked.connect(lambda: self._stop_countdown(hide=False))
        cdrow.addStretch(1)
        cdrow.addWidget(self.cd_label)
        cdrow.addWidget(self.cd_keep)
        cdrow.addStretch(1)
        self.cd_label.hide()
        self.cd_keep.hide()
        cl.addLayout(cdrow)
        self.conn.hide()
        root.addWidget(self.conn)

        # ---------- päta
        self.footer = QWidget()
        self.footer.setObjectName("Footer")
        self.footer.setFixedSize(W, 36)
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(28, 0, 28, 0)
        self.footer_label = QLabel("Cisco Secure Client")
        self.footer_label.setFont(ui_font(11))
        self.lnk_help = LinkButton("Pomoc")
        self.lnk_help.setFont(ui_font(11))
        self.lnk_help.clicked.connect(self._show_help)
        fl.addWidget(self.footer_label, 1)
        fl.addWidget(self.lnk_help)
        root.addWidget(self.footer)

        self.f_user.edit.returnPressed.connect(self._on_connect_clicked)
        self.f_pw.edit.returnPressed.connect(self._on_connect_clicked)
        self.f_code.edit.returnPressed.connect(self._on_connect_clicked)
        self._layout_fields()

    def _build_tray(self):
        self.tray: Optional[QSystemTrayIcon] = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icons.app_icon(0), self)
        m = QMenu()
        self.mi_status = QAction("Nepripojené", m)
        self.mi_status.setEnabled(False)
        mi_open = QAction("Otvoriť okno", m)
        f = mi_open.font()
        f.setBold(True)
        mi_open.setFont(f)
        mi_open.triggered.connect(self.show_from_tray)
        self.mi_disconnect = QAction("Odpojiť", m)
        self.mi_disconnect.setEnabled(False)
        self.mi_disconnect.triggered.connect(self.do_disconnect)
        mi_exit = QAction("Ukončiť", m)
        mi_exit.triggered.connect(self.request_exit)
        m.addAction(self.mi_status)
        m.addSeparator()
        m.addAction(mi_open)
        m.addAction(self.mi_disconnect)
        m.addSeparator()
        m.addAction(mi_exit)
        self._tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_activated)
        self.tray.setToolTip(f"{self.cfg.NazovAplikacie} – nepripojené")
        self.tray.show()

    def _wait_for_tray(self, tries: int):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._build_tray()
            if self.tray and self.connected:
                self._set_tray_state(2 if self.reconnecting else 1, "pripojené")
            return
        if tries <= 0:
            self.show()                 # lišta nie je (napr. GNOME bez rozšírenia) – ukázať okno
            return
        QTimer.singleShot(1000, lambda: self._wait_for_tray(tries - 1))

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide_to_tray()
            else:
                self.show_from_tray()

    # ================================================================== vzhľad

    def apply_theme(self):
        pref = self.user.Vzhlad or self.cfg.Vzhlad
        t = TH.resolve(pref)
        TH.set_current(t)
        app = QApplication.instance()
        app.setStyleSheet(TH.stylesheet(t) + f"""
            QWidget#Footer {{ background: {t.window_bg}; border-top: 1px solid {t.footer_line}; }}
            QWidget#Footer QLabel {{ color: {t.footer_text}; }}
        """)
        self.notice.refresh_theme()
        self.conn_notice.refresh_theme()
        self.steps._apply()
        if self.selected:
            self.f_profile.set_value(self.selected.name, self._profile_extra(self.selected))
        for w in self.findChildren(QWidget):
            w.update()
        self.update()

    def paintEvent(self, e):
        t = TH.current()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(t.window_bg))
        if self.frameless:
            p.setPen(QPen(QColor(t.field_border if not t.is_dark else t.header_line), 1))
            p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()

    # ================================================================== štart

    def _startup(self):
        if not self._start_hidden:
            self.show()
        elif not self.tray:
            self._wait_for_tray(10)     # po prihlásení môže lišta naskočiť o chvíľu neskôr
        if not self.cli.available:
            self.pill.set_state("error", "Cisco Secure Client chýba")
            self.footer_label.setText("Cisco Secure Client nenájdený")
            self.notice.show_msg("error", "Nenašiel sa Cisco Secure Client (/opt/cisco/secureclient/bin/vpn). "
                                          "Nainštalujte ho alebo nastavte cestu v ≡ → Profily a certifikáty.")
            self._update_connect_enabled()
            return
        self.load_items(check_state=True)

    def load_items(self, check_state: bool = False):
        self.busy = True
        self.pill.set_state("check")
        self.btn_connect.setText("Načítavam…")
        self._update_connect_enabled()
        cli = self.cli

        def work():
            res = {"version": cli.version(), "agent": system.agent_running()}
            names = cli.hosts() if res["agent"] else []
            res["hosts"] = merge_hosts(names, read_xml_hosts())
            if system.mode() == "vpnpripojenie":
                res["gui_disabled"] = system.disable_cisco_gui()
            if check_state and res["agent"]:
                res["stats"] = cli.stats()
            res["clients"] = certs.list_client()
            res["cas"] = certs.list_ca()
            res["firefox"] = certs.firefox_user_certs()
            return res

        run_task(self, work, self._items_loaded)

    def _items_loaded(self, res):
        self.busy = False
        self.btn_connect.setText("Pripojiť")
        if isinstance(res, Exception):
            self.notice.show_msg("error", "Načítanie pripojení zlyhalo.", str(res))
            res = {"hosts": [], "agent": False, "version": ""}
        self.cisco_version = res.get("version", "")
        agent = res.get("agent", False)
        self.footer_label.setText(f"Cisco Secure Client {self.cisco_version}".strip() +
                                  (" · služba beží" if agent else " · služba nebeží"))
        self.items = build_items(self.cfg, res.get("hosts", []))
        self.client_certs = res.get("clients", [])
        self.firefox_certs = res.get("firefox")
        news = self._news(res, agent)
        vis = self.visible_items()
        sel = next((p for p in vis if p.key.lower() == self.user.PoslednaPolozka.lower()), None)
        sel = sel or next((p for p in vis if p.host_name.lower() == self.user.PosledneCisco.lower()), None)
        sel = sel or next((p for p in vis if p.is_default), None)
        sel = sel or (vis[0] if vis else None)
        self.selected = sel
        self._apply_selection()
        if not agent:
            self.pill.set_state("error", "Služba Cisca nebeží")
            self.notice.show_msg("error", "Služba Cisca (vpnagentd) nebeží, pripojiť sa nedá. "
                                          "Spustite ju v ≡ → Profily a certifikáty → Diagnostika alebo reštartujte počítač.")
        elif not vis:
            self.pill.set_state("off")
            self.notice.show_msg("error", "Nenašlo sa žiadne VPN pripojenie. Pridajte XML profil "
                                          "v ≡ → Profily a certifikáty.")
        else:
            self.pill.set_state("off")
            if news:
                kind = "error" if any(k == "error" for k, _ in news) else \
                    ("warn" if any(k == "warn" for k, _ in news) else "info")
                self.notice.show_msg(kind, "\n".join(t for _, t in news))
        st: Optional[Stats] = res.get("stats")
        if st and st.state in ("Connected", "Reconnecting"):
            self._on_connected(self.selected, self.user.Meno if self.user.Zapamatat else "", st, countdown=False)
            if st.state == "Reconnecting":
                self._set_reconnecting(True)
        elif self.pending_reload:
            self.pending_reload = False
        self._update_connect_enabled()
        self._focus_first_empty()

    def _news(self, res: dict, agent: bool) -> list:
        """Čo sa zmenilo od minula – pripojenia z Cisca a certifikáty, ktoré vypršia. list[(druh, text)]."""
        out = []
        if agent:
            now = [h.host_name for h in res.get("hosts", [])]
            before = list(self.user.ZnamePripojenia)
            if before:
                added, removed = changes(before, now)
                if added:
                    out.append(("info", "Pribudlo pripojenie: " + ", ".join(added) + "."))
                if removed:
                    out.append(("warn", "Ubudlo pripojenie: " + ", ".join(removed) +
                                " (profil bol odstránený alebo zmenený)."))
            if now != before:
                self.user.ZnamePripojenia = now
                self.user.save()
        warns = certs.expiry_warnings(self.cfg.DniUpozorneniaCertifikat, res.get("clients", []), res.get("cas", []))
        out.extend(warns)
        if warns and not getattr(self, "_cert_notified", False):
            self._cert_notified = True           # notifikácia raz za spustenie
            self._notify("Certifikát VPN", warns[0][1])
        return out

    def _cert_choice(self) -> tuple:
        """(použiteľné osobné certifikáty, text pre okno) pre pripojenie s prihlásením certifikátom."""
        clients = getattr(self, "client_certs", [])
        usable = [c for c in clients if c.usable]
        if usable:
            c = usable[0]
            more = f" (nainštalovaných {len(usable)}, Cisco vyberie podľa servera)" if len(usable) > 1 else ""
            return usable, (f"Toto pripojenie overí váš osobný certifikát {c.cn} (platný do {c.valid_to}){more}. "
                            "Nič nezadávate, stačí Pripojiť.")
        ff = getattr(self, "firefox_certs", None)
        expired = [c for c in clients if c.expired]
        why = (f"Váš certifikát {expired[0].cn} vypršal {expired[0].valid_to}." if expired else
               "Osobný certifikát nie je nainštalovaný." if not clients else
               "Nainštalovanému certifikátu chýba súkromný kľúč.")
        if ff:
            return [], (why + " Cisco skúsi certifikát z Firefoxu (" + ", ".join(ff) + ").")
        return [], (why + " Importujte súbor .p12 v ≡ → Profily a certifikáty → Certifikáty.")

    def visible_items(self) -> list:
        return [p for p in self.items if not p.hidden and not p.missing]

    # ================================================================== výber pripojenia a polia

    @staticmethod
    def _profile_extra(p: VpnProfile) -> str:
        if p.manual:
            return "ručne zadaná adresa"
        return p.address or (p.host_name if p.host_name != p.name else "")

    def _apply_selection(self):
        p = self.selected
        if p:
            self.f_profile.set_value(p.name, self._profile_extra(p))
            if not self.f_user.edit.text():
                if p.preset_user:
                    self.f_user.edit.setText(p.preset_user)
                elif self.user.Zapamatat and self.user.Meno:
                    self.f_user.edit.setText(self.user.Meno)
        else:
            self.f_profile.set_value("–")
        if p:
            self.f_profile.setToolTip(describe(p))
        if p and p.auth.value == "Certifikat" and (self.notice.isHidden() or self.notice.kind == "info"):
            usable, text = self._cert_choice()
            self.notice.show_msg("info" if usable else "warn", text)
        elif p and p.manual:
            self.notice.show_msg("warn", "Pri ručne zadanej adrese Cisco nepoužije nastavenia profilu "
                                         "(napr. protokol IPsec). Ak to ide, vyberte pripojenie z roletky.")
        elif not self.notice.isHidden() and self.notice.kind in ("info", "warn") and not self.connecting:
            self.notice.hide()
        self._layout_fields()
        self._fill_keyring_password()
        self._set_header()
        self._update_connect_enabled()

    def _layout_fields(self):
        p = self.selected
        self.f_profile.setVisible(len(self.visible_items()) > 1 or (p is not None and p.manual) or not self.items)
        learned = bool(p and self.user.needs_user(p.host_name))
        show_user = p is None or p.needs_user(learned)
        show_pw = p is None or p.needs_password
        second = bool(p and p.needs_second)
        show_code = p is None or p.needs_code or second
        self.f_user.setVisible(show_user)
        self.f_pw.setVisible(show_pw)
        self.f_code.setVisible(show_code)
        self.f_code.set_caption("Druhé heslo / kód" if second else "Kód z autentifikátora")
        self.f_code.edit.setMaxLength(128 if second else 12)
        self.f_code.set_password_mode(second)
        self.f_code.edit.setFont(ui_font(16) if second else TH.mono_font(18))
        self.code_hint.setVisible(show_code and not second and self.steps.isHidden())
        self.t_remember.setVisible(show_user)
        allow_kr = self.cfg.PovolitKlucenku and system.keyring_available() and show_pw
        self.t_keyring.setVisible(allow_kr)

    def _set_header(self):
        if self.connected:
            cap = "Obnovujem spojenie k" if self.reconnecting else "Pripojené k"
            name = self.connected_profile.name if self.connected_profile else ""
        else:
            cap = "Pripájam sa k" if self.connecting else "Pripojenie k"
            name = self.selected.name if self.selected else ""
        self.header.set_texts(title=self.cfg.NazovAplikacie, caption=cap, profile=name)

    def _show_profile_menu(self):
        if self.busy or self.connecting or self.connected:
            return
        m = QMenu(self)
        m.setMinimumWidth(self.f_profile.width())
        for p in self.visible_items():
            extra = self._profile_extra(p)
            a = QAction(p.name + (f"\t{extra} · {p.auth.label}" if extra else f"\t{p.auth.label}"), m)
            a.setCheckable(True)
            a.setChecked(p is self.selected)
            a.setToolTip(describe(p))
            a.triggered.connect(lambda _=False, prof=p: self._select(prof))
            m.addAction(a)
        m.setToolTipsVisible(True)
        manual = [p for p in self.items if p.manual]
        for p in manual:
            a = QAction(f"{p.name}\tručne zadaná adresa", m)
            a.setCheckable(True)
            a.setChecked(p is self.selected)
            a.triggered.connect(lambda _=False, prof=p: self._select(prof))
            m.addAction(a)
        m.addSeparator()
        other = QAction("Iná adresa servera…", m)
        other.triggered.connect(self._enter_manual_address)
        m.addAction(other)
        m.exec(self.f_profile.mapToGlobal(QPoint(0, self.f_profile.height() + 4)))

    def _select(self, prof: VpnProfile):
        self.selected = prof
        self.user.PoslednaPolozka = prof.key
        self.user.save()
        self.notice.hide()
        self.steps.stop()
        self.f_pw.edit.clear()
        self.f_code.edit.clear()
        if prof.preset_user:
            self.f_user.edit.setText(prof.preset_user)
        self._apply_selection()
        self._focus_first_empty()

    def _enter_manual_address(self):
        addr, ok = QInputDialog.getText(self, "Iná adresa servera",
                                        "Adresa VPN servera (napr. vpn.firma.sk).\n"
                                        "Odporúčame vybrať pripojenie z roletky – pri ručnej adrese\n"
                                        "Cisco nepoužije nastavenia profilu.")
        addr = (addr or "").strip()
        if not ok or not addr:
            return
        if any(c.isspace() for c in addr) or len(addr) > 200:
            QMessageBox.warning(self, self.cfg.NazovAplikacie, "Adresa nesmie obsahovať medzery.")
            return
        item = next((p for p in self.items if p.manual and p.host_name == addr), None)
        if not item:
            item = manual_item(addr, self.cfg)
            self.items.append(item)
        self._select(item)

    def _on_user_changed(self, _=None):
        self._fill_keyring_password()
        self._update_connect_enabled()

    def _on_pw_changed(self, _=None):
        if self.password_from_keyring and self.f_pw.edit.text() == "":
            self.password_from_keyring = False
            self.f_pw.set_caption("Heslo")
        self._hide_failed_steps()
        self._update_connect_enabled()

    def _on_code_changed(self, text: str):
        p = self.selected
        if p and p.needs_code:
            clean = "".join(ch for ch in text if ch.isdigit())[:6]
            if clean != text:
                pos = len(clean)
                self.f_code.edit.setText(clean)
                self.f_code.edit.setCursorPosition(pos)
        self._hide_failed_steps()
        self._update_connect_enabled()

    def _on_keyring_toggled(self, on: bool):
        self.user.UlozitHeslo = on
        self.user.save()
        if not on and self.selected:
            system.keyring_clear(self.selected.host_name, self.f_user.edit.text().strip())
            if self.password_from_keyring:
                self.f_pw.edit.clear()

    def _fill_keyring_password(self):
        p = self.selected
        if not (p and p.needs_password and self.cfg.PovolitKlucenku and self.user.UlozitHeslo):
            return
        u = self.f_user.edit.text().strip() if not self.f_user.isHidden() else ""
        if self.f_pw.edit.text() and not self.password_from_keyring:
            return
        host = p.host_name

        def work():
            return system.keyring_get(host, u)

        def done(pw):
            if isinstance(pw, str) and pw and self.selected is p and not self.connecting:
                self.f_pw.edit.setText(pw)
                self.password_from_keyring = True
                self.f_pw.set_caption("Heslo · z kľúčenky")
                self._focus_first_empty()

        run_task(self, work, done)

    def _inputs_valid(self) -> bool:
        p = self.selected
        if not p:
            return False
        if not self.f_user.isHidden() and not self.f_user.edit.text().strip():
            return False
        if not self.f_pw.isHidden() and not self.f_pw.edit.text():
            return False
        if p.needs_code and len(self.f_code.edit.text()) != 6:
            return False
        if p.needs_second and not self.f_code.edit.text():
            return False
        return True

    def _update_connect_enabled(self):
        if self.connecting:
            self.btn_connect.setEnabled(not (self.worker and self.worker.cancelling))
            return
        self.btn_connect.setEnabled(not self.busy and self.cli.available and self._inputs_valid())

    def _focus_first_empty(self):
        if self.login.isHidden() or not self.isVisible():
            return
        for f in (self.f_user, self.f_pw, self.f_code):
            if not f.isHidden() and not f.edit.text():
                f.edit.setFocus()
                return
        self.btn_connect.setFocus()

    def _hide_failed_steps(self):
        if not self.connecting and not self.steps.isHidden() and self.steps.failed:
            self.steps.stop()
            self.code_hint.setVisible(not self.f_code.isHidden() and not (self.selected and self.selected.needs_second))

    def _toggle_log(self):
        vis = self.log.isHidden()
        self.log.setVisible(vis)
        self.lnk_log.setText(("▾ Skryť priebeh" if vis else "▸ Zobraziť priebeh"))

    def _toggle_more(self):
        vis = self.more.isHidden()
        self.more.setVisible(vis)
        self.lnk_more.setText(("▾ Skryť podrobnosti" if vis else "▸ Podrobnosti (protokol, trasy)"))

    # ================================================================== pripojenie

    def _on_connect_clicked(self):
        if self.connecting:
            if self.worker:
                self.worker.cancel()
                self.btn_connect.setText("Ruším…")
                self._update_connect_enabled()
            return
        self.do_connect()

    def do_connect(self):
        if self.busy or not self._inputs_valid() or not self.cli.available or not self.selected:
            return
        prof = self.selected
        cert_line = ""
        if prof.auth.value == "Certifikat":
            usable, text = self._cert_choice()
            if not usable and self.firefox_certs == []:
                # bez certifikátu Cisco aj tak zlyhá – povedať to hneď a poslať na import
                self.pill.set_state("off")
                self.notice.show_msg("error", text)
                return
            cert_line = (f"Osobný certifikát: {usable[0].cn}, platný do {usable[0].valid_to}" if usable else
                         "Osobný certifikát: hľadá sa vo Firefoxe")
        user = self.f_user.edit.text().strip() if not self.f_user.isHidden() else ""
        pw = self.f_pw.edit.text() if prof.needs_password else ""
        code = self.f_code.edit.text()
        password = pw + (code if prof.needs_code else "")       # heslo + kód spolu, ako v Cisco okne
        second = code if prof.needs_second else ""
        self._pending_pw = pw if (not self.t_keyring.isHidden() and self.t_keyring.isChecked()) else ""
        self._pw_was_keyring = self.password_from_keyring

        # zapamätať meno (heslo nikdy)
        self.user.Zapamatat = self.t_remember.isChecked()
        if not self.user.Zapamatat:
            self.user.Meno = ""
        elif user:
            self.user.Meno = user
        self.user.PoslednaPolozka = prof.key
        self.user.PosledneCisco = prof.host_name
        self.user.save()

        # heslo a kód sa po pokuse z polí vymažú (heslo z kľúčenky ostáva)
        if not self.password_from_keyring:
            self.f_pw.edit.clear()
        self.f_code.edit.clear()

        self.connecting = True
        self.notice.hide()
        self.code_hint.hide()
        self.log.clear_log()
        if cert_line:
            self.log.append_text(cert_line + "\n")
        self._set_inputs_enabled(False)
        self.btn_connect.setText("Pripájam…  (kliknutím zrušíte)")
        self.btn_connect.set_busy(True)
        self.pill.set_state("busy", f"Pripájam sa k {prof.name}…")
        self.steps.start(0)
        self._set_header()
        self._update_connect_enabled()
        self._set_tray_state(2, f"pripájam sa k {prof.name}…")

        def check_agent():
            return system.agent_running()

        def agent_checked(ok):
            if not self.connecting:
                return
            if ok is not True:
                self._finish_connect_ui()
                self.steps.fail()
                self.pill.set_state("error", "Služba Cisca nebeží")
                self.notice.show_msg("error", "Služba Cisca (vpnagentd) nebeží. Spustite ju v ≡ → Profily a "
                                              "certifikáty → Diagnostika alebo reštartujte počítač.")
                self._set_tray_state(0, "nepripojené")
                return
            self.steps.set_step(1)
            self.worker = ConnectThread(self.cli, prof, user, password, second, self.cfg.AutoPrijatBanner, self)
            self.worker.progress.connect(self._on_progress)
            self.worker.output.connect(self.log.append_text)
            self.worker.ask.connect(self._on_ask)
            self.worker.done.connect(lambda out, pr=prof, u=user: self._on_connect_done(out, pr, u))
            self.worker.finished.connect(self.worker.deleteLater)
            self.worker.start()

        run_task(self, check_agent, agent_checked)

    def _on_progress(self, step: int, msg: str):
        if self.connecting:
            self.steps.set_step(min(step, 4), msg)

    def _on_ask(self, kind: str, text: str):
        if not self.worker:
            return
        if self.isHidden():
            self.show_from_tray()
        if kind == "banner":
            dlg = BannerDialog(self, text)
            ans = dlg.exec() == QDialog.DialogCode.Accepted
        else:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Nedôveryhodný server")
            box.setText("<b>Server VPN sa nedá overiť.</b><br>Môže ísť o podvrhnutý server. "
                        "Pripájajte sa len vtedy, ak vám to potvrdil správca.")
            box.setDetailedText(text)
            no = box.addButton("Nepripájať", QMessageBox.ButtonRole.RejectRole)
            ca = box.addButton("Importovať CA certifikát…", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Pripojiť aj tak", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(no)
            box.exec()
            clicked = box.clickedButton()
            ans = clicked is not no and clicked is not ca
            if clicked is ca:
                QTimer.singleShot(0, lambda: self.open_manager(1))
        if self.worker:
            self.worker.answer(ans)

    def _finish_connect_ui(self):
        self.connecting = False
        self.worker = None
        self.btn_connect.set_busy(False)
        self.btn_connect.setText("Pripojiť")
        self._set_inputs_enabled(True)
        self._set_header()
        self._update_connect_enabled()

    def _on_connect_done(self, out: Outcome, prof: VpnProfile, user: str):
        self._finish_connect_ui()
        r = out.result
        if r == Result.CONNECTED:
            self.steps.set_step(4)
            if self._pending_pw:
                system.keyring_set(prof.host_name, user, self._pending_pw)
            self._pending_pw = ""
            run_task(self, self.cli.stats, lambda st, pr=prof, u=user: self._on_connected(
                pr, u, st if isinstance(st, Stats) else Stats(), countdown=True))
            return
        self._pending_pw = ""
        self.pill.set_state("off")
        self._set_tray_state(0, "nepripojené")
        if r == Result.LOGIN_FAILED:
            self.steps.current = max(self.steps.current, 2)
            self.steps.fail()
            if self._pw_was_keyring:
                system.keyring_clear(prof.host_name, user)
                self.f_pw.edit.clear()
            msg = ("Prihlásenie zlyhalo. Skontrolujte heslo a zadajte nový kód z aplikácie."
                   if prof.needs_code else "Prihlásenie zlyhalo. Skontrolujte prihlasovacie údaje.")
            self.notice.show_msg("error", msg, out.original)
            if not self.f_pw.isHidden():
                self.f_pw.edit.setFocus()
        elif r == Result.NEED_USER:
            self.steps.stop()
            self.user.learn_needs_user(prof.host_name)
            self._layout_fields()
            self.notice.show_msg("info", "Toto pripojenie si pýta aj používateľské meno. Doplňte ho a pripojte "
                                         "sa znova – nabudúce už bude pole zobrazené.")
            self.f_user.edit.setFocus()
        elif r == Result.CANCELLED:
            self.steps.stop()
            self.notice.show_msg("info", "Pripájanie bolo zrušené.")
        elif r == Result.DECLINED:
            self.steps.fail()
            self.notice.show_msg("warn", out.error, out.original)
        else:
            self.steps.fail()
            self.notice.show_msg("error", out.error or "Pripojenie sa nepodarilo.", out.original)
        self.code_hint.setVisible(False)
        if self.pending_reload:
            self._reload_now()
        if r not in (Result.LOGIN_FAILED, Result.NEED_USER):
            self._focus_first_empty()

    def _set_inputs_enabled(self, on: bool):
        for w in (self.f_profile, self.f_user, self.f_pw, self.f_code, self.t_remember, self.t_keyring):
            w.setEnabled(on)

    # ================================================================== pripojené

    def _on_connected(self, prof: Optional[VpnProfile], user: str, st: Stats, countdown: bool):
        self.connected = True
        self.reconnecting = False
        self.connected_profile = prof
        self.connected_user = user
        self.connected_since = time.time() - (st.duration or 0)
        name = prof.name if prof else "VPN"
        self.details.set(0, name)
        self.details.set(1, (prof.address if prof and prof.address else "") or st.server or
                         (prof.host_name if prof else "–"))
        self.details.set(2, user or "–")
        self._update_stats(st)
        self.conn_title.setText("Pripojené")
        self.conn_text.setText(f"Ste pripojený/á cez {name}. Okno môžete zavrieť, VPN beží ďalej v pozadí.")
        self.badge.set_reconnecting(False)
        self.pill.set_state("on")
        self.pill2.set_state("on", f"Pripojené k {name}")
        self.conn_notice.hide()
        self.login.hide()
        self.conn.show()
        self.btn_hide.setVisible(self.tray is not None)
        self.btn_hide.setText("Skryť do lišty" if self.tray else "Minimalizovať")
        self.btn_disconnect.setEnabled(True)
        self.btn_disconnect.setText("Odpojiť")
        self._set_header()
        self._set_tray_state(1, f"pripojené: {name}")
        if self.tray:
            self.mi_disconnect.setEnabled(True)
        self.setWindowIcon(icons.app_icon(1))
        self.sec_timer.start()
        self.poll_timer.setInterval(15000)
        self.poll_timer.start()
        self._tick()
        if countdown and self.tray and self.cfg.SkrytPoSekundach >= 0:
            if self.cfg.SkrytPoSekundach == 0:
                self.hide_to_tray()
            else:
                self.countdown_left = self.cfg.SkrytPoSekundach
                self._countdown_tick(first=True)
                self.cd_timer.start()
        elif countdown:
            system.notify(f"Pripojené: {name}", "VPN je pripojená.")

    def _update_stats(self, st: Stats):
        ip = st.client_ip or st.client_ipv6
        if ip:
            self.details.set(3, ip)
        if st.bytes_sent is not None or st.bytes_received is not None:
            self.details.set(5, f"↑ {format_bytes(st.bytes_sent)}   ↓ {format_bytes(st.bytes_received)}")
        rows = []
        for label, val in (("Protokol", st.protocol), ("Šifrovanie", st.cipher), ("Režim tunela", st.tunnel_mode),
                           ("Adresa servera", st.server), ("IPv6", st.client_ipv6)):
            if val:
                rows.append(f"<b>{escape(label)}:</b> {escape(val)}")
        if st.routes:
            shown = st.routes[:12]
            rows.append("<b>Zabezpečené trasy:</b> " + escape(", ".join(shown)) +
                        (f" … (+{len(st.routes) - 12})" if len(st.routes) > 12 else ""))
        self.more.setText("<br>".join(rows) if rows else "Cisco neposlalo podrobnosti.")

    def _tick(self):
        if not self.connected:
            return
        s = format_duration(time.time() - self.connected_since)
        self.details.set(4, s)
        if self.tray:
            self.mi_status.setText("Obnovujem spojenie…" if self.reconnecting else f"Pripojené · {s}")

    def _countdown_tick(self, first: bool = False):
        if not first:
            self.countdown_left -= 1
        if self.countdown_left <= 0:
            self._stop_countdown(hide=True)
            return
        self.cd_label.setText(f"Skryjem do lišty o {self.countdown_left} s…")
        self.cd_label.show()
        self.cd_keep.show()

    def _stop_countdown(self, hide: bool):
        self.cd_timer.stop()
        self.cd_label.hide()
        self.cd_keep.hide()
        if hide and self.connected:
            self.hide_to_tray()

    def _poll(self):
        if self.polling or not self.connected or self.busy or self.connecting:
            return
        self.polling = True
        run_task(self, self.cli.stats, self._polled)

    def _polled(self, st):
        self.polling = False
        if not self.connected or not isinstance(st, Stats):
            return
        state = st.state or "Unknown"
        if state == "Disconnected":
            self._dropped()
            return
        if state in ("Reconnecting", "Connecting"):
            if not self.reconnecting:
                self._set_reconnecting(True)
        elif state == "Connected":
            if self.reconnecting:
                self._set_reconnecting(False)
            self._update_stats(st)
            if st.duration is not None:
                self.connected_since = time.time() - st.duration

    def _set_reconnecting(self, on: bool):
        self.reconnecting = on
        self.badge.set_reconnecting(on)
        name = self.connected_profile.name if self.connected_profile else "VPN"
        self.conn_title.setText("Obnovujem spojenie…" if on else "Pripojené")
        self.conn_text.setText("Spojenie sa prerušilo, Cisco ho obnovuje. Nič netreba robiť." if on
                               else f"Ste pripojený/á cez {name}. Okno môžete zavrieť, VPN beží ďalej v pozadí.")
        self.pill.set_state("reconnect" if on else "on")
        self.pill2.set_state("reconnect" if on else "on", None if on else f"Pripojené k {name}")
        self.poll_timer.setInterval(3000 if on else 15000)
        self._set_tray_state(2 if on else 1, "obnovujem spojenie…" if on else f"pripojené: {name}")
        self.setWindowIcon(icons.app_icon(2 if on else 1))
        self._set_header()
        self._tick()
        if not on:
            self._notify("Spojenie obnovené", name)

    def _dropped(self):
        self._on_disconnected("Spojenie sa prerušilo a treba sa znova prihlásiť.")
        self._notify(self.cfg.NazovAplikacie, "VPN sa odpojila – treba sa znova prihlásiť.")
        if self.cfg.PriOdpojeniOtvoritOkno:
            self.show_from_tray()

    def _on_disconnected(self, message: Optional[str]):
        self.cd_timer.stop()
        self.cd_label.hide()
        self.cd_keep.hide()
        self.connected = False
        self.reconnecting = False
        prof = self.connected_profile
        self.connected_profile = None
        self.sec_timer.stop()
        self.poll_timer.stop()
        self.badge.set_reconnecting(False)
        self.conn.hide()
        self.login.show()
        self.pill.set_state("off")
        self.steps.stop()
        self.details.set(3, "–")
        self.details.set(5, "–")
        self.setWindowIcon(icons.app_icon(0))
        self._set_tray_state(0, "nepripojené")
        if self.tray:
            self.mi_disconnect.setEnabled(False)
            self.mi_status.setText("Nepripojené")
        if prof and prof in self.items:
            self.selected = prof
        self._apply_selection()
        if message:
            self.notice.show_msg("error", message)
        if self.pending_reload:
            self._reload_now()
        self._focus_first_empty()

    def do_disconnect(self):
        if not self.connected or self.busy:
            return
        self.busy = True
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.setText("Odpájam…")
        if self.tray:
            self.mi_disconnect.setEnabled(False)

        def done(_):
            self.busy = False
            self._on_disconnected(None)
            if not self.isVisible():
                self._notify(self.cfg.NazovAplikacie, "VPN je odpojená.")

        run_task(self, self.cli.disconnect, done)

    # ================================================================== lišta, okno, ukončenie

    def _set_tray_state(self, state: int, text: str):
        if self.tray:
            self.tray.setIcon(icons.app_icon(state))
            self.tray.setToolTip(f"{self.cfg.NazovAplikacie} – {text}")

    def _notify(self, title: str, body: str):
        if self.tray and self.tray.supportsMessages():
            self.tray.showMessage(title, body, icons.app_icon(1 if self.connected else 0), 5000)
        else:
            system.notify(title, body)

    def hide_to_tray(self):
        self.cd_timer.stop()
        self.cd_label.hide()
        self.cd_keep.hide()
        if not self.tray:
            self.showMinimized()
            return
        self.hide()
        if not self.notified_hidden:
            self.notified_hidden = True
            name = self.connected_profile.name if (self.connected and self.connected_profile) else ""
            self._notify((f"Pripojené: {name}" if name else self.cfg.NazovAplikacie + " beží ďalej"),
                         "Okno je skryté v lište. Kliknutím na ikonu ho znova otvoríte.")

    def show_from_tray(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
        if not self.connected:
            self._focus_first_empty()

    def request_exit(self):
        if self.connected:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(self.cfg.NazovAplikacie)
            box.setText("VPN je pripojená. Čo s ňou?")
            b_disc = box.addButton("Odpojiť a ukončiť", QMessageBox.ButtonRole.DestructiveRole)
            b_keep = box.addButton("Ukončiť, VPN nechať", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Zrušiť", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_keep)
            box.exec()
            if box.clickedButton() is b_disc:
                self.cli.disconnect()
            elif box.clickedButton() is not b_keep:
                return
        if self.worker:
            self.worker.cancel()
            self.worker.wait(5000)
        self.exiting = True
        if self.tray:
            self.tray.hide()
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, e):
        if self.exiting:
            e.accept()
            return
        if self.connecting:
            e.ignore()
            self.notice.show_msg("info", "Počkajte na dokončenie alebo pripájanie zrušte tlačidlom.")
            return
        if self.connected and self.tray:
            e.ignore()
            self.hide_to_tray()
            return
        e.accept()
        if self.connected:
            system.notify(self.cfg.NazovAplikacie, "VPN beží ďalej. Odpojíte ju po opätovnom spustení aplikácie.")
        self.exiting = True
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()

    # ================================================================== ponuka ≡

    def _show_main_menu(self):
        m = QMenu(self)
        a = m.addAction("Podrobnosti a štatistiky…")
        a.triggered.connect(self._show_details)
        a = m.addAction("Denník (priebeh pripojení)…")
        a.triggered.connect(self._show_log)
        a = m.addAction("Profily a certifikáty…")
        a.triggered.connect(self.open_manager)
        m.addSeparator()
        vz = m.addMenu("Vzhľad")
        group = QActionGroup(vz)
        cur = (self.user.Vzhlad or "").lower()
        for label, val in (("Podľa správcu (" + self._theme_name(self.cfg.Vzhlad) + ")", ""),
                           ("Podľa systému", "Systemovy"), ("Svetlý", "Svetly"), ("Tmavý", "Tmavy")):
            act = QAction(label, vz)
            act.setCheckable(True)
            act.setChecked(cur == val.lower())
            act.triggered.connect(lambda _=False, v=val: self._set_theme_pref(v))
            group.addAction(act)
            vz.addAction(act)
        frame = QAction("Systémový rám okna (po reštarte)", m)
        frame.setCheckable(True)
        frame.setChecked(self.user.SystemovyRam)
        frame.triggered.connect(self._toggle_frame)
        m.addAction(frame)
        a = m.addAction("Znova načítať pripojenia")
        a.setEnabled(not self.connected and not self.connecting and not self.busy)
        a.triggered.connect(lambda: self._reload_now(force=True))
        m.addSeparator()
        a = m.addAction("Otvoriť pôvodné Cisco okno")
        a.setEnabled(system.cisco_ui_path(self.cli.path) is not None)
        a.triggered.connect(self._open_cisco_ui)
        if system.mode() == "cisco":
            a = m.addAction("Používať VPN Pripojenie (aj po prihlásení)")
            a.triggered.connect(self._switch_to_ours)
        else:
            a = m.addAction("Vrátiť pôvodné Cisco okno…")
            a.triggered.connect(self._switch_to_cisco)
        m.addSeparator()
        a = m.addAction("O aplikácii")
        a.triggered.connect(self._show_about)
        a = m.addAction("Ukončiť")
        a.triggered.connect(self.request_exit)
        btn = self.header.btn_menu
        m.exec(btn.mapToGlobal(QPoint(btn.width() - m.sizeHint().width(), btn.height())))

    @staticmethod
    def _theme_name(v: str) -> str:
        return {"svetly": "svetlý", "tmavy": "tmavý"}.get((v or "").lower(), "podľa systému")

    def _set_theme_pref(self, val: str):
        self.user.Vzhlad = val
        self.user.save()
        self.apply_theme()

    def _toggle_frame(self, on: bool):
        self.user.SystemovyRam = on
        self.user.save()
        QMessageBox.information(self, self.cfg.NazovAplikacie, "Zmena sa prejaví po reštarte aplikácie.")

    def _open_cisco_ui(self):
        if self.connected or self.connecting:
            QMessageBox.information(self, self.cfg.NazovAplikacie,
                                    "Okno Cisca otvorte, až keď nebudete pripojený cez túto aplikáciu – "
                                    "inak si budú obe aplikácie brániť v pripojení.")
            return
        if not system.start_cisco_ui(self.cli.path):
            QMessageBox.information(self, self.cfg.NazovAplikacie, "Okno Cisco Secure Client sa nenašlo.")

    def _switch_to_cisco(self):
        r = QMessageBox.question(
            self, self.cfg.NazovAplikacie,
            "Vrátiť pôvodné okno Cisco Secure Client vrátane spúšťania po prihlásení?\n\n"
            "VPN Pripojenie sa ukončí a po prihlásení sa už nebude spúšťať. VPN spojenie ostáva.")
        if r != QMessageBox.StandardButton.Yes:
            return
        msg = system.switch_to_cisco()
        if not self.connected:
            system.start_cisco_ui(self.cli.path)
        QMessageBox.information(self, self.cfg.NazovAplikacie, msg)
        self.exiting = True
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()

    def _switch_to_ours(self):
        msg = system.switch_to_vpnpripojenie()
        self.cli.close_cisco_ui()
        QMessageBox.information(self, self.cfg.NazovAplikacie, msg)

    # ================================================================== dialógy

    def _show_help(self):
        QMessageBox.information(
            self, self.cfg.NazovAplikacie + " – pomoc",
            "1. Vyberte pripojenie (profil).\n"
            "2. Vyplňte, čo okno žiada – meno, heslo, prípadne 6-miestny kód z aplikácie Authenticator.\n"
            "3. Kliknite na Pripojiť. Po pripojení sa okno skryje do lišty.\n\n"
            "Ak pripojenie zlyhá, rozbaľte „Zobraziť priebeh“ alebo otvorte ≡ → Denník a pošlite ho správcovi.\n"
            "Profily, certifikáty a diagnostiku nájdete v ≡ → Profily a certifikáty.")

    def _show_about(self):
        from . import certs
        QMessageBox.about(
            self, "O aplikácii",
            f"<b>{escape(self.cfg.NazovAplikacie)}</b> {__version__}<br>"
            f"Grafické okno nad Cisco Secure Client pre Linux.<br><br>"
            f"Cisco CLI: {escape(self.cli.path or 'nenájdené')}<br>"
            f"Verzia Cisca: {escape(self.cisco_version or '?')}<br>"
            f"Systém: {escape(system.distro())} ({escape(system.session_type())})<br>"
            f"Nastavenia správcu: {escape(self.cfg.loaded_from or 'predvolené')}<br>"
            f"Denník: {escape(str(C.log_path()))}<br>"
            f"Certifikáty: {escape(str(certs.cisco_home()))}")

    def _show_details(self):
        dlg = DetailsDialog(self)
        dlg.exec()

    def _show_log(self):
        dlg = LogDialog(self)
        dlg.exec()

    def open_manager(self, tab: int = 0):
        from .manager import ManagerWindow
        if self.manager is None:
            self.manager = ManagerWindow(self)
            self.manager.changed.connect(self._on_manager_changed)
            self.manager.destroyed.connect(lambda: setattr(self, "manager", None))
        self.manager.set_tab(tab)
        self.manager.show()
        self.manager.raise_()
        self.manager.activateWindow()

    def _on_manager_changed(self, what: str):
        if what == "config":
            self.cfg = C.AdminConfig.load()
            self.cli = CiscoCli(find_cli(self.cfg.VpnCliPath), self.cfg.PouzitPty, self.cfg.ConnectTimeoutSeconds)
            self.apply_theme()
        self._reload_now()

    def _reload_now(self, force: bool = False):
        if self.connecting or self.busy or self.connected:
            self.pending_reload = True      # prevezme sa po odpojení, VPN sa neodpája
            return
        self.pending_reload = False
        self.setWindowTitle(self.cfg.NazovAplikacie)
        self.notice.hide()
        if self.cli.available:
            self.load_items(check_state=force)
        else:
            self._startup()


class BannerDialog(QDialog):
    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle("Správa od servera")
        self.setMinimumSize(460, 360)
        lay = QVBoxLayout(self)
        head = QLabel("<b>Správa od servera VPN</b><br>Pred pripojením ju treba prijať.")
        lay.addWidget(head)
        view = QTextBrowser()
        view.setPlainText(text or "(server neposlal žiadny text)")
        lay.addWidget(view, 1)
        bb = QDialogButtonBox()
        accept = bb.addButton("Prijať", QDialogButtonBox.ButtonRole.AcceptRole)
        accept.setProperty("primary", True)
        bb.addButton("Odmietnuť", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        accept.setDefault(True)
        lay.addWidget(bb)


class DetailsDialog(QDialog):
    def __init__(self, win: MainWindow):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Podrobnosti a štatistiky")
        self.setMinimumSize(520, 460)
        lay = QVBoxLayout(self)
        p = win.connected_profile if win.connected else win.selected
        info = []
        if p:
            info += [("Pripojenie", p.name), ("Názov v Cisco", p.host_name), ("Server", p.address or "–"),
                     ("XML profil", p.xml_file or "–"), ("Protokol v profile", p.protocol or "–"),
                     ("Prihlásenie", p.auth.label)]
        info += [("Stav", "pripojené" if win.connected else "nepripojené"),
                 ("Cisco Secure Client", win.cisco_version or "?"), ("Cisco CLI", win.cli.path or "nenájdené")]
        lbl = QLabel("<table cellspacing=4>" + "".join(
            f"<tr><td style='padding-right:14px'><b>{escape(a)}</b></td><td>{escape(b)}</td></tr>" for a, b in info)
            + "</table>")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(lbl)
        lay.addWidget(QLabel("<b>Výstup „vpn stats“</b>"))
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setFont(TH.mono_font(11))
        self.raw.setPlainText("Načítavam…")
        lay.addWidget(self.raw, 1)
        bb = QDialogButtonBox()
        refresh = bb.addButton("Obnoviť", QDialogButtonBox.ButtonRole.ActionRole)
        refresh.clicked.connect(self._load)
        bb.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        lay.addWidget(bb)
        self._load()

    def _load(self):
        if not self.win.cli.available:
            self.raw.setPlainText("Cisco CLI sa nenašlo.")
            return
        run_task(self, self.win.cli.stats, lambda st: self.raw.setPlainText(
            st.raw.strip() if isinstance(st, Stats) and st.raw.strip() else "Cisco neposlalo štatistiky."))


class LogDialog(QDialog):
    def __init__(self, win: MainWindow):
        super().__init__(win)
        self.setWindowTitle("Denník – priebeh pripojení")
        self.setMinimumSize(640, 480)
        lay = QVBoxLayout(self)
        path = C.log_path()
        note = QLabel(f"Súbor: {path}<br>Heslá sú v denníku nahradené hviezdičkami. Pri probléme ho pošlite správcovi.")
        note.setProperty("muted", True)
        note.setWordWrap(True)
        lay.addWidget(note)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(TH.mono_font(11))
        try:
            view.setPlainText(path.read_text(encoding="utf-8", errors="replace") or "(denník je prázdny)")
        except OSError:
            view.setPlainText("(denník zatiaľ neexistuje)")
        view.moveCursor(QTextCursor.MoveOperation.End)
        lay.addWidget(view, 1)
        bb = QDialogButtonBox()
        op = bb.addButton("Otvoriť v editore", QDialogButtonBox.ButtonRole.ActionRole)
        op.clicked.connect(lambda: system.open_path(path))
        cp = bb.addButton("Kopírovať všetko", QDialogButtonBox.ButtonRole.ActionRole)
        cp.clicked.connect(lambda: QApplication.clipboard().setText(view.toPlainText()))
        bb.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        lay.addWidget(bb)
