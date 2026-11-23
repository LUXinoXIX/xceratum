import AppKit
import FiremnaVPNCore
import Foundation
import SwiftUI

enum Screen: Equatable { case login, connecting, connected, reconnecting }

enum Notice: Equatable {
    case outage
    case touchCancelled
    case replaced(until: String, removedOld: Bool)
    case error(title: String, text: String, original: String)
    case info(String)
}

enum Field: Hashable { case user, password, code, second }

final class CancelFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var v = false
    var value: Bool {
        get { lock.lock(); defer { lock.unlock() }; return v }
        set { lock.lock(); v = newValue; lock.unlock() }
    }
}

@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    // nastavenia
    @Published var cfg = AdminConfig.load()
    @Published var userState = UserState.load()
    private(set) var cli: CiscoCLI

    // pripojenia
    @Published var allItems: [VpnProfile] = []
    @Published var selectedID = ""
    @Published var profileFiles: [ProfileFile] = []
    @Published var ciscoVersion = ""

    // prihlásenie
    @Published var userName = ""
    @Published var password = ""
    @Published var code = ""
    @Published var second = ""
    @Published var rememberUser = true
    @Published var savePassword = true
    @Published var passwordInKeychain = false
    @Published var focus: Field? = .code
    @Published var fieldError: Field?

    // stav
    @Published var screen: Screen = .login
    @Published var step = 0
    @Published var failAt: Int?
    @Published var notice: Notice?
    @Published var stats = Stats()
    @Published var connectedSince: Date?
    @Published var countdown = 0
    @Published var keepOpen = false
    @Published var lastMessage = ""

    // certifikáty
    @Published var certs: [CertInfo] = []
    @Published var certWarning: CertInfo?
    @Published var replaceSheet = false
    @Published var droppedFile: URL?

    // okná (otvára ich MenuBarLabel, ktorý žije stále)
    @Published var openRequest: String?

    private var cancel = CancelFlag()
    private var userDisconnect = false
    private var pollTimer: Timer?
    private var certTimer: Timer?
    private var countdownTimer: Timer?
    private var notifiedCertDay = ""

    var visibleItems: [VpnProfile] { allItems.filter { !$0.hidden } }
    var selected: VpnProfile? { allItems.first { $0.id == selectedID } ?? visibleItems.first }
    var keychainAllowed: Bool { cfg.povolitKlucenku }
    var usesKeychainPassword: Bool {
        guard let p = selected else { return false }
        return keychainAllowed && savePassword && passwordInKeychain && p.auth.needsPassword
    }
    /// Režim pre tohto používateľa: „FiremnaVPN“ (okno Cisca odstavené) alebo „Cisco“ (pôvodné okno).
    @Published var mode = UserDefaults.standard.string(forKey: "rezim") ?? "FiremnaVPN"

    private init() {
        cli = CiscoCLI(configured: "", timeout: 90)
        reloadConfig()
        rememberUser = userState.zapamatatMeno
        savePassword = userState.ulozitHeslo
        if rememberUser { userName = userState.meno }
        if !userState.posledne.isEmpty, allItems.contains(where: { $0.id == userState.posledne }) {
            selectedID = userState.posledne
        }
        refreshKeychainFlag()
        applyAppearance()
    }

    // MARK: štart

    func start() {
        Notify.setup()
        applyAppearance()
        if mode == "FiremnaVPN" {
            if !CiscoSystem.guiDisabled() { CiscoSystem.disableCiscoGUI() }
        }
        pollTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in
            Task { @MainActor in AppModel.shared.poll() }
        }
        certTimer = Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { _ in
            Task { @MainActor in AppModel.shared.checkCerts(notify: true) }
        }
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { _ in
            Task { @MainActor in
                AppModel.shared.checkCerts(notify: true)
                AppModel.shared.poll()
            }
        }
        checkCerts(notify: true)
        refreshProfiles()
        poll()
    }

    func reloadConfig() {
        cfg = AdminConfig.load()
        cli = CiscoCLI(configured: cfg.vpnCliPath, timeout: cfg.connectTimeoutSeconds)
        rebuildItems(cliNames: [])
    }

    func refreshProfiles() {
        let c = cli
        Task.detached {
            let names = c.hosts()
            let ver = c.version()
            await MainActor.run {
                self.ciscoVersion = ver
                self.rebuildItems(cliNames: names)
            }
        }
    }

    func rebuildItems(cliNames: [String]) {
        profileFiles = Profiles.listFiles()
        let xml = profileFiles.flatMap(\.hosts)
        let hosts = Profiles.merge(cliNames: cliNames, xmlHosts: xml)
        allItems = Profiles.buildItems(cfg: cfg, hosts: hosts)
        if selected == nil || !visibleItems.contains(where: { $0.id == selectedID }) {
            selectedID = (visibleItems.first { $0.isDefault } ?? visibleItems.first)?.id ?? ""
        }
        refreshKeychainFlag()
    }

    func select(_ id: String) {
        selectedID = id
        failAt = nil
        notice = nil
        fieldError = nil
        if let p = selected, !p.presetUser.isEmpty { userName = p.presetUser }
        refreshKeychainFlag()
        focus = selected?.auth.needsCode == true ? .code : (usesKeychainPassword ? nil : .password)
    }

    func refreshKeychainFlag() {
        guard let p = selected, !userName.isEmpty else { passwordInKeychain = false; return }
        passwordInKeychain = keychainAllowed && PasswordStore.exists(PasswordStore.account(p, userName))
    }

    func applyAppearance() {
        let v = userState.vzhlad.isEmpty ? cfg.vzhlad : userState.vzhlad
        switch v.lowercased() {
        case "svetly": NSApp?.appearance = NSAppearance(named: .aqua)
        case "tmavy": NSApp?.appearance = NSAppearance(named: .darkAqua)
        default: NSApp?.appearance = nil
        }
    }

    func setSavePassword(_ on: Bool) {
        savePassword = on
        userState.ulozitHeslo = on
        userState.save()
        if !on, let p = selected, !userName.isEmpty {
            PasswordStore.delete(PasswordStore.account(p, userName))
            passwordInKeychain = false
            password = ""
        }
    }

    func forgetKeychainPassword() {
        if let p = selected, !userName.isEmpty { PasswordStore.delete(PasswordStore.account(p, userName)) }
        passwordInKeychain = false
        password = ""
        focus = .password
    }

    // MARK: pripojenie

    func connect() async {
        guard let prof = selected, screen == .login else { return }
        fieldError = nil
        var pw = password
        if prof.auth.needsUser && userName.trimmingCharacters(in: .whitespaces).isEmpty {
            fieldError = .user; focus = .user; return
        }
        if prof.auth.needsPassword && !usesKeychainPassword && password.isEmpty {
            fieldError = .password; focus = .password; return
        }
        if prof.auth.needsCode && code.count != 6 {
            fieldError = .code; focus = .code; return
        }
        if prof.auth.needsSecond && second.isEmpty {
            fieldError = .second; focus = .second; return
        }
        if prof.auth.needsPassword && usesKeychainPassword {
            if cfg.vyzadovatTouchID {
                let ok = await PasswordStore.authenticate("použiť heslo k VPN uložené v Kľúčenke")
                if !ok {
                    passwordInKeychain = false
                    notice = .touchCancelled
                    focus = .password
                    return
                }
            }
            pw = PasswordStore.read(PasswordStore.account(prof, userName)) ?? ""
            if pw.isEmpty { passwordInKeychain = false; fieldError = .password; focus = .password; return }
        }

        let cred = CiscoCLI.Credentials(user: prof.auth.needsUser || !userName.isEmpty ? userName : "",
                                        // heslo a 2FA kód spolu, ako v okne Cisca
                                        password: prof.auth.needsPassword ? pw + (prof.auth.needsCode ? code : "") : "",
                                        second: prof.auth.needsSecond ? second : "")
        screen = .connecting
        step = 0
        failAt = nil
        notice = nil
        userDisconnect = false
        cancel = CancelFlag()
        let flag = cancel
        let c = cli
        let autoBanner = cfg.autoPrijatBanner
        let outcome: Outcome = await Task.detached {
            c.connect(prof, cred,
                      progress: { s, m in Task { @MainActor in AppModel.shared.step = s; AppModel.shared.lastMessage = m } },
                      ask: { kind, text in
                          DispatchQueue.main.sync { Prompts.ask(kind, text) }
                      },
                      cancelled: { flag.value },
                      autoBanner: autoBanner)
        }.value
        finish(outcome, prof: prof, typedPassword: pw, fromKeychain: usesKeychainPassword)
    }

    private func finish(_ o: Outcome, prof: VpnProfile, typedPassword: String, fromKeychain: Bool) {
        code = ""
        switch o.result {
        case .connected:
            screen = .connected
            step = 3
            connectedSince = Date()
            userState.zapamatatMeno = rememberUser
            userState.meno = rememberUser ? userName : ""
            userState.posledne = prof.id
            userState.save()
            if keychainAllowed && savePassword && prof.auth.needsPassword && !fromKeychain && !typedPassword.isEmpty {
                if PasswordStore.save(PasswordStore.account(prof, userName), typedPassword) {
                    passwordInKeychain = true
                }
            }
            password = ""
            Notify.post("Pripojené", "VPN \(prof.name) je pripojená.", id: "stav")
            startCountdown()
            poll()
        case .cancelled:
            screen = .login
            step = 0
        case .loginFailed:
            screen = .login
            failAt = 1
            var text = "Skontrolujte meno a heslo. Kód z autentifikátora platí len 30 sekúnd, zadajte nový."
            if fromKeychain {
                text += " Ak ste si zmenili heslo, kliknite na „Zabudnúť uložené heslo“ a zadajte nové."
            }
            notice = .error(title: "Prihlásenie sa nepodarilo.", text: text, original: o.original)
            focus = .code
        case .needUser:
            screen = .login
            fieldError = .user
            focus = .user
            notice = .error(title: "Pripojenie si pýta meno.", text: "Zadajte používateľské meno a kliknite Pripojiť.", original: "")
        case .otherClient, .declined, .failed:
            screen = .login
            failAt = step
            notice = .error(title: o.error.isEmpty ? "Pripojenie sa nepodarilo." : o.error,
                            text: o.result == .otherClient ? "Okno Cisca bolo zatvorené. Skúste znova." : "",
                            original: o.original)
        }
    }

    func cancelConnect() { cancel.value = true }

    func disconnect() {
        userDisconnect = true
        countdownTimer?.invalidate()
        let c = cli
        Task.detached {
            c.disconnect()
            await MainActor.run {
                AppModel.shared.screen = .login
                AppModel.shared.step = 0
                AppModel.shared.connectedSince = nil
                AppModel.shared.focus = .code
                Notify.post("Odpojené", "VPN je odpojená.", id: "stav")
            }
        }
    }

    private func startCountdown() {
        keepOpen = false
        countdownTimer?.invalidate()
        guard cfg.skrytPoSekundach >= 0 else { countdown = 0; return }
        countdown = max(cfg.skrytPoSekundach, 1)
        countdownTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            Task { @MainActor in AppModel.shared.tick() }
        }
    }

    private func tick() {
        if keepOpen || screen != .connected {
            countdown = 0
            countdownTimer?.invalidate()
            return
        }
        countdown -= 1
        if countdown <= 0 {
            countdownTimer?.invalidate()
            Windows.close("main")
        }
    }

    /// Stav Cisca každých 5 s – rozpozná výpadok aj pripojenie zvonka.
    func poll() {
        guard screen != .connecting else { return }
        let c = cli
        Task.detached {
            let st = c.stats()
            await MainActor.run { AppModel.shared.applyState(st) }
        }
    }

    private func applyState(_ st: Stats) {
        let s = st.state.lowercased()
        switch screen {
        case .connected:
            if s == "connected" {
                stats = st
            } else if s == "reconnecting" {
                screen = .reconnecting
            } else if s == "disconnected" && !userDisconnect {
                outage()
            }
        case .reconnecting:
            if s == "connected" {
                screen = .connected
                stats = st
            } else if s == "disconnected" {
                outage()
            }
        case .login:
            if s == "connected" {
                screen = .connected
                stats = st
                if connectedSince == nil, let d = st.duration { connectedSince = Date().addingTimeInterval(-Double(d)) }
            }
        case .connecting:
            break
        }
    }

    private func outage() {
        screen = .login
        notice = .outage
        failAt = nil
        code = ""
        focus = .code
        connectedSince = nil
        refreshKeychainFlag()
        Notify.post("Spojenie sa prerušilo", "Treba sa znova prihlásiť. Zadajte nový kód z autentifikátora.", id: "stav")
        if cfg.priOdpojeniOtvoritOkno { openRequest = "main" }
    }

    // MARK: certifikáty

    var certProfilesVisible: Bool { visibleItems.contains { $0.auth == .certifikat } }

    func checkCerts(notify: Bool) {
        certs = CertStore.identities()
        var w = CertLogic.warning(certs, rules: cfg.vydavatelia, days: cfg.upozornitDni)
        if !certProfilesVisible { w = nil }
        if let until = userState.pripomenutPo, until > Date() { w = nil }
        certWarning = w
        if notify, let w {
            let day = CertLogic.format(Date())
            if day != notifiedCertDay {
                notifiedCertDay = day
                Notify.post("Certifikát pre VPN \(CertLogic.inDays(CertLogic.daysLeft(w.notAfter)))",
                            "Platí do \(CertLogic.format(w.notAfter)). Keď vám \(cfg.kontaktText) pošle nový súbor .p12, otvorte Firemnú VPN a kliknite Vymeniť certifikát.",
                            id: "certifikat")
            }
        }
    }

    var currentCert: CertInfo? { CertLogic.current(certs, rules: cfg.vydavatelia) }

    func remindTomorrow() {
        userState.pripomenutPo = Calendar.current.date(byAdding: .day, value: 1, to: Calendar.current.startOfDay(for: Date()))
        userState.save()
        certWarning = nil
    }

    func openReplace(_ file: URL? = nil) {
        droppedFile = file
        if let p = allItems.first(where: { $0.auth == .certifikat && !$0.hidden }) { selectedID = p.id }
        openRequest = "main"
        replaceSheet = true
    }

    func replaced(_ c: CertInfo?, removed: Int) {
        userState.pripomenutPo = nil
        userState.save()
        checkCerts(notify: false)
        let until = c.map { CertLogic.format($0.notAfter) } ?? "–"
        notice = .replaced(until: until, removedOld: removed > 0)
        failAt = nil
        Notify.post("Certifikát vymenený", "Nový platí do \(until).", id: "certifikat")
    }
}

extension AppModel {
    func setMode(_ m: String) {
        mode = m
        UserDefaults.standard.set(m, forKey: "rezim")
        if m == "Cisco" {
            CiscoSystem.enableCiscoGUI()
        } else {
            CiscoSystem.disableCiscoGUI()
        }
    }
}

/// Otázky Cisca počas pripájania (volá sa z vlákna pripájania cez DispatchQueue.main.sync).
enum Prompts {
    static func ask(_ kind: AskKind, _ text: String) -> Bool? {
        let a = NSAlert()
        NSApp.activate(ignoringOtherApps: true)
        if kind == .untrusted {
            a.messageText = "Server sa nedá overiť"
            a.informativeText = "Cisco hlási nedôveryhodný server. Pripojte sa, len ak to potvrdí IT oddelenie.\n\n" + text
            a.alertStyle = .critical
            a.addButton(withTitle: "Nepripájať")
            a.addButton(withTitle: "Pripojiť aj tak")
            return a.runModal() == .alertSecondButtonReturn
        }
        a.messageText = "Správa servera"
        a.informativeText = text
        a.addButton(withTitle: "Prijať")
        a.addButton(withTitle: "Neprijať")
        return a.runModal() == .alertFirstButtonReturn
    }
}

/// Otváranie a zatváranie okien SwiftUI z modelu.
enum Windows {
    static func find(_ id: String) -> NSWindow? {
        NSApp.windows.first { ($0.identifier?.rawValue ?? "").hasPrefix(id) && $0.isVisible }
    }

    static func close(_ id: String) { find(id)?.close() }
}
