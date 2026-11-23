import AppKit
import FiremnaVPNCore
import SwiftUI

@main
struct FiremnaVPNApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel.shared

    var body: some Scene {
        Window("Firemná VPN", id: "main") {
            MainView().environmentObject(model)
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
        .defaultPosition(.center)

        Window("Nastaviť pripojenia – Firemná VPN", id: "settings") {
            SettingsView().environmentObject(model)
        }
        .windowResizability(.contentSize)

        Window("Certifikáty – Firemná VPN", id: "certs") {
            CertificatesView().environmentObject(model)
        }
        .windowResizability(.contentSize)

        MenuBarExtra {
            MenuItems().environmentObject(model)
        } label: {
            MenuBarLabel().environmentObject(model)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Režim „pôvodné Cisco“: Firemná VPN sa po prihlásení nespúšťa (LaunchAgent ju môže ešte zavolať).
        if UserDefaults.standard.string(forKey: "rezim") == "Cisco",
           ProcessInfo.processInfo.arguments.contains("--pri-prihlaseni") {
            NSApp.terminate(nil)
            return
        }
        NSApp.setActivationPolicy(.accessory)
        Task { @MainActor in AppModel.shared.start() }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    /// Dvojklik na .p12 / pretiahnutie na ikonu aplikácie → výmena certifikátu.
    func application(_ application: NSApplication, open urls: [URL]) {
        guard let u = urls.first(where: { ["p12", "pfx"].contains($0.pathExtension.lowercased()) }) else { return }
        Task { @MainActor in AppModel.shared.openReplace(u) }
    }
}

/// Ikona v lište – žije stále, preto otvára okná, o ktoré požiada model.
struct MenuBarLabel: View {
    @EnvironmentObject var m: AppModel
    @Environment(\.openWindow) var openWindow

    var body: some View {
        Image(systemName: icon)
            .onChange(of: m.openRequest) { req in
                guard let req else { return }
                openWindow(id: req)
                NSApp.activate(ignoringOtherApps: true)
                m.openRequest = nil
            }
    }

    var icon: String {
        switch m.screen {
        case .connected: return m.certWarning != nil ? "lock.shield.fill" : "lock.shield.fill"
        case .connecting, .reconnecting: return "shield.lefthalf.filled"
        case .login: return (m.notice == .outage || m.certWarning != nil) ? "exclamationmark.shield" : "shield"
        }
    }
}

/// Ponuka v lište aj pod kolieskom v okne.
struct MenuItems: View {
    @EnvironmentObject var m: AppModel
    @Environment(\.openWindow) var openWindow

    var body: some View {
        Text(statusLine)
        if m.screen == .connected {
            Text("\(m.selected?.server ?? "") · \(m.stats.clientIP)")
        }
        if let w = m.certWarning {
            Text("Certifikát \(CertLogic.inDays(CertLogic.daysLeft(w.notAfter))) (\(CertLogic.format(w.notAfter)))")
        }
        Divider()
        if m.screen == .connected || m.screen == .reconnecting {
            Button("Odpojiť") { m.disconnect() }
        } else {
            Button("Pripojiť…") { open("main") }.disabled(m.screen != .login)
        }
        Button("Otvoriť okno") { open("main") }
        Divider()
        if m.certWarning != nil {
            Button("Vymeniť certifikát…") { m.openReplace(); open("main") }
        }
        Button("Certifikáty…") { open("certs") }
        Button("Nastaviť pripojenia…") { open("settings") }
        Menu("Vzhľad") {
            Button("Podľa systému") { setLook("") }
            Button("Svetlý") { setLook("Svetly") }
            Button("Tmavý") { setLook("Tmavy") }
        }
        Button("Otvoriť log") { NSWorkspace.shared.open(m.cli.logURL) }
        Divider()
        if m.mode == "Cisco" {
            Button("Prepnúť na Firemnú VPN") { m.setMode("FiremnaVPN") }
        } else {
            Button("Obnoviť pôvodné Cisco") { m.setMode("Cisco") }
        }
        Button("Ukončiť Firemnú VPN") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }

    var statusLine: String {
        switch m.screen {
        case .connected: return "Pripojené k \(m.selected?.name ?? "")"
        case .connecting: return "Pripájam…"
        case .reconnecting: return "Obnovujem spojenie…"
        case .login: return m.notice == .outage ? "Spojenie sa prerušilo" : "Nepripojené"
        }
    }

    func open(_ id: String) {
        openWindow(id: id)
        NSApp.activate(ignoringOtherApps: true)
    }

    func setLook(_ v: String) {
        m.userState.vzhlad = v
        m.userState.save()
        m.applyAppearance()
    }
}
