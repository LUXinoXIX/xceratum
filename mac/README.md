# Firemná VPN pre Mac (prototyp 0.1)

Vlastné okno nad Cisco Secure Client (`/opt/cisco/secureclient/bin/vpn`), rovnaké správanie ako Windows
a Linux verzia: roletka pripojení, meno + heslo + 2FA kód, kroky pripájania, ikona v lište, výpadok spojenia,
preklad chýb Cisca, nastavenia správcu a osobné certifikáty. Napísané v Swifte (SwiftUI), macOS 13 a novší,
Intel aj Apple čip.

## Čo je navyše oproti Windows

- **Heslo v Kľúčenke**, pred použitím Touch ID (alebo heslo Macu). Správca to môže vypnúť.
- **Výmena osobného certifikátu**: keď sa blíži koniec platnosti, okno, lišta aj Centrum hlásení upozornia.
  Používateľ klikne *Vymeniť certifikát…* (alebo pretiahne `.p12` do okna), zadá heslo k súboru a aplikácia
  certifikát vloží do prihlasovacej kľúčenky, povolí ho Ciscu a po úspechu zmaže starý.
- **Touch ID všade**: pri hesle k VPN z Kľúčenky aj pri odomknutí nastavení správcu (zámok namiesto UAC).
  Akcie správcu robí úzky pomocník `/Library/PrivilegedHelperTools/firemnavpn-helper` (uloženie nastavení,
  pridanie/odstránenie XML profilu, reštart služby Cisca); balík pridá pravidlo `/etc/sudoers.d/firemnavpn`,
  aby ho správcovia Macu mohli spustiť po overení Touch ID bez hesla. Používateľ, ktorý nie je správca,
  zadá meno a heslo správcu.

## Inštalácia (z GitHubu, bez kompilovania)

1. V záložke **Actions → Mac → posledný beh → Artifacts** stiahnite `firemna-vpn-mac`
   (pri vydaní `mac-v*` aj v **Releases**). Rozbaľte `FiremnaVPN-x.y.z.zip`.
2. Do priečinka `firma` vedľa `.pkg` dajte firemné súbory (pozri `firma/README.txt`):
   XML profily Cisca, certifikáty firemnej CA, prípadne `FiremnaVPN.ini`. **Tieto súbory nikdy nedávajte na GitHub.**
3. Otvorte `FiremnaVPN-x.y.z.pkg`. Balík zatiaľ nie je podpísaný Developer ID, takže macOS ho prvýkrát zablokuje:
   **Systémové nastavenia → Súkromie a bezpečnosť → Otvoriť aj tak**.
4. Inštalátor nainštaluje aplikáciu, profily a CA, odstaví automatické okno Cisca (VPN služba Cisca beží ďalej)
   a spustí Firemnú VPN. Ikona štítu je v lište hore.

Odinštalovanie: `sudo mac/packaging/odinstalovat.sh` (vráti pôvodné okno Cisca).

## Zostavenie na Macu (voliteľné)

```bash
xcode-select --install        # raz, nástroje Apple
cd mac
swift test                    # testy (simulácia Cisca: ../tests/fake_vpn.py)
./packaging/build.sh          # → dist/FiremnaVPN-x.y.z.pkg
```

## Kde čo je

| Čo | Kde |
|---|---|
| Aplikácia | `/Applications/FiremnaVPN.app` |
| Pomocník pre správcu | `/Library/PrivilegedHelperTools/firemnavpn-helper` + `/etc/sudoers.d/firemnavpn` |
| Spúšťanie po prihlásení | `/Library/LaunchAgents/org.xceratum.firemnavpn.plist` |
| Nastavenia správcu | `/Library/Application Support/FiremnaVPN/FiremnaVPN.ini` (rovnaký formát ako Windows) |
| Stav používateľa | `~/Library/Application Support/FiremnaVPN/pouzivatel.json` (bez hesla) |
| Heslo | Kľúčenka, položka „FiremnaVPN“ |
| Log Cisca | `~/Library/Logs/FiremnaVPN/cisco-vpn-log.txt` (heslá maskované) |
| Log inštalácie | `/Library/Logs/FiremnaVPN-instalacia.log` |

## Treba overiť na skutočnom Macu

- `launchctl disable gui/<uid>/com.cisco.secureclient.gui` na macOS 13–26 (okno Cisca je od macOS 13 v balíku aplikácie).
- Ktoré procesy Cisca potrebujú prístup ku kľúču certifikátu (`security import -T …`); či sa Kľúčenka ešte pýta.
- Presné výzvy `vpn -s` a label služby Cisca na danej verzii.
- Či Cisco načíta nový XML profil hneď, alebo až po reštarte služby (aplikácia ju reštartuje).

## Pravidlo pre repozitár

V kóde, testoch, príkladoch ani správach commitov nesmú byť skutočné mená ľudí, firiem ani serverov –
len všeobecné hodnoty (`firma.example`, `meno@firma.example`, Firma A). Pred každým pushom skontrolovať zmeny.
