# VERIFY: OS-04 Auth Log Audit

Bu doğrulama, Ubuntu Server lab VM'inde (VirtualBox) ve `os-lab` deposunun kök dizininde çalıştırılır.

## Gereksinimler
- `bash`, `python3` (3.8+; standart kütüphane yeterli, ek paket yok)
- `/var/log/auth.log` okumak için `sudo` (örnek log ile `sudo` gerekmez)

## 1) Otomatik test (örnek log ile, ağ/sudo gerekmez)

    ./linux-lab/scripts/auth-audit/tests/test-auth-audit.sh

Beklenen çıktının sonu:

    passed: 19  failed: 0

## 2) JSON çıktısı (varsayılan)

    ./linux-lab/scripts/auth-audit/auth-audit.sh --file linux-lab/scripts/auth-audit/tests/fixtures/auth.log.sample

Beklenen (özet): `"failed_logins": 8`, `"unique_ips": 3`, `suspicious_ips` içinde yalnızca `203.0.113.50` (5 deneme), `"sudo_violations": 4`. Çıkış kodu `1`.

## 3) Okunabilir özet

    ./linux-lab/scripts/auth-audit/auth-audit.sh --file linux-lab/scripts/auth-audit/tests/fixtures/auth.log.sample --summary

Beklenen:

    Source: linux-lab/scripts/auth-audit/tests/fixtures/auth.log.sample   Threshold: 4
    Failed SSH logins: 8 from 3 IP(s)

    IP                                       ATTEMPTS  STATUS      USERS
    203.0.113.50                                    5  SUSPICIOUS  admin,root,test,ubuntu
    198.51.100.7                                    2  normal      ubuntu
    192.0.2.10                                      1  normal      ubuntu

    Unauthorized sudo attempts: 4
      guest: not in sudoers (1)
      ubuntu: incorrect password (3)

## 4) Eşik değiştirme

    ./linux-lab/scripts/auth-audit/auth-audit.sh --file linux-lab/scripts/auth-audit/tests/fixtures/auth.log.sample --threshold 2 --summary

Beklenen: `203.0.113.50` ve `198.51.100.7` SUSPICIOUS görünür.

## 5) Gerçek log (kendi lab VM'in)

    sudo ./linux-lab/scripts/auth-audit/auth-audit.sh --summary
    # auth.log yoksa journal'dan:
    sudo ./linux-lab/scripts/auth-audit/auth-audit.sh --journal --summary

Beklenen: VM'e yapılan başarısız SSH denemeleri IP bazında listelenir; eşiği (varsayılan 4) aşan IP `SUSPICIOUS` olur.

## Çıkış kodları
| Kod | Anlam |
|-----|-------|
| 0 | Temiz: şüpheli IP ve yetkisiz sudo yok |
| 1 | Bulgu var (şüpheli IP veya yetkisiz sudo) |
| 2 | Kullanım/okuma hatası (dosya yok, izin yok, geçersiz parametre) |

## Kapsam ve güvenlik
Script **salt okunurdur**, hiçbir dosyayı değiştirmez ve ağa bağlanmaz. Yalnızca kendi lab VM'indeki loglar üzerinde çalıştırılmalıdır. Örnek logdaki IP'ler dokümantasyon amaçlı ayrılmış adreslerdir (RFC 5737).
