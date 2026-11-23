import AppKit
import CryptoKit
import FiremnaVPNCore
import Foundation
import LocalAuthentication
import Security
import UserNotifications

// MARK: - príkazy

enum Shell {
    struct Result { var code: Int32; var out: String }

    @discardableResult
    static func run(_ path: String, _ args: [String], env: [String: String] = [:]) -> Result {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        if !env.isEmpty {
            p.environment = ProcessInfo.processInfo.environment.merging(env) { _, new in new }
        }
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch { return Result(code: -1, out: error.localizedDescription) }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return Result(code: p.terminationStatus, out: String(decoding: data, as: UTF8.self))
    }

    /// Text v jednoduchých úvodzovkách pre /bin/sh.
    static func q(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }

    /// Záloha bez pomocníka: príkaz s právami správcu po zadaní mena a hesla správcu (pozri `Admin`).
    @MainActor
    static func admin(_ command: String, prompt: String) -> Result {
        if AdminAuth.valid == nil {
            guard AdminAuth.ask(prompt) else { return Result(code: -128, out: "User canceled.") }
        }
        guard let c = AdminAuth.valid else { return Result(code: -128, out: "User canceled.") }
        let r = AdminAuth.run(command, user: c.user, password: c.password)
        if r.code != 0 && AdminAuth.isAuthError(r) { AdminAuth.clear() }
        return r
    }

    static func cancelled(_ r: Result) -> Bool { r.out.contains("-128") || r.out.lowercased().contains("user canceled") }
}

// MARK: - overenie správcu: Touch ID, záloha meno a heslo správcu

@MainActor
enum AdminAuth {
    struct Creds { var user: String; var password: String; var at: Date }
    private static var creds: Creds?
    static let validFor: TimeInterval = 5 * 60

    static var valid: Creds? {
        guard let c = creds, Date().timeIntervalSince(c.at) < validFor else { creds = nil; return nil }
        return c
    }

    static func clear() { creds = nil }

    static func asq(_ s: String) -> String {
        "\"" + s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }

    static func run(_ command: String, user: String, password: String) -> Shell.Result {
        let src = "do shell script \(asq(command)) user name \(asq(user)) password \(asq(password)) with administrator privileges"
        var err: NSDictionary?
        let out = NSAppleScript(source: src)?.executeAndReturnError(&err)
        if let err {
            let n = (err[NSAppleScript.errorNumber] as? Int) ?? -1
            let msg = (err[NSAppleScript.errorMessage] as? String) ?? "chyba \(n)"
            return Shell.Result(code: Int32(truncatingIfNeeded: n), out: msg)
        }
        return Shell.Result(code: 0, out: out?.stringValue ?? "")
    }

    static func isAuthError(_ r: Shell.Result) -> Bool {
        let l = r.out.lowercased()
        return r.code == -60005 || r.code == -60007 || l.contains("password") || l.contains("heslo")
    }

    /// Okno „meno a heslo správcu“. Overí heslo hneď (`true`); pri zlom hesle sa pýta znova.
    static func ask(_ prompt: String) -> Bool {
        var message = prompt
        while true {
            let a = NSAlert()
            a.messageText = message
            a.informativeText = "Zadajte meno a heslo správcu tohto Macu."
            a.addButton(withTitle: "Odomknúť")
            a.addButton(withTitle: "Zrušiť")
            let user = NSTextField(string: NSUserName())
            user.placeholderString = "Meno správcu"
            let pass = NSSecureTextField(string: "")
            pass.placeholderString = "Heslo"
            for f in [user, pass] as [NSTextField] {
                f.translatesAutoresizingMaskIntoConstraints = false
                f.widthAnchor.constraint(equalToConstant: 260).isActive = true
            }
            let stack = NSStackView(views: [user, pass])
            stack.orientation = .vertical
            stack.spacing = 8
            stack.frame = NSRect(x: 0, y: 0, width: 260, height: 56)
            a.accessoryView = stack
            a.window.initialFirstResponder = pass
            NSApp.activate(ignoringOtherApps: true)
            guard a.runModal() == .alertFirstButtonReturn else { return false }
            let r = run("/usr/bin/true", user: user.stringValue, password: pass.stringValue)
            if r.code == 0 {
                creds = Creds(user: user.stringValue, password: pass.stringValue, at: Date())
                return true
            }
            message = "Meno alebo heslo správcu nesedí. Skúste znova."
        }
    }
}

/// Akcie správcu. Hlavná cesta: Touch ID (alebo heslo Macu) a potom `sudo -n` na úzky pomocník,
/// ktorý nainštaloval balík (pravidlo v /etc/sudoers.d/firemnavpn pre skupinu admin).
/// Ak pomocník nie je (alebo používateľ nie je správca), aplikácia si vypýta meno a heslo správcu.
@MainActor
enum Admin {
    static let helper = "/Library/PrivilegedHelperTools/firemnavpn-helper"
    private static var until: Date?
    static let validFor: TimeInterval = 5 * 60

    static var unlocked: Bool { (until ?? .distantPast) > Date() }

    static func helperReady() -> Bool {
        FileManager.default.isExecutableFile(atPath: helper)
            && Shell.run("/usr/bin/sudo", ["-n", helper, "test"]).code == 0
    }

    static func lock() {
        until = nil
        AdminAuth.clear()
    }

    /// Odomknutie: Touch ID; bez pomocníka meno a heslo správcu.
    static func unlock(_ reason: String) async -> Bool {
        if unlocked { return true }
        if helperReady() {
            let ctx = LAContext()
            ctx.localizedFallbackTitle = "Zadať heslo"
            var err: NSError?
            if ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &err),
               (try? await ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) == true {
                until = Date().addingTimeInterval(validFor)
                return true
            }
            return false
        }
        AdminAuth.clear()
        if AdminAuth.ask("Firemná VPN chce \(reason).") {
            until = Date().addingTimeInterval(validFor)
            return true
        }
        return false
    }

    /// Akcia cez pomocníka; `fallback` je ten istý krok ako príkaz pre shell (cesta bez pomocníka).
    static func perform(_ action: [String], fallback: String, reason: String) async -> Shell.Result {
        guard await unlock(reason) else { return Shell.Result(code: -128, out: "User canceled.") }
        if helperReady() {
            return Shell.run("/usr/bin/sudo", ["-n", helper] + action)
        }
        return Shell.admin(fallback, prompt: "Firemná VPN chce \(reason).")
    }

    static func restartCisco() async -> Shell.Result {
        let labels = CiscoSystem.serviceLabels.map { "launchctl kickstart -k system/\($0) 2>/dev/null" }.joined(separator: " || ")
        return await perform(["restart-cisco"], fallback: "(\(labels)) || true", reason: "reštartovať službu Cisca")
    }
}

// MARK: - heslo v Kľúčenke + Touch ID

enum PasswordStore {
    static let service = "FiremnaVPN"

    static func account(_ prof: VpnProfile, _ user: String) -> String { prof.hostName + "|" + user.lowercased() }

    static func base(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    static func exists(_ account: String) -> Bool {
        var q = base(account)
        q[kSecReturnAttributes as String] = true
        return SecItemCopyMatching(q as CFDictionary, nil) == errSecSuccess
    }

    static func read(_ account: String) -> String? {
        var q = base(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var res: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &res) == errSecSuccess, let d = res as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    @discardableResult
    static func save(_ account: String, _ password: String) -> Bool {
        let data = Data(password.utf8)
        let st = SecItemUpdate(base(account) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if st == errSecSuccess { return true }
        var q = base(account)
        q[kSecValueData as String] = data
        q[kSecAttrLabel as String] = "Firemná VPN – heslo"
        return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
    }

    static func delete(_ account: String) { SecItemDelete(base(account) as CFDictionary) }

    /// Touch ID (alebo heslo Macu) pred použitím uloženého hesla.
    static func authenticate(_ reason: String) async -> Bool {
        let ctx = LAContext()
        var err: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &err) else { return true }
        return (try? await ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) ?? false
    }
}

// MARK: - osobné certifikáty (prihlasovacia kľúčenka)

enum ImportResult {
    case ok(CertInfo?, removed: Int)
    case wrongPassword
    case needsConfirm([ReplaceProblem], CertInfo)
    case failed(String)
}

enum CertStore {
    /// Aplikácie Cisca, ktoré smú používať súkromný kľúč bez otázky Kľúčenky (overiť na Macu – mac-vetva.md).
    static var ciscoApps: [String] {
        [
            "/opt/cisco/secureclient/bin/vpn",
            "/opt/cisco/secureclient/bin/vpnagentd",
            "/opt/cisco/secureclient/bin/Cisco Secure Client - AnyConnect VPN Service.app",
            "/Applications/Cisco/Cisco Secure Client.app",
            "/opt/cisco/anyconnect/bin/vpn",
            "/opt/cisco/anyconnect/bin/vpnagentd",
            "/Applications/Cisco/Cisco AnyConnect Secure Mobility Client.app",
        ].filter { FileManager.default.fileExists(atPath: $0) }
    }

    static var loginKeychain: String {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Keychains/login.keychain-db").path
    }

    static func info(_ cert: SecCertificate, hasKey: Bool) -> CertInfo {
        let subject = (SecCertificateCopySubjectSummary(cert) as String?) ?? "?"
        var issuer = ""
        var notAfter = Date.distantPast
        let keys = [kSecOIDX509V1IssuerName, kSecOIDX509V1ValidityNotAfter] as CFArray
        if let vals = SecCertificateCopyValues(cert, keys, nil) as? [String: Any] {
            if let na = vals[kSecOIDX509V1ValidityNotAfter as String] as? [String: Any],
               let v = na[kSecPropertyKeyValue as String] as? NSNumber {
                notAfter = Date(timeIntervalSinceReferenceDate: v.doubleValue)
            }
            if let iss = vals[kSecOIDX509V1IssuerName as String] as? [String: Any],
               let arr = iss[kSecPropertyKeyValue as String] as? [[String: Any]] {
                for e in arr where (e[kSecPropertyKeyLabel as String] as? String) == "2.5.4.3" {
                    issuer = (e[kSecPropertyKeyValue as String] as? String) ?? ""
                }
                if issuer.isEmpty, let o = arr.first(where: { ($0[kSecPropertyKeyLabel as String] as? String) == "2.5.4.10" }) {
                    issuer = (o[kSecPropertyKeyValue as String] as? String) ?? ""
                }
            }
        }
        let der = SecCertificateCopyData(cert) as Data
        let sha1 = Insecure.SHA1.hash(data: der).map { String(format: "%02X", $0) }.joined()
        return CertInfo(id: sha1, subject: subject, issuer: issuer, notAfter: notAfter, hasKey: hasKey)
    }

    /// Identity (certifikát + súkromný kľúč) v kľúčenkách používateľa.
    static func identities() -> [CertInfo] {
        let q: [String: Any] = [kSecClass as String: kSecClassIdentity,
                                kSecMatchLimit as String: kSecMatchLimitAll,
                                kSecReturnRef as String: true]
        var res: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &res) == errSecSuccess, let arr = res as? [SecIdentity] else { return [] }
        var out: [CertInfo] = []
        for idt in arr {
            var cert: SecCertificate?
            if SecIdentityCopyCertificate(idt, &cert) == errSecSuccess, let c = cert {
                let i = info(c, hasKey: true)
                if !out.contains(where: { $0.id == i.id }) { out.append(i) }
            }
        }
        return out.sorted { $0.notAfter > $1.notAfter }
    }

    /// Údaje z .p12 bez importu (systémové `openssl`, heslo cez premennú prostredia, nie v príkazovom riadku).
    static func peek(_ file: URL, password: String) -> (CertInfo?, wrongPassword: Bool) {
        let env = ["FVPN_P12": password]
        let r = Shell.run("/usr/bin/openssl", ["pkcs12", "-in", file.path, "-passin", "env:FVPN_P12", "-nokeys", "-clcerts"], env: env)
        if r.code != 0 {
            let low = r.out.lowercased()
            return (nil, low.contains("mac verify") || low.contains("invalid password") || low.contains("bad decrypt"))
        }
        guard let begin = r.out.range(of: "-----BEGIN CERTIFICATE-----"),
              let end = r.out.range(of: "-----END CERTIFICATE-----", range: begin.upperBound..<r.out.endIndex) else { return (nil, false) }
        let b64 = r.out[begin.upperBound..<end.lowerBound].filter { !$0.isWhitespace }
        guard let der = Data(base64Encoded: String(b64)), let cert = SecCertificateCreateWithData(nil, der as CFData) else { return (nil, false) }
        return (info(cert, hasKey: true), false)
    }

    /// Výmena / import osobného certifikátu.
    static func importP12(_ file: URL, password: String, deleteOld: Bool, rules: [IssuerRule], confirmed: Bool) -> ImportResult {
        let before = identities()
        let (peeked, wrong) = peek(file, password: password)
        if wrong { return .wrongPassword }
        if let new = peeked, !confirmed {
            let old = CertLogic.current(before.filter { $0.subject.lowercased() == new.subject.lowercased() }, rules: [])
                ?? CertLogic.current(before, rules: rules)
            let problems = CertLogic.check(new: new, old: old, rules: rules)
            if !problems.isEmpty { return .needsConfirm(problems, new) }
        }
        // `security import` neberie heslo z prostredia; je v príkazovom riadku len na okamih importu.
        var args = ["import", file.path, "-k", loginKeychain, "-f", "pkcs12", "-P", password]
        for app in ciscoApps { args += ["-T", app] }
        let r = Shell.run("/usr/bin/security", args)
        if r.code != 0 {
            let low = r.out.lowercased()
            if low.contains("mac verification") || low.contains("passphrase") || low.contains("wrong password") { return .wrongPassword }
            if low.contains("already exists") {
                return .ok(peeked, removed: 0)
            }
            return .failed(r.out.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        let after = identities()
        let new = after.first { a in !before.contains { $0.id == a.id } } ?? peeked
        var removed = 0
        if deleteOld, let n = new {
            for old in CertLogic.toRemove(after: n, in: after) where delete(old) { removed += 1 }
        }
        return .ok(new, removed: removed)
    }

    @discardableResult
    static func delete(_ c: CertInfo) -> Bool {
        Shell.run("/usr/bin/security", ["delete-identity", "-Z", c.id, loginKeychain]).code == 0
    }

    /// CA, ktoré nainštaloval balík (kópie v /Library/Application Support/FiremnaVPN/ca).
    static func packagedCAs() -> [CertInfo] {
        let dir = "/Library/Application Support/FiremnaVPN/ca"
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: dir) else { return [] }
        var out: [CertInfo] = []
        for n in names.sorted() {
            guard let d = FileManager.default.contents(atPath: dir + "/" + n) else { continue }
            var der = d
            let s = String(decoding: d, as: UTF8.self)
            if let b = s.range(of: "-----BEGIN CERTIFICATE-----"),
               let e = s.range(of: "-----END CERTIFICATE-----", range: b.upperBound..<s.endIndex),
               let dd = Data(base64Encoded: String(s[b.upperBound..<e.lowerBound].filter { !$0.isWhitespace })) {
                der = dd
            }
            if let c = SecCertificateCreateWithData(nil, der as CFData) { out.append(info(c, hasKey: false)) }
        }
        return out
    }

    static func openKeychainAccess() {
        let ws = NSWorkspace.shared
        if let u = ws.urlForApplication(withBundleIdentifier: "com.apple.keychainaccess") {
            ws.openApplication(at: u, configuration: NSWorkspace.OpenConfiguration())
        }
    }
}

// MARK: - služba a okno Cisca (launchd)

enum CiscoSystem {
    static let serviceLabels = [
        "com.cisco.secureclient.vpn.service.agent",   // 5.1
        "com.cisco.secureclient.vpnagentd",           // 5.0
        "com.cisco.anyconnect.vpnagentd",             // 4.x
    ]
    static let guiLabels = ["com.cisco.secureclient.gui", "com.cisco.anyconnect.gui"]
    static var uid: String { String(getuid()) }

    static func serviceLabel() -> String? {
        serviceLabels.first { Shell.run("/bin/launchctl", ["print", "system/\($0)"]).code == 0 }
    }

    /// Je okno Cisca vypnuté pre tohto používateľa?
    static func guiDisabled() -> Bool {
        let out = Shell.run("/bin/launchctl", ["print-disabled", "gui/\(uid)"]).out
        return guiLabels.contains { label in
            out.split(separator: "\n").contains { l in
                l.contains("\"\(label)\"") && (l.contains("disabled") || l.contains("true"))
            }
        }
    }

    /// Režim Firemná VPN: okno Cisca sa po prihlásení nespúšťa, VPN služba Cisca beží ďalej.
    static func disableCiscoGUI() {
        for l in guiLabels {
            Shell.run("/bin/launchctl", ["bootout", "gui/\(uid)/\(l)"])
            Shell.run("/bin/launchctl", ["disable", "gui/\(uid)/\(l)"])
        }
        Shell.run("/bin/launchctl", ["enable", "gui/\(uid)/\(AppInfo.agentLabel)"])
    }

    /// Režim pôvodné Cisco: okno Cisca späť, Firemná VPN sa sama nespúšťa.
    static func enableCiscoGUI() {
        for l in guiLabels { Shell.run("/bin/launchctl", ["enable", "gui/\(uid)/\(l)"]) }
        Shell.run("/bin/launchctl", ["disable", "gui/\(uid)/\(AppInfo.agentLabel)"])
        for app in ["/Applications/Cisco/Cisco Secure Client.app", "/Applications/Cisco/Cisco AnyConnect Secure Mobility Client.app"]
        where FileManager.default.fileExists(atPath: app) {
            NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: app), configuration: NSWorkspace.OpenConfiguration())
            break
        }
    }
}

// MARK: - hlásenia (Centrum hlásení)

enum Notify {
    static func setup() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    static func post(_ title: String, _ body: String, id: String = UUID().uuidString) {
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = body
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: id, content: c, trigger: nil))
    }
}

enum AppInfo {
    static let agentLabel = "org.xceratum.firemnavpn"
    static var version: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "vývoj"
    }
}
