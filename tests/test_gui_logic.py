"""Toky hlavného okna nad náhradou PyQt6 (tests/qtstub) a simulovaným Cisco CLI.

Overuje logiku okna (stavy, prechody, polia, lišta, správca), nie vzhľad. Spustenie:
    python3 -m unittest tests.test_gui_logic -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    import PyQt6  # noqa: F401  skutočné Qt je k dispozícii → tieto testy s náhradou nespúšťať
    REAL_QT = "qtstub" not in PyQt6.__file__
except ImportError:
    REAL_QT = False
if not REAL_QT:
    sys.path.insert(0, str(ROOT / "tests" / "qtstub"))
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="vpnp-gui-"))
ENV = ({
    "HOME": str(TMP / "home"), "XDG_CONFIG_HOME": str(TMP / "home/.config"),
    "XDG_STATE_HOME": str(TMP / "home/.local/state"), "VPN_PRIPOJENIE_ETC": str(TMP / "etc"),
    "FAKE_STATE": str(TMP / "state"), "FAKE_PW": "tajne123456",
})
os.environ.update(ENV)


def setUpModule():
    os.environ.update(ENV)
(TMP / "home").mkdir(parents=True)
(TMP / "etc").mkdir()
FAKE = TMP / "vpn"
FAKE.write_text(f"#!/bin/sh\nexec {sys.executable} {ROOT / 'tests' / 'fake_vpn.py'} \"$@\"\n")
FAKE.chmod(0o755)


@unittest.skipIf(REAL_QT, "beží so skutočným PyQt6 – tieto testy sú pre náhradu")
class GuiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6 import QtWidgets
        from vpn_pripojenie import system
        cls.QtW = QtWidgets
        cls.app = QtWidgets.QApplication([])
        cls.notes = []
        system.agent_running = lambda: True
        system.agent_status = lambda: "active"
        system.notify = lambda t, b, *a: cls.notes.append((t, b))
        cls.helper_calls = []

        def fake_helper(*args, **k):
            cls.helper_calls.append(args)
            if args[0] == "save-config":
                Path(TMP / "etc" / "config.json").write_text(Path(args[1]).read_text())
            return True, "OK"
        system.run_helper = fake_helper

    def setUp(self):
        self.write_cfg()
        (TMP / "state").write_text("Disconnected")
        os.environ["FAKE_SCENARIO"] = "ok"
        self.QtW.QSystemTrayIcon.available = True
        self.QtW.QMessageBox.choose.clear()
        self.QtW.QMessageBox.answers.clear()
        self.helper_calls.clear()
        from vpn_pripojenie import config as C
        C.UserState.path().unlink(missing_ok=True)

    def write_cfg(self, **extra):
        cfg = {"VpnCliPath": str(FAKE), "ConnectTimeoutSeconds": 20, "SkrytPoSekundach": 3, **extra}
        (TMP / "etc" / "config.json").write_text(json.dumps(cfg))

    def make(self):
        from PyQt6.QtCore import run_single_shots
        from vpn_pripojenie.main_window import MainWindow
        w = MainWindow()
        run_single_shots()
        return w

    def fill(self, w, user="jnovak", pw="tajne", code="123456"):
        if w.f_user.isVisible():
            w.f_user.edit.setText(user)
        if w.f_pw.isVisible():
            w.f_pw.edit.setText(pw)
        if w.f_code.isVisible():
            w.f_code.edit.setText(code)

    # ------------------------------------------------------------------

    def test_startup_and_fields(self):
        w = self.make()
        self.assertEqual([p.name for p in w.visible_items()], ["Pripojenie 1", "Pripojenie 2"])
        self.assertEqual(w.selected.host_name, "Firma B EAP+2FA")
        self.assertTrue(w.f_profile.isVisible() and w.f_user.isVisible() and w.f_pw.isVisible())
        self.assertTrue(w.f_code.isVisible() and w.code_hint.isVisible())
        self.assertFalse(w.t_keyring.isVisible())            # správca nepovolil
        self.assertIn("5.1.13.177", w.footer_label.text())
        self.assertFalse(w.btn_connect.isEnabled())
        self.fill(w)
        self.assertTrue(w.btn_connect.isEnabled())
        w.f_code.edit.setText("12a34567")                       # len 6 číslic
        self.assertEqual(w.f_code.edit.text(), "123456")
        self.assertEqual(w.header.caption, "Pripojenie k")

    def test_connect_poll_reconnect_drop(self):
        w = self.make()
        self.fill(w, pw="tajne12345", code="6")     # heslo + kód = tajne123456
        w.f_code.edit.setText("123456")
        w.f_pw.edit.setText("tajne")
        os.environ["FAKE_PW"] = "tajne123456"
        w.btn_connect.click()
        self.assertTrue(w.connected, w.notice.label.text())
        self.assertTrue(w.conn.isVisible() and not w.login.isVisible())
        self.assertEqual(w.details.rows[3][1], "10.20.30.40")
        self.assertIn("MB", w.details.rows[5][1])
        self.assertEqual(w.f_pw.edit.text(), "")                # heslo sa vymaže
        self.assertTrue(w.cd_timer.isActive())
        self.assertEqual(w.header.caption, "Pripojené k")
        self.assertEqual(w.user.Meno, "jnovak")
        for _ in range(3):
            w.cd_timer.fire()
        self.assertFalse(w.isVisible())                          # skryté do lišty
        (TMP / "state").write_text("Reconnecting")
        w.poll_timer.fire()
        self.assertTrue(w.reconnecting)
        self.assertEqual(w.poll_timer.interval(), 3000)
        (TMP / "state").write_text("Connected")
        w.poll_timer.fire()
        self.assertFalse(w.reconnecting)
        (TMP / "state").write_text("Disconnected")
        w.poll_timer.fire()
        self.assertFalse(w.connected)
        self.assertTrue(w.isVisible())                           # okno sa otvorí na prihlásenie
        self.assertIn("znova prihlásiť", w.notice.label.text())

    def test_login_failed_and_banner(self):
        w = self.make()
        self.fill(w, pw="zle")
        w.btn_connect.click()
        self.assertFalse(w.connected)
        self.assertTrue(w.steps.failed)
        self.assertIn("nový kód", w.notice.label.text())
        self.assertEqual(w.f_pw.edit.text(), "")
        os.environ["FAKE_SCENARIO"] = "banner"
        self.fill(w, pw="tajne", code="123456")
        w.btn_connect.click()
        self.assertTrue(w.connected, w.notice.label.text())

    def test_banner_declined(self):
        self.QtW.QDialog.result_code = self.QtW.QDialog.DialogCode.Rejected
        try:
            os.environ["FAKE_SCENARIO"] = "banner"
            w = self.make()
            self.fill(w, pw="tajne")
            w.btn_connect.click()
            self.assertFalse(w.connected)
            self.assertEqual(w.notice.kind, "warn")
        finally:
            self.QtW.QDialog.result_code = None

    def test_need_user_learning_and_admin_items(self):
        self.write_cfg(Polozky=[{"Cisco": "Firma A", "Nazov": "Centrála", "Auth": "HesloKod", "Predvolene": True}])
        w = self.make()
        self.assertEqual(w.selected.name, "Centrála")
        self.assertFalse(w.f_user.isVisible())
        w.f_pw.edit.setText("tajne")
        w.f_code.edit.setText("123456")
        w.btn_connect.click()
        self.assertFalse(w.connected)
        self.assertTrue(w.f_user.isVisible())                    # naučené: pýta si meno
        self.assertTrue(w.user.needs_user("Firma A"))
        self.fill(w)
        w.btn_connect.click()
        self.assertTrue(w.connected)
        w.do_disconnect()
        self.assertFalse(w.connected)
        self.assertTrue(w.login.isVisible())
        self.assertEqual((TMP / "state").read_text(), "Disconnected")

    def test_error_translated_and_manual_address(self):
        os.environ["FAKE_SCENARIO"] = "error"
        w = self.make()
        self.QtW.QInputDialog.answers.append(("vpn.example.sk", True))
        w._enter_manual_address()
        self.assertTrue(w.selected.manual)
        self.assertEqual(w.notice.kind, "warn")
        self.fill(w)
        w.btn_connect.click()
        self.assertIn("nedá kontaktovať", w.notice.label.text())
        self.assertIn("ručne zadanej", w.notice.label.text())

    def test_start_connected_and_exit_keep_vpn(self):
        (TMP / "state").write_text("Connected")
        w = self.make()
        self.assertTrue(w.connected)
        self.QtW.QMessageBox.choose.append(1)                    # „Ukončiť, VPN nechať“
        w.request_exit()
        self.assertEqual((TMP / "state").read_text(), "Connected")
        self.assertTrue(w.exiting)

    def test_no_tray(self):
        self.QtW.QSystemTrayIcon.available = False
        w = self.make()
        self.fill(w, pw="tajne")
        w.btn_connect.click()
        self.assertTrue(w.connected)
        self.assertFalse(w.btn_hide.isVisible())
        self.assertFalse(w.cd_timer.isActive())
        w.close()                                                # bez lišty: aplikácia skončí, VPN beží
        self.assertEqual((TMP / "state").read_text(), "Connected")
        self.assertTrue(any("beží ďalej" in b for _, b in self.notes))

    def test_start_hidden(self):
        from PyQt6.QtCore import run_single_shots
        from vpn_pripojenie.main_window import MainWindow
        w = MainWindow(start_hidden=True)            # štart po prihlásení, lišta je
        run_single_shots()
        self.assertFalse(w.isVisible())
        self.QtW.QSystemTrayIcon.available = False   # lišta nie je ani po 10 s → okno sa ukáže
        w2 = MainWindow(start_hidden=True)
        run_single_shots()
        self.assertTrue(w2.isVisible())
        self.assertIsNone(w2.tray)

    def test_theme_and_menu(self):
        from vpn_pripojenie import theme as TH
        w = self.make()
        w._set_theme_pref("Tmavy")
        self.assertTrue(TH.current().is_dark)
        w._set_theme_pref("Svetly")
        self.assertFalse(TH.current().is_dark)
        w._show_main_menu()
        w._show_profile_menu()

    def test_manager_save_config(self):
        w = self.make()
        w.open_manager(2)
        m = w.manager
        tab = m.p_conn
        self.assertEqual(tab.table.rowCount(), 2)
        tab.e_title.setText("VPN Firma")
        tab.table.selectRow(0)
        tab.clone()
        self.assertEqual(tab.table.rowCount(), 3)
        tab.k_keyring.setChecked(True)
        tab.e_cli.setText("/tmp/zla/cesta")
        tab.save()
        self.assertEqual(self.helper_calls, [])                 # zlá cesta k CLI sa neuloží
        tab.e_cli.setText("")
        tab.save()
        self.assertEqual(self.helper_calls[-1][0], "save-config")
        saved = json.loads((TMP / "etc" / "config.json").read_text())
        self.assertEqual(saved["NazovAplikacie"], "VPN Firma")
        self.assertEqual(len(saved["Polozky"]), 3)
        self.assertTrue(saved["PovolitKlucenku"])
        self.assertEqual(w.cfg.NazovAplikacie, "VPN Firma")       # okno prevzalo nové nastavenia
        for i in (0, 1, 3):
            m.set_tab(i)
        self.assertTrue(w.t_keyring.isVisible() or not __import__("shutil").which("secret-tool"))


    def test_untrusted_import_ca_button(self):
        os.environ["FAKE_SCENARIO"] = "untrusted"
        w = self.make()
        self.fill(w)
        self.QtW.QMessageBox.choose.append(1)                    # „Importovať CA certifikát…“
        w.btn_connect.click()
        from PyQt6.QtCore import run_single_shots
        run_single_shots()
        self.assertFalse(w.connected)
        self.assertIn("Importovať CA certifikát…", self.QtW.QMessageBox.log[-1][1])
        self.assertIsNotNone(w.manager)                          # otvorí sa karta Certifikáty
        self.assertEqual(w.manager.tabs.currentIndex(), 1)

    def test_certificate_mode_without_cert(self):
        self.write_cfg(Polozky=[{"Cisco": "Firma A", "Nazov": "Cert", "Auth": "Certifikat", "Predvolene": True}])
        w = self.make()
        self.assertEqual(w.selected.name, "Cert")
        self.assertEqual(w.notice.kind, "warn")
        self.assertIn("nie je nainštalovaný", w.notice.label.text())
        w.btn_connect.click()
        self.assertFalse(w.connecting or w.connected)            # bez certifikátu sa ani nezačne
        self.assertEqual(w.notice.kind, "error")
        self.assertIn("Importujte súbor .p12", w.notice.label.text())

    @unittest.skipUnless(__import__("shutil").which("openssl"), "chýba openssl")
    def test_certificate_mode_and_expiry_warning(self):
        import subprocess
        from vpn_pripojenie import certs
        d = certs.client_dir()
        certs.private_dir().mkdir(parents=True, exist_ok=True)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "10",
                        "-keyout", str(certs.private_dir() / "jnovak.key"), "-out", str(d / "jnovak.pem"),
                        "-subj", "/CN=jnovak"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.write_cfg(Polozky=[{"Cisco": "Firma A", "Nazov": "Cert", "Auth": "Certifikat", "Predvolene": True}])
            self.notes.clear()
            w = self.make()
            self.assertEqual(w.notice.kind, "warn")
            self.assertIn("jnovak vyprší o", w.notice.label.text())
            self.assertTrue(w._cert_notified)                               # aj notifikácia (raz za spustenie)
            w.btn_connect.click()                                          # certifikát je → pripájanie začne
            self.assertIn("Osobný certifikát: jnovak", w.log.toPlainText())
            self.write_cfg(DniUpozorneniaCertifikat=0)                     # správca vypol upozornenia
            w2 = self.make()
            self.assertNotIn("vyprší", w2.notice.label.text() if w2.notice.isVisible() else "")
        finally:
            for f in (d / "jnovak.pem", certs.private_dir() / "jnovak.key"):
                f.unlink(missing_ok=True)

    def test_connections_changed_since_last_start(self):
        from vpn_pripojenie import config as C
        st = C.UserState()
        st.ZnamePripojenia = ["Firma A", "Stara firma"]
        st.save()
        w = self.make()
        text = w.notice.label.text()
        self.assertIn("Pribudlo pripojenie: Firma B EAP+2FA", text)
        self.assertIn("Ubudlo pripojenie: Stara firma", text)
        self.assertEqual(C.UserState.load().ZnamePripojenia, ["Firma B EAP+2FA", "Firma A"])
        w2 = self.make()
        self.assertFalse(w2.notice.isVisible() and "Pribudlo" in w2.notice.label.text())

    def test_manager_profile_and_cert_reporting(self):
        w = self.make()
        w.open_manager(0)
        m = w.manager
        self.assertIn("žiadne profily", m.p_profiles.table.item(0, 0).text())
        m.set_tab(1)
        self.assertIn("žiadny osobný certifikát", m.p_certs.cl.item(0, 0).text())
        calls = []
        m.say("Test", "warn", ("Reštartovať službu Cisca  🔒", lambda: calls.append("akcia")))
        self.assertTrue(m.action.isVisible())
        m._run_action()
        self.assertEqual(calls, ["akcia"])
        self.assertFalse(m.action.isVisible())
        m.set_tab(2)
        self.assertEqual(m.p_conn.s_warn.value(), 30)
        m.p_conn.s_warn.setValue(14)
        m.p_conn.e_cli.setText("")                               # testovacia cesta k CLI nie je v /opt/cisco
        m.p_conn.save()
        saved = json.loads((TMP / "etc" / "config.json").read_text())
        self.assertEqual(saved["DniUpozorneniaCertifikat"], 14)


if __name__ == "__main__":
    unittest.main()
