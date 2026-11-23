# VPN Pripojenie pre Linux (Ubuntu, Fedora)

Grafické okno nad Cisco Secure Client (`/opt/cisco/secureclient/bin/vpn`), rovnaké správanie ako
Windows verzia: roletka pripojení, meno + heslo + 2FA kód, kroky pripájania, ikona v lište,
obnovovanie spojenia, preklad chýb Cisca, správa XML profilov a certifikátov.


## Inštalácia z balíka

Balíky sú univerzálne – ten istý súbor ide na x64 aj ARM. Hotové sú v záložke **Releases**
(alebo v **Actions → posledný beh → Artifacts**). Cisco Secure Client sa inštaluje zvlášť.

```bash
# Ubuntu 24.04 / 26.04 (PyQt6 sa doinštaluje z repozitára)
sudo apt install ./vpn-pripojenie_1.1.0_all.deb
# Ubuntu 22.04: to isté; PyQt6 sa pri inštalácii stiahne do /opt/vpn-pripojenie/venv
# Fedora
sudo dnf install ./vpn-pripojenie-1.1.0-1.noarch.rpm
```

Po inštalácii: **VPN Pripojenie** v ponuke aplikácií, po prihlásení sa spúšťa samo (ikona v lište,
`/etc/xdg/autostart/vpn-pripojenie.desktop`). Na Fedore s GNOME doinštalujte rozšírenie pre lištu:
`sudo dnf install gnome-shell-extension-appindicator` a zapnite ho v aplikácii Rozšírenia.

Odinštalovanie: `sudo apt remove vpn-pripojenie` / `sudo dnf remove vpn-pripojenie`
(nastavenia správcu v `/etc/vpn-pripojenie` ostávajú).

## Výroba balíkov

- **GitHub:** každý push na `main` spustí testy a vyrobí `.deb` aj `.rpm` (Actions → Artifacts).
  Nové vydanie: zvýšte `__version__` vo `vpn_pripojenie/__init__.py`, potom
  `git tag v1.0.1 && git push --tags` – balíky sa pripoja k Release.
- **Lokálne (Ubuntu, aj ARM v Parallels):** `sudo apt install rpm` (len pre .rpm) a
  `./packaging/build-packages.sh` → priečinok `dist/`.

## Spustenie bez inštalácie (na skúšku)

```bash
# Ubuntu 24.04 / 26.04
sudo apt install python3-pyqt6 openssl pkexec libnotify-bin libsecret-tools
# Fedora
sudo dnf install python3-pyqt6 openssl polkit libnotify libsecret

cd vpn-pripojenie
python3 -m vpn_pripojenie            # okno
python3 -m vpn_pripojenie --skryte   # len ikona v lište (štart po prihlásení)
python3 -m vpn_pripojenie --nastavenia
```

Ubuntu 22.04 nemá `python3-pyqt6`: `python3 -m venv ~/.venv-vpn && ~/.venv-vpn/bin/pip install PyQt6`
a spúšťať cez `~/.venv-vpn/bin/python -m vpn_pripojenie`.

Bez inštalácie sa akcie správcu (XML profil, CA pre všetkých, reštart služby, nastavenia pripojení)
spúšťajú cez `pkexec python3 helper/vpn-pripojenie-helper` – polkit ukáže všeobecné okno na heslo.
Po inštalácii (Krok 3) sa použije `/usr/libexec/vpn-pripojenie/vpn-pripojenie-helper` a pravidlo
`data/sk.vpnpripojenie.policy` s textom po slovensky.

## Kde čo je

| | |
|---|---|
| Nastavenia správcu | `/etc/vpn-pripojenie/config.json` (záložne `FiremnaVPN.ini` z Windows) |
| Stav používateľa | `~/.config/vpn-pripojenie/pouzivatel.json` (meno, posledné pripojenie, vzhľad – heslo nie) |
| Denník (heslá maskované) | `~/.local/state/vpn-pripojenie/cisco-vpn-log.txt` |
| XML profily | `/opt/cisco/secureclient/vpn/profile/` |
| CA certifikáty | `~/.cisco/certificates/ca/` (ja), `/opt/.cisco/certificates/ca/` (všetci) |
| Osobný certifikát | `~/.cisco/certificates/client/<meno>.pem` + `client/private/<meno>.key` |
| Log pomocného skriptu | `/var/log/vpn-pripojenie-helper.log` |

## Nastavenia správcu (config.json)

```json
{
  "NazovAplikacie": "VPN Pripojenie",
  "DefaultAuth": "MenoHesloKod",
  "Vzhlad": "Systemovy",
  "SkrytPoSekundach": 3,
  "PriOdpojeniOtvoritOkno": true,
  "AutoPrijatBanner": false,
  "PovolitKlucenku": false,
  "DniUpozorneniaCertifikat": 30,
  "Polozky": [
    {"Cisco": "Firma A", "Nazov": "Centrála", "Auth": "MenoHesloKod", "Predvolene": true},
    {"Cisco": "Firma B EAP+2FA", "Nazov": "Firma B", "Auth": "MenoHeslo"}
  ]
}
```

`Auth`: `MenoHesloKod | HesloKod | MenoHeslo | Heslo | Certifikat | DveHesla`.
`DniUpozorneniaCertifikat`: koľko dní pred vypršaním osobného certifikátu alebo CA aplikácia upozorní
(predvolene 30, `0` = neupozorňovať).
Netreba ho písať ručne – ukladá ho karta „Pripojenia (správca)“ v okne Profily a certifikáty.

## Čo okno hlási o profiloch a certifikátoch

- **Profily:** po inštalácii XML overí cez `vpn hosts`, či Cisco nové pripojenia naozaj načítal; ak nie,
  ponúkne reštart služby Cisca. Stĺpec Stav: v roletke / skryté správcom / Cisco ho zatiaľ nenačítal /
  rovnaký názov aj v inom súbore. Pred odstránením povie, ktoré pripojenia zmiznú a či ste cez ne práve pripojený.
- **Roletka pripojení:** bublina s profilom, serverom, protokolom a spôsobom prihlásenia. Po spustení
  hlásenie, ak od minula pribudlo alebo ubudlo pripojenie.
- **Certifikáty:** vydavateľ a či je jeho CA nainštalovaná, duplicitné súbory, osobné certifikáty vo Firefoxe
  (ak je `certutil`), po importe .p12 zhrnutie (komu, kto vydal, platnosť, kam sa uložil kľúč).
- **Vypršanie:** upozornenie v hlavnom okne a notifikácia (raz za spustenie).
- **Pripojenie certifikátom:** v okne aj v priebehu je vidieť, ktorý certifikát sa použije; bez platného
  certifikátu sa pripájanie nezačne a okno pošle na import. Pri nedôveryhodnom serveri tlačidlo „Importovať CA certifikát…“.

## Testy

```bash
python3 -m unittest discover -s tests -v
```

`test_core` skúša Cisco CLI proti simulácii (`tests/fake_vpn.py`), profily, nastavenia, certifikáty
(openssl) a pomocný skript. `test_gui_logic` prejde toky okna nad náhradou PyQt6 (`tests/qtstub`) –
overuje logiku, nie vzhľad; vzhľad treba pozrieť na skutočnom Ubuntu/Fedore.
