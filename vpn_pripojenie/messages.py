"""Preklad známych hlášok Cisca do slovenčiny s radou, čo robiť (plán v6, kap. 2).

Pôvodný anglický text sa v okne zobrazí menším písmom pod prekladom.
"""
from __future__ import annotations

import re
from typing import Optional

# (regex na anglický text, slovenský text s radou)
KNOWN: list[tuple[str, str]] = [
    (r"establishment capability for a remote user is disabled|remote user.*disabled",
     "Pripojenie zo vzdialenej relácie (vzdialená plocha, SSH) je v profile Cisca zakázané. "
     "Pripojte sa priamo pri počítači alebo požiadajte správcu o povolenie v profile."),
    (r"connect capability is unavailable|another .*(application|client).*(acquired|running)",
     "Pripojenie si drží iná Cisco aplikácia. Zatvorte okno Cisco Secure Client a skúste znova."),
    (r"no valid certificates? available|certificate.*not found|unable to (find|locate).*certificate",
     "Nenašiel sa platný osobný certifikát. Importujte ho cez ponuku ≡ → Profily a certifikáty."),
    (r"untrusted (vpn )?server|certificate validation failure|server certificate.*(invalid|untrusted|not trusted)",
     "Server sa nedal overiť – chýba alebo nesedí certifikát certifikačnej autority (CA). "
     "Importujte firemný CA certifikát cez ponuku ≡ → Profily a certifikáty."),
    (r"unable to contact|could not connect to (the )?server|connection attempt has failed|host .*not reachable|name resolution",
     "Server sa nedá kontaktovať. Skontrolujte pripojenie na internet a skúste to o chvíľu znova."),
    (r"secure gateway has rejected|gateway.*rejected",
     "Server pripojenie odmietol. Skontrolujte, či máte na toto pripojenie oprávnenie, prípadne kontaktujte správcu."),
    (r"single sign-on|sso cookie|saml|external browser",
     "Toto pripojenie používa prihlásenie cez prehliadač (SAML/SSO), ktoré príkazový riadok Cisca nepodporuje. "
     "Použite pôvodné okno Cisco Secure Client."),
    (r"captive portal",
     "Sieť vyžaduje prihlásenie v prehliadači (napr. hotel, letisko). Otvorte prehliadač, prihláste sa do siete a skúste znova."),
    (r"(vpn )?agent .*(not (running|responding|available)|unavailable)|vpn service .*(unavailable|not available)|failed to connect to (the )?agent",
     "Služba Cisca (vpnagentd) nebeží. Spustite ju cez ponuku ≡ → Profily a certifikáty → Diagnostika, "
     "alebo reštartujte počítač."),
    (r"session (has )?expired|session timeout",
     "Relácia na serveri vypršala. Prihláste sa znova."),
    (r"login (failed|denied)|authentication failed|access denied",
     "Prihlásenie zlyhalo. Skontrolujte prihlasovacie údaje."),
    (r"no (valid )?profile|host .*not (found|in profile)|invalid host",
     "Pripojenie sa v profiloch Cisca nenašlo. Skontrolujte XML profily (≡ → Profily a certifikáty)."),
]


def translate(english: str) -> Optional[str]:
    """Slovenský text pre známu hlášku Cisca, inak None."""
    low = (english or "").lower()
    for pattern, sk in KNOWN:
        if re.search(pattern, low):
            return sk
    return None


def friendly(english: str, fallback_prefix: str = "Pripojenie sa nepodarilo.") -> tuple[str, str]:
    """(slovenský text, pôvodný anglický text)."""
    english = (english or "").strip()
    sk = translate(english)
    if sk:
        return sk, english
    return fallback_prefix, english
