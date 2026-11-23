import FiremnaVPNCore
import SwiftUI
import UniformTypeIdentifiers

let stepLabels = ["Kontaktujem server", "Overujem prihlásenie", "Nastavujem pripojenie", "Pripojené"]

struct MainView: View {
    @EnvironmentObject var m: AppModel
    @Environment(\.colorScheme) var scheme
    @FocusState private var focus: Field?
    @State private var dropTargeted = false

    var p: Palette { Palette(scheme) }

    var body: some View {
        VStack(spacing: 0) {
            header
            VStack(alignment: .leading, spacing: 12) {
                switch m.screen {
                case .login, .connecting: loginBody
                case .connected: connectedBody
                case .reconnecting: reconnectingBody
                }
            }
            .padding(.horizontal, 28)
            .padding(.top, 24)
            .padding(.bottom, 20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            footer
        }
        .frame(width: 440, height: 740)
        .background(p.window)
        .foregroundStyle(p.text)
        .ignoresSafeArea()
        .onChange(of: m.focus) { focus = $0 }
        .onChange(of: focus) { if let f = $0 { m.focus = f } }
        .onAppear { focus = m.focus }
        .onDrop(of: [UTType.fileURL], isTargeted: $dropTargeted) { providers in
            guard let pr = providers.first else { return false }
            _ = pr.loadObject(ofClass: URL.self) { url, _ in
                guard let url, ["p12", "pfx"].contains(url.pathExtension.lowercased()) else { return }
                Task { @MainActor in AppModel.shared.openReplace(url) }
            }
            return true
        }
        .sheet(isPresented: $m.replaceSheet) { ReplaceCertSheet().environmentObject(m) }
    }

    // MARK: hlavička a päta

    var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "lock.shield").font(.system(size: 36, weight: .light))
            VStack(alignment: .leading, spacing: 1) {
                Text("Firemná VPN").font(.system(size: 15, weight: .bold))
                Text("Cisco Secure Client").font(.system(size: 11)).foregroundStyle(p.headerSub)
            }
            Rectangle().fill(.white.opacity(0.55)).frame(width: 1, height: 40)
            VStack(alignment: .leading, spacing: 1) {
                Text(caption).font(.system(size: 11)).foregroundStyle(p.headerSub)
                Text(m.selected?.name ?? "—").font(.system(size: 14, weight: .semibold)).lineLimit(1)
            }
            Spacer()
            GearMenu().environmentObject(m)
        }
        .foregroundStyle(.white)
        .padding(.leading, 22)
        .padding(.trailing, 16)
        .padding(.top, 28)
        .frame(height: 112)
        .frame(maxWidth: .infinity)
        .background(p.header)
        .overlay(alignment: .bottom) { Rectangle().fill(p.line).frame(height: 1) }
    }

    var caption: String {
        switch m.screen {
        case .login: return "Pripojenie k"
        case .connecting: return "Pripájam k"
        case .connected: return "Pripojené k"
        case .reconnecting: return "Obnovujem"
        }
    }

    var footer: some View {
        HStack(spacing: 16) {
            Text(m.ciscoVersion.isEmpty ? (m.cli.available ? "Cisco Secure Client" : "Cisco Secure Client sa nenašiel")
                                        : "Cisco Secure Client \(m.ciscoVersion)")
            Spacer()
            Button("Nastavenia") { m.openRequest = "settings" }.buttonStyle(.link)
        }
        .font(.system(size: 11))
        .foregroundStyle(p.muted)
        .padding(.horizontal, 28)
        .frame(height: 36)
        .overlay(alignment: .top) { Rectangle().fill(p.line).frame(height: 1) }
    }

    // MARK: prihlásenie

    @ViewBuilder var loginBody: some View {
        let busy = m.screen == .connecting
        let prof = m.selected
        ProfileMenu().environmentObject(m).disabled(busy)
        if let prof {
            if prof.auth == .certifikat {
                certField(disabled: busy)
                NoticeBox(kind: .info, icon: "info.circle") {
                    Text("Toto pripojenie overí váš osobný certifikát z Kľúčenky. Nič nezadávate, stačí Pripojiť.")
                }
            } else {
                if prof.auth.needsUser {
                    FieldBox(icon: "person", caption: "Používateľ", error: m.fieldError == .user) {
                        TextField("", text: $m.userName)
                            .focused($focus, equals: .user)
                            .onChange(of: m.userName) { _ in m.refreshKeychainFlag() }
                    }.disabled(busy)
                }
                FieldBox(icon: "lock", caption: m.usesKeychainPassword ? "Heslo · z Kľúčenky" : "Heslo",
                         error: m.fieldError == .password, focused: focus == .password) {
                    if m.usesKeychainPassword {
                        HStack {
                            Text("••••••••••").font(.system(size: 16))
                            Spacer()
                            Button("Zabudnúť") { m.forgetKeychainPassword() }
                                .buttonStyle(.link).font(.system(size: 11))
                        }
                    } else {
                        SecureField("Zadajte heslo", text: $m.password)
                            .focused($focus, equals: .password)
                            .onSubmit { Task { await m.connect() } }
                    }
                }.disabled(busy)
                if prof.auth.needsSecond {
                    FieldBox(icon: "lock.rotation", caption: "Druhé heslo", error: m.fieldError == .second) {
                        SecureField("", text: $m.second).focused($focus, equals: .second)
                    }.disabled(busy)
                }
                if prof.auth.needsCode {
                    FieldBox(icon: "checkmark.shield", caption: "Kód z autentifikátora",
                             error: m.fieldError == .code, focused: focus == .code) {
                        TextField("", text: $m.code)
                            .font(.system(size: 18, weight: .medium, design: .monospaced))
                            .tracking(5)
                            .focused($focus, equals: .code)
                            .onChange(of: m.code) { v in
                                let d = String(v.filter(\.isNumber).prefix(6))
                                if d != v { m.code = d }
                            }
                            .onSubmit { Task { await m.connect() } }
                    }.disabled(busy)
                    Text(m.fieldError == .code ? "Zadajte 6-ciferný kód z aplikácie Authenticator."
                                               : "6 číslic z aplikácie Authenticator, mení sa každých 30 s.")
                        .font(.system(size: 12))
                        .foregroundStyle(m.fieldError == .code ? p.red : p.muted)
                        .padding(.top, -6)
                }
                if prof.auth.needsUser {
                    Toggle("Zapamätať si meno", isOn: $m.rememberUser).toggleStyle(.switch).disabled(busy)
                }
                if m.keychainAllowed {
                    Toggle("Uložiť heslo v Kľúčenke", isOn: Binding(get: { m.savePassword }, set: { m.setSavePassword($0) }))
                        .toggleStyle(.switch).disabled(busy)
                }
            }
        } else {
            NoticeBox(kind: .orange, icon: "exclamationmark.circle") {
                Text("Nenašlo sa žiadne pripojenie.").bold()
                Text("Cisco nemá XML profil. Požiadajte správcu o inštalačný balík s profilmi.")
            }
        }
        Spacer(minLength: 0)
        if busy {
            StepsView(step: m.step, failAt: nil).padding(12)
                .background(RoundedRectangle(cornerRadius: 8).fill(p.field))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(p.fieldBorder))
            Button("Zrušiť") { m.cancelConnect() }.buttonStyle(PrimaryButtonStyle(secondary: true))
        } else {
            noticeView
            Button("Pripojiť") { Task { await m.connect() } }
                .buttonStyle(PrimaryButtonStyle())
                .keyboardShortcut(.defaultAction)
                .disabled(prof == nil || !m.cli.available)
        }
    }

    func certField(disabled: Bool) -> some View {
        let c = m.currentCert
        let warn = m.certWarning != nil
        return Button { m.openRequest = "certs" } label: {
            FieldBox(icon: "rectangle.badge.checkmark", caption: "Osobný certifikát") {
                HStack {
                    Text(c.map { "\($0.subject) · do \(CertLogic.format($0.notAfter))" } ?? "Nenašiel sa – importujte ho")
                        .foregroundStyle(warn || c == nil ? p.redText : p.text)
                    Spacer()
                    Image(systemName: "chevron.right").foregroundStyle(p.muted)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(disabled)
    }

    @ViewBuilder var noticeView: some View {
        if let n = m.notice {
            switch n {
            case .outage:
                NoticeBox(kind: .orange, icon: "exclamationmark.circle") {
                    Text("Spojenie sa prerušilo a treba sa znova prihlásiť.").bold()
                    Text(outageHint)
                }
            case .touchCancelled:
                NoticeBox(kind: .info, icon: "info.circle") {
                    Text("Heslo z Kľúčenky sa nepoužilo. Zadajte ho ručne alebo kliknite Pripojiť znova.")
                }
            case let .replaced(until, removedOld):
                NoticeBox(kind: .ok, icon: "checkmark") {
                    Text("Certifikát je vymenený").bold()
                    Text("Nový platí do \(until). " + (removedOld ? "Starý bol odstránený z Kľúčenky. " : "") + "Cisco môže kľúč používať bez otázok.")
                    Text("Kliknite Pripojiť a overte, že prihlásenie funguje.")
                }
            case let .error(title, text, original):
                VStack(alignment: .leading, spacing: 10) {
                    StepsView(step: m.failAt ?? 0, failAt: m.failAt)
                    Divider().overlay(p.redBorder)
                    Text(title).bold()
                    if !text.isEmpty { Text(text) }
                    if !original.isEmpty {
                        Text("(Cisco: \(original))").font(.system(size: 11, design: .monospaced)).opacity(0.85)
                    }
                }
                .font(.system(size: 13))
                .foregroundStyle(p.redText)
                .fixedSize(horizontal: false, vertical: true)
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 8).fill(p.redBg))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(p.redBorder))
            case let .info(t):
                NoticeBox(kind: .info, icon: "info.circle") { Text(t) }
            }
        } else if m.selected?.auth == .certifikat, let w = m.certWarning {
            NoticeBox(kind: .red, icon: "exclamationmark.triangle") {
                Text("Váš certifikát \(CertLogic.inDays(CertLogic.daysLeft(w.notAfter)))").bold()
                Text("Keď vám \(m.cfg.kontaktText) pošle nový súbor (.p12), kliknite Vymeniť certifikát. Súbor môžete aj pretiahnuť sem do okna.")
                HStack(spacing: 14) {
                    Button("Vymeniť certifikát…") { m.openReplace() }
                        .buttonStyle(.borderedProminent).tint(p.red)
                    Button("Pripomenúť zajtra") { m.remindTomorrow() }.buttonStyle(.link)
                }.padding(.top, 4)
            }
        }
    }

    var outageHint: String {
        guard let prof = m.selected else { return "" }
        if prof.auth == .certifikat { return "Kliknite Pripojiť." }
        if m.usesKeychainPassword { return "Heslo je doplnené z Kľúčenky. Zadajte nový kód z autentifikátora a kliknite Pripojiť." }
        return prof.auth.needsCode ? "Zadajte heslo a nový kód z autentifikátora a kliknite Pripojiť." : "Zadajte heslo a kliknite Pripojiť."
    }

    // MARK: pripojené / obnovujem

    @ViewBuilder var connectedBody: some View {
        VStack(spacing: 10) {
            ZStack {
                Circle().fill(p.okBg).overlay(Circle().stroke(p.okBorder, lineWidth: 2))
                Image(systemName: "checkmark").font(.system(size: 40, weight: .semibold)).foregroundStyle(p.ok)
            }.frame(width: 92, height: 92)
            Text("Pripojené").font(.system(size: 22, weight: .bold))
            Text("Firemná sieť je dostupná.").font(.system(size: 13)).foregroundStyle(p.muted)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
        TimelineView(.periodic(from: .now, by: 1)) { ctx in
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 8) {
                row("Pripojenie", m.selected?.name ?? "")
                row("Server", m.stats.server.isEmpty ? (m.selected?.server ?? "") : m.stats.server)
                if m.selected?.auth != .certifikat { row("Používateľ", m.userName) }
                row("Pripojené", CiscoParse.formatDuration(Int(ctx.date.timeIntervalSince(m.connectedSince ?? ctx.date))))
                row("Adresa vo VPN", m.stats.clientIP.isEmpty ? "–" : m.stats.clientIP)
                row("Prenesené", "↓ \(CiscoParse.formatBytes(m.stats.bytesReceived)) · ↑ \(CiscoParse.formatBytes(m.stats.bytesSent))")
                if !m.stats.proto.isEmpty { row("Protokol", m.stats.proto) }
            }
            .font(.system(size: 14))
        }
        Spacer(minLength: 0)
        if m.countdown > 0 && !m.keepOpen {
            NoticeBox(kind: .info, icon: "info.circle") {
                HStack {
                    Text("Okno sa skryje o \(m.countdown) s, VPN beží ďalej v lište.")
                    Spacer()
                    Button("Nechať otvorené") { m.keepOpen = true }.buttonStyle(.link)
                }
            }
        }
        Button("Odpojiť") { m.disconnect() }.buttonStyle(PrimaryButtonStyle(secondary: true))
    }

    func row(_ k: String, _ v: String) -> some View {
        GridRow {
            Text(k).foregroundStyle(p.muted).frame(width: 110, alignment: .leading)
            Text(v).fontWeight(.medium).lineLimit(1).truncationMode(.middle)
        }
    }

    @ViewBuilder var reconnectingBody: some View {
        VStack(spacing: 10) {
            ZStack {
                Circle().fill(p.orBg).overlay(Circle().stroke(p.orBorder, lineWidth: 2))
                ProgressView().controlSize(.large)
            }.frame(width: 92, height: 92)
            Text("Obnovujem spojenie…").font(.system(size: 22, weight: .bold))
            Text("Spojenie so serverom \(m.selected?.server ?? "") vypadlo, Cisco ho obnovuje.")
                .font(.system(size: 13)).foregroundStyle(p.muted).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
        Spacer(minLength: 0)
        NoticeBox(kind: .info, icon: "info.circle") {
            Text("Ak sa spojenie neobnoví, okno vás požiada o nové prihlásenie.")
        }
        Button("Zastaviť a odpojiť") { m.disconnect() }.buttonStyle(PrimaryButtonStyle(secondary: true))
    }
}

// MARK: - súčasti

struct FieldBox<Content: View>: View {
    @Environment(\.colorScheme) var scheme
    let icon: String
    let caption: String
    var error = false
    var focused = false
    @ViewBuilder var content: Content

    var body: some View {
        let p = Palette(scheme)
        HStack(spacing: 12) {
            Image(systemName: icon).font(.system(size: 16)).foregroundStyle(p.muted).frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(caption).font(.system(size: 12)).foregroundStyle(p.muted)
                content.textFieldStyle(.plain).font(.system(size: 16, weight: .medium))
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 58)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(p.field))
        .overlay(RoundedRectangle(cornerRadius: 8)
            .stroke(error ? p.red : (focused ? p.accent : p.fieldBorder), lineWidth: error || focused ? 2 : 1))
    }
}

struct ProfileMenu: View {
    @EnvironmentObject var m: AppModel
    @Environment(\.colorScheme) var scheme

    var body: some View {
        let p = Palette(scheme)
        Menu {
            ForEach(m.visibleItems) { it in
                Button {
                    m.select(it.id)
                } label: {
                    Text(it.name + "  ·  " + it.auth.label)
                }
            }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "globe").font(.system(size: 16)).foregroundStyle(p.muted).frame(width: 22)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Pripojenie (profil)").font(.system(size: 12)).foregroundStyle(p.muted)
                    Text(m.selected?.name ?? "—").font(.system(size: 16, weight: .medium)).foregroundStyle(p.text)
                }
                Spacer()
                Image(systemName: "chevron.down").foregroundStyle(p.muted)
            }
            .padding(.horizontal, 14)
            .frame(height: 58)
            .frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: 8).fill(p.field))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(p.fieldBorder))
            .contentShape(Rectangle())
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
    }
}

struct StepsView: View {
    @Environment(\.colorScheme) var scheme
    let step: Int
    let failAt: Int?

    var body: some View {
        let p = Palette(scheme)
        HStack(alignment: .top, spacing: 0) {
            ForEach(0..<4, id: \.self) { i in
                VStack(spacing: 5) {
                    ZStack {
                        if failAt == i {
                            Circle().fill(p.red)
                            Image(systemName: "xmark").font(.system(size: 10, weight: .bold)).foregroundStyle(.white)
                        } else if i < step || (step == 3 && i == 3) {
                            Circle().fill(p.accent)
                            Image(systemName: "checkmark").font(.system(size: 10, weight: .bold)).foregroundStyle(p.onAccent)
                        } else if i == step && failAt == nil {
                            Circle().stroke(p.accent, lineWidth: 2)
                            ProgressView().controlSize(.mini)
                        } else {
                            Circle().stroke(p.fieldBorder, lineWidth: 2)
                        }
                    }
                    .frame(width: 22, height: 22)
                    Text(stepLabels[i])
                        .font(.system(size: 11, weight: i <= step ? .semibold : .regular))
                        .foregroundStyle(failAt == i ? p.redText : (i <= step ? p.text : p.muted))
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity)
            }
        }
    }
}

struct GearMenu: View {
    @EnvironmentObject var m: AppModel
    var body: some View {
        Menu {
            MenuItems().environmentObject(m)
        } label: {
            Image(systemName: "gearshape").font(.system(size: 18)).foregroundStyle(.white)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .frame(width: 44, height: 44)
    }
}
