import Foundation

/// XML profily Cisca a položky v roletke „Pripojenie (profil)“ – ako Linux `profiles.py`.
public struct CiscoHost: Equatable, Sendable {
    public var hostName: String
    public var address = ""
    public var file = ""
    public var guess: AuthMode?
    public init(hostName: String, address: String = "", file: String = "", guess: AuthMode? = nil) {
        self.hostName = hostName; self.address = address; self.file = file; self.guess = guess
    }
}

public struct ProfileFile: Equatable, Sendable {
    public var path: String
    public var hosts: [CiscoHost] = []
    public var error = ""
    public var name: String { (path as NSString).lastPathComponent }
}

public enum Profiles {
    public static let dirs = [
        "/opt/cisco/secureclient/vpn/profile",   // Secure Client 5
        "/opt/cisco/anyconnect/profile",         // AnyConnect 4.x
    ]
    static let maxBytes = 1024 * 1024

    public static func dir(forCli cli: String?) -> String {
        if let c = cli, c.contains("/anyconnect/") { return dirs[1] }
        return dirs[0]
    }

    public static func parse(path: String) -> ProfileFile {
        var pf = ProfileFile(path: path)
        guard let data = FileManager.default.contents(atPath: path) else {
            pf.error = "nedá sa prečítať"
            return pf
        }
        if data.count > maxBytes {
            pf.error = "súbor je príliš veľký"
            return pf
        }
        let r = parse(data: data, fileName: pf.name)
        pf.hosts = r.hosts
        pf.error = r.error
        return pf
    }

    public static func parse(data: Data, fileName: String) -> (hosts: [CiscoHost], error: String) {
        let d = ProfileDelegate(file: fileName)
        let p = XMLParser(data: data)
        p.shouldProcessNamespaces = true
        p.shouldResolveExternalEntities = false
        p.delegate = d
        if !p.parse() {
            return ([], "nedá sa prečítať: " + (p.parserError?.localizedDescription ?? "chybné XML"))
        }
        if d.root != "AnyConnectProfile" {
            return ([], "nie je to profil Cisco (chýba AnyConnectProfile)")
        }
        return (d.hosts, "")
    }

    public static func listFiles(dirs: [String] = dirs) -> [ProfileFile] {
        var out: [ProfileFile] = []
        for d in dirs {
            guard let names = try? FileManager.default.contentsOfDirectory(atPath: d) else { continue }
            for n in names.sorted() where n.lowercased().hasSuffix(".xml") {
                out.append(parse(path: (d as NSString).appendingPathComponent(n)))
            }
        }
        return out
    }

    /// Názvy z `vpn hosts` doplnené o údaje z XML; bez CLI len XML.
    public static func merge(cliNames: [String], xmlHosts: [CiscoHost]) -> [CiscoHost] {
        var names: [String] = []
        for n in (cliNames.isEmpty ? xmlHosts.map(\.hostName) : cliNames) where !names.contains(n) {
            names.append(n)
        }
        return names.map { n in
            if let f = xmlHosts.first(where: { $0.hostName.lowercased() == n.lowercased() }) {
                return CiscoHost(hostName: n, address: f.address, file: f.file, guess: f.guess)
            }
            return CiscoHost(hostName: n)
        }
    }

    public static func buildItems(cfg: AdminConfig, hosts: [CiscoHost]) -> [VpnProfile] {
        var result: [VpnProfile] = []
        var used = Set<String>()
        for it in cfg.polozky {
            let h = hosts.first { $0.hostName.lowercased() == it.cisco.lowercased() }
            let mode = it.authMode ?? h?.guess ?? cfg.defaultAuthMode
            var p = VpnProfile(hostName: h?.hostName ?? it.cisco,
                               name: it.nazov.isEmpty ? (h?.hostName ?? it.cisco) : it.nazov,
                               auth: mode)
            p.address = h?.address ?? ""
            p.xmlFile = h?.file ?? ""
            p.group = it.group.isEmpty ? cfg.group : it.group
            p.presetUser = it.meno
            p.hidden = it.skryt
            p.isDefault = it.predvolene
            p.missing = h == nil
            p.configured = it.authMode != nil
            result.append(p)
            used.insert(p.hostName.lowercased())
        }
        for (n, h) in hosts.enumerated() where !used.contains(h.hostName.lowercased()) {
            var p = VpnProfile(hostName: h.hostName, name: "Pripojenie \(n + 1)", auth: h.guess ?? cfg.defaultAuthMode)
            p.address = h.address
            p.xmlFile = h.file
            p.group = cfg.group
            result.append(p)
        }
        var seen = false
        for i in result.indices {
            if result[i].isDefault && seen { result[i].isDefault = false }
            seen = seen || result[i].isDefault
        }
        return result
    }
}

public struct VpnProfile: Identifiable, Equatable, Sendable {
    public var hostName: String
    public var name: String
    public var auth: AuthMode
    public var address = ""
    public var xmlFile = ""
    public var group = ""
    public var presetUser = ""
    public var hidden = false
    public var isDefault = false
    public var missing = false
    public var configured = false

    public init(hostName: String, name: String, auth: AuthMode) {
        self.hostName = hostName; self.name = name; self.auth = auth
    }
    public var id: String { hostName + "|" + name }
    public var server: String { address.isEmpty ? hostName : address }
}

final class ProfileDelegate: NSObject, XMLParserDelegate {
    let file: String
    var root = ""
    var hosts: [CiscoHost] = []
    private var stack: [String] = []
    private var cur: CiscoHost?
    private var text = ""
    private var inProtocol = false
    private var protoText = ""

    init(file: String) { self.file = file }

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes attributeDict: [String: String] = [:]) {
        let name = elementName.components(separatedBy: ":").last ?? elementName
        if stack.isEmpty { root = name }
        stack.append(name)
        text = ""
        if name == "HostEntry" { cur = CiscoHost(hostName: "", file: file) }
        if name == "PrimaryProtocol" { inProtocol = true; protoText = "" }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        text += string
        if inProtocol { protoText += string }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) {
        let name = stack.popLast() ?? elementName
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if cur != nil {
            switch name {
            case "HostName": cur?.hostName = t
            case "HostAddress": cur?.address = t
            case "AuthMethodDuringIKENegotiation":
                if t.uppercased().contains("IKE-RSA") { cur?.guess = .certifikat }
            case "PrimaryProtocol":
                inProtocol = false
                if protoText.uppercased().contains("IKE-RSA") { cur?.guess = .certifikat }
            case "HostEntry":
                if let c = cur, !c.hostName.isEmpty { hosts.append(c) }
                cur = nil
            default: break
            }
        }
        text = ""
    }
}
