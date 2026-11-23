"""Texty, ktorými okno správy oznamuje, čo sa s profilmi a certifikátmi deje (bez Qt, dá sa testovať)."""
from __future__ import annotations

from pathlib import Path

from . import certs
from .profiles import parse_profile


def names_of(pf) -> str:
    return ", ".join(h.host_name for h in pf.hosts) or "žiadne"


def removal_question(path: Path, main) -> str:
    """Otázka pred odstránením profilu – povie, čo všetko sa tým zmení."""
    pf = parse_profile(path)
    hosts = {h.host_name.lower(): h.host_name for h in pf.hosts}
    lines = [f"Odstrániť profil {path.name}?"]
    if hosts:
        lines.append("Z roletky zmiznú pripojenia: " + ", ".join(hosts.values()) + ".")
    sel = getattr(main, "selected", None)
    if getattr(main, "connected", False) and sel and sel.host_name.lower() in hosts:
        lines.append(f"Práve ste pripojený cez {sel.name}. VPN ostane pripojená, ale po odpojení "
                     "sa k nej už nepripojíte.")
    cfg_items = [i for i in main.cfg.Polozky if i.Cisco.lower() in hosts]
    if cfg_items:
        names = ", ".join((i.Nazov or i.Cisco) + (" – predvolené" if i.Predvolene else "") for i in cfg_items)
        lines.append(f"V nastaveniach správcu sú na tento profil naviazané: {names}. "
                     "Ostanú tam, ale budú označené ako chýbajúce.")
    lines.append("Pôvodný súbor sa uloží do zálohy (backup).")
    return "\n\n".join(lines)


def import_summary(info, path: Path, n_ca: int, cas: list, days: int) -> str:
    """Čo sa pri importe .p12 stalo – zobrazí sa v dialógu po importe."""
    key = certs.private_dir() / (path.stem + ".key")
    lines = [
        f"Komu je vydaný: {info.cn}",
        f"Vydal: {info.issuer_cn or '?'}",
        f"Platný: {info.valid_from} – {certs.describe_expiry(info, days)}",
        f"Certifikát: {path}",
        f"Súkromný kľúč: {key} (čitateľný len pre vás)",
        f"CA z balíka: {n_ca}" if n_ca else "CA z balíka: žiadna",
    ]
    if info.issuer and info.issuer != info.subject and not certs.issuer_installed(info, cas):
        lines.append("")
        lines.append(f"Pozor: CA „{info.issuer_cn}“, ktorá certifikát vydala, nie je nainštalovaná. "
                     "Ak ju server vyžaduje, importujte ju vyššie v časti Certifikačné autority.")
    lines.append("")
    lines.append("Cisco tento certifikát použije pri pripojeniach s prihlásením certifikátom.")
    return "\n".join(lines)
