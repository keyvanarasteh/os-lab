# Kurumsal A? Topolojisi ve G?venlik Mimarisi (Siber G?venlik ?irketi)

> Contributed by `U*** B***` ([@ufuk888](https://github.com/ufuk888)) ? BGT207 G?venlik Duvar? ??z?mleri ? 2026-2027 G?z midterm project.
> Student names are masked on purpose. Updated to close all 13 architectural and security audit gaps (30 findings) and synchronized 1:1 with `company.json`.

---

## ?? 1. ?ube A? ve Kapasite Planlamalar?

### ?? ?UBE 1: ?stanbul (Ana Merkez - HQ ? `istanbul-hq`)
**Kapasite:** 60 Personel (40 Staff + 20 R&D) | **Supernet:** `10.10.0.0/16` | **Bant Geni?li?i:** 250 Mbps / 250 Mbps (Dual-ISP Active-Active SD-WAN: 250 Mbps Ana + 100 Mbps Yedek Hat)
> *Gerek?e:* Muhasebe/idari birimin bulut tabanl? ERP/finans programlar?n? aktif kullanmas? ve Red Team ekibinin yo?un veri transferleri nedeniyle simetrik y?ksek kapasite ayr?lm??t?r.

| Departman / Segment | Ki?i / Cihaz | Subnet / CIDR | Gateway IP | Kullan?labilir IP Aral??? | VLAN ID | ?ema VLAN Ad? & G?venlik Rol? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Y?netim & Muhasebe** | 25 | `10.10.10.0/27` | `10.10.10.1` | `10.10.10.2 - 10.10.10.30` | **10** | `management-accounting` ? Finans/ERP izole a?? (Sysmon + Wazuh EDR) |
| **Pazarlama** | 10 | `10.10.20.0/28` | `10.10.20.1` | `10.10.20.2 - 10.10.20.14` | **20** | `marketing` ? CRM ve dijital operasyon a?? |
| **?? Sistemler & IT** | 5 | `10.10.30.0/28` | `10.10.30.1` | `10.10.30.2 - 10.10.30.14` | **30** | `it-systems` ? ?? sistem y?neticileri ve yerel NVR/Yaz?c? sunucusu (`10.10.30.10`) |
| **Red Team (TR & EU)** | 12 | `10.10.40.0/27` | `10.10.40.1` | `10.10.40.2 - 10.10.40.30` | **40** | `redteam-tr-eu` ? ?zole ofansif s?zma testi a?? (SPAN mirror aktif) |
| **Ar-Ge (Yaz?l?m)** | 8 | `10.10.50.0/28` | `10.10.50.1` | `10.10.50.2 - 10.10.50.14` | **50** | `rnd-software` ? Red Team'den izole yaz?l?m geli?tirme VLAN'? |
| **IoT / Kamera / Yaz?c?** | ~10 Cihaz | `10.10.60.0/28` | `10.10.60.1` | `10.10.60.2 - 10.10.60.14` | **60** | `iot-cameras-printers` ? Yaln?zca yerel NVR/Yaz?c? (`10.10.30.10`) eri?imli kapal? a? |
| **Misafir Wi-Fi (Guest)** | Ziyaret?i | `10.10.70.0/27` | `10.10.70.1` | `10.10.70.2 - 10.10.70.30` | **70** | `guest-wifi` ? Client Isolation aktif, i? a?a kapal? HTTP/HTTPS internet |
| **OOB A? Y?netimi** | Altyap? | `10.10.99.0/28` | `10.10.99.1` | `10.10.99.2 - 10.10.99.14` | **99** | `oob-management` ? FortiGate 80F HA, Switch ve AP y?netim aray?zleri |

---

### ?? ?UBE 2: Sivas (SOC ve Ar-Ge Merkezi ? `sivas-soc`)
**Kapasite:** 105 Personel (70 Staff + 35 Software/R&D) | **Supernet:** `10.20.0.0/16` | **Bant Geni?li?i:** 500 Mbps / 500 Mbps (Dual-ISP BGP/SD-WAN: 500 Mbps Ana + 250 Mbps Yedek Hat)
> *Gerek?e:* T?m ?ubelerden (?stanbul, Ankara, Dubai) akan SIEM/EDR loglar?n?n toplanmas?, 65 ki?ilik SOC ekibinin aktif tehdit avc?l??? ve Ar-Ge Docker imaj transferleri nedeniyle en y?ksek kapasite buraya tahsis edilmi?tir.

| Departman / Segment | Ki?i / Cihaz | Subnet / CIDR | Gateway IP | Kullan?labilir IP Aral??? | VLAN ID | ?ema VLAN Ad? & G?venlik Rol? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ar-Ge (Yaz?l?m)** | 35 | `10.20.10.0/26` | `10.20.10.1` | `10.20.10.2 - 10.20.10.62` | **10** | `rnd-software` ? GitLab, CI/CD runner ve Harbor container registry eri?imi |
| **SOC Analistleri** | 65 | `10.20.20.0/25` | `10.20.20.1` | `10.20.20.2 - 10.20.20.126` | **20** | `soc` ? Wazuh SIEM, FortiAnalyzer ve SOAR konsollar? (S?k? ??k?? kontrol?) |
| **Yerel Teknik Destek** | 5 | `10.20.30.0/28` | `10.20.30.1` | `10.20.30.2 - 10.20.30.14` | **30** | `local-support` ? Veri merkezi fiziksel destek birimi ve NVR/Yaz?c? (`10.20.30.10`) |
| **IoT / Kamera / Sens?r** | ~14 Cihaz | `10.20.60.0/27` | `10.20.60.1` | `10.20.60.2 - 10.20.60.30` | **60** | `iot-cameras-printers` ? 30 host kapasiteli (`/27`); CCTV, UPS sens?rleri ve yaz?c?lar (`10.20.30.10`) |
| **Misafir Wi-Fi (Guest)** | Ziyaret?i | `10.20.70.0/28` | `10.20.70.1` | `10.20.70.2 - 10.20.70.14` | **70** | `guest-wifi` ? Denet?i/misafir a??; i? VLAN'lara eri?im tamamen engelli |
| **OOB A? Y?netimi** | Altyap? | `10.20.99.0/28` | `10.20.99.1` | `10.20.99.2 - 10.20.99.14` | **99** | `oob-management` ? FortiGate 200F HA, IPMI/iDRAC, Switch ve SIEM sunucu y?netimi |

---

### ?? ?UBE 3: Ankara (Akademi ? `ankara-academy`)
**Kapasite:** 110 Ki?i (10 Staff/Akademisyen + 100 Stajyer/??renci) | **Supernet:** `10.30.0.0/16` | **Bant Geni?li?i:** 300 Mbps / 300 Mbps (Dual-ISP SD-WAN: 300 Mbps Ana + 100 Mbps Yedek Hat)
> *Gerek?e:* Stajyerlerin ayn? anda ?evrimi?i e?itim videolar? izlemesi, b?y?k boyutlu sanal makine (VM/ISO) indirmeleri ve bulut laboratuvar eri?imleri i?in trafik ?ekillendirme (QoS) destekli geni? hat ayr?lm??t?r.

| Departman / Segment | Ki?i / Cihaz | Subnet / CIDR | Gateway IP | Kullan?labilir IP Aral??? | VLAN ID | ?ema VLAN Ad? & G?venlik Rol? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **E?itmen & ?dari** | 10 | `10.30.10.0/28` | `10.30.10.1` | `10.30.10.2 - 10.30.10.14` | **10** | `academics` ? E?itmen/personel a?? ve yerel NVR/Yaz?c? sunucusu (`10.30.10.10`) |
| **Stajyerler / ??renciler** | 100 | `10.30.20.0/24` | `10.30.20.1` | `10.30.20.2 - 10.30.20.254` | **20** | `interns-students` ? Zero Trust: i? `10.x` a?lar?na kapal?, h?z limitli internet |
| **IoT / Kamera / Yaz?c?** | ~10 Cihaz | `10.30.60.0/28` | `10.30.60.1` | `10.30.60.2 - 10.30.60.14` | **60** | `iot-cameras-printers` ? Kamp?s IP kameralar?, ak?ll? tahtalar ve yaz?c?lar (`10.30.10.10`) |
| **Misafir Wi-Fi (Guest)** | Ziyaret?i | `10.30.70.0/27` | `10.30.70.1` | `10.30.70.2 - 10.30.70.30` | **70** | `guest-wifi` ? Seminer/ziyaret?i a?? (Client Isolation aktif) |
| **OOB A? Y?netimi** | Altyap? | `10.30.99.0/28` | `10.30.99.1` | `10.30.99.2 - 10.30.99.14` | **99** | `oob-management` ? FortiGate 100F HA ve kamp?s kenar switch y?netimi |

---

### ?? ?UBE 4: Dubai (Saha ve Ticaret Ofisi ? `dubai-field`)
**Kapasite:** 35 Personel (15 Staff + 20 R&D/Red Team) | **Supernet:** `10.40.0.0/16` | **Bant Geni?li?i:** 200 Mbps / 200 Mbps (Dual-ISP SD-WAN: 200 Mbps Fiber + 5G/LTE Yedek Hat)
> *Gerek?e:* Uluslararas? m??terilerle kesintisiz video konferans ve Orta Do?u (MEA) operasyonlar?ndan elde edilen test/Ar-Ge verilerinin ?ifreli IPsec VPN t?neli ile Sivas merkezine aktar?lmas? i?in tasarlanm??t?r.

| Departman / Segment | Ki?i / Cihaz | Subnet / CIDR | Gateway IP | Kullan?labilir IP Aral??? | VLAN ID | ?ema VLAN Ad? & G?venlik Rol? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Uluslararas? Sat??** | 10 | `10.40.10.0/28` | `10.40.10.1` | `10.40.10.2 - 10.40.10.14` | **10** | `intl-sales` ? Global CRM ve m??teri ili?kileri a?? |
| **Red Team (MEA)** | 12 | `10.40.20.0/27` | `10.40.20.1` | `10.40.20.2 - 10.40.20.30` | **20** | `redteam-mea` ? Orta Do?u saha s?zma testi ekibi |
| **Yerel Teknik Destek** | 5 | `10.40.30.0/28` | `10.40.30.1` | `10.40.30.2 - 10.40.30.14` | **30** | `local-support` ? Yerel sistem destek ekibi ve NVR/Yaz?c? (`10.40.30.10`) |
| **Ar-Ge (Yaz?l?m)** | 8 | `10.40.40.0/28` | `10.40.40.1` | `10.40.40.2 - 10.40.40.14` | **40** | `rnd-software` ? B?lgesel yaz?l?m geli?tirme birimi (Red Team ve Sat??tan izole) |
| **IoT / Kamera / Yaz?c?** | ~8 Cihaz | `10.40.60.0/28` | `10.40.60.1` | `10.40.60.2 - 10.40.60.14` | **60** | `iot-cameras-printers` ? Ofis kameralar?, ak?ll? kilit ve yaz?c?lar (`10.40.30.10`) |
| **Misafir Wi-Fi (Guest)** | Ziyaret?i | `10.40.70.0/28` | `10.40.70.1` | `10.40.70.2 - 10.40.70.14` | **70** | `guest-wifi` ? M??teri/misafir Wi-Fi a?? (Tam izolasyon) |
| **OOB A? Y?netimi** | Altyap? | `10.40.99.0/28` | `10.40.99.1` | `10.40.99.2 - 10.40.99.14` | **99** | `oob-management` ? FortiGate 60F HA ve yerel switch y?netimi |

---

## ??? 2. Y?ksek Eri?ilebilirlik (HA) & TCO Maliyet Analizi

Tek nokta ar?zas?n? (SPOF) ortadan kald?rmak amac?yla **t?m ?ubelerde (Dubai dahil) 2 d???ml? Active-Passive HA Cluster (FGCP - FortiGate Clustering Protocol)** mimarisi kurulmu?tur (`company.json` i?inde her ?ubede `perimeter` Active ve `ha-standby` Passive d???mleri tan?ml?d?r). Donan?m ar?zas?nda aktif oturumlar (`TCP/UDP 703` session sync & heartbeat) 1 saniyenin alt?nda yedek cihaza devredilir.

| Lokasyon | Se?ilen Donan?m (HA Pair) | HA Modu & Failover | Birim Donan?m | 3 Y?ll?k UTP (Cihaz Ba??) | Cihaz Ba?? 3 Y?l (`priceUsd`) | 2-Node HA K?me Toplam? (3 Y?l) | Konfig?rasyon Oda?? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Sivas (SOC Hub)** | **2x FortiGate 200F** | Active-Passive (FGCP) | $4,800 | $6,600 | **$11,400** | **$22,800** | 3 Gbps Threat Protection, 13 Gbps IPsec, donan?msal SSL Decryption |
| **?stanbul (HQ)** | **2x FortiGate 80F** | Active-Passive (FGCP) | $1,250 | $1,700 | **$2,950** | **$5,900** | 1.5M Concurrent Session ile Red Team taramalar?n? kay?ps?z kar??lama |
| **Ankara (Akademi)** | **2x FortiGate 100F** | Active-Passive (FGCP) | $2,600 | $3,600 | **$6,200** | **$12,400** | Y?ksek fiziksel port yo?unlu?u + 100 stajyer i?in App Control & QoS |
| **Dubai (Saha)** | **2x FortiGate 60F** | Active-Passive (FGCP) | $700 | $950 | **$1,650** | **$3,300** | SOC4 ASIC ile 6.5 Gbps IPsec VPN + 5G/LTE SD-WAN yedeklili?i |
| **GENEL TOPLAM** | **8 FortiGate Cihaz?** | **4x HA Cluster** | **$18,700** | **$25,700** | ? | **$44,400** | **T?m ?ubelerde u?tan uca donan?m + hat yedeklili?i** |

---

## ?? 3. ?ube Bazl? Alternatif Model Kar??la?t?rmas? (Top-5 Analizi)

### 3.1 ?stanbul HQ (`FortiGate 80F` vs Alternatifler)
| De?erlendirilen Model | ?retici | Threat Throughput | Cihaz Ba?? 3 Y?l TCO | Tercih Edilme / Elenme Gerek?esi |
| :--- | :--- | :--- | :--- | :--- |
| **FortiGate 80F (Se?ilen)** | Fortinet | **715 Mbps** | **$2,950** (`$1,250` HW + `$1,700` UTP) | **1.5M Concurrent Session** ve 4 GB RAM ile Red Team taramalar?n? d???rmez; 250 Mbps hatt? rahat?a kar??lar. |
| **FortiGate 60F** | Fortinet | 700 Mbps | $1,650 (`$700` HW + `$950` UTP) | 2 GB RAM kapasitesi, 60 kullan?c? ?zerine binen agresif Red Team taramalar?nda "Session Drop" riski yarat?r. |
| **PA-440** | Palo Alto Networks | 1.3 Gbps | $6,400 (`$2,200` HW + `$4,200` Lisans) | G??l? NGFW ancak 3 y?ll?k toplam sahip olma maliyeti (TCO) ?ube ?l?e?i i?in 2 kat?ndan fazlad?r. |
| **Secure Firewall 1210** | Cisco | 1.2 Gbps | $5,800 (`$2,400` HW + `$3,400` Lisans) | Y?ksek abonelik yenileme maliyeti nedeniyle elenmi?tir. |
| **Quantum Spark 1600** | Check Point | 850 Mbps | $4,500 (`$1,950` HW + `$2,550` Lisans) | Fortinet Security Fabric ve merkezi FortiAnalyzer entegrasyonu bulunmad??? i?in elenmi?tir. |

### 3.2 Sivas SOC ve Ar-Ge Hub (`FortiGate 200F` vs Alternatifler)
| De?erlendirilen Model | ?retici | Threat Throughput | Cihaz Ba?? 3 Y?l TCO | Tercih Edilme / Elenme Gerek?esi |
| :--- | :--- | :--- | :--- | :--- |
| **FortiGate 200F (Se?ilen)** | Fortinet | **3.0 Gbps** | **$11,400** (`$4,800` HW + `$6,600` UTP) | **3 Gbps Threat Protection**, **13 Gbps IPsec** ve ?zel NP6XLite/CP9 ASIC ile SSL Decryption alt?nda darbo?az ya?atmaz. |
| **FortiGate 100F** | Fortinet | 1.0 Gbps | $6,200 (`$2,600` HW + `$3,600` UTP) | SSL Decryption + 3 ?ube IPsec log y?k? birlikte a??ld???nda i?lemci kapasitesi %80 s?n?r?na dayan?r. |
| **FortiGate 400F** | Fortinet | 6.0 Gbps | $26,800 (`$11,500` HW + `$15,300` UTP) | 500+ ki?ilik b?y?k veri merkezleri i?indir; 105 personel i?in gereksiz maliyet olu?turur. |
| **PA-1410** | Palo Alto Networks | 3.4 Gbps | $19,500 (`$7,900` HW + `$11,600` Lisans) | Benzer performansa kar??n 3 y?ll?k TCO de?eri FortiGate 200F'in yakla??k %70 ?zerindedir. |
| **Quantum Force 9100** | Check Point | 4.0 Gbps | $21,000 (`$9,200` HW + `$11,800` Lisans) | Y?ksek lisans maliyeti nedeniyle b?t?e/performans dengesinde elenmi?tir. |

### 3.3 Ankara Akademi (`FortiGate 100F` vs Alternatifler)
| De?erlendirilen Model | ?retici | Threat Throughput | Cihaz Ba?? 3 Y?l TCO | Tercih Edilme / Elenme Gerek?esi |
| :--- | :--- | :--- | :--- | :--- |
| **FortiGate 100F (Se?ilen)** | Fortinet | **1.0 Gbps** | **$6,200** (`$2,600` HW + `$3,600` UTP) | **22 fiziksel aray?z** ile e?itmen, stajyer, IoT ve OOB a?lar?n? fiziksel port baz?nda ay?r?r; QoS/App Control headroom'u y?ksektir. |
| **FortiGate 80F** | Fortinet | 715 Mbps | $2,950 (`$1,250` HW + `$1,700` UTP) | Fiziksel port say?s? daha azd?r ve 100 stajyerin e?zamanl? ISO/video indirmelerinde darbo?aza yakla??r. |
| **FortiGate 60F** | Fortinet | 700 Mbps | $1,650 (`$700` HW + `$950` UTP) | 50-60 kullan?c? ?l?e?i i?indir; 110 ki?ilik kamp?ste yetersiz kal?r. |
| **PA-440** | Palo Alto Networks | 1.3 Gbps | $6,400 (`$2,200` HW + `$4,200` Lisans) | Port yo?unlu?u (8x RJ45) FortiGate 100F'e k?yasla s?n?f bazl? fiziksel izolasyon i?in s?n?rl?d?r. |
| **Quantum Spark 1600** | Check Point | 850 Mbps | $4,500 (`$1,950` HW + `$2,550` Lisans) | Daha d???k aray?z yo?unlu?u nedeniyle tercih edilmemi?tir. |

### 3.4 Dubai Saha Ofisi (`FortiGate 60F` vs Alternatifler)
| De?erlendirilen Model | ?retici | Threat Throughput | Cihaz Ba?? 3 Y?l TCO | Tercih Edilme / Elenme Gerek?esi |
| :--- | :--- | :--- | :--- | :--- |
| **FortiGate 60F (Se?ilen)** | Fortinet | **700 Mbps** | **$1,650** (`$700` HW + `$950` UTP) | **SOC4 ASIC** ile **6.5 Gbps IPsec VPN** sa?lar; MEA Red Team ve Ar-Ge verilerini Sivas'a gecikmesiz aktar?r. |
| **FortiGate 40F** | Fortinet | 600 Mbps | $1,150 (`$500` HW + `$650` UTP) | 10-15 ki?ilik k???k ?ube s?n?f?d?r; 35 personel ve yo?un veri transferi i?in s?n?rda kal?r. |
| **PA-410** | Palo Alto Networks | 650 Mbps | $3,100 (`$1,100` HW + `$2,000` Lisans) | Yerel disk bar?nd?rmamas? ve yakla??k 2 kat y?ksek TCO nedeniyle elenmi?tir. |
| **Quantum Spark 1550** | Check Point | 650 Mbps | $2,750 (`$1,150` HW + `$1,600` Lisans) | IPsec ASIC performans? ve Security Fabric entegrasyonu daha d???kt?r. |
| **XGS 116** | Sophos | 680 Mbps | $2,600 (`$1,050` HW + `$1,550` Lisans) | Fortinet SD-WAN ve merkezi FortiAnalyzer ekosistemi ile uyumlu de?ildir. |

---

## ?? 4. ?ube Bazl? Firewall Kural Setleri (`render-rules.py` Uyumlu Politika S?ras?)

T?m firewall politikalar?nda **"First Match Wins" (?lk E?le?en Kazan?r)** prensibi uygulan?r ve `company.json` ile birebir ayn? VLAN adlar? / CIDR bloklar? kullan?l?r:
1. **Temel Altyap? Servisleri:** DHCP (`UDP 67:68`), DNS (`UDP 53` ve `TCP 53` ayr? kurallar) ve NTP (`UDP 123`) a??k?a tan?ml?d?r.
2. **OOB Y?netim ?zolasyonu:** Yaln?zca yetkili IT/SOC/E?itmen VLAN'lar? (`it-systems`, `soc`, `local-support`, `academics`) VLAN 99 (`oob-management`) cihazlar?na `TCP 22,443` eri?ebilir; di?er t?m VLAN'lar bloklan?r.
3. **IoT/Kamera & Misafir Segmentasyonu:** VLAN 60 (`iot-cameras-printers`) yaln?zca yerel NVR/Yaz?c? sunucusuna (`10.x.30.10` / `10.30.10.10`, `TCP 554,9100`) eri?ebilir; di?er t?m i? `10.0.0.0/8` a?lar?na kapal?d?r.
4. **Explicit Default-Deny (Inbound, Forward & Outbound):** En alt sat?rda e?le?meyen t?m `in`, `forward` ve `out` trafi?i d???r?l?r ve loglan?r.

### 4.1 ?stanbul HQ (`FortiGate 80F HA`) Kural Seti
| S?ra | Aksiyon | Y?n | Protokol / Port | Kaynak (`From`) | Hedef (`To`) | A??klama & Denetim Amac? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `ALLOW` | `in` | `UDP 67:68` | `10.10.0.0/16` | `10.10.0.0/16` | **Temel Servis (DHCP):** ?stanbul VLAN'lar? i?in otomatik IP da??t?m? |
| **2** | `ALLOW` | `forward` | `UDP 53` | `10.10.0.0/16` | `10.10.30.0/28` | **Temel Servis (DNS UDP):** ?? DNS sunucular?na UDP isim ??z?mleme |
| **3** | `ALLOW` | `forward` | `TCP 53` | `10.10.0.0/16` | `10.10.30.0/28` | **Temel Servis (DNS TCP):** ?? DNS sunucular?na TCP isim ??z?mleme |
| **4** | `ALLOW` | `forward` | `UDP 123` | `10.10.0.0/16` | `10.10.30.0/28` | **Temel Servis (NTP):** SIEM log korelasyonu i?in zaman senkronizasyonu |
| **5** | `ALLOW` | `forward` | `TCP 22,443` | `it-systems` | `oob-management` | **OOB Y?netim:** Yetkili IT y?neticilerinin VLAN 99'a SSH/HTTPS eri?imi |
| **6** | `DENY` | `forward` | `ANY` | `10.10.0.0/16` | `oob-management` | **OOB ?zolasyonu:** Di?er t?m ?stanbul VLAN'lar?n?n VLAN 99'a eri?imi yasak |
| **7** | `ALLOW` | `forward` | `TCP 554,9100` | `iot-cameras-printers` | `10.10.30.10` | **IoT NVR/Yaz?c? ?stisnas?:** Kamera ve yaz?c?lar?n yerel sunucuya (`10.10.30.10`) eri?imi |
| **8** | `DENY` | `forward` | `ANY` | `iot-cameras-printers` | `10.0.0.0/8` | **IoT ?zolasyonu:** VLAN 60 cihazlar?n?n di?er t?m i? a?lara eri?imi engelli |
| **9** | `DENY` | `forward` | `ANY` | `guest-wifi` | `10.0.0.0/8` | **Misafir ?zolasyonu:** VLAN 70 misafirlerinin ?irket i? `10.x` a?lar?na eri?imi engelli |
| **10** | `ALLOW` | `forward` | `TCP 80,443` | `guest-wifi` | `any` | **Misafir ?nternet:** Client Isolation aktif yaln?zca web internet ??k??? |
| **11** | `ALLOW` | `forward` | `TCP 1514:1515` | `10.10.0.0/16` | `10.20.20.0/25` | **Merkezi EDR Telemetri:** Wazuh/Sysmon olaylar?n?n IPsec ?zerinden Sivas SOC'a iletimi |
| **12** | `ALLOW` | `forward` | `UDP 514` | `10.10.0.0/16` | `10.20.20.0/25` | **Merkezi Syslog:** FortiGate HA loglar?n?n Sivas FortiAnalyzer'a aktar?m? |
| **13** | `ALLOW` | `forward` | `UDP 500,4500` | `10.10.0.0/16` | `10.20.0.0/16` | **IPsec VPN / SD-WAN:** Sivas SOC Hub ile ?ifreli site-to-site t?nel |
| **14** | `ALLOW` | `forward` | `TCP 22,443` | `rnd-software` | `10.20.10.0/26` | **Ar-Ge Senkronizasyonu:** ?stanbul Ar-Ge (`VLAN 50`) -> Sivas GitLab/Harbor eri?imi |
| **15** | `ALLOW` | `forward` | `ANY` | `redteam-tr-eu` | `any` | **Red Team Operasyonlar?:** Yetkili TR/EU Red Team taramalar? (SPAN mirror kay?tl?) |
| **16** | `ALLOW` | `forward` | `TCP 80,443` | `management-accounting` | `any` | **Kurumsal Web/ERP ??k???:** Y?netim & Muhasebe bulut ERP/finans HTTPS eri?imi |
| **17** | `ALLOW` | `forward` | `TCP 80,443` | `marketing` | `any` | **Kurumsal Web/CRM ??k???:** Pazarlama birimi SaaS/CRM HTTPS eri?imi |
| **18** | `ALLOW` | `forward` | `TCP 80,443` | `it-systems` | `any` | **IT Y?netim Web ??k???:** IT y?neticilerinin ?retici yama/bulut konsol HTTPS eri?imi |
| **19** | `ALLOW` | `out` | `UDP 53,123,500,4500` | `any` | `any` | **Firewall Self-Egress:** FortiGate DNS, NTP ve IPsec t?nel ba?latma trafi?i |
| **20-22** | `DENY` | `in / forward / out` | `ANY` | `any` | `any` | **Explicit Default-Deny:** E?le?meyen t?m gelen, y?nlendirilen ve giden trafik d???r?l?r |

### 4.2 Sivas SOC ve Ar-Ge Hub (`FortiGate 200F HA`) Kural Seti
| S?ra | Aksiyon | Y?n | Protokol / Port | Kaynak (`From`) | Hedef (`To`) | A??klama & Denetim Amac? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `ALLOW` | `in` | `UDP 67:68` | `10.20.0.0/16` | `10.20.0.0/16` | **Temel Servis (DHCP):** Sivas VLAN'lar? i?in otomatik IP da??t?m? |
| **2-3** | `ALLOW` | `forward` | `UDP 53` & `TCP 53` | `10.20.0.0/16` | `10.20.30.0/28` | **Temel Servis (DNS):** UDP 53 ve TCP 53 i? isim ??z?mleme |
| **4** | `ALLOW` | `forward` | `UDP 123` | `10.20.0.0/16` | `10.20.30.0/28` | **Temel Servis (NTP):** T?m ?ubeler i?in Stratum-1/2 zaman senkronizasyonu |
| **5-6** | `ALLOW` | `forward` | `TCP 22,443` | `local-support`, `soc` | `oob-management` | **OOB Y?netim:** Yetkili veri merkezi destek ve SOC m?hendislerinin VLAN 99 eri?imi |
| **7** | `DENY` | `forward` | `ANY` | `10.20.0.0/16` | `oob-management` | **OOB ?zolasyonu:** Di?er t?m Sivas VLAN'lar?n?n VLAN 99'a eri?imi yasak |
| **8** | `ALLOW` | `forward` | `TCP 554,9100` | `iot-cameras-printers` | `10.20.30.10` | **IoT NVR/Yaz?c? ?stisnas?:** CCTV/UPS sens?rleri ve yaz?c?lar?n NVR sunucusuna eri?imi |
| **9-10** | `DENY` | `forward` | `ANY` | `iot-cameras-printers`, `guest-wifi` | `10.0.0.0/8` | **IoT & Misafir ?zolasyonu:** SOC ve Ar-Ge a?lar?na eri?im tamamen engelli |
| **11** | `ALLOW` | `forward` | `TCP 80,443` | `guest-wifi` | `any` | **Misafir ?nternet:** Denet?i/misafir Wi-Fi i?in izole HTTP/HTTPS internet eri?imi |
| **12** | `ALLOW` | `in` | `UDP 500,4500` | `10.0.0.0/8` | `10.20.0.0/16` | **IPsec Hub Sonland?rma:** T?m ?ube IPsec VPN / SD-WAN t?nelleri burada sonlan?r |
| **13-14** | `ALLOW` | `forward` | `TCP 1514:1515`, `UDP 514` | `10.0.0.0/8` | `soc` | **Merkezi Log Toplama:** T?m ?ubelerden gelen Wazuh EDR ve Syslog ak??lar? |
| **15-16** | `ALLOW` | `forward` | `TCP 22,443` | `10.10.50.0/28`, `10.40.40.0/28` | `rnd-software` | **?ubeler Aras? Ar-Ge:** ?stanbul ve Dubai Ar-Ge ekiplerinin Sivas GitLab/Harbor eri?imi |
| **17-18** | `ALLOW` | `forward` | `TCP 80,443` | `rnd-software`, `local-support` | `any` | **Ar-Ge & Destek Web ??k???:** Onayl? paket/container registry ve ?retici yama eri?imi |
| **19** | `ALLOW` | `forward` | `TCP 443` | `soc` | `10.0.0.0/8` | **SOC S?k? ??k?? Kontrol?:** SOC istasyonlar? yaln?zca i? `10.0.0.0/8` altyap?s?n? sorgular (veri s?z?nt?s? ?nlemi) |
| **20** | `ALLOW` | `out` | `UDP 53,123,500,4500` | `any` | `any` | **Firewall Self-Egress:** FortiGate 200F DNS, NTP ve IPsec kontrol trafi?i |
| **21-23** | `DENY` | `in / forward / out` | `ANY` | `any` | `any` | **Explicit Default-Deny:** E?le?meyen t?m gelen, y?nlendirilen ve giden trafik d???r?l?r |

### 4.3 Ankara Akademi (`FortiGate 100F HA`) Kural Seti
| S?ra | Aksiyon | Y?n | Protokol / Port | Kaynak (`From`) | Hedef (`To`) | A??klama & Denetim Amac? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1-4** | `ALLOW` | `in / forward` | `UDP 67:68`, `UDP/TCP 53`, `UDP 123` | `10.30.0.0/16` | `10.30.10.0/28` | **Temel Servisler:** DHCP, ayr? UDP/TCP 53 DNS ve NTP eri?imi |
| **5-6** | `ALLOW / DENY` | `forward` | `TCP 22,443` / `ANY` | `academics` / `10.30.0.0/16` | `oob-management` | **OOB Y?netimi:** Yaln?zca `academics` y?neticileri VLAN 99'a eri?ir; stajyer/misafir/IoT yasak |
| **7-8** | `ALLOW / DENY` | `forward` | `TCP 554,9100` / `ANY` | `iot-cameras-printers` | `10.30.10.10` / `10.0.0.0/8` | **IoT ?zolasyonu:** Kameralar/yaz?c?lar yaln?zca `10.30.10.10` sunucusuna eri?ir |
| **9** | `DENY` | `forward` | `ANY` | `interns-students` | `10.0.0.0/8` | **Zero Trust ?zolasyonu:** Stajyerler (`VLAN 20`) hi?bir i? `10.x` VLAN'?na eri?emez |
| **10** | `DENY` | `forward` | `ANY 6881:6889,6969` | `interns-students` | `any` | **P2P / Torrent Engeli:** Stajyer trafi?inde BitTorrent/P2P portlar? bloklan?r |
| **11** | `LIMIT` | `forward` | `TCP 80,443` | `interns-students` | `any` | **QoS H?z Limitli ?nternet:** Stajyer HTTP/HTTPS trafi?i h?z limiti i?inde kabul edilir; a?an paketler Default-Deny'a d??er |
| **12-13** | `DENY / ALLOW` | `forward` | `ANY` / `TCP 80,443` | `guest-wifi` | `10.0.0.0/8` / `any` | **Misafir Wi-Fi:** ?? a?a kapal?, izole HTTP/HTTPS internet eri?imi |
| **14-16** | `ALLOW` | `forward` | `TCP 1514:1515`, `UDP 514`, `UDP 500,4500` | `10.30.0.0/16` | `10.20.20.0/25`, `10.20.0.0/16` | **Merkezi SIEM & IPsec VPN:** Wazuh/Syslog telemetrisi ve Sivas hub VPN t?neli |
| **17** | `ALLOW` | `forward` | `TCP 80,443` | `academics` | `any` | **E?itmen Web ??k???:** E?itmen ve idari personelin bulut e?itim portallar?na HTTPS eri?imi |
| **18-21** | `ALLOW / DENY` | `out` & `in/forward/out` | `UDP 53,123,500,4500` / `ANY` | `any` | `any` | **Firewall Self-Egress & Explicit Default-Deny** |

### 4.4 Dubai Saha Ofisi (`FortiGate 60F HA`) Kural Seti
| S?ra | Aksiyon | Y?n | Protokol / Port | Kaynak (`From`) | Hedef (`To`) | A??klama & Denetim Amac? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1-4** | `ALLOW` | `in / forward` | `UDP 67:68`, `UDP/TCP 53`, `UDP 123` | `10.40.0.0/16` | `10.40.30.0/28` | **Temel Servisler:** DHCP, ayr? UDP/TCP 53 DNS ve NTP eri?imi |
| **5-6** | `ALLOW / DENY` | `forward` | `TCP 22,443` / `ANY` | `local-support` / `10.40.0.0/16` | `oob-management` | **OOB Y?netimi:** Yaln?zca `local-support` y?neticileri VLAN 99'a eri?ir |
| **7-8** | `ALLOW / DENY` | `forward` | `TCP 554,9100` / `ANY` | `iot-cameras-printers` | `10.40.30.10` / `10.0.0.0/8` | **IoT ?zolasyonu:** Kameralar/yaz?c?lar yaln?zca `10.40.30.10` sunucusuna eri?ir |
| **9-10** | `DENY / ALLOW` | `forward` | `ANY` / `TCP 80,443` | `guest-wifi` | `10.0.0.0/8` / `any` | **Misafir Wi-Fi:** ?? a?a kapal?, izole HTTP/HTTPS internet eri?imi |
| **11-13** | `ALLOW` | `forward` | `TCP 1514:1515`, `UDP 514`, `UDP 500,4500` | `10.40.0.0/16` | `10.20.20.0/25`, `10.20.0.0/16` | **Merkezi SIEM & 6.5 Gbps IPsec VPN:** Wazuh/Syslog telemetrisi ve Sivas hub VPN t?neli |
| **14** | `ALLOW` | `forward` | `TCP 22,443` | `rnd-software` | `10.20.10.0/26` | **Ar-Ge Senkronizasyonu:** Dubai Ar-Ge (`VLAN 40`) -> Sivas GitLab/Harbor eri?imi |
| **15** | `ALLOW` | `forward` | `ANY` | `redteam-mea` | `any` | **MEA Red Team Operasyonlar?:** Yetkili saha test trafi?i (SPAN kay?tl?) |
| **16-17** | `ALLOW` | `forward` | `TCP 80,443` | `intl-sales`, `local-support` | `any` | **Sat?? & Destek Web ??k???:** Global CRM, video konferans ve destek HTTPS eri?imi |
| **18-21** | `ALLOW / DENY` | `out` & `in/forward/out` | `UDP 53,123,500,4500` / `ANY` | `any` | `any` | **Firewall Self-Egress & Explicit Default-Deny** |

---

## ?? 5. Rol Tabanl? Uzaktan Eri?im (RBAC ZTNA & VPN Mimarisi)

?ubeler aras? trafik **Site-to-Site IPsec VPN / SD-WAN (`AES-256-GCM`)** ile Sivas merkez ?ss?nde (`10.20.0.0/16`) sonlan?rken, uzaktan ?al??an personelin eri?imi d?z VPN yerine **FortiClient ZTNA + SAML 2.0 SSO + Phishing-Resistant FIDO2 Donan?m MFA (TOTP kapal?)** ve cihaz uyumluluk kontrol? (Device Posture Check) ile rol bazl? s?n?rland?r?lm??t?r:

| Kullan?c? Rol? | Kimlik Do?rulama & Posture | ?zin Verilen Hedef A? / Servis | Yasakl? Alanlar |
| :--- | :--- | :--- | :--- |
| **SOC Analistleri** | SAML 2.0 SSO + FIDO2 MFA + Kurumsal EDR | Sivas SOC (`10.20.20.0/25` ? Wazuh/SOAR) | Muhasebe, Ar-Ge kaynak kodlar? |
| **Red Team Uzmanlar?** | SAML 2.0 SSO + FIDO2 MFA + Sertifikal? Laptop | Red Team A?lar? (`10.10.40.0/27`, `10.40.20.0/27`) | Kurumsal ERP/?K ve OOB VLAN 99 |
| **Ar-Ge M?hendisleri** | SAML 2.0 SSO + FIDO2 MFA + Disk ?ifreleme | Sivas GitLab/Harbor (`10.20.10.0/26`) & Ar-Ge VLAN'lar? | SOC SIEM ve finans sunucular? |
| **A? / Sistem Y?neticileri** | SAML 2.0 SSO + FIDO2 MFA + JIT PAM Bastion | T?m ?ube OOB VLAN 99 (`10.x.99.0/28`) | Do?rudan internete a??k SSH/HTTPS |
| **Y?netim & Sat??** | SAML 2.0 SSO + FIDO2 MFA | Bulut ERP/CRM ZTNA Uygulama Proxy'si | Do?rudan i? sunucu VLAN'lar? |
| **Stajyerler (Akademi)** | SAML 2.0 SSO + FIDO2 MFA | Yaln?zca Bulut E?itim Portal? (Public HTTPS) | T?m i? `10.x` kurumsal VLAN'lar |

---

## ?? 6. ?? Katmanl? ?zleme, Log Saklama ve Olay M?dahalesi

1. **Katman 1 ? Firewall & VPN Loglar?:** T?m ?ube FortiGate HA k?meleri g?venlik olaylar?n? `UDP 514` ?zerinden Sivas **FortiAnalyzer**'a aktar?r.
2. **Katman 2 ? A? Telemetrisi & Trafik Analizi:** Switch ve firewall'lardan **NetFlow/sFlow**, Red Team VLAN'lar?ndan **SPAN Mirror Port** ile **Wireshark/Zeek** paket analizi yap?l?r.
3. **Katman 3 ? U? Nokta & Sunucu EDR/XDR:** Kritik sunucular ve i? istasyonlar?nda **Sysmon + Wazuh EDR** ajanlar? `TCP 1514:1515` ?zerinden Sivas **Wazuh SIEM**'e ba?l?d?r.
4. **Log Saklama Politikas? (Retention):** **90 g?n** s?cak NVMe depolama, **1 y?l** s?k??t?r?lm?? ?l?k depolama, **5 y?l** SHA-256 imzal? de?i?mez (WORM) so?uk ar?iv (5651 say?l? Kanun ve KVKK/GDPR uyumlu).

---

## ?? 7. Yedekleme, Felaket Kurtarma (DR) ve Yama Y?netimi

* **Yedekleme & DR:** Her gece **03:00 TRT**'de t?m FortiGate HA yap?land?rmalar?, sertifikalar ve SIEM kurallar? **AES-256** ile ?ifrelenerek **3-2-1** kural?na g?re yedeklenir. **RTO < 15 dakika**, **RPO < 24 saat** hedeflenir; y?lda 2 kez Sivas-?stanbul aras? DR tatbikat? yap?l?r.
* **Yama & Zafiyet Y?netimi (CVE Watch):** Her ay?n **3. Pazar g?n? 02:00 - 05:00 TRT** aral???nda FGCP HA ?zerinde kesintisiz (hitless rolling upgrade) **FortiOS Mature** s?r?m g?ncellemesi uygulan?r; CVSS >= 9.0 kritik zafiyetler 24 saat i?inde yama veya sanal yama (IPS/WAF) ile kapat?l?r.

| CVE ID | CVSS | Etkilenen ?r?n / Bile?en | Durum | Uygulanan Teknik ?nlem |
| :--- | :--- | :--- | :--- | :--- |
| **CVE-2024-4577** | 9.8 | PHP-CGI (Akademi & Web Portallar?) | `patched` | PHP ?al??ma zaman? yamaland?, WAF sanal yama aktif edildi ve Wazuh SIEM ?zerinde istismar taramas? do?ruland?. |
| **CVE-2024-21762** | 9.8 | FortiOS SSL-VPN | `patched` | 8 FortiGate cihaz?n?n tamam? FortiOS 7.4.x Mature s?r?m?ne ge?irildi; WAN SSL-VPN kapat?larak ZTNA + FIDO2 MFA'ya ge?ildi. |
| **CVE-2024-55591** | 9.8 | FortiOS / FortiProxy Auth Bypass | `patched` | WAN aray?zlerinde HTTP/HTTPS y?netim eri?imi kapat?ld?, y?netim yaln?zca OOB VLAN 99'a izole edildi ve yama uyguland?. |
| **CVE-2024-47575** | 9.8 | FortiManager (FortiJump) | `mitigated` | `TCP/541` eri?imi yaln?zca IPsec hub t?nelleri ve OOB VLAN 99 ile s?n?rland?r?ld?; Wazuh ?zerinde `fgfm` anomali kural? eklendi. |
| **CVE-2025-24472** | 8.1 | FortiOS CSF Auth Bypass | `patched` | FortiOS Mature g?venlik yamas? uyguland?, `trusted-hosts` k?s?tlamas? s?k?la?t?r?ld? ve yetkisiz giri? denemeleri SIEM'e ba?land?. |

---

## ?? 8. KVKK, GDPR ve 5651 Uyumluluk Kontrolleri

* **Veri Minimizasyonu & PII Maskeleme:** SIEM/Wazuh ingest a?amas?nda T.C. Kimlik No, e-posta ve oturum ?erezleri maskelenir; analistler yaln?zca rol bazl? yetki (RBAC) ile eri?ir.
* **SSL Decryption (DPI) ?stisnalar?:** Bankac?l?k, e-Devlet, sa?l?k portallar? ve ?K/finans uygulamalar? KVKK/GDPR gizlilik ilkeleri gere?i SSL sertifika incelemesinden muaf tutulur.
* **S?n?r ?tesi Veri Transferi (Dubai -> Sivas):** Dubai ofisinden Sivas SOC merkezine aktar?lan g?venlik loglar? **AES-256-GCM** ?ifreli IPsec t?neli ?zerinden ve KVKK Madde 9 / GDPR SCCs kapsam?nda yaln?zca g?venlik telemetrisiyle s?n?rl? olarak aktar?l?r.
