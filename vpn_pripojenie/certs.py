"""Certifikáty pre Cisco na Linuxe (úložisko PEM).

Cisco číta:
* CA certifikáty z ~/.cisco/certificates/ca/*.pem (používateľ) a /opt/.cisco/certificates/ca/ (všetci);
* osobný certifikát z ~/.cisco/certificates/client/<meno>.pem a jeho kľúč
  z ~/.cisco/certificates/client/private/<meno>.key (rovnaké meno súboru).
Súbor .p12/.pfx preto nestačí skopírovať – rozbalí sa cez openssl na certifikát a kľúč.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SYSTEM_CA_DIR = Path("/opt/.cisco/certificates/ca")
WARN_DAYS = 30          # predvolene: upozorniť 30 dní pred vypršaním (správca môže zmeniť)


def cisco_home() -> Path:
    return Path.home() / ".cisco" / "certificates"


def user_ca_dir() -> Path:
    return cisco_home() / "ca"


def client_dir() -> Path:
    return cisco_home() / "client"


def private_dir() -> Path:
    return client_dir() / "private"


class CertError(Exception):
    pass


@dataclass
class CertInfo:
    path: Path
    subject: str = ""
    issuer: str = ""
    serial: str = ""
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    has_key: bool = False
    system: bool = False
    error: str = ""

    @property
    def cn(self) -> str:
        m = re.search(r"CN\s*=\s*([^,/]+)", self.subject)
        return m.group(1).strip() if m else (self.subject or self.path.stem)

    @property
    def issuer_cn(self) -> str:
        m = re.search(r"CN\s*=\s*([^,/]+)", self.issuer)
        return m.group(1).strip() if m else self.issuer

    @property
    def expired(self) -> bool:
        return bool(self.not_after and self.not_after < datetime.now(timezone.utc))

    @property
    def days_left(self) -> Optional[int]:
        if not self.not_after:
            return None
        return (self.not_after - datetime.now(timezone.utc)).days

    def expires_within(self, days: int = WARN_DAYS) -> bool:
        """Vyprší do `days` dní (0 = neupozorňovať)."""
        d = self.days_left
        return bool(days > 0 and d is not None and not self.expired and d < days)

    @property
    def expires_soon(self) -> bool:
        return self.expires_within(WARN_DAYS)

    @property
    def usable(self) -> bool:
        """Osobný certifikát, ktorý Cisco môže použiť: čitateľný, s kľúčom, platný."""
        return not self.error and self.has_key and not self.expired

    @property
    def valid_from(self) -> str:
        return self.not_before.strftime("%d. %m. %Y") if self.not_before else "?"

    @property
    def valid_to(self) -> str:
        return self.not_after.strftime("%d. %m. %Y") if self.not_after else "?"


def _openssl(args: list, stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
    exe = shutil.which("openssl")
    if not exe:
        raise CertError("Chýba program openssl (balík openssl).")
    return subprocess.run([exe, *args], input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)


def inspect(path: Path, system: bool = False) -> CertInfo:
    info = CertInfo(path=path, system=system)
    try:
        p = _openssl(["x509", "-noout", "-subject", "-issuer", "-serial", "-startdate", "-enddate", "-nameopt", "RFC2253", "-in", str(path)])
    except (CertError, OSError, subprocess.SubprocessError) as e:
        info.error = str(e)
        return info
    if p.returncode != 0:
        info.error = "nie je to platný certifikát PEM"
        return info
    out = p.stdout.decode(errors="replace")
    for line in out.splitlines():
        k, _, v = line.partition("=")
        k = k.strip().lower()
        if k == "subject":
            info.subject = v.strip()
        elif k == "issuer":
            info.issuer = v.strip()
        elif k == "serial":
            info.serial = v.strip()
        elif k in ("notafter", "notbefore"):
            try:
                d = datetime.strptime(" ".join(v.split()), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if k == "notafter":
                info.not_after = d
            else:
                info.not_before = d
    return info


def list_ca() -> list:
    out = []
    for d, system in ((user_ca_dir(), False), (SYSTEM_CA_DIR, True)):
        try:
            files = sorted(f for f in d.iterdir() if f.suffix.lower() in (".pem", ".crt", ".cer") and f.is_file())
        except OSError:
            continue
        out.extend(inspect(f, system) for f in files)
    return out


def list_client() -> list:
    out = []
    try:
        files = sorted(f for f in client_dir().glob("*.pem") if f.is_file())
    except OSError:
        return out
    for f in files:
        info = inspect(f)
        info.has_key = (private_dir() / (f.stem + ".key")).is_file()
        out.append(info)
    return out


def _safe_name(text: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return (s or fallback)[:60]


def to_pem(src: Path) -> bytes:
    """Načíta certifikát (.crt/.cer/.pem, PEM alebo DER) a vráti ho v PEM."""
    for fmt in ("PEM", "DER"):
        p = _openssl(["x509", "-inform", fmt, "-in", str(src), "-outform", "PEM"])
        if p.returncode == 0 and b"BEGIN CERTIFICATE" in p.stdout:
            return p.stdout
    raise CertError("Súbor nie je certifikát (PEM ani DER).")


def import_ca_user(src: Path) -> Path:
    pem = to_pem(src)
    d = user_ca_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkstemp(dir=d, suffix=".tmp")[1])
    tmp.write_bytes(pem)
    info = inspect(tmp)
    dest = d / (_safe_name(info.cn, src.stem) + ".pem")
    os.chmod(tmp, 0o644)
    tmp.replace(dest)
    return dest


def ca_to_tempfile(src: Path) -> Path:
    """PEM v dočasnom súbore pre pomocný skript (inštalácia CA pre všetkých)."""
    pem = to_pem(src)
    fd, name = tempfile.mkstemp(prefix="vpn-pripojenie-ca-", suffix=".pem")
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    os.chmod(name, 0o644)
    return Path(name)


def import_p12(src: Path, password: str, name_hint: str = "") -> tuple:
    """Rozbalí .p12/.pfx na certifikát + kľúč (+ CA z balíka). Vráti (cesta k certifikátu, počet CA)."""
    pw = (password + "\n").encode()

    def run(extra: list) -> subprocess.CompletedProcess:
        p = _openssl(["pkcs12", "-in", str(src), "-passin", "stdin", *extra], stdin=pw)
        if p.returncode != 0 and b"unsupported" in p.stderr.lower() + p.stdout.lower():
            p = _openssl(["pkcs12", "-legacy", "-in", str(src), "-passin", "stdin", *extra], stdin=pw)
        return p

    cert = run(["-clcerts", "-nokeys"])
    if cert.returncode != 0:
        err = cert.stderr.decode(errors="replace").lower()
        if "mac verify" in err or "invalid password" in err or "bad decrypt" in err:
            raise CertError("Nesprávne heslo k certifikátu.")
        raise CertError("Súbor sa nedá otvoriť ako .p12/.pfx: " + _first_line(cert.stderr))
    key = run(["-nocerts", "-nodes"])
    if key.returncode != 0 or b"PRIVATE KEY" not in key.stdout:
        raise CertError("V súbore chýba súkromný kľúč: " + _first_line(key.stderr))
    if b"BEGIN CERTIFICATE" not in cert.stdout:
        raise CertError("V súbore chýba osobný certifikát.")
    cas = run(["-cacerts", "-nokeys"])

    cdir, pdir = client_dir(), private_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    os.chmod(pdir, 0o700)

    fd, tmpname = tempfile.mkstemp(dir=cdir, suffix=".tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(_only_pem(cert.stdout, b"CERTIFICATE"))
    info = inspect(Path(tmpname))
    base = _safe_name(name_hint or info.cn, src.stem)
    cert_path = cdir / f"{base}.pem"
    key_path = pdir / f"{base}.key"

    kfd, ktmp = tempfile.mkstemp(dir=pdir, suffix=".tmp")
    with os.fdopen(kfd, "wb") as f:
        f.write(_only_pem(key.stdout, b"PRIVATE KEY"))
    os.chmod(ktmp, 0o600)
    os.chmod(tmpname, 0o644)
    Path(ktmp).replace(key_path)
    Path(tmpname).replace(cert_path)

    n_ca = 0
    if cas.returncode == 0 and b"BEGIN CERTIFICATE" in cas.stdout:
        user_ca_dir().mkdir(parents=True, exist_ok=True)
        for i, block in enumerate(_pem_blocks(cas.stdout, b"CERTIFICATE"), start=1):
            fd, t = tempfile.mkstemp(dir=user_ca_dir(), suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                f.write(block)
            ci = inspect(Path(t))
            os.chmod(t, 0o644)
            Path(t).replace(user_ca_dir() / (_safe_name(ci.cn, f"{base}-ca{i}") + ".pem"))
            n_ca += 1
    return cert_path, n_ca


def remove_client(cert: Path) -> None:
    key = private_dir() / (cert.stem + ".key")
    for f in (cert, key):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def remove_user_ca(path: Path) -> None:
    if path.parent.resolve() != user_ca_dir().resolve():
        raise CertError("Mimo priečinka používateľa sa CA maže len cez správcu.")
    path.unlink(missing_ok=True)


def _pem_blocks(data: bytes, kind: bytes) -> list:
    pat = re.compile(rb"-----BEGIN [A-Z ]*" + kind + rb"-----.*?-----END [A-Z ]*" + kind + rb"-----", re.S)
    return [m.group(0) + b"\n" for m in pat.finditer(data)]


def _only_pem(data: bytes, kind: bytes) -> bytes:
    """Bez riadkov „Bag Attributes“ – len bloky PEM."""
    return b"".join(_pem_blocks(data, kind))


def _first_line(b: bytes) -> str:
    for line in b.decode(errors="replace").splitlines():
        if line.strip():
            return line.strip()
    return ""


# ------------------------------------------------------------------ prehľad pre okno (čo hlásiť používateľovi)

def issuer_installed(cert: CertInfo, cas: list) -> bool:
    """Je nainštalovaná CA, ktorá certifikát vydala? (porovnanie subjektu CA s vydavateľom)"""
    norm = lambda s: re.sub(r"\s+", "", s or "").lower()
    return any(norm(c.subject) == norm(cert.issuer) for c in cas if not c.error)


def duplicates(certs_list: list) -> dict:
    """Cesta → názvy ostatných súborov s rovnakým certifikátom (subjekt + sériové číslo)."""
    groups: dict = {}
    for c in certs_list:
        if c.error:
            continue
        groups.setdefault((c.subject, c.serial), []).append(c)
    out = {}
    for same in groups.values():
        if len(same) > 1:
            for c in same:
                out[c.path] = [o.path.name for o in same if o is not c]
    return out


def describe_expiry(c: CertInfo, days: int = WARN_DAYS) -> str:
    """„platný do …“ doplnené o varovanie – rovnaký text v tabuľke aj v hláseniach."""
    if c.error:
        return c.error
    if c.expired:
        return f"{c.valid_to} – EXPIROVANÝ"
    if c.expires_within(days):
        d = c.days_left or 0
        return f"{c.valid_to} – vyprší o {d} {_days_word(d)}"
    return c.valid_to


def expiry_warnings(days: int = WARN_DAYS, clients: Optional[list] = None, cas: Optional[list] = None) -> list:
    """Varovania o vypršaní pre hlavné okno: list[(závažnosť 'error'|'warn', text)]."""
    if days <= 0:
        return []
    clients = list_client() if clients is None else clients
    cas = list_ca() if cas is None else cas
    out = []
    for c in clients:
        if c.error:
            continue
        if c.expired:
            out.append(("error", f"Váš osobný certifikát {c.cn} vypršal {c.valid_to}. Prihlásenie certifikátom "
                                 "nebude fungovať – požiadajte správcu o nový."))
        elif c.expires_within(days):
            d = c.days_left or 0
            out.append(("warn", f"Váš osobný certifikát {c.cn} vyprší o {d} {_days_word(d)} ({c.valid_to}). "
                                "Požiadajte správcu o nový."))
    for c in cas:
        if c.error:
            continue
        if c.expired:
            out.append(("error", f"CA certifikát {c.cn} vypršal {c.valid_to} – server sa ním už neoverí."))
        elif c.expires_within(days):
            d = c.days_left or 0
            out.append(("warn", f"CA certifikát {c.cn} vyprší o {d} {_days_word(d)} ({c.valid_to})."))
    out.sort(key=lambda x: x[0] != "error")
    return out


def _days_word(n: int) -> str:
    return "deň" if n == 1 else ("dni" if 2 <= n <= 4 else "dní")


def firefox_profiles() -> list:
    """Profily Firefoxu (aj Snap a Flatpak) s úložiskom certifikátov NSS."""
    home = Path.home()
    bases = [home / ".mozilla/firefox", home / "snap/firefox/common/.mozilla/firefox",
             home / ".var/app/org.mozilla.firefox/.mozilla/firefox"]
    out = []
    for b in bases:
        try:
            out.extend(sorted(d for d in b.iterdir() if (d / "cert9.db").is_file()))
        except OSError:
            continue
    return out


def firefox_user_certs() -> Optional[list]:
    """Osobné certifikáty vo Firefoxe (príznak u). None = nedá sa zistiť (chýba certutil)."""
    exe = shutil.which("certutil")
    profs = firefox_profiles()
    if not profs:
        return []
    if not exe:
        return None
    names = []
    for d in profs:
        try:
            p = subprocess.run([exe, "-L", "-d", f"sql:{d}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in p.stdout.decode(errors="replace").splitlines():
            m = re.match(r"^(.+?)\s{2,}(\S*u\S*)\s*$", line)
            if m and "," in m.group(2) and m.group(1) not in names:
                names.append(m.group(1).strip())
    return names
