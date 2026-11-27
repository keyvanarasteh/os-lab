# PENT-03 — Verification

- **Öğrenci:** Burak Özdemir · 2520191014
- **Ders:** MYO062 İleri Sızma Testi (Vize Seçenek 3 → PENT-03)
- **Kanıt Videosu (2–4 dk):** https://drive.google.com/file/d/1EkefgWf0mzZ19vQw48SmSnomJjOPKwCJ/view?usp=sharing

## Ortam

- Offline doğrulama: Linux konteyner, Python 3.13, pytest 9, openssl
- Cihaz/emülatör çalıştırması: `/dev/kvm` olan Linux host + Docker (budtmo/docker-android)
- Modül: `android-lab/lab/pent03/`

## Amaç

Boru hattının (1) doğru komutları ürettiğini ve yetki sınırını zorladığını offline,
deterministik olarak; (2) gerçek bir emülatörde uçtan uca çalışıp SSL pinning'i
objection/frida ile **arka planda** devre dışı bırakıp mitmproxy trafiğini okunur
hale getirdiğini canlı olarak doğrulamak.

## A. Offline doğrulama (bu depoda tekrar üretilebilir)

### A1 — Tam test takımı
```
$ cd android-lab/lab/pent03/tests && python3 -m pytest -q
79 passed in ~0.5s
```
**Sonuç:** PASS — 79/79.

### A2 — Kapsam muhafızı yetkisiz hedefi reddediyor (exit 2)
```
$ python3 scripts/scope.py --serial 192.168.1.50:5555 --package com.whatsapp
OUT OF SCOPE: refusing to act outside the authorized lab scope:
  - device '192.168.1.50:5555' is not a recognized lab emulator
  - package 'com.whatsapp' is not a lab-owned app
$ echo $?
2
```
**Sonuç:** PASS.

### A3 — Proxy enjeksiyonu reddediliyor
```
$ python3 -c "import sys;sys.path.insert(0,'scripts');import pipeline;pipeline.parse_proxy('10.0.2.2:8080;id')"
ValueError: proxy port must be a number in 1..65535, got '8080;id'
```
**Sonuç:** PASS.

### A4 — API 34+ CA yöntemi otomatik seçimi
```
$ python3 -c "import sys;sys.path.insert(0,'scripts');import install_ca as i;print(i.install_method_for_sdk(33), i.install_method_for_sdk(34))"
writable-system apex-tmpfs
```
**Sonuç:** PASS.

### A5 — Pipeline dry-run (arka plan unpinning dahil)
```
$ python3 scripts/pipeline.py com.securebank.mobile --dry-run
DRY RUN — pipeline for com.securebank.mobile on emulator-5554
  steps: scope -> boot -> frida -> ca -> proxy -> unpin
    deploy_frida.deploy('emulator-5554', version='16.5.9')
    install_ca.install('emulator-5554')
    adb -s emulator-5554 shell settings put global http_proxy 10.0.2.2:8080
    # started in the background (subprocess.Popen), held for --hold s, then stopped:
    objection -g com.securebank.mobile -S emulator-5554 explore --startup-command android sslpinning disable
```
**Sonuç:** PASS.

## B. Cihaz / emülatör ile uçtan uca çalıştırma

Aşağıdaki tek komut stack'i ayağa kaldırır ve boru hattını çalıştırır
(`/dev/kvm` olan bir host gerektirir). SSL unpinning adımı artık **arka planda**
`subprocess.Popen` ile başlatılır, `--hold` süresince açık tutulur
(mitmproxy'nin akışları yakaladığı pencere) ve sonunda sonlandırılır.

```
$ cd android-lab/lab/pent03
$ ./run.sh --docker com.securebank.mobile --proxy 10.0.2.2:8080 --hold 30 --report runs
```

Üretilen adım akışı (denetim raporu):
```
  [ok ] scope: emulator-5554 / com.securebank.mobile / 10.0.2.2
  [ok ] boot: emulator boot_completed
  [ok ] frida: frida-server 16.5.9 running
  [ok ] ca: mitmproxy CA at /apex/com.android.conscrypt/cacerts/<hash>.0
  [ok ] proxy: global http_proxy -> 10.0.2.2:8080
  [ok ] unpin: unpinning active in background (pid=…)
  [ok ] analysis: held unpinning session 30s for capture
  [ok ] teardown: stopped unpinning session (pid=…)
```

Bu uçtan uca çalıştırma, mitmproxy'de çözülen TLS akışlarıyla birlikte **kanıt
videosunda** (yukarıdaki link, 2–4 dk) kayıt altına alınmıştır. Çalıştırma JSON+MD
raporu `runs/` altına yazılır.

**Sonuç:** PASS (video ile kanıtlanmıştır).

## Özet

Offline kontrollerin tamamı (A1–A5) yeşil; cihaz/emülatör üzerindeki uçtan uca
çalıştırma (B) kanıt videosunda gösterilmiştir. Boru hattı doğru komutları üretir,
yetki sınırını kod düzeyinde zorlar ve unpinning oturumunu arka planda başlatıp
analiz penceresi boyunca sürdürüp sonlandırır.
