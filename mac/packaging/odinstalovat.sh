#!/bin/bash
# Odinštalovanie Firemnej VPN: sudo ./odinstalovat.sh
# Vráti pôvodné okno Cisca. XML profily, CA a Cisco Secure Client ostávajú.
set -u
[ "$(id -u)" = 0 ] || { echo "Spustite so sudo."; exit 1; }
USER_NOW=$(stat -f %Su /dev/console)
UID_NOW=$(id -u "$USER_NOW")
launchctl bootout "gui/$UID_NOW/org.xceratum.firemnavpn" 2>/dev/null
for l in com.cisco.secureclient.gui com.cisco.anyconnect.gui; do launchctl enable "gui/$UID_NOW/$l"; done
pkill -x FiremnaVPN 2>/dev/null
rm -f /Library/LaunchAgents/org.xceratum.firemnavpn.plist
rm -rf /Applications/FiremnaVPN.app
pkgutil --forget org.xceratum.firemnavpn.pkg 2>/dev/null
echo "Hotovo. Nastavenia správcu ostali v /Library/Application Support/FiremnaVPN (zmažte ručne, ak treba)."
