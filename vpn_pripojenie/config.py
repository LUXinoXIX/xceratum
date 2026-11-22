"""Nastavenia aplikácie.

Dve úrovne, ako vo Windows verzii:
* nastavenia správcu – /etc/vpn-pripojenie/config.json (zapisuje ich len pomocný skript cez polkit);
  záložne /etc/vpn-pripojenie/FiremnaVPN.ini v rovnakom formáte ako vo Windows, aby sa dal zdieľať;
* stav používateľa – ~/.config/vpn-pripojenie/pouzivatel.json (zapamätané meno, posledné pripojenie,
  vzhľad, pripojenia, ktoré si pýtajú meno). Heslo sa sem nikdy neukladá.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

from . import APP_ID


class AuthMode(str, Enum):
    MENO_HESLO_KOD = "MenoHesloKod"
    HESLO_KOD = "HesloKod"
    MENO_HESLO = "MenoHeslo"
    HESLO = "Heslo"
    CERTIFIKAT = "Certifikat"
    DVE_HESLA = "DveHesla"

    @classmethod
    def parse(cls, value) -> Optional["AuthMode"]:
        v = str(value or "").strip().lower().replace("á", "a")
        for m in cls:
            if m.value.lower() == v:
                return m
        return None

    @property
    def label(self) -> str:
        return {
            AuthMode.MENO_HESLO_KOD: "meno, heslo a kód",
            AuthMode.HESLO_KOD: "heslo a kód",
            AuthMode.MENO_HESLO: "meno a heslo",
            AuthMode.HESLO: "len heslo",
            AuthMode.CERTIFIKAT: "osobný certifikát",
            AuthMode.DVE_HESLA: "meno a dve heslá",
        }[self]


# ------------------------------------------------------------------ cesty

def etc_dir() -> Path:
    return Path(os.environ.get("VPN_PRIPOJENIE_ETC", "/etc/" + APP_ID))


def admin_config_path() -> Path:
    return etc_dir() / "config.json"


def admin_ini_path() -> Path:
    return etc_dir() / "FiremnaVPN.ini"


def user_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_ID


def user_state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / APP_ID


def log_path() -> Path:
    return user_state_dir() / "cisco-vpn-log.txt"


# ------------------------------------------------------------------ nastavenia správcu

@dataclass
class ItemSettings:
    """Jedna položka v roletke – odkazuje na pripojenie (HostName) z Cisca."""
    Cisco: str = ""
    Nazov: str = ""
    Auth: str = ""          # prázdne = odhad z XML / DefaultAuth
    Meno: str = ""
    Group: str = ""
    Skryt: bool = False
    Predvolene: bool = False

    @property
    def auth_mode(self) -> Optional[AuthMode]:
        return AuthMode.parse(self.Auth)


@dataclass
class AdminConfig:
    NazovAplikacie: str = "VPN Pripojenie"
    DefaultAuth: str = AuthMode.MENO_HESLO_KOD.value
    Group: str = ""
    VpnCliPath: str = ""                 # prázdne = nájsť automaticky
    ConnectTimeoutSeconds: int = 90
    Vzhlad: str = "Systemovy"            # Svetly | Tmavy | Systemovy
    SkrytPoSekundach: int = 3            # 0 = hneď, -1 = neskrývať
    PriOdpojeniOtvoritOkno: bool = True
    AutoPrijatBanner: bool = False       # správu servera potvrdiť automaticky („y“)
    PovolitKlucenku: bool = False        # dovoliť uložiť heslo v kľúčenke systému
    PouzitPty: bool = True               # výstup Cisco CLI cez pseudoterminál (bez bufferovania)
    Polozky: list = field(default_factory=list)   # list[ItemSettings]
    loaded_from: str = ""                # informačne, neukladá sa

    @property
    def default_auth(self) -> AuthMode:
        return AuthMode.parse(self.DefaultAuth) or AuthMode.MENO_HESLO_KOD

    # ---------- načítanie

    @classmethod
    def load(cls) -> "AdminConfig":
        for path, loader in ((admin_config_path(), cls._from_json), (admin_ini_path(), cls._from_ini)):
            try:
                if path.is_file():
                    cfg = loader(path.read_text(encoding="utf-8-sig"))
                    cfg.loaded_from = str(path)
                    return cfg
            except (OSError, ValueError):
                continue
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "AdminConfig":
        cfg = cls()
        if not isinstance(data, dict):
            raise ValueError("nastavenia musia byť objekt JSON")
        for key, default in asdict(cls()).items():
            if key in ("Polozky", "loaded_from") or key not in data:
                continue
            val = data[key]
            if isinstance(default, bool):
                val = _yes(val)
            elif isinstance(default, int):
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    continue
            else:
                val = str(val)
            setattr(cfg, key, val)
        cfg.ConnectTimeoutSeconds = max(10, cfg.ConnectTimeoutSeconds)
        cfg.SkrytPoSekundach = max(-1, min(60, cfg.SkrytPoSekundach))
        items = []
        for raw in data.get("Polozky") or []:
            if not isinstance(raw, dict):
                continue
            it = ItemSettings(
                Cisco=_unquote(raw.get("Cisco", "")),
                Nazov=str(raw.get("Nazov", "") or ""),
                Auth=str(raw.get("Auth", "") or ""),
                Meno=str(raw.get("Meno", "") or ""),
                Group=str(raw.get("Group", "") or ""),
                Skryt=_yes(raw.get("Skryt", False)),
                Predvolene=_yes(raw.get("Predvolene", False)),
            )
            if it.Cisco:
                items.append(it)
        cfg.Polozky = items
        return cfg

    @classmethod
    def _from_json(cls, text: str) -> "AdminConfig":
        return cls.from_dict(json.loads(text))

    _LEGACY = re.compile(r"^\[?\s*pripojenie\s*:\s*(.+?)\s*\]?$", re.I)

    @classmethod
    def _from_ini(cls, text: str) -> "AdminConfig":
        """FiremnaVPN.ini z Windows verzie ([Polozka N], [Vseobecne], starý [Pripojenie:XY])."""
        general: dict = {}
        items: list[dict] = []
        cur: Optional[dict] = None
        keymap = {
            "nazovaplikacie": "NazovAplikacie", "defaultauth": "DefaultAuth", "group": "Group",
            "vpnclipath": "VpnCliPath", "connecttimeoutseconds": "ConnectTimeoutSeconds",
            "vzhlad": "Vzhlad", "skrytposekundach": "SkrytPoSekundach",
            "priodpojeniotvoritokno": "PriOdpojeniOtvoritOkno", "autoprijatbanner": "AutoPrijatBanner",
            "povolitklucenku": "PovolitKlucenku", "pouzitpty": "PouzitPty",
        }
        itemmap = {"cisco": "Cisco", "nazov": "Nazov", "auth": "Auth", "meno": "Meno",
                   "group": "Group", "skryt": "Skryt", "predvolene": "Predvolene"}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line[0] in ";#":
                continue
            eq = line.find("=")
            m = cls._LEGACY.match(line) if eq < 0 else None
            if m:
                cur = {"Cisco": m.group(1)}
                items.append(cur)
                continue
            if line.startswith("["):
                name = _fold(line.strip("[] "))
                if name in ("vseobecne", "general"):
                    cur = None
                else:
                    cur = {}
                    items.append(cur)
                continue
            if eq <= 0:
                continue
            key = _fold(line[:eq])
            val = line[eq + 1:].strip()
            sc = val.find(" ;")
            if sc >= 0:
                val = val[:sc].strip()
            if cur is not None:
                if key in itemmap:
                    cur[itemmap[key]] = val
            elif key in keymap:
                general[keymap[key]] = val
            elif key in ("defaultconnection", "server"):
                general["_default"] = _unquote(val)
        cfg = cls.from_dict({**general, "Polozky": items})
        dflt = general.get("_default")
        if dflt:
            for it in cfg.Polozky:
                if it.Cisco.lower() == dflt.lower() and not any(i.Predvolene for i in cfg.Polozky):
                    it.Predvolene = True
        return cfg

    # ---------- uloženie (zapisuje pomocný skript, tu len obsah)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("loaded_from", None)
        d["Polozky"] = [asdict(i) if isinstance(i, ItemSettings) else i for i in self.Polozky]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


# ------------------------------------------------------------------ stav používateľa

@dataclass
class UserState:
    Zapamatat: bool = True
    Meno: str = ""
    PoslednaPolozka: str = ""     # kľúč položky (HostName|Názov)
    PosledneCisco: str = ""
    Vzhlad: str = ""              # prázdne = podľa správcu
    PytaMeno: list = field(default_factory=list)   # HostName pripojení, ktoré si pýtajú meno (naučené)
    UlozitHeslo: bool = False     # heslo v kľúčenke (len ak to správca povolí)
    SystemovyRam: bool = False    # okno so systémovým rámom namiesto vlastnej hlavičky

    @staticmethod
    def path() -> Path:
        return user_config_dir() / "pouzivatel.json"

    @classmethod
    def load(cls) -> "UserState":
        st = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return st
        if not isinstance(data, dict):
            return st
        for key, default in asdict(cls()).items():
            if key not in data:
                continue
            val = data[key]
            if isinstance(default, bool):
                val = _yes(val)
            elif isinstance(default, list):
                val = [str(x) for x in val] if isinstance(val, list) else []
            else:
                val = str(val)
            setattr(st, key, val)
        return st

    def save(self) -> None:
        p = self.path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(tmp, 0o600)
            tmp.replace(p)
        except OSError:
            pass

    def needs_user(self, host: str) -> bool:
        return host.lower() in (h.lower() for h in self.PytaMeno)

    def learn_needs_user(self, host: str) -> None:
        if not self.needs_user(host):
            self.PytaMeno.append(host)
            self.save()


# ------------------------------------------------------------------ pomôcky

def _yes(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "ano", "áno", "yes", "y")


def _fold(s: str) -> str:
    table = str.maketrans("áäčďéíĺľňóôŕšťúýž", "aacdeillnoorstuyz")
    return s.strip().lower().translate(table).replace(" ", "")


def _unquote(s) -> str:
    s = str(s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1].strip()
    return s
