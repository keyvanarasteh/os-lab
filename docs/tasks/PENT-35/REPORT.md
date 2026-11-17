# PENT-35 · Red-Team Report & MITRE ATT&CK Mapping Generator

| | |
|---|---|
| Öğrenci | Ufuk Babasız · 2520191002 (`ufuk888`) |
| Ders | MYO062 — vize projesi |
| Görev | [PENT-35](../../../CONTRIBUTING.md) · Rezervasyon: [`reservations/PENT-35.json`](../../../reservations/PENT-35.json) |
| Kanıt videosu | https://www.youtube.com/watch?v=ywXgfwWg0Rc |

## 1. Amaç

İzole lab ortamında üretilmiş red-team / pentest oturum loglarını (`.json` / `.jsonl`)
MITRE ATT&CK çerçevesine göre eşleştiren, risk puanı hesaplayan ve profesyonel
çift formatlı rapor (Markdown + PDF) üreten bir CLI aracı geliştirmek.

Araç, **kapsam koruması (Scope Guard)** sayesinde yalnızca özel ağ (RFC 1918),
loopback ve `.local` / `.lab` hedeflerini kabul eder; herhangi bir genel IP veya
yetkisiz domain görüldüğünde `ScopeViolationError` fırlatarak sıfır dışı çıkış koduyla
sonlanır.

## 2. Mimari

```
source-lab/engine/
├── pent35_report_gen.py          # Ana CLI aracı (Python 3.11+ stdlib only)
├── mitre_rules.json              # 28 MITRE ATT&CK teknik kuralı
├── fixtures/
│   ├── sample_lab_session.json   # Gerçekçi izole lab oturumu (17 olay)
│   └── out_of_scope_session.json # Scope Guard test verisi
└── tests/
    └── test_pent35_report_gen.py # 30+ pytest testi
```

### Bileşenler

| Bileşen | Açıklama |
|---|---|
| **Scope Guard** | Oturumdaki tüm IP, CIDR ve hostname'leri denetler. RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`, `localhost`) ve `.local`/`.lab` uzantıları dışında kalan hedefleri reddeder. |
| **MITRE ATT&CK Motoru** | `mitre_rules.json` dosyasındaki 28 kural ile logları keyword tabanlı eşleştirir. Taktik, Teknik ID, isim, severity ve remediation bilgisi üretir. |
| **Risk Skoru** | Ağırlıklı formül: %40 max severity + %30 ortalama severity + %30 taktik genişliği. 0–10 aralığında skaler skor. |
| **Markdown Rapor** | Yapılandırılmış profesyonel rapor: Executive Summary, Scope & Targets, MITRE ATT&CK Mapping tablosu, Detailed Findings ve Remediation Summary. |
| **PDF Rapor** | Sıfır harici bağımlılık ile saf Python `%PDF-1.4` yazıcı. Geçerli xref, page tree, Helvetica font, FlateDecode sıkıştırma içerir. |

### MITRE ATT&CK Kapsam

Araç aşağıdaki taktik ve teknikleri tanır:

| Taktik | Örnek Teknikler |
|---|---|
| Initial Access | T1190 (Exploit Public-Facing Application) |
| Execution | T1059.001 (PowerShell), T1059.003 (cmd), T1059.004 (Unix Shell) |
| Persistence | T1547.001 (Registry Run Keys), T1053.005 (Scheduled Task), T1053.003 (Cron), T1078 (Valid Accounts) |
| Privilege Escalation | T1068 (Exploitation for Privilege Escalation) |
| Defense Evasion | T1055 (Process Injection), T1070.004 (File Deletion), T1562.001 (Disable Tools) |
| Credential Access | T1003 (OS Credential Dumping), T1003.001 (LSASS), T1110 (Brute Force) |
| Discovery | T1046 (Network Service Discovery), T1082 (System Info), T1033 (User Discovery), T1087 (Account Discovery), T1135 (Share Discovery), T1018 (Remote System Discovery) |
| Lateral Movement | T1021.001 (RDP), T1021.004 (SSH) |
| Command and Control | T1071 (Application Layer Protocol), T1071.001 (Web Protocols), T1105 (Tool Transfer), T1572 (Tunneling) |
| Exfiltration | T1048 (Alternative Protocol) |

## 3. Kullanım

### Kurulum

Ek bağımlılık gerekmez — Python 3.11+ standart kütüphanesi yeterlidir.

### Çalıştırma

```bash
# Temel kullanım
python source-lab/engine/pent35_report_gen.py \
  --input source-lab/engine/fixtures/sample_lab_session.json \
  --out-dir ./reports

# Kısa parametreler
python source-lab/engine/pent35_report_gen.py \
  -i source-lab/engine/fixtures/sample_lab_session.json \
  -o ./reports

# Özel kural dosyası ile
python source-lab/engine/pent35_report_gen.py \
  -i session.json -o ./reports --rules custom_rules.json
```

### Çıktılar

```
reports/
├── redteam_report.md    # Yapılandırılmış Markdown rapor
└── redteam_report.pdf   # Geçerli PDF rapor (%PDF-1.4)
```

### Örnek Çıktı Özeti

```
Report generated successfully!
  Risk Score : 8.1/10
  Findings   : 18
  Markdown   : ./reports/redteam_report.md
  PDF        : ./reports/redteam_report.pdf
```

## 4. Testler

```bash
# Yalnızca PENT-35 testleri
cd source-lab/engine
python -m pytest tests/test_pent35_report_gen.py -v

# Tüm repo testleri (run-tests.sh)
./scripts/run-tests.sh
```

### Test Kapsamı

| Test Kategorisi | Kontrol |
|---|---|
| **Scope Guard** | Özel IP kabul, genel IP red, hostname doğrulama, `out_of_scope_session.json` reddi |
| **MITRE Eşleştirme** | `nmap→T1046`, `powershell→T1059.001`, `mimikatz→T1003`, `schtasks→T1053.005`, `reg.exe→T1547.001`, `whoami→T1033`, `curl→T1071` |
| **Risk Skoru** | Boş bulgu=0, yüksek severity>5, düşük severity<5, max 10 |
| **Girdi Formatı** | `.json` (nesne), `.json` (dizi), `.jsonl` |
| **Rapor Çıktısı** | Markdown başlıkları, PDF `%PDF-` imzası, PDF yapısal bütünlük (xref, trailer, EOF) |
| **CLI** | Başarılı çalıştırma (exit 0), scope ihlali (exit 2), eksik dosya (exit 1), subprocess çalıştırma |

## 5. Scope Guard Güvenlik Detayı

```
Kabul Edilen:
  ✓ 10.0.0.0/8        (RFC 1918 Class A)
  ✓ 172.16.0.0/12     (RFC 1918 Class B)
  ✓ 192.168.0.0/16    (RFC 1918 Class C)
  ✓ 127.0.0.0/8       (Loopback)
  ✓ localhost          (Loopback hostname)
  ✓ *.local            (mDNS / lab)
  ✓ *.lab              (Lab domains)

Reddedilen (ScopeViolationError):
  ✗ 8.8.8.8            (Public IP)
  ✗ 1.1.1.1            (Public IP)
  ✗ example.com        (Public domain)
  ✗ google.com         (Public domain)
```

## 6. Demo Komutu (Video için tek satır)

```bash
python source-lab/engine/pent35_report_gen.py -i source-lab/engine/fixtures/sample_lab_session.json -o ./demo-report && cat ./demo-report/redteam_report.md && python -m pytest source-lab/engine/tests/test_pent35_report_gen.py -v
```

---

*Bu rapor PENT-35 · Red-Team Report & MITRE ATT&CK Mapping Generator görevi
kapsamında hazırlanmıştır. Tüm testler yalnızca izole lab ortamında yürütülmüştür.*
