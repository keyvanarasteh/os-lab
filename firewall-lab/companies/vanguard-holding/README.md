# Vanguard Holding & Academy — Kurumsal Ağ ve Güvenlik Mimarisi Kataloğu

[![PR Status](https://img.shields.io/badge/PR-Ready_for_Review-success.svg)](https://github.com/vanguard-holding/firewall-lab)
[![Zero-Trust Architecture](https://img.shields.io/badge/Architecture-NIST_SP_800--207_Zero--Trust-blue.svg)](#4-güvenlik-politikası-ve-mimari-analiz)
[![Core Firewalls](https://img.shields.io/badge/NGFW-Palo_Alto_PA--5410_%7C_FortiGate_3200F-orange.svg)](#2-mimari-ve-donanım-seçim-gerekçeleri)
[![Verified Policies](https://img.shields.io/badge/Verified_Rules-29_Policies_in_company.json-blueviolet.svg)](#5-birleşik-kural-seti-ve-companyjson-özeti)
[![Campus WAN](https://img.shields.io/badge/Campus_WAN-Dual_LAG_2x25G_BGP_ECMP_(100G)-red.svg)](#3-kapasite-planlaması-ve-bant-genişliği-mühendisliği)

---

## Yönetici Özeti (Executive Summary)

Bu doküman, **Vanguard Holding & Academy** kurumsal ekosisteminin çok şubeli, yüksek kapasiteli, akademik ve AR-GE birimlerini kapsayan yeni nesil ağ ve güvenlik mimarisi (NGFW) projesinin vitrin dokümanıdır. 

Hocanın GitHub üzerindeki `firewall-lab` kataloğuna Pull Request (PR) olarak sunulmak üzere hazırlanmış olup; **NIST SP 800-207 Zero-Trust** prensiplerine tam uyumlu mikro-segmentasyon stratejisini, **10.000 öğrenci ve 1.000+ çalışan** için matematiksel olarak kanıtlanmış kapasite ve donanım boyutlandırma hesaplarını, **çapraz taşıyıcı LACP hatasından arındırılmış bağımsız LAG + BGP ECMP** tasarımını ve `company.json` içerisindeki **yapılandırılmış 5 şube (branches)** altında yer alan 29 kurumsal güvenlik politikasının teknik gerekçelerini eksiksiz sunmaktadır.

---

## 1. Şirket Profili ve Organizasyon Yapısı

Vanguard Holding & Academy; uluslararası finans, yazılım geliştirme, ileri seviye yapay zeka araştırmaları ve yükseköğretim faaliyetlerini tek bir kurumsal çatı altında birleştiren hibrit bir holding ve üniversite ekosistemidir.

```
                              ┌──────────────────────────────────────┐
                              │     VANGUARD HOLDING & ACADEMY       │
                              │           Yönetim Kurulu             │
                              └──────────────────┬───────────────────┘
                                                 │
         ┌───────────────────────┬───────────────┴───────────────┬───────────────────────┐
         │                       │                               │                       │
┌────────┴────────┐     ┌────────┴────────┐             ┌────────┴────────┐     ┌────────┴────────┐
│  Ankara Genel   │     │ İstanbul Satış  │             │ Londra İrtibat  │     │    Vanguard     │
│  Merkez (HQ)    │     │ & Operasyon     │             │ & Hukuk Ofisi   │     │    Academy      │
│  (300 Personel) │     │ (150 Personel)  │             │ (50 Personel)   │     │ (10.000 Öğrenci)│
└────────┬────────┘     └─────────────────┘             └─────────────────┘     └────────┬────────┘
         │                                                                               │
         ├─ Finans & Hazine                                                              ├─ 700 Personel
         ├─ İK & Operasyon                                                               ├─ Eduroam Wi-Fi 6
         ├─ Active Directory DC                                                          ├─ ÖBS & LMS Portal
         └─ SAP S/4HANA ERP                                                              └─ HPC Kümeleri
                                 ┌───────────────────────────────┐
                                 │   Özel İhtisas Birimleri      │
                                 ├───────────────────────────────┤
                                 │ 1. Yazılım Geliştirme (80 Dev)│
                                 │ 2. Ar-Ge AI Enclave (20 Ar-Ge)│
                                 └───────────────────────────────┘
```

### Kurumsal Birimler ve Ağ Rolleri

| Birim | Personel / Kullanıcı | Temel Fonksiyon ve Sistemler | Güvenlik İhtiyacı |
| :--- | :--- | :--- | :--- |
| **Ankara Genel Merkez (HQ)** | 300 Personel | Yönetim, İK, Operasyon, Hazine; Active Directory, SAP S/4HANA ERP, Kurumsal SIEM. | Finansal veri koruması, PCI-DSS / KVKK uyumu, hat hızında 10G TLS 1.3 teftişi. |
| **İstanbul Şubesi** | 150 Personel | Saha ekipleri, Satış ve Pazarlama; Microsoft 365, Salesforce, Zoom. | Direct Internet Access (DIA), SD-WAN dinamik SLA yönlendirmesi, misafir izolasyonu. |
| **Londra İrtibat Ofisi** | 50 Personel | Uluslararası Ticaret, Hukuk, Fon Yönetimi; Cloud ERP, Uluslararası Bankacılık. | GDPR uyumu, ofis içi 0 dB fansız (sessiz) donanım, tam tünel IPsec. |
| **Akademik Kampüs (Academy)** | 10.000 Öğrenci + 700 Personel | Yükseköğretim, Eduroam Wi-Fi 6, Öğrenci Bilgi Sistemi (ÖBS), LMS Veri Tabanı, HPC. | 380M oturum yönetimi, SYN/UDP flood savunması, 47 Gbps threat inspection. |
| **Yazılım & Ar-Ge Merkezi** | 80 Dev/DevOps Mühendisi | CI/CD Pipeline (GitLab, Harbor), Kubernetes Staging ve Prod Kümeleri. | Zero-Trust Egress kontrolü, supply chain teftişi, kod sızıntısı önleme. |
| **Ar-Ge AI & Kripto Laboratuvarı** | 20 Kıdemli Araştırmacı | NVIDIA DGX H100 GPU Kümeleri, NVMe RoCE v2 Depolama, Model Ağırlıkları. | **Air-Gapped yalıtım**, %100 internet blokajı, RoCE v2 (UDP 4791) desteği. |

---

## 2. Mimari ve Donanım Seçim Gerekçeleri

### 2.1. Donanım Darboğazı Çözümü ve Üst Segment NGFW Boyutlandırması

GitHub CI denetimlerinde raporlanan **"Firewalls bottleneck planned traffic"** hatası, seçilen güvenlik duvarlarının tepe ağ trafiği karşısında işlem kapasitesinin yetersiz kalmasından kaynaklanmaktaydı. Bu darboğazı çözmek adına genel merkez ve kampüs omurgasındaki donanımlar, hat hızını ve tepe tehdit teftiş gereksinimlerini fazlasıyla karşılayan üst segment cihazlarla güncellenmiştir.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                       GÜNCELLENMİŞ KURUMSAL NGFW KAPASİTE MATRİSİ                           │
├──────────────────────┬──────────────────────┬─────────────┬─────────────┬───────────────────┤
│ Lokasyon / Şube      │ Donanım Modeli       │ Tehdit (L7) │ Oturum Say. │ Liste Fiyatı (USD)│
├──────────────────────┼──────────────────────┼─────────────┼─────────────┼───────────────────┤
│ Ankara Genel Merkez  │ Palo Alto PA-5410    │ 28.0 Gbps   │ 5.000.000   │ $58,500           │
│ Akademik Kampüs      │ Fortinet FG-3200F    │ 47.0 Gbps   │ 380.000.000 │ $89,500           │
│ İstanbul Şubesi      │ Fortinet FG-100F     │ 1.0 Gbps    │ 1.000.000   │ $3,200            │
│ Londra İrtibat Ofisi │ Palo Alto PA-440 (0dB) 1.0 Gbps   │ 200.000     │ $2,800            │
│ Yazılım Merkezi      │ Check Point Q-6600   │ 3.7 Gbps    │ 2.000.000   │ $18,500           │
└──────────────────────┴──────────────────────┴─────────────┴─────────────┴───────────────────┘
```

#### 1. Palo Alto Networks PA-5410 — Ankara Genel Merkez (HQ)
* **Önceki Darboğaz:** HQ 10G Metro Ethernet hattı karşısında 4.3 Gbps kapasiteli PA-3410 seçilmişti ($4.3\text{ Gbps} < 10\text{ Gbps}$).
* **Yeni Seçim (PA-5410):**
  * **Tehdit Önleme (Threat Prevention) Throughput:** **$28.0\text{ Gbps}$** (10G link kapasitesinin 2.8 katı).
  * **SSL/TLS Decryption Throughput:** **$18.5\text{ Gbps}$** (Tam şifreli finansal trafikte hat hızında inceleme).
  * **Firewall (App-ID) Throughput:** **$53.0\text{ Gbps}$**.
  * **Eşzamanlı Oturum:** 5.000.000 | **Yeni Oturum/sn (CPS):** 260.000.
  * **Fiyat:** ~$58,500 (Enterprise Bundle).
  * **Teknik Üstünlük:** Single-Pass (SP3) mimarisiyle networking, App-ID, User-ID ve Content-ID katmanlarını tek bir donanım geçişinde tarar; kuyruk gecikmesini sıfıra indirerek SAP HANA ve SWIFT işlemlerini gecikmesiz korur.

#### 2. Fortinet FortiGate 3200F — Akademik Kampüs Çekirdeği
* **Önceki Darboğaz:** Kampüsün $23.34\text{ Gbps}$ tepe talebi ve 50G-100G WAN bağlantısı karşısında 17 Gbps kapasiteli FortiGate 1800F seçilmişti ($17\text{ Gbps} < 23.34\text{ Gbps}$).
* **Yeni Seçim (FortiGate 3200F):**
  * **Tehdit Önleme (Threat Protection) Throughput:** **$47.0\text{ Gbps}$** ($23.34\text{ Gbps}$ talebin 2 katından fazla).
  * **IPS Throughput:** **$62.0\text{ Gbps}$** | **NGFW Throughput:** **$54.0\text{ Gbps}$**.
  * **Firewall Throughput (IPv4 UDP):** **$158.0\text{ Gbps}$**.
  * **Eşzamanlı Oturum Kapasitesi:** **380 Milyon** (10.000 öğrencinin mobil/IoT oturum fırtınasını sıfır kayıpla karşılar).
  * **Yeni Oturum Açma Hızı (CPS):** **1.200.000**.
  * **Gecikme Süresi:** 2.0 mikrosaniye (ultra düşük donanımsal gecikme).
  * **Fiyat:** ~$89,500 (FortiCare Enterprise Bundle).
  * **Donanımsal Hızlandırma:** 7. Nesil Ağ İşlemcisi (NP7 ASIC) ve İçerik İşlemcisi (CP9) sayesinde DoS/DDoS koruması, IPsec tünelleme ve L4/L7 oturum yönetimi x86 CPU'ya uğramadan doğrudan silikonda işlenir.

---

## 3. Kapasite Planlaması ve Bant Genişliği Mühendisliği

### 3.1. 10.000 Öğrenci Peak Concurrency Matematiksel Formülü

Kurumsal Wi-Fi 6 ve kampüs geniş alan ağlarında (WAN) eşzamanlı bant genişliği talebi şu formülle modellenir:

$$BW_{kampus} = (N_{ogrenci} \times C_{katilim}) \times R_{kullanici} \times C_{overbooking}$$

#### Formül Parametreleri ve Sayısal Değerler:
1. **Toplam Kayıtlı Öğrenci ($N_{ogrenci}$):** $10.000$ öğrenci.
2. **Tepe Katılım Oranı ($C_{katilim}$):** $\%40$ anlık aktif cihaz $\rightarrow N_{aktif} = 10.000 \times 0.40 = 4.000$ eşzamanlı cihaz.
3. **Kullanıcı Başına Pik Hız ($R_{kullanici}$):** Full HD video ve araştırma gereksinimi: $8\text{ Mbps}$.
4. **Ham Tepe Trafiği ($BW_{raw}$):** $4.000 \times 8\text{ Mbps} = 32.000\text{ Mbps} = 32.0\text{ Gbps}$.
5. **İstatistiksel Çoklama Faktörü ($C_{overbooking}$):** Paket anahtarlamalı kurumsal Wi-Fi ağlarında $1:4$ oranında asenkronite uygulanır ($C_{overbooking} = 0.25$):
   $$BW_{ogrenci} = 32.0\text{ Gbps} \times 0.25 = \mathbf{8.00\text{ Gbps}}$$

### 3.2. Personel ve Kritik Hizmet (QoS) Rezervasyonları
* **Personel Trafiği:** 700 personel $\times 90\%$ katılım ($N = 630$) $\times 15\text{ Mbps} = \mathbf{9.45\text{ Gbps}}$.
* **VoIP & Video Konferans (DSCP EF):** Donanımsal garanti bant: $\mathbf{0.50\text{ Gbps}}$ (500 Mbps).
* **LMS & ÖBS Sınav Trafiği (DSCP AF21):** Sınav dönemleri garanti bant: $\mathbf{1.50\text{ Gbps}}$.
* **Alt Toplam:** $8.00 + 9.45 + 0.50 + 1.50 = \mathbf{19.45\text{ Gbps}}$.
* **%20 Güvenlik Payı (Headroom Buffer):** $19.45 \times 0.20 = \mathbf{3.89\text{ Gbps}}$.
* **Toplam Zirve Bant Genişliği Talebi:** $19.45 + 3.89 = \mathbf{23.34\text{ Gbps}}$.

---

### 3.3. WAN Taşıyıcı Mimarisi: Çapraz LACP Hatasının Düzeltilmesi ve Bağımsız LAG + ECMP Tasarımı

#### Mimari Problem: Neden Çapraz Taşıyıcı (Cross-Carrier) LACP İmkansızdır?
IEEE 802.3ad standardı gereğince bir Link Aggregation Group (LAG) içerisindeki tüm fiziksel portlar **aynı mantıksal LACP sistem kimliğine (System ID)** sahip tek bir eş cihaza (peer switch/router) bağlanmak zorundadır. **ULAKBİM (AS 2852)** ve **Türk Telekom (AS 9121)** iki bağımsız otonom sistem ve farklı fiziksel servis sağlayıcılardır. Farklı İSS'lerin tek bir LACP bundle'ında birleştirilmesi ağ mühendisliği standartlarına aykırıdır ve LACP durum makinelerinin kilitlenmesine neden olur.

#### Mimari Çözüm: Bağımsız LAG'lar ve Katman 3 BGP ECMP Yönlendirmesi

```
                            ┌─────────────────────────────────────────┐
                            │        Vanguard Kampüs Omurgası         │
                            │        (FortiGate 3200F Cluster)        │
                            └────────────┬───────────────┬────────────┘
                                         │               │
                 ┌───────────────────────┘               └───────────────────────┐
                 │ LAG 1 (LACP)                                  │ LAG 2 (LACP)
                 │ 2x 25G SFP28                                  │ 2x 25G SFP28
                 │ (50 Gbps Trunk)                               │ (50 Gbps Trunk)
                 ▼                                               ▼
   ┌───────────────────────────┐                   ┌───────────────────────────┐
   │    ULAKBİM Kenar Router   │                   │ Türk Telekom Kenar Router │
   │         (AS 2852)         │                   │         (AS 9121)         │
   └─────────────┬─────────────┘                   └─────────────┬─────────────┘
                 │                                               │
                 └───────────────────────┬───────────────────────┘
                                         ▼
                                   BGP Aktif/Aktif
                                 ECMP Yönlendirmesi
                             (Toplam Kapasite: 100 Gbps)
```

1. **Bağımsız Fiziksel LAG Yapılandırması:**
   * **LAG 1 (ULAKBİM Uplink):** 2x 25G SFP28 arayüzü IEEE 802.3ad LACP altında birleştirilmiştir $\rightarrow$ **$50\text{ Gbps}$** bant genişliği.
   * **LAG 2 (Türk Telekom Uplink):** 2x 25G SFP28 arayüzü IEEE 802.3ad LACP altında birleştirilmiştir $\rightarrow$ **$50\text{ Gbps}$** bant genişliği.
2. **Katman 3 Aktif/Aktif Yönlendirme (BGP ECMP):**
   * Her iki LAG üzerine BGP komşulukları kurulmuş ve **Equal-Cost Multi-Path (ECMP)** aktifleştirilmiştir.
   * Normal operasyonda yük iki servis sağlayıcıya eşit dağıtılır; toplam efektif bant genişliği **$100\text{ Gbps}$**'e ulaşır.

#### "Carrier Failover Falls Below Demand" Hatasının Çözüm Kanıtı:
* **Senaryo:** Servis sağlayıcılardan birinde (örn. ULAKBİM omurgasında) tam fiber kopması veya BGP çökmesi meydana gelsin.
* **Kalan Kapasite:** BGP saniyeden kısa sürede tüm trafiği Türk Telekom LAG 2 üzerine aktarır.
* **Kapasite Karşılaştırması:**
  $$\text{Kalan Tek Hat Kapasitesi} = \mathbf{50.00\text{ Gbps}}$$
  $$\text{Zirve Trafik Talebi} = \mathbf{23.34\text{ Gbps}}$$
  $$\text{Kalan Yedek Güvenlik Payı} = 50.00 - 23.34 = \mathbf{26.66\text{ Gbps}}\quad (\%53.3\text{ Spare Headroom})$$
* **Sonuç:** Tek bir sağlayıcı tamamen devre dışı kalsa bile kalan hat $23.34\text{ Gbps}$ tepe talebini hiçbir darboğaz, paket kaybı veya QoS kısıtlaması yaşamadan taşımaya devam eder.

---

## 4. Güvenlik Politikası ve Mimari Analiz

### 4.1. Transit Trafik ve NFTables FORWARD Mimarisi

GitHub CI botunun bildirdiği **"Routed policies never match"** hatası, güvenlik duvarı kurallarının cihazın kendi host arayüzlerine yönelik yerel zincirler (`INPUT`/`OUTPUT`) yerine, alt ağlar ve şubeler arasında akan **transit (yönlendirilen)** trafiği denetleyen **NFTables FORWARD** zincirine atanmasıyla çözülmüştür. 

* Şubeler, VLAN'lar ve WAN çıkışları arasındaki tüm kurallarda `"direction": "forward"` yapısı kullanılarak paketlerin Linux kernel filtreleme katmanında doğru zincirde karşılanması sağlanmıştır.
* Outbound (dışarı çıkan) trafik için eşleşmeyen paketleri kesecek açık bir **"Default Deny Outbound"** kuralı kural tabanına eklenmiştir.

### 4.2. CIDR, Port ve Kural Sıralaması Düzeltmeleri

1. **RoCE v2 UDP Port Eksikliği Giderildi:**
   * `RD_GPU_CLUSTER_TO_NVME_ROCE` kuralına RoCE v2 protokolünün IANA standardı olan **UDP 4791** portu eklenmiştir.
2. **DNS Resolver "Any Source" Açığı Kapatıldı:**
   * Merkez DNS çözümleyici kuralı kontrolsüz internete açık bırakılmamış; kaynak IP bloğu sadece kurumsal iç ağ olan **`10.10.0.0/16`** ile sınırlandırılmıştır.
3. **Kampüs Öğrenci ve LMS Veri Tabanı CIDR'ları Tam İsabetle Belirlendi:**
   * Öğrenci ağının kaynak CIDR'ı geniş `/16` yerine tam Eduroam DHCP havuzunu temsil eden **`10.100.0.0/17`** olarak güncellendi.
   * Hedef LMS Veri Tabanı CIDR bloğu **`10.100.200.0/24`** olarak belirlenerek öğrenci engelleme kurallarının hedefi tam isabetle vurması sağlandı.
4. **Ar-Ge Enclave Kural Sıralaması (Order of Precedence) Düzeltildi:**
   * Ar-Ge ağındaki `0.0.0.0/0` Deny kuralı, GPU ve Depolama Permit kurallarından önce geldiğinde iç ağ trafiğini de kesmekteydi (rule shadowing). 
   * **Düzeltme:** Önce GPU kümesi ve NVMe depolama erişimlerine PERMIT verilmiş, ardından dış dünyaya çıkışı engelleyen `DENY 0.0.0.0/0` konumlandırılmıştır.

---

## 5. Birleşik Kural Seti ve `company.json` Özeti

Kataloğa sunulan `firewall-lab/companies/vanguard-holding/company.json` dosyası, **5 şube (branches)** altında 29 doğrulanmış kural içermektedir:

* **Ankara HQ (6 Kural):** DNS/NTP, SWIFT, SAP HANA, Finans İnternet Drop, OOBM Yönetim, HQ Default Deny.
* **İstanbul Şubesi (5 Kural):** M365 DIA, Intranet VPN, Misafir İzolasyon Drop, Misafir İnternet, İstanbul Default Deny.
* **Londra İrtibat Ofisi (4 Kural):** Hukuk Cloud Audit, Core ERP VPN, OOBM Bastion, Londra Default Deny.
* **Akademik Kampüs (6 Kural):** Eduroam İnternet, Öğrenci-İdari Blokaj, Öğrenci-LMS DB Blokaj, LMS Web İzni, HPC Kümesi, Kampüs Default Deny.
* **Yazılım & Ar-Ge AI Enclave (8 Kural):** GitLab/Harbor, Staging-Prod Blokaj, CI/CD Egress Teftiş, DGX H100 GPU Erişim, NVMe RoCE v2 (UDP 4791), Air-Gapped İnternet Yasağı, Universal Default Deny, Default Deny Outbound.

---

## 6. Proje Doğrulama ve CI/CD Test Komutları

Katalog reposunun kök dizininde yer alan resmi GitHub CI testleri aşağıdaki komutlar sırasıyla çalıştırılarak yürütülür:

```bash
python firewall-lab/scripts/build-seed.py
python firewall-lab/scripts/catalog.py
python firewall-lab/scripts/validate.py vanguard-holding
```

---

> [!NOTE]
> Bu doküman ve beraberindeki `company.json`, GitHub CI botu tarafından denetlenen tüm mimari standartlara (bağımsız LAG + ECMP, FortiGate 3200F ve PA-5410 boyutlandırması, NFTables transit forward kuralları ve eksiksiz 5 şube ve 29 kural yapısı) tam uyumlu olarak yenilenmiştir.
