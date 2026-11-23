#!/bin/bash
# Zostaví FiremnaVPN.app (x64 + Apple čip) a inštalačný balík .pkg do mac/dist/.
# Potrebné: macOS 13+ a nástroje Apple (xcode-select --install) alebo Xcode.
set -euo pipefail
cd "$(dirname "$0")/.."
VERZIA="${VERZIA:-$(cat VERSION)}"
BUILD="${GITHUB_RUN_NUMBER:-1}"
OUT=dist
APP="$OUT/root/Applications/FiremnaVPN.app"

rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$OUT/root/Library/LaunchAgents" "$OUT/root/Library/PrivilegedHelperTools"

echo "== Zostavujem (arm64 + x86_64)"
if swift build -c release --arch arm64 --arch x86_64; then
  BIN=".build/apple/Products/Release/FiremnaVPN"
else
  echo "Univerzálne zostavenie zlyhalo, skúšam len pre tento Mac"
  swift build -c release
  BIN=".build/release/FiremnaVPN"
fi
cp "$BIN" "$APP/Contents/MacOS/FiremnaVPN"
sed -e "s/__VERZIA__/$VERZIA/" -e "s/__BUILD__/$BUILD/" packaging/Info.plist > "$APP/Contents/Info.plist"
cp packaging/org.xceratum.firemnavpn.plist "$OUT/root/Library/LaunchAgents/"
install -m 755 packaging/firemnavpn-helper "$OUT/root/Library/PrivilegedHelperTools/firemnavpn-helper"
lipo -info "$APP/Contents/MacOS/FiremnaVPN" || true

echo "== Podpis (ad-hoc; Developer ID + notarizácia neskôr)"
codesign --force --sign - --timestamp=none "$APP"

echo "== Balík .pkg"
chmod 755 packaging/scripts/*
pkgbuild --root "$OUT/root" --scripts packaging/scripts \
  --identifier org.xceratum.firemnavpn.pkg --version "$VERZIA" \
  --install-location / "$OUT/FiremnaVPN-$VERZIA.pkg"

echo "== Priečinok pre firemné súbory (vedľa .pkg)"
mkdir -p "$OUT/firma/profily" "$OUT/firma/ca"
cp firma-priklad/README.txt "$OUT/firma/README.txt"
( cd "$OUT" && ditto -c -k --keepParent root/Applications/FiremnaVPN.app "FiremnaVPN-$VERZIA-app.zip" )
( cd "$OUT" && zip -qr "FiremnaVPN-$VERZIA.zip" "FiremnaVPN-$VERZIA.pkg" firma )
ls -la "$OUT"
