# Kurumsal Ağ Topolojisi ve Güvenlik Mimarisi (Siber Güvenlik Şirketi)

> Contributed by `U*** B***` ([@ufuk888](https://github.com/ufuk888)) · BGT207 Güvenlik Duvarı Çözümleri · 2026-2027 Güz midterm project.
> Student names are masked on purpose. Updated to close all 13 architectural and security audit gaps (30 findings) and synchronized with `company.json`.

Küresel ölçekte siber güvenlik çözümleri sunan şirketimiz; İstanbul merkezli genel müdürlük yapısı, Sivas'taki 7/24 Güvenlik Operasyon Merkezi (SOC) ve Ar-Ge üssü, Ankara'daki Siber Güvenlik Eğitim Akademisi ve Dubai'deki uluslararası ticaret ofisi olmak üzere dört ana lokasyonda faaliyet göstermektedir. Kurumlara yönelik uçtan uca, hem ofansif hem de defansif güvenlik hizmetleri sağlayan firmamızın temel faaliyet alanları arasında; Avrupa ve Orta Doğu (MEA) bölgelerine özel operasyonlar yürüten Fiziksel Sızma Testi (Red Team) faaliyetleri, sürekli ağ izleme ve tehdit analizi, siber güvenlik yazılımları geliştirme süreçleri ve stajyer programlarıyla sektöre yeni uzmanlar kazandıran akademik eğitim hizmetleri yer almaktadır.

---

## 🏢 1. Şube Ağ ve Kapasite Planlamaları

Tüm şubelerde ağ segmentasyonu; üretim/iş birimleri, Ar-Ge/yazılım geliştirme, ofansif test (Red Team), fiziksel güvenlik/IoT cihazları, misafir erişimi ve bant dışı ağ yönetimi (**Out-of-Band Management - VLAN 99**) birbirinden tamamen izole edilecek şekilde tasarlanmıştır.

### 📍 ŞUBE 1: İstanbul (Ana Merkez - HQ)
**Kapasite:** 60 Personel (40 İdari/Operasyon + 20 Red Team & Ar-Ge) | **Süper Ağ:** `10.10.0.0/16`  
**Bant Genişliği & Yedeklilik:** Dual-ISP Active-Active SD-WAN (Birincil: 250/250 Mbps Simetrik Fiber + İkincil: 100/100 Mbps Yedek Fiber)
> *Gerekçe:* Muhasebe/idari birimin bulut tabanlı ERP/finans programlarını aktif kullanması, Red Team ekibinin yoğun veri transferleri ve yerel Ar-Ge ekibinin kod/imaj senkronizasyonu nedeniyle yüksek kapasiteli çift hatlı yedekli mimari uygulanmıştır.

| Birim / Ekip | Personel / Varlık | IP Bloğu (CIDR) | Gateway | Kullanılabilir IP Aralığı | VLAN ID | Güvenlik & İzolasyon Politikası |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Yönetim & Muhasebe** | 25 | `10.10.10.0/27` | `10.10.10.1` | `10.10.10.2 - 10.10.10.30` | **10** | Bulut ERP/Finans erişimi, Sysmon + Wazuh EDR zorunlu |
| **Yerel Pazarlama** | 10 | `10.10.20.0/28` | `10.10.20.1` | `10.10.20.2 - 10.10.20.14` | **20** | Standart kurumsal internet ve CRM erişimi |
| **Merkezi IT / Sistem** | 5 | `10.10.30.0/28` | `10.10.30.1` | `10.10.30.2 - 10.10.30.14` | **30** | Altyapı yönetimi için PAM Bastion üzerinden VLAN 99'a geçiş |
| **Red Team (TR/EU)** | 12 | `10.10.40.0/27` | `10.10.40.1` | `10.10.40.2 - 10.10.40.30` | **40** | Ofansif sızma testi ağı; SPAN port mirroring ile SOC izlemeli |
| **Ar-Ge (Yazılım)** | 8 | `10.10.50.0/28` | `10.10.50.1` | `10.10.50.2 - 10.10.50.14` | **50** | Red Team ağından ayrıştırılmış özel yazılım geliştirme VLAN'ı |
| **IoT / Kamera / Yazıcı** | ~12 Cihaz | `10.10.60.0/28` | `10.10.60.1` | `10.10.60.2 - 10.10.60.14` | **60** | IP kameralar, kartlı geçiş ve yazıcılar; iç ağa ve internete kapalı |
| **Misafir Wi-Fi (Guest)** | Ziyaretçi | `10.10.70.0/27` | `10.10.70.1` | `10.10.70.2 - 10.10.70.30` | **70** | Client Isolation aktif; yalnızca HTTP/HTTPS internet çıkışı |
| **OOB Ağ Yönetimi** | Altyapı | `10.10.99.0/28` | `10.10.99.1` | `10.10.99.2 - 10.10.99.14` | **99** | FortiGate HA, Core Switch ve AP yönetim arayüzleri (İzole) |

---

### 📍 ŞUBE 2: Sivas (SOC ve Ar-Ge Merkez Üssü)
**Kapasite:** 105 Personel (70 SOC & Destek + 35 Ar-Ge) | **Süper Ağ:** `10.20.0.0/16`  
**Bant Genişliği & Yedeklilik:** Dual-ISP BGP/SD-WAN Active-Active (Birincil: 500/500 Mbps + İkincil: 250/250 Mbps Simetrik Fiber)
> *Gerekçe:* Şirketin en kalabalık ve tüm şubelerin VPN/SIEM trafiğinin toplandığı merkezi omurgasıdır. SOC ekibi 7/24 tüm kurum genelinden gelen log/telemetri verilerini işler; Ar-Ge ekibi CI/CD hatları ve büyük Docker imajları üzerinde çalışır.

| Birim / Ekip | Personel / Varlık | IP Bloğu (CIDR) | Gateway | Kullanılabilir IP Aralığı | VLAN ID | Güvenlik & İzolasyon Politikası |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ar-Ge (Yazılım)** | 35 | `10.20.10.0/26` | `10.20.10.1` | `10.20.10.2 - 10.20.10.62` | **10** | GitLab, CI/CD runner ve özel container registry erişimi |
| **SOC Analistleri** | 65 | `10.20.20.0/25` | `10.20.20.1` | `10.20.20.2 - 10.20.20.126` | **20** | Wazuh SIEM, FortiAnalyzer ve SOAR konsollarına tam erişim |
| **Yerel Teknik Destek** | 5 | `10.20.30.0/28` | `10.20.30.1` | `10.20.30.2 - 10.20.30.14` | **30** | Veri merkezi fiziksel destek ve donanım bakım birimi |
| **IoT / Kamera / Sensör** | ~14 Cihaz | `10.20.60.0/28` | `10.20.60.1` | `10.20.60.2 - 10.20.60.14` | **60** | Veri merkezi CCTV, ortam/UPS sensörleri ve yazıcılar |
| **Misafir Wi-Fi (Guest)** | Ziyaretçi | `10.20.70.0/28` | `10.20.70.1` | `10.20.70.2 - 10.20.70.14` | **70** | Denetçi/misafir ağı; iç VLAN'lara erişim tamamen engelli |
| **OOB Ağ Yönetimi** | Altyapı | `10.20.99.0/28` | `10.20.99.1` | `10.20.99.2 - 10.20.99.14` | **99** | FortiGate 200F HA, IPMI/iDRAC, Switch ve SIEM sunucu yönetimi |

---

### 📍 ŞUBE 3: Ankara (Siber Güvenlik Eğitim Akademisi)
**Kapasite:** 110 Kullanıcı (10 Eğitmen + 100 Stajyer/Öğrenci) | **Süper Ağ:** `10.30.0.0/16`  
**Bant Genişliği & Yedeklilik:** Dual-ISP SD-WAN (Birincil: 300/300 Mbps + İkincil: 100/100 Mbps Simetrik Fiber)
> *Gerekçe:* 100 öğrencinin aynı anda sanal makine (ISO) indirmesi ve laboratuvar ortamlarına bağlanması yüksek bant genişliği gerektirir. Omurganın tıkanmaması için Traffic Shaping / QoS uygulanır ve stajyer ağı Zero Trust ilkesiyle iç ağdan tamamen yalıtılır.

| Birim / Ekip | Personel / Varlık | IP Bloğu (CIDR) | Gateway | Kullanılabilir IP Aralığı | VLAN ID | Güvenlik & İzolasyon Politikası |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Akademik & Eğitmenler** | 10 | `10.30.10.0/28` | `10.30.10.1` | `10.30.10.2 - 10.30.10.14` | **10** | Eğitim materyalleri ve merkez kaynaklara şifreli erişim |
| **Stajyerler / Öğrenciler** | 100 | `10.30.20.0/24` | `10.30.20.1` | `10.30.20.2 - 10.30.20.254` | **20** | **Zero Trust:** Yalnızca hız limitli (QoS) internet; `10.x` ağlarına kapalı |
| **IoT / Kamera / Akıllı Tahta** | ~12 Cihaz | `10.30.60.0/28` | `10.30.60.1` | `10.30.60.2 - 10.30.60.14` | **60** | Sınıf akıllı ekranları, güvenlik kameraları ve yazıcılar |
| **Misafir Wi-Fi (Guest)** | Ziyaretçi | `10.30.70.0/27` | `10.30.70.1` | `10.30.70.2 - 10.30.70.30` | **70** | Seminer/etkinlik katılımcıları için izole internet erişimi |
| **OOB Ağ Yönetimi** | Altyapı | `10.30.99.0/28` | `10.30.99.1` | `10.30.99.2 - 10.30.99.14` | **99** | FortiGate 100F HA ve kampüs switch yönetim arayüzleri |

---

### 📍 ŞUBE 4: Dubai (Uluslararası Ticaret ve MEA Saha Üssü)
**Kapasite:** 35 Personel (15 Satış/Destek + 20 Red Team & Ar-Ge) | **Süper Ağ:** `10.40.0.0/16`  
**Bant Genişliği & Yedeklilik:** Dual-ISP SD-WAN (Birincil: 200/200 Mbps Fiber + İkincil: Kurumsal 5G/LTE Failover)
> *Gerekçe:* MEA bölgesi Red Team operasyon verilerinin Sivas merkezine gecikmesiz aktarımı, bölgesel Ar-Ge geliştirme süreçleri ve küresel müşteri görüşmeleri için yüksek erişilebilirlikli bağlantı sağlanmıştır.

| Birim / Ekip | Personel / Varlık | IP Bloğu (CIDR) | Gateway | Kullanılabilir IP Aralığı | VLAN ID | Güvenlik & İzolasyon Politikası |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Uluslararası Satış** | 10 | `10.40.10.0/28` | `10.40.10.1` | `10.40.10.2 - 10.40.10.14` | **10** | Küresel CRM ve video konferans trafiği |
| **Red Team (MEA)** | 12 | `10.40.20.0/27` | `10.40.20.1` | `10.40.20.2 - 10.40.20.30` | **20** | MEA saha operasyon verileri IPsec tüneliyle Sivas'a aktarılır |
| **Yerel Teknik Destek** | 5 | `10.40.30.0/28` | `10.40.30.1` | `10.40.30.2 - 10.40.30.14` | **30** | Yerel ofis sistem ve ağ destek birimi |
| **Ar-Ge (Yazılım)** | 8 | `10.40.40.0/28` | `10.40.40.1` | `10.40.40.2 - 10.40.40.14` | **40** | Red Team ve Satış ağlarından ayrıştırılmış Ar-Ge VLAN'ı |
| **IoT / Kamera / Yazıcı** | ~10 Cihaz | `10.40.60.0/28` | `10.40.60.1` | `10.40.60.2 - 10.40.60.14` | **60** | Ofis güvenlik kameraları, akıllı kilit ve yazıcılar |
| **Misafir Wi-Fi (Guest)** | Ziyaretçi | `10.40.70.0/28` | `10.40.70.1` | `10.40.70.2 - 10.40.70.14` | **70** | Müşteri/ziyaretçi ağı; iç VLAN'lara erişim kapalı |
| **OOB Ağ Yönetimi** | Altyapı | `10.40.99.0/28` | `10.40.99.1` | `10.40.99.2 - 10.40.99.14` | **99** | FortiGate 60F HA ve yerel switch yönetim arayüzleri |

---

## 🛡️ 2. Güvenlik Duvarı (Firewall) Donanım Konumlandırması ve Yüksek Erişilebilirlik (HA)

Tek nokta arızasını (Single Point of Failure - SPOF) ortadan kaldırmak amacıyla **tüm şubelerde 2 düğümlü Active-Passive HA Cluster (FGCP - FortiGate Clustering Protocol)** mimarisi kullanılmıştır. Donanım arızası durumunda aktif oturumlar (stateful session sync) 1 saniyenin altında yedek cihaza devredilir.

| Lokasyon | Seçilen Donanım (HA Pair) | HA Modu & Failover | Birim Fiyat | 3 Yıllık UTP Paket (Cihaz Başı) | HA Küme Toplam TCO (3 Yıl) | Konfigürasyon Odağı |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Sivas (SOC Hub)** | **2x FortiGate 200F** | Active-Passive (FGCP) | $4,800 | $11,400 | **$22,800** | 3 Gbps Threat Protection, 13 Gbps IPsec, donanımsal SSL Decryption |
| **İstanbul (HQ)** | **2x FortiGate 80F** | Active-Passive (FGCP) | $1,250 | $2,950 | **$5,900** | 1.5M Concurrent Session ile Red Team taramalarını kayıpsız karşılama |
| **Ankara (Akademi)** | **2x FortiGate 100F** | Active-Passive (FGCP) | $2,600 | $6,200 | **$12,400** | Yüksek fiziksel port yoğunluğu + 100 stajyer için App Control & QoS |
| **Dubai (Saha)** | **2x FortiGate 60F** | Active-Passive (FGCP) | $700 | $1,650 | **$3,300** | SOC4 ASIC ile 6.5 Gbps IPsec VPN + 5G/LTE SD-WAN yedekliliği |

---

## ⚙️ 3. Güvenlik Duvarı Model Karşılaştırmaları ve Maliyet Analizi (En İyi 5 Alternatif)

### 1. İstanbul (HQ ve Red Team) — Seçilen: **FortiGate 80F (HA Cluster)**
Red Team ekipleri Nmap, Masscan ve Burp Suite ile saniyede binlerce eşzamanlı oturum (Concurrent Session) açar.

| Değerlendirilen Model | Üretici | Birim Donanım | 3 Yıllık UTP/Lisans | Tercih Edilme / Elenme Gerekçesi |
| :--- | :--- | :--- | :--- | :--- |
| **FortiGate 80F (Seçilen)** | Fortinet | **$1,250** | **$2,950** | **1.5M Concurrent Session** ve 4 GB RAM ile Red Team taramalarını düşürmez; 715 Mbps Threat Protection 250 Mbps hattı rahatça karşılar. |
| **FortiGate 60F** | Fortinet | $700 | $1,650 | 2 GB RAM kapasitesi, 60 kullanıcı üzerine binen agresif Red Team taramalarında "Session Drop" riski yaratır. |
| **PA-440** | Palo Alto Networks | $2,200 | $6,400 | Güçlü NGFW ancak 3 yıllık toplam sahip olma maliyeti (TCO) şube ölçeği için 2 katından fazladır. |
| **Secure Firewall 1210** | Cisco | $2,400 | $5,800 | Benzer performans sunmasına karşın lisanslama ve SD-WAN entegrasyon maliyeti yüksektir. |
| **Quantum Spark 1600** | Check Point | $1,950 | $4,500 | Kompakt KOBİ ağ geçidi; Sivas merkezi Fortinet Security Fabric yapısıyla yerel uyumu zayıftır. |

---

### 2. Sivas (SOC ve Ar-Ge Merkez Hub) — Seçilen: **FortiGate 200F (HA Cluster)**
Tüm şubelerin IPsec tünellerinin sonlandığı ve SOC ekibinin SSL Decryption (Deep Packet Inspection) yaptığı merkez üssüdür.

| Değerlendirilen Model | Üretici | Birim Donanım | 3 Yıllık UTP/Lisans | Tercih Edilme / Elenme Gerekçesi |
| :--- | :--- | :--- | :--- | :--- |
| **FortiGate 200F (Seçilen)** | Fortinet | **$4,800** | **$11,400** | **3 Gbps Threat Protection** ve **13 Gbps IPsec** kapasitesi ile 500 Mbps hattı SSL Decryption açıkken darboğaza sokmadan denetler. |
| **FortiGate 100F** | Fortinet | $2,600 | $6,200 | ~1 Gbps Threat Protection kapasitesi, 105 kullanıcı + SSL Decryption + 4 şubenin VPN logları birleştiğinde %80+ CPU yüküne ulaşır. |
| **FortiGate 400F** | Fortinet | $11,500 | $26,800 | 500+ kullanıcılı büyük veri merkezleri içindir; 105 kişilik üs için gereksiz bütçe maliyetidir. |
| **PA-1410** | Palo Alto Networks | $7,900 | $19,500 | SOC sınıfı muadil NGFW ancak donanım ve abonelik maliyeti FG-200F HA kümesinin oldukça üzerindedir. |
| **Quantum Force 9100** | Check Point | $9,200 | $21,000 | Yüksek SSL inceleme performansı sunmasına karşın toplam TCO değeri yüksektir. |

---

### 3. Ankara (Eğitim ve Akademi) — Seçilen: **FortiGate 100F (HA Cluster)**
100 stajyerin aynı anda ISO/VM indirmesi ve eğitim videoları izlemesi nedeniyle katı Application Control ve QoS gerektirir.

| Değerlendirilen Model | Üretici | Birim Donanım | 3 Yıllık UTP/Lisans | Tercih Edilme / Elenme Gerekçesi |
| :--- | :--- | :--- | :--- | :--- |
| **FortiGate 100F (Seçilen)** | Fortinet | **$2,600** | **$6,200** | **1 Gbps Threat Protection** ve yüksek fiziksel port sayısı ile eğitmen, stajyer, IoT ve yönetim ağlarını fiziksel arayüzlerden izole eder. |
| **FortiGate 80F** | Fortinet | $1,250 | $2,950 | 715 Mbps Threat Protection ve daha az fiziksel port sayısı nedeniyle 100 eşzamanlı stajyer trafiğinde marjı dardır. |
| **FortiGate 60F** | Fortinet | $700 | $1,650 | 110 kullanıcı, cihazın önerilen 50-60 kullanıcı sınırının çok üzerindedir; P2P engelleme ve QoS altında CPU darboğazı yaşar. |
| **PA-440** | Palo Alto Networks | $2,200 | $6,400 | Fiziksel port sayısı daha azdır ve 3 yıllık lisans maliyeti yüksektir. |
| **Quantum Spark 1600** | Check Point | $1,950 | $4,500 | Sınıf ve laboratuvar fiziksel arayüz ayrımı için port yoğunluğu yetersizdir. |

---

### 4. Dubai (Uluslararası Ticaret ve Saha) — Seçilen: **FortiGate 60F (HA Cluster)**
MEA Red Team operasyon verilerinin Sivas merkezine sıfır gecikmeyle şifreli aktarımı temel önceliktir.

| Değerlendirilen Model | Üretici | Birim Donanım | 3 Yıllık UTP/Lisans | Tercih Edilme / Elenme Gerekçesi |
| :--- | :--- | :--- | :--- | :--- |
| **FortiGate 60F (Seçilen)** | Fortinet | **$700** | **$1,650** | Dahili **SOC4 ASIC** çipi ile **6.5 Gbps IPsec VPN** hızı sunar; 35 kullanıcı ve 200 Mbps hat için en ideal fiyat/performans çözümüdür. |
| **FortiGate 40F** | Fortinet | $500 | $1,150 | 10-15 kişilik SOHO ofisler içindir; 35 personel ve sürekli Red Team veri transferi için sınırda kalır. |
| **PA-410** | Palo Alto Networks | $1,100 | $3,100 | Küçük şube NGFW modeli; 3 yıllık paket maliyeti FG-60F'in yaklaşık 2 katıdır. |
| **Quantum Spark 1550** | Check Point | $1,150 | $2,750 | Donanımsal IPsec hızlandırma kapasitesi SOC4 çipli FG-60F'in gerisindedir. |
| **XGS 116** | Sophos | $1,050 | $2,600 | Masaüstü şube cihazı; Sivas merkezdeki Fortinet SD-WAN orkestrasyonuna yerel uyumu yoktur. |

---

## 📜 4. Güvenlik Duvarı Kural Tabloları (First-Match Wins)

Tüm güvenlik duvarlarında kurallar **yukarıdan aşağıya (First-Match Wins)** işlenir. Her şubede:
1. Temel ağ servisleri (**DHCP `UDP/67,68`**, **DNS `UDP/TCP 53`**, **NTP `UDP/123`**) açıkça tanımlanmıştır.
2. **OOB Yönetim VLAN 99** erişimi yalnızca yetkili yöneticilerle sınırlandırılmış, diğer tüm VLAN'lerden engellenmiştir.
3. **IoT/Kamera (VLAN 60)** ve **Misafir Wi-Fi (VLAN 70)** segmentlerinin şirket iç ağına erişimi bloklanmıştır.
4. En alt satırda eşleşmeyen tüm gelen, giden ve yönlendirilen trafiği düşürüp loglayan **Explicit Default-Deny (`ANY -> ANY`)** kuralı yer alır.

### 4.1 İstanbul HQ (`FortiGate 80F HA`) Kural Seti

| Sıra | Aksiyon | Yön | Protokol / Port | Kaynak (`From`) | Hedef (`To`) | Açıklama & Denetim Amacı |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `ALLOW` | Inbound | `UDP 67,68` | `all-vlans` | `local-dhcp-server` | **Temel Servis (DHCP):** VLAN bazlı otomatik IP dağıtımı |
| **2** | `ALLOW` | Forward | `UDP/TCP 53` | `all-vlans` | `internal-dns-resolvers` | **Temel Servis (DNS):** İç DNS sunucuları üzerinden isim çözümleme |
| **3** | `ALLOW` | Forward | `UDP 123` | `all-vlans` | `internal-ntp-servers` | **Temel Servis (NTP):** SIEM log korelasyonu için zaman senkronizasyonu |
| **4** | `ALLOW` | Forward | `TCP 22,443` | `vlan99-oob-mgmt` | `network-infra-mgmt` | **OOB Yönetim:** Ağ cihazlarına SSH/HTTPS erişimi yalnızca VLAN 99'dan |
| **5** | `DENY` | Forward | `ANY` | `user-guest-iot-vlans` | `vlan99-oob-mgmt` | **OOB İzolasyonu:** Kullanıcı, misafir ve IoT ağlarının VLAN 99'a erişimi yasak |
| **6** | `ALLOW` | Forward | `ANY` | `critical-vlans` | `critical-vlans` | Kritik VLAN trafiği `Log Allowed Traffic` ile SOC tarafından izlenir |
| **7** | `ALLOW` | Forward | `UDP 500,4500` | `branch-lan` | `sivas-hub` | Sivas SOC Hub ile şifreli IPsec VPN / SD-WAN tüneli |
| **8** | `ALLOW` | Forward | `ANY` | `vlan40-redteam` | `red-team-targets` | Yetkili Red Team taramaları (SPAN mirror port ile Wireshark/Zeek kayıtlı) |
| **9** | `ALLOW` | Forward | `TCP 22,443` | `vlan50-rnd` | `sivas-rnd-git-registry` | İstanbul Ar-Ge VLAN 50'nin Sivas GitLab ve Docker Registry erişimi |
| **10** | `ALLOW` | Outbound | `TCP/UDP 80,443` | `vlan70-guest` | `internet` | Misafir Wi-Fi için Client Isolation aktif yalnızca web internet çıkışı |
| **11** | `DENY` | Forward | `ANY` | `vlan60-iot, vlan70-guest` | `internal-vlans` | IoT/Kamera ve Misafir ağlarının şirket iç VLAN'larına erişimi engelli |
| **12** | `DENY` | **ANY** | `ANY` | `ANY` | `ANY` | **Explicit Default-Deny:** Eşleşmeyen tüm trafik düşürülür ve loglanır |

### 4.2 Sivas SOC ve Ar-Ge Hub (`FortiGate 200F HA`) Kural Seti

| Sıra | Aksiyon | Yön | Protokol / Port | Kaynak (`From`) | Hedef (`To`) | Açıklama & Denetim Amacı |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `ALLOW` | Inbound | `UDP 67,68` | `all-vlans` | `local-dhcp-server` | **Temel Servis (DHCP):** VLAN bazlı otomatik IP dağıtımı |
| **2** | `ALLOW` | Forward | `UDP/TCP 53` | `all-vlans` | `internal-dns-resolvers` | **Temel Servis (DNS):** İç DNS sunucuları üzerinden isim çözümleme |
| **3** | `ALLOW` | Forward | `UDP 123` | `all-vlans` | `internal-ntp-servers` | **Temel Servis (NTP):** Stratum-1/2 merkezi saat senkronizasyonu |
| **4** | `ALLOW` | Forward | `TCP 22,443` | `vlan99-oob-mgmt` | `network-infra-mgmt` | **OOB Yönetim:** Firewall, IPMI/iDRAC ve SIEM sunucu yönetimi |
| **5** | `DENY` | Forward | `ANY` | `user-guest-iot-vlans` | `vlan99-oob-mgmt` | **OOB İzolasyonu:** Yönetim dışı VLAN'ların VLAN 99'a erişimi engelli |
| **6** | `ALLOW` | Forward | `UDP 500,4500` | `branch-lan` | `sivas-hub` | Şubeler arası SD-WAN / IPsec VPN omurga geçişi |
| **7** | `ALLOW` | Inbound | `UDP 500,4500` | `branch-vpns` | `sivas-hub` | Tüm şube IPsec tünelleri burada sonlanır; loglar Wazuh/FortiAnalyzer'a akar |
| **8** | `ALLOW` | Forward | `ANY` | `critical-vlans` | `critical-vlans` | Kritik VLAN'lerde yanal hareket (Lateral Movement) tespiti için tam loglama |
| **9** | `ALLOW` | Forward | `TCP 443` | `vlan20-soc` | `any` | SOC SSL Decryption / DPI analizi (KVKK/GDPR istisna listesi aktif) |
| **10** | `ALLOW` | Outbound | `TCP/UDP 80,443` | `vlan70-guest` | `internet` | Misafir/denetçi Wi-Fi için izole internet erişimi |
| **11** | `DENY` | Forward | `ANY` | `vlan60-iot, vlan70-guest` | `internal-vlans` | IoT/CCTV ve Misafir ağlarının SOC ve Ar-Ge ağlarına erişimi engelli |
| **12** | `DENY` | **ANY** | `ANY` | `ANY` | `ANY` | **Explicit Default-Deny:** Eşleşmeyen tüm trafik düşürülür ve loglanır |

### 4.3 Ankara Eğitim Akademisi (`FortiGate 100F HA`) Kural Seti

| Sıra | Aksiyon | Yön | Protokol / Port | Kaynak (`From`) | Hedef (`To`) | Açıklama & Denetim Amacı |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `ALLOW` | Inbound | `UDP 67,68` | `all-vlans` | `local-dhcp-server` | **Temel Servis (DHCP):** VLAN bazlı otomatik IP dağıtımı |
| **2** | `ALLOW` | Forward | `UDP/TCP 53` | `all-vlans` | `internal-dns-resolvers` | **Temel Servis (DNS):** İç DNS sunucuları üzerinden isim çözümleme |
| **3** | `ALLOW` | Forward | `UDP 123` | `all-vlans` | `internal-ntp-servers` | **Temel Servis (NTP):** SIEM log korelasyonu için zaman senkronizasyonu |
| **4** | `ALLOW` | Forward | `TCP 22,443` | `vlan99-oob-mgmt` | `network-infra-mgmt` | **OOB Yönetim:** Ağ cihazlarına yönetim erişimi yalnızca VLAN 99'dan |
| **5** | `DENY` | Forward | `ANY` | `user-intern-guest-iot-vlans` | `vlan99-oob-mgmt` | **OOB İzolasyonu:** Stajyer, misafir ve IoT ağlarının VLAN 99'a erişimi yasak |
| **6** | `DENY` | Forward | `ANY` | `vlan20-interns` | `internal-vlans` | **Zero Trust İzolasyonu:** Stajyerler hiçbir iç `10.x` VLAN'ına erişemez |
| **7** | `DENY` | Outbound | `ANY` | `vlan20-interns` | `p2p` | Stajyer ağında P2P / Torrent trafiği Application Control ile bloklanır |
| **8** | `LIMIT` | Outbound | `ANY` | `vlan20-interns` | `internet` | **Traffic Shaping / QoS:** ISO indirmelerinin hattı kilitlemesini önler |
| **9** | `ALLOW` | Outbound | `ANY` | `vlan20-interns` | `internet` | Stajyer VLAN 20'ye yalnızca hız limitli internet çıkışı verilir |
| **10** | `ALLOW` | Forward | `UDP 500,4500` | `branch-lan` | `sivas-hub` | Eğitmen ağı ve firewall logları için Sivas merkez IPsec tüneli |
| **11** | `ALLOW` | Outbound | `TCP/UDP 80,443` | `vlan70-guest` | `internet` | Seminer/etkinlik misafirleri için izole internet çıkışı |
| **12** | `DENY` | Forward | `ANY` | `vlan60-iot, vlan70-guest` | `internal-vlans` | IoT/Akıllı Tahta ve Misafir ağlarının iç ağa erişimi engelli |
| **13** | `DENY` | **ANY** | `ANY` | `ANY` | `ANY` | **Explicit Default-Deny:** Eşleşmeyen tüm trafik düşürülür ve loglanır |

### 4.4 Dubai Uluslararası Ticaret Ofisi (`FortiGate 60F HA`) Kural Seti

| Sıra | Aksiyon | Yön | Protokol / Port | Kaynak (`From`) | Hedef (`To`) | Açıklama & Denetim Amacı |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `ALLOW` | Inbound | `UDP 67,68` | `all-vlans` | `local-dhcp-server` | **Temel Servis (DHCP):** VLAN bazlı otomatik IP dağıtımı |
| **2** | `ALLOW` | Forward | `UDP/TCP 53` | `all-vlans` | `internal-dns-resolvers` | **Temel Servis (DNS):** İç DNS sunucuları üzerinden isim çözümleme |
| **3** | `ALLOW` | Forward | `UDP 123` | `all-vlans` | `internal-ntp-servers` | **Temel Servis (NTP):** SIEM log korelasyonu için zaman senkronizasyonu |
| **4** | `ALLOW` | Forward | `TCP 22,443` | `vlan99-oob-mgmt` | `network-infra-mgmt` | **OOB Yönetim:** Ağ cihazlarına yönetim erişimi yalnızca VLAN 99'dan |
| **5** | `DENY` | Forward | `ANY` | `user-guest-iot-vlans` | `vlan99-oob-mgmt` | **OOB İzolasyonu:** Kullanıcı, misafir ve IoT ağlarının VLAN 99'a erişimi yasak |
| **6** | `ALLOW` | Forward | `UDP 500,4500` | `branch-lan` | `sivas-hub` | Sivas SOC Hub ile 6.5 Gbps donanım hızlandırmalı IPsec tüneli |
| **7** | `ALLOW` | Forward | `ANY` | `critical-vlans` | `critical-vlans` | Kritik VLAN trafiği `Log Allowed Traffic` ile SOC tarafından izlenir |
| **8** | `ALLOW` | Forward | `TCP 22,443` | `vlan40-rnd` | `sivas-rnd-git-registry` | Dubai Ar-Ge VLAN 40'ın Sivas GitLab ve Docker Registry erişimi |
| **9** | `ALLOW` | Outbound | `TCP/UDP 80,443` | `vlan70-guest` | `internet` | Müşteri/misafir Wi-Fi için izole web internet çıkışı |
| **10** | `DENY` | Forward | `ANY` | `vlan60-iot, vlan70-guest` | `internal-vlans` | IoT/Kamera ve Misafir ağlarının şirket iç VLAN'larına erişimi engelli |
| **11** | `DENY` | **ANY** | `ANY` | `ANY` | `ANY` | **Explicit Default-Deny:** Eşleşmeyen tüm trafik düşürülür ve loglanır |

---

## 🔐 5. Rol Tabanlı Uzaktan Erişim (RBAC ZTNA & VPN Mimarisi)

Şubeler arası trafik **Site-to-Site IPsec VPN / SD-WAN** ile Sivas merkez üssünde sonlanırken, uzaktan çalışan personelin erişimi düz VPN yerine **FortiClient ZTNA (Zero Trust Network Access) + SAML 2.0 SSO + Phishing-Resistant MFA (FIDO2/TOTP)** ve cihaz uyumluluk kontrolü (Device Posture Check) ile rol bazlı sınırlandırılmıştır:

| Kullanıcı Rolü | Yetkili Hedef Ağ / Uygulama | Cihaz Sağlık & Güvenlik Şartı (Posture Check) |
| :--- | :--- | :--- |
| **SOC Analisti** | `10.20.20.0/25` (Sivas SOC), Wazuh SIEM & FortiAnalyzer | Kurumsal EDR aktif, tam disk şifreleme (BitLocker/LUKS), güncel OS |
| **Red Team Operatörü** | `10.10.40.0/27` (TR/EU), `10.40.20.0/27` (MEA), Yetkili Jump Host | Sertleştirilmiş Kali/Linux profili, tam disk şifreleme, FIDO2 MFA |
| **Ar-Ge Yazılımcısı** | `10.20.10.0/26`, `10.10.50.0/28`, `10.40.40.0/28`, GitLab & Harbor | Kurumsal SSH sertifikası, sağlıklı EDR ajanı, MFA |
| **IT & Ağ Yöneticisi** | `10.x.99.0/28` (OOB Yönetim VLAN'ları — yalnızca PAM Bastion üzeri) | Just-in-Time (JIT) ayrıcalık yükseltme + donanımsal FIDO2 anahtarı |
| **Yönetim / Muhasebe / Satış** | `10.10.10.0/27`, `10.40.10.0/28`, ZTNA Proxy üzeri Bulut ERP/CRM | Kurumsal cihaz sertifikası + MFA |
| **Stajyer / Öğrenci** | Yalnızca bulut laboratuvar portalı (İç `10.x` ağlarına erişim sıfır) | Dönem bazlı süreli hesap + MFA |

---

## 👁️ 6. Merkezi İzleme (Monitoring) ve 3 Katmanlı SOC Mimarisi

İzleme mimarisinin operasyonel merkezi **Sivas (7/24 SOC — 65 Analist)** şubesidir. Güvenlik görünürlüğü üç katmanda kurgulanmıştır:

### Katman 1: Merkezi Loglama ve Telemetri (Firewall & SIEM)
* **Merkezi Toplama:** Dört şubedeki HA firewall kümelerinin logları şifreli IPsec tünelleri üzerinden anlık olarak Sivas'taki **Wazuh SIEM** ve **FortiAnalyzer** sunucularına aktarılır.
* **İç Ağ Görünürlüğü:** Kritik VLAN'ler arası kurallarda `Log Allowed Traffic` aktif edilerek olası yanal hareketler (Lateral Movement) tespit edilir.

### Katman 2: Derinlemesine Ağ Analizi (NDR — NetFlow & SPAN)
* **sFlow / NetFlow:** Ankara eğitim ağı ve İstanbul/Dubai Red Team çıkışlarındaki ani trafik sıçramalarını (DDoS, veri sızıntısı) yakalamak için tüm omurga anahtarlarda ve firewall'larda aktiftir.
* **SPAN / Port Mirroring:** Red Team operasyon VLAN'lerinde paket seviyesinde inceleme yapabilmek için **Wireshark / Zeek** sensörlerine bağlı mirror portlar sürekli aktiftir.

### Katman 3: Uç Nokta İzleme (EDR/XDR) ve Zero Trust
* **Uç Nokta Telemetrisi:** Yönetim, Muhasebe, SOC ve Ar-Ge uç noktalarında **Sysmon + Wazuh Agent** kurulu olup süreç oluşturma, kayıt defteri ve ağ bağlantısı olayları merkezi SIEM'e akıtılır.
* **SOAR Otomasyonu:** Kritik alarmlar Sivas SOC konsollarında otomatik müdahale (SOAR) playbook'ları ile eşleştirilir.

---

## 🛠️ 7. Operasyonel Süreklilik, Yama Yönetimi ve CVE Watch

### 7.1 Log Saklama ve Arşivleme Planı (Log Retention)
* **Sıcak Depolama (Hot — 90 Gün):** Sivas Wazuh SIEM ve FortiAnalyzer NVMe kümelerinde anlık sorgulanabilir ve korelasyona açık tutulur.
* **Ilık Depolama (Warm — 1 Yıl):** Sıkıştırılmış indeksler halinde Sivas veri merkezi depolama havuzunda saklanır.
* **Soğuk Arşiv (Cold Archive — 2 ila 5 Yıl):** 5651 sayılı kanun ve KVKK/GDPR gereklilikleri doğrultusunda **SHA-256 kriptografik özet (hash)** ile imzalanarak **WORM (Write-Once-Read-Many)** değiştirilemez depolama birimlerinde ve şifreli dış lokasyon kasasında arşivlenir.

### 7.2 Firewall Konfigürasyon Yedekleme ve Felaket Kurtarma (DR)
* **Otomatik Yedekleme:** Her gün **03:00 TRT**'de ve her konfigürasyon değişikliği sonrasında tüm FortiGate cihazlarının `.conf` dosyaları **AES-256** ile şifrelenerek alınır ve **GitOps Policy-as-Code** deposunda sürüm kontrolüne tabii tutulur.
* **3-2-1 Yedekleme Stratejisi:** 3 kopya, 2 farklı depolama ortamı (Sivas ana kasa + İstanbul ikincil depolama) ve 1 değiştirilemez off-site arşiv. Çeyreklik DR geri yükleme tatbikatları ile **RTO < 15 dakika**, **RPO < 24 saat** hedeflenir.

### 7.3 Firmware ve Yama Yönetimi Rutini
* **Sürüm Politikası:** Tüm şubelerde yeni özellik odaklı *Feature* sürümleri yerine kararlı **FortiOS Mature (M)** dalı kullanılır.
* **Bakım Penceresi:** Her ayın **3. Pazar günü 02:00–05:00 TRT** aralığında önce laboratuvar ortamında doğrulanan yamalar, Active-Passive HA kümeleri üzerinde kesintisiz (hitless rolling upgrade) uygulanır.
* **Acil Durum SLA:** Kritik/KEV zafiyetler (**CVSS ≥ 9.0**) **24 saat**, Yüksek zafiyetler (**CVSS 7.0–8.9**) **7 gün** içinde yamalanır.

### 7.4 Aktif CVE Takip Tablosu (`CVE Watch`)

| CVE Kodu | CVSS | Etkilenen Bileşen | Durum | Uygulanan Teknik Önlem |
| :--- | :--- | :--- | :--- | :--- |
| **CVE-2024-21762** | 9.8 | FortiOS SSL-VPN | `Patched & Mitigated` | Tüm cihazlar FortiOS 7.4.x Mature sürümüne yükseltildi; WAN arayüzlerinde eski SSL-VPN kapatılarak ZTNA + SAML MFA'ya geçildi. |
| **CVE-2024-55591** | 9.8 | FortiOS / FortiProxy Auth Bypass | `Patched & Mitigated` | WAN arayüzlerinde HTTP/HTTPS yönetim erişimi kapatıldı, yönetim yalnızca OOB VLAN 99'a izole edildi ve yama uygulandı. |
| **CVE-2024-47575** | 9.8 | FortiManager (FortiJump) | `Patched & Mitigated` | `TCP/541` erişimi yalnızca IPsec hub tünelleri ve OOB VLAN 99 ile sınırlandırıldı; Wazuh üzerinde `fgfm` anomali kuralı eklendi. |
| **CVE-2025-24472** | 8.1 | FortiOS CSF Auth Bypass | `Patched` | FortiOS Mature güvenlik yaması uygulandı, `trusted-hosts` kısıtlaması sıkılaştırıldı ve yetkisiz giriş denemeleri SIEM'e bağlandı. |
| **CVE-2023-27997** | 9.8 | FortiOS SSL-VPN Heap Overflow | `Patched` | 4 şubenin tamamında yamalı sürüm doğrulaması ve Sivas SOC üzerinden sürekli IOC taraması aktif edildi. |

---

## ⚖️ 8. Mevzuat Uyumu ve Veri Gizliliği (KVKK / GDPR / 5651)

* **KVKK (6698 Sayılı Kanun) & GDPR:** Wazuh SIEM ve FortiAnalyzer üzerindeki loglarda kişisel verilerin (PII) maskelenmesi ve rol bazlı erişim kontrolü (RBAC) uygulanarak veri minimizasyonu sağlanır.
* **SSL/TLS DPI Gizlilik İstisnaları:** Sivas SOC tarafından yürütülen derin paket incelemesinde (SSL Decryption); çalışanların ve stajyerlerin bankacılık, sağlık ve insan kaynakları/e-Devlet portallarına ait trafikleri KVKK ve GDPR mahremiyet ilkeleri gereği şifre çözme (decryption) kapsamı dışında tutulur.
* **5651 Sayılı Kanun Uyumu:** Tüm şubelerdeki DHCP, NAT ve firewall oturum logları zaman damgalı ve SHA-256 bütünlük doğrulamalı olarak en az 2 yıl süreyle değiştirilemez ortamda saklanır.
* **Sınır Ötesi Veri Aktarımı:** Dubai (MEA), İstanbul (EU operasyonları) ve Sivas merkezi arasındaki telemetri ve log aktarımı, GDPR Veri İşleme Sözleşmeleri (DPA) kapsamında **AES-256-GCM** şifreli IPsec tünelleri üzerinden gerçekleştirilir.