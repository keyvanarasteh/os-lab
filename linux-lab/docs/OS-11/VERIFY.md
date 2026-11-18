# OS-11 — Doğrulama

Python 3.11+ ve Linux lab/VM gerekir; araç yalnızca standart kütüphaneyi
kullanır. Sudo, paket kurulumu, ağ erişimi veya otomatik dosya değişikliği yoktur.

## Örnek alıştırma yapısı

Roadmap `ali/eda/aleyna`, `odevler/sinavlar/sunumlar/puan.txt` adlarını verir;
tam bir ders klasör ağacı yayımlamaz. Bu aracın açıkça tanımlanan örnek profili:
her öğrenci klasöründe üç alt klasör ve bir `puan.txt` dosyasıdır.
Bu profil, dersin yayımlanmamış birebir ağacı veya resmi notlandırması değildir.

```text
ali/     eda/     aleyna/   (üç ayrı öğrenci klasörü)
Her birinin içinde:
  odevler/   (klasör)
  sinavlar/  (klasör)
  sunumlar/  (klasör)
  puan.txt  (normal dosya)
```

Toplam 15 yol kontrol edilir. Fazladan dosyalar kabul edilir. `puan.txt`
içeriği okunmaz ve puan değeri değerlendirilmez; boş dosya geçerlidir.
Eksik/yanlış tür/erişilemeyen yollar başarısızdır. Sembolik bağlantılar kabul
edilmez; öğrenci klasörlerinin içindeki bağlantılar takip edilmez.
Kök yolunun üst bileşenleri işletim sistemi tarafından normal çözülür;
kendi lab klasörünüzü kullanın. Denetim anlık kontroldür, eşzamanlı dosya
değişikliklerine karşı bütün ağacın atomik görüntüsü değildir.

## Çalıştırma ve beklenen sonuçlar

Repo kökünde aşağıdaki komutları aynı terminal oturumunda çalıştırın:

```bash
python3 linux-lab/exercises/shell_basics_check.py --show-exercise
os11_lab=$(mktemp -d /tmp/os11-demo.XXXXXX)
for student in ali eda aleyna; do
  mkdir -p "$os11_lab/$student/odevler" "$os11_lab/$student/sinavlar" "$os11_lab/$student/sunumlar"
  touch "$os11_lab/$student/puan.txt"
done
python3 linux-lab/exercises/shell_basics_check.py "$os11_lab"
echo "Cikis kodu: $?"
python3 linux-lab/exercises/shell_basics_check.py "$os11_lab" --json
echo "Cikis kodu: $?"
```

Beklenen: 15 PASS, `Sonuc: 15/15 dogru`, çıkış 0. JSON'da `success: true`,
`passed: 15`, `total: 15` ve 15 sonuç vardır. Bu komutlardaki `mkdir`/`touch`
örneği kullanıcı oluşturur; denetleyicinin kendisi hiçbir dosya oluşturmaz.

Eksik dosyayı silmeden, yeniden adlandırarak gösterin:

```bash
mv "$os11_lab/eda/puan.txt" "$os11_lab/eda/puan-yedek.txt"
python3 linux-lab/exercises/shell_basics_check.py "$os11_lab"
echo "Cikis kodu: $?"
mv "$os11_lab/eda/puan-yedek.txt" "$os11_lab/eda/puan.txt"
python3 linux-lab/exercises/shell_basics_check.py "$os11_lab"
echo "Cikis kodu: $?"
```

Eksikken 14/15, `eda/puan.txt` için FAIL ve `touch` ipucu, çıkış 1;
geri getirince 15/15 ve çıkış 0 beklenir. Geçersiz/erişilemeyen kök veya
yanlış argüman çıkış 2 verir. İpuçları çalıştırılmaz, sadece gösterilir.

Etkileşimli kullanım: `python3 linux-lab/exercises/shell_basics_check.py --interactive`.
Sorulduğunda alıştırmanın kök yolunu yazın. JSON ile etkileşimli mod birlikte
kullanılmaz; JSON çıktısına giriş istemi karışmaz.

## Testler

```bash
python3 -m venv .venv-test
.venv-test/bin/python -m pip install pytest
.venv-test/bin/python -m pytest android-lab/lab/tests/test_shell_basics_check.py -q
./scripts/run-tests.sh
```

15 Kasım 2026 geliştirme ortamı: OS-11 **23 passed in 0.04s**.
Gerçek geçici dizinlerle metin/JSON tam yapı çıkış 0; eksik dosya 14/15 ve
çıkış 1 ayrıca doğrulandı. Bu sonuç öğrencinin VM/video kanıtı değildir.
Testler eksik yolları, türleri, bağlantıları, FIFO'yu, erişim hatasını,
JSON/CLI/etkileşimli modu, ASCII çıktıyı ve değişiklik yapılmamasını kapsar.

Genel kontrol (`bash scripts/run-tests.sh --no-venv`, mevcut test venv'i PATH'te):
6 aşama geçti, 2 aşama başarısız, 3 aşama atlandı. Android testleri
479 passed / 9 failed / 4 skipped; cleanup engine 4 failure / 7 error verdi.
Aynı ortamda, değişikliksiz `6f7d517bb51e9d52f59d20ef4215dbcac274987d`
üzerinde `--quick --no-venv` ile aynı 9 Android başarısız testi ve aynı
cleanup engine hata/test adları tekrarlandı (Android: 456 passed).
Dolayısıyla genel kontrol temiz değildir; OS-11'in eklediği 23 test geçer.
Source testleri, cleanup reference, OS-30, örnek analiz ve 83 kabuk dosyasının
sözdizimi kontrolü geçti. Cargo/dashboard bağımlılıkları eksik olduğundan
ilgili aşamalar atlandı. `lat check` ayrıca çalıştırıldı ve geçti.
Öğrencinin VM'inde genel kontrol tekrar çalıştırılmalı; bu kayıt başarı iddiası
ile değiştirilmemelidir.

## Kanıt videosu — henüz eklenmedi

2–4 dakikalık kayıtta fork'u, kabul edilmiş rezervasyon #264'ü, çalışma dalını,
15/15 → 14/15 → 15/15 akışını, JSON'u ve 23 test sonucunu gösterin.
Ardından gerçek bir belge değişikliğinin commit/push adımlarını ve uygulama
PR'ını gösterin. Çalıştırmadan test başarısı veya kişisel deneyim yazmayın.
Video bağlantısını uygulama PR'ına ve ders Telegram grubuna ekleyin.

## Ubuntu lab dogrulamasi

15 Kasim 2026: feyzaozoglu Ubuntu hesabinda OS-11 testleri 23 passed verdi. Tam yapi 15/15 (cikis 0), eksik dosya 14/15 (cikis 1), duzeltme sonrasi 15/15 (cikis 0) olarak dogrulandi. JSON success=true verdi. Genel --quick kontrolu 4 asama basarili, 2 basarisiz, 1 atlandi sonucunu verdi; genel test cikis kodu 1 idi.
