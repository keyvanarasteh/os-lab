# PENT-02 · Automated Browser Extension Injection & Malicious Script Audit Engine

| | |
|---|---|
| Öğrenci | Yusuf Yılmaz (`yusufiyilmaz`) |
| Ders | MYO062 — vize projesi, seçenek 2 |
| Görev | [PENT-02](../../../CONTRIBUTING.md) · Rezervasyon: [`reservations/PENT-02.json`](../../../reservations/PENT-02.json) |
| Kanıt videosu | VIDEO_LINKI_BURAYA |

## 1. Amaç

Bazı tarayıcı eklentileri mağaza incelemesinden temiz geçer, kurulduktan sonra internetten kod
indirip çalıştırır (derste anlatılan iki aşamalı / "clean dropper" modeli). Bu araç bir eklentiyi
**kurmadan önce** inceler ve iki soruya cevap verir:

1. **Ne istiyor?** `manifest.json` içindeki izinler, eriştiği siteler ve CSP.
2. **Kodu ne yapıyor?** JavaScript dosyalarındaki `eval`, gizlenmiş `eval`, `Function`,
   `executeScript`, iframe/script ekleme, çerez okuma ve ağ istekleri.

Sonuç 0–100 arası bir risk puanı, bir not (low / medium / high / critical) ve dosya:satır
bilgisiyle bulgu listesidir.

## 2. Yapılanlar

| Dosya | Açıklama |
|---|---|
| [`scripts/analysis/ext_scan/manifest.py`](../../../scripts/analysis/ext_scan/manifest.py) | `manifest.json` okuma; MV2/MV3 izinleri, tüm siteler (`<all_urls>`), content script eşleşmeleri, CSP (`'unsafe-eval'`, uzak script) |
| [`scripts/analysis/ext_scan/patterns.py`](../../../scripts/analysis/ext_scan/patterns.py) | Kod tarayıcı: yorum silme, string birleştirme, string maskeleme ve 9 kural; iki korelasyon (iki aşamalı yük, çerez sızdırma); URL listesi |
| [`scripts/analysis/ext_scan/scanner.py`](../../../scripts/analysis/ext_scan/scanner.py) | Puan (yetenek ≤ 40 + davranış ≤ 60), not, metin rapor |
| [`scripts/analysis/ext_scan/__main__.py`](../../../scripts/analysis/ext_scan/__main__.py) | Komut satırı: `scan KLASÖR [--json] [--fail-on NOT]` |
| [`scripts/analysis/ext_scan/lab/`](../../../scripts/analysis/ext_scan/lab/) | Bu görev için yazılmış 3 zararsız örnek eklenti |
| [`scripts/analysis/ext_scan/tests/`](../../../scripts/analysis/ext_scan/tests/) | 38 pytest testi |
| [`scripts/run-tests.sh`](../../../scripts/run-tests.sh), [`lat.md/tooling.md`](../../../lat.md/tooling.md) | Testler runner'a ayrı aşama olarak eklendi; dokümantasyon |

### Kod nasıl taranıyor?

Düz metin araması iki hata yapar: yorumdaki `// eval(x)` için alarm verir, `self["ev" + "al"]`
gibi bölünmüş çağrıyı kaçırır. Bu yüzden her dosya önce temizlenir:

1. **Yorumlar silinir** (satır sonları korunur, böylece satır numaraları doğru kalır).
2. **Birleştirilmiş string'ler katlanır:** `"ev" + "al"` → `"eval"`.
3. **String içleri maskelenir:** `"eval kullanma"` gibi metinler kural aramasına girmez.

Sonra kurallar uygulanır. Aynı dosyada **ağ isteği + metinden kod çalıştırma** varsa
`CODE-TWO-STAGE` (critical), **çerez okuma + ağ isteği** varsa `CODE-COOKIE-EXFIL` (high) bulgusu
eklenir.

### Puan

`puan = yetenek (izinler, en fazla 40) + davranış (kod, en fazla 60)`. Bir kural dosyada kaç kez
geçerse geçsin bir kez sayılır. Notlar: low < 20 ≤ medium < 45 ≤ high < 70 ≤ critical.
Sadece izinlerle en fazla **medium** olunabilir; critical için tehlikeli kod gerekir.

## 3. Geliştirme sırasında karşılaşılan sorunlar

1. **İzinler kodu bastırıyordu.** İlk denemede yalnızca izinler puanlanınca aşırı izinli ama kodu
   zararsız `over-privileged` örneği 60 puan, gerçekten kod indirip çalıştıran `two-stage-loader`
   43 puan aldı. Yani araç yanlış eklentiyi daha tehlikeli gösteriyordu. Çözüm: izin puanına 40
   tavan kondu, kod davranışı ayrı (en fazla 60) sayıldı. Test:
   `test_permissions_alone_cannot_reach_critical`.
2. **Yorum ve metinlerde yanlış alarm.** `clean-notes` örneğinin yorumunda ve bir string'inde
   bilerek `eval(` geçiyor. Basit aramayla bu temiz eklenti bulgu üretiyordu; yorum silme ve string
   maskeleme ile 0 bulguya indi. Test: `test_no_false_alarm` (5 durum).
3. **PowerShell 5.1'de `&&` yok.** Windows PowerShell 5.1'de `cd ... && python ...` satırı parse
   hatası verdi; README'deki komutlar tek tek verilecek şekilde yazıldı.

## 4. Lab örnekleri ve sonuçlar

Örneklerin hepsi bu görev için yazıldı, üçüncü taraf kod yok. "Zararlı" davranışlar yalnızca
`127.0.0.1:8765` adresini gösterir; orada bir sunucu çalışmadığı sürece hiçbir şey gönderilmez.

| Örnek | İçerik | Sonuç |
|---|---|---|
| `clean-notes` | Not defteri, sadece `storage`; yorum ve string içinde `eval(` | **0 / LOW**, 0 bulgu |
| `over-privileged` | Sekme sayacı; `<all_urls>`, `cookies`, `history`, `nativeMessaging`, `tabs` | **40 / MEDIUM** (40 + 0) |
| `two-stage-loader` | Alarmdan sonra `fetch(LAB + "/stage2.js")` → `self["ev" + "al"](payload)`, çerez adları → `/collect`, gizli iframe | **100 / CRITICAL** (40 + 60) |

`two-stage-loader` çıktısı:

```
Lab Coupon Finder 1.0.0 (MV3)
Risk: 100/100  CRITICAL   (capability 40/40, behaviour 60/60)

  [CRITICAL] CODE-HIDDEN-EVAL     sw.js:14               hidden eval: called through a string name like self['ev'+'al']
  [CRITICAL] CODE-TWO-STAGE       sw.js:14               downloads data and runs code from text in the same file (two-stage payload, 'clean dropper')
  [HIGH    ] PERM-ALL-SITES       manifest.json          runs on every website (<all_urls>)
  [HIGH    ] PERM-COOKIES         manifest.json          permission 'cookies': can read session cookies (account takeover)
  [HIGH    ] CODE-COOKIE-EXFIL    sw.js:17               reads cookies and sends network requests in the same file (possible exfiltration)
  [MEDIUM  ] CODE-IFRAME-INJECT   inject.js:3            creates an iframe inside the page
  [MEDIUM  ] PERM-SCRIPTING       manifest.json          permission 'scripting': can inject code into web pages
  [MEDIUM  ] CODE-COOKIE-READ     sw.js:17               reads cookies

Endpoints:
  http://127.0.0.1:8765
  http://127.0.0.1:8765/frame.html
```

## 5. Doğrulama

```powershell
cd scripts\analysis
python -m ext_scan scan ext_scan\lab\clean-notes
python -m ext_scan scan ext_scan\lab\over-privileged
python -m ext_scan scan ext_scan\lab\two-stage-loader
python -m ext_scan scan ext_scan\lab\two-stage-loader --fail-on high   # çıkış kodu 3
python -m pytest ext_scan\tests -q
```

### Test sonuçları

`ext_scan/tests`: **38 passed** (Windows 11, Python 3.14). Kapsam: temizleme adımları, her kural
için pozitif örnek, 5 yanlış alarm durumu, iki aşamalı ve sızdırma korelasyonu, satır numarası,
MV2/MV3 izinleri, CSP'nin iki biçimi, bozuk/eksik/BOM'lu manifest, lab örneklerinin beklenen
puanları ve CLI çıkış kodları.

`./scripts/run-tests.sh --no-venv` (Windows 11, Git Bash):

```
[ok]   scripts/analysis/ext_scan test suite          38 passed
[ok]   sample analysis + report generated
[ok]   all 70 shell scripts parse
[fail] android-lab/lab test suite                   7 failed, 204 passed
[fail] source-lab/engine test suite                 4 failed, 171 passed
[fail] cleanup-lab/reference/python                 2 failed, 6 errors / 35
[fail] cleanup-lab/engine                           49 failed, 37 errors / 228
[fail] cleanup-lab/reference/qrust-scan             build script blocked
[skip] lat check, dashboard                         araçlar kurulu değil
```

Bu PR'ın yeni aşaması temiz geçiyor. Kalan kırmızı aşamalar bu değişiklikten bağımsız: PR o
klasörlerde hiçbir dosyaya dokunmuyor (dışarıda değişen yalnızca `scripts/run-tests.sh`'e eklenen
aşama ve `lat.md/tooling.md`). Hatalar Windows hostuna özgü: macOS/Linux yolları, sembolik link
izni ve Rust derleme betiğinin Windows Akıllı Uygulama Denetimi tarafından engellenmesi
(`os error 4551`). Linux'ta çalıştırma imkânım olmadı (WSL dağıtımı ve Docker kurulu değil).

## 6. Sınırlamalar

- **Yalnızca statik analiz.** Görev tanımındaki dinamik (çalıştırarak) analiz bu sürümde yok;
  araç kodu çalıştırmadan okur.
- **Korelasyon dosya düzeyinde.** `fetch` ve `eval` aynı dosyadaysa iki aşamalı sayılır; verinin
  gerçekten `fetch`'ten `eval`'e aktığı izlenmez. Ağ isteği ve `eval` farklı dosyalara bölünürse
  korelasyon kaçar (tekil `CODE-EVAL` / `CODE-HIDDEN-EVAL` bulguları yine görünür).
- **Tam bir JavaScript parser değil.** Regex literal'leri ve yoğun obfuscation (string dizileri,
  `\x65val` kaçışları) kısmen anlaşılır.
- Paketlenmiş `.crx` / `.zip` dosyaları değil, açılmış eklenti klasörü taranır.

## 7. Yapay zekâ kullanım beyanı

Kod, testler ve bu rapor Anthropic'in Claude modeli (Claude Code) ile birlikte yazıldı. Claude
kodu adım adım yazıp açıkladı; görev seçimi, adımların sırası, her adımda kodun çalıştırılıp
sonuçların kontrol edilmesi, commit'ler ve kanıt videosu bana ait. Bütün çıktılar testlerle ve
lab örnekleri üzerinde elle çalıştırılarak doğrulandı.
