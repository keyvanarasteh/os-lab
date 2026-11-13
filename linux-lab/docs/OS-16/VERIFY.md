# OS-16 — Doğrulama

Tüm komutları kendi Linux lab/VM'inizde, repo kökünden çalıştırın.
Python 3.11+ yeterlidir; script için pip paketi veya sudo gerekmez.

## Çalıştırma

```bash
python3 linux-lab/scripts/server_firstlook.py
python3 linux-lab/scripts/server_firstlook.py --json | python3 -m json.tool
```

Metin raporunda `SYSTEM`, `CPU (inxi)`, `MEMORY`, `LOCAL DISKS`, `SERVICES`
ve `COMMAND CHECKS` başlıkları görülür. JSON çıktısı başka bir metinle karışmaz;
`schema_version: 1`, `system`, `architecture_note`, `memory`, `disks`,
`services`, `checks` alanları bulunur. RAM ve disk boyutlarının birimi byte'tır.
Gerçek sayılar çalıştırılan makineye göre değişir.

Komut karşılaştırmaları:

```bash
uname -srm
free -b
df -P -k -l
systemctl --no-pager --plain list-units --type=service --all --no-legend
```

`system.architecture`, `uname` çıktısına eşit olmalıdır. JSON disk boyutu,
`df -k` değerinin 1024 katıdır. RAM değerleri canlı olduğundan arka arkaya
çalıştırmada küçük farklar normaldir. `services.failed` yalnızca listede
`active=failed` olan servisleri içerir; durdurulmuş `inactive` servisler başarısız
sayılmaz. systemd çalışmıyorsa `services: null` ve ilgili komutta `error` görülür.

`lsb_release` veya `inxi` kurulmamışsa `checks` içinde `missing` ve
`complete: false` beklenir; diğer bilgiler yine gösterilir. Paketler otomatik
kurulmaz. `complete`, veri toplamanın tamamlanmasını belirtir; sağlık onayı değildir.
Çıkış 0 rapor üretildiğini, çıkış 2 yanlış argümanı veya Linux dışı ortamı belirtir.

## Otomatik kontroller

```bash
python3 -m pytest android-lab/lab/tests/test_server_firstlook.py -q
./scripts/run-tests.sh
lat check
```

Testler sentetik komut çıktıları kullanır; ağı veya gerçek servisleri değiştirmez.
Beklenen OS-16 sonucu: `21 passed`. Repo runner'ı pytest yoksa `.venv-test`
oluşturabilir; o durumda ilk komutta `.venv-test/bin/python` kullanılabilir.
Eksik komut, timeout, izin hatası, bozuk çıktı, başarısız servis ve systemd'siz
ortam senaryoları test edilir. `lat` grafik denetleyicisidir; scriptin bağımlılığı değildir.

## Ubuntu labından paylaşılan sonuçlar (14 Kasım 2026)

Öğrencinin paylaştığı terminal kayıtlarında Ubuntu 26.04.1 LTS,
`7.0.0-30-generic` kernel ve `x86_64` mimarisi görülüyor. Metin raporu ve
JSON çalıştırıldı; ilk JSON çıktısı ayrıştırılarak geçerli olduğu doğrulandı.
İlk çalıştırmada `inxi` eksikti. Kurulumdan sonraki metin raporunda
`Collection: complete` ve altı komutun tamamında `ok` görüldü.

OS-16'nın kendi testleri aynı Ubuntu labında ayrıca çalıştırıldı:

```text
.venv-test/bin/python -m pytest android-lab/lab/tests/test_server_firstlook.py -q
21 passed in 0.02s
```

Bu sonuç, 14 Kasım 2026'da paylaşılan terminal çıktısıyla doğrulandı.

197 servis listelendi; `systemd-networkd-wait-online.service` başarısız olarak
gösterildi. `complete`, tüm verilerin toplandığı anlamındadır; başarısız servis
olmadığını söylemez. Bu bulgu raporun tespit ettiği lab durumudur.

İlk genel kontrolde Python 3.14 venv/ensurepip eksikliği test hazırlığını
engelledi. `python3.14-venv` kurulup ortam yeniden oluşturulduktan sonraki çıktı:

- Android/lab: **195 passed, 1 failed, 2 skipped**. Tek hata
  `test_web_ui.py::test_lab_start_requires_a_previewed_plan` (400/409).
  OS-16 dosyasıyla ilgili başarısız test listelenmiyor.
- Source Lab: **176 passed**; Cleanup reference: **35 test, OK**.
- Cleanup engine: **228 test; 4 failure, 5 error**; relocation ve safety testleri.
- Örnek analiz ve **71 kabuk scriptinin** sözdizimi kontrolü geçti.
- Cargo, lat ve dashboard kontrolleri ilgili araç/bağımlılıklar olmadığı için atlandı.
- Runner özeti: **4 passed, 2 failed, 3 skipped**. Bunlar kontrol aşaması
  sayılarıdır; tek tek test sayıları değildir. Genel kontrol henüz temiz değil.

Bu kayıtlar çalışan Linux labından metin kanıtıdır; 2–4 dakikalık video henüz yok.

## Ayrı geliştirme ortamı ve ana dal karşılaştırması

Linux x86_64 / Python 3.12 test ortamında metin ve JSON çalıştırıldı.
`uname`, `free`, `df` başarılı; `lsb_release` ve `inxi` kurulu değil;
systemd bağlantısı kullanılamıyor. Script bunları kısmi rapor olarak gösterdi.
Bu ortam testi, öğrencinin kendi VM videosunun yerine geçmez.

- OS-16: **21 test geçti**.
- Genel runner: Android/lab suite **190 geçti, 6 başarısız, 2 atlandı**;
  Source Lab **176 geçti**; 71 kabuk scriptinin sözdizimi ve örnek analiz geçti.
- Katkısız ana dal `5924675c` ile karşılaştırmada aynı 5 Android/lab hatası
  görüldü: üç Cleanup volume/privilege testi, Source merge-download (403),
  web-ui preview (400/409). Uygulama güncelleme testi tam koşuda ayrıca
  başarısız oldu; tek başına hem ana dalda hem katkı dalında tekrar geçiyor.
- Cleanup engine'de ana dalda da aynı **3 failure + 6 error** var
  (relocation / path handling). Bu katkının dosyalarıyla ilgili değiller.
- `lat check`: her iki dalda mevcut `lat.md/cleanup-lab.md` Dashboard pages
  özet paragrafı 250 karakter sınırını aşıyor. Değişen Linux düğümünde hata yok.
- Cargo ve dashboard bağımlılıkları kurulu olmadığından ilgili kontroller atlandı.

Dolayısıyla **genel runner tamamen temiz değil**. Mevcut repo/ortam sorunları
PR'da belirtilmeli; tüm testlerin geçtiği kutusu işaretlenmemelidir.

## Kanıt videosu (2–4 dakika)

1. GitHub'da `gozdekazma/os-lab` fork'unu ve kabul edilmiş rezervasyon
   [#113](https://github.com/keyvanarasteh/os-lab/pull/113) bağlantısını gösterin.
2. Linux lab terminalinde repoyu ve dalı gösterin:

   ```bash
   git clone --branch feat/server-firstlook https://github.com/gozdekazma/os-lab.git
   cd os-lab
   git remote -v
   git branch --show-current
   git log -5 --oneline
   ```

3. Metin ve JSON komutlarını çalıştırın. Mimari notunu, RAM/disk değerlerini
   ve varsa `missing`/systemd durumunu açıklayın; kısmi raporu tam rapor diye sunmayın.
4. OS-16 testlerini çalıştırıp sonucu gösterin. Genel test sonucunu da gösterin.
5. Kendi gözlemlerinizi `REPORT.md` kişisel değerlendirme kısmına ekledikten sonra
   gerçek bir commit ve push gösterin:

   ```bash
   git add linux-lab/docs/OS-16/REPORT.md
   git commit -m "docs(os-16): record personal lab verification"
   git push origin feat/server-firstlook
   ```

6. GitHub'da güncellenen commit'i ve uygulama PR'ını gösterin. Video bağlantısını
   PR açıklamasına ekleyip dersin Telegram kanalında paylaşın.



## Video sırasında doğrulama

Doğrulama zamanı: 2026-11-13 22:34:33 +0000
Metin ve JSON raporlarını video kaydı sırasında yeniden çalıştırdım. OS-16 için 21 testin tamamı geçti.
