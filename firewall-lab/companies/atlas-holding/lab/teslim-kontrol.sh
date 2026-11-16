#!/usr/bin/env bash
#
# Dersin os-lab araçlarıyla teslim kontrolü. os-lab deposuna hiçbir şey göndermez:
# depoyu kopyalar, company.json'u yalnızca bu geçici kopyaya koyar.
#
# Kullanım (Linux, root gerekir, çünkü nft denetimi izole isim alanında yapılır):
#   sudo bash lab/teslim-kontrol.sh <os-lab klonu> [node yolu]
#
# os-lab klonu için:
#   git clone --depth 1 https://github.com/keyvanarasteh/os-lab.git
#
# Sağlık denetimi dersin paneldeki dashboard/src/firewall/audit.ts dosyasıdır. Dosya yoksa
# veya node bulunamazsa o adım "çalıştırılmadı" olarak kaydedilir.

set -uo pipefail
export LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OSLAB="${1:?os-lab klonu gerekli}"
NODE="${2:-$(command -v node || true)}"
RAPOR="$KOK/lab/sonuclar/TESLIM.md"
GECICI=$(mktemp -d /tmp/atlas-teslim.XXXXXX)
NS=atl-teslim
temizle() { ip netns del "$NS" 2>/dev/null; rm -rf "$GECICI"; }
trap temizle EXIT

[[ -f $OSLAB/firewall-lab/scripts/validate.py ]] || { echo "HATA: $OSLAB içinde firewall-lab yok" >&2; exit 2; }
SLUG=$(python3 -c "import json;print(json.load(open('$KOK/company.json',encoding='utf-8'))['slug'])")
cp -r "$OSLAB/firewall-lab" "$GECICI/firewall-lab"
mkdir -p "$GECICI/firewall-lab/companies/$SLUG"
cp "$KOK/company.json" "$KOK/README.md" "$GECICI/firewall-lab/companies/$SLUG/"
OSLAB_COMMIT=$(git -c safe.directory='*' -C "$OSLAB" log -1 --format='%h %ad' --date=short 2>/dev/null || echo bilinmiyor)

printf '=== Dersin doğrulayıcısı\n'
DOGRULA=$(python3 -I "$GECICI/firewall-lab/scripts/validate.py" "$SLUG" 2>&1)
DOGRULA_RC=$?
printf '%s\nrc=%s\n' "$DOGRULA" "$DOGRULA_RC"

printf '=== Dersin katalog aracı\n'
KATALOG=$(python3 -I "$GECICI/firewall-lab/scripts/catalog.py" 2>&1)
KATALOG_RC=$?
printf '%s\nrc=%s\n' "$KATALOG" "$KATALOG_RC"
KATALOG_OZET=$(python3 -I - "$GECICI/firewall-lab/catalog.json" "$SLUG" <<'PY'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
for r in c["firewalls"]:
    if r["companySlug"] == sys.argv[2]:
        print(f'{r["branch"]}|{r["segment"]}|{r["product"]}|{r["priceUsd"]}|{r["ruleCount"]}')
PY
)

printf '=== Dersin kural üreticisi ve nftables sözdizimi\n'
: >"$GECICI/render.txt"
RENDER_HATA=0
ip netns add "$NS" || { echo "HATA: isim alanı açılamadı (root gerekir)" >&2; exit 2; }
for sube in istanbul izmir amsterdam ankara-akademik; do
	dosya="$GECICI/$sube.nft"
	python3 -I "$GECICI/firewall-lab/vm/scripts/render-rules.py" "$SLUG" --branch "$sube" --segment perimeter --target nft -o "$dosya" >/dev/null
	if ip netns exec "$NS" nft -c -f "$dosya" >"$GECICI/nft.log" 2>&1; then
		sonuc=Yüklendi
	else
		sonuc="Yüklenmedi: $(head -1 "$GECICI/nft.log" | cut -c1-100)"
		RENDER_HATA=$((RENDER_HATA + 1))
	fi
	# Kaynak veya hedefi "any"a düşen satırlar: internet, wan-* ve FQDN dışında olmamalı
	acik=$(grep -cE 'accept comment|drop comment|reject comment' "$dosya")
	printf '%s|%s|%s\n' "$sube" "$acik" "$sonuc" >>"$GECICI/render.txt"
	printf '%-18s %s satır: %s\n' "$sube" "$acik" "$sonuc"
done

printf '=== Sağlık denetimi\n'
AUDIT="$OSLAB/dashboard/src/firewall/audit.ts"
DENETIM_DURUM="Çalıştırılmadı: audit.ts veya node bulunamadı"
DENETIM_SATIR=""
if [[ -f $AUDIT && -n $NODE ]]; then
	# Dosyalar yerel kopyaya alınır; node çalışma dizininden göreli yolla çalışır (WSL'de node.exe için gerekli).
	mkdir -p "$KOK/lab/.denetim-gecici"
	cp "$AUDIT" "$KOK/lab/.denetim-gecici/audit.ts"
	cat >"$KOK/lab/.denetim-gecici/calistir.mjs" <<'JS'
import { readFileSync } from "node:fs";
import { auditCompany } from "./audit.ts";
const a = auditCompany(JSON.parse(readFileSync("../../company.json", "utf8")));
console.log(`PUAN|${a.score}|${a.checks}|${a.total}`);
for (const f of a.findings) console.log(`BULGU|${f.severity}|${f.id}|${f.title}|${(f.instances || []).length}`);
JS
	DENETIM=$(cd "$KOK/lab/.denetim-gecici" && "$NODE" --no-warnings calistir.mjs 2>&1)
	rc=$?
	rm -rf "$KOK/lab/.denetim-gecici"
	printf '%s\nrc=%s\n' "$DENETIM" "$rc"
	if ((rc == 0)); then
		IFS='|' read -r _ PUAN KONTROL BASARISIZ <<<"$(grep '^PUAN' <<<"$DENETIM")"
		DENETIM_DURUM="$PUAN / 100 ($KONTROL kontrol, $BASARISIZ bulgu)"
		DENETIM_SATIR=$(grep '^BULGU' <<<"$DENETIM")
	else
		DENETIM_DURUM="Çalıştırılamadı: rc=$rc"
	fi
fi

{
	printf '# Teslim kontrolleri\n\n'
	printf 'Bu dosyayı `lab/teslim-kontrol.sh` üretir, elle düzenlenmez. Dersin deposuna hiçbir şey gönderilmedi: kontroller geçici bir kopyada çalıştı.\n\n'
	printf '| Bilgi | Değer |\n|---|---|\n'
	printf '| Tarih | %s |\n| `os-lab` sürümü | %s |\n| Ortam | %s |\n\n' "$(date '+%Y-%m-%d %H:%M %Z')" "$OSLAB_COMMIT" "$(uname -sr), $(python3 --version)"
	printf '## Sonuç\n\n| Kontrol | Sonuç |\n|---|---|\n'
	printf '| Dersin şema doğrulayıcısı (`validate.py`) | %s |\n' "$([[ $DOGRULA_RC == 0 ]] && echo Geçti || echo Kaldı)"
	printf '| Dersin katalog aracı (`catalog.py`) | %s |\n' "$([[ $KATALOG_RC == 0 ]] && echo Çalıştı || echo Hata)"
	printf '| Dersin kural üreticisi: nftables sözdizimi | %s |\n' "$([[ $RENDER_HATA == 0 ]] && echo '4 / 4 güvenlik duvarı yüklendi' || echo "$RENDER_HATA güvenlik duvarında hata")"
	printf '| Sağlık denetimi (`audit.ts`) | %s |\n\n' "$DENETIM_DURUM"
	printf '**Sağlık denetiminin puanı güvenlik kanıtı değildir.** Denetim çoğunlukla metinde anahtar kelime arar, kuralları çalıştırmaz. Bu projenin öğrencilerin bütün internetini kesen önceki sürümü 100 / 100 almıştı. Gerçek sonuçlar [PAKET.md](PAKET.md) ve [MODEL.md](MODEL.md) dosyalarındadır.\n\n'
	printf '**Dersin kural üreticisi hakkında:** `nft -c` yalnızca sözdizimini denetler. Araç `internet`, `wan-*` ve FQDN değerlerini `any` olarak işler ve `direction: in` kurallarını güvenlik duvarının kendi girişine yazar, ayrıca kendi başına SSH izni ekler. Bu yüzden üretilen dosya doğrudan üretimde kullanılacak bir kural seti değildir.\n\n'
	if [[ -n $DENETIM_SATIR ]]; then
		printf '## Sağlık denetimi bulguları\n\n| Önem | Kontrol | Başlık | Etkilenen | Açıklama |\n|---:|---|---|---:|---|\n'
		while IFS='|' read -r _ onem kid baslik adet; do
			aciklama=""
			[[ $kid == fiveProducts ]] && aciklama="Bilinçli: doğrulanamayan fiyatlar çıkarıldı, teklif gelince eklenir"
			printf '| %s | `%s` | %s | %s | %s |\n' "$onem" "$kid" "$baslik" "$adet" "$aciklama"
		done <<<"$DENETIM_SATIR"
		printf '\n'
	fi
	printf '## Dersin kataloğunda görünecek satırlar\n\n`priceUsd` tek cihazın donanım fiyatıdır. Toplam maliyet değildir, ayrıntı ana README bölüm 4 içindedir.\n\n'
	printf '| Şube | Segment | Ürün | Fiyat (USD) | Kural satırı |\n|---|---|---|---:|---:|\n'
	awk -F'|' '{ printf "| %s | %s | %s | %s | %s |\n", $1, $2, $3, $4, $5 }' <<<"$KATALOG_OZET"
	printf '\n## Kural üreticisi çıktısı\n\n| Şube | Üretilen kural satırı | `nft -c` |\n|---|---:|---|\n'
	awk -F'|' '{ printf "| %s | %s | %s |\n", $1, $2, $3 }' "$GECICI/render.txt"
} >"$RAPOR"
printf 'Rapor: lab/sonuclar/TESLIM.md\n'
[[ $DOGRULA_RC == 0 && $RENDER_HATA == 0 ]]
