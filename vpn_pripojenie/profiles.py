"""XML profily Cisca a položky v roletke „Pripojenie (profil)“.

Zoznam pripojení: primárne `vpn hosts` (presne to, čo ponúka Cisco), záložne HostEntry z XML.
Položky: najprv tie zo správcovských nastavení (v ich poradí), potom nové pripojenia z Cisca
ako „Pripojenie N“ – rovnako ako vo Windows verzii.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import AdminConfig, AuthMode

PROFILE_DIRS = [
    Path("/opt/cisco/secureclient/vpn/profile"),   # Secure Client 5
    Path("/opt/cisco/anyconnect/profile"),         # AnyConnect 4.x
]

MAX_XML_BYTES = 1024 * 1024


@dataclass
class CiscoHost:
    host_name: str
    address: str = ""
    file: str = ""
    protocol: str = ""
    guess: Optional[AuthMode] = None


@dataclass
class ProfileFile:
    path: Path
    hosts: list = field(default_factory=list)   # list[CiscoHost]
    error: str = ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_profile(path: Path) -> ProfileFile:
    pf = ProfileFile(path=path)
    try:
        if path.stat().st_size > MAX_XML_BYTES:
            pf.error = "súbor je príliš veľký"
            return pf
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        pf.error = f"nedá sa prečítať: {e}"
        return pf
    if _local(root.tag) != "AnyConnectProfile":
        pf.error = "nie je to profil Cisco (chýba AnyConnectProfile)"
        return pf
    for he in root.iter():
        if _local(he.tag) != "HostEntry":
            continue
        h = CiscoHost(host_name="", file=path.name)
        for ch in he:
            name = _local(ch.tag)
            text = "".join(ch.itertext()).strip()
            if name == "HostName":
                h.host_name = text
            elif name == "HostAddress":
                h.address = text
            elif name == "PrimaryProtocol":
                h.protocol = (ch.text or "").strip()
                inner = text.upper()
                # IKE-RSA = len certifikát; EAP-* = meno a heslo (len odhad, potvrdí správca)
                for sub in ch.iter():
                    if _local(sub.tag) == "AuthMethodDuringIKENegotiation":
                        inner = (sub.text or "").upper()
                if "IKE-RSA" in inner:
                    h.guess = AuthMode.CERTIFIKAT
        if h.host_name:
            pf.hosts.append(h)
    return pf


def profile_dir_for(cli_path: Optional[str]) -> Path:
    """Priečinok profilov podľa nájdeného CLI (Secure Client 5 alebo starý AnyConnect)."""
    if cli_path and "/anyconnect/" in cli_path:
        return PROFILE_DIRS[1]
    return PROFILE_DIRS[0]


def list_profile_files(dirs: Optional[list] = None) -> list:
    out = []
    for d in dirs or PROFILE_DIRS:
        try:
            files = sorted(p for p in d.glob("*.xml") if p.is_file())
        except OSError:
            continue
        out.extend(parse_profile(p) for p in files)
    return out


def read_xml_hosts(dirs: Optional[list] = None) -> list:
    hosts = []
    for pf in list_profile_files(dirs):
        hosts.extend(pf.hosts)
    return hosts


def merge_hosts(cli_names: list, xml_hosts: list) -> list:
    """Názvy z `vpn hosts` doplnené o údaje z XML; bez CLI len XML."""
    names = list(dict.fromkeys(cli_names)) if cli_names else []
    if not names:
        names = list(dict.fromkeys(h.host_name for h in xml_hosts))
    result = []
    for n in names:
        found = next((x for x in xml_hosts if x.host_name.lower() == n.lower()), None)
        if found:
            result.append(CiscoHost(n, found.address, found.file, found.protocol, found.guess))
        else:
            result.append(CiscoHost(n))
    return result


@dataclass
class VpnProfile:
    host_name: str               # posiela sa do `vpn connect`
    name: str                    # názov v aplikácii
    auth: AuthMode
    address: str = ""
    xml_file: str = ""
    protocol: str = ""
    group: str = ""
    preset_user: str = ""
    hidden: bool = False
    is_default: bool = False
    missing: bool = False        # v nastaveniach, ale v Cisco už nie je
    configured: bool = False     # spôsob prihlásenia nastavil správca
    manual: bool = False         # ručne zadaná adresa servera

    @property
    def key(self) -> str:
        return f"{self.host_name}|{self.name}"

    def needs_user(self, learned: bool = False) -> bool:
        return self.auth in (AuthMode.MENO_HESLO_KOD, AuthMode.MENO_HESLO, AuthMode.DVE_HESLA) or learned

    @property
    def needs_password(self) -> bool:
        return self.auth != AuthMode.CERTIFIKAT

    @property
    def needs_code(self) -> bool:
        return self.auth in (AuthMode.MENO_HESLO_KOD, AuthMode.HESLO_KOD)

    @property
    def needs_second(self) -> bool:
        return self.auth == AuthMode.DVE_HESLA

    @property
    def subtitle(self) -> str:
        where = self.address or (self.host_name if self.host_name != self.name else "")
        return f"{where} · {self.auth.label}" if where else self.auth.label


def build_items(cfg: AdminConfig, hosts: list) -> list:
    result: list[VpnProfile] = []
    used = set()
    for it in cfg.Polozky:
        h = next((x for x in hosts if x.host_name.lower() == it.Cisco.lower()), None)
        mode = it.auth_mode
        p = VpnProfile(
            host_name=h.host_name if h else it.Cisco,
            name=it.Nazov or (h.host_name if h else it.Cisco),
            auth=mode or (h.guess if h and h.guess else cfg.default_auth),
            address=h.address if h else "",
            xml_file=h.file if h else "",
            protocol=h.protocol if h else "",
            group=it.Group or cfg.Group,
            preset_user=it.Meno,
            hidden=it.Skryt,
            is_default=it.Predvolene,
            missing=h is None,
            configured=mode is not None,
        )
        result.append(p)
        used.add(p.host_name.lower())
    for n, h in enumerate(hosts, start=1):
        if h.host_name.lower() in used:
            continue
        result.append(VpnProfile(
            host_name=h.host_name, name=f"Pripojenie {n}",
            auth=h.guess or cfg.default_auth, address=h.address, xml_file=h.file,
            protocol=h.protocol, group=cfg.Group,
        ))
    seen = False
    for p in result:   # predvolená môže byť len jedna
        if p.is_default and seen:
            p.is_default = False
        seen = seen or p.is_default
    return result


def manual_item(address: str, cfg: AdminConfig) -> VpnProfile:
    """Ručne zadaná adresa – Cisco nepoužije nastavenia profilu (protokol IPsec/EAP)."""
    address = address.strip()
    return VpnProfile(host_name=address, name=address, auth=cfg.default_auth,
                      address=address, group=cfg.Group, manual=True)
