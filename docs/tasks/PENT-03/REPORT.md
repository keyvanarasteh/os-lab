# PENT-03 — Headless Android Analysis Pipeline & Objection SSL Pinning Bypass

- **Öğrenci:** Burak Özdemir · 2520191014
- **Ders:** MYO062 İleri Sızma Testi (Vize Seçenek 3 -> PENT-03)
- **Pull Request:** https://github.com/keyvanarasteh/os-lab/pull/261
- **Kanıt Videosu (2-4 dk):** https://drive.google.com/file/d/1EkefgWf0mzZ19vQw48SmSnomJjOPKwCJ/view?usp=sharing

## 1. Amaç ve Kapsam

PENT-03 görevi, bir Android uygulamasının TLS trafiğini uçtan uca analiz edebilmek
için **başsız (headless), konteynerleştirilmiş** bir çalıştırma hattı (pipeline)
gerektirir. Geliştirilen modül, mevcut `android-lab` üzerine **çakışmadan** eklenen,
kendi içinde kapsüllenmiş bir PENT-03 paketidir (`android-lab/lab/pent03/`) ve şunları
otomatikleştirir:

1. **Kapsam (scope) denetimi** — yalnızca yetkili lab emülatörü/paketi hedeflenir.
2. **frida-server dağıtımı** — cihaz ABI'si tespit edilir, uygun `frida-server`
   indirilip push edilir ve root olarak başlatılır.
3. **mitmproxy system CA kurulumu** — sertifika Android **system** güven deposuna
   yazılır; Android 7–13 için writable-`/system`, **Android 14 / API 34+** için
   Conscrypt-APEX `tmpfs` overlay yöntemi otomatik seçilir.
4. **Cihaz proxy yönlendirmesi** — global `http_proxy` mitmproxy'ye yönlendirilir.
5. **objection ile universal SSL pinning bypass** — `android sslpinning disable`;
   objection yoksa paketlenmiş Frida hook'una düşülür.

> **Yalnızca yetki dahilinde.** Tüm araçlar yalnızca sahibi olunan veya yazılı izinle
> test edilen emülatör/uygulamaları hedefler; `scope.py` bunu kod düzeyinde zorunlu kılar.

## 2. Geliştirilen Dosyalar

Tümü `android-lab/lab/pent03/` altında, standart kütüphane ağırlıklı ve offline test edilebilir:

- `scripts/scope.py` — yetki/kapsam muhafızı (lab serial/paket/proxy host allowlist'i).
- `scripts/adb.py` — test edilebilir adb sarmalayıcı (argv üreticiler + boot bekleme + ABI/SDK).
- `scripts/deploy_frida.py` — ABI→arch eşleme, sürüm çözümleme, indirme/xz açma, push+başlatma.
- `scripts/install_ca.py` — SDK'ya göre CA kurulumu (writable-system / **APEX tmpfs overlay**).
- `scripts/sslpinning_bypass.py` — objection sürücüsü + Frida universal unpinning fallback.
- `scripts/pipeline.py` — `scope → boot → frida → ca → proxy → unpin` orkestrasyonu (`--dry-run`, `--report`).
- `scripts/report.py` — çalıştırma başına JSON + Markdown denetim raporu.
- `scripts/mitm_addon.py` — mitmproxy trafik loglama addon'u.
- `hooks/ssl-pinning-universal.js` — Conscrypt/OkHttp/NSC/WebView/HostnameVerifier unpinning.
- `hooks/root-bypass.js`, `hooks/method-trace.js` — root gizleme ve genel metod izleme.
- `docker/` — Alpine controller imajı + emülatör + mitmproxy compose yığını.
- `tests/` — 65 offline test (cihaz/ağ/openssl mock'lu).
- `reservations/PENT-03.json` — MYO062 vize seçenek 3 notu ile `pr-open` durumunda rezervasyon.

## 3. Doğrulama ve Test Çıktıları

**Kapsam muhafızı yetkisiz hedefi reddediyor:**
```
$ python3 scripts/scope.py --serial 192.168.1.50:5555 --package com.whatsapp
OUT OF SCOPE: refusing to act outside the authorized lab scope:
  - device '192.168.1.50:5555' is not a recognized lab emulator
  - package 'com.whatsapp' is not a lab-owned app
# çıkış kodu = 2
```

**Pipeline dry-run — cihazda çalışacak tam komutlar:**
```
$ python3 scripts/pipeline.py com.securebank.mobile --dry-run
DRY RUN — pipeline for com.securebank.mobile on emulator-5554
  steps: scope -> boot -> frida -> ca -> proxy -> unpin
    deploy_frida.deploy('emulator-5554', version='16.5.9')
    install_ca.install('emulator-5554')
    adb -s emulator-5554 shell settings put global http_proxy 10.0.2.2:8080
    objection -g com.securebank.mobile -S emulator-5554 explore --startup-command android sslpinning disable
```

**API 34+ CA yöntemi otomatik seçimi:**
```
$ python3 -c "import install_ca as i; print(i.install_method_for_sdk(33), i.install_method_for_sdk(34))"
writable-system apex-tmpfs
```

**Tam offline test takımı:**
```
$ ./run-tests.sh                # (veya: cd tests && python3 -m pytest -q)
75 passed in ~0.8s
```

Statik analiz (`pyflakes`) temiz; Bash scriptleri `bash -n` ile doğrulandı.

## 6. Kod İnceleme ve Sertleştirme (review hardening)

PR üzerindeki otomatik inceleme (Sourcery) 30 bulgu üretti ve tamamı ele alındı.
Öne çıkan güvenlik/doğruluk düzeltmeleri:

- **Komut enjeksiyonu:** `--proxy` artık katı `host:port` olarak doğrulanıyor
  (`parse_proxy`); port numerik 1–65535 ve host scope içinde olmalı — `adb shell`
  komutuna kabuk metakarakteri geçemiyor.
- **Path traversal:** paket kimliği katı Android app-id desenine zorlanıyor ve
  rapor dosya adları sanitize ediliyor; `..`/`/` içeren değerler reddediliyor.
- **Scope daraltması:** geniş `com.example.` ön eki kaldırıldı, proxy host'u tam
  eşleşme (alt ağ güvenilmiyor), boş/eksik serial reddediliyor (`require_serial`).
- **Root doğrulama:** `adb root` sonrası gerçek root (uid 0) teyidi; değilse hata.
- **API 34 overlay:** kritik mount/cp adımları artık hata kontrollü, overlay
  zygote namespace'ine de uygulanıyor, ve "reboot" yanıltıcı mesajı düzeltildi
  (tmpfs reboot'ta kaybolur).
- **Docker:** portlar yalnızca `127.0.0.1`'e bağlı, `privileged` kaldırıldı
  (yalnız `/dev/kvm`), mitmproxy CA volume'u gerçek yoluna (`/home/mitmproxy`)
  taşındı, build-context/yol uyumsuzlukları giderildi, frida istemci sürümü
  sunucuyla sabitlendi.
- **Frida hook'ları:** `File.exists` recursion'ı, `Runtime.exec` substring/dizi
  overload kaçakları, RootBeer tekil kontrolleri, NSC `checkServerTrusted`
  zincir dönüşü ve WebView alt sınıf kapsaması düzeltildi.
- **Dayanıklılık:** ağ hataları `FridaDeployError`'a sarmalanıyor; başarısızlıkta
  bile kısmi denetim raporu yazılıyor; rapor dosya adlarına benzersiz ek eklendi.

Düzeltmelerden sonra offline test takımı **75 test** ile yeşil.

## 4. Mimari ve Çalışma Akışı

Hafif bir **Alpine controller** konteyneri, ayrı bir **Android emülatör** konteynerini
adb üzerinden sürer; trafik **mitmproxy** üzerinden geçer ve SSL pinning devre dışı
bırakılarak okunur hale gelir. Controller emülatörü kendisi çalıştırmaz (KVM gerekmez);
yalnızca emülatör konteyneri `privileged` + `/dev/kvm` ister. `frida-server` çalışma
anında cihaz ABI'si için indirilir — depoya ikili dosya konmaz.

## 5. Güvenlik ve Yetki Sınırı

Saldırgan güvenlik araçları olduğu için yetki sınırı **kodda** zorunlu kılınmıştır:
`scope.assert_in_scope()` her yıkıcı/ağ işleminin önünde çağrılır ve lab dışı bir
serial, paket veya proxy host'u reddeder. Kapsam, bilinen bir lab için ortam
değişkenleriyle (`OSLAB_EXTRA_*`) kod değiştirmeden genişletilebilir.
