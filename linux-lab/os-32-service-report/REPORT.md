# OS-32 System Audit & Service Health Report

## Amaç
Bu rapor, sistemdeki servislerin envanterini çıkarmak, `systemctl` kullanarak aktif ve etkinleştirilmiş servis durumlarını denetlemek ve hatalı (failed) servisleri tespit etmek amacıyla hazırlanmıştır.

## Gerçekleştirilen İşlemler
- `systemctl list-units --type=service --all` komutu ile tüm servislerin yüklenme, aktiflik ve alt durumları listelenmiştir.
- `systemctl list-unit-files` komutu ile servis dosyalarının başlangıç durumları (enabled/disabled) denetlenmiştir.
- `systemctl --failed` komutu ile sistemde hata veren servisler filtrelenmiştir.
- Python `subprocess` ve hata yakalama (`try-except`) blokları ile güvenli yürütme sağlanmıştır.
