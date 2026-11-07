# 🌐 Kurumsal Ağ Topolojisi ve Güvenlik Mimarisi Dokümantasyonu

Küresel ölçekte siber güvenlik çözümleri sunan şirketimiz; İstanbul merkezli genel müdürlük yapısı, Sivas'taki 7/24 Güvenlik Operasyon Merkezi (SOC) ve Ar-Ge üssü, Ankara'daki Siber Güvenlik Eğitim Akademisi ve Dubai'deki uluslararası ticaret ofisi olmak üzere dört ana lokasyonda faaliyet göstermektedir. Kurumlara yönelik uçtan uca, hem ofansif hem de defansif güvenlik hizmetleri sağlayan firmamızın temel faaliyet alanları arasında; Avrupa ve Orta Doğu (MEA) bölgelerine özel operasyonlar yürüten Fiziksel Sızma Testi (Red Team) faaliyetleri, sürekli ağ izleme ve tehdit analizi, siber güvenlik yazılımları geliştirme süreçleri ve stajyer programlarıyla sektöre yeni uzmanlar kazandıran akademik eğitim hizmetleri yer almaktadır.
---

## 🏢 1. Şube Ağ ve Kapasite Planlamaları

### 📍 ŞUBE 1: İstanbul (Ana Merkez - HQ)
**Kapasite:** 60 Personel | **Bant Genişliği:** 250 Mbps / 250 Mbps (Simetrik Fiber)
> *Gerekçe:* Muhasebe/idari birimin bulut tabanlı ERP/finans programlarını aktif kullanması ve Red Team ekibinin yoğun veri transferleri nedeniyle yüksek kapasite ayrılmıştır.

| Birim / Ekip | Personel | IP Bloğu (CIDR) | Gateway | IP Aralığı | VLAN ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Yönetim & Muhasebe** | 25 | `10.10.10.0/27` | `10.10.10.1` | `10.10.10.2 - 10.10.10.30` | **10** |
| **Yerel Pazarlama** | 10 | `10.10.20.0/28` | `10.10.20.1` | `10.10.20.2 - 10.10.20.14` | **20** |
| **Merkezi IT / Sistem** | 5 | `10.10.30.0/28` | `10.10.30.1` | `10.10.30.2 - 10.10.30.14` | **30** |
| **Red Team (TR/EU)** | 20 | `10.10.40.0/27` | `10.10.40.1` | `10.10.40.2 - 10.10.40.30` | **40** |

---

### 📍 ŞUBE 2: Sivas (Teknoloji ve Operasyon Üssü)
**Kapasite:** 105 Personel | **Bant Genişliği:** 500 Mbps / 500 Mbps (Yüksek Kapasiteli Simetrik Hat)
> *Gerekçe:* Şirketin en kalabalık ve en çok ağ trafiği üreten üssüdür. SOC ekibi tüm şirket genelinden gelen devasa log/telemetri verilerini toplar; Ar-Ge ekibi sürekli büyük yazılım paketleri/Docker imajları indirip yükler.

| Birim / Ekip | Personel | IP Bloğu (CIDR) | Gateway | IP Aralığı | VLAN ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Ar-Ge (Yazılım)** | 35 | `10.20.10.0/26` | `10.20.10.1` | `10.20.10.2 - 10.20.10.62` | **10** |
| **SOC Analistleri** | 65 | `10.20.20.0/25` | `10.20.20.1` | `10.20.20.2 - 10.20.20.126`| **20** |
| **Yerel Teknik Destek** | 5 | `10.20.30.0/28` | `10.20.30.1` | `10.20.30.2 - 10.20.30.14` | **30** |

---

### 📍 ŞUBE 3: Ankara (Eğitim ve Akademik Üs)
**Kapasite:** 110 Kullanıcı | **Bant Genişliği:** 300 Mbps / 300 Mbps
> *Gerekçe:* Öğrencilerin laboratuvar ortamlarına bağlanması, VM indirmesi ve eğitim videoları izlemesi ciddi bant genişliği tüketir. Ancak ana omurgayı kilitlememesi için Traffic Shaping / QoS (Rate Limiting) uygulanmalıdır.

| Birim / Ekip | Personel | IP Bloğu (CIDR) | Gateway | IP Aralığı | VLAN ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Akademik & Eğitmenler** | 10 | `10.30.10.0/28` | `10.30.10.1` | `10.30.10.2 - 10.30.10.14` | **10** |
| **Stajyerler / Öğrenciler** | 100 | `10.30.20.0/24` | `10.30.20.1` | `10.30.20.2 - 10.30.20.254`| **20** |

---

### 📍 ŞUBE 4: Dubai (Uluslararası Ticaret ve Saha Üssü)
**Kapasite:** 35 Personel | **Bant Genişliği:** 200 Mbps / 200 Mbps
> *Gerekçe:* Uluslararası Red Team ekibinin operasyonel veri alışverişi ve küresel müşterilerle yapılan kesintisiz video konferanslar için güçlü bir kurumsal hat gereklidir.

| Birim / Ekip | Personel | IP Bloğu (CIDR) | Gateway | IP Aralığı | VLAN ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Uluslararası Satış** | 10 | `10.40.10.0/28` | `10.40.10.1` | `10.40.10.2 - 10.40.10.14` | **10** |
| **Red Team (MEA)** | 20 | `10.40.20.0/27` | `10.40.20.1` | `10.40.20.2 - 10.40.20.30` | **20** |
| **Yerel Teknik Destek** | 5 | `10.40.30.0/28` | `10.40.30.1` | `10.40.30.2 - 10.40.30.14` | **30** |

---

## 🛡️ 2. Güvenlik Duvarı (Firewall) Donanım Konumlandırması

Şubeler arası IPSec VPN / SD-WAN mimarisini sorunsuz kurabilmek ve merkezi yönetim sağlayabilmek için aşağıdaki Fortinet donanımları konumlandırılmıştır:

| Lokasyon | Önerilen Donanım | Gerekçe ve Konfigürasyon Odakları |
| :--- | :--- | :--- |
| **Sivas (SOC Üssü)** | **FortiGate 200F** | Tüm şubelerden gelen IPSec VPN tünelleri burada sonlanır. SOC ekibinin SSL Decryption yapabilmesi ve 500 Mbps hattın Threat Protection açıkken darboğaza girmemesi için yüksek donanım gücü şarttır. |
| **İstanbul (HQ)** | **FortiGate 80F** | 60 kullanıcı ve 250 Mbps için idealdir. Red Team'in üreteceği yüksek "concurrent session" (eşzamanlı oturum) için cihazın bellek kapasitesi rahat bırakılmalıdır. |
| **Ankara (Eğitim)** | **FortiGate 80F / 100F** | Bant genişliği 300 Mbps olsa da, stajyer ağı üzerinde uygulanacak katı Application Control ve Traffic Shaping politikaları nedeniyle yüksek işlemci gücüne ihtiyaç vardır. |
| **Dubai (Saha)** | **FortiGate 60F** | 35 kullanıcı ve 200 Mbps hat için idealdir. Sivas merkez ile sürekli stabil bir SD-WAN/VPN tüneli kuracak şekilde yapılandırılmıştır. |

---
##  ⚙️ 3. Güvenlik Duvarı (Firewall) Tercih Sebepleri ve Kapasite Planlaması

### 1. İstanbul (HQ ve Red Team)
**Seçilen Model: FortiGate 80F**

Red Team (Fiziksel Sızma Testi) ekipleri Nmap, Masscan, Burp Suite gibi araçlarla tarama yaparken saniyede binlerce "Concurrent Session" (Eşzamanlı Oturum) açar. Bu durum standart güvenlik duvarlarının RAM'ini anında doldurur.

| Karşılaştırılan Model | Neden Tercih Edilmedi? / Farkı Nedir? |
| :--- | :--- |
| **Alt Model: FG-60F** | Bellek (RAM) kapasitesi daha düşüktür. 60 kullanıcının normal trafiği üzerine 20 kişilik Red Team'in ofansif ağ taramaları eklendiğinde cihaz "Session Drop" (oturum düşürme) yaşatabilirdi. |
| **Seçilen: FG-80F** | **1.5 Milyon Eşzamanlı Oturum** kapasitesi ile Red Team'in agresif ağ taramalarını sorunsuz tolere eder. 250 Mbps fiber hattı 715 Mbps Threat Protection kapasitesiyle rahatlıkla filtreler. |

---

### 2. Sivas (SOC ve Ar-Ge) - Merkez Hub
**Seçilen Model: FortiGate 200F**

SOC ekibinin analiz yapabilmesi için tüm trafiğin (SSL şifreli trafik dahil) açılarak incelenmesi (Deep Packet Inspection) gerekir. Sivas, diğer 3 şubenin VPN tünellerinin sonlandığı merkez noktadır.

| Karşılaştırılan Model | Neden Tercih Edilmedi? / Farkı Nedir? |
| :--- | :--- |
| **Alt Model: FG-100F** | Threat Protection (IPS+AV+Web) kapasitesi ~1 Gbps'dir. 500 Mbps simetrik hat, 105 kullanıcı ve tüm şubelerden gelen yoğun VPN logları birleştiğinde cihaz %80 CPU kullanımlarına ulaşıp darboğaz yaratabilirdi. |
| **Seçilen: FG-200F** | **Threat Protection: 3 Gbps, IPSec VPN: 13 Gbps.** 500 Mbps hattı hiçbir gecikme yaşatmadan denetler. SOC için gereken SSL Decryption yükünü donanımsal olarak rahatça kaldırır. |
| **Üst Model: FG-400F** | 105 kullanıcı ve 500 Mbps hat için bütçe israfı olurdu. FG-400F daha çok 500+ kullanıcılı Veri Merkezleri içindir. |

---

### 3. Ankara (Eğitim ve Akademi)
**Seçilen Model: FortiGate 100F (veya 80F)**

100'den fazla stajyerin aynı anda video izlemesi, sanal makine (ISO) indirmesi ve laboratuvar ortamlarına bağlanması, hattın hızla tıkanmasına yol açar. Burada en önemli faktör Application Control (Uygulama Kontrolü) ve Traffic Shaping (Trafik Şekillendirme/QoS) gücüdür.

| Karşılaştırılan Model | Neden Tercih Edilmedi? / Farkı Nedir? |
| :--- | :--- |
| **Alt Model: FG-60F** | 110 kullanıcı cihazın önerilen limitlerinin (genelde maks 50-60 kişi) çok üzerindedir. Stajyerlerin P2P/Torrent engellemeleri ve hız limitleri eklendiğinde CPU yetersiz kalır. |
| **Seçilen: FG-100F** | Cihaz üzerindeki fiziksel port sayısı fazladır. Eğitim salonları, stajyer Wi-Fi ağları ve eğitmen ağları fiziksel olarak ayrı arayüzlere bağlanıp tam izolasyon sağlanabilir. |

---

### 4. Dubai (Uluslararası Saha)
**Seçilen Model: FortiGate 60F**

Şirketin en küçük ama uluslararası verisinin aktığı noktadır. Temel gereksinim, Sivas merkeze kesintisiz, stabil ve şifreli bir SD-WAN/VPN tüneli kurmaktır.

| Karşılaştırılan Model | Neden Tercih Edilmedi? / Farkı Nedir? |
| :--- | :--- |
| **Alt Model: FG-40F** | 10-15 kişilik küçük ofisler (SOHO) içindir. Dubai'deki 35 personel ve özellikle 200 Mbps hattan Sivas'a sürekli video konferans/operasyonel veri aktaran Red Team için VPN throughput performansı sınırda kalır. |
| **Seçilen: FG-60F** | **IPSec VPN kapasitesi 6.5 Gbps'dir.** Şube donanımı olmasına rağmen, içindeki SOC4 çipi sayesinde Dubai'den Sivas'a (merkeze) aktarılan sızma testi verilerini sıfır gecikme ile şifreler. 35 kullanıcı için fiyat/performans olarak en ideal cihazdır. |

---


## 👁️ 4. Merkezi İzleme (Monitoring) ve SOC Mimarisi

İzleme mimarisinin operasyonel merkezi **Sivas (SOC)** şubesidir. Ağ izleme ve güvenlik operasyonları 3 temel katmanda kurgulanmıştır:

### Katman 1: Merkezi Loglama ve Ağ Telemetrisi
* **Merkezi Yönetim:** Dört şubedeki Firewall logları anlık olarak Sivas'taki merkezi **Wazuh SIEM** veya **FortiAnalyzer** sunucusuna aktarılır.
* **Güvenli İletim:** Log iletiminin izlenememesi için şubeler arası trafiğin tamamı IPSec VPN üzerinden şifreli aktarılır.
* **Görünürlük:** Firewall'lar üzerinde tüm kritik VLAN'ler için "Log Allowed Traffic" kuralı aktif edilerek, SOC ekibinin şüpheli iç ağ hareketlerini görmesi sağlanır.

### Katman 2: Derinlemesine Ağ Analizi (NDR)
* **sFlow / NetFlow:** Ankara'daki eğitim ağı veya İstanbul'daki Red Team ağından dışarıya doğru oluşabilecek beklenmedik trafik artışlarını (DDoS, Veri Sızıntısı) tespit etmek için switch ve firewall'larda aktif edilir.
* **SPAN / Port Mirroring:** Red Team'in sızma testi operasyonlarının incelenebilmesi için operasyon VLAN'lerinde **Wireshark/Zeek** ile trafik analizi yapılabilmesi adına mirror port tanımları hazırda bekletilir.

### Katman 3: Uç Nokta İzleme (EDR/XDR) ve Zero Trust
* **Agent Tabanlı İzleme:** Ağ tarafındaki izolasyon (VLAN segmentasyonu) sağlandıktan sonra, Muhasebe, Ar-Ge ve Yönetim cihazlarına **Sysmon ve Wazuh Agent** kurularak loglar SOC'a yönlendirilir.
* **Zero Trust Segmentasyonu:** Özellikle Ankara şubesindeki Stajyer VLAN'inin (VLAN 20), şirket iç ağındaki (10.x.x.x) diğer hiçbir VLAN'e erişemeyeceği garanti altına alınmıştır. Bu ağa sadece internet çıkış izni verilmiştir.

  
