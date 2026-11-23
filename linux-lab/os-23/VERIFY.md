# OS-23 — Doğrulama ve gerçek test sonuçları

Öğrenci: Berat Kurşun (`Beratkursun`)  
Son güncelleme: 18 Kasım 2026

## Tekrar çalıştırma komutları

Depo kökünden:

```bash
cat /etc/os-release
python3 --version
python3 linux-lab/scripts/dpkg_inventory.py -l
python3 linux-lab/scripts/dpkg_inventory.py -L dpkg
python3 linux-lab/scripts/dpkg_inventory.py -S /usr/bin/dpkg
python3 linux-lab/tests/test_dpkg_inventory.py
./scripts/run-tests.sh --quick
```

Bu komut bloğu çalıştırma talimatıdır; aşağıdaki sonuçlar kanıtın elde edildiği ortama göre ayrılmıştır.

## Video ve çalışma günlükleri

Uygulama videosu ve çalışma günlükleri bu depoya eklenmemiştir. Bu rapor, 14 Kasım tarihli terminal ekranı transkripsiyonunu sunar.

## 14 Kasım 2026 — öğrencinin Ubuntu ekran kanıtları

### Görev testleri — 18:57

```text
Ran 12 tests in 0.331s
OK
ubuntu@ubuntu:~/os23-teslim$
```

Bu ekran OS-23 testlerinin Ubuntu terminalinde başarılı olduğunu gösterir. O koşunun commit kimliği tek başına bu ekrandan belirlenemez.

### Ortak test — 19:06 ve 19:08

```text
Ran 228 tests in 1.295s
FAILED (failures=4, errors=5)
[fail] cleanup-lab/engine
[skip] cargo not installed; qrust-scan tests not run

Ran 116 tests in 40.870s
OK
[ok] linux-lab/tests (OS-30 hardening)

--quick: skipping remaining stages
== Summary ==
2 passed, 4 failed, 1 skipped
```

Ortak komut başarısızdır. Cleanup ekranında platform seçimi, relocation ve app-running denetimleriyle ilgili hatalar görülür. Ubuntu’daki dört başarısız süitin tümünü belirlemek için tam günlük mevcut değildir. Ubuntu başarısızlıklarının tamamının temel sürüm kaynaklı olduğu iddia edilmez.

## Debian ortamında uygulama ve temel sürüm karşılaştırması

Ortam: Debian 13, x86_64, Python 3.12.14. Bu sonuçlar öğrencinin Ubuntu koşusundan ayrıdır.

```bash
python3 -m pytest linux-lab/tests/test_dpkg_inventory.py -q
```

Sonuç: **12 başarılı test**. Bunların 11’i çevrimdışı birim testi, biri geçici sentetik veritabanı kullanan gerçek dpkg bütünleşme testidir. Sentetik test ana sistemin paket veritabanını değiştirmez ve canlı Ubuntu testinin yerine geçmez.

Upstream `33d703fc` ile birleştirme sonrası ortak koşu: **3 süit başarılı, 2 başarısız, 1 atlandı**. Android süiti temel sürümde 368 başarılı / 8 başarısız / 4 atlandı; OS-23 katkısıyla 380 başarılı / aynı 8 başarısız / 4 atlandı sonucunu verdi. Cleanup süitinde 3 başarısızlık ve 6 hata raporlandı. Source süiti 176, OS-30 süiti 116 başarılı test verdi; cleanup reference süitinde 35 test başarılıydı. Cargo bulunmadığı için Rust testleri atlandı.

`lat check`, temel sürümde de bulunan cleanup-lab paragraf uzunluğu hatasını bildirdi. Bu karşılaştırmalar belirtilen temel sürüm ve Debian ortamıyla sınırlıdır; bütün ortak testlerin başarılı olduğu anlamına gelmez.

## Teslim durumu ve sınırlamalar

- Uygulama, görev testleri ve raporlar GitHub’dadır. Video veya çalışma günlüğü bu depoda bulunmaz; harici teslim durumu doğrulanmamıştır.
- [Pull Request #208](https://github.com/keyvanarasteh/os-lab/pull/208)
- Ubuntu ortak testlerinin tam günlüğü ve o koşunun commit kimliği mevcut değildir.
- Öğretim üyesinin kabulü, PR’ın birleştirilmesi veya Blackboard gönderiminin tamamlandığı iddia edilmez.
- Kod, test ve belgeler ChatGPT/Codex desteğiyle hazırlanmıştır.
