import Foundation
import Darwin

/// Práca s Cisco CLI (`/opt/cisco/secureclient/bin/vpn`) – rovnaké poučenia ako Windows a Linux verzia:
/// * pripája sa cez HostName z profilu (v úvodzovkách, ak má medzery), nie cez adresu;
/// * pred pripojením sa zavrie okno Cisca, inak „Connect capability is unavailable“;
/// * na výzvy (Group / Username / Password / Second Password / [y/n]) sa odpovedá, až keď naozaj prídu;
/// * neznáma výzva → po 20 s chyba s jej textom; chyba Cisca + návrat na `VPN>` → okamžitý koniec;
/// * heslo sa v logu a vo výpise maskuje.
/// Výstup sa číta cez pseudoterminál, aby ho Cisco nebufferovalo a výzvy prišli hneď.
public enum ConnectResult: String, Sendable {
    case connected, loginFailed, otherClient, cancelled, needUser, declined, failed
}

public struct Outcome: Sendable {
    public var result: ConnectResult
    public var error: String = ""      // slovensky
    public var original: String = ""   // pôvodný text Cisca
    public init(_ result: ConnectResult, _ error: String = "", _ original: String = "") {
        self.result = result; self.error = error; self.original = original
    }
}

public struct Stats: Sendable, Equatable {
    public var state = ""
    public var clientIP = ""
    public var server = ""
    public var duration: Int?
    public var bytesSent: Int?
    public var bytesReceived: Int?
    public var proto = ""
    public var cipher = ""
    public var tunnelMode = ""
    public init() {}
}

/// Kroky v okne: 0 kontaktujem server, 1 overujem prihlásenie, 2 nastavujem pripojenie, 3 pripojené.
public typealias ProgressHandler = @Sendable (_ step: Int, _ message: String) -> Void

public enum AskKind: String, Sendable { case banner, untrusted }

public final class CiscoCLI: @unchecked Sendable {
    public static let candidates = [
        "/opt/cisco/secureclient/bin/vpn",   // Cisco Secure Client 5
        "/opt/cisco/anyconnect/bin/vpn",     // AnyConnect 4.x
    ]

    public let path: String?
    public var timeout: TimeInterval
    public var usePty: Bool
    public var logURL: URL

    public init(configured: String = "", timeout: Int = 90, usePty: Bool = true, logURL: URL? = nil) {
        self.path = CiscoCLI.find(configured: configured)
        self.timeout = TimeInterval(timeout)
        self.usePty = usePty
        self.logURL = logURL ?? CiscoCLI.defaultLogURL
    }

    public static var defaultLogURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/FiremnaVPN/cisco-vpn-log.txt")
    }

    public var available: Bool { path != nil }

    public static func find(configured: String) -> String? {
        var cands = candidates
        let c = (configured as NSString).expandingTildeInPath
        if !configured.isEmpty { cands.insert(c, at: 0) }
        return cands.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    static var env: [String: String] {
        var e = ProcessInfo.processInfo.environment
        e["LANG"] = "C"
        e["LC_ALL"] = "C"
        return e
    }

    // MARK: jednoduché príkazy

    public func run(_ args: [String], timeout: TimeInterval = 20) -> String {
        guard let path else { return "" }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        p.environment = CiscoCLI.env
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch { return "" }
        let box = DataBox()
        let group = DispatchGroup()
        group.enter()
        DispatchQueue.global().async {
            box.data = pipe.fileHandleForReading.readDataToEndOfFile()
            group.leave()
        }
        if group.wait(timeout: .now() + timeout) == .timedOut {
            p.terminate()
            _ = group.wait(timeout: .now() + 2)
        } else {
            p.waitUntilExit()
        }
        return String(decoding: box.data, as: UTF8.self).replacingOccurrences(of: "\r", with: "")
    }

    public func version() -> String {
        let out = run(["-v"], timeout: 10)
        return CiscoParse.firstMatch(#"version\s+(\d+(?:\.\d+){1,3})"#, in: out) ?? ""
    }

    public func hosts() -> [String] { CiscoParse.hosts(run(["hosts"], timeout: 15)) }

    public func state() -> String { CiscoParse.state(run(["state"], timeout: 20)) }

    public func stats() -> Stats { CiscoParse.stats(run(["stats"], timeout: 20)) }

    @discardableResult
    public func disconnect() -> String {
        let out = run(["disconnect"], timeout: 30)
        writeLog("disconnect", out, "")
        return out
    }

    /// Ukončí okno Cisca a staré `vpn` procesy tohto používateľa. Vráti, čo ukončil.
    @discardableResult
    public func closeCiscoUI() -> [String] {
        let ps = Process()
        ps.executableURL = URL(fileURLWithPath: "/bin/ps")
        ps.arguments = ["-x", "-o", "pid=,comm=", "-U", String(getuid())]
        let pipe = Pipe()
        ps.standardOutput = pipe
        ps.standardError = FileHandle.nullDevice
        guard (try? ps.run()) != nil else { return [] }
        let out = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        ps.waitUntilExit()
        var killed: [String] = []
        let me = getpid()
        for line in out.split(separator: "\n") {
            let t = line.trimmingCharacters(in: .whitespaces)
            guard let sp = t.firstIndex(of: " "), let pid = Int32(t[..<sp]), pid != me else { continue }
            let comm = String(t[sp...]).trimmingCharacters(in: .whitespaces)
            let isUI = comm.contains("Cisco Secure Client.app/Contents/MacOS/")
                || comm.contains("Cisco AnyConnect Secure Mobility Client.app/Contents/MacOS/")
            let isCli = path != nil && comm == path
            if isUI || isCli {
                if kill(pid, SIGTERM) == 0 { killed.append("\((comm as NSString).lastPathComponent) (\(pid))") }
            }
        }
        if !killed.isEmpty { Thread.sleep(forTimeInterval: 0.7) }
        return killed
    }

    // MARK: pripojenie

    public struct Credentials: Sendable {
        public var user: String
        public var password: String
        public var second: String
        public init(user: String = "", password: String = "", second: String = "") {
            self.user = user; self.password = password; self.second = second
        }
    }

    /// Pripojí sa (blokuje – volať mimo hlavného vlákna).
    /// `ask(kind, text)` vráti true/false, nil = zrušené.
    public func connect(_ prof: VpnProfile, _ cred: Credentials,
                        progress: ProgressHandler = { _, _ in },
                        output: @Sendable (String) -> Void = { _ in },
                        ask: (AskKind, String) -> Bool? = { _, _ in true },
                        cancelled: () -> Bool = { false },
                        autoBanner: Bool = false) -> Outcome {
        guard let path else { return Outcome(.failed, "Nenašiel sa Cisco Secure Client (príkaz vpn).") }
        if state() == "Connected" { return Outcome(.connected) }
        let killed = closeCiscoUI()
        if !killed.isEmpty { output("Ukončené: " + killed.joined(separator: ", ") + "\n") }

        let io: ProcessIO
        do { io = try ProcessIO.spawn(path: path, args: ["-s"], usePty: usePty) } catch {
            return Outcome(.failed, "Cisco CLI sa nedá spustiť: \(error.localizedDescription)")
        }

        var sentLog: [String] = []
        var step = 0
        progress(step, "")
        var buf = ""
        var handled = buf.startIndex
        var handledCount = 0
        var users = 0, passwords = 0, seconds = 0
        let start = Date()
        var lastChange = Date()
        var lastProgress = (step, "")
        var result: ConnectResult?
        var error = "", original = ""
        var eof = false
        let secrets = [cred.password, cred.second]

        func send(_ line: String, _ shown: String) {
            io.write(line + "\n")
            let f = DateFormatter()
            f.dateFormat = "HH:mm:ss"
            sentLog.append("[\(f.string(from: Date()))] odoslané: \(shown)")
            output("  → \(shown)\n")
        }
        func markHandled() { handledCount = buf.count }

        // počkať na úvodný výpis Cisca (napr. „state: Connected“ z minulosti nesmie znamenať úspech)
        let greetEnd = Date().addingTimeInterval(3)
        var idleSince = Date()
        while Date() < greetEnd {
            guard let c = io.read(timeout: 0.1) else { eof = true; break }
            if !c.isEmpty { buf += c; idleSince = Date() }
            if buf.contains("VPN>") && Date().timeIntervalSince(idleSince) > 0.4 { break }
        }
        output(buf)
        markHandled()

        let cmd = "connect " + CiscoParse.quoteHost(prof.hostName)
        send(cmd, cmd)

        func cleanup() {
            if io.isRunning {
                if result == .connected {
                    io.write("exit\n")
                    io.closeInput()
                    if !io.wait(3) { io.kill() }
                } else {
                    io.kill()
                }
            }
            buf += io.drain()
            io.close()
            writeLog("connect " + prof.hostName, CiscoParse.mask(buf, secrets), sentLog.joined(separator: "\n"))
        }

        while true {
            var chunk = ""
            if !eof {
                if let c = io.read(timeout: 0.15) { chunk = c } else { eof = true }
            } else if io.isRunning {
                Thread.sleep(forTimeInterval: 0.15)
            }
            if !chunk.isEmpty {
                buf += chunk
                lastChange = Date()
                output(CiscoParse.mask(chunk, secrets))
            }
            handled = buf.index(buf.startIndex, offsetBy: min(handledCount, buf.count))
            let tail = String(buf[handled...])
            let low = tail.lowercased()

            if step < 2, CiscoParse.matches(#"establishing|state:\s*connecting|reconnecting|connecting to"#, tail),
               passwords > 0 || users > 0 || !prof.auth.needsPassword || buf.lowercased().contains("establishing") {
                step = 2
            }
            let msg = CiscoParse.lastCiscoMessage(buf)
            if step != lastProgress.0 || msg != lastProgress.1 {
                lastProgress = (step, msg)
                progress(step, msg)
            }

            if cancelled() { result = .cancelled; break }
            if CiscoParse.matches(#"state:\s*Connected"#, tail) {
                result = .connected
                progress(3, "Connected")
                break
            }
            if CiscoParse.matches(#"login failed|authentication failed|access denied|login denied"#, tail) {
                result = .loginFailed; break
            }
            if CiscoParse.matches(#"connect capability is unavailable|another .*(acquired|running)"#, tail) {
                result = .otherClient; break
            }
            if eof && !io.isRunning { break }
            if low.contains("error:") && CiscoParse.ends(tail, #"VPN>"#) {
                result = .failed
                (error, original) = friendly(tail, prof)
                break
            }

            if CiscoParse.ends(tail, #"\[y/n\]:?"#) {
                let text = CiscoParse.promptText(tail)
                let kind: AskKind = CiscoParse.matches(#"untrusted|security threat|certificate|not trusted|change the setting"#, text) ? .untrusted : .banner
                let answer: Bool? = (kind == .banner && autoBanner) ? true : ask(kind, text)
                guard let a = answer else { result = .cancelled; break }
                send(a ? "y" : "n", a ? "y" : "n")
                markHandled()
                if !a {
                    result = .declined
                    error = kind == .banner ? "Správu servera ste neprijali, pripojenie sa nevytvorí."
                        : "Pripojenie k nedôveryhodnému serveru ste odmietli."
                    original = CiscoParse.lastLine(text)
                    break
                }
                continue
            }
            if CiscoParse.ends(tail, #"Second Password:"#) {
                if !prof.auth.needsSecond || cred.second.isEmpty {
                    result = .failed
                    error = "Pripojenie si pýta druhé heslo. Správca má pre toto pripojenie nastaviť prihlásenie „Meno a dve heslá“."
                    break
                }
                seconds += 1
                if seconds > 1 { result = .loginFailed; break }
                step = max(step, 1)
                send(cred.second, "********")
                markHandled()
                continue
            }
            if CiscoParse.ends(tail, #"Password:"#) {
                if !prof.auth.needsPassword || cred.password.isEmpty {
                    result = .failed
                    error = "Pripojenie si pýta heslo, ale je nastavené na „\(prof.auth.label)“. Správca má upraviť spôsob prihlásenia."
                    break
                }
                passwords += 1
                if passwords > 1 { result = .loginFailed; break }
                step = max(step, 1)
                send(cred.password, "********")
                markHandled()
                continue
            }
            if CiscoParse.ends(tail, #"Username:(\s*\[[^\]]*\])?"#) {
                if cred.user.isEmpty { result = .needUser; break }
                users += 1
                if users > 1 { result = .loginFailed; break }
                step = max(step, 1)
                send(cred.user, cred.user)
                markHandled()
                continue
            }
            if CiscoParse.ends(tail, #"Group:(\s*\[[^\]]*\])?"#) {
                step = max(step, 1)
                send(prof.group, prof.group.isEmpty ? "(Enter – predvolená skupina)" : prof.group)
                markHandled()
                continue
            }

            let now = Date()
            if now.timeIntervalSince(lastChange) > 20,
               tail.trimmingCharacters(in: .whitespacesAndNewlines).hasSuffix(":") {
                result = .failed
                error = "Cisco čaká na otázku, ktorú aplikácia nepozná."
                original = CiscoParse.lastLine(tail)
                break
            }
            if now.timeIntervalSince(start) > timeout {
                result = .failed
                error = "Pripájanie trvalo príliš dlho."
                original = CiscoParse.lastLine(buf)
                break
            }
        }

        cleanup()
        let finalResult = result
        let finalBuf = buf
        switch finalResult {
        case .cancelled?, .needUser?:
            if waitConnected(tries: 1) { return Outcome(.connected) }
            return Outcome(finalResult!, error, original)
        case .declined?:
            return Outcome(.declined, error, original)
        case .connected?, nil:
            if waitConnected(tries: finalResult == .connected ? 5 : 1) { return Outcome(.connected) }
            if finalResult == nil {
                let err = CiscoParse.lastErrorLine(finalBuf).isEmpty ? CiscoParse.lastLine(finalBuf) : CiscoParse.lastErrorLine(finalBuf)
                let (sk, orig) = Messages.friendly(err)
                return Outcome(.failed, sk, orig)
            }
            return Outcome(.failed, "Cisco hlásilo pripojenie, ale stav nie je Connected.", CiscoParse.lastLine(finalBuf))
        case .otherClient?:
            let (sk, _) = Messages.friendly("connect capability is unavailable")
            return Outcome(.otherClient, sk, CiscoParse.lastLine(finalBuf))
        case .loginFailed?:
            let e = CiscoParse.lastErrorLine(finalBuf)
            return Outcome(.loginFailed, "", e.isEmpty ? CiscoParse.lastLine(finalBuf) : e)
        case .failed?:
            return Outcome(.failed, error, original)
        }
    }

    /// Stav po ukončení relácie; služba Cisca ho niekedy hlási s oneskorením.
    func waitConnected(tries: Int) -> Bool {
        for i in 0..<max(tries, 1) {
            if state() == "Connected" { return true }
            if i < tries - 1 { Thread.sleep(forTimeInterval: 1) }
        }
        return false
    }

    func friendly(_ output: String, _ prof: VpnProfile) -> (String, String) {
        let e = CiscoParse.lastErrorLine(output)
        return Messages.friendly(e.isEmpty ? CiscoParse.lastLine(output) : e)
    }

    // MARK: log

    static let maxLog = 256 * 1024

    public func writeLog(_ what: String, _ output: String, _ sent: String) {
        let fm = FileManager.default
        try? fm.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        var old = ""
        if let attrs = try? fm.attributesOfItem(atPath: logURL.path),
           let size = attrs[.size] as? Int, size < CiscoCLI.maxLog,
           let d = fm.contents(atPath: logURL.path) {
            old = String(decoding: d, as: UTF8.self)
        }
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        let entry = "=== \(what) \(f.string(from: Date())) ===\n--- čo poslala aplikácia ---\n\(sent)\n--- výstup Cisco CLI ---\n\(output)\n\n"
        try? Data((old + entry).utf8).write(to: logURL, options: .atomic)
        try? fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: logURL.path)
    }
}

final class DataBox: @unchecked Sendable { var data = Data() }

// MARK: - parsovanie výstupu Cisca (čisté funkcie, testované)

public enum CiscoParse {
    public static func matches(_ pattern: String, _ text: String) -> Bool {
        text.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil
    }

    /// Text končí vzorom (výzva bez nového riadku).
    public static func ends(_ text: String, _ pattern: String) -> Bool {
        matches(pattern + #"\s*\z"#, text)
    }

    public static func firstMatch(_ pattern: String, in text: String, group: Int = 1) -> String? {
        guard let re = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive, .anchorsMatchLines]) else { return nil }
        let ns = text as NSString
        guard let m = re.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)),
              m.numberOfRanges > group, m.range(at: group).location != NSNotFound else { return nil }
        return ns.substring(with: m.range(at: group))
    }

    static func allMatches(_ pattern: String, in text: String) -> [String] {
        guard let re = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { return [] }
        let ns = text as NSString
        return re.matches(in: text, range: NSRange(location: 0, length: ns.length)).compactMap {
            $0.numberOfRanges > 1 ? ns.substring(with: $0.range(at: 1)) : nil
        }
    }

    public static func quoteHost(_ host: String) -> String {
        var h = host.trimmingCharacters(in: .whitespaces)
        if h.count >= 2, h.first == "\"", h.last == "\"" {
            h = String(h.dropFirst().dropLast()).trimmingCharacters(in: .whitespaces)
        }
        return h.contains(" ") ? "\"\(h)\"" : h
    }

    static func lines(_ text: String) -> [String] {
        text.replacingOccurrences(of: "\r", with: "").components(separatedBy: "\n")
    }

    public static func lastLine(_ text: String) -> String {
        for l in lines(text).reversed() {
            let t = l.trimmingCharacters(in: .whitespaces)
            if !t.isEmpty { return t }
        }
        return ""
    }

    static func stripPrompt(_ line: String) -> String {
        var t = line.trimmingCharacters(in: .whitespaces)
        while t.hasPrefix(">") { t.removeFirst() }
        return t.trimmingCharacters(in: .whitespaces)
    }

    public static func lastCiscoMessage(_ text: String) -> String {
        var found = ""
        for raw in lines(text) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            guard line.hasPrefix(">>") else { continue }
            var l = stripPrompt(line)
            for pre in ["notice:", "warning:", "error:", "state:"] where l.lowercased().hasPrefix(pre) {
                l = String(l.dropFirst(pre.count)).trimmingCharacters(in: .whitespaces)
                break
            }
            if !l.isEmpty { found = l }
        }
        return found
    }

    public static func lastErrorLine(_ text: String) -> String {
        var found = ""
        for raw in lines(text) {
            let l = stripPrompt(raw)
            if l.lowercased().contains("error") { found = l }
        }
        return found
    }

    public static func mask(_ text: String, _ secrets: [String]) -> String {
        var t = text
        for s in secrets where !s.isEmpty { t = t.replacingOccurrences(of: s, with: "********") }
        return t
    }

    public static func promptText(_ tail: String) -> String {
        var out: [String] = []
        for raw in lines(tail) {
            let s = raw.trimmingCharacters(in: .whitespaces)
            if s.hasPrefix(">>"), s.lowercased().contains("state:") || s.lowercased().contains("contacting") { continue }
            if s.hasPrefix("VPN>") { continue }
            out.append(raw)
        }
        return out.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public static func hosts(_ out: String) -> [String] {
        var names: [String] = []
        for raw in lines(out) {
            if raw.trimmingCharacters(in: .whitespaces).hasPrefix(">>") { continue }
            if let n = firstMatch(#"^\s*>\s+(\S.*?)\s*$"#, in: raw), !names.contains(n) { names.append(n) }
        }
        return names
    }

    public static func state(_ out: String) -> String {
        allMatches(#"state:\s*(\w+)"#, in: out).last ?? "Unknown"
    }

    public static func stats(_ out: String) -> Stats {
        var st = Stats()
        func grab(_ label: String) -> String {
            firstMatch(#"^\s*"# + label + #"\s*:\s*(.+?)\s*$"#, in: out) ?? ""
        }
        func num(_ label: String) -> Int? {
            let digits = grab(label).filter(\.isNumber)
            return digits.isEmpty ? nil : Int(digits)
        }
        st.state = allMatches(#"state:\s*(\w+)"#, in: out).last ?? grab("Connection State")
        st.clientIP = grab(#"Client Address \(IPv4\)"#)
        st.server = grab("Server Address")
        st.proto = grab("Protocol")
        st.cipher = grab("Protocol Cipher")
        st.tunnelMode = grab(#"Tunnel Mode \(IPv4\)"#)
        st.bytesSent = num("Bytes Sent")
        st.bytesReceived = num("Bytes Received")
        if let re = try? NSRegularExpression(pattern: #"Duration:\s*(\d+):(\d{2}):(\d{2})"#, options: .caseInsensitive) {
            let ns = out as NSString
            if let m = re.firstMatch(in: out, range: NSRange(location: 0, length: ns.length)) {
                let h = Int(ns.substring(with: m.range(at: 1))) ?? 0
                let mi = Int(ns.substring(with: m.range(at: 2))) ?? 0
                let s = Int(ns.substring(with: m.range(at: 3))) ?? 0
                st.duration = h * 3600 + mi * 60 + s
            }
        }
        return st
    }

    public static func formatBytes(_ n: Int?) -> String {
        guard let n else { return "–" }
        var v = Double(n)
        for unit in ["B", "kB", "MB", "GB"] {
            if v < 1024 || unit == "GB" {
                return unit == "B" ? "\(n) B" : String(format: "%.1f %@", v, unit).replacingOccurrences(of: ".", with: ",")
            }
            v /= 1024
        }
        return "\(n)"
    }

    public static func formatDuration(_ sec: Int) -> String {
        let s = max(0, sec)
        return String(format: "%02d:%02d:%02d", s / 3600, s % 3600 / 60, s % 60)
    }
}

// MARK: - proces s pseudoterminálom

final class ProcessIO {
    let process: Process
    let input: Pipe
    let readFD: Int32
    let ownsFD: Bool
    private var closed = false

    private init(process: Process, input: Pipe, readFD: Int32, ownsFD: Bool) {
        self.process = process; self.input = input; self.readFD = readFD; self.ownsFD = ownsFD
    }

    static func spawn(path: String, args: [String], usePty: Bool) throws -> ProcessIO {
        signal(SIGPIPE, SIG_IGN)   // zápis do skončeného procesu nesmie zhodiť aplikáciu
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        p.environment = CiscoCLI.env
        let input = Pipe()
        p.standardInput = input
        if usePty, let (master, slave) = openPty() {
            let h = FileHandle(fileDescriptor: slave, closeOnDealloc: false)
            p.standardOutput = h
            p.standardError = h
            do { try p.run() } catch {
                Darwin.close(slave); Darwin.close(master)
                throw error
            }
            Darwin.close(slave)
            return ProcessIO(process: p, input: input, readFD: master, ownsFD: true)
        }
        let out = Pipe()
        p.standardOutput = out
        p.standardError = out
        try p.run()
        return ProcessIO(process: p, input: input, readFD: out.fileHandleForReading.fileDescriptor, ownsFD: false)
    }

    static func openPty() -> (Int32, Int32)? {
        let master = posix_openpt(O_RDWR | O_NOCTTY)
        guard master >= 0 else { return nil }
        guard grantpt(master) == 0, unlockpt(master) == 0, let name = ptsname(master) else {
            Darwin.close(master); return nil
        }
        let slave = open(name, O_RDWR | O_NOCTTY)
        guard slave >= 0 else { Darwin.close(master); return nil }
        var t = termios()
        if tcgetattr(slave, &t) == 0 {
            t.c_oflag &= ~tcflag_t(OPOST)     // bez \r\n
            t.c_lflag &= ~tcflag_t(ECHO)
            _ = tcsetattr(slave, TCSANOW, &t)
        }
        return (master, slave)
    }

    var isRunning: Bool { process.isRunning }

    func write(_ s: String) {
        guard !closed else { return }
        let fd = input.fileHandleForWriting.fileDescriptor
        let bytes = Array(s.utf8)
        _ = bytes.withUnsafeBufferPointer { Darwin.write(fd, $0.baseAddress, $0.count) }
    }

    func closeInput() { try? input.fileHandleForWriting.close() }

    /// Text alebo "" (nič nové); nil = koniec výstupu.
    func read(timeout: TimeInterval) -> String? {
        var pfd = pollfd(fd: readFD, events: Int16(POLLIN), revents: 0)
        let r = poll(&pfd, 1, Int32(timeout * 1000))
        if r < 0 { return errno == EINTR ? "" : nil }
        if r == 0 { return "" }
        var buf = [UInt8](repeating: 0, count: 65536)
        let n = buf.withUnsafeMutableBytes { Darwin.read(readFD, $0.baseAddress, 65536) }
        if n <= 0 { return nil }
        return String(decoding: buf[0..<n], as: UTF8.self).replacingOccurrences(of: "\r", with: "")
    }

    func drain() -> String {
        var out = ""
        for _ in 0..<20 {
            guard let c = read(timeout: 0.05), !c.isEmpty else { break }
            out += c
        }
        return out
    }

    func wait(_ seconds: TimeInterval) -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while process.isRunning && Date() < end { Thread.sleep(forTimeInterval: 0.05) }
        return !process.isRunning
    }

    func kill() {
        guard process.isRunning else { return }
        process.terminate()
        if !wait(3) { Darwin.kill(process.processIdentifier, SIGKILL) }
    }

    func close() {
        guard !closed else { return }
        closed = true
        if ownsFD { Darwin.close(readFD) }
        try? input.fileHandleForWriting.close()
    }
}
