import Foundation

/// Preklad známych hlášok Cisca do slovenčiny s radou, čo robiť.
/// Rovnaká tabuľka ako vo Windows a Linux verzii (`vpn_pripojenie/messages.py`).
public enum Messages {
    static let known: [(String, String)] = [
        (#"establishment capability for a remote user is disabled|remote user.*disabled"#,
         "Pripojenie zo vzdialenej relácie (vzdialená plocha, SSH) je v profile Cisca zakázané. Pripojte sa priamo pri počítači alebo požiadajte správcu o povolenie v profile."),
        (#"connect capability is unavailable|another .*(application|client).*(acquired|running)"#,
         "Pripojenie si drží iná Cisco aplikácia. Zatvorte okno Cisco Secure Client a skúste znova."),
        (#"no valid certificates? available|certificate.*not found|unable to (find|locate).*certificate"#,
         "Nenašiel sa platný osobný certifikát. Importujte ho v okne Certifikáty (ikona v lište → Certifikáty…)."),
        (#"untrusted (vpn )?server|certificate validation failure|server certificate.*(invalid|untrusted|not trusted)"#,
         "Server sa nedal overiť – chýba alebo nesedí certifikát certifikačnej autority (CA). Požiadajte správcu o inštalačný balík s firemnou CA."),
        (#"unable to contact|could not connect to (the )?server|connection attempt has failed|host .*not reachable|name resolution"#,
         "Server sa nedá kontaktovať. Skontrolujte pripojenie na internet a skúste to o chvíľu znova."),
        (#"secure gateway has rejected|gateway.*rejected"#,
         "Server pripojenie odmietol. Skontrolujte, či máte na toto pripojenie oprávnenie, prípadne kontaktujte správcu."),
        (#"single sign-on|sso cookie|saml|external browser"#,
         "Toto pripojenie používa prihlásenie cez prehliadač (SAML/SSO), ktoré príkazový riadok Cisca nepodporuje. Použite pôvodné okno Cisco Secure Client."),
        (#"captive portal"#,
         "Sieť vyžaduje prihlásenie v prehliadači (napr. hotel, letisko). Otvorte prehliadač, prihláste sa do siete a skúste znova."),
        (#"(vpn )?agent .*(not (running|responding|available)|unavailable)|vpn service .*(unavailable|not available)|failed to connect to (the )?agent"#,
         "Služba Cisca nebeží. Reštartujte ju v Nastaveniach (Profily → Reštartovať službu Cisca) alebo reštartujte Mac."),
        (#"session (has )?expired|session timeout"#,
         "Relácia na serveri vypršala. Prihláste sa znova."),
        (#"login (failed|denied)|authentication failed|access denied"#,
         "Prihlásenie zlyhalo. Skontrolujte prihlasovacie údaje."),
        (#"no (valid )?profile|host .*not (found|in profile)|invalid host"#,
         "Pripojenie sa v profiloch Cisca nenašlo. Skontrolujte XML profily v Nastaveniach (Profily)."),
    ]

    /// Slovenský text pre známu hlášku Cisca, inak nil.
    public static func translate(_ english: String) -> String? {
        let low = english.lowercased()
        for (pattern, sk) in known where low.range(of: pattern, options: .regularExpression) != nil {
            return sk
        }
        return nil
    }

    /// (slovenský text, pôvodný anglický text)
    public static func friendly(_ english: String, fallback: String = "Pripojenie sa nepodarilo.") -> (String, String) {
        let e = english.trimmingCharacters(in: .whitespacesAndNewlines)
        return (translate(e) ?? fallback, e)
    }
}
