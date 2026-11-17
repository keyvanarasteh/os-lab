# MYO062 Vize — PENT-18

**Öğrenci:** Rauf Fatih Kaya · 2520191004 · [RFKaya](https://github.com/RFKaya)

**Görev:** Extension Native-Messaging Host Risk Analyzer

**İlk teslim:** 13 Kasım 2026

**Rebase ve rapor düzenlemesi:** 14 Kasım 2026

**Tek teslim PR'ı:** https://github.com/keyvanarasteh/os-lab/pull/130

## Amaç ve kapsam

Tarayıcı eklentilerinin `nativeMessaging` izniyle yerel bir programa açtığı
yetki köprüsünü çevrimdışı inceleyen Python aracı geliştirildi. Araç bir
zararlı yazılım hükmü vermez; somut dosya/konum kanıtlarıyla incelenmesi gereken
yapılandırma ve dosya izinlerini raporlar.

Hedeflerin tamamı `make_native_host_lab.py` ile yerelde üretilen, bize ait,
işlevsiz eğitim dosyalarıdır. Başka kişilerin eklentileri, sistemde kurulu hostlar,
internet hedefleri, tarayıcı profilleri veya registry taranmadı. Eklenti tarayıcıya
yüklenmedi; host programı çalıştırılmadı. Docker/VM gerektirmeyen statik görevdir.

## Uygulama

- [`scripts/analysis/ext_native_host.py`](../../../../scripts/analysis/ext_native_host.py):
  Python 3.11+ standart kütüphanesiyle CLI ve içe aktarılabilir `analyze()`.
- Manifest V2/V3 zorunlu/isteğe bağlı `nativeMessaging` izinleri; JavaScript/HTML
  üzerinde `connectNative` / `sendNativeMessage` çağrı ipuçları ve satır konumları.
- Chromium `allowed_origins` ve Firefox `allowed_extensions` kontrolü; wildcard,
  boş/geçersiz erişim listesi, eşleşmeyen kimlik, birden fazla çağıran ve eksik host.
- Host adı/türü/açıklaması; binary boyutu, SHA-256 ve PE/ELF/shebang başlıkları.
  POSIX üzerinde yazılabilir dosya/dizinler ve setuid/setgid bitleri.
- `--lab-root` tüm girdi okumalarını sınırlar. Kapsam dışına çözülen host yolu
  okunmadan raporlanır; kapsam dışı girdi dosyası analizi reddeder. JSON/kaynak/
  binary boyutu ve dosya/host sayısı sınırlıdır; eksik tarama temiz gösterilmez.
- İnsan tarafından okunabilir çıktı veya `--json`; çıkış kodları 0/1/2.
  Ayrıntılar ve sınırlamalar [kullanım belgesinde](../../../../scripts/analysis/README.md).

## 13 Kasım — rebase öncesi doğrulama

Ubuntu 24.04 / WSL2, Python 3.12.3 üzerinde:

```bash
python3 -m pytest android-lab/lab/tests/test_ext_native_host.py -q
./scripts/run-tests.sh
```

Sonuç: PENT-18 **26 test geçti**. Tam Android testleri **179 geçti, 2 atlandı**;
Source Lab **176 geçti**; örnek APK analizi/raporu tamamlandı; **70 shell betiği**
`bash -n` kontrolünden geçti. Runner özeti: **4 passed, 0 failed, 2 skipped**,
`All required checks passed.`, çıkış **0**.

Runner'da `lat` Linux PATH'inde olmadığı için grafik adımı atlandı; `lat.md 0.13.8`
ile Windows'ta **ayrıca `lat check` çalıştırıldı ve geçti**. `dashboard/node_modules`
kurulu olmadığı için isteğe bağlı dashboard kontrolü atlandı. Dashboard kaynakları,
derlenmiş çıktısı ve bağımlılıkları bu PR'da değiştirilmedi. macOS çalıştırması
yapılmadı. Windows ACL değerlendirmesi araç tarafından açıkça doğrulanmamış gösterilir.

Gerçek ham tam-runner çıktısı: [VERIFY.md](../../../../scripts/analysis/PENT-18/VERIFY.md).

Windows / Python 3.14 üzerinde araca özel testler de çalıştırıldı: **23 geçti,
3 atlandı**. Atlananlar POSIX izinleri ve symlink davranışına özgü testlerdir;
bunların tamamı Linux'ta geçti. Windows testinde geçici dosyalar çalışma klasörü
altında `--basetemp` ile tutuldu.

Tam suite'i bu ortamda çalıştırırken mevcut iki taşınabilirlik sorunu da giderildi:

1. Source Lab `sourcemap query --map` Python 3.12'de üst parser'ın `--map-*`
   seçenekleriyle karışıyordu; üst parser'da kısaltma kapatıldı. Mevcut iki CLI
   regresyon testi artık geçiyor.
2. Web UI'nin sahte preview-token testi kurulu Android VM sağlayıcısına bağlıydı.
   Bu testte plan üretimi taklit edilerek sadece token reddi sınanıyor. Üretimdeki
   web/plan güvenlik davranışı değiştirilmedi.

## Lab sonuçları

| Senaryo | Gözlem | Çıkış |
|---|---|---|
| Güvenli fixture | Tek geçerli origin, doğru kimlik, özel POSIX host dosyası; yalnızca izin bilgisi | 0 |
| Sorunlu fixture | Geçersiz `*`, izin verilmeyen çağıran, dünya/grup yazılabilir host, dinamik host adı | 1 |
| Kapsam dışı extension | Girdi lab kökünün dışında; analiz reddedildi | 2 |

## Kanıt videosu

**2 dakika 38 saniye**, 1280×720 MP4, Türkçe açıklamalar:

[PENT-18 kanıt videosu](https://github.com/RFKaya/os-lab/releases/download/myo062-pent18-proof-2026-11-13/PENT-18-kanit.mp4)

Video, gerçekten çalıştırılan komutların yakalanmış çıktılarının okunabilir bir
terminal tekrarıdır; bu biçim videoda da açıkça etiketlenmiştir. Masaüstü ekran
kaydı veya canlı tarayıcı/native-host çalıştırması olarak sunulmaz. Manifestler,
güvenli/sorunlu örnek, JSON raporu, kapsam reddi, 26 test ve tamamlanmış tam
runner çıktısı gösterilir. JSON sahnesi tam çıktının seçili alanlarıdır ve bu
seçim sahnede etiketlidir. Ham komut çıktıları aynı kanıt release'ine eklenmiştir.

## Sınırlamalar

JavaScript taraması lexical regex ipuçları üretir; yorum/metin içinde eşleşme
olabilir, alias veya hesaplanan API çağrıları kaçabilir. Bu bir AST/data-flow
analizi değildir. Native host kaydı, mesaj doğrulaması, imza doğrulaması, efektif
yetkiler ve Windows ACL'leri sınanmaz. Dosya başlıkları yalnızca format ipucudur.
Tarama sırasında dosyaları başka bir süreçle değiştiren saldırgana karşı koruma
iddia edilmez. Yüksek risk bulunmaması güvenlik sertifikası değildir.

## Yapay zekâ kullanımı

Kod, testler, belgeler ve gerçek komut çıktılarını videoya dönüştüren yardımcı
betikler OpenAI Codex desteğiyle hazırlandı. Test ve demo sonuçları gerçekten
çalıştırılmış komutlardan elde edildi; sonuç üretilmiş/taklit edilmiş değildir.
AI katkısı ve aracın sınırları bu raporda açıkça belirtilmiştir.

Referanslar: [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging),
[Mozilla native manifests](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests).

## Güncel master ile birleştirme ve rezervasyon kaydı

PR #130, 13 Kasım 2026 tarihinde rezervasyon içeren ilk commit ile açılmıştır.
14 Kasım tarihli değerlendirme yorumundan sonra master'da başka öğrencinin
PENT-18 teslimi (#189), rezervasyonu ve görev raporu da merge edilmiştir.
Güncel master üzerine rebase sırasında bu öğrencinin tamamlanmış rezervasyonu,
raporu ve kodu korunmuştur. Bizim özgün rezervasyon kaydımız
[reservation.json](reservation.json) dosyasındadır; ortak
[reservations/PENT-18.json](../../../../reservations/PENT-18.json) notu da önce
açılmış PR #130'a ve bu kayda işaret eder. İki öğrencinin kaydı tek bir kişinin
adıyla değiştirilmemiştir; görev tahsisinin nihai değerlendirmesi ders hocasına aittir.

Bu rapor kökten görev/öğrenci klasörüne taşınmış, mevcut
[görev raporuna](../REPORT.md) bu teslimin bağlantısı eklenmiştir.
İlk video ve 13 Kasım doğrulama çıktıları kendi tarihlerindeki gerçek çalıştırmayı
göstermeye devam eder; rebase sonrası doğrulama ayrıca kaydedilir.

## 14 Kasım — rebase sonrası doğrulama

Güncel master (`33d703fc`) üzerine rebase tamamlandı. PENT-18 ve çakışması
çözülen web testleri birlikte **43 geçti**. Source Lab **176 geçti**; Cleanup
reference, OS-30, örnek analiz/rapor ve 77 shell betiği kontrolü geçti.
`lat check` de geçti; yeni master'daki bir uzun özet paragrafı yalnızca
bölünerek grafik biçim denetimi düzeltildi.

Tam runner'ın güncel özeti **5 başarılı aşama, 2 başarısız aşama, 3 atlama**.
Android tarafında üç macOS testi; Cleanup engine'de üç başarısızlık ve altı hata
var. Bunların tamamı değiştirilmemiş master kopyasında da yeniden üretildi.
Bu PR macOS/Cleanup işlevlerini veya ilgili testleri değiştirmiyor. Önceki
13 Kasım temiz test sonucu bu yeni master'ın temiz geçtiği iddiası değildir.

Yeni ham çıktılar ve master karşılaştırması:
[VERIFY-2026-11-14.md](VERIFY-2026-11-14.md). Yerel çalışma klasörü yolları
bu yeni kayıtta gizlilik için maskelenmiştir. Video 13 Kasım çalıştırmasını
göstermeye devam eder.
