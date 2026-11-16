# OS-17 SSH Connection Troubleshooter — Verification

## Environment
- Operating System: Windows 11
- Terminal: Git Bash
- Language: Python 3
- Task: OS-17

## Manual Tests

### Test 1 — Connection Timeout
Command:
`python linux-lab/scripts/ssh_troubleshooter.py "Connection timed out"`

Expected result: `TIMEOUT`

Actual result: `TIMEOUT`

Status: PASS

### Test 2 — Authentication Failure
Command:
`python linux-lab/scripts/ssh_troubleshooter.py "Permission denied"`

Expected result: `AUTHENTICATION`

Actual result: `AUTHENTICATION`

Status: PASS

### Test 3 — Loopback Address
Command:
`python linux-lab/scripts/ssh_troubleshooter.py "127.0.1.1"`

Expected result: `LOOPBACK`

Actual result: `LOOPBACK`

Status: PASS

### Test 4 — Firewall Block
Command:
`python linux-lab/scripts/ssh_troubleshooter.py "Firewall blocked"`

Expected result: `FIREWALL`

Actual result: `FIREWALL`

Status: PASS

### Test 5 — Wrong Network Adapter
Command:
`python linux-lab/scripts/ssh_troubleshooter.py "Wrong adapter"`

Expected result: `ADAPTER`

Actual result: `ADAPTER`

Status: PASS

## Conclusion
All five manual SSH error classification tests passed successfully.

The script identifies common SSH connection problems and provides troubleshooting suggestions.

Note: These tests verify message classification, not live SSH connectivity.
# OS-21 Dogrulama (Verification) — Boot-Time Python Service Starter (systemd)

## 1. Calistirma Komutlari

Servis birim dosyasini (.service) uretmek ve onizlemek icin:
    ./linux-lab/scripts/os-21-service-starter.sh

Servisi systemd altina kurmak, acilista otomatik baslayacak sekilde etkinlestirmek (enable) ve status / journalctl ciktilariyla dogrulamak icin:
    sudo ./linux-lab/scripts/os-21-service-starter.sh --install

## 2. Beklenen Cikti

    === [1/4] loop.py dosyasi kontrol ediliyor ===
    === [2/4] Systemd .service birim dosyasi olusturuluyor ===
    === [3/4] Servis sisteme kuruluyor ve etkinlestiriliyor (enable & start) ===
    === [4/4] Dogrulama: enable / status / journalctl ===
    -> Enabled durumu:
    enabled
    -> Servis durumu (status):
    Active: active (running)
    -> Servis loglari (journalctl):
    [OS-21] Python systemd servisi aktif! Sayac: 1
