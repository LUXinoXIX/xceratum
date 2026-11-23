import AppKit
import FiremnaVPNCore
import SwiftUI
import UniformTypeIdentifiers

/// Nastavenia správcu (D1–D4): zámok macOS = overenie heslom správcu, zápis do systémového priečinka.
struct SettingsView: View {
    @EnvironmentObject var m: AppModel
    @State private var tab = "Pripojenia"
    @State private var unlocked = false
    @State private var cfg = AdminConfig()
    @State private var items: [ItemRow] = []
    @State private var selRow: UUID?
    @State private var xmlShown: ProfileFile?
    @State private var status = ""
    @State private var newIssuer = ""

    struct ItemRow: Identifiable, Equatable {
        var id = UUID()
        var cisco: String
        var name: String
        var base: AuthMode.Base
        var twoFA: Bool
        var user: String
        var show: Bool
        var isDefault: Bool
        var state: String          // nastavené | nové – skontrolujte | nový klon – uložte | zmenené – uložte | chýba v Cisco
        var auth: AuthMode { AuthMode.join(base, twoFA: twoFA) }
    }

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                ForEach(["Pripojenia", "Profily", "Certifikáty", "Všeobecné"], id: \.self) { Text($0).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 440)
            .padding(.vertical, 10)
            Divider()
            Group {
                switch tab {
                case "Pripojenia": connections
                case "Profily": profiles
                case "Certifikáty": certificates
                default: general
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .disabled(!unlocked && tab != "Profily")
            Divider()
            HStack(spacing: 10) {
                Button { toggleLock() } label: {
                    Image(systemName: unlocked ? "lock.open" : "lock").font(.system(size: 18)).frame(width: 30)
                }
                .buttonStyle(.plain)
                .help(unlocked ? "Zamknúť zmeny" : "Odomknúť heslom správcu")
                Text(status.isEmpty ? (unlocked ? "Zmeny sú povolené. Kliknutím na zámok ich zamknete."
                                                : "Na vykonanie zmien kliknite na zámok (heslo správcu).") : status)
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Zrušiť") { load(); Windows.close("settings") }
                Button("Uložiť") { save() }.keyboardShortcut(.defaultAction).disabled(!unlocked)
            }
            .padding(.horizontal, 20)
            .frame(height: 60)
        }
        .frame(width: 1060, height: 620)
        .onAppear { load() }
        .onDisappear { unlocked = false; AdminAuth.clear() }
    }

    // MARK: Pripojenia

    var ciscoHosts: [String] {
        var h = m.profileFiles.flatMap(\.hosts).map(\.hostName)
        for i in items where !h.contains(i.cisco) { h.append(i.cisco) }
        return h
    }

    var connections: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Každý riadok je jedna voľba v roletke aplikácie. Pri každom nastavte spôsob prihlásenia a či sa pridáva kód z aplikácie Authenticator (2FA). „Klonovať“ vytvorí ďalšiu voľbu nad tým istým pripojením – napr. bez 2FA alebo pre iné meno.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Table(items, selection: $selRow) {
                TableColumn("Predvolené") { r in
                    Toggle("", isOn: Binding(get: { r.isDefault }, set: { on in
                        for i in items.indices { items[i].isDefault = on && items[i].id == r.id }
                        mark(r.id)
                    })).labelsHidden().toggleStyle(.checkbox)
                }.width(70)
                TableColumn("Názov v aplikácii") { r in TextField("", text: bind(r, \.name)) }
                    .width(min: 140, ideal: 170)
                TableColumn("Pripojenie v Cisco") { r in
                    Picker("", selection: bind(r, \.cisco)) {
                        ForEach(ciscoHosts, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden()
                }.width(min: 140, ideal: 170)
                TableColumn("Prihlásenie") { r in
                    Picker("", selection: Binding(get: { r.base }, set: { b in
                        update(r.id) { $0.base = b; if !b.allows2FA { $0.twoFA = false } }
                    })) {
                        ForEach(AuthMode.Base.allCases, id: \.self) { Text($0.label).tag($0) }
                    }.labelsHidden()
                }.width(min: 130, ideal: 150)
                TableColumn("2FA kód") { r in
                    Toggle("", isOn: bind(r, \.twoFA)).labelsHidden().toggleStyle(.checkbox)
                        .disabled(!r.base.allows2FA)
                        .help("Zaškrtnite, ak sa k heslu pridáva 6-miestny kód z aplikácie Authenticator.")
                }.width(56)
                TableColumn("Meno (voliteľné)") { r in
                    TextField("", text: bind(r, \.user)).help("Predvyplní sa v okne, používateľ ho môže prepísať.")
                }.width(min: 90, ideal: 120)
                TableColumn("Zobraziť") { r in
                    Toggle("", isOn: bind(r, \.show)).labelsHidden().toggleStyle(.checkbox)
                }.width(56)
                TableColumn("Stav") { r in
                    Text(r.state).foregroundStyle(stateColor(r.state))
                }.width(min: 110, ideal: 140)
            }
            HStack {
                Button("Klonovať riadok") { cloneRow() }.disabled(selIndex == nil)
                Button("Odstrániť") { deleteRow() }.disabled(!canDelete)
                    .help("Posledná voľba pripojenia z Cisca sa dá len skryť (Zobraziť).")
                Button("▲ Hore") { move(-1) }.disabled(selIndex == nil || selIndex == 0)
                Button("▼ Dole") { move(1) }.disabled(selIndex == nil || selIndex == items.count - 1)
                Spacer()
                Button("Načítať znova z Cisca") { m.refreshProfiles(); DispatchQueue.main.asyncAfter(deadline: .now() + 2) { load() } }
            }
        }
    }

    var selIndex: Int? { items.firstIndex { $0.id == selRow } }

    var canDelete: Bool {
        guard let i = selIndex else { return false }
        if items[i].state == "chýba v Cisco" { return true }
        return items.filter { $0.cisco.lowercased() == items[i].cisco.lowercased() }.count > 1
    }

    func stateColor(_ s: String) -> Color {
        switch s {
        case "nastavené": return Color(hex: 0x0E7A0D)
        case "chýba v Cisco": return .secondary
        case "nové – skontrolujte": return Color(hex: 0xB86E00)
        default: return .accentColor
        }
    }

    func mark(_ id: UUID) {
        guard let i = items.firstIndex(where: { $0.id == id }) else { return }
        if items[i].state == "nastavené" || items[i].state == "nové – skontrolujte" { items[i].state = "zmenené – uložte" }
    }

    func update(_ id: UUID, _ f: (inout ItemRow) -> Void) {
        guard let i = items.firstIndex(where: { $0.id == id }) else { return }
        f(&items[i])
        mark(id)
    }

    func bind<T>(_ r: ItemRow, _ kp: WritableKeyPath<ItemRow, T>) -> Binding<T> {
        Binding(get: { items.first { $0.id == r.id }?[keyPath: kp] ?? r[keyPath: kp] },
                set: { v in update(r.id) { $0[keyPath: kp] = v } })
    }

    func cloneRow() {
        guard let i = selIndex else { return }
        var c = items[i]
        c.id = UUID()
        c.name = AuthMode.uniqueName(c.name, existing: items.map(\.name))
        c.isDefault = false
        c.show = true
        c.state = "nový klon – uložte"
        items.insert(c, at: i + 1)
        selRow = c.id
    }

    func deleteRow() {
        guard let i = selIndex, canDelete else { return }
        items.remove(at: i)
        selRow = items.indices.contains(i) ? items[i].id : items.last?.id
    }

    func move(_ d: Int) {
        guard let i = selIndex, i + d >= 0, i + d < items.count else { return }
        items.swapAt(i, i + d)
        mark(items[i + d].id)
    }

    // MARK: Profily

    var profiles: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("XML profily Cisca v \(Profiles.dir(forCli: m.cli.path)). Po zmene aplikácia reštartuje službu Cisca, aby ich načítala.")
                .foregroundStyle(.secondary)
            Table(m.profileFiles, selection: Binding(get: { xmlShown?.path }, set: { p in xmlShown = m.profileFiles.first { $0.path == p } })) {
                TableColumn("Súbor") { Text($0.name) }
                TableColumn("Pripojenia") { f in
                    Text(f.error.isEmpty ? f.hosts.map(\.hostName).joined(separator: ", ") : "chyba: " + f.error)
                }
            }
            .frame(minHeight: 140)
            HStack {
                Button("Pridať XML…") { addXML() }
                Button("Odstrániť") { removeXML() }.disabled(xmlShown == nil)
                Spacer()
                Button("Reštartovať službu Cisca") {
                    let r = CiscoSystem.restartService()
                    status = r.code == 0 ? "Služba Cisca bola reštartovaná." : (Shell.cancelled(r) ? "" : "Reštart sa nepodaril: \(r.out)")
                    m.refreshProfiles()
                }
            }
            if let f = xmlShown, let d = FileManager.default.contents(atPath: f.path) {
                ScrollView {
                    Text(String(decoding: d, as: UTF8.self))
                        .font(.system(size: 11, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(8)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .textBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.3)))
            }
        }
    }

    func addXML() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [UTType.xml]
        p.allowsMultipleSelection = true
        guard p.runModal() == .OK else { return }
        var cmds: [String] = []
        let dir = Profiles.dir(forCli: m.cli.path)
        for u in p.urls {
            let pf = Profiles.parse(path: u.path)
            if !pf.error.isEmpty {
                status = "\(u.lastPathComponent): \(pf.error)"
                return
            }
            cmds.append("install -m 644 \(Shell.q(u.path)) \(Shell.q(dir + "/"))")
        }
        let labels = CiscoSystem.serviceLabels.map { "launchctl kickstart -k system/\($0) 2>/dev/null" }.joined(separator: " || ")
        let r = Shell.admin("mkdir -p \(Shell.q(dir)) && " + cmds.joined(separator: " && ") + " && ((\(labels)) || true)",
                            prompt: "Firemná VPN chce pridať XML profil Cisca.")
        status = r.code == 0 ? "Profil je pridaný, služba Cisca reštartovaná." : (Shell.cancelled(r) ? "" : r.out)
        m.refreshProfiles()
    }

    func removeXML() {
        guard let f = xmlShown else { return }
        let a = NSAlert()
        a.messageText = "Odstrániť profil \(f.name)?"
        a.informativeText = "Pripojenia z neho zmiznú z roletky: \(f.hosts.map(\.hostName).joined(separator: ", "))"
        a.addButton(withTitle: "Odstrániť")
        a.addButton(withTitle: "Zrušiť")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        let r = Shell.admin("rm -f \(Shell.q(f.path))", prompt: "Firemná VPN chce odstrániť XML profil Cisca.")
        status = r.code == 0 ? "Profil je odstránený." : (Shell.cancelled(r) ? "" : r.out)
        xmlShown = nil
        m.refreshProfiles()
    }

    // MARK: Certifikáty

    var certificates: some View {
        VStack(alignment: .leading, spacing: 12) {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 10) {
                GridRow {
                    Text("Upozorniť na koniec platnosti")
                    Picker("", selection: $cfg.upozornitDni) {
                        Text("neupozorňovať").tag(0)
                        ForEach([14, 30, 60], id: \.self) { Text("\($0) dní vopred").tag($0) }
                    }.labelsHidden().frame(width: 180)
                }
                GridRow {
                    Text("Kontakt v upozornení")
                    TextField("IT oddelenie", text: $cfg.kontakt).frame(width: 280)
                }
            }
            Text("Sleduje sa len osobný certifikát v prihlasovacej kľúčenke, a len od vydavateľov nižšie (meno vydavateľa obsahuje text). Upozorňuje sa, len ak sa niektoré viditeľné pripojenie prihlasuje certifikátom.")
                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Table(cfg.vydavatelia.indices.map { IssuerRow(i: $0) }) {
                TableColumn("Sledovať") { r in
                    Toggle("", isOn: $cfg.vydavatelia[r.i].on).labelsHidden().toggleStyle(.checkbox)
                }.width(60)
                TableColumn("Vydavateľ obsahuje") { r in Text(cfg.vydavatelia[r.i].text) }
                TableColumn("Našlo sa na tomto Macu") { r in
                    let t = cfg.vydavatelia[r.i].text.lowercased()
                    let found = m.certs.filter { $0.issuer.lowercased().contains(t) }
                    Text(found.isEmpty ? "nenašiel sa"
                         : "\(found.count) osobný certifikát (najneskorší do \(CertLogic.format(found.map(\.notAfter).max()!)))")
                        .foregroundStyle(.secondary)
                }
            }
            .frame(minHeight: 120)
            HStack {
                TextField("Napr. Firma Issuing CA", text: $newIssuer).frame(width: 220)
                Button("Pridať vydavateľa") {
                    let t = newIssuer.trimmingCharacters(in: .whitespaces)
                    if !t.isEmpty { cfg.vydavatelia.append(IssuerRule(text: t, on: true)); newIssuer = "" }
                }
                Menu("Vybrať z certifikátov na Macu…") {
                    ForEach(Array(Set(m.certs.map(\.issuer))).sorted(), id: \.self) { iss in
                        Button(iss) { cfg.vydavatelia.append(IssuerRule(text: iss, on: true)) }
                    }
                }.frame(width: 240)
                Spacer()
                Button("Odstrániť posledného") { if !cfg.vydavatelia.isEmpty { cfg.vydavatelia.removeLast() } }
                    .disabled(cfg.vydavatelia.isEmpty)
            }
        }
    }

    struct IssuerRow: Identifiable { var i: Int; var id: Int { i } }

    // MARK: Všeobecné

    var general: some View {
        Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 12) {
            GridRow {
                Text("Vzhľad")
                Picker("", selection: $cfg.vzhlad) {
                    Text("Podľa systému").tag("Systemovy")
                    Text("Svetlý").tag("Svetly")
                    Text("Tmavý").tag("Tmavy")
                }.labelsHidden().frame(width: 200)
            }
            GridRow {
                Text("Heslo v Kľúčenke")
                Toggle("Povoliť ukladanie hesla v Kľúčenke", isOn: $cfg.povolitKlucenku)
            }
            GridRow {
                Text("Touch ID")
                Toggle("Vyžadovať Touch ID pred použitím uloženého hesla", isOn: $cfg.vyzadovatTouchID)
                    .disabled(!cfg.povolitKlucenku)
            }
            GridRow {
                Text("Po pripojení skryť okno")
                Picker("", selection: $cfg.skrytPoSekundach) {
                    Text("hneď").tag(0)
                    ForEach([3, 5, 10], id: \.self) { Text("o \($0) s").tag($0) }
                    Text("neskrývať").tag(-1)
                }.labelsHidden().frame(width: 160)
            }
            GridRow {
                Text("Pri výpadku")
                Toggle("Otvoriť okno na nové prihlásenie", isOn: $cfg.priOdpojeniOtvoritOkno)
            }
            GridRow {
                Text("Správa servera")
                Toggle("Potvrdiť automaticky (Accept)", isOn: $cfg.autoPrijatBanner)
            }
            GridRow {
                Text("Cisco CLI")
                TextField(m.cli.path ?? CiscoCLI.candidates[0], text: $cfg.vpnCliPath)
                    .font(.system(.body, design: .monospaced)).frame(width: 380)
            }
            GridRow {
                Text("Časový limit pripojenia")
                Picker("", selection: $cfg.connectTimeoutSeconds) {
                    ForEach([60, 90, 120], id: \.self) { Text("\($0) s").tag($0) }
                }.labelsHidden().frame(width: 120)
            }
            Divider()
            GridRow {
                Text("Režim (tento používateľ)")
                VStack(alignment: .leading, spacing: 6) {
                    Text(m.mode == "Cisco" ? "Pôvodné Cisco – okno Cisca sa spúšťa po prihlásení."
                                           : "Firemná VPN – okno Cisca je odstavené, VPN služba Cisca beží ďalej.").bold()
                    Button(m.mode == "Cisco" ? "Prepnúť na Firemnú VPN" : "Obnoviť pôvodné Cisco") {
                        m.setMode(m.mode == "Cisco" ? "FiremnaVPN" : "Cisco")
                        if m.mode == "Cisco" { status = "Pôvodné Cisco je obnovené. Firemná VPN sa po prihlásení nespustí." }
                    }
                }
            }
        }
    }

    // MARK: načítanie, zámok, uloženie

    func load() {
        cfg = m.cfg
        let known = Set(m.profileFiles.flatMap(\.hosts).map { $0.hostName.lowercased() })
        items = m.allItems.map {
            ItemRow(cisco: $0.hostName, name: $0.name, base: $0.auth.base, twoFA: $0.auth.has2FA,
                    user: $0.presetUser, show: !$0.hidden, isDefault: $0.isDefault,
                    state: !known.isEmpty && !known.contains($0.hostName.lowercased()) ? "chýba v Cisco"
                        : ($0.configured ? "nastavené" : "nové – skontrolujte"))
        }
    }

    func toggleLock() {
        if unlocked { unlocked = false; AdminAuth.clear(); return }
        AdminAuth.clear()   // vždy nové overenie heslom
        let r = Shell.admin("/usr/bin/true", prompt: "Firemná VPN chce odomknúť nastavenia pripojení.")
        unlocked = r.code == 0
        status = r.code == 0 || Shell.cancelled(r) ? "" : r.out
    }

    func save() {
        var c = cfg
        c.polozky = items.map {
            ItemSettings(cisco: $0.cisco, nazov: $0.name, auth: $0.auth.rawValue, meno: $0.user,
                         skryt: !$0.show, predvolene: $0.isDefault)
        }
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("FiremnaVPN-\(UUID().uuidString).ini")
        do { try c.toIni().write(to: tmp, atomically: true, encoding: .utf8) } catch {
            status = "Nastavenia sa nedajú pripraviť: \(error.localizedDescription)"
            return
        }
        let dir = (AdminConfig.systemPath as NSString).deletingLastPathComponent
        let r = Shell.admin("mkdir -p \(Shell.q(dir)) && install -m 644 \(Shell.q(tmp.path)) \(Shell.q(AdminConfig.systemPath))",
                            prompt: "Firemná VPN chce uložiť nastavenia pre všetkých používateľov.")
        try? FileManager.default.removeItem(at: tmp)
        if r.code == 0 {
            m.reloadConfig()
            m.refreshProfiles()
            m.applyAppearance()
            m.checkCerts(notify: false)
            unlocked = false
            AdminAuth.clear()
            status = "Nastavenia sú uložené. Platia pre všetkých používateľov tohto Macu."
        } else if !Shell.cancelled(r) {
            status = "Uloženie sa nepodarilo: \(r.out)"
        }
    }
}

extension Array {
    subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}

extension ProfileFile: Identifiable {
    public var id: String { path }
}
