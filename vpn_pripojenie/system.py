"""Systémové veci: pomocný skript cez polkit, služba Cisca, autoštart, notifikácie, kľúčenka."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from . import APP_ID

HELPER_INSTALLED = Path("/usr/libexec") / APP_ID / f"{APP_ID}-helper"
HELPER_SOURCE = Path(__file__).resolve().parent.parent / "helper" / f"{APP_ID}-helper"

AGENT_SERVICE = "vpnagentd"
AUTOSTART_SYSTEM = Path("/etc/xdg/autostart")
OUR_DESKTOP = f"{APP_ID}.desktop"


def user_autostart_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart"


# ------------------------------------------------------------------ pomocný skript (root cez polkit)

def helper_path() -> Optional[Path]:
    for p in (HELPER_INSTALLED, HELPER_SOURCE):
        if p.is_file():
            return p
    return None


def run_helper(*args: str, timeout: int = 120) -> tuple:
    """Spustí pomocný skript s právami správcu. Vráti (ok, text pre používateľa)."""
    helper = helper_path()
    pkexec = shutil.which("pkexec")
    if not helper:
        return False, "Chýba pomocný skript aplikácie – preinštalujte VPN Pripojenie."
    if not pkexec:
        return False, "Chýba pkexec (balík polkit / pkexec)."
    cmd = [pkexec, str(helper), *args]
    if helper == HELPER_SOURCE:
        cmd = [pkexec, "/usr/bin/python3", "-I", str(helper), *args]   # vývojová verzia bez inštalácie
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Overenie správcu trvalo príliš dlho."
    except OSError as e:
        return False, f"pkexec sa nedá spustiť: {e}"
    out = (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    if p.returncode == 0:
        return True, out
    if p.returncode == 126:
        return False, "Overenie správcu bolo zrušené."
    if p.returncode == 127:
        return False, "Na túto akciu nemáte oprávnenie (treba heslo správcu počítača)."
    return False, out or f"Pomocný skript skončil s chybou {p.returncode}."


# ------------------------------------------------------------------ služba Cisca

def agent_status() -> str:
    """active | inactive | failed | unknown"""
    exe = shutil.which("systemctl")
    if not exe:
        return "unknown"
    try:
        p = subprocess.run([exe, "is-active", AGENT_SERVICE], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=10)
        s = p.stdout.decode().strip()
        return s or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def agent_running() -> bool:
    st = agent_status()
    if st == "unknown":     # bez systemd – podľa procesu
        return any(_proc_name(pid) == AGENT_SERVICE for pid in _pids())
    return st == "active"


def _pids():
    for d in os.listdir("/proc"):
        if d.isdigit():
            yield int(d)


def _proc_name(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


# ------------------------------------------------------------------ okno Cisca a autoštart

def cisco_ui_path(cli_path: Optional[str]) -> Optional[str]:
    if not cli_path:
        return None
    d = Path(cli_path).parent
    for name in ("vpnui", "csc_ui"):
        if (d / name).is_file():
            return str(d / name)
    return None


def start_cisco_ui(cli_path: Optional[str]) -> bool:
    ui = cisco_ui_path(cli_path)
    if not ui:
        return False
    try:
        subprocess.Popen([ui], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except OSError:
        return False


def cisco_autostart_files() -> list:
    """Systémové .desktop súbory autoštartu, ktoré spúšťajú okno Cisca."""
    out = []
    dirs = [AUTOSTART_SYSTEM]
    for d in dirs:
        try:
            files = sorted(d.glob("*.desktop"))
        except OSError:
            continue
        for f in files:
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            m = re.search(r"^Exec\s*=\s*(.+)$", text, re.M)
            exe = m.group(1) if m else ""
            if re.search(r"vpnui|csc_ui", exe) or ("cisco" in f.name.lower() and "vpn" in text.lower()):
                out.append(f)
    return out


def _override(name: str) -> Path:
    return user_autostart_dir() / name


def _is_hidden(path: Path) -> bool:
    try:
        return re.search(r"^Hidden\s*=\s*true\s*$", path.read_text(errors="replace"), re.M | re.I) is not None
    except OSError:
        return False


def _hide(name: str, marker: str) -> None:
    d = user_autostart_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(
        "[Desktop Entry]\nType=Application\nName=" + marker + "\nHidden=true\n"
        f"X-{APP_ID}-Override=true\n", encoding="utf-8")


def _unhide(name: str) -> None:
    p = _override(name)
    try:
        if f"X-{APP_ID}-Override=true" in p.read_text(errors="replace"):
            p.unlink()
    except OSError:
        pass


def cisco_gui_disabled() -> bool:
    files = cisco_autostart_files()
    return bool(files) and all(_is_hidden(_override(f.name)) for f in files)


def mode() -> str:
    """„cisco“ = používa sa pôvodné okno Cisca, „vpnpripojenie“ = naša aplikácia (predvolené)."""
    return "cisco" if _is_hidden(_override(OUR_DESKTOP)) else "vpnpripojenie"


def disable_cisco_gui() -> list:
    """Vypne autoštart okna Cisca pre tohto používateľa (vratné, bez práv správcu)."""
    done = []
    for f in cisco_autostart_files():
        if not _is_hidden(_override(f.name)):
            _hide(f.name, "Cisco Secure Client (vypnuté aplikáciou VPN Pripojenie)")
            done.append(f.name)
    return done


def switch_to_cisco() -> str:
    for f in cisco_autostart_files():
        _unhide(f.name)
    _hide(OUR_DESKTOP, "VPN Pripojenie (vypnuté – používa sa pôvodné Cisco)")
    return ("Pôvodné okno Cisco Secure Client sa bude znova spúšťať po prihlásení. "
            "VPN Pripojenie ostáva nainštalované, po prihlásení sa už nespúšťa.")


def switch_to_vpnpripojenie() -> str:
    _unhide(OUR_DESKTOP)
    disable_cisco_gui()
    return "VPN Pripojenie je znova hlavná aplikácia: spúšťa sa po prihlásení, okno Cisca nie."


# ------------------------------------------------------------------ notifikácie

def notify(title: str, body: str, icon: str = APP_ID) -> None:
    ns = shutil.which("notify-send")
    try:
        if ns:
            subprocess.Popen([ns, "-a", "VPN Pripojenie", "-i", icon, title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
        gd = shutil.which("gdbus")
        if gd:
            subprocess.Popen([gd, "call", "--session", "--dest", "org.freedesktop.Notifications",
                              "--object-path", "/org/freedesktop/Notifications",
                              "--method", "org.freedesktop.Notifications.Notify",
                              "VPN Pripojenie", "0", icon, title, body, "[]", "{}", "5000"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


# ------------------------------------------------------------------ kľúčenka (GNOME Keyring / KWallet cez Secret Service)

def keyring_available() -> bool:
    return shutil.which("secret-tool") is not None


def _attrs(host: str, user: str) -> list:
    return ["aplikacia", APP_ID, "pripojenie", host, "pouzivatel", user]


def keyring_get(host: str, user: str) -> Optional[str]:
    if not keyring_available() or not user:
        return None
    try:
        p = subprocess.run(["secret-tool", "lookup", *_attrs(host, user)], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace") or None


def keyring_set(host: str, user: str, password: str) -> bool:
    if not keyring_available() or not user:
        return False
    try:
        p = subprocess.run(["secret-tool", "store", "--label", f"VPN Pripojenie – {host} ({user})",
                            *_attrs(host, user)], input=password.encode(), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60)
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def keyring_clear(host: str, user: str) -> None:
    if not keyring_available():
        return
    try:
        subprocess.run(["secret-tool", "clear", *_attrs(host, user)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def open_path(path: Path) -> None:
    exe = shutil.which("xdg-open")
    if exe:
        try:
            subprocess.Popen([exe, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass


def distro() -> str:
    try:
        text = Path("/etc/os-release").read_text()
        m = re.search(r'^PRETTY_NAME="?([^"\n]+)', text, re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "") or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11")
