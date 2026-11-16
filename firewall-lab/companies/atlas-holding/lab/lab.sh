#!/usr/bin/env bash
#
# Atlas Holding gerçek Linux paket testi.
#
# Dört şube güvenlik duvarını ve her VLAN'ı Linux ağ isim alanı olarak kurar. Kuralları
# company.json'dan üretip nftables ile yükler ve gerçek TCP/UDP bağlantılarıyla sınar.
# İsim alanlarının gerçek ağa bağlantısı yoktur; ana makinenin kuralları değişmez.
#
# Kullanım (root gerekir):
#   lab.sh hepsi     kurar, sınar, raporu yazar ve temizler
#   lab.sh kur       yalnızca kurar (elle deneme yapmak için)
#   lab.sh test      kurulu lab'i sınar ve raporu yazar
#   lab.sh temizle   lab'i kaldırır
#
# Çıkış kodu: 0 hepsi geçti, 1 kalan test var, 2 lab çalıştırılamadı.

set -uo pipefail
export LC_ALL=C.UTF-8

LAB_DIZINI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOPOLOJI="$LAB_DIZINI/topoloji.txt"
POLITIKA="$LAB_DIZINI/politika.py"
SONUC_DIZINI="$LAB_DIZINI/sonuclar"
HAM_SONUC="$SONUC_DIZINI/ham-paket.txt"
RAPOR="$SONUC_DIZINI/PAKET.md"
CALISMA=/run/atlas-lab
ON_EK=atl-

SUBELER=(ist izm ams ank)
declare -A SUBE_ADI=([ist]=istanbul [izm]=izmir [ams]=amsterdam [ank]=ankara-akademik)
declare -A WAN_IP=([ist]=203.0.113.1 [izm]=203.0.113.2 [ams]=203.0.113.3 [ank]=203.0.113.4)
declare -A OZEL_BLOK=([ist]=10.1.0.0/16 [izm]=10.2.0.0/16 [ams]=10.3.0.0/16 [ank]=10.4.0.0/16)
declare -A TUNEL_NO=([izm]=2 [ams]=3 [ank]=4)
ISP_IP=203.0.113.254

hata() { printf 'HATA: %s\n' "$*" >&2; exit 2; }
k() { "$@" || hata "komut başarısız: $*"; }
ns() { local ad=$1; shift; ip netns exec "$ON_EK$ad" "$@"; }
satirlar() { grep -vE '^[[:space:]]*(#|$)' "$1"; }

on_kontrol() {
	[[ $EUID -eq 0 ]] || hata "root gerekir."
	local arac
	for arac in ip nft nc timeout sysctl python3; do
		command -v "$arac" >/dev/null || hata "$arac bulunamadı. Kurulum: apt install nftables iproute2 netcat-openbsd python3"
	done
	nc -h 2>&1 | grep -q OpenBSD || hata "netcat-openbsd gerekir."
	local dosya
	for dosya in "$TOPOLOJI" "$LAB_DIZINI/gereksinimler.txt" "$LAB_DIZINI/lab-degerleri.txt" "$POLITIKA" "${BASH_SOURCE[0]}"; do
		if grep -q $'\r' "$dosya"; then
			hata "$dosya CRLF satır sonu içeriyor. .gitattributes'a uygun olarak LF olmalı."
		fi
	done
}

# --- Kurulum ---------------------------------------------------------------

ad_ekle() {
	k ip netns add "$ON_EK$1"
	k ns "$1" ip link set lo up
	# IPv6 gürültüsü kural sayaçlarını kirletmesin.
	k ns "$1" sysctl -qw net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1
}

yonlendirici_yap() {
	k ns "$1" sysctl -qw net.ipv4.ip_forward=1 net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.default.rp_filter=0
}

kablo() { # ad1 ad2 arayuz1 arayuz2
	k ip link add "$3" netns "$ON_EK$1" type veth peer name "$4" netns "$ON_EK$2"
}

internet_kur() {
	ad_ekle isp
	yonlendirici_yap isp
	ad_ekle net
	kablo isp net net eth0
	k ns isp ip addr add 198.51.100.254/24 dev net
	k ns isp ip link set net up
	local a
	for a in 198.51.100.10 198.51.100.20 198.51.100.21 198.51.100.30 198.51.100.31; do
		k ns net ip addr add "$a/24" dev eth0
	done
	k ns net ip link set eth0 up
	k ns net ip route add default via 198.51.100.254
}

guvenlik_duvarlarini_kur() {
	local s
	for s in "${SUBELER[@]}"; do
		ad_ekle "fw-$s"
		yonlendirici_yap "fw-$s"
		kablo "fw-$s" isp wan "$s"
		k ns "fw-$s" ip addr add "${WAN_IP[$s]}/32" dev wan
		k ns "fw-$s" ip link set wan up
		k ns "fw-$s" ip route add "$ISP_IP/32" dev wan
		k ns "fw-$s" ip route add default via "$ISP_IP" dev wan
		k ns isp ip addr add "$ISP_IP/32" dev "$s"
		k ns isp ip link set "$s" up
		k ns isp ip route add "${WAN_IP[$s]}/32" dev "$s"
		# Operatör özel adresleri de yönlendirir. Böylece "internetten iç ağa erişilemez"
		# sonucunu yönlendirme eksikliği değil, güvenlik duvarının kendisi üretir.
		k ns isp ip route add "${OZEL_BLOK[$s]}" via "${WAN_IP[$s]}" dev "$s"
	done
}

tunelleri_kur() {
	# IPsec şifrelemesi modellenmez: tünel, iki güvenlik duvarı arasında doğrudan bir bağlantıdır.
	# Şubeler bütün özel adresleri merkeze yollar, şubeler arası doğrudan bağlantı yoktur.
	local s n
	for s in izm ams ank; do
		n=${TUNEL_NO[$s]}
		kablo fw-ist "fw-$s" "tun-$s" tun
		k ns fw-ist ip addr add "172.31.$n.1/30" dev "tun-$s"
		k ns fw-ist ip link set "tun-$s" up
		k ns fw-ist ip route add "${OZEL_BLOK[$s]}" via "172.31.$n.2"
		k ns "fw-$s" ip addr add "172.31.$n.2/30" dev tun
		k ns "fw-$s" ip link set tun up
		k ns "fw-$s" ip route add 10.0.0.0/8 via "172.31.$n.1"
		k ns "fw-$s" ip route add 172.31.0.0/16 via "172.31.$n.1"
	done
}

vlanlari_kur() {
	local sube ad alt_ag gecit hostlar hedef onek ip_adresi
	local -a liste
	while IFS='|' read -r sube ad alt_ag gecit hostlar <&3; do
		hedef="$sube-$ad"
		onek=${alt_ag#*/}
		ad_ekle "$hedef"
		kablo "fw-$sube" "$hedef" "$ad" eth0
		k ns "fw-$sube" ip addr add "$gecit/$onek" dev "$ad"
		k ns "fw-$sube" ip link set "$ad" up
		IFS=',' read -ra liste <<<"$hostlar"
		for ip_adresi in "${liste[@]}"; do
			k ns "$hedef" ip addr add "$ip_adresi/$onek" dev eth0
		done
		k ns "$hedef" ip link set eth0 up
		k ns "$hedef" ip route add default via "$gecit"
	done 3< <(satirlar "$TOPOLOJI")
}

kurallari_yukle() {
	local s dosya
	for s in "${SUBELER[@]}"; do
		dosya="$CALISMA/$s.nft"
		k python3 "$POLITIKA" nft "${SUBE_ADI[$s]}" >"$dosya"
		k ns "fw-$s" nft -f "$dosya"
	done
}

dinleyicileri_baslat() {
	# Yalnızca testlerin hedeflediği porta dinleyici açılır.
	local hedef proto port
	while IFS='|' read -r hedef proto port <&3; do
		case $proto in
		tcp) ns "$hedef" nc -l -k -n "$port" >/dev/null 2>&1 </dev/null & ;;
		udp) ns "$hedef" nc -u -l -k -n "$port" >"$CALISMA/udp-$hedef-$port.log" 2>/dev/null </dev/null & ;;
		*) hata "bilinmeyen protokol: $proto" ;;
		esac
	done 3< <(cut -d'|' -f4,6,7 "$CALISMA/testler.txt" | sort -u)
	sleep 0.5
}

kur() {
	on_kontrol
	temizle
	k mkdir -p "$CALISMA"
	k python3 "$POLITIKA" testler >"$CALISMA/testler.txt"
	internet_kur
	guvenlik_duvarlarini_kur
	tunelleri_kur
	vlanlari_kur
	kurallari_yukle
	dinleyicileri_baslat
	printf 'Lab kuruldu: %s isim alanı.\n' "$(ip netns list | grep -c "^$ON_EK")"
}

temizle() {
	local ad pid
	for ad in $(ip netns list | awk '{print $1}' | grep "^$ON_EK"); do
		for pid in $(ip netns pids "$ad"); do
			kill "$pid" 2>/dev/null
		done
		ip netns del "$ad"
	done
	rm -rf "$CALISMA"
}

# --- Tek bağlantı denemesi ---------------------------------------------------

dene() { # kaynak_ad kaynak_ip hedef_ad hedef_ip proto port -> SONUC
	local kaynak=$1 kaynak_ip=$2 hedef=$3 hedef_ip=$4 proto=$5 port=$6
	SONUC=red
	if [[ $proto == tcp ]]; then
		local cikti rc
		cikti=$(ns "$kaynak" timeout 3 nc -n -z -v -w 1 -s "$kaynak_ip" "$hedef_ip" "$port" 2>&1 </dev/null)
		rc=$?
		if ((rc == 0)); then
			SONUC=izin
		elif ((rc == 124)) || [[ $cikti == *"timed out"* ]]; then
			SONUC=red
		else
			SONUC=reject
		fi
	else
		# UDP'de bağlantı yoktur: paketin hedefe ulaştığı, dinleyicinin aldığı jetonla kanıtlanır.
		local jeton="j$RANDOM$RANDOM" dosya="$CALISMA/udp-$hedef-$port.log" i
		printf '%s\n' "$jeton" | ns "$kaynak" nc -u -n -w1 -q0 -s "$kaynak_ip" "$hedef_ip" "$port" >/dev/null 2>&1
		for i in 1 2 3 4 5; do
			sleep 0.1
			if grep -q "$jeton" "$dosya" 2>/dev/null; then
				SONUC=izin
				break
			fi
		done
	fi
}

sayaclari_oku() { # her satır: guvenlik_duvari tutamac kural paket
	local s
	for s in "${SUBELER[@]}"; do
		ns "fw-$s" nft -a list table inet atlas |
			sed -nE 's/.*counter packets ([0-9]+) .*comment "([^"]+)" # handle ([0-9]+).*/'"$s"' \3 \2 \1/p'
	done
}

# Sayaçlar sıfırlanmaz: "nft reset rules" nftables 1.0.9'da anonim küme içeren kurallarda
# çöküyor. Bunun yerine denemeden önceki ve sonraki değerler karşılaştırılır.
sayaclari_sifirla() { ONCEKI_SAYAC=$(sayaclari_oku); }

kararlari_oku() { # önceki okumadan beri sayacı artan kuralları "guvenlik_duvari:kural" olarak verir
	awk 'NR == FNR { once[$1 " " $2] = $4; next } $4 > once[$1 " " $2] { print $1 ":" $3 }' \
		<(printf '%s\n' "$ONCEKI_SAYAC") <(sayaclari_oku) | sort -u | tr '\n' ' ' | sed 's/ $//'
}

# --- Aşama 1: kontrol --------------------------------------------------------

kontrol_asamasi() {
	# Kurallar devre dışıyken her bağlantı kurulabilmeli. Böylece sonraki "red" sonuçlarının
	# kopuk bir yoldan veya kapalı bir dinleyiciden kaynaklanmadığı kanıtlanır.
	local s
	for s in "${SUBELER[@]}"; do
		k ns "fw-$s" nft insert rule inet atlas ileri accept
		k ns "fw-$s" nft insert rule inet atlas giris accept
	done
	KONTROL_TOPLAM=0
	KONTROL_GECEN=0
	local no kaynak kaynak_ip hedef hedef_ip proto port geri
	while IFS='|' read -r no kaynak kaynak_ip hedef hedef_ip proto port geri <&3; do
		dene "$kaynak" "$kaynak_ip" "$hedef" "$hedef_ip" "$proto" "$port"
		KONTROL_TOPLAM=$((KONTROL_TOPLAM + 1))
		if [[ $SONUC == izin ]]; then
			KONTROL_GECEN=$((KONTROL_GECEN + 1))
		else
			printf 'KONTROL HATASI %s: %s -> %s %s/%s sonucu %s\n' "$no" "$kaynak_ip" "$hedef_ip" "$proto" "$port" "$SONUC" >&2
		fi
	done 3<"$CALISMA/testler.txt"
	kurallari_yukle
	printf 'Kontrol: %d / %d yol açık.\n' "$KONTROL_GECEN" "$KONTROL_TOPLAM"
	((KONTROL_GECEN == KONTROL_TOPLAM)) || hata "Kontrol geçmedi, kural testleri güvenilir olmaz."
}

# --- Aşama 2: gereksinim testleri --------------------------------------------

testleri_calistir() {
	k mkdir -p "$SONUC_DIZINI"
	printf '# no|kaynak|hedef|proto|port|beklenen|gercek|karar_veren_kural|durum|aciklama\n' >"$HAM_SONUC"
	TEST_TOPLAM=0
	TEST_GECEN=0
	local no kaynak kaynak_ip hedef hedef_ip proto port beklenen aciklama karar durum
	while IFS='|' read -r no kaynak kaynak_ip hedef hedef_ip proto port beklenen aciklama <&3; do
		sayaclari_sifirla
		dene "$kaynak" "$kaynak_ip" "$hedef" "$hedef_ip" "$proto" "$port"
		karar=$(kararlari_oku)
		[[ -n $karar ]] || karar=yok
		durum=Geçti
		[[ $SONUC == "$beklenen" ]] || durum=Kaldı
		# Engellenen trafikte kararı bir kural vermiş olmalı; yoksa sonuç yolun kopukluğundan gelebilir.
		[[ $SONUC != izin && $karar == yok ]] && durum=Kaldı
		TEST_TOPLAM=$((TEST_TOPLAM + 1))
		[[ $durum == Geçti ]] && TEST_GECEN=$((TEST_GECEN + 1))
		printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' "$no" "$kaynak_ip" "$hedef_ip" "$proto" "$port" \
			"$beklenen" "$SONUC" "$karar" "$durum" "$aciklama" >>"$HAM_SONUC"
		printf '%-7s %-6s beklenen=%-6s gerçek=%-6s karar=%s\n' "$no" "$durum" "$beklenen" "$SONUC" "$karar"
	done 3<"$CALISMA/testler.txt"
	printf 'Gereksinim testleri: %d / %d geçti.\n' "$TEST_GECEN" "$TEST_TOPLAM"
}

# --- Aşama 3: bozma deneyleri ------------------------------------------------
# Kurallar gerçekten bozulur ve testin bunu görüp görmediği ölçülür.

kural_tutamaci() { # guvenlik_duvari yorum -> ilk eşleşen kuralın tutamacı
	ns "fw-$1" nft -a list chain inet atlas ileri |
		sed -nE 's/.*comment "'"$2"'" # handle ([0-9]+).*/\1/p' | head -1
}

deney_kaydet() { # ad iddia beklenen_sonuc beklenen_kural
	local durum=Doğrulandı karar
	karar=$(kararlari_oku)
	if [[ $SONUC != "$3" || $karar != "$4" ]]; then
		durum="Doğrulanamadı"
	fi
	DENEY_TOPLAM=$((DENEY_TOPLAM + 1))
	[[ $durum == Doğrulandı ]] && DENEY_GECEN=$((DENEY_GECEN + 1))
	printf '%s|%s|%s|%s|%s\n' "$1" "$2" "$SONUC" "$karar" "$durum" >>"$CALISMA/deney.txt"
	printf 'Deney: %-50s %s (%s, %s)\n' "$1" "$durum" "$SONUC" "$karar"
}

deneyleri_calistir() {
	DENEY_TOPLAM=0
	DENEY_GECEN=0
	: >"$CALISMA/deney.txt"
	local tutamac

	# A: Eski hata: öğrenciden internete portsuz ret, web izninin üstünde.
	tutamac=$(kural_tutamaci ank 5)
	k ns fw-ank nft "insert rule inet atlas ileri position $tutamac ip saddr 10.4.128.0/17 oifname \"wan\" counter drop comment \"eski-5\""
	sayaclari_sifirla
	dene ank-v100 10.4.128.100 net 198.51.100.10 tcp 443
	deney_kaydet "Eski kural 5 geri kondu" "Portsuz ret öğrencinin web erişimini keser" red ank:eski-5
	kurallari_yukle

	# B: Ankara kural 4, kural 3'ün üstüne alınır.
	tutamac=$(kural_tutamaci ank 3)
	k ns fw-ank nft "insert rule inet atlas ileri position $tutamac ip saddr 10.4.128.0/17 ip daddr 10.0.0.0/8 counter drop comment \"4\""
	sayaclari_sifirla
	dene ank-v100 10.4.128.100 ank-v70 10.4.70.10 tcp 443
	deney_kaydet "Ankara kural 4, kural 3'ün üstüne alındı" "Kural 3 kural 4'ten önce gelmezse öğrenciler LMS'e ulaşamaz" red ank:4
	kurallari_yukle

	# C: O4 silinir.
	while tutamac=$(kural_tutamaci ank O4) && [[ -n $tutamac ]]; do
		k ns fw-ank nft delete rule inet atlas ileri handle "$tutamac"
	done
	sayaclari_sifirla
	dene ank-v100 10.4.128.100 ank-v60 10.4.60.2 udp 67
	deney_kaydet "Ankara'da O4 silindi" "O4 silinirse istemciler IP alamaz" red ank:4
	kurallari_yukle

	# D: O3, O2'nin üstüne alınır.
	tutamac=$(kural_tutamaci ist O2)
	k ns fw-ist nft "insert rule inet atlas ileri position $tutamac ip daddr { 10.1.10.0/26, 10.2.10.0/26, 10.3.10.0/26, 10.4.10.0/26 } counter drop comment \"O3\""
	sayaclari_sifirla
	dene ist-v61 10.1.61.20 izm-v10 10.2.10.1 udp 161
	deney_kaydet "İstanbul'da O3, O2'nin üstüne alındı" "O2, O3'ten önce gelmezse izleme durur" red ist:O3
	kurallari_yukle

	# E: Merkez izni silinir, şube izni tek başına kalır.
	while tutamac=$(kural_tutamaci ist 4) && [[ -n $tutamac ]]; do
		k ns fw-ist nft delete rule inet atlas ileri handle "$tutamac"
	done
	sayaclari_sifirla
	dene ank-v20 10.4.20.10 ist-v60 10.1.60.31 tcp 443
	deney_kaydet "İstanbul kural 4 silindi" "Şube izni merkez izni olmadan yetmez" red "ank:8 ist:O7"
	kurallari_yukle

	printf 'Bozma deneyleri: %d / %d doğrulandı.\n' "$DENEY_GECEN" "$DENEY_TOPLAM"
}

# --- Aşama 4: aynı VLAN ve sunucu güvenlik duvarı ----------------------------
# Çevre güvenlik duvarının görmediği trafiği gösterir. Dört sunucu ayrı isim alanındadır ve
# aynı köprüye bağlıdır, yani arada yönlendirme yoktur.

sunucu_vlan_asamasi() {
	local -A SUNUCU=([erp]=10.1.60.31 [git]=10.1.60.32 [ad]=10.1.60.3 [dns]=10.1.60.2)
	local -A NESNE=([erp]=ist-erp [git]=ist-git [ad]=ist-ad [dns]=ist-dns)
	local h
	ad_ekle hf-sw
	k ns hf-sw ip link add br0 type bridge
	k ns hf-sw ip link set br0 up
	for h in erp git ad dns; do
		ad_ekle "hf-$h"
		kablo hf-sw "hf-$h" "p-$h" eth0
		k ns hf-sw ip link set "p-$h" master br0
		k ns hf-sw ip link set "p-$h" up
		k ns "hf-$h" ip addr add "${SUNUCU[$h]}/24" dev eth0
		k ns "hf-$h" ip link set eth0 up
	done
	ns hf-git nc -l -k -n 22 >/dev/null 2>&1 </dev/null &
	ns hf-erp nc -l -k -n 443 >/dev/null 2>&1 </dev/null &
	ns hf-ad nc -l -k -n 636 >/dev/null 2>&1 </dev/null &
	ns hf-erp nc -l -k -n 22 >/dev/null 2>&1 </dev/null &
	ns hf-dns nc -u -l -k -n 53 >"$CALISMA/udp-hf-dns-53.log" 2>/dev/null </dev/null &
	sleep 0.5

	: >"$CALISMA/sunucu.txt"
	SUNUCU_TOPLAM=0
	SUNUCU_GECEN=0
	sunucu_dene() { # no aciklama kaynak hedef hedef_ip proto port beklenen asama
		dene "hf-$3" "${SUNUCU[$3]}" "hf-$4" "$5" "$6" "$7"
		local durum=Geçti
		[[ $SONUC == "$8" ]] || durum=Kaldı
		SUNUCU_TOPLAM=$((SUNUCU_TOPLAM + 1))
		[[ $durum == Geçti ]] && SUNUCU_GECEN=$((SUNUCU_GECEN + 1))
		printf '%s|%s|%s|%s|%s|%s\n' "$1" "$9" "$2" "$8" "$SONUC" "$durum" >>"$CALISMA/sunucu.txt"
		printf 'Sunucu %-5s %-6s %s: beklenen=%s gerçek=%s\n' "$1" "$durum" "$2" "$8" "$SONUC"
	}
	# Sunucu güvenlik duvarı yokken aynı VLAN'daki her şey geçer: çevre güvenlik duvarı bunu göremez.
	sunucu_dene S-01 "ERP, Git sunucusuna SSH yapar" erp git 10.1.60.32 tcp 22 izin "Sunucu güvenlik duvarı yok"
	sunucu_dene S-02 "Git, ERP sunucusuna HTTPS yapar" git erp 10.1.60.31 tcp 443 izin "Sunucu güvenlik duvarı yok"

	for h in erp git ad dns; do
		python3 "$POLITIKA" sunucu-nft "${NESNE[$h]}" >"$CALISMA/hf-$h.nft" || hata "sunucu kuralı üretilemedi"
		k ns "hf-$h" nft -f "$CALISMA/hf-$h.nft"
	done
	sunucu_dene S-03 "ERP, dizin sunucusuna LDAPS yapar" erp ad 10.1.60.3 tcp 636 izin "Sunucu güvenlik duvarı açık"
	sunucu_dene S-04 "Git, dizin sunucusuna LDAPS yapar" git ad 10.1.60.3 tcp 636 izin "Sunucu güvenlik duvarı açık"
	sunucu_dene S-05 "ERP, iç DNS kullanır" erp dns 10.1.60.2 udp 53 izin "Sunucu güvenlik duvarı açık"
	sunucu_dene S-06 "ERP, Git sunucusuna SSH yapamaz" erp git 10.1.60.32 tcp 22 red "Sunucu güvenlik duvarı açık"
	sunucu_dene S-07 "Git, ERP sunucusuna HTTPS yapamaz" git erp 10.1.60.31 tcp 443 red "Sunucu güvenlik duvarı açık"
	sunucu_dene S-08 "Dizin sunucusu ERP'ye SSH yapamaz" ad erp 10.1.60.31 tcp 22 red "Sunucu güvenlik duvarı açık"
	printf 'Aynı VLAN testleri: %d / %d geçti.\n' "$SUNUCU_GECEN" "$SUNUCU_TOPLAM"
}

# --- Rapor -------------------------------------------------------------------

rapor_yaz() {
	local surum commit tarih
	tarih=$(date '+%Y-%m-%d %H:%M %Z')
	surum=$(nft --version)
	local git_komut=(git -c safe.directory='*' -c core.autocrlf=true -C "$LAB_DIZINI/..")
	commit=$("${git_komut[@]}" rev-parse --short HEAD 2>/dev/null || echo bilinmiyor)
	if [[ -n $("${git_komut[@]}" status --porcelain -- company.json lab ':!lab/sonuclar' 2>/dev/null) ]]; then
		commit="$commit + kaydedilmemiş değişiklikler"
	fi
	{
		printf '# Gerçek Linux paket testi sonuçları\n\n'
		printf 'Bu dosyayı `lab/lab.sh hepsi` üretir, elle düzenlenmez. Yöntem ve sınırlar: [lab/README.md](../README.md). Model sonuçları ayrıdır: [MODEL.md](MODEL.md).\n\n'
		printf 'Kurallar `company.json` dosyasından üretilip Linux çekirdeğinde nftables ile çalıştırılır. **Bu testler FortiGate üzerinde yapılmadı.** IPS, uygulama tanıma, TLS denetimi, HA, IPsec, WAF ve hız sınırı burada sınanmaz.\n\n'
		printf '| Çalıştırma bilgisi | Değer |\n|---|---|\n'
		printf '| Tarih | %s |\n| Ortam | Linux ağ isim alanları, gerçek ağa bağlantı yok |\n| Çekirdek | %s |\n| nftables | %s |\n| Commit | %s |\n\n' "$tarih" "$(uname -r)" "$surum" "$commit"

		printf '## Özet\n\n| Aşama | Sonuç |\n|---|---:|\n'
		printf '| Kontrol: kurallar kapalıyken açık yol | %d / %d |\n' "$KONTROL_GECEN" "$KONTROL_TOPLAM"
		printf '| Gereksinim testleri | %d / %d |\n' "$TEST_GECEN" "$TEST_TOPLAM"
		printf '| Bozma deneyleri: doğrulanan | %d / %d |\n' "$DENEY_GECEN" "$DENEY_TOPLAM"
		printf '| Aynı VLAN ve sunucu güvenlik duvarı | %d / %d |\n\n' "$SUNUCU_GECEN" "$SUNUCU_TOPLAM"

		printf '## Kalan testler\n\n'
		if ((TEST_GECEN == TEST_TOPLAM)); then
			printf 'Kalan test yok.\n\n'
		else
			printf '| No | Akış | Beklenen | Gerçek | Karar veren kural |\n|---|---|---|---|---|\n'
			awk -F'|' '!/^#/ && $9 == "Kaldı" { printf "| %s | %s: `%s` → `%s` %s/%s | %s | %s | %s |\n", $1, $10, $2, $3, $4, $5, $6, $7, $8 }' "$HAM_SONUC"
			printf '\n'
		fi

		printf '## Bozma deneyleri\n\nKural gerçekten bozulur, sonuç ölçülür, sonra kurallar geri yüklenir.\n\n'
		printf '| Yapılan bozma | Beklenen etki | Gerçek | Karar veren kural | Sonuç |\n|---|---|---|---|---|\n'
		awk -F'|' '{ printf "| %s | %s | %s | %s | %s |\n", $1, $2, $3, $4, $5 }' "$CALISMA/deney.txt"
		printf '\n'

		printf '## Aynı VLAN ve sunucu güvenlik duvarı\n\n'
		printf 'Dört sunucu tek köprüye bağlıdır, arada yönlendirme yoktur. İlk iki satır çevre güvenlik duvarının bu trafiği göremediğini, kalanlar sunucu güvenlik duvarının akışları sınırladığını gösterir. Kurallar `sunucu-akislari.json` dosyasından üretilir. Yalnızca İstanbul VLAN 60 sınanır.\n\n'
		printf '| No | Durum | Akış | Beklenen | Gerçek | Sonuç |\n|---|---|---|---|---|---|\n'
		awk -F'|' '{ printf "| %s | %s | %s | %s | %s | %s |\n", $1, $2, $3, $4, $5, $6 }' "$CALISMA/sunucu.txt"
		printf '\n'

		printf '## Tüm gereksinim testleri\n\n| No | Akış | Kaynak → hedef | Servis | Beklenen | Gerçek | Karar veren kural | Sonuç |\n|---|---|---|---|---|---|---|---|\n'
		awk -F'|' '!/^#/ { printf "| %s | %s | `%s` → `%s` | %s/%s | %s | %s | %s | %s |\n", $1, $10, $2, $3, $4, $5, $6, $7, $8, $9 }' "$HAM_SONUC"
	} >"$RAPOR"
	printf 'Rapor: lab/sonuclar/PAKET.md\n'
}

testleri_tamamla() {
	on_kontrol
	ip netns list | grep -q "^${ON_EK}isp" || hata "Lab kurulu değil. Önce: lab.sh kur"
	kontrol_asamasi
	testleri_calistir
	deneyleri_calistir
	sunucu_vlan_asamasi
	rapor_yaz
	((TEST_GECEN == TEST_TOPLAM && DENEY_GECEN == DENEY_TOPLAM && SUNUCU_GECEN == SUNUCU_TOPLAM))
}

# --- Giriş -------------------------------------------------------------------

case "${1:-}" in
kur) kur ;;
test) testleri_tamamla ;;
temizle) temizle ;;
hepsi)
	trap temizle EXIT
	kur
	testleri_tamamla
	exit $?
	;;
*)
	printf 'Kullanım: %s {hepsi|kur|test|temizle}\n' "$0" >&2
	exit 2
	;;
esac
