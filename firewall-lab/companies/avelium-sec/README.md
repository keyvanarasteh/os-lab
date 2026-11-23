# 🛡️ Avelium Siber ve Akademi Holding A.Ş. (`avelium-sec`)

**Sektör:** Eğitim & Siber Güvenlik Ar-Ge  
**Ders:** BGT207 — Güvenlik Duvarı ve Ağ Güvenliği  

İstanbul Merkez, Ankara, Londra, **10.000 öğrencilik Akademik Kampüs** ve izole **Yazılım/Ar-Ge** merkezinden oluşan çok şubeli kurumsal ağ segmentasyonu, QoS bant genişliği planlaması, L7 WAF + NGFW güvenlik duvarı seçimi ve SOC/SIEM izleme mimarisi.

---

## 📊 1. Şubeler, Kişi Sayıları, Bant Genişliği ve Alt Ağ (VLAN) Planı

Her şubenin tüm alt ağları (Yönetim, Personel, Öğrenci, DMZ ve Misafir/IoT VLAN 90) **kendi şube üst bloğunun (Supernet CIDR) içinde** kalacak şekilde tasarlanmıştır:

| Şube | Kişi Sayıları | Şube Bloğu (CIDR) | VLAN Segmentasyonu | Bant Genişliği (Down/Up) |
| :--- | :--- | :--- | :--- | :--- |
| **İstanbul Merkez (`istanbul-hq`)** | 160 Personel, 60 Yazılım, 30 Ar-Ge | `10.10.0.0/16` | • VLAN 10 Yönetim (`10.10.10.0/24`)<br>• VLAN 20 Personel (`10.10.20.0/23`)<br>• VLAN 30 Yazılım (`10.10.30.0/24`)<br>• VLAN 40 Ar-Ge (`10.10.40.0/24`)<br>• VLAN 50 Sunucular (`10.10.50.0/24`)<br>• VLAN 60 DMZ + WAF (`10.10.60.0/24`)<br>• VLAN 90 Misafir/IoT (`10.10.90.0/24`) | **1000 / 1000 Mbps** (1 Gbps Simetrik) |
| **Ankara Ofisi (`ankara-office`)** | 80 Personel, 15 Yazılım, 10 Ar-Ge | `10.20.0.0/16` | • VLAN 10 Yönetim (`10.20.10.0/24`)<br>• VLAN 20 Personel (`10.20.20.0/24`)<br>• VLAN 30 Yazılım (`10.20.30.0/24`)<br>• VLAN 90 Misafir/IoT (`10.20.90.0/24`) | **500 / 500 Mbps** |
| **Londra Ofisi (`london-office`)** | 45 Personel, 25 Yazılım, 15 Ar-Ge | `10.30.0.0/16` | • VLAN 10 Yönetim (`10.30.10.0/24`)<br>• VLAN 20 Personel (`10.30.20.0/24`)<br>• VLAN 30 Yazılım (`10.30.30.0/24`)<br>• VLAN 90 Misafir/IoT (`10.30.90.0/24`) | **500 / 500 Mbps** (IPsec VPN) |
| **Akademik Şube (`academic-campus`)**| **10.000 Öğrenci**, 450 Hoca/Personel, 15 Yazılım, 10 Ar-Ge | `10.64.0.0/14` | • VLAN 10 Yönetim (`10.64.10.0/24`)<br>• VLAN 20 Hoca/Personel (`10.64.20.0/22`)<br>• VLAN 30 Ar-Ge (`10.64.30.0/24`)<br>• VLAN 60 DMZ LMS+WAF (`10.64.60.0/24`)<br>• VLAN 90 Misafir/IoT (`10.64.90.0/23`)<br>• VLAN 100 Öğrenci (`10.65.0.0/16`) | **10.000 / 10.000 Mbps** (10 Gbps)<br>*(Öğrenci: 5 Mbps/IP, Hoca: 25 Mbps)* |
| **Yazılım & Ar-Ge (`software-rnd-lab`)**| 80 Yazılım, 45 Ar-Ge, 35 DevOps/Personel | `10.50.0.0/16` | • VLAN 10 Yönetim (`10.50.10.0/24`)<br>• VLAN 30 Yazılım (`10.50.30.0/24`)<br>• VLAN 40 Ar-Ge (`10.50.40.0/24`)<br>• VLAN 50 Git/DB Sunucu (`10.50.50.0/24`)<br>• VLAN 90 Misafir/IoT (`10.50.90.0/24`) | **2000 / 2000 Mbps** (2 Gbps Düşük Gecikme) |

---

## 🏆 2. Seçilen Güvenlik Duvarları, WAF ve Top-5 Karşılaştırması

Tüm şubelerde seçilen güvenlik duvarı modellerinin Threat Protection kapasiteleri, şube hat hızlarının (10 Gbps dahil) üzerindedir:

* **İstanbul Merkez (1 Gbps Hat):** **FortiGate 600F + FortiWeb WAF** (10.5 Gbps Kapasite, $14,500) — *Alternatifler: Palo Alto PA-3420 ($22,000), Check Point Quantum 6600 ($17,500), Cisco Firepower 2130 ($16,000), Netgate 8200 ($1,900).*
* **Ankara Ofisi (500 Mbps Hat):** **FortiGate 200F** (3.0 Gbps Kapasite, $4,200) — *Alternatifler: Palo Alto PA-850 ($6,800), Check Point 6200 ($5,400), Cisco 1140 ($4,900), OPNsense DEC2750 ($1,450).*
* **Londra Ofisi (500 Mbps Hat):** **Check Point Quantum 6600** (3.8 Gbps Kapasite, $8,900) — *Alternatifler: Palo Alto PA-1410 ($9,500), FortiGate 200F ($4,200), Cisco 2110 ($6,200), Netgate 6100 ($999).*
* **Akademik Şube (10 Gbps Hat - 10.000 Öğrenci):** **FortiGate 1000F + Cloudflare/ModSecurity WAF** (20.0 Gbps Kapasite, $18,500) — *Alternatifler: Palo Alto PA-5410 ($38,000), Check Point 7000 ($29,000), Cisco 3120 ($24,000), OPNsense DEC4280 ($3,200 - 8.5 Gbps olduğu için 10G hattı karşılamadığından elendi).*
* **Yazılım ve Ar-Ge Merkezi (2 Gbps Hat):** **Palo Alto PA-3430** (12.5 Gbps Kapasite, $25,000 - Kaynak kod DLP koruması için seçildi) — *Alternatifler: Check Point 6700 ($21,000), FortiGate 600F ($14,500), Cisco 2140 ($19,500), Netgate 1541 ($2,800).*

---

## 🔒 3. Güvenlik Politikası, WAF, VPN (MFA) ve Savunma Özeti

1. **L7 WAF Koruması:** İstanbul Merkez web sunucuları ve Akademik Şube öğrenci portalı (LMS/OBS) önünde OWASP Core Rule Set (SQLi, XSS, LFI, RCE ve DDoS/Rate-Limit) aktif WAF konumlandırılmıştır.
2. **Temel Altyapı ve İzolasyon:** Her şubede `DHCP (UDP 67:68)`, yerel güvenli `DNS (UDP 53)` ve `NTP (UDP 123)` kuralları tanımlanmış; Öğrenci (`VLAN 100`) ve Misafir/IoT (`VLAN 90`) ağlarının kurumsal iç ağlara (`10.0.0.0/8`) erişimi `DROP` (`deny`) ile kesilmiştir.
3. **Açık Default-Deny:** Dış kenarda `reject` yerine bilgi sızdırmayan `DROP` (`deny`) kullanılmış ve her kural setinin en sonuna açık `default-deny` kuralı eklenmiştir.
4. **MFA Zorunlu VPN:** İnternetten doğrudan SSH/RDP kapalıdır; uzaktan erişim yalnızca MFA (TOTP/Donanım Token) doğrulamalı `role-based-vpn` ile Bastion Yönetim VLAN'ı üzerinden yapılır.

---

## 👁️ 4. İzleme (Monitoring), Yedekleme, Yama ve CVE Takibi

* **Sistematik İzleme:** Tüm şubelerden çıkan loglar **Wazuh SIEM & OpenSearch** üzerinde toplanır (5651 sayılı kanuna uygun zaman damgalı 2 yıl saklama). Alarmlar (53/UDP DNS döngüsü bastırılmış şekilde) **PagerDuty** ve **SOC Telegram Botuna** düşer.
* **İnsani İzleme:** **7/24 SOC Ekibi** (Tier 1 Triyaj, Tier 2 Olay Müdahale, Tier 3 Threat Hunter) güvenlik olaylarını; **NOC Ekibi** ise **Prometheus + Grafana** üzerinden hat kapasitesini ve donanım sağlığını birbirinden ayrı panellerde izler.
* **Yedekleme ve Yama Rutini:** Güvenlik duvarı konfigürasyonları her gece otomatik yedeklenir ve **3-2-1 kuralıyla** şifreli off-site depoda saklanır. Kritik güvenlik yamaları (Örn: **CVE-2024-21762** FortiOS ve **CVE-2024-3400** PAN-OS) önce IPS sanal yama (Virtual Patch) ile hafifletilir, ardından bakım penceresinde kalıcı olarak yamalanır.

---

Contributed by **Erbay Aydoğan** (`@Erbay-Aydogan-BGT`) — BGT207
