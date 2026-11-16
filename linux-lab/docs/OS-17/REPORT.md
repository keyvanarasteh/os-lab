# OS-17 — SSH Connection Troubleshooter

## Project Summary
This project implements a Python-based SSH connection troubleshooting tool for OS-17.

The tool analyzes common SSH error messages and provides explanations and suggested solutions.

## Features
The script detects five common SSH problems:

1. Connection timed out
2. Authentication failure
3. Loopback IP address (127.0.1.1)
4. Firewall restrictions
5. Incorrect network adapter

## Implementation
- Programming language: Python 3
- Script: `linux-lab/scripts/ssh_troubleshooter.py`
- Uses Python standard libraries
- No additional Python packages required

## Testing
Five manual tests were performed successfully.

All five error categories returned the expected results.

Detailed verification commands and results are documented in `linux-lab/VERIFY.md`.

## What I Learned
During this project, I learned how to:

- Create a Git branch
- Write and run a Python script
- Diagnose common SSH connection errors
- Document and verify program behavior
- Prepare a contribution using Git and GitHub

## Limitations
The tool classifies supplied error messages. It does not perform live SSH connection checks or automatically modify firewall and network settings.

## Conclusion
The OS-17 SSH Connection Troubleshooter provides a simple command-line tool for identifying common SSH errors and suggesting possible fixes.# OS-21 Vize Projesi Raporu — Boot-Time Python Service Starter (systemd)

## 1. Projede Ne Yaptim?
Bu calismada OS-21 (Boot-Time Python Service Starter) gorevi kapsaminda Linux sistem acilisinda (boot) otomatik olarak baslayan bir Python arka plan servisi hazirladim:
- linux-lab/scripts/loop.py: Belirli araliklarla (time.sleep(5)) standart ciktiya (stdout / flush=True) calisma durumu logu basan dongusel bir Python betigi yazdim.
- linux-lab/scripts/os-21-service-starter.sh: loop.py betigini calistiracak minimal .service (systemd unit) dosyasini ureten, --install parametresi verildiginde servisi /etc/systemd/system/ altina kopyalayip systemctl daemon-reload ve systemctl enable --now ile aktif eden, ardindan systemctl is-enabled, systemctl status ve journalctl -u komutlariyla servisin calistigini dogrulayan bir Bash araci gelistirdim.

## 2. Git ve Pull Request (PR) Surecinde Ne Ogrendim?
- Acik kaynak bir projeyi kendi hesabima fork etmeyi ve yerel gelistirme ortamima git clone ile indirmeyi ogrendim.
- Ana dali (master) bozmadan izole bir sekilde calismak icin gorev ozelinde yeni bir branch (dal) (os-21-systemd-service) olusturmanin onemini kavradim.
- Degisiklikleri gondermeden once yerel dogrulama testlerini (./scripts/run-tests.sh --quick) calistirarak kod kalitesini ve kabuk sozdizimini (bash -n) kontrol etmeyi deneyimledim.
- Anlamli commit mesajlari yazarak degisiklikleri kendi fork depoma (git push) aktarmayi ve ana projeye Pull Request (PR) acarak acik kaynak katkisi sunma is akisini uygulamali olarak ogrendim.
