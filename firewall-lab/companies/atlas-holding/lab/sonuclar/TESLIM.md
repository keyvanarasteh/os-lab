# Teslim kontrolleri

Bu dosyayı `lab/teslim-kontrol.sh` üretir, elle düzenlenmez. Dersin deposuna hiçbir şey gönderilmedi: kontroller geçici bir kopyada çalıştı.

| Bilgi | Değer |
|---|---|
| Tarih | 2026-11-07 19:48 +03 |
| `os-lab` sürümü | 0e09c32 2026-11-07 |
| Ortam | Linux 6.6.87.2-microsoft-standard-WSL2, Python 3.12.3 |

## Sonuç

| Kontrol | Sonuç |
|---|---|
| Dersin şema doğrulayıcısı (`validate.py`) | Geçti |
| Dersin katalog aracı (`catalog.py`) | Çalıştı |
| Dersin kural üreticisi: nftables sözdizimi | 4 / 4 güvenlik duvarı yüklendi |
| Sağlık denetimi (`audit.ts`) | 100 / 100 (42 kontrol, 0 bulgu) |

**Sağlık denetiminin puanı güvenlik kanıtı değildir.** Denetim çoğunlukla metinde anahtar kelime arar, kuralları çalıştırmaz. Bu projenin öğrencilerin bütün internetini kesen önceki sürümü 100 / 100 almıştı. Gerçek sonuçlar [PAKET.md](PAKET.md) ve [MODEL.md](MODEL.md) dosyalarındadır.

**Dersin kural üreticisi hakkında:** `nft -c` yalnızca sözdizimini denetler. Araç `internet`, `wan-*` ve FQDN değerlerini `any` olarak işler ve `direction: in` kurallarını güvenlik duvarının kendi girişine yazar, ayrıca kendi başına SSH izni ekler. Bu yüzden üretilen dosya doğrudan üretimde kullanılacak bir kural seti değildir.

## Dersin kataloğunda görünecek satırlar

`priceUsd` tek cihazın donanım fiyatıdır. Toplam maliyet değildir, ayrıntı ana README bölüm 4 içindedir.

| Şube | Segment | Ürün | Fiyat (USD) | Kural satırı |
|---|---|---|---:|---:|
| İstanbul Genel Merkez | perimeter | FortiGate 200G | 8920 | 145 |
| İstanbul Genel Merkez | dmz-waf | ModSecurity + OWASP Core Rule Set (Nginx, iki sunucu, aktif-pasif) | 0 | 4 |
| İzmir Ofisi | perimeter | FortiGate 120G | 4280 | 60 |
| Amsterdam Ofisi | perimeter | FortiGate 70G | 1210 | 67 |
| Ankara Akademik Şube | perimeter | FortiGate 900G | 32320 | 95 |
| Ankara Akademik Şube | dmz-waf | ModSecurity + OWASP Core Rule Set (Nginx, iki sunucu, aktif-pasif) | 0 | 4 |

## Kural üreticisi çıktısı

| Şube | Üretilen kural satırı | `nft -c` |
|---|---:|---|
| istanbul | 146 | Yüklendi |
| izmir | 61 | Yüklendi |
| amsterdam | 68 | Yüklendi |
| ankara-akademik | 96 | Yüklendi |
