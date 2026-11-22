"""Práca s Cisco CLI (`/opt/cisco/secureclient/bin/vpn`).

Rovnaké poučenia ako vo Windows verzii:
* pripája sa cez HostName z profilu (v úvodzovkách, ak má medzery), nie cez adresu;
* pred pripojením sa zavrie okno Cisca (vpnui), inak „Connect capability is unavailable“;
* na výzvy (Group / Username / Password / Second Password / [y/n]) sa odpovedá až keď naozaj prídu;
* neznáma výzva → po 20 s chyba s jej textom; chyba Cisca + návrat na `VPN>` → okamžitý koniec;
* heslo sa v logu a vo výpise maskuje.

Pripájanie beží cez `subprocess.Popen(stdin=PIPE)` v samostatnom vlákne (volá ho GUI).
Výstup Cisca sa číta cez pseudoterminál, aby ho program nebufferoval a výzvy prišli hneď.
"""
from __future__ import annotations

import enum
import errno
import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import config as C
from .messages import friendly
from .profiles import VpnProfile

CLI_CANDIDATES = [
    "/opt/cisco/secureclient/bin/vpn",   # Cisco Secure Client 5
    "/opt/cisco/anyconnect/bin/vpn",     # AnyConnect 4.x
]

UI_NAMES = ("vpnui", "csc_ui")           # okno Cisca na Linuxe

def _env() -> dict:
    return {**os.environ, "LANG": "C", "LC_ALL": "C"}


def find_cli(configured: str = "") -> Optional[str]:
    cands = ([os.path.expanduser(configured)] if configured else []) + CLI_CANDIDATES
    for p in cands:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def quote_host(host: str) -> str:
    host = host.strip()
    if len(host) >= 2 and host[0] == host[-1] == '"':
        host = host[1:-1].strip()
    return f'"{host}"' if " " in host else host


def _ends(text: str, pattern: str) -> bool:
    return re.search(pattern + r"\s*$", text, re.I) is not None


def last_line(text: str) -> str:
    for line in reversed(text.replace("\r", "").split("\n")):
        if line.strip():
            return line.strip()
    return ""


def last_cisco_message(text: str) -> str:
    found = ""
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line.startswith(">>"):
            continue
        line = line.lstrip(">").strip()
        for pre in ("notice:", "warning:", "error:", "state:"):
            if line.lower().startswith(pre):
                line = line[len(pre):].strip()
                break
        if line:
            found = line
    return found


def last_error_line(text: str) -> str:
    found = ""
    for raw in text.split("\n"):
        line = raw.strip().lstrip(">").strip()
        if "error" in line.lower():
            found = line
    return found


def mask(text: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "********")
    return text


# ------------------------------------------------------------------ výsledky

class Result(enum.Enum):
    CONNECTED = "connected"
    LOGIN_FAILED = "login_failed"
    OTHER_CLIENT = "other_client"
    CANCELLED = "cancelled"
    NEED_USER = "need_user"
    DECLINED = "declined"          # používateľ neprijal správu servera / nedôveryhodný server
    FAILED = "failed"


@dataclass
class Outcome:
    result: Result
    error: str = ""                 # slovensky
    original: str = ""              # pôvodný text Cisca (anglicky)


@dataclass
class Stats:
    state: str = ""
    client_ip: str = ""
    client_ipv6: str = ""
    server: str = ""
    duration: Optional[int] = None  # sekundy
    bytes_sent: Optional[int] = None
    bytes_received: Optional[int] = None
    protocol: str = ""
    cipher: str = ""
    tunnel_mode: str = ""
    raw: str = ""
    routes: list = field(default_factory=list)


# kroky v okne: 0 služba Cisca, 1 kontaktujem server, 2 overujem prihlásenie, 3 nastavujem pripojenie, 4 hotovo
STEP_LABELS = ["Služba Cisca (vpnagentd) beží", "Kontaktujem server", "Overujem prihlásenie", "Nastavujem pripojenie"]

_STEP_CONNECTING = re.compile(r"establishing|state:\s*connecting|reconnecting|connecting to", re.I)
_LOGIN_FAILED = re.compile(r"login failed|authentication failed|access denied|login denied", re.I)
_OTHER = re.compile(r"connect capability is unavailable|another .*(acquired|running)", re.I)
_UNTRUSTED = re.compile(r"untrusted|security threat|certificate|not trusted|change the setting", re.I)


class CiscoCli:
    def __init__(self, path: Optional[str], use_pty: bool = True, timeout: int = 90):
        self.path = path
        self.use_pty = use_pty
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.path)

    # ---------- jednoduché príkazy

    def run(self, *args: str, timeout: float = 20) -> str:
        if not self.path:
            return ""
        try:
            p = subprocess.run([self.path, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=timeout, env=_env(), start_new_session=True)
            return p.stdout.decode("utf-8", "replace").replace("\r", "")
        except subprocess.TimeoutExpired as e:
            out = e.output or b""
            return out.decode("utf-8", "replace").replace("\r", "")
        except OSError:
            return ""

    def version(self) -> str:
        out = self.run("-v", timeout=10)
        m = re.search(r"version\s+(\d+(?:\.\d+){1,3})", out, re.I)
        if m:
            return m.group(1)
        if self.path:   # záložne súbor update.txt / version v inštalácii Cisca
            root = Path(self.path).resolve().parent.parent
            for f in (root / "update.txt", root / "vpn" / "update.txt", root / "version"):
                try:
                    m = re.search(r"\d+(?:[.,]\d+){2,3}", f.read_text(errors="replace"))
                    if m:
                        return m.group(0).replace(",", ".")
                except OSError:
                    pass
        return ""

    def hosts(self) -> list:
        out = self.run("hosts", timeout=15)
        names = []
        for raw in out.split("\n"):
            if raw.lstrip().startswith(">>"):
                continue
            m = re.match(r"^\s*>\s+(\S.*?)\s*$", raw)
            if m and m.group(1) not in names:
                names.append(m.group(1))
        return names

    def state(self) -> str:
        out = self.run("state", timeout=20)
        ms = re.findall(r"state:\s*(\w+)", out, re.I)
        return ms[-1] if ms else "Unknown"

    def stats(self) -> Stats:
        out = self.run("stats", timeout=20)
        st = Stats(raw=out)

        def grab(label: str) -> str:
            m = re.search(rf"^\s*{label}\s*:\s*(.+?)\s*$", out, re.I | re.M)
            return m.group(1) if m else ""

        def num(label: str) -> Optional[int]:
            v = grab(label)
            v = re.sub(r"[^\d]", "", v)
            return int(v) if v else None

        ms = re.findall(r"state:\s*(\w+)", out, re.I)
        st.state = ms[-1] if ms else grab("Connection State")
        st.client_ip = grab(r"Client Address \(IPv4\)")
        st.client_ipv6 = grab(r"Client Address \(IPv6\)")
        st.server = grab("Server Address")
        st.protocol = grab("Protocol")
        st.cipher = grab("Protocol Cipher")
        st.tunnel_mode = grab(r"Tunnel Mode \(IPv4\)")
        st.bytes_sent = num("Bytes Sent")
        st.bytes_received = num("Bytes Received")
        m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2})", out, re.I)
        if m:
            st.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        # zabezpečené trasy (Secured Routes)
        sec = re.search(r"\[\s*Secured Routes[^\]]*\]\s*\n(.*?)(?:\n\s*\n|\n\s*\[|\Z)", out, re.I | re.S)
        if sec:
            for line in sec.group(1).split("\n"):
                line = line.strip()
                if re.match(r"^\d+\.\d+\.\d+\.\d+", line):
                    st.routes.append(line.split()[0] + (" /" + line.split()[1] if len(line.split()) > 1 else ""))
        return st

    def disconnect(self) -> str:
        out = self.run("disconnect", timeout=30)
        write_log("disconnect", out, "")
        return out

    # ---------- okno Cisca a zabudnuté CLI

    def close_cisco_ui(self) -> list:
        """Ukončí okno Cisca a staré `vpn` procesy tohto používateľa. Vráti, čo ukončil."""
        killed = []
        me, uid = os.getpid(), os.getuid()
        cli_real = os.path.realpath(self.path) if self.path else None
        for pid_s in os.listdir("/proc"):
            if not pid_s.isdigit() or int(pid_s) == me:
                continue
            pid = int(pid_s)
            try:
                if os.stat(f"/proc/{pid}").st_uid != uid:
                    continue
                comm = Path(f"/proc/{pid}/comm").read_text().strip()
                exe = os.path.realpath(f"/proc/{pid}/exe")
            except OSError:
                continue
            if comm in UI_NAMES or (cli_real and exe == cli_real):
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed.append(f"{comm} ({pid})")
                except OSError:
                    pass
        if killed:
            time.sleep(0.7)
        return killed

    # ---------- pripojenie

    def connect(
        self,
        prof: VpnProfile,
        user: str,
        password: str,
        second: str,
        progress: Callable[[int, str], None] = lambda s, m: None,
        output: Callable[[str], None] = lambda t: None,
        ask: Callable[[str, str], Optional[bool]] = lambda kind, text: True,
        cancelled: Callable[[], bool] = lambda: False,
        auto_banner: bool = False,
    ) -> Outcome:
        """Pripojí sa. `ask(kind, text)` – kind „banner“ alebo „untrusted“; vráti True/False, None = zrušené."""
        if not self.path:
            return Outcome(Result.FAILED, "Nenašiel sa Cisco Secure Client (príkaz vpn).")
        killed = self.close_cisco_ui()
        if killed:
            output("Ukončené: " + ", ".join(killed) + "\n")

        sent_log: list[str] = []
        step = 1
        progress(step, "")

        try:
            proc, fd = self._spawn()
        except OSError as e:
            return Outcome(Result.FAILED, f"Cisco CLI sa nedá spustiť: {e}")

        buf = ""
        handled = 0
        users = passwords = seconds = 0
        start = last_change = time.monotonic()
        last_progress = (step, "")
        result: Optional[Result] = None
        error = ""
        original = ""
        eof = False

        def send(line: str, shown: str) -> None:
            try:
                proc.stdin.write((line + "\n").encode())
                proc.stdin.flush()
            except (OSError, ValueError):
                pass
            stamp = datetime.now().strftime("%H:%M:%S")
            sent_log.append(f"[{stamp}] odoslané: {shown}")
            output(f"  → {shown}\n")

        connect_cmd = "connect " + quote_host(prof.host_name)
        send(connect_cmd, connect_cmd)

        try:
            while True:
                chunk = "" if eof else self._read(fd, 0.15)
                if chunk is None:
                    eof = True
                    chunk = ""
                if chunk:
                    buf += chunk
                    last_change = time.monotonic()
                    output(mask(chunk, password, second))
                elif eof and proc.poll() is None:
                    time.sleep(0.15)

                tail = buf[handled:]
                low = tail.lower()

                if step < 3 and _STEP_CONNECTING.search(tail) and (
                        passwords or users or not prof.needs_password or "establishing" in buf.lower()):
                    step = 3
                msg = last_cisco_message(buf)
                if (step, msg) != last_progress:
                    last_progress = (step, msg)
                    progress(step, msg)

                if cancelled():
                    result = Result.CANCELLED
                    break
                if re.search(r"state:\s*Connected", tail, re.I):
                    result = Result.CONNECTED
                    progress(4, "Connected")
                    break
                if _LOGIN_FAILED.search(tail):
                    result = Result.LOGIN_FAILED
                    break
                if _OTHER.search(tail):
                    result = Result.OTHER_CLIENT
                    break
                if eof and proc.poll() is not None:
                    break
                if "error:" in low and _ends(tail, r"VPN>"):
                    result = Result.FAILED
                    error, original = self._friendly(tail, prof)
                    break

                if _ends(tail, r"\[y/n\]:?"):
                    text = _prompt_text(tail)
                    kind = "untrusted" if _UNTRUSTED.search(text) else "banner"
                    if kind == "banner" and auto_banner:
                        answer: Optional[bool] = True
                    else:
                        answer = ask(kind, text)
                    if answer is None:
                        result = Result.CANCELLED
                        break
                    send("y" if answer else "n", "y" if answer else "n")
                    handled = len(buf)
                    if not answer:
                        result = Result.DECLINED
                        error = ("Správu servera ste neprijali, pripojenie sa nevytvorí." if kind == "banner"
                                 else "Pripojenie k nedôveryhodnému serveru ste odmietli.")
                        original = last_line(text)
                        break
                    continue
                if _ends(tail, r"Second Password:"):
                    if not prof.needs_second or not second:
                        result = Result.FAILED
                        error = ("Pripojenie si pýta druhé heslo. Správca má pre toto pripojenie nastaviť "
                                 "prihlásenie „Meno a dve heslá“.")
                        break
                    seconds += 1
                    if seconds > 1:
                        result = Result.LOGIN_FAILED
                        break
                    step = max(step, 2)
                    send(second, "********")
                    handled = len(buf)
                    continue
                if _ends(tail, r"Password:"):
                    if not prof.needs_password or not password:
                        result = Result.FAILED
                        error = (f"Pripojenie si pýta heslo, ale je nastavené na „{prof.auth.label}“. "
                                 "Správca má upraviť spôsob prihlásenia.")
                        break
                    passwords += 1
                    if passwords > 1:
                        result = Result.LOGIN_FAILED
                        break
                    step = max(step, 2)
                    send(password, "********")
                    handled = len(buf)
                    continue
                if _ends(tail, r"Username:(\s*\[[^\]]*\])?"):
                    if not user:
                        result = Result.NEED_USER
                        break
                    users += 1
                    if users > 1:
                        result = Result.LOGIN_FAILED
                        break
                    step = max(step, 2)
                    send(user, user)
                    handled = len(buf)
                    continue
                if _ends(tail, r"Group:(\s*\[[^\]]*\])?"):
                    g = prof.group or ""
                    step = max(step, 2)
                    send(g, g or "(Enter – predvolená skupina)")
                    handled = len(buf)
                    continue

                now = time.monotonic()
                if now - last_change > 20 and tail.rstrip().endswith(":"):
                    result = Result.FAILED
                    error = "Cisco čaká na otázku, ktorú aplikácia nepozná."
                    original = last_line(tail)
                    break
                if now - start > self.timeout:
                    result = Result.FAILED
                    error = "Pripájanie trvalo príliš dlho."
                    original = last_line(buf)
                    break
        finally:
            if proc.poll() is None:
                if result == Result.CONNECTED:
                    try:
                        proc.stdin.write(b"exit\n")
                        proc.stdin.flush()
                        proc.stdin.close()
                    except (OSError, ValueError):
                        pass
                    try:
                        proc.wait(3)
                    except subprocess.TimeoutExpired:
                        _kill(proc)
                else:
                    _kill(proc)
            rest = self._drain(fd)
            if rest:
                buf += rest
            if self.use_pty:
                try:
                    os.close(fd)
                except OSError:
                    pass
            for f in (proc.stdin, proc.stdout):
                if f:
                    try:
                        f.close()
                    except OSError:
                        pass
            write_log("connect " + prof.host_name, mask(buf, password, second), "\n".join(sent_log))

        if result in (Result.CANCELLED, Result.NEED_USER, Result.DECLINED):
            if result != Result.DECLINED and self.state() == "Connected":
                return Outcome(Result.CONNECTED)
            return Outcome(result, error, original)
        if result in (Result.CONNECTED, None):
            if self.state() == "Connected":
                return Outcome(Result.CONNECTED)
            if result is None:
                err = last_error_line(buf) or last_line(buf)
                sk, orig = friendly(err)
                return Outcome(Result.FAILED, sk, orig)
        if result == Result.OTHER_CLIENT:
            sk, orig = friendly("connect capability is unavailable")
            return Outcome(result, sk, last_line(buf))
        if result == Result.LOGIN_FAILED:
            return Outcome(result, "", last_error_line(buf) or last_line(buf))
        return Outcome(result or Result.FAILED, error, original)

    def _friendly(self, output: str, prof: VpnProfile) -> tuple[str, str]:
        err = last_error_line(output) or last_line(output)
        sk, orig = friendly(err)
        if prof.manual:
            sk += " Pri ručne zadanej adrese Cisco nepoužije nastavenia profilu – skúste pripojenie z roletky."
        return sk, orig

    # ---------- proces a čítanie

    def _spawn(self):
        args = [self.path, "-s"]
        if self.use_pty:
            master, slave = pty.openpty()
            try:
                attrs = termios.tcgetattr(slave)
                attrs[1] &= ~termios.OPOST          # bez \r\n
                attrs[3] &= ~termios.ECHO
                termios.tcsetattr(slave, termios.TCSANOW, attrs)
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 250, 0, 0))
            except (OSError, termios.error):
                pass
            try:
                proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=slave, stderr=slave,
                                        env=_env(), start_new_session=True, close_fds=True)
            finally:
                os.close(slave)
            return proc, master
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=_env(), start_new_session=True)
        return proc, proc.stdout.fileno()

    @staticmethod
    def _read(fd: int, timeout: float) -> Optional[str]:
        """Text alebo '' (nič nové); None = koniec výstupu."""
        try:
            r, _, _ = select.select([fd], [], [], timeout)
        except (OSError, ValueError):
            return None
        if not r:
            return ""
        try:
            data = os.read(fd, 65536)
        except OSError as e:
            if e.errno == errno.EIO:     # pty: proces skončil
                return None
            raise
        if not data:
            return None
        return data.decode("utf-8", "replace").replace("\r", "")

    def _drain(self, fd: int) -> str:
        out = ""
        for _ in range(20):
            chunk = self._read(fd, 0.05)
            if not chunk:
                break
            out += chunk
        return out


def _prompt_text(tail: str) -> str:
    """Text správy servera / varovania pred výzvou [y/n] – bez riadkov so stavom."""
    lines = []
    for raw in tail.split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if s.startswith(">>") and ("state:" in s.lower() or "contacting" in s.lower()):
            continue
        if s.startswith("VPN>"):
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    return text


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        proc.wait(3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass


# ------------------------------------------------------------------ log

MAX_LOG = 256 * 1024


def write_log(what: str, output: str, sent: str) -> None:
    p = C.log_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        old = ""
        if p.exists() and p.stat().st_size < MAX_LOG:
            old = p.read_text(encoding="utf-8", errors="replace")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (f"=== {what} {stamp} ===\n--- čo poslala aplikácia ---\n{sent}\n"
                 f"--- výstup Cisco CLI ---\n{output}\n\n")
        p.write_text(old + entry, encoding="utf-8")
        os.chmod(p, 0o600)
    except OSError:
        pass


def format_bytes(n: Optional[int]) -> str:
    if n is None:
        return "–"
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return (f"{n:.1f} {unit}" if unit != "B" else f"{n} B").replace(".", ",")
        n /= 1024
    return str(n)


def format_duration(sec: int) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
