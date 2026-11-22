#!/bin/sh
# Vyrobí balíky VPN Pripojenie:
#   dist/vpn-pripojenie_<verzia>_all.deb    – Ubuntu (x64 aj ARM)
#   dist/vpn-pripojenie-<verzia>-1.noarch.rpm – Fedora (x64 aj ARM), ak je k dispozícii rpmbuild
#
# Spustenie z koreňa repozitára:  ./packaging/build-packages.sh
# Potrebné: dpkg-deb (Ubuntu/Debian), voliteľne rpmbuild (Ubuntu: apt install rpm, Fedora: dnf install rpm-build)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PKG="$ROOT/packaging"
OUT="$ROOT/dist"
WORK="$ROOT/build"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/vpn_pripojenie/__init__.py")
[ -n "$VERSION" ] || { echo "Verzia sa nenašla vo vpn_pripojenie/__init__.py" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$OUT" "$WORK"
STAGE="$WORK/root"

# ---------- spoločný strom súborov
inst() {  # inst <práva> <zdroj> <cieľ v systéme>
    mkdir -p "$STAGE$(dirname "$3")"
    cp "$2" "$STAGE$3"
    chmod "$1" "$STAGE$3"
}
for f in "$ROOT"/vpn_pripojenie/*.py; do
    inst 0644 "$f" "/usr/share/vpn-pripojenie/vpn_pripojenie/$(basename "$f")"
done
inst 0755 "$PKG/vpn-pripojenie"                  /usr/bin/vpn-pripojenie
inst 0755 "$ROOT/helper/vpn-pripojenie-helper"   /usr/libexec/vpn-pripojenie/vpn-pripojenie-helper
inst 0644 "$ROOT/data/sk.vpnpripojenie.policy" /usr/share/polkit-1/actions/sk.vpnpripojenie.policy
inst 0644 "$PKG/vpn-pripojenie.desktop"          /usr/share/applications/vpn-pripojenie.desktop
inst 0644 "$PKG/vpn-pripojenie-autostart.desktop" /etc/xdg/autostart/vpn-pripojenie.desktop
inst 0644 "$PKG/vpn-pripojenie.svg"              /usr/share/icons/hicolor/scalable/apps/vpn-pripojenie.svg
inst 0644 "$ROOT/README.md"                      /usr/share/doc/vpn-pripojenie/README.md
inst 0644 "$PKG/config.example.json"             /usr/share/doc/vpn-pripojenie/config.example.json
find "$STAGE" -type d -exec chmod 0755 {} +

# skripty musia mať linuxové konce riadkov (pre istotu, ak sa repozitár upravoval vo Windows)
for f in "$STAGE/usr/bin/vpn-pripojenie" "$STAGE/usr/libexec/vpn-pripojenie/vpn-pripojenie-helper"; do
    sed -i 's/\r$//' "$f"
done

# ---------- .deb
DEB="$WORK/deb"
mkdir -p "$DEB"
cp -a "$STAGE/." "$DEB/"
mkdir -p "$DEB/DEBIAN"
SIZE=$(du -sk "$STAGE" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" "$PKG/deb/control.in" > "$DEB/DEBIAN/control"
for s in postinst postrm; do
    sed 's/\r$//' "$PKG/deb/$s" > "$DEB/DEBIAN/$s"
    chmod 0755 "$DEB/DEBIAN/$s"
done
cp "$PKG/deb/conffiles" "$DEB/DEBIAN/conffiles"
chmod 0644 "$DEB/DEBIAN/control" "$DEB/DEBIAN/conffiles"
DEBFILE="$OUT/vpn-pripojenie_${VERSION}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$DEB" "$DEBFILE" >/dev/null
echo "Hotovo: $DEBFILE"

# ---------- .rpm
if command -v rpmbuild >/dev/null 2>&1; then
    TOP="$WORK/rpmbuild"
    mkdir -p "$TOP/SPECS" "$TOP/RPMS" "$TOP/BUILD" "$TOP/BUILDROOT"
    sed -e "s/@VERSION@/$VERSION/" -e "s#@STAGE@#$STAGE#" "$PKG/rpm/vpn-pripojenie.spec.in" > "$TOP/SPECS/vpn-pripojenie.spec"
    rpmbuild -bb --quiet \
        --define "_topdir $TOP" \
        --define "dist %{nil}" \
        --define "__os_install_post %{nil}" \
        --define "debug_package %{nil}" \
        --define "_binary_payload w9.xzdio" \
        "$TOP/SPECS/vpn-pripojenie.spec"
    RPMFILE=$(find "$TOP/RPMS" -name '*.rpm' | head -n 1)
    cp "$RPMFILE" "$OUT/"
    echo "Hotovo: $OUT/$(basename "$RPMFILE")"
else
    echo "rpmbuild chýba – .rpm sa nevyrobil (Ubuntu: sudo apt install rpm)."
fi
