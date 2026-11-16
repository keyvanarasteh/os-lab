# PENT-05 — Binary Exploitation & Hardening Verification Harness

- **Öğrenci:** Tuğba Soğanlı · 2520191023 (GitHub: niltuvba-dotcom)
- **Ders:** MYO062 İleri Sızma Testi (Vize -> PENT-05)
- **Pull Request:** https://github.com/keyvanarasteh/os-lab/pull/284 (rezervasyon: https://github.com/keyvanarasteh/os-lab/pull/283)
- **Demo (GIF, Claude tarafından hazırlanmış otomatik demo):** https://github.com/keyvanarasteh/os-lab/pull/284#issuecomment-6903162572
- **Kanıt Videosu (öğrenci kaydı, 2-4 dk):** eklenecek

## 1. Amaç ve Kapsam

Bir ELF ikilisinin bellek bozulması saldırılarına karşı hangi derleyici/linker
korumalarıyla derlendiğini `readelf` ile otomatik denetleyen bir araç ve AFL++
fuzzing sonucunda çıkan crash'leri tekrar oynatıp benzersiz gruplara ayıran bir
triage aracı geliştirilmiştir.

| Koruma | Neyi engeller | Nasıl tespit edilir |
|---|---|---|
| NX | Yığına yazılan shellcode'un çalışmasını | `GNU_STACK` segmenti `RWE` değil |
| PIE | Kod adreslerinin önceden bilinmesini (ROP) | ELF tipi `DYN` + `INTERP` |
| Stack canary | Dönüş adresinin fark edilmeden ezilmesini | `__stack_chk_fail` sembolü |
| Full RELRO | GOT girdilerinin üzerine yazılmasını | `GNU_RELRO` + `BIND_NOW` |
| FORTIFY | Bilinen boyutlu tamponlarda taşmayı (bilgi) | `__*_chk` sembolleri |
| ASLR (sistem) | Bellek düzeninin tahmin edilmesini | `randomize_va_space` = 2 |

## 2. Geliştirilen Dosyalar

- `linux-lab/scripts/pent-05-hardening-audit.sh`: Bir veya birden çok ELF için
  NX, PIE, canary, RELRO ve FORTIFY durumunu ve sistem ASLR seviyesini raporlar.
  Eksik her koruma için derleme bayrağı önerir. `--json` destekler. Çıkış kodu
  0 = sağlam, 1 = zayıf, 2 = hata.
- `linux-lab/scripts/pent-05-afl-triage.sh`:
  - `fuzz`: hedefi `afl-cc` + ASAN ile derler, `afl-fuzz -V N` çalıştırır ve
    crash'leri triage eder. AFL++ yoksa `[skip]` verir.
  - `triage`: crash dizinindeki girdileri yeniden oynatır, ASAN hata türü + üst
    iki çerçeve, sinyal, hang veya no-crash olarak gruplar.
- `linux-lab/pent-05/hedef.c`: Üç bilinçli crash yolu olan lab hedefi (strcpy
  stack overflow, NULL yazımı, sıfıra bölme).
- `linux-lab/pent-05/Makefile`: Aynı kaynaktan `hedef-weak` (tüm korumalar
  kapalı) ve `hedef-hardened` (tüm korumalar açık) üretir. `make audit`,
  `make fuzz` hedefleri vardır. `seeds/` AFL için başlangıç girdileridir.
- `linux-lab/tests/pent05_test.sh` + `linux-lab/tests/test_pent05.py`: Sahte
  `readelf` ve sahte crash hedefiyle çalışan 28 çevrimdışı test. `test_pent05.py`,
  `scripts/run-tests.sh` içindeki linux-lab unittest aşamasında otomatik çalışır.
- `linux-lab/tests/fixtures/pent05/`: Gerçekçi `readelf` çıktıları (weak,
  hardened, partial RELRO, paylaşımlı kütüphane).
- `lat.md/linux-lab.md`: PENT-05 bölümü.
- `reservations/PENT-05.json`: Görev rezervasyonu.

## 3. Kullanım

```bash
cd linux-lab/pent-05
make                      # hedef-weak ve hedef-hardened derlenir
make audit                # ikisini karşılaştırmalı denetler
../scripts/pent-05-hardening-audit.sh --json /usr/bin/ls
make fuzz                 # AFL++ kuruluysa 60 sn fuzz + triage
```

## 4. Doğrulama ve Test Çıktıları

- Çalıştırılan komut: `bash linux-lab/tests/pent05_test.sh`
- Sonuç: `PENT-05: 41 geçti, 0 başarısız, 4 atlandı` (atlanan 4 test python3/jq ile JSON doğrulaması; bu makinede yoktu, Linux CI'da çalışır)
- `linux-lab/tests/test_pent05.py`: bash suite'ini çalıştırır ve her iki aracın `--json` çıktısını `json.loads` ile doğrular

<!-- Linux'ta make audit ve make fuzz çıktısını buraya yapıştırın -->

## 5. Sınırlamalar

- Canary tespiti sembole dayanır. Hiç dizi içermeyen bir program
  `-fstack-protector-strong` ile derlense bile `__stack_chk_fail` içermeyebilir.
- Statik ve strip edilmiş ikililerde sembol tabanlı kontroller (canary, FORTIFY)
  sonuç veremeyebilir.
- Kabuk, 128 üzeri normal bir çıkış kodunu sinyalden ayıramaz; bu durum `signal:` olarak raporlanır (ASAN `abort_on_error=1` ile crash'ler zaten sinyaldir).
- Triage gruplaması üst iki çerçeveye dayanır. Aynı hatanın farklı çağrı
  yollarından gelmesi ayrı bucket oluşturabilir.

## 6. Etik Not

`hedef.c` bilinçli olarak zafiyetlidir ve yalnızca lab içindir. Araçlar
yalnızca sahibi olunan veya test izni bulunan ikililerde kullanılmalıdır.
