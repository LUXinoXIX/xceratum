import Foundation

/// Osobný certifikát (identita v prihlasovacej kľúčenke).
public struct CertInfo: Identifiable, Equatable, Sendable {
    public var id: String          // SHA-1 odtlačok (hex, veľké písmená) – ako `security find-identity`
    public var subject: String     // CN komu je vydaný
    public var issuer: String      // CN vydavateľa
    public var notAfter: Date
    public var hasKey: Bool
    public init(id: String, subject: String, issuer: String, notAfter: Date, hasKey: Bool = true) {
        self.id = id; self.subject = subject; self.issuer = issuer; self.notAfter = notAfter; self.hasKey = hasKey
    }
}

public enum ReplaceProblem: Equatable, Sendable {
    case differentUser(old: String, new: String)
    case untrackedIssuer(String)
    case expired
    case notNewer

    public var text: String {
        switch self {
        case let .differentUser(old, new): return "Certifikát je pre iného používateľa (\(new)), doteraz bol \(old)."
        case let .untrackedIssuer(i): return "Vydavateľ „\(i)“ nie je medzi sledovanými vydavateľmi."
        case .expired: return "Nový certifikát už neplatí."
        case .notNewer: return "Nový certifikát neplatí dlhšie ako súčasný."
        }
    }
}

public enum CertLogic {
    public static func daysLeft(_ date: Date, now: Date = Date()) -> Int {
        let cal = Calendar(identifier: .gregorian)
        let a = cal.startOfDay(for: now), b = cal.startOfDay(for: date)
        return cal.dateComponents([.day], from: a, to: b).day ?? 0
    }

    /// Certifikáty od sledovaných vydavateľov (meno vydavateľa obsahuje text). Bez pravidiel všetky.
    public static func tracked(_ certs: [CertInfo], rules: [IssuerRule]) -> [CertInfo] {
        let on = rules.filter(\.on).map { $0.text.lowercased() }
        if rules.isEmpty { return certs }
        return certs.filter { c in on.contains { c.issuer.lowercased().contains($0) } }
    }

    /// Rozhoduje certifikát s najneskoršou platnosťou.
    public static func current(_ certs: [CertInfo], rules: [IssuerRule]) -> CertInfo? {
        tracked(certs, rules: rules).max { $0.notAfter < $1.notAfter }
    }

    /// Certifikát, na ktorý treba upozorniť (končí do `days` dní), inak nil.
    public static func warning(_ certs: [CertInfo], rules: [IssuerRule], days: Int, now: Date = Date()) -> CertInfo? {
        guard days > 0, let c = current(certs, rules: rules) else { return nil }
        return daysLeft(c.notAfter, now: now) <= days ? c : nil
    }

    /// Kontrola pred výmenou: nový certifikát má byť pre toho istého človeka, od sledovaného vydavateľa a platiť dlhšie.
    public static func check(new: CertInfo, old: CertInfo?, rules: [IssuerRule], now: Date = Date()) -> [ReplaceProblem] {
        var p: [ReplaceProblem] = []
        if new.notAfter <= now { p.append(.expired) }
        if !rules.isEmpty, tracked([new], rules: rules).isEmpty { p.append(.untrackedIssuer(new.issuer)) }
        if let old {
            if old.subject.lowercased() != new.subject.lowercased() {
                p.append(.differentUser(old: old.subject, new: new.subject))
            }
            if new.notAfter <= old.notAfter { p.append(.notNewer) }
        }
        return p
    }

    /// Ktoré staré certifikáty zmazať po úspešnej výmene: rovnaký používateľ a vydavateľ, kratšia platnosť.
    public static func toRemove(after new: CertInfo, in certs: [CertInfo]) -> [CertInfo] {
        certs.filter {
            $0.id != new.id && $0.subject.lowercased() == new.subject.lowercased()
                && $0.issuer.lowercased() == new.issuer.lowercased() && $0.notAfter < new.notAfter
        }
    }

    public static func format(_ d: Date) -> String {
        let c = Calendar(identifier: .gregorian).dateComponents([.day, .month, .year], from: d)
        return "\(c.day ?? 0). \(c.month ?? 0). \(c.year ?? 0)"
    }

    /// Text „vyprší o N dní“ so správnym tvarom.
    public static func inDays(_ n: Int) -> String {
        switch n {
        case ..<0: return "už neplatí"
        case 0: return "vyprší dnes"
        case 1: return "vyprší zajtra"
        case 2...4: return "vyprší o \(n) dni"
        default: return "vyprší o \(n) dní"
        }
    }
}
