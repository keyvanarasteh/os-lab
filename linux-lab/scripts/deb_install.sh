#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Kullanim: $0 paket.deb"
    exit 1
fi

DEB_FILE="$1"

if [ ! -f "$DEB_FILE" ] || [[ "$DEB_FILE" != *.deb ]]; then
    echo "Hata: Gecerli bir .deb dosyasi belirtin"
    exit 1
fi

for tool in dpkg-deb apt-get dpkg-query mktemp realpath; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "Hata: Gerekli arac bulunamadi: $tool"
        exit 1
    fi
done

STAGING_DIR=$(mktemp -d)
trap 'rm -rf -- "$STAGING_DIR"' EXIT

install -m 600 -- "$DEB_FILE" "$STAGING_DIR/package.deb"
STAGED_FILE="$STAGING_DIR/package.deb"

if ! dpkg-deb --info "$STAGED_FILE" >/dev/null 2>&1; then
    echo "Hata: Gecersiz deb paketi"
    exit 1
fi

PACKAGE_NAME=$(dpkg-deb -f "$STAGED_FILE" Package)

echo "Kurulacak paket: $PACKAGE_NAME"
echo "Kurulum plani:"
sudo apt-get --simulate install "$STAGED_FILE"

read -r -p "Kurulumu onayliyor musunuz? [e/H]: " ANSWER
if [[ "$ANSWER" != "e" && "$ANSWER" != "E" ]]; then
    echo "Kurulum iptal edildi"
    exit 0
fi

sudo apt-get install "$STAGED_FILE"

if [ "$(dpkg-query -W -f='${Status}' "$PACKAGE_NAME" 2>/dev/null)" != "install ok installed" ]; then
    echo "Hata: Kurulum dogrulanamadi"
    exit 1
fi

echo "Paket kurulumu tamamlandi: $PACKAGE_NAME"
