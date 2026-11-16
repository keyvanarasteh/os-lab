#!/usr/bin/env bash
#
# Duman testinin paketlerini sisteme KURMADAN indirip bir klasöre açar. Sistemin apt
# listesine ve kurulu paketlerine dokunmaz, servis başlatmaz. Ubuntu 24.04 için yazılmıştır.
#
# Kullanım: sudo bash waf/paketleri-indir.sh /tmp/waf-paket
# Paketler <hedef>/kok altına açılır: sudo bash waf/duman-testi.sh /tmp/waf-paket/kok

set -euo pipefail
HEDEF="${1:?hedef klasör gerekli}"
rm -rf "$HEDEF"
mkdir -p "$HEDEF/deb/partial" "$HEDEF/kok" "$HEDEF/apt/lists/partial" "$HEDEF/apt/cache/archives/partial"
cat >"$HEDEF/apt/sources.list" <<EOF
deb http://archive.ubuntu.com/ubuntu noble main universe
deb http://archive.ubuntu.com/ubuntu noble-updates main universe
deb http://archive.ubuntu.com/ubuntu noble-security main universe
EOF
APT=(-o Dir::Etc::sourcelist="$HEDEF/apt/sources.list" -o Dir::Etc::sourceparts=/dev/null
	-o Dir::State::lists="$HEDEF/apt/lists" -o Dir::Cache="$HEDEF/apt/cache" -o Dir::Cache::archives="$HEDEF/deb"
	-o Debug::NoLocking=1)
apt-get "${APT[@]}" update >"$HEDEF/guncelle.log" 2>&1
apt-get "${APT[@]}" install -y --no-install-recommends --download-only \
	nginx libnginx-mod-http-modsecurity modsecurity-crs wrk >"$HEDEF/indir.log" 2>&1
for f in "$HEDEF"/deb/*.deb; do
	dpkg -x "$f" "$HEDEF/kok"
done
for p in nginx libmodsecurity3t64 libnginx-mod-http-modsecurity modsecurity-crs wrk; do
	f=$(ls "$HEDEF"/deb/"${p}"_*.deb 2>/dev/null | head -1)
	[[ -n $f ]] && printf '%s %s\n' "$p" "$(dpkg-deb -f "$f" Version)"
done
