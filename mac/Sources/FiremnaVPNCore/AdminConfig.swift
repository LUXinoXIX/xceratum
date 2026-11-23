import Foundation

/// Spôsob prihlásenia (rovnaké hodnoty ako v ini Windows a Linux verzie).
public enum AuthMode: String, CaseIterable, Codable, Sendable {
    case menoHesloKod = "MenoHesloKod"
    case hesloKod = "HesloKod"
    case menoHeslo = "MenoHeslo"
    case heslo = "Heslo"
    case certifikat = "Certifikat"
    case dveHesla = "DveHesla"

    public static func parse(_ value: String) -> AuthMode? {
        let v = value.trimmingCharacters(in: .whitespaces).lowercased().replacingOccurrences(of: "á", with: "a")
        return AuthMode.allCases.first { $0.rawValue.lowercased() == v }
    }

    public var label: String {
        switch self {
        case .menoHesloKod: return "Meno, heslo a kód"
        case .hesloKod: return "Heslo a kód"
        case .menoHeslo: return "Meno a heslo"
        case .heslo: return "Len heslo"
        case .certifikat: return "Osobný certifikát"
        case .dveHesla: return "Meno a dve heslá"
        }
    }

    /// Základ prihlásenia bez 2FA – ako stĺpec „Prihlásenie“ vo Windows a Linux nastaveniach.
    public enum Base: Int, CaseIterable, Sendable {
        case menoHeslo, heslo, certifikat, dveHesla
        public var label: String {
            switch self {
            case .menoHeslo: return "Meno a heslo"
            case .heslo: return "Len heslo"
            case .certifikat: return "Osobný certifikát"
            case .dveHesla: return "Meno a dve heslá"
            }
        }
        /// 2FA kód sa dá pridať len k prihláseniu heslom.
        public var allows2FA: Bool { self == .menoHeslo || self == .heslo }
    }

    public var base: Base {
        switch self {
        case .menoHesloKod, .menoHeslo: return .menoHeslo
        case .hesloKod, .heslo: return .heslo
        case .certifikat: return .certifikat
        case .dveHesla: return .dveHesla
        }
    }

    public var has2FA: Bool { self == .menoHesloKod || self == .hesloKod }

    public static func join(_ base: Base, twoFA: Bool) -> AuthMode {
        switch base {
        case .menoHeslo: return twoFA ? .menoHesloKod : .menoHeslo
        case .heslo: return twoFA ? .hesloKod : .heslo
        case .certifikat: return .certifikat
        case .dveHesla: return .dveHesla
        }
    }

    /// Nový jedinečný názov pre klon: „Firma A“ → „Firma A (2)“, „Firma A (2)“ → „Firma A (3)“.
    public static func uniqueName(_ name: String, existing: [String]) -> String {
        var stem = name.trimmingCharacters(in: .whitespaces)
        var n = 2
        if let r = stem.range(of: #"\s*\((\d+)\)$"#, options: .regularExpression) {
            let num = stem[r].filter(\.isNumber)
            n = (Int(num) ?? 1) + 1
            stem = String(stem[..<r.lowerBound])
        }
        let taken = Set(existing.map { $0.lowercased() })
        while taken.contains("\(stem) (\(n))".lowercased()) { n += 1 }
        return "\(stem) (\(n))"
    }

    public var needsUser: Bool { [.menoHesloKod, .menoHeslo, .dveHesla].contains(self) }
    public var needsPassword: Bool { self != .certifikat }
    public var needsCode: Bool { [.menoHesloKod, .hesloKod].contains(self) }
    public var needsSecond: Bool { self == .dveHesla }
}

/// Jedna položka v roletke – odkazuje na pripojenie (HostName) z Cisca.
public struct ItemSettings: Equatable, Sendable {
    public var cisco = ""
    public var nazov = ""
    public var auth = ""
    public var meno = ""
    public var group = ""
    public var skryt = false
    public var predvolene = false
    public init(cisco: String = "", nazov: String = "", auth: String = "", meno: String = "",
                group: String = "", skryt: Bool = false, predvolene: Bool = false) {
        self.cisco = cisco; self.nazov = nazov; self.auth = auth; self.meno = meno
        self.group = group; self.skryt = skryt; self.predvolene = predvolene
    }
    public var authMode: AuthMode? { AuthMode.parse(auth) }
}

public struct IssuerRule: Equatable, Sendable {
    public var text: String
    public var on: Bool
    public init(text: String, on: Bool) { self.text = text; self.on = on }
}

/// Nastavenia správcu – `FiremnaVPN.ini` v rovnakom formáte ako vo Windows.
/// Na Macu: `/Library/Application Support/FiremnaVPN/FiremnaVPN.ini` (zapisuje len správca).
public struct AdminConfig: Equatable, Sendable {
    public var nazovAplikacie = "Firemná VPN"
    public var defaultAuth = AuthMode.menoHesloKod.rawValue
    public var group = ""
    public var vpnCliPath = ""
    public var connectTimeoutSeconds = 90
    public var vzhlad = "Systemovy"          // Svetly | Tmavy | Systemovy
    public var skrytPoSekundach = 5          // 0 = hneď, -1 = neskrývať
    public var priOdpojeniOtvoritOkno = true
    public var autoPrijatBanner = false
    public var povolitKlucenku = true        // Mac: heslo v Kľúčenke (s Touch ID)
    public var vyzadovatTouchID = true
    public var polozky: [ItemSettings] = []
    // [Certifikaty]
    public var upozornitDni = 30
    public var kontakt = ""
    public var vydavatelia: [IssuerRule] = []

    public init() {}

    public static let systemPath = "/Library/Application Support/FiremnaVPN/FiremnaVPN.ini"

    public var defaultAuthMode: AuthMode { AuthMode.parse(defaultAuth) ?? .menoHesloKod }
    public var kontaktText: String { kontakt.isEmpty ? "IT oddelenie" : kontakt }

    public static func load(path: String = systemPath) -> AdminConfig {
        guard let data = FileManager.default.contents(atPath: path) else { return AdminConfig() }
        var text = String(decoding: data, as: UTF8.self)
        if text.hasPrefix("\u{FEFF}") { text.removeFirst() }
        return parse(ini: text)
    }

    static func fold(_ s: String) -> String {
        s.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
            .replacingOccurrences(of: " ", with: "")
    }

    static func bool(_ v: String) -> Bool {
        ["1", "true", "ano", "yes", "on"].contains(fold(v))
    }

    static func unquote(_ s: String) -> String {
        var t = s.trimmingCharacters(in: .whitespaces)
        if t.count >= 2, t.first == "\"", t.last == "\"" { t = String(t.dropFirst().dropLast()) }
        return t
    }

    public static func parse(ini text: String) -> AdminConfig {
        var cfg = AdminConfig()
        enum Section { case general, cert, item(Int) }
        var section = Section.general
        var defaultConn = ""
        for raw in text.components(separatedBy: .newlines) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            guard let first = line.first, first != ";", first != "#" else { continue }
            if first == "[" {
                let name = line.trimmingCharacters(in: CharacterSet(charactersIn: "[] "))
                let f = fold(name)
                if f == "vseobecne" || f == "general" {
                    section = .general
                } else if f == "certifikaty" {
                    section = .cert
                } else if f.hasPrefix("pripojenie:") {
                    let host = name[name.index(after: name.firstIndex(of: ":")!)...].trimmingCharacters(in: .whitespaces)
                    cfg.polozky.append(ItemSettings(cisco: host))
                    section = .item(cfg.polozky.count - 1)
                } else {
                    cfg.polozky.append(ItemSettings())
                    section = .item(cfg.polozky.count - 1)
                }
                continue
            }
            guard let eq = line.firstIndex(of: "="), eq != line.startIndex else { continue }
            let key = fold(String(line[..<eq]))
            var val = String(line[line.index(after: eq)...]).trimmingCharacters(in: .whitespaces)
            if let sc = val.range(of: " ;") { val = String(val[..<sc.lowerBound]).trimmingCharacters(in: .whitespaces) }
            switch section {
            case .item(let i):
                switch key {
                case "cisco": cfg.polozky[i].cisco = unquote(val)
                case "nazov": cfg.polozky[i].nazov = val
                case "auth": cfg.polozky[i].auth = val
                case "meno": cfg.polozky[i].meno = val
                case "group": cfg.polozky[i].group = val
                case "skryt": cfg.polozky[i].skryt = bool(val)
                case "predvolene": cfg.polozky[i].predvolene = bool(val)
                default: break
                }
            case .cert:
                switch key {
                case "upozornitdni": cfg.upozornitDni = Int(val) ?? cfg.upozornitDni
                case "kontakt": cfg.kontakt = val
                default:
                    if key.hasPrefix("vydavatel") {
                        let parts = val.split(separator: "|", maxSplits: 1).map(String.init)
                        let text = parts.first?.trimmingCharacters(in: .whitespaces) ?? ""
                        if !text.isEmpty {
                            cfg.vydavatelia.append(IssuerRule(text: text, on: parts.count < 2 || bool(parts[1])))
                        }
                    }
                }
            case .general:
                switch key {
                case "nazovaplikacie": cfg.nazovAplikacie = val
                case "defaultauth": cfg.defaultAuth = val
                case "group": cfg.group = val
                case "vpnclipath": cfg.vpnCliPath = val
                case "connecttimeoutseconds": cfg.connectTimeoutSeconds = Int(val) ?? cfg.connectTimeoutSeconds
                case "vzhlad": cfg.vzhlad = val
                case "skrytposekundach": cfg.skrytPoSekundach = Int(val) ?? cfg.skrytPoSekundach
                case "priodpojeniotvoritokno": cfg.priOdpojeniOtvoritOkno = bool(val)
                case "autoprijatbanner": cfg.autoPrijatBanner = bool(val)
                case "povolitklucenku": cfg.povolitKlucenku = bool(val)
                case "vyzadovattouchid": cfg.vyzadovatTouchID = bool(val)
                case "dniupozorneniacertifikat": cfg.upozornitDni = Int(val) ?? cfg.upozornitDni
                case "defaultconnection", "server": defaultConn = unquote(val)
                default: break
                }
            }
        }
        cfg.polozky.removeAll { $0.cisco.isEmpty }
        if !defaultConn.isEmpty, !cfg.polozky.contains(where: { $0.predvolene }),
           let i = cfg.polozky.firstIndex(where: { $0.cisco.lowercased() == defaultConn.lowercased() }) {
            cfg.polozky[i].predvolene = true
        }
        return cfg
    }

    public func toIni() -> String {
        func b(_ v: Bool) -> String { v ? "1" : "0" }
        var s = """
        ; Firemná VPN – nastavenia správcu (rovnaký formát ako Windows a Linux verzia)
        NazovAplikacie=\(nazovAplikacie)
        DefaultAuth=\(defaultAuth)

        [Vseobecne]
        VpncliPath=\(vpnCliPath)
        ConnectTimeoutSeconds=\(connectTimeoutSeconds)
        Vzhlad=\(vzhlad)
        SkrytPoSekundach=\(skrytPoSekundach)
        PriOdpojeniOtvoritOkno=\(b(priOdpojeniOtvoritOkno))
        AutoPrijatBanner=\(b(autoPrijatBanner))
        PovolitKlucenku=\(b(povolitKlucenku))
        VyzadovatTouchID=\(b(vyzadovatTouchID))

        [Certifikaty]
        UpozornitDni=\(upozornitDni)
        Kontakt=\(kontakt)

        """
        for (i, v) in vydavatelia.enumerated() {
            s += "Vydavatel\(i + 1)=\(v.text)|\(b(v.on))\n"
        }
        for (i, p) in polozky.enumerated() {
            s += "\n[Polozka \(i + 1)]\nCisco=\(p.cisco)\nNazov=\(p.nazov)\nAuth=\(p.auth)\nMeno=\(p.meno)\nGroup=\(p.group)\nSkryt=\(b(p.skryt))\nPredvolene=\(b(p.predvolene))\n"
        }
        return s
    }
}

/// Stav používateľa (zapamätané meno, posledné pripojenie). Heslo sa sem neukladá – je v Kľúčenke.
public struct UserState: Codable, Equatable, Sendable {
    public var meno = ""
    public var zapamatatMeno = true
    public var ulozitHeslo = true
    public var posledne = ""
    public var vzhlad = ""                 // prázdne = podľa správcu
    public var pripomenutPo: Date?         // „Pripomenúť zajtra“
    public init() {}

    public static var url: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("FiremnaVPN/pouzivatel.json")
    }

    public static func load() -> UserState {
        guard let d = try? Data(contentsOf: url), let s = try? JSONDecoder().decode(UserState.self, from: d) else {
            return UserState()
        }
        return s
    }

    public func save() {
        let u = UserState.url
        try? FileManager.default.createDirectory(at: u.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let d = try? JSONEncoder().encode(self) {
            try? d.write(to: u, options: .atomic)
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: u.path)
        }
    }
}
