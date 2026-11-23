"""Okno „Profily a certifikáty“: XML profily, certifikáty, pripojenia (správca), diagnostika."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from datetime import datetime
from html import escape
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import certs, system
from . import config as C
from .config import AuthMode, ItemSettings
from .profiles import PROFILE_DIRS, build_items, host_states, list_profile_files, merge_hosts, not_loaded, \
    parse_profile, profile_dir_for, read_xml_hosts
from .prehlad import import_summary, names_of, removal_question
from .tasks import run_task
from .theme import ui_font


def primary(btn: QPushButton) -> QPushButton:
    btn.setProperty("primary", True)
    return btn


def muted_label(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setProperty("muted", True)
    lb.setFont(ui_font(12))
    return lb


def make_table(headers: list) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setStretchLastSection(True)
    t.verticalHeader().setDefaultSectionSize(34)
    return t


def cell(text: str, data=None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    return it


class ManagerWindow(QDialog):
    changed = pyqtSignal(str)     # "profiles" | "certs" | "config"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(f"{main.cfg.NazovAplikacie} – profily a certifikáty")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(False)
        self.resize(920, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self.tabs = QTabWidget()
        self.p_profiles = ProfilesTab(self)
        self.p_certs = CertsTab(self)
        self.p_conn = ConnectionsTab(self)
        self.p_diag = DiagTab(self)
        self.tabs.addTab(self.p_profiles, "Profily")
        self.tabs.addTab(self.p_certs, "Certifikáty")
        self.tabs.addTab(self.p_conn, "Pripojenia (správca)")
        self.tabs.addTab(self.p_diag, "Diagnostika")
        self.tabs.currentChanged.connect(self._tab_changed)
        lay.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.action = QPushButton()
        self.action.hide()
        self.action.clicked.connect(self._run_action)
        self._action_fn = None
        row.addWidget(self.action)
        close = QPushButton("Zavrieť")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)

    def set_tab(self, i: int):
        self.tabs.setCurrentIndex(max(0, min(i, self.tabs.count() - 1)))
        self._tab_changed(self.tabs.currentIndex())

    def _tab_changed(self, i: int):
        w = self.tabs.widget(i)
        if hasattr(w, "refresh"):
            w.refresh()

    def say(self, text: str, ok=True, action=None):
        """Stavový riadok okna: ok = True (zelená), False (červená), "warn" (oranžová), "info" (sivá).

        action = (text tlačidla, funkcia) – tlačidlo vedľa hlásenia, napr. Reštartovať službu Cisca.
        """
        color = {True: "#0E7A0D", False: "#B10E1C", "warn": "#9A5B00", "info": "#5A6270"}.get(ok, "#0E7A0D")
        self.status.setText(f"<span style='color:{color}'>{escape(text)}</span>")
        self.status.setToolTip(text)
        self._action_fn = action[1] if action else None
        self.action.setText(action[0] if action else "")
        self.action.setVisible(bool(action))

    def _run_action(self):
        fn = self._action_fn
        self.action.hide()
        self._action_fn = None
        if fn:
            fn()

    @property
    def warn_days(self) -> int:
        return self.main.cfg.DniUpozorneniaCertifikat

    def admin(self, args: list, after=None, what: str = ""):
        """Spustí pomocný skript cez pkexec na pozadí (okno polkit sa zobrazí samo)."""
        self.say("Čakám na overenie správcu…")
        self.setEnabled(False)

        def done(res):
            self.setEnabled(True)
            if isinstance(res, Exception):
                ok, msg = False, str(res)
            else:
                ok, msg = res
            self.say(msg or ("Hotovo." if ok else "Nepodarilo sa."), ok)
            if ok and what:
                self.changed.emit(what)
            if after:
                after(ok)

        run_task(self, lambda: system.run_helper(*args), done)


# ================================================================== Profily

class ProfilesTab(QWidget):
    def __init__(self, win: ManagerWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        self.dir = profile_dir_for(win.main.cli.path)
        lay.addWidget(muted_label(
            f"XML profily Cisca v priečinku {self.dir}. Každý profil môže obsahovať viac pripojení "
            "(HostEntry). Pripája sa cez názov pripojenia (HostName), nie cez adresu servera."))
        self.table = make_table(["Súbor", "Pripojenie (HostName)", "Server (HostAddress)", "Protokol", "Stav"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.b_add = primary(QPushButton("+ Pridať XML profil…  🔒"))
        self.b_add.clicked.connect(self.add)
        self.b_del = QPushButton("Odstrániť  🔒")
        self.b_del.clicked.connect(self.remove)
        self.b_view = QPushButton("Zobraziť XML")
        self.b_view.clicked.connect(self.view)
        row.addWidget(self.b_add)
        row.addWidget(self.b_del)
        row.addWidget(self.b_view)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(muted_label("🔒 = vyžaduje heslo správcu počítača. Ak sa nové pripojenie neobjaví v roletke, "
                                  "reštartujte službu Cisca na karte Diagnostika."))

    def refresh(self):
        """Tabuľka hneď z XML, stav („v roletke“, „Cisco ho zatiaľ nenačítal“…) po overení cez `vpn hosts`."""
        self.table.setRowCount(0)
        files = list_profile_files(PROFILE_DIRS)
        self._rows = []
        for pf in files:
            hosts = pf.hosts or [None]
            for h in hosts:
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, cell(pf.path.name, str(pf.path)))
                self.table.setItem(r, 1, cell(h.host_name if h else "–"))
                self.table.setItem(r, 2, cell(h.address if h else "–"))
                self.table.setItem(r, 3, cell((h.protocol or "SSL") if h else "–"))
                st = pf.error or ("overujem v Cisco…" if pf.hosts else "bez pripojení – Cisco z neho nič neponúkne")
                self.table.setItem(r, 4, cell(st))
                self._rows.append((pf.path.name, h.host_name if h else None))
        if self.table.rowCount() == 0:
            self.table.insertRow(0)
            self.table.setItem(0, 0, cell("(žiadne profily)"))
            self.table.setItem(0, 4, cell("bez profilu sa nedá pripojiť – pridajte XML profil od správcu"))
            return
        cli = self.win.main.cli

        def work():
            return cli.hosts() if (cli.available and system.agent_running()) else None

        def done(names):
            if isinstance(names, Exception):
                names = None
            states = host_states(files, names, self.win.main.cfg)
            for r, (fname, host) in enumerate(self._rows):
                if host is not None and (fname, host) in states and r < self.table.rowCount():
                    self.table.setItem(r, 4, cell(states[(fname, host)]))
            waiting = sorted({h for (f, h), t in states.items() if "nenačítal" in t})
            if waiting and not self.win.action.isVisible():
                self.win.say("Cisco ešte neponúka pripojenia: " + ", ".join(waiting) +
                             ". Načíta ich po reštarte služby Cisca.", "warn",
                             ("Reštartovať službu Cisca  🔒", self.win.p_diag.restart_agent))

        run_task(self, work, done)

    def _selected_path(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        p = it.data(Qt.ItemDataRole.UserRole) if it else None
        return Path(p) if p else None

    def add(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Vyberte XML profil Cisca", str(Path.home()),
                                            "XML profil (*.xml);;Všetky súbory (*)")
        if not fn:
            return
        src = Path(fn)
        pf = parse_profile(src)
        if pf.error:
            QMessageBox.warning(self, "XML profil", f"Súbor sa nedá použiť: {pf.error}")
            return
        names = ", ".join(h.host_name for h in pf.hosts) or "žiadne"
        base = re.sub(r"[^A-Za-z0-9._+-]+", "_", src.stem).strip("._") or "profil"
        dest_name = base + ".xml"
        existing = self.dir / dest_name
        q = (f"Nainštalovať profil {dest_name}?\n\nPripojenia: {names}\nPriečinok: {self.dir}"
             + ("\n\nProfil s rovnakým názvom už existuje – nahradí sa (pôvodný ide do zálohy)." if existing.exists() else ""))
        if QMessageBox.question(self, "XML profil", q) != QMessageBox.StandardButton.Yes:
            return
        tmpdir = Path(tempfile.mkdtemp(prefix="vpn-pripojenie-"))
        tmp = tmpdir / dest_name
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o600)

        cli = self.win.main.cli

        def check():
            # Cisco načíta nový profil obvykle do pár sekúnd – overiť, čo naozaj ponúka
            if not (cli.available and system.agent_running()):
                return None
            names = []
            for _ in range(3):
                time.sleep(2)
                names = cli.hosts()
                if not not_loaded(pf, names):
                    break
            return names

        def checked(names, installed_msg):
            self.refresh()
            if isinstance(names, Exception) or names is None:
                self.win.say(installed_msg + " Služba Cisca nebeží, preto sa nedá overiť, či profil načítala.",
                             "warn", ("Reštartovať službu Cisca  🔒", self.win.p_diag.restart_agent))
                return
            missing = not_loaded(pf, names)
            if missing:
                self.win.say(installed_msg + " Cisco ho zatiaľ nenačítal (chýba: " + ", ".join(missing) +
                             "). Reštartujte službu Cisca.", "warn",
                             ("Reštartovať službu Cisca  🔒", self.win.p_diag.restart_agent))
            else:
                self.win.say(installed_msg + " Cisco ponúka: " + names_of(pf) + " – nájdete ich v roletke.")

        def after(ok):
            shutil.rmtree(tmpdir, ignore_errors=True)
            if not ok:
                self.refresh()
                return
            msg = self.win.status.toolTip()
            self.win.say(msg + " Overujem, či ho Cisco načítal…", "info")
            run_task(self, check, lambda names: checked(names, msg))

        self.win.admin(["install-profile", str(tmp), str(self.dir)], after, "profiles")

    def remove(self):
        p = self._selected_path()
        if not p:
            return
        if QMessageBox.question(self, "XML profil", removal_question(p, self.win.main)) \
                != QMessageBox.StandardButton.Yes:
            return
        self.win.admin(["remove-profile", p.name, str(p.parent)], lambda ok: self.refresh(), "profiles")

    def view(self):
        p = self._selected_path()
        if p:
            system.open_path(p)


# ================================================================== Certifikáty

class CertsTab(QWidget):
    def __init__(self, win: ManagerWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)

        g1 = QGroupBox("Certifikačné autority (CA) – overenie servera")
        l1 = QVBoxLayout(g1)
        self.ca = make_table(["Názov (CN)", "Platný do", "Pre koho", "Súbor"])
        self.ca.setToolTip("Certifikačné autority, ktorými Cisco overuje VPN server.")
        self.ca.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        l1.addWidget(self.ca)
        r1 = QHBoxLayout()
        b = primary(QPushButton("+ Importovať CA (.crt/.cer/.pem)…"))
        b.clicked.connect(self.add_ca)
        self.all_users = QCheckBox("pre všetkých používateľov počítača  🔒")
        bd = QPushButton("Odstrániť")
        bd.clicked.connect(self.del_ca)
        r1.addWidget(b)
        r1.addWidget(self.all_users)
        r1.addStretch(1)
        r1.addWidget(bd)
        l1.addLayout(r1)
        lay.addWidget(g1, 1)

        g2 = QGroupBox("Osobný certifikát – prihlásenie certifikátom")
        l2 = QVBoxLayout(g2)
        self.cl = make_table(["Komu je vydaný (CN)", "Vydal (CA)", "Platný do", "Súkromný kľúč", "Súbor"])
        self.cl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        l2.addWidget(self.cl)
        r2 = QHBoxLayout()
        b2 = primary(QPushButton("+ Importovať .p12 / .pfx…"))
        b2.clicked.connect(self.add_p12)
        bd2 = QPushButton("Odstrániť")
        bd2.clicked.connect(self.del_client)
        r2.addWidget(b2)
        r2.addStretch(1)
        r2.addWidget(bd2)
        l2.addLayout(r2)
        lay.addWidget(g2, 1)
        lay.addWidget(muted_label(
            f"Cisco na Linuxe číta certifikáty v PEM z {certs.cisco_home()} (osobný certifikát v client/, "
            "kľúč v client/private/) a z /opt/.cisco/certificates/ca (pre všetkých). Súbor .p12 sa preto pri "
            "importe rozbalí na certifikát a kľúč (kľúč je čitateľný len pre vás). Cisco prednostne hľadá aj "
            "v úložisku Firefoxu – ak je tam starší certifikát, môže mať prednosť."))
        self.ff = muted_label("")
        self.ff.hide()
        lay.addWidget(self.ff)

    def refresh(self, summary: bool = True):
        def fill(table, rows):
            table.setRowCount(0)
            for vals, data in rows:
                r = table.rowCount()
                table.insertRow(r)
                for c, v in enumerate(vals):
                    table.setItem(r, c, cell(v, data if c == 0 else None))

        days = self.win.warn_days
        cas = certs.list_ca()
        clients = certs.list_client()
        dup_ca = certs.duplicates(cas)
        dup_cl = certs.duplicates(clients)

        def file_col(c, dup):
            return c.path.name + (f" · rovnaký ako {', '.join(dup[c.path])}" if c.path in dup else "")

        def issuer_col(c):
            if c.error:
                return "–"
            if c.issuer == c.subject:
                return f"{c.issuer_cn} (sám sebe)"
            return c.issuer_cn + ("" if certs.issuer_installed(c, cas) else " · CA nie je nainštalovaná")

        fill(self.ca, [((c.cn, certs.describe_expiry(c, days), "všetci" if c.system else "len ja",
                         file_col(c, dup_ca)), c) for c in cas])
        fill(self.cl, [((c.cn, issuer_col(c), certs.describe_expiry(c, days),
                         "áno" if c.has_key else "CHÝBA – certifikát sa nedá použiť", file_col(c, dup_cl)), c)
                       for c in clients])
        if not cas:
            self.ca.insertRow(0)
            self.ca.setItem(0, 0, cell("(žiadna CA)"))
            self.ca.setItem(0, 1, cell("Cisco použije len CA systému; ak server neoverí, importujte firemnú CA"))
        if not clients:
            self.cl.insertRow(0)
            self.cl.setItem(0, 0, cell("(žiadny osobný certifikát)"))
            self.cl.setItem(0, 1, cell("treba len pre pripojenia s prihlásením certifikátom"))
        if summary:                           # súhrn len pri otvorení karty, neprepíše výsledok akcie
            self._summary(cas, clients, days)
        run_task(self, certs.firefox_user_certs, self._firefox)

    def _summary(self, cas, clients, days):
        warns = certs.expiry_warnings(days, clients, cas)
        if warns:
            kind, text = warns[0]
            more = f" (a ďalšie upozornenia: {len(warns) - 1})" if len(warns) > 1 else ""
            self.win.say(text + more, False if kind == "error" else "warn")
        elif clients or cas:
            ok = [c for c in clients if c.usable]
            parts = []
            if clients:
                parts.append(f"osobné certifikáty: {len(ok)} z {len(clients)} použiteľné")
            parts.append(f"CA: {len(cas)}")
            self.win.say("Certifikáty sú v poriadku – " + ", ".join(parts) + ".", "info")

    def _firefox(self, names):
        if isinstance(names, Exception) or not names:
            self.ff.hide()
            return
        self.ff.setText("Vo Firefoxe sú aj osobné certifikáty: " + ", ".join(names) +
                        ". Cisco ich môže použiť prednostne pred certifikátmi vyššie.")
        self.ff.show()

    @staticmethod
    def _sel(table):
        r = table.currentRow()
        it = table.item(r, 0) if r >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def add_ca(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Vyberte CA certifikát", str(Path.home()),
                                            "Certifikát (*.crt *.cer *.pem);;Všetky súbory (*)")
        if not fn:
            return
        src = Path(fn)
        try:
            if self.all_users.isChecked():
                tmp = certs.ca_to_tempfile(src)
                info = certs.inspect(tmp)
                name = re.sub(r"[^A-Za-z0-9._+-]+", "_", info.cn).strip("._") or src.stem
                final = tmp.with_name(name + ".pem")
                tmp.replace(final)
                self.win.admin(["install-ca", str(final)],
                               lambda ok: (final.unlink(missing_ok=True), self.refresh(False)), "certs")
                return
            dest = certs.import_ca_user(src)
        except certs.CertError as e:
            QMessageBox.warning(self, "CA certifikát", str(e))
            return
        info = certs.inspect(dest)
        self.refresh(False)
        self.win.say(f"CA certifikát {info.cn} (platný do {info.valid_to}) je uložený len pre vás: {dest}")
        self.win.changed.emit("certs")

    def del_ca(self):
        c = self._sel(self.ca)
        if not c:
            return
        if QMessageBox.question(self, "CA certifikát", f"Odstrániť CA certifikát {c.cn}?") \
                != QMessageBox.StandardButton.Yes:
            return
        if c.system:
            self.win.admin(["remove-ca", c.path.name], lambda ok: self.refresh(False), "certs")
            return
        try:
            certs.remove_user_ca(c.path)
        except (OSError, certs.CertError) as e:
            QMessageBox.warning(self, "CA certifikát", str(e))
        self.refresh(False)

    def add_p12(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Vyberte osobný certifikát", str(Path.home()),
                                            "Certifikát PKCS#12 (*.p12 *.pfx);;Všetky súbory (*)")
        if not fn:
            return
        pw, ok = QInputDialog.getText(self, "Heslo k certifikátu", f"Heslo k súboru {Path(fn).name}:",
                                      QLineEdit.EchoMode.Password)
        if not ok:
            return
        self.win.say("Rozbaľujem certifikát…")

        def done(res):
            if isinstance(res, Exception):
                QMessageBox.warning(self, "Osobný certifikát", str(res))
                self.win.say(str(res), False)
                return
            path, n_ca = res
            info = certs.inspect(path)
            msg = f"Osobný certifikát {info.cn} je importovaný (platný do {info.valid_to})."
            if n_ca:
                msg += f" Pribudlo aj {n_ca} CA z balíka."
            self.refresh(False)
            self.win.say(msg)
            self.win.changed.emit("certs")
            QMessageBox.information(self, "Osobný certifikát importovaný",
                                    import_summary(info, path, n_ca, certs.list_ca(), self.win.warn_days))

        run_task(self, lambda: certs.import_p12(Path(fn), pw), done)
        pw = ""

    def del_client(self):
        c = self._sel(self.cl)
        if not c:
            return
        if QMessageBox.question(self, "Osobný certifikát", f"Odstrániť osobný certifikát {c.cn} aj jeho kľúč?") \
                != QMessageBox.StandardButton.Yes:
            return
        certs.remove_client(c.path)
        self.refresh(False)


# ================================================================== Pripojenia (správca)

BASE = ["Meno a heslo", "Len heslo", "Osobný certifikát", "Meno a dve heslá"]


def split_auth(m: AuthMode):
    return {AuthMode.MENO_HESLO_KOD: (0, True), AuthMode.MENO_HESLO: (0, False), AuthMode.HESLO_KOD: (1, True),
            AuthMode.HESLO: (1, False), AuthMode.CERTIFIKAT: (2, False), AuthMode.DVE_HESLA: (3, False)}[m]


def join_auth(base: int, twofa: bool) -> AuthMode:
    if base == 0:
        return AuthMode.MENO_HESLO_KOD if twofa else AuthMode.MENO_HESLO
    if base == 1:
        return AuthMode.HESLO_KOD if twofa else AuthMode.HESLO
    return AuthMode.CERTIFIKAT if base == 2 else AuthMode.DVE_HESLA


class ConnectionsTab(QWidget):
    C_DEF, C_NAME, C_CISCO, C_AUTH, C_2FA, C_USER, C_HIDE, C_STATE = range(8)

    def __init__(self, win: ManagerWindow):
        super().__init__()
        self.win = win
        self.hosts = []
        lay = QVBoxLayout(self)
        lay.addWidget(muted_label(
            "Každý riadok je jedna voľba v roletke aplikácie. Nastavte spôsob prihlásenia a či sa k heslu pridáva "
            "kód z aplikácie Authenticator (2FA). „Klonovať“ vytvorí ďalšiu voľbu nad tým istým pripojením – napr. "
            "bez 2FA alebo pre iné meno. Uloženie vyžaduje heslo správcu a platí pre všetkých používateľov."))
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Predvolené", "Názov v aplikácii", "Pripojenie v Cisco", "Prihlásenie",
                                              "2FA kód", "Meno (voliteľné)", "Skryť", "Stav"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        for c, w in ((0, 84), (1, 170), (2, 160), (3, 150), (4, 70), (5, 130), (6, 56)):
            self.table.setColumnWidth(c, w)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        for text, fn in (("Klonovať riadok", self.clone), ("Odstrániť", self.delete), ("Hore", lambda: self.move(-1)),
                         ("Dole", lambda: self.move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        g = QGroupBox("Všeobecné")
        form = QFormLayout(g)
        self.e_title = QLineEdit()
        self.c_theme = QComboBox()
        self.c_theme.addItems(["Podľa systému", "Svetlý", "Tmavý"])
        self.c_hide = QComboBox()
        self.c_hide.addItems(["hneď", "o 3 s", "o 5 s", "neskrývať"])
        self.s_timeout = QSpinBox()
        self.s_timeout.setRange(10, 600)
        self.s_timeout.setSuffix(" s")
        self.k_drop = QCheckBox("Pri prerušení spojenia otvoriť okno na prihlásenie")
        self.k_banner = QCheckBox("Správu servera (banner) potvrdiť automaticky")
        self.k_keyring = QCheckBox("Povoliť ukladanie hesla v kľúčenke systému (GNOME Keyring / KWallet)")
        self.s_warn = QSpinBox()
        self.s_warn.setRange(0, 365)
        self.s_warn.setSuffix(" dní")
        self.s_warn.setSpecialValueText("neupozorňovať")
        self.s_warn.setToolTip("Koľko dní pred vypršaním osobného certifikátu alebo CA upozorniť používateľa "
                               "(predvolene 30).")
        self.e_cli = QLineEdit()
        self.e_cli.setPlaceholderText("automaticky (/opt/cisco/secureclient/bin/vpn)")
        form.addRow("Nadpis aplikácie", self.e_title)
        form.addRow("Predvolený vzhľad", self.c_theme)
        form.addRow("Po pripojení skryť okno", self.c_hide)
        form.addRow("Limit pripájania", self.s_timeout)
        form.addRow("Upozorniť na vypršanie certifikátu", self.s_warn)
        form.addRow("Cesta k Cisco CLI", self.e_cli)
        form.addRow("", self.k_drop)
        form.addRow("", self.k_banner)
        form.addRow("", self.k_keyring)
        lay.addWidget(g)

        bottom = QHBoxLayout()
        self.lbl_src = muted_label("")
        bottom.addWidget(self.lbl_src, 1)
        save = primary(QPushButton("Uložiť pre všetkých  🔒"))
        save.clicked.connect(self.save)
        bottom.addWidget(save)
        lay.addLayout(bottom)
        self._loaded = False

    HIDE_VALUES = [0, 3, 5, -1]
    THEME_VALUES = ["Systemovy", "Svetly", "Tmavy"]

    def refresh(self):
        if self._loaded:
            return
        self._loaded = True
        cfg = C.AdminConfig.load()
        self.cfg = cfg
        self.lbl_src.setText("Načítané z: " + (cfg.loaded_from or "predvolené (žiadny súbor)") +
                             f" · ukladá sa do {C.admin_config_path()}")
        self.e_title.setText(cfg.NazovAplikacie)
        tv = [v.lower() for v in self.THEME_VALUES]
        self.c_theme.setCurrentIndex(tv.index(cfg.Vzhlad.lower()) if cfg.Vzhlad.lower() in tv else 0)
        self.c_hide.setCurrentIndex(self.HIDE_VALUES.index(cfg.SkrytPoSekundach)
                                    if cfg.SkrytPoSekundach in self.HIDE_VALUES else 1)
        self.s_timeout.setValue(cfg.ConnectTimeoutSeconds)
        self.s_warn.setValue(cfg.DniUpozorneniaCertifikat)
        self.e_cli.setText(cfg.VpnCliPath)
        self.k_drop.setChecked(cfg.PriOdpojeniOtvoritOkno)
        self.k_banner.setChecked(cfg.AutoPrijatBanner)
        self.k_keyring.setChecked(cfg.PovolitKlucenku)
        cli = self.win.main.cli

        def work():
            names = cli.hosts() if cli.available else []
            return merge_hosts(names, read_xml_hosts())

        def done(hosts):
            self.hosts = hosts if isinstance(hosts, list) else []
            self.table.setRowCount(0)
            for p in build_items(cfg, self.hosts):
                state = "chýba v Cisco" if p.missing else ("nastavené" if p.configured else "nové – skontrolujte")
                self._add_row(self.table.rowCount(), p.is_default, p.name, p.host_name, p.auth, p.preset_user,
                              p.hidden, state)

        run_task(self, work, done)

    def _add_row(self, r, default, name, host, auth, user, hidden, state):
        t = self.table
        t.insertRow(r)
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        chk.setCheckState(Qt.CheckState.Checked if default else Qt.CheckState.Unchecked)
        t.setItem(r, self.C_DEF, chk)
        t.setItem(r, self.C_NAME, QTableWidgetItem(name))
        hc = QComboBox()
        names = [h.host_name for h in self.hosts]
        if host not in names:
            names.append(host)
        hc.addItems(names)
        hc.setCurrentText(host)
        t.setCellWidget(r, self.C_CISCO, hc)
        base, twofa = split_auth(auth)
        ac = QComboBox()
        ac.addItems(BASE)
        ac.setCurrentIndex(base)
        t.setCellWidget(r, self.C_AUTH, ac)
        fa = QCheckBox()
        fa.setObjectName("twofa")
        fa.setChecked(twofa)
        fa.setEnabled(base in (0, 1))
        ac.currentIndexChanged.connect(lambda i, box=fa: (box.setEnabled(i in (0, 1)),
                                                          box.setChecked(box.isChecked() and i in (0, 1))))
        t.setCellWidget(r, self.C_2FA, self._center(fa))
        t.setItem(r, self.C_USER, QTableWidgetItem(user or ""))
        hide = QTableWidgetItem()
        hide.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        hide.setCheckState(Qt.CheckState.Checked if hidden else Qt.CheckState.Unchecked)
        t.setItem(r, self.C_HIDE, hide)
        st = QTableWidgetItem(state)
        st.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        t.setItem(r, self.C_STATE, st)

    @staticmethod
    def _center(w: QWidget) -> QWidget:
        box = QWidget()
        l = QHBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        l.addWidget(w, 0, Qt.AlignmentFlag.AlignCenter)
        return box

    def _read_row(self, r):
        t = self.table
        host = t.cellWidget(r, self.C_CISCO).currentText().strip()
        base = t.cellWidget(r, self.C_AUTH).currentIndex()
        twofa = t.cellWidget(r, self.C_2FA).findChild(QCheckBox, "twofa").isChecked()
        return dict(
            default=t.item(r, self.C_DEF).checkState() == Qt.CheckState.Checked,
            name=(t.item(r, self.C_NAME).text() if t.item(r, self.C_NAME) else "").strip() or host,
            host=host, auth=join_auth(base, twofa),
            user=(t.item(r, self.C_USER).text() if t.item(r, self.C_USER) else "").strip(),
            hidden=t.item(r, self.C_HIDE).checkState() == Qt.CheckState.Checked,
            state=t.item(r, self.C_STATE).text() if t.item(r, self.C_STATE) else "",
        )

    def clone(self):
        r = self.table.currentRow()
        if r < 0:
            return
        d = self._read_row(r)
        names = {self._read_row(i)["name"] for i in range(self.table.rowCount())}
        stem = re.sub(r"\s*\(\d+\)$", "", d["name"])
        n = 2
        while f"{stem} ({n})" in names:
            n += 1
        self._add_row(r + 1, False, f"{stem} ({n})", d["host"], d["auth"], d["user"], d["hidden"], "nový klon – uložte")
        self.table.selectRow(r + 1)

    def delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        d = self._read_row(r)
        same = sum(1 for i in range(self.table.rowCount()) if self._read_row(i)["host"].lower() == d["host"].lower())
        if same < 2 and d["state"] != "chýba v Cisco":
            QMessageBox.information(self, "Pripojenia", "Posledná položka pripojenia z Cisca sa nedá odstrániť, "
                                                         "dá sa len skryť (stĺpec Skryť).")
            return
        self.table.removeRow(r)

    def move(self, d: int):
        r = self.table.currentRow()
        to = r + d
        if r < 0 or to < 0 or to >= self.table.rowCount():
            return
        a = self._read_row(r)
        self.table.removeRow(r)
        self._add_row(to, a["default"], a["name"], a["host"], a["auth"], a["user"], a["hidden"], a["state"])
        self.table.selectRow(to)

    def save(self):
        rows = [self._read_row(i) for i in range(self.table.rowCount())]
        names = [r["name"].lower() for r in rows]
        dup = next((n for n in names if names.count(n) > 1), None)
        if dup:
            QMessageBox.warning(self, "Pripojenia", f"Dve položky majú rovnaký názov „{dup}“. Premenujte jednu z nich.")
            return
        cli = self.e_cli.text().strip()
        if cli and not re.fullmatch(r"/opt/cisco/[A-Za-z0-9._/-]+/vpn", cli):
            QMessageBox.warning(self, "Pripojenia", "Cesta k Cisco CLI musí byť v tvare /opt/cisco/…/vpn.")
            return
        cfg = self.cfg
        cfg.NazovAplikacie = self.e_title.text().strip() or "VPN Pripojenie"
        cfg.Vzhlad = self.THEME_VALUES[self.c_theme.currentIndex()]
        cfg.SkrytPoSekundach = self.HIDE_VALUES[self.c_hide.currentIndex()]
        cfg.ConnectTimeoutSeconds = self.s_timeout.value()
        cfg.DniUpozorneniaCertifikat = self.s_warn.value()
        cfg.VpnCliPath = cli
        cfg.PriOdpojeniOtvoritOkno = self.k_drop.isChecked()
        cfg.AutoPrijatBanner = self.k_banner.isChecked()
        cfg.PovolitKlucenku = self.k_keyring.isChecked()
        seen_default = False
        items = []
        for r in rows:
            if not r["host"]:
                continue
            default = r["default"] and not seen_default
            seen_default = seen_default or default
            items.append(ItemSettings(Cisco=r["host"], Nazov=r["name"], Auth=r["auth"].value, Meno=r["user"],
                                      Skryt=r["hidden"], Predvolene=default))
        cfg.Polozky = items
        fd, tmp = tempfile.mkstemp(prefix="vpn-pripojenie-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(cfg.to_json())

        def after(ok):
            Path(tmp).unlink(missing_ok=True)
            if ok:
                self._loaded = False
                self.refresh()

        self.win.admin(["save-config", tmp], after, "config")


# ================================================================== Diagnostika

class DiagTab(QWidget):
    def __init__(self, win: ManagerWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        self.info = QLabel("Zisťujem…")
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        g = QGroupBox("Cesta k Cisco CLI")
        gl = QHBoxLayout(g)
        self.cli_label = QLabel()
        gl.addWidget(self.cli_label, 1)
        b = QPushButton("Zmeniť…")
        b.clicked.connect(lambda: self.win.set_tab(2))
        b.setToolTip("Cesta sa nastavuje pre všetkých na karte Pripojenia (správca).")
        gl.addWidget(b)
        lay.addWidget(g)
        row1 = QHBoxLayout()
        for text, fn in (("Reštartovať službu Cisca  🔒", self.restart_agent),
                         ("Otvoriť denník", lambda: system.open_path(C.log_path())),
                         ("Uložiť diagnostiku…", self.save_diag)):
            bt = QPushButton(text)
            bt.clicked.connect(fn)
            row1.addWidget(bt)
        row1.addStretch(1)
        lay.addLayout(row1)
        g2 = QGroupBox("Pôvodné okno Cisco Secure Client")
        l2 = QVBoxLayout(g2)
        self.mode_label = QLabel()
        self.mode_label.setWordWrap(True)
        l2.addWidget(self.mode_label)
        r2 = QHBoxLayout()
        self.b_open = QPushButton("Otvoriť pôvodné Cisco okno")
        self.b_open.clicked.connect(self.open_cisco)
        self.b_mode = QPushButton()
        self.b_mode.clicked.connect(self.switch_mode)
        r2.addWidget(self.b_open)
        r2.addWidget(self.b_mode)
        r2.addStretch(1)
        l2.addLayout(r2)
        lay.addWidget(g2)
        lay.addStretch(1)

    def refresh(self):
        main = self.win.main
        cli = main.cli

        def work():
            return dict(agent=system.agent_status(), version=cli.version() if cli.available else "",
                        state=cli.state() if cli.available else "", distro=system.distro(),
                        session=system.session_type(), keyring=system.keyring_available(),
                        cisco_files=[f.name for f in system.cisco_autostart_files()])

        run_task(self, work, self._show)
        self.cli_label.setText(cli.path or "nenájdené")
        self._mode_ui()

    def _show(self, d):
        if isinstance(d, Exception):
            self.info.setText(str(d))
            return
        main = self.win.main
        from PyQt6.QtWidgets import QSystemTrayIcon
        agent = {"active": "● beží", "inactive": "○ zastavená", "failed": "✕ zlyhala"}.get(d["agent"], d["agent"])
        rows = [
            ("Systém", f"{d['distro']} · relácia {d['session']}"),
            ("Cisco Secure Client", d["version"] or "?"),
            ("Služba vpnagentd", agent),
            ("Stav VPN", d["state"] or "?"),
            ("Priečinok profilov", str(profile_dir_for(main.cli.path))),
            ("Ikona v lište", "dostupná" if QSystemTrayIcon.isSystemTrayAvailable() else
             "nedostupná (GNOME bez rozšírenia AppIndicator – okno sa namiesto skrytia minimalizuje)"),
            ("Kľúčenka (secret-tool)", "áno" if d["keyring"] else "nie"),
            ("Nastavenia správcu", main.cfg.loaded_from or "predvolené"),
            ("Denník", str(C.log_path())),
            ("Autoštart okna Cisca", ", ".join(d["cisco_files"]) or "nenašiel sa"),
        ]
        self._last = rows
        self.info.setText("<table cellspacing=5>" + "".join(
            f"<tr><td style='padding-right:16px'><b>{escape(a)}</b></td><td>{escape(b)}</td></tr>" for a, b in rows)
            + "</table>")

    def _mode_ui(self):
        if system.mode() == "cisco":
            self.mode_label.setText("Na tomto účte sa po prihlásení spúšťa <b>pôvodné okno Cisca</b>; "
                                    "VPN Pripojenie sa automaticky nespúšťa.")
            self.b_mode.setText("Používať VPN Pripojenie")
        else:
            self.mode_label.setText("Po prihlásení sa spúšťa <b>VPN Pripojenie</b>; automatické spúšťanie okna Cisca "
                                    "je pre tento účet vypnuté (služba Cisca beží ďalej). Ak niečo nefunguje, "
                                    "dá sa jedným klikom vrátiť pôvodné Cisco.")
            self.b_mode.setText("Vrátiť pôvodné Cisco okno")

    def restart_agent(self):
        if self.win.main.connected:
            if QMessageBox.question(self, "Služba Cisca", "Reštart služby odpojí VPN. Pokračovať?") \
                    != QMessageBox.StandardButton.Yes:
                return
        def after(ok):
            self.refresh()
            if ok:
                self.win.p_profiles.refresh()      # znova overiť, čo Cisco po reštarte ponúka

        self.win.admin(["restart-agent"], after, "profiles")

    def open_cisco(self):
        if not system.start_cisco_ui(self.win.main.cli.path):
            QMessageBox.information(self, "Cisco", "Okno Cisco Secure Client sa nenašlo.")

    def switch_mode(self):
        if system.mode() == "cisco":
            msg = system.switch_to_vpnpripojenie()
        else:
            if QMessageBox.question(self, "Cisco", "Vrátiť pôvodné okno Cisco Secure Client aj jeho spúšťanie po "
                                    "prihlásení? VPN Pripojenie sa po prihlásení prestane spúšťať.") \
                    != QMessageBox.StandardButton.Yes:
                return
            msg = system.switch_to_cisco()
        self._mode_ui()
        self.win.say(msg)

    def save_diag(self):
        default = str(Path.home() / f"vpn-diagnostika-{datetime.now():%Y%m%d-%H%M}.txt")
        fn, _ = QFileDialog.getSaveFileName(self, "Uložiť diagnostiku", default, "Text (*.txt)")
        if not fn:
            return
        main = self.win.main
        parts = ["VPN Pripojenie – diagnostika " + datetime.now().strftime("%Y-%m-%d %H:%M"), ""]
        for a, b in getattr(self, "_last", []):
            parts.append(f"{a}: {b}")
        parts += ["", "--- profily ---"]
        for pf in list_profile_files(PROFILE_DIRS):
            parts.append(f"{pf.path}: " + (pf.error or ", ".join(f"{h.host_name} → {h.address}" for h in pf.hosts)))
        parts += ["", "--- certifikáty ---"]
        for c in certs.list_ca():
            parts.append(f"CA {c.cn} do {c.valid_to} ({'všetci' if c.system else 'používateľ'})")
        for c in certs.list_client():
            parts.append(f"osobný {c.cn} do {c.valid_to}, kľúč {'áno' if c.has_key else 'CHÝBA'}")
        if main.cli.available:
            parts += ["", "--- vpn stats ---", main.cli.stats().raw]
        try:
            log = C.log_path().read_text(encoding="utf-8", errors="replace")
            parts += ["", "--- denník (koniec, heslá maskované) ---", log[-20000:]]
        except OSError:
            pass
        try:
            Path(fn).write_text("\n".join(parts), encoding="utf-8")
            self.win.say(f"Diagnostika uložená: {fn}")
        except OSError as e:
            self.win.say(str(e), False)
