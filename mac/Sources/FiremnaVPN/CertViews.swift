import AppKit
import FiremnaVPNCore
import SwiftUI
import UniformTypeIdentifiers

/// Hárok „Vymeniť osobný certifikát“ (F2–F4 na plátne).
struct ReplaceCertSheet: View {
    @EnvironmentObject var m: AppModel
    @Environment(\.dismiss) var dismiss
    @State private var file: URL?
    @State private var password = ""
    @State private var deleteOld = true
    @State private var busy = false
    @State private var wrongPassword = false
    @State private var problems: [ReplaceProblem] = []
    @State private var newCert: CertInfo?
    @State private var failure = ""
    @State private var dropTargeted = false
    @FocusState private var pwFocus: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Vymeniť osobný certifikát").font(.system(size: 16, weight: .bold))
            HStack(spacing: 12) {
                Image(systemName: "rectangle.badge.checkmark").font(.system(size: 20)).foregroundStyle(Color(hex: 0x1F4A86))
                VStack(alignment: .leading, spacing: 2) {
                    Text(file?.lastPathComponent ?? "Pretiahnite sem súbor .p12 / .pfx").fontWeight(.semibold)
                    Text(file == nil ? "ktorý vám poslal \(m.cfg.kontaktText), alebo" : "Pretiahnite iný súbor alebo")
                        .font(.system(size: 12)).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Vybrať…") { pick() }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 10).fill(dropTargeted ? Color(hex: 0xE4EDFA) : Color(hex: 0xF4F7FB)))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color(hex: 0x9AB0CF), style: StrokeStyle(lineWidth: 1.5, dash: [5, 4])))
            .onDrop(of: [UTType.fileURL], isTargeted: $dropTargeted) { providers in
                guard let pr = providers.first else { return false }
                _ = pr.loadObject(ofClass: URL.self) { url, _ in
                    if let url { Task { @MainActor in setFile(url) } }
                }
                return true
            }

            VStack(alignment: .leading, spacing: 2) {
                Text("Heslo k súboru (od IT, neukladá sa)").font(.system(size: 11)).foregroundStyle(.secondary)
                SecureField("", text: $password)
                    .textFieldStyle(.plain)
                    .font(.system(size: 15))
                    .focused($pwFocus)
                    .onSubmit { run(confirmed: false) }
            }
            .padding(.horizontal, 12)
            .frame(height: 50)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(wrongPassword ? Color(hex: 0xB10E1C) : Color(hex: 0x1F4A86), lineWidth: 2))
            .disabled(file == nil || busy)

            if wrongPassword {
                box(red: true) {
                    Text("Heslo k súboru nesedí.").bold()
                    Text("Skontrolujte veľké a malé písmená. Heslo ste dostali od IT spolu so súborom (často iným kanálom, napr. SMS). Starý certifikát ostáva.")
                }
            }
            if !problems.isEmpty {
                box(red: true) {
                    Text("Skontrolujte, či je to správny certifikát").bold()
                    ForEach(problems.indices, id: \.self) { Text("• " + problems[$0].text) }
                    Text("Starý certifikát ostáva, kým výmenu nepotvrdíte.")
                }
            }
            if !failure.isEmpty {
                box(red: true) {
                    Text("Import sa nepodaril.").bold()
                    Text(failure).font(.system(size: 11, design: .monospaced))
                }
            }
            if let old = m.currentCert {
                Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 5) {
                    if let n = newCert {
                        GridRow { Text("Nový").foregroundStyle(.secondary); Text("\(n.subject) · platí do \(CertLogic.format(n.notAfter))").bold() }
                        GridRow { Text("Vydal").foregroundStyle(.secondary); Text(n.issuer) }
                    }
                    GridRow { Text("Nahradí").foregroundStyle(.secondary); Text("\(old.subject) · do \(CertLogic.format(old.notAfter))") }
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(hex: 0xDFE5EE)))
            }
            Text("Po zadaní hesla sa skontroluje: rovnaký používateľ, sledovaný vydavateľ, platnosť. Aplikácia povolí Ciscu používať kľúč.")
                .font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Toggle("Po úspešnom importe odstrániť starý certifikát", isOn: $deleteOld).toggleStyle(.checkbox)
            HStack {
                if busy { ProgressView().controlSize(.small); Text("Importujem…").foregroundStyle(.secondary) }
                Spacer()
                Button("Zrušiť") { dismiss() }.keyboardShortcut(.cancelAction)
                if problems.isEmpty {
                    Button("Vymeniť") { run(confirmed: false) }
                        .keyboardShortcut(.defaultAction)
                        .disabled(file == nil || password.isEmpty || busy)
                } else {
                    Button("Vymeniť aj tak") { run(confirmed: true) }.disabled(busy)
                }
            }
        }
        .font(.system(size: 13))
        .padding(20)
        .frame(width: 408)
        .onAppear {
            if let f = m.droppedFile { setFile(f) }
        }
    }

    func box<C: View>(red: Bool, @ViewBuilder _ c: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 4) { c() }
            .foregroundStyle(Color(hex: 0x8A0B16))
            .fixedSize(horizontal: false, vertical: true)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: 0xFDF3F4)))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(hex: 0xEEACB2)))
    }

    func setFile(_ url: URL) {
        guard ["p12", "pfx"].contains(url.pathExtension.lowercased()) else {
            failure = "Potrebujem súbor .p12 alebo .pfx (osobný certifikát s kľúčom)."
            return
        }
        file = url
        failure = ""
        wrongPassword = false
        problems = []
        newCert = nil
        pwFocus = true
    }

    func pick() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [UTType.pkcs12, UTType(filenameExtension: "pfx") ?? .data]
        p.allowsMultipleSelection = false
        p.message = "Vyberte súbor s osobným certifikátom, ktorý vám poslalo IT oddelenie."
        if p.runModal() == .OK, let u = p.url { setFile(u) }
    }

    func run(confirmed: Bool) {
        guard let file, !password.isEmpty else { return }
        busy = true
        failure = ""
        wrongPassword = false
        let pw = password, del = deleteOld, rules = m.cfg.vydavatelia
        Task.detached {
            let r = CertStore.importP12(file, password: pw, deleteOld: del, rules: rules, confirmed: confirmed)
            await MainActor.run {
                busy = false
                switch r {
                case let .ok(cert, removed):
                    m.replaced(cert, removed: removed)
                    dismiss()
                case .wrongPassword:
                    wrongPassword = true
                    password = ""
                    pwFocus = true
                case let .needsConfirm(p, c):
                    problems = p
                    newCert = c
                case let .failed(t):
                    failure = t
                }
            }
        }
    }
}

/// Okno Certifikáty (E3).
struct CertificatesView: View {
    @EnvironmentObject var m: AppModel
    @State private var sel: CertInfo.ID?
    @State private var cas: [CertInfo] = []
    @State private var replace = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            (Text("Osobný certifikát ").bold() + Text("· prihlasovacia kľúčenka").foregroundColor(.secondary)).font(.system(size: 15))
            Table(tracked, selection: $sel) {
                TableColumn("Komu je vydaný") { Text($0.subject) }
                TableColumn("Vydal") { Text($0.issuer) }
                TableColumn("Platný do") { c in
                    let d = CertLogic.daysLeft(c.notAfter)
                    Text(CertLogic.format(c.notAfter) + (d <= m.cfg.upozornitDni ? " · \(CertLogic.inDays(d))" : ""))
                        .foregroundColor(d <= m.cfg.upozornitDni ? Color(hex: 0xB10E1C) : .primary)
                }
            }
            .frame(minHeight: 120)
            HStack {
                Button("Vymeniť certifikát…") { replace = true }.buttonStyle(.borderedProminent)
                Button("Odstrániť") {
                    if let c = tracked.first(where: { $0.id == sel }), confirmDelete(c) {
                        CertStore.delete(c)
                        m.checkCerts(notify: false)
                    }
                }.disabled(sel == nil)
                Spacer()
                Button("Otvoriť Prístup ku kľúčenke") { CertStore.openKeychainAccess() }
            }
            Text("Rozhoduje certifikát s najneskoršou platnosťou. Pri importe sa pýta heslo k súboru (neukladá sa).")
                .font(.system(size: 12)).foregroundStyle(.secondary)
            (Text("Certifikačné autority (CA) ").bold() + Text("· z inštalačného balíka").foregroundColor(.secondary)).font(.system(size: 15)).padding(.top, 8)
            Table(cas) {
                TableColumn("Názov") { Text($0.subject) }
                TableColumn("Vydal") { Text($0.issuer) }
                TableColumn("Platný do") { Text(CertLogic.format($0.notAfter)) }
            }
            .frame(minHeight: 90)
            Text("CA a XML profily inštaluje balík pre všetkých používateľov Macu. Používateľ rieši len svoj osobný certifikát pri výmene.")
                .font(.system(size: 12)).foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(width: 680, height: 520)
        .onAppear {
            m.checkCerts(notify: false)
            cas = CertStore.packagedCAs()
        }
        .sheet(isPresented: $replace) { ReplaceCertSheet().environmentObject(m) }
    }

    var tracked: [CertInfo] {
        let t = CertLogic.tracked(m.certs, rules: m.cfg.vydavatelia)
        return t.isEmpty ? m.certs : t
    }

    func confirmDelete(_ c: CertInfo) -> Bool {
        let a = NSAlert()
        a.messageText = "Odstrániť certifikát \(c.subject)?"
        a.informativeText = "Platí do \(CertLogic.format(c.notAfter)). Bez neho sa pripojenia s certifikátom nepripoja."
        a.addButton(withTitle: "Odstrániť")
        a.addButton(withTitle: "Zrušiť")
        return a.runModal() == .alertFirstButtonReturn
    }
}
