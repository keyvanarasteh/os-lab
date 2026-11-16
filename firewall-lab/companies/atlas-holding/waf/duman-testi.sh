#!/usr/bin/env bash
#
# WAF duman testi. KABUL TESTİ DEĞİLDİR: tek makinede, istemci ve sunucu aynı işlemciyi
# paylaşarak çalışır. Talimatların çalıştığını ve ModSecurity + CRS'in örnek saldırıları
# durdurduğunu gösterir, 3 Gbps hedefi hakkında kanıt üretmez.
#
# Üç ağ isim alanı kullanır: istemci -> WAF -> uygulama. Gerçek ağa bağlantı yoktur.
#
# Kullanım: sudo bash waf/duman-testi.sh [paket_kökü]
#   paket_kökü: paketler sisteme kurulu değilse açıldıkları klasör (README'ye bakın).

set -uo pipefail
export LC_ALL=C.UTF-8

WAF_DIZINI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KOK="${1:-}"
CALISMA=/run/waf-duman
ON_EK=wafd-
RAPOR="$WAF_DIZINI/sonuclar/DUMAN.md"
SURE=20
BAGLANTI=200
WAF_CPU=0-3
ISTEMCI_CPU=4-7
UYG_CPU=8-9

hata() { printf 'HATA: %s\n' "$*" >&2; exit 2; }
ns() { local ad=$1; shift; ip netns exec "$ON_EK$ad" "$@"; }

[[ $EUID -eq 0 ]] || hata "root gerekir."
NGINX="$KOK/usr/sbin/nginx"
WRK="$KOK/usr/bin/wrk"
MODUL="$KOK/usr/lib/nginx/modules/ngx_http_modsecurity_module.so"
CRS_KURAL="$KOK/usr/share/modsecurity-crs/rules"
CRS_AYAR="$KOK/etc/modsecurity/crs/crs-setup.conf"
for f in "$NGINX" "$WRK" "$MODUL" "$CRS_AYAR"; do
	[[ -e $f ]] || hata "$f bulunamadı. README'deki paket adımına bakın."
done
[[ -d $CRS_KURAL ]] || hata "$CRS_KURAL bulunamadı."
for arac in openssl curl taskset; do
	command -v "$arac" >/dev/null || hata "$arac bulunamadı."
done
if [[ -n $KOK ]]; then
	export LD_LIBRARY_PATH="$KOK/usr/lib/x86_64-linux-gnu:$KOK/lib/x86_64-linux-gnu"
fi

temizle() {
	local ad pid
	for ad in $(ip netns list | awk '{print $1}' | grep "^$ON_EK"); do
		for pid in $(ip netns pids "$ad"); do kill "$pid" 2>/dev/null; done
		ip netns del "$ad"
	done
	rm -rf "$CALISMA"
}
trap temizle EXIT
temizle
mkdir -p "$CALISMA"/{gecici,log} "$WAF_DIZINI/sonuclar"

# --- Ağ ----------------------------------------------------------------------
for ad in istemci waf uyg; do
	ip netns add "$ON_EK$ad" || hata "isim alanı açılamadı"
	ns "$ad" ip link set lo up
done
ip link add e-waf netns "${ON_EK}istemci" type veth peer name e-ist netns "${ON_EK}waf"
ip link add e-uyg netns "${ON_EK}waf" type veth peer name e-waf netns "${ON_EK}uyg"
ns istemci ip addr add 10.99.1.1/24 dev e-waf
ns istemci ip link set e-waf up
ns waf ip addr add 10.99.1.2/24 dev e-ist
ns waf ip link set e-ist up
ns waf ip addr add 10.99.2.1/24 dev e-uyg
ns waf ip link set e-uyg up
ns uyg ip addr add 10.99.2.2/24 dev e-waf
ns uyg ip link set e-waf up

# --- Dosyalar ----------------------------------------------------------------
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 2 \
	-subj "/CN=lms.atlas.example" -keyout "$CALISMA/anahtar.pem" -out "$CALISMA/sertifika.pem" >/dev/null 2>&1 \
	|| hata "sertifika üretilemedi"
head -c 1024 /dev/zero | tr '\0' 'a' >"$CALISMA/kucuk.bin"
head -c 51200 /dev/zero | tr '\0' 'a' >"$CALISMA/buyuk.bin"

cat >"$CALISMA/modsec.conf" <<EOF
SecRuleEngine On
SecRequestBodyAccess On
SecRequestBodyLimit 13107200
SecRequestBodyNoFilesLimit 131072
SecResponseBodyAccess Off
SecAuditEngine Off
SecTmpDir $CALISMA/gecici
SecDataDir $CALISMA/gecici
Include $CRS_AYAR
Include $CRS_KURAL/*.conf
EOF

waf_conf() { # dosya motor(on|off)
	sed -e "s|@MODUL@|$MODUL|" -e "s|@CALISMA@|$CALISMA|g" -e "s|@MOTOR@|$2|" \
		"$WAF_DIZINI/nginx-waf.conf" >"$1"
}
waf_conf "$CALISMA/waf-acik.conf" on
waf_conf "$CALISMA/waf-kapali.conf" off

cat >"$CALISMA/uyg.conf" <<EOF
user root;
worker_processes 2;
pid $CALISMA/uyg.pid;
error_log $CALISMA/log/uyg-hata.log crit;
events { worker_connections 20000; }
http {
	access_log off;
	client_body_temp_path $CALISMA/gecici/uyg-govde;
	proxy_temp_path $CALISMA/gecici/uyg-proxy;
	fastcgi_temp_path $CALISMA/gecici/uyg-f;
	uwsgi_temp_path $CALISMA/gecici/uyg-u;
	scgi_temp_path $CALISMA/gecici/uyg-s;
	server {
		listen 8080 reuseport;
		location = /kucuk { alias $CALISMA/kucuk.bin; default_type text/plain; }
		location = /buyuk { alias $CALISMA/buyuk.bin; default_type text/plain; }
		location / { default_type text/plain; return 200 "tamam\n"; }
	}
}
EOF

waf_baslat() { # dosya
	ns waf taskset -c "$WAF_CPU" "$NGINX" -e "$CALISMA/log/waf-hata.log" -c "$1" || hata "WAF başlatılamadı: $(tail -2 "$CALISMA/log/waf-hata.log")"
	sleep 2
}
waf_durdur() {
	[[ -f $CALISMA/waf.pid ]] && kill "$(cat "$CALISMA/waf.pid")" 2>/dev/null
	sleep 1
}
ns uyg taskset -c "$UYG_CPU" "$NGINX" -e "$CALISMA/log/uyg-hata.log" -c "$CALISMA/uyg.conf" || hata "uygulama başlatılamadı"

# --- 1. İşlev: meşru istek geçer, saldırı durur ------------------------------
waf_baslat "$CALISMA/waf-acik.conf"
ISLEV="$CALISMA/islev.txt"
: >"$ISLEV"
ISLEV_TOPLAM=0
ISLEV_GECEN=0
istek() { # ad beklenen curl_arg...
	local ad=$1 beklenen=$2 kod
	shift 2
	kod=$(ns istemci curl -sk -o /dev/null -w '%{http_code}' --max-time 5 --resolve lms.atlas.example:443:10.99.1.2 "$@")
	ISLEV_TOPLAM=$((ISLEV_TOPLAM + 1))
	local durum=Kaldı
	if [[ $kod == "$beklenen" ]]; then
		durum=Geçti
		ISLEV_GECEN=$((ISLEV_GECEN + 1))
	fi
	printf '%s|%s|%s|%s\n' "$ad" "$beklenen" "$kod" "$durum" >>"$ISLEV"
	printf 'İşlev: %-46s beklenen=%s gerçek=%s %s\n' "$ad" "$beklenen" "$kod" "$durum"
}
A=https://lms.atlas.example
istek "Meşru: ana sayfa" 200 "$A/"
istek "Meşru: parametreli sayfa" 200 "$A/ders?id=42&bolum=3"
istek "Meşru: sınav cevabı POST" 200 -X POST -d 'soru=12&cevap=B' "$A/sinav/cevap"
istek "Meşru: Türkçe metin POST" 200 -X POST --data-urlencode 'yorum=Bugünkü ders çok güzeldi' "$A/forum/yaz"
istek "SQL enjeksiyonu" 403 -G --data-urlencode "id=1' OR '1'='1" "$A/ders"
istek "SQL enjeksiyonu: UNION" 403 -G --data-urlencode "id=1 UNION SELECT parola FROM kullanici" "$A/ders"
istek "XSS" 403 -G --data-urlencode "q=<script>alert(1)</script>" "$A/ara"
istek "Dizin geçişi" 403 -G --data-urlencode "dosya=../../../../etc/passwd" "$A/indir"
istek "Komut enjeksiyonu" 403 -G --data-urlencode "ad=;cat /etc/passwd" "$A/profil"
istek "POST gövdesinde SQL enjeksiyonu" 403 -X POST --data-urlencode "kullanici=admin' OR 1=1 -- " "$A/giris"
waf_durdur

# --- 2. Yük: WAF açık ve kapalı ----------------------------------------------
YUK="$CALISMA/yuk.txt"
: >"$YUK"
cpu_toplam() { # WAF süreçlerinin kullandığı işlemci tiki
	local t=0 p
	for p in $(ip netns pids "${ON_EK}waf"); do
		[[ -r /proc/$p/stat ]] && t=$((t + $(awk '{print $14 + $15}' "/proc/$p/stat")))
	done
	echo "$t"
}
rss_toplam() { # WAF süreçlerinin kB cinsinden belleği
	local t=0 p r
	for p in $(ip netns pids "${ON_EK}waf"); do
		r=$(awk '/^VmRSS/ {print $2}' "/proc/$p/status" 2>/dev/null)
		t=$((t + ${r:-0}))
	done
	echo "$t"
}
kosu() { # ad yol [ek_wrk_arg...]
	local ad=$1 yol=$2
	shift 2
	local c1 c2 cikti rps gecikme50 gecikme99 hata_kod hata_soket bant cpu rss
	c1=$(cpu_toplam)
	cikti=$(ns istemci taskset -c "$ISTEMCI_CPU" "$WRK" -t4 -c"$BAGLANTI" -d"${SURE}s" --latency "$@" "https://10.99.1.2$yol" 2>&1)
	c2=$(cpu_toplam)
	rss=$(rss_toplam)
	rps=$(awk '/Requests\/sec/ {print $2}' <<<"$cikti")
	bant=$(awk '/Transfer\/sec/ {print $2}' <<<"$cikti")
	gecikme50=$(awk '$1 == "50%" {print $2}' <<<"$cikti")
	gecikme99=$(awk '$1 == "99%" {print $2}' <<<"$cikti")
	hata_kod=$(awk '/Non-2xx/ {print $NF}' <<<"$cikti")
	hata_soket=$(awk '/Socket errors/ {print}' <<<"$cikti" | sed 's/^ *//')
	cpu=$(awk -v a="$c1" -v b="$c2" -v s="$SURE" 'BEGIN { printf "%.0f", (b - a) / 100 / s / 4 * 100 }')
	printf '%s|%s|%s|%s|%s|%s|%s|%s|%s\n' "$ad" "${rps:-?}" "${bant:-?}" "${gecikme50:-?}" "${gecikme99:-?}" "${hata_kod:-0}" "${hata_soket:-yok}" "$cpu" "$((rss / 1024))" >>"$YUK"
	printf 'Yük: %-34s %s istek/sn, %s, p50=%s p99=%s, non-2xx=%s, cpu=%%%s, bellek=%s MB\n' \
		"$ad" "${rps:-?}" "${bant:-?}" "${gecikme50:-?}" "${gecikme99:-?}" "${hata_kod:-0}" "$cpu" "$((rss / 1024))"
}
for motor in acik kapali; do
	etiket="WAF açık"
	[[ $motor == kapali ]] && etiket="WAF kapalı"
	waf_baslat "$CALISMA/waf-$motor.conf"
	kosu "$etiket, 1 KB yanıt" /kucuk
	kosu "$etiket, 50 KB yanıt" /buyuk
	kosu "$etiket, parametreli 1 KB" "/kucuk?id=42&bolum=3&ad=ogrenci"
	kosu "$etiket, her istekte yeni TLS" /kucuk -H "Connection: close"
	waf_durdur
done

# --- Rapor -------------------------------------------------------------------
surum_nginx=$("$NGINX" -v 2>&1 | sed 's/.*: //')
cpu_ad=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | sed 's/^ *//')
{
	printf '# WAF duman testi sonuçları\n\n'
	printf 'Bu dosyayı `waf/duman-testi.sh` üretir, elle düzenlenmez.\n\n'
	printf '> **Bu bir kabul testi değildir.** İstemci, WAF ve uygulama tek makinede aynı işlemciyi paylaşır, trafik sanal arayüzlerden geçer. Sonuçlar 3 Gbps hedefi veya hedef sunucu hakkında bir şey söylemez. Kabul testi [waf/README.md](../README.md) dosyasındadır ve **çalıştırılmadı**.\n\n'
	printf '| Ortam | Değer |\n|---|---|\n'
	printf '| Tarih | %s |\n| Ağ | Linux ağ isim alanları, gerçek ağa bağlantı yok |\n| İşlemci | %s, WAF için 4 çekirdek ayrıldı |\n' "$(date '+%Y-%m-%d %H:%M %Z')" "$cpu_ad"
	printf '| Çekirdek | %s |\n| Yazılım | %s, ModSecurity 3 + OWASP CRS (Ubuntu paketi), wrk |\n| Yük | %s bağlantı, her koşu %s sn, TLS |\n\n' "$(uname -r)" "$surum_nginx" "$BAGLANTI" "$SURE"
	printf '## İşlev: %d / %d\n\nGerçek ModSecurity ve CRS çalıştı. Örnek saldırı seti küçüktür, WAF'"'"'ın bütün saldırıları durdurduğunu göstermez. Beklenen kod meşru istekte 200, saldırıda 403'"'"'tür.\n\n' "$ISLEV_GECEN" "$ISLEV_TOPLAM"
	printf '| İstek | Beklenen | Gerçek | Sonuç |\n|---|---|---|---|\n'
	awk -F'|' '{ printf "| %s | %s | %s | %s |\n", $1, $2, $3, $4 }' "$ISLEV"
	printf '\n## Yük\n\nİşlemci, WAF için ayrılan dört çekirdeğin ortalama kullanımıdır. Değerler yalnızca WAF açık ve kapalı arasındaki farkı görmek içindir.\n\n'
	printf '| Koşu | İstek/sn | Veri/sn | p50 | p99 | 2xx/3xx dışı | Soket hatası | İşlemci | Bellek |\n|---|---:|---:|---:|---:|---:|---|---:|---:|\n'
	awk -F'|' '{ printf "| %s | %s | %s | %s | %s | %s | %s | %%%s | %s MB |\n", $1, $2, $3, $4, $5, $6, $7, $8, $9 }' "$YUK"
	printf '\n## Sınanmayanlar\n\n- VRRP ile sanal adres geçişi ve iki düğümlü çalışma\n- Hedef sunucu, gerçek ağ kartı ve 3 Gbps yük\n- Gerçek LMS trafiği, sınav uç noktaları ve yanlış pozitif oranı\n- WAF ile uygulama arasında TLS\n- FortiGate üzerinden geçiş ve IPS\n'
} >"$RAPOR"
printf 'İşlev testleri: %d / %d. Rapor: waf/sonuclar/DUMAN.md\n' "$ISLEV_GECEN" "$ISLEV_TOPLAM"
((ISLEV_GECEN == ISLEV_TOPLAM))
