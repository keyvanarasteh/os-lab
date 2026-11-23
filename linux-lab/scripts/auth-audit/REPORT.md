# REPORT: OS-04 Auth Log Audit

**Öğrenci:** Esmanur Turkay · **GitHub:** esmanurturkay · **Görev:** OS-04

## Ne yaptım
Ubuntu Server lab VM'inde SSH brute-force denemelerini ve yetkisiz `sudo` girişimlerini log dosyasından çıkaran küçük, salt okunur bir araç yazdım. İnce bir bash kabuğu (`auth-audit.sh`) Python ayrıştırıcıyı (`auth_audit.py`) çağırır.

- `Failed password` satırlarını IP bazında sayar; aynı IP'den **4 veya daha fazla** başarısız deneme "şüpheli" sayılır (`--threshold` ile değişir).
- `sudo` için "user NOT in sudoers" ve "incorrect password attempts" satırlarını yakalar.
- Çıktı: varsayılan JSON (dashboard/test için), `--summary` ile okunabilir tablo.
- Kaynak: `--file` (varsayılan `/var/log/auth.log`, `-` ile stdin) veya `--journal`.
- Çıkış kodları repo stiline uygun: 0 temiz, 1 bulgu, 2 hata.
- 19 kontrollük offline test ve örnek log dosyaları ekledim.

## Neden bu tasarım
- Ayrıştırma Python'da: regex ve JSON işleme bash'te kırılgan, Python'da test etmesi kolay.
- Kabuk ince tutuldu: bağımlılık kontrolü yapıp Python'a devreder, repo'nun `set -euo pipefail` kuralına uyar.
- Salt okunur: logu hiçbir şekilde değiştirmez, ağa çıkmaz.

## Sınırlar (bilerek ilk sürümde yok)
SQLite kaydı, `journalctl -f` ile sürekli izleme, zaman penceresi tabanlı eşik ve systemd servis dosyası. Bunlar teslimden sonra ikinci aşama olarak ayrı bir PR'da eklenecek.

## Git/PR'da ne öğrendim
- Projeyi **fork**'layıp kendi kopyamda çalışmayı, `upstream` uzak deposunu eklemeyi öğrendim.
- Her iş için `master`'dan ayrı bir **dal** açmanın ana kodu bozmadan çalışma sağladığını gördüm.
- **Conventional Commits** ile anlamlı, küçük commit'ler yazdım (`feat`, `test`, `docs`).
- Dalı fork'uma `git push` ile gönderip GitHub'da **Pull Request** açtım; PR'ın tek bir işi kapsaması gerektiğini öğrendim.
- Görevi önce **rezervasyon PR'ı** ile almanın aynı işin iki kişi tarafından yapılmasını önlediğini öğrendim.

## Karşılaştığım zorluklar
Dosyaları Windows'tan VM'e taşırken `scp` komutunu yanlış yerde (VM içinde) çalıştırdım ve yol hataları aldım; komutun Windows PowerShell'de çalışması gerektiğini öğrendim.
Repo'nun `./scripts/run-tests.sh` kontrolü ilk çalıştırmada `python3-venv` paketi eksik olduğu için hata verdi; hata mesajını okuyup paketi `apt` ile kurarak çözdüm.
