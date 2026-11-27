import Foundation
import XCTest
@testable import FiremnaVPNCore

final class MessagesTests: XCTestCase {
    func testTranslate() {
        XCTAssertTrue(Messages.translate("VPN establishment capability for a remote user is disabled.")!.contains("vzdialenej"))
        XCTAssertTrue(Messages.translate("Authentication failed due to problem retrieving the single sign-on cookie")!.contains("SAML"))
        XCTAssertNil(Messages.translate("something odd"))
        XCTAssertEqual(CiscoParse.formatBytes(19818086), "18,9 MB")
        XCTAssertEqual(CiscoParse.formatDuration(3723), "01:02:03")
    }
}

final class ConfigTests: XCTestCase {
    func testIni() {
        let ini = """
        NazovAplikacie=Firemná VPN
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
        [Certifikaty]
        UpozornitDni=14
        Kontakt=Helpdesk
        Vydavatel1=Betatech|1
        Vydavatel2=Severka|0
        """
        let c = AdminConfig.parse(ini: ini)
        XCTAssertEqual(c.nazovAplikacie, "Firemná VPN")
        XCTAssertEqual(c.defaultAuthMode, .menoHeslo)
        XCTAssertEqual(c.vzhlad, "Tmavy")
        XCTAssertEqual(c.skrytPoSekundach, 5)
        XCTAssertEqual(c.polozky.map(\.cisco), ["Firma B EAP+2FA", "Firma A"])
        XCTAssertEqual(c.polozky.map(\.skryt), [false, true])
        XCTAssertEqual(c.upozornitDni, 14)
        XCTAssertEqual(c.kontakt, "Helpdesk")
        XCTAssertEqual(c.vydavatelia, [IssuerRule(text: "Betatech", on: true), IssuerRule(text: "Severka", on: false)])
        // zápis a načítanie späť
        XCTAssertEqual(AdminConfig.parse(ini: c.toIni()), c)
    }
}

final class CloneTests: XCTestCase {
    func testAuthSplitAndClone() {
        for m in AuthMode.allCases {
            XCTAssertEqual(AuthMode.join(m.base, twoFA: m.has2FA), m)
        }
        XCTAssertEqual(AuthMode.join(.menoHeslo, twoFA: false), .menoHeslo)
        XCTAssertEqual(AuthMode.join(.certifikat, twoFA: true), .certifikat)
        XCTAssertFalse(AuthMode.Base.certifikat.allows2FA)
        XCTAssertEqual(AuthMode.uniqueName("Firma A", existing: ["Firma A"]), "Firma A (2)")
        XCTAssertEqual(AuthMode.uniqueName("Firma A (2)", existing: ["Firma A", "Firma A (2)", "Firma A (3)"]), "Firma A (4)")

        // dva riadky nad tým istým pripojením Cisca: s 2FA a bez neho
        var cfg = AdminConfig()
        cfg.polozky = [ItemSettings(cisco: "Firma A", nazov: "Firma A", auth: "MenoHesloKod"),
                       ItemSettings(cisco: "Firma A", nazov: "Firma A bez 2FA", auth: "MenoHeslo")]
        let items = Profiles.buildItems(cfg: cfg, hosts: [CiscoHost(hostName: "Firma A")])
        XCTAssertEqual(items.map(\.name), ["Firma A", "Firma A bez 2FA"])
        XCTAssertEqual(items.map(\.auth), [.menoHesloKod, .menoHeslo])
        XCTAssertNotEqual(items[0].id, items[1].id)
        XCTAssertEqual(AdminConfig.parse(ini: cfg.toIni()).polozky, cfg.polozky)
    }
}

final class ProfileTests: XCTestCase {
    let xml = """
    <?xml version="1.0" encoding="UTF-8"?>
    <AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
      <ServerList>
        <HostEntry>
          <HostName>Firma A</HostName>
          <HostAddress>vpn.firma-a.example</HostAddress>
        </HostEntry>
        <HostEntry>
          <HostName>Firma B certifikát</HostName>
          <HostAddress>cert.firma-b.example</HostAddress>
          <PrimaryProtocol>IPsec
            <StandardAuthenticationOnly>true
              <AuthMethodDuringIKENegotiation>IKE-RSA</AuthMethodDuringIKENegotiation>
            </StandardAuthenticationOnly>
          </PrimaryProtocol>
        </HostEntry>
      </ServerList>
    </AnyConnectProfile>
    """

    func testParseAndBuild() {
        let r = Profiles.parse(data: Data(xml.utf8), fileName: "firma.xml")
        XCTAssertEqual(r.error, "")
        XCTAssertEqual(r.hosts.map(\.hostName), ["Firma A", "Firma B certifikát"])
        XCTAssertEqual(r.hosts[0].address, "vpn.firma-a.example")
        XCTAssertNil(r.hosts[0].guess)
        XCTAssertEqual(r.hosts[1].guess, .certifikat)

        let merged = Profiles.merge(cliNames: ["Firma B certifikát", "Iné"], xmlHosts: r.hosts)
        XCTAssertEqual(merged.map(\.hostName), ["Firma B certifikát", "Iné"])
        XCTAssertEqual(merged[0].address, "cert.firma-b.example")

        var cfg = AdminConfig()
        cfg.polozky = [ItemSettings(cisco: "Firma A", nazov: "Centrála", predvolene: true)]
        let items = Profiles.buildItems(cfg: cfg, hosts: Profiles.merge(cliNames: [], xmlHosts: r.hosts))
        XCTAssertEqual(items.map(\.name), ["Centrála", "Pripojenie 2"])
        XCTAssertEqual(items[1].auth, .certifikat)
        XCTAssertTrue(items[0].isDefault)
    }

    func testNotCisco() {
        XCTAssertFalse(Profiles.parse(data: Data("<a/>".utf8), fileName: "x.xml").error.isEmpty)
        XCTAssertFalse(Profiles.parse(data: Data("nie je xml".utf8), fileName: "x.xml").error.isEmpty)
    }
}

final class ParseTests: XCTestCase {
    func testHostsStateStats() {
        let hosts = "Cisco Secure Client (version 5.1.13.177) .\n  >> notice: Ready to connect.\n[hosts]\n  > Firma B EAP+2FA\n  > Firma A\n"
        XCTAssertEqual(CiscoParse.hosts(hosts), ["Firma B EAP+2FA", "Firma A"])
        XCTAssertEqual(CiscoParse.state("  >> state: Disconnected\n  >> state: Connected\n"), "Connected")
        let stats = """
          >> state: Connected
        [ Connection Information ]
            Connection State:           Connected
            Duration:                   01:02:03
            Client Address (IPv4):      10.20.30.40
            Server Address:             198.51.100.7
            Bytes Sent:                 4404019
            Bytes Received:             19818086
            Protocol:                   IKEv2/IPsec NAT-T
        """
        let s = CiscoParse.stats(stats)
        XCTAssertEqual(s.state, "Connected")
        XCTAssertEqual(s.duration, 3723)
        XCTAssertEqual(s.clientIP, "10.20.30.40")
        XCTAssertEqual(s.bytesReceived, 19818086)
        XCTAssertEqual(s.proto, "IKEv2/IPsec NAT-T")
    }

    func testPromptsAndQuote() {
        XCTAssertTrue(CiscoParse.ends("  >> Please enter\nUsername: [jnovak] ", #"Username:(\s*\[[^\]]*\])?"#))
        XCTAssertTrue(CiscoParse.ends("Password: ", #"Password:"#))
        XCTAssertFalse(CiscoParse.ends("Password: \n  >> Login failed.\n", #"Password:"#))
        XCTAssertEqual(CiscoParse.quoteHost("Firma A"), "\"Firma A\"")
        XCTAssertEqual(CiscoParse.quoteHost("vpn.firma.example"), "vpn.firma.example")
        XCTAssertEqual(CiscoParse.mask("heslo tajne", ["tajne"]), "heslo ********")
    }
}

final class CertLogicTests: XCTestCase {
    func d(_ s: String) -> Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone.current
        return f.date(from: s)!
    }

    func testWarningAndReplace() {
        let now = d("2026-11-22")
        let old = CertInfo(id: "A", subject: "Ján Vzorový", issuer: "Severka Issuing CA", notAfter: d("2026-12-04"))
        let other = CertInfo(id: "B", subject: "Ján Vzorový", issuer: "Iná CA", notAfter: d("2026-12-01"))
        let rules = [IssuerRule(text: "Severka", on: true), IssuerRule(text: "Gamma", on: false)]
        XCTAssertEqual(CertLogic.tracked([old, other], rules: rules).map(\.id), ["A"])
        XCTAssertEqual(CertLogic.warning([old, other], rules: rules, days: 30, now: now)?.id, "A")
        XCTAssertNil(CertLogic.warning([old], rules: rules, days: 7, now: now))
        XCTAssertEqual(CertLogic.daysLeft(old.notAfter, now: now), 12)
        XCTAssertEqual(CertLogic.inDays(12), "vyprší o 12 dní")

        let new = CertInfo(id: "C", subject: "Ján Vzorový", issuer: "Severka Issuing CA", notAfter: d("2027-11-22"))
        XCTAssertEqual(CertLogic.check(new: new, old: old, rules: rules, now: now), [])
        XCTAssertEqual(CertLogic.toRemove(after: new, in: [old, other, new]).map(\.id), ["A"])

        let wrong = CertInfo(id: "D", subject: "Iný Človek", issuer: "Gamma Labs CA", notAfter: d("2026-01-01"))
        let p = CertLogic.check(new: wrong, old: old, rules: rules, now: now)
        XCTAssertTrue(p.contains(.expired))
        XCTAssertTrue(p.contains(.untrackedIssuer("Gamma Labs CA")))
        XCTAssertTrue(p.contains(.notNewer))
        XCTAssertEqual(CertLogic.format(d("2026-12-04")), "4. 12. 2026")
    }
}

/// Pripájanie proti simulácii Cisco CLI (`tests/fake_vpn.py` – ten istý ako pre Linux verziu).
final class ConnectTests: XCTestCase {
    var dir: URL!
    var cli: CiscoCLI!

    override func setUpWithError() throws {
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let fake = repo.appendingPathComponent("tests/fake_vpn.py")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: fake.path), "chýba tests/fake_vpn.py")
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("fvpn-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let wrapper = dir.appendingPathComponent("vpn")
        try "#!/bin/sh\nexec /usr/bin/env python3 \"\(fake.path)\" \"$@\"\n".write(to: wrapper, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: wrapper.path)
        setenv("FAKE_STATE", dir.appendingPathComponent("state").path, 1)
        cli = CiscoCLI(configured: wrapper.path, timeout: 30, logURL: dir.appendingPathComponent("log.txt"))
        cli.settleSeconds = 1.5
    }

    override func tearDown() {
        unsetenv("FAKE_SCENARIO")
        try? FileManager.default.removeItem(at: dir)
    }

    let prof = VpnProfile(hostName: "Firma A", name: "Firma A", auth: .menoHeslo)

    func testSimpleCommands() {
        XCTAssertEqual(cli.version(), "5.1.13.177")
        XCTAssertEqual(cli.hosts(), ["Firma B EAP+2FA", "Firma A"])
        XCTAssertEqual(cli.state(), "Disconnected")
    }

    func testConnectOkPtyAndPipe() {
        for pty in [true, false] {
            cli.usePty = pty
            setenv("FAKE_SCENARIO", "ok", 1)
            let o = cli.connect(prof, .init(user: "jnovak", password: "tajne123456"))
            XCTAssertEqual(o.result, .connected, "pty=\(pty): \(o.error) \(o.original)")
            XCTAssertEqual(cli.state(), "Connected")
            cli.disconnect()
            XCTAssertEqual(cli.state(), "Disconnected")
        }
        let log = (try? String(contentsOf: dir.appendingPathComponent("log.txt"))) ?? ""
        XCTAssertFalse(log.contains("tajne123456"), "heslo sa nesmie dostať do logu")
    }

    func testLoginFailed() {
        setenv("FAKE_SCENARIO", "badpw", 1)
        let o = cli.connect(prof, .init(user: "jnovak", password: "zle"))
        XCTAssertEqual(o.result, .loginFailed)
    }

    func testBanner() {
        setenv("FAKE_SCENARIO", "banner", 1)
        var asked = ""
        let o = cli.connect(prof, .init(user: "jnovak", password: "tajne123456"), ask: { _, text in asked = text; return true })
        XCTAssertEqual(o.result, .connected)
        XCTAssertTrue(asked.contains("Pristup len pre opravnenych"))
        cli.disconnect()
        let d = cli.connect(prof, .init(user: "jnovak", password: "tajne123456"), ask: { _, _ in false })
        XCTAssertEqual(d.result, .declined)
    }

    /// Cisco hlási Connected, ale spojenie hneď ukončí – aplikácia nesmie ukázať „Pripojené“.
    func testConnectedThenDropped() {
        setenv("FAKE_SCENARIO", "drop", 1)
        let o = cli.connect(prof, .init(user: "jnovak", password: "tajne123456"))
        XCTAssertEqual(o.result, .failed, o.error)
        XCTAssertEqual(cli.state(), "Disconnected")
    }

    func testServerError() {
        setenv("FAKE_SCENARIO", "error", 1)
        let o = cli.connect(prof, .init(user: "jnovak", password: "tajne123456"))
        XCTAssertEqual(o.result, .failed)
        XCTAssertTrue(o.error.contains("Server sa nedá kontaktovať"), o.error)
    }

    func testUntrustedDeclined() {
        setenv("FAKE_SCENARIO", "untrusted", 1)
        var kind: AskKind?
        let o = cli.connect(prof, .init(user: "jnovak", password: "tajne123456"), ask: { k, _ in kind = k; return false })
        XCTAssertEqual(kind, .untrusted)
        XCTAssertEqual(o.result, .declined)
    }
}
