"""Testy jadra bez GUI: Cisco CLI (simulácia), profily, nastavenia, certifikáty, pomocný skript.

Spustenie:  python3 -m unittest discover -s tests -v
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="vpnp-test-"))
(TMP / "home").mkdir(parents=True)
(TMP / "etc").mkdir()
ENV = {"HOME": str(TMP / "home"), "XDG_CONFIG_HOME": str(TMP / "home/.config"),
       "XDG_STATE_HOME": str(TMP / "home/.local/state"), "VPN_PRIPOJENIE_ETC": str(TMP / "etc")}
os.environ.update(ENV)


def setUpModule():
    os.environ.update(ENV)   # iný testovací modul mohol prepísať prostredie

from vpn_pripojenie import certs, config as C, messages, profiles  # noqa: E402
from vpn_pripojenie.cisco import CiscoCli, Result, format_bytes, quote_host  # noqa: E402
from vpn_pripojenie.config import AuthMode  # noqa: E402

FAKE = TMP / "bin" / "vpn"
FAKE.parent.mkdir()
FAKE.write_text(f"#!/bin/sh\nexec {sys.executable} {ROOT / 'tests' / 'fake_vpn.py'} \"$@\"\n")
FAKE.chmod(0o755)

PROFILE_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
      <ServerList>
        <HostEntry>
          <HostName>Firma B EAP+2FA</HostName>
          <HostAddress>vpn.firma-b.example</HostAddress>
          <PrimaryProtocol>IPsec
            <StandardAuthenticationOnly>true
              <AuthMethodDuringIKENegotiation>EAP-MD5</AuthMethodDuringIKENegotiation>
            </StandardAuthenticationOnly>
          </PrimaryProtocol>
        </HostEntry>
        <HostEntry>
          <HostName>Certifikat</HostName>
          <HostAddress>cert.example.sk</HostAddress>
          <PrimaryProtocol>IPsec
            <StandardAuthenticationOnly>true
              <AuthMethodDuringIKENegotiation>IKE-RSA</AuthMethodDuringIKENegotiation>
            </StandardAuthenticationOnly>
          </PrimaryProtocol>
        </HostEntry>
      </ServerList>
    </AnyConnectProfile>
    """)


def prof(host="Firma A", auth=AuthMode.MENO_HESLO_KOD, **kw):
    return profiles.VpnProfile(host_name=host, name=host, auth=auth, **kw)


class CiscoTests(unittest.TestCase):
    def setUp(self):
        self.state = TMP / "state"
        self.state.write_text("Disconnected")
        os.environ["FAKE_STATE"] = str(self.state)
        os.environ["FAKE_PW"] = "tajne123456"
        self.cli = CiscoCli(str(FAKE), use_pty=True, timeout=20)
        self.out = []
        self.steps = []

    def connect(self, scenario, password="tajne123456", user="jnovak", p=None, ask=lambda k, t: True, pty=True,
                **kw):
        os.environ["FAKE_SCENARIO"] = scenario
        self.cli.use_pty = pty
        return self.cli.connect(p or prof(), user, password, "", progress=lambda s, m: self.steps.append(s),
                                output=self.out.append, ask=ask, **kw)

    def test_simple_commands(self):
        self.assertEqual(self.cli.version(), "5.1.13.177")
        self.assertEqual(self.cli.hosts(), ["Firma B EAP+2FA", "Firma A"])
        self.assertEqual(self.cli.state(), "Disconnected")
        self.state.write_text("Connected")
        st = self.cli.stats()
        self.assertEqual(st.state, "Connected")
        self.assertEqual(st.client_ip, "10.20.30.40")
        self.assertEqual(st.duration, 3723)
        self.assertEqual(st.bytes_received, 19818086)
        self.assertEqual(st.protocol, "IKEv2/IPsec NAT-T")
        self.assertEqual(st.tunnel_mode, "Tunnel All Traffic")
        self.assertEqual(st.routes, ["10.0.0.0 /8", "192.168.50.0 /24"])

    def test_connect_ok_pty_and_pipe(self):
        for pty in (True, False):
            self.state.write_text("Disconnected")
            out = self.connect("ok", pty=pty)
            self.assertEqual(out.result, Result.CONNECTED, out)
            self.assertIn(3, self.steps)
            self.assertIn(4, self.steps)
        text = "".join(self.out)
        self.assertNotIn("tajne123456", text)
        log = C.log_path().read_text()
        self.assertNotIn("tajne123456", log)
        self.assertIn("********", log)

    def test_banner_accept_and_decline(self):
        seen = []
        out = self.connect("banner", ask=lambda k, t: (seen.append((k, t)), True)[1])
        self.assertEqual(out.result, Result.CONNECTED)
        self.assertEqual(seen[0][0], "banner")
        self.assertIn("opravnenych", seen[0][1])
        self.state.write_text("Disconnected")
        out = self.connect("banner", ask=lambda k, t: False)
        self.assertEqual(out.result, Result.DECLINED)
        self.state.write_text("Disconnected")
        out = self.connect("banner", ask=lambda k, t: self.fail("nemalo sa pýtať"), auto_banner=True)
        self.assertEqual(out.result, Result.CONNECTED)

    def test_untrusted(self):
        kinds = []
        out = self.connect("untrusted", ask=lambda k, t: (kinds.append(k), False)[1])
        self.assertEqual(kinds, ["untrusted"])
        self.assertEqual(out.result, Result.DECLINED)

    def test_login_failed(self):
        out = self.connect("badpw", password="zle")
        self.assertEqual(out.result, Result.LOGIN_FAILED)

    def test_error_translated(self):
        out = self.connect("error")
        self.assertEqual(out.result, Result.FAILED)
        self.assertIn("Server sa nedá kontaktovať", out.error)
        self.assertIn("failed", out.original.lower())

    def test_need_user(self):
        out = self.connect("ok", user="", p=prof(auth=AuthMode.HESLO_KOD))
        self.assertEqual(out.result, Result.NEED_USER)

    def test_group_prompt(self):
        out = self.connect("group", p=prof(group="Zamestnanci"))
        self.assertEqual(out.result, Result.CONNECTED)
        self.assertIn("  → Zamestnanci\n", self.out)

    def test_cancel(self):
        out = self.connect("unknown", cancelled=lambda: len(self.out) > 3)
        self.assertEqual(out.result, Result.CANCELLED)

    def test_quote_host(self):
        self.assertEqual(quote_host("Firma B EAP+2FA"), '"Firma B EAP+2FA"')
        self.assertEqual(quote_host('"Firma A"'), '"Firma A"')
        self.assertEqual(quote_host('"FirmaA"'), 'FirmaA')


class ProfileConfigTests(unittest.TestCase):
    def test_parse_and_build(self):
        d = TMP / "profiles"
        d.mkdir(exist_ok=True)
        (d / "firma-b.xml").write_text(PROFILE_XML)
        (d / "zly.xml").write_text("<html/>")
        files = profiles.list_profile_files([d])
        good = next(f for f in files if f.path.name == "firma-b.xml")
        self.assertEqual([h.host_name for h in good.hosts], ["Firma B EAP+2FA", "Certifikat"])
        self.assertEqual(good.hosts[0].protocol, "IPsec")
        self.assertIsNone(good.hosts[0].guess)
        self.assertEqual(good.hosts[1].guess, AuthMode.CERTIFIKAT)
        self.assertTrue(next(f for f in files if f.path.name == "zly.xml").error)

        hosts = profiles.merge_hosts(["Firma B EAP+2FA", "Firma A"], good.hosts)
        cfg = C.AdminConfig.from_dict({"Polozky": [
            {"Cisco": "Firma A", "Nazov": "Centrála", "Auth": "Heslo", "Predvolene": True},
            {"Cisco": "Stare", "Nazov": "Zrušené"}]})
        items = profiles.build_items(cfg, hosts)
        self.assertEqual([i.name for i in items], ["Centrála", "Zrušené", "Pripojenie 1"])
        self.assertTrue(items[0].is_default and items[1].missing)
        self.assertEqual(items[2].address, "vpn.firma-b.example")
        self.assertFalse(items[0].needs_user() or items[0].needs_code)
        self.assertTrue(items[2].needs_code)

    def test_windows_ini(self):
        (TMP / "etc" / "FiremnaVPN.ini").write_text(textwrap.dedent("""\
            ; komentár
            NazovAplikacie=VPN Pripojenie Firma
            DefaultAuth=MenoHeslo
            [Polozka 1]
            Cisco=Firma B EAP+2FA
            Nazov=Firma B
            Auth=MenoHesloKod
            Predvolene=1
            [Pripojenie:Firma A]
            Nazov=Centrála
            Skryt=áno
            [Vseobecne]
            Vzhlad=Tmavy
            SkrytPoSekundach=5 ; komentár
            """), encoding="utf-8")
        cfg = C.AdminConfig.load()
        self.assertEqual(cfg.NazovAplikacie, "VPN Pripojenie Firma")
        self.assertEqual(cfg.default_auth, AuthMode.MENO_HESLO)
        self.assertEqual(cfg.Vzhlad, "Tmavy")
        self.assertEqual(cfg.SkrytPoSekundach, 5)
        self.assertEqual([(i.Cisco, i.Nazov, i.Skryt) for i in cfg.Polozky],
                         [("Firma B EAP+2FA", "Firma B", False), ("Firma A", "Centrála", True)])
        # JSON má prednosť a dá sa načítať späť
        (TMP / "etc" / "config.json").write_text(cfg.to_json())
        again = C.AdminConfig.load()
        self.assertEqual(again.to_dict(), cfg.to_dict())
        (TMP / "etc" / "config.json").unlink()
        (TMP / "etc" / "FiremnaVPN.ini").unlink()

    def test_user_state(self):
        st = C.UserState.load()
        st.Meno = "jnovak"
        st.learn_needs_user("Firma A")
        st.save()
        again = C.UserState.load()
        self.assertEqual(again.Meno, "jnovak")
        self.assertTrue(again.needs_user("firma a"))
        mode = stat.S_IMODE(C.UserState.path().stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_messages(self):
        self.assertIn("vzdialenej", messages.translate("VPN establishment capability for a remote user is disabled."))
        self.assertIn("SAML", messages.translate("Authentication failed due to problem retrieving the single sign-on cookie"))
        self.assertIsNone(messages.translate("something odd"))
        self.assertEqual(format_bytes(19818086), "18,9 MB")


@unittest.skipUnless(shutil.which("openssl"), "chýba openssl")
class CertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = TMP / "pki"
        d.mkdir()
        cls.d = d

        def ossl(*a, **kw):
            subprocess.run(["openssl", *a], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)

        ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "ca.key"), "-out", str(d / "ca.pem"),
             "-days", "3650", "-subj", "/CN=Firma Root CA")
        ossl("x509", "-in", str(d / "ca.pem"), "-outform", "DER", "-out", str(d / "ca.crt"))
        ossl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "user.key"), "-out", str(d / "user.csr"),
             "-subj", "/CN=Ján Novák")
        ossl("x509", "-req", "-in", str(d / "user.csr"), "-CA", str(d / "ca.pem"), "-CAkey", str(d / "ca.key"),
             "-CAcreateserial", "-out", str(d / "user.pem"), "-days", "365")
        ossl("pkcs12", "-export", "-in", str(d / "user.pem"), "-inkey", str(d / "user.key"), "-certfile",
             str(d / "ca.pem"), "-out", str(d / "user.p12"), "-passout", "pass:Heslo 123")

    def test_ca_der(self):
        dest = certs.import_ca_user(self.d / "ca.crt")
        self.assertTrue(dest.name.startswith("Firma_Root_CA"))
        info = certs.list_ca()[0]
        self.assertEqual(info.cn, "Firma Root CA")
        self.assertFalse(info.expired)
        with self.assertRaises(certs.CertError):
            certs.to_pem(self.d / "user.csr")

    def test_p12(self):
        with self.assertRaises(certs.CertError) as e:
            certs.import_p12(self.d / "user.p12", "zle")
        self.assertIn("heslo", str(e.exception))
        path, n_ca = certs.import_p12(self.d / "user.p12", "Heslo 123")
        self.assertEqual(n_ca, 1)
        key = certs.private_dir() / (path.stem + ".key")
        self.assertTrue(key.is_file())
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertIn(b"PRIVATE KEY", key.read_bytes())
        self.assertNotIn(b"Bag Attributes", path.read_bytes())
        cl = certs.list_client()
        self.assertEqual(len(cl), 1)
        self.assertTrue(cl[0].has_key)
        self.assertIn("Nov", cl[0].cn)
        certs.remove_client(path)
        self.assertFalse(key.exists())


    def test_details_issuer_duplicates(self):
        info = certs.inspect(self.d / "user.pem")
        self.assertEqual(info.issuer_cn, "Firma Root CA")
        self.assertTrue(info.serial)
        self.assertIsNotNone(info.not_before)
        self.assertGreater(info.days_left, 300)
        ca = certs.inspect(self.d / "ca.pem")
        self.assertTrue(certs.issuer_installed(info, [ca]))
        self.assertFalse(certs.issuer_installed(info, []))
        dup = self.d / "kopia.pem"
        shutil.copy(self.d / "user.pem", dup)
        d = certs.duplicates([info, certs.inspect(dup), ca])
        self.assertEqual(d[info.path], ["kopia.pem"])
        self.assertNotIn(ca.path, d)
        from vpn_pripojenie.prehlad import import_summary
        text = import_summary(info, self.d / "user.pem", 0, [], 30)
        self.assertIn("Vydal: Firma Root CA", text)
        self.assertIn("nie je nainštalovaná", text)
        self.assertNotIn("nie je nainštalovaná", import_summary(info, self.d / "user.pem", 1, [ca], 30))


class OverviewTests(unittest.TestCase):
    """Čo okno hlási o profiloch a certifikátoch (stav, zmeny, vypršanie)."""

    def files(self):
        a = profiles.ProfileFile(Path("a.xml"), [profiles.CiscoHost("Firma A", "vpn.firma-a.example", "a.xml"),
                                                  profiles.CiscoHost("Firma C", "", "a.xml")])
        b = profiles.ProfileFile(Path("b.xml"), [profiles.CiscoHost("Firma B", "", "b.xml"),
                                                  profiles.CiscoHost("firma a", "", "b.xml")])
        return [a, b]

    def test_host_states(self):
        cfg = C.AdminConfig.from_dict({"Polozky": [{"Cisco": "Firma B", "Skryt": True},
                                                   {"Cisco": "Firma A", "Predvolene": True}]})
        st = profiles.host_states(self.files(), ["Firma A", "Firma B"], cfg)
        self.assertTrue(st[("a.xml", "Firma A")].startswith("v roletke (predvolené)"))
        self.assertIn("rovnaký názov aj v b.xml", st[("a.xml", "Firma A")])
        self.assertIn("nenačítal", st[("a.xml", "Firma C")])
        self.assertEqual(st[("b.xml", "Firma B")], "skryté správcom")
        off = profiles.host_states(self.files(), None, cfg)
        self.assertTrue(all("služba Cisca nebeží" in t for t in off.values()))
        self.assertEqual(profiles.not_loaded(self.files()[0], ["FIRMA A"]), ["Firma C"])

    def test_changes_and_describe(self):
        self.assertEqual(profiles.changes(["Firma A", "Firma B"], ["firma a", "Firma C"]), (["Firma C"], ["Firma B"]))
        self.assertEqual(profiles.changes([], []), ([], []))
        p = prof("Firma A", AuthMode.CERTIFIKAT, address="vpn.firma-a.example", xml_file="a.xml", protocol="IPsec")
        text = profiles.describe(p)
        self.assertIn("Profil: a.xml", text)
        self.assertIn("IPsec", text)
        self.assertIn("odhad", text)
        self.assertIn("Ručne", profiles.describe(profiles.manual_item("vpn.firma.sk", C.AdminConfig())))

    def test_expiry(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        def ci(cn, days, key=True):
            return certs.CertInfo(Path(cn + ".pem"), subject=f"CN={cn}", not_after=now + timedelta(days=days, hours=1),
                                  has_key=key)
        soon, old, fine, ca_soon = ci("jnovak", 12), ci("stary", -3), ci("novy", 200), ci("Firma CA", 20)
        w = certs.expiry_warnings(30, [soon, old, fine], [ca_soon])
        self.assertEqual(w[0][0], "error")
        self.assertIn("stary vypršal", w[0][1])
        self.assertTrue(any("jnovak vyprší o 12 dní" in t for _, t in w))
        self.assertTrue(any("Firma CA" in t for _, t in w))
        self.assertFalse(any("novy" in t for _, t in w))
        self.assertEqual([t for _, t in certs.expiry_warnings(10, [soon], [ca_soon])], [])
        self.assertEqual(certs.expiry_warnings(0, [old], []), [])           # 0 = neupozorňovať
        self.assertIn("vyprší o 2 dni", certs.describe_expiry(ci("x", 2)))
        self.assertIn("EXPIROVANÝ", certs.describe_expiry(old))
        self.assertTrue(soon.usable)
        self.assertFalse(old.usable)
        self.assertFalse(ci("bez", 100, key=False).usable)

    def test_warn_days_setting(self):
        self.assertEqual(C.AdminConfig().DniUpozorneniaCertifikat, 30)
        self.assertEqual(C.AdminConfig.from_dict({"DniUpozorneniaCertifikat": 900}).DniUpozorneniaCertifikat, 365)
        self.assertEqual(C.AdminConfig.from_dict({"DniUpozorneniaCertifikat": "14"}).DniUpozorneniaCertifikat, 14)
        cfg = C.AdminConfig._from_ini("[Vseobecne]\nDniUpozorneniaCertifikat=60\n")
        self.assertEqual(cfg.DniUpozorneniaCertifikat, 60)
        helper = (ROOT / "helper" / "vpn-pripojenie-helper").read_text()
        self.assertIn('"DniUpozorneniaCertifikat"', helper)       # pomocný skript ho prijme pri ukladaní
        self.assertIn("DniUpozorneniaCertifikat", C.AdminConfig().to_dict())

    def test_removal_question(self):
        from types import SimpleNamespace
        from vpn_pripojenie.prehlad import removal_question
        xml = TMP / "odstranit.xml"
        xml.write_text(PROFILE_XML)
        cfg = C.AdminConfig.from_dict({"Polozky": [{"Cisco": "Certifikat", "Nazov": "Firma Cert", "Predvolene": True}]})
        main = SimpleNamespace(cfg=cfg, connected=True, selected=prof("Firma B EAP+2FA"))
        q = removal_question(xml, main)
        self.assertIn("zmiznú pripojenia: Firma B EAP+2FA, Certifikat", q)
        self.assertIn("Práve ste pripojený", q)
        self.assertIn("Firma Cert – predvolené", q)
        main.connected = False
        self.assertNotIn("Práve ste pripojený", removal_question(xml, main))

class HelperTests(unittest.TestCase):
    """Validácia v pomocnom skripte (bez roota – len kontroly pred zápisom)."""

    def run_helper(self, *args):
        return subprocess.run([sys.executable, "-I", str(ROOT / "helper" / "vpn-pripojenie-helper"), *args],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_requires_root(self):
        if os.geteuid() == 0:
            self.skipTest("beží ako root")
        p = self.run_helper("restart-agent")
        self.assertEqual(p.returncode, 1)
        self.assertIn("správcu", p.stderr)

    @unittest.skipUnless(os.geteuid() == 0, "len ako root")
    def test_rejects_bad_input(self):
        env_bad = [("install-profile", "/etc/shadow", "/opt/cisco/secureclient/vpn/profile"),
                   ("install-profile", str(TMP / "x.xml"), "/tmp"),
                   ("remove-profile", "../../etc/passwd.xml", "/opt/cisco/secureclient/vpn/profile"),
                   ("save-config", "/etc/shadow")]
        for args in env_bad:
            p = self.run_helper(*args)
            self.assertNotEqual(p.returncode, 0, args)


if __name__ == "__main__":
    unittest.main()
