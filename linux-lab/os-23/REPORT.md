# MYO203 — OS-23 — dpkg envanteri ve dosya sahipliği

Öğrenci: Berat Kurşun (`Beratkursun`)  
Son güncelleme: 18 Kasım 2026  
Rezervasyon: https://github.com/keyvanarasteh/os-lab/pull/205  
Uygulama PR’ı: https://github.com/keyvanarasteh/os-lab/pull/208

## Problem ve çözüm

`dpkg -l`, `dpkg -L` ve `dpkg -S` çıktılarından paket durumlarını ve dosya sahiplerini elle okumak yerine Python standart kütüphanesiyle tek bir JSON arayüzü hazırlandı. Görev kapsamı `CONTRIBUTING.md` ve dashboard içindeki OS-23 kartının `linux-lab/scripts/dpkg_inventory.py` teslimine göre belirlendi.

- `-l`: ad, sürüm, mimari, açıklama, üç karakterli durum ve kurulu paket sayısı.
- `-L PACKAGE`: paketin veritabanında kayıtlı dosyaları; boşluklu yollar korunur.
- `-S /PATH`: tam yol eşleştirmesi, çoklu sahip ve mimari eki desteği.
- `--admindir`: ana sistem veritabanına dokunmadan bir kopya veya örnek üzerinde sorgu.

## Tasarım kararları

Komutlar argüman listesiyle çağrılır; shell kullanılmaz. Paket adlarında seçenek ve joker girişleri reddedilir. Dosya aramasında dpkg jokerleri kaçırılır, sonuç tam yolla karşılaştırılır. Dil `LC_ALL=C`, süre sınırı 20 saniyedir. Eksik komut, zaman aşımı veya bulunamayan paket/yol boş başarılı rapor olarak gösterilmez. İşlem hatası JSON ve çıkış 1, kullanım hatası argparse ve çıkış 2 verir.

Araç yerel paket metadatasını okur; root, ağ veya paket değiştirme işlemi gerektirmez. Dosya sahipliği kaydı dosyanın gerçekten mevcut veya değiştirilmemiş olduğunu kanıtlamaz. Symlink ve usr-merge yolları otomatik çevrilmez. Bakım betiklerinin oluşturduğu her dosya dpkg’de kayıtlı olmaz.

## Değişen alanlar ve doğrulama

- [Uygulama kodu](../scripts/dpkg_inventory.py)
- [11 birim testi ve 1 gerçek dpkg bütünleşme testi](../tests/test_dpkg_inventory.py)
- Kullanım: `linux-lab/README.md`; davranış: `lat.md/linux-lab.md`.
- [Gerçek sonuçlar ve sınırlamalar](VERIFY.md)

Göreve ait 12 test başarılıdır. Sentetik veritabanı bütünleşme testi ile canlı Ubuntu doğrulaması ayrı kanıtlardır. Debian temel sürüm karşılaştırmasında ortak hatalar ayrıca tekrarlandı; bütün ortak testlerin başarılı olduğu iddia edilmez.

## Kanıt ve teslim durumu

Ubuntu çalıştırmasına ait terminal ekranı transkripsiyonu [VERIFY.md](VERIFY.md) içindedir. Video ve çalışma günlükleri bu depoda tutulmaz; harici teslim bağlantısı burada doğrulanmamıştır.

## AI kullanım beyanı ve teslim durumu

Kod, test ve belgeler ChatGPT/Codex desteğiyle hazırlanmıştır. Bu belge hocanın kabulünü, PR’ın birleştirilmesini veya Blackboard gönderiminin tamamlandığını beyan etmez.
