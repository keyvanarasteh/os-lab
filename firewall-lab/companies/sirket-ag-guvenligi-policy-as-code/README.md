# Şirket Ağ Güvenliği — Policy-as-Code Çok Şubeli Tasarım

> BGT207 Güvenlik Duvarı Çözümleri · Mahmut Çirka ([@mahmutcirka](https://github.com/mahmutcirka))
>
> Bu klasördeki `company.json` elle yazılmadı. Tasarımın kaynak deposunda her firewall'un kural seti YAML olarak
> tutuluyor, 187 akış testiyle doğrulanıyor ve hem bu dosyaya hem de cihaza yüklenecek FortiOS / PAN-OS config'ine
> aynı kaynaktan derleniyor. Kaynak depo özel (private); ders hocasının erişimi var.

## Şirket

Bir eğitim ve teknoloji şirketi: **Ankara**'da genel merkez ve veri merkezi, **İstanbul** ve **Londra**'da satış
ofisleri, Ankara'da **10.000 öğrencili bir kampüs**, İstanbul'da hibrit çalışan bir **yazılım ekibi** (müşteri
uygulaması AWS'de) ve Ankara'da ayrı katta bir **Ar-Ge** birimi.

| Birim | Personel | Öğrenci | Akademisyen | Yazılım / Teknik | Ar-Ge |
|---|---:|---:|---:|---:|---:|
| Ankara (genel merkez) | 220 | – | – | 35 | – |
| İstanbul | 160 | – | – | 25 | – |
| Londra | 60 | – | – | 10 | – |
| Kampüs | 300 | 10.000 | 450 | 40 | – |
| Yazılım | 10 | – | – | 120 | – |
| Ar-Ge | 5 | – | – | 10 | 45 |

Toplam ~11.500 kişi, kişi başı ~2 cihazla ~23.000 cihaz. `company.json`'da akademisyenler `staff`, yazılım / teknik
personel `software` olarak sayıldı.

## Ağ Gerekçesi

**Her site tek bir bloktan numaralanır** (10.10/16, 10.20/16, 10.30/16, kampüs 10.40/14, 10.50/16, 10.60/16) ve tüm
VLAN'lar o bloktan kesilir. Böylece her site Ankara hub'ına tek bir özet rota ile duyurulur ve siteler arası VPN'de
çakışma olmaz.

**Alt ağlar kişiye değil cihaza göre boyutlandı**: kişi başı 2 cihaz + %30 büyüme.
- 220 kişilik Ankara personeli ~570 adres ister → /24 yetmez, **/22**.
- 450 akademisyen 2-3 cihazla → **/21**.
- 10.000 öğrenci ~26.000 cihaz → **10.42.0.0/16** (65.534 adres; dönem başı ve sınav günü zirvesi için pay). Öğrenci
  ağı ilk taslakta 10.100/16'daydı, yani kampüs bloğunun dışındaydı. Kampüs bloğu /14'e genişletilip öğrenciler
  10.42/16'ya taşındı.

**Segmentasyon role göredir.** Her rol ayrı VLAN ve ayrı kural setidir:
- personel
- öğrenci
- Ar-Ge
- yazılım (geliştirici / DEV / TEST / CI-CD ayrı)
- sunucu
- misafir
- yazıcı ve IoT
- yönetim

Öne çıkan kararlar:
- **Kampüs:** Öğrenci ağı aynı PA-5420'de **ayrı bir sanal firewall'dadır (VSYS)**. `company.json`'da bu, aynı
  cihazın iki segmenti olarak görünür: `perimeter` ve `students`. Öğrenci, kurumsal ağa yalnızca DMZ'deki LMS ön
  yüzü ve öğrenci DNS çözümleyicisi üzerinden dokunur. Not sistemine (OBS) öğrencinin doğrudan yolu yoktur; not
  girişi yalnızca akademisyen kimliğiyle yapılır.
- **Ar-Ge:** Kendi iç segmentasyon firewall'unun (ISFW) arkasındadır ve Ankara dahil şirketin geri kalanını
  güvenilmez sayar. İnternete **yalnızca açık web proxy üzerinden** çıkar; proxy'de kullanıcı bazlı log, DLP,
  sandbox ve GPU sunucuları için akademik allow-list vardır. Zararlı yazılım analizi ve IoT prototipleri, ayrı bir
  OPNsense arkasında, gerçek internete hiç çıkmayan izole bir laboratuvardadır (sahte internet: INetSim).
- **Yazılım:** PROD'a yalnızca CI/CD hattı erişir; geliştirici PROD'a hem ofis hem bulut firewall'unda ayrı ayrı
  reddedilir. DEV / TEST ortamları internete çıkamaz, paketler yalnızca iç artifact proxy'den gelir (tedarik
  zinciri kontrolü). QA'nın test telefonları ve yazıcılar ayrı bir IoT VLAN'ındadır.
- **DMZ:** İnternetin dokunduğu her şey bir DMZ'dedir ve iç ağa geri bağlanamaz:
  - Ankara'da web sitesi
  - kampüste LMS ön yüzü
  - AWS'de ingress / reverse proxy

## Web Siteleri ve Uygulamalar

| Yayın | Nerede | Koruma |
|---|---|---|
| Kurumsal web sitesi (`www.sirket.example`) | Ankara DMZ | WAF (FortiWeb profili) + IPS + DoS politikası (yeni bağlantı hız limiti) |
| LMS ve mobil öğrenci uygulaması API'si (`lms.sirket.example`) | Kampüs DMZ | Reverse proxy + WAF + PAN-OS Zone Protection (sınav günü taşkınına karşı) |
| Müşteri web uygulaması ve mobil uygulama API'si (`app.` / `api.sirket.example`) | AWS DMZ | WAF + IPS + hız limiti; ingress yalnızca uygulama pod'larının 8443 portuna gider |

KVKK kapsamındaki siteler için çerez ve aydınlatma metinleri web ekibinin sorumluluğundadır. Londra'daki İngiliz
müşteri verisi UK GDPR kapsamındadır: Türkiye'ye giden tünel DLP'den geçer ve ham loglar Londra'da kalır.

## Bant Genişliği

Formül: **kişi × eşzamanlılık × kişi başı Mbps**, toplamın üstüne servis / VPN trafiği ve **%30 büyüme**.

| Profil | Kişi başı | Eşzamanlılık |
|---|---:|---:|
| Ofis personeli | 4 Mbps | %70 |
| Yazılım / teknik | 10 Mbps | %80 |
| Ar-Ge | 15 Mbps | %80 |
| Akademisyen | 4 Mbps | %70 |
| Öğrenci | 2 Mbps | %35 |

| Site | İhtiyaç | Hatlar | En büyük hat koparsa |
|---|---:|---|---:|
| Ankara | 1,81 Gbps | 2 Gbps + 1 Gbps (farklı güzergah) | 1 Gbps |
| İstanbul | 972 Mbps | 1 Gbps + 500 Mbps | 500 Mbps |
| Londra | 387 Mbps | 500 Mbps + 200 Mbps + 5G | 300 Mbps |
| Kampüs | 12,25 Gbps | 2 × 10 Gbps **aktif-aktif** | 10 Gbps |
| Yazılım | 771 Mbps (+514 Mbps AWS'ye) | 1 Gbps + 500 Mbps + 1 Gbps Direct Connect | 500 Mbps |
| Ar-Ge | 824 Mbps | 1 Gbps + 500 Mbps (ayrı devre) | 500 Mbps |

Her sitede ikinci bir ISP ya da 5G yedek vardır; SD-WAN hat kalitesine göre otomatik geçer. Kampüsün 12,25 Gbps
ihtiyacı tek 10G hatla karşılanamadığı için iki hat birlikte çalışır. Biri koparsa kalan 10 Gbps ihtiyacın ~%80'ini
taşır; QoS önce online dersi korur. Öğrenci başına 20/5 Mbps sınırı, trafik ağa girmeden Wi-Fi denetleyicisinde
uygulanır.

## Ürün Seçimi

Boyutlandırmada datasheet'in ham "firewall throughput" değerine değil, **UTM / IPS açıkken ölçülen Threat
Protection** değerine bakıldı. Gereken değer, ihtiyacın 1,25 katı (SSL inceleme ve zirve tamponu). Fiyatlar tek cihaz
için yaklaşık donanım liste fiyatıdır; HA çifti iki cihazdır ve abonelikler hariçtir.

- **Ofisler: FortiGate** (600F / 200F / 100F)
  - Altı noktanın beşi tek FortiManager'dan yönetilir.
  - SD-WAN cihazın içindedir.
  - Gbps başına maliyeti en düşük seçenektir.
  - Palo Alto ofislerde güvenlik açısından en az onun kadar iyi, ancak aynı performans için belirgin pahalı.
  - Cisco Secure Firewall SD-WAN için ikinci bir ürün ister.
  - Sophos çok şubeli bir hub tasarımında sınırlı kalıyor.
- **Kampüs: Palo Alto PA-5420** (~25 Gbps TP)
  - Burada FortiGate seçilmedi: FortiGate 1800F (~9,1 Gbps TP) ve Check Point 16200 (~11 Gbps), 15,3 Gbps
    gereksinimini tek cihazla karşılayamıyor.
  - PA-5420'yi seçtiren başka nedenler de var: 10.000 kimliği User-ID ile kurallara bağlaması, Tor / Psiphon /
    torrent gibi kaçış araçlarını port bağımsız tanıyan App-ID ve öğrenci ağını ayrı sanal firewall yapan VSYS.
  - Bedeli ikinci bir yönetim konsolu (Panorama). Faydası ise tek bir üreticinin zafiyetinin tüm şirketi
    etkilememesi.
- **AWS: FortiGate-VM**
  - AWS Network Firewall daha ucuz ve kendiliğinden ölçekleniyor, ancak ofis kurallarıyla ortak bir politika dili ve
    panel yok.
- **İzole lab: OPNsense**
  - İnternete hiç çıkmayan bir labda tehdit istihbaratı aboneliği işe yaramaz. Burada şeffaf ve denetlenebilir bir
    açık kaynak firewall yeterli.
  - FortiGate 40F'nin değeri aboneliğindedir; burada boşa gider.

Her segmentin beş adayı, fiyatı, throughput'u ve "neden seçmedik" notu `company.json`'da.

## Kural Setini Okumak

- **İlk eşleşen kural kazanır.** Her firewall cihaza yönelik kurallarla (DHCP, VPN girişi, yönetim kapatma) başlar
  ve **portsuz, kaynaksız bir varsayılan red** ile biter.
- **DHCP, DNS ve NTP her sitede açıkça izinlidir.** İstemciler IP'yi FortiGate DHCP'sinden alır; kampüste PAN-OS bu
  istekleri Kea DHCP kümesine aktarır (relay). DNS ve NTP yalnızca Ankara'daki AD sunucularından dışarı çıkar.
- **Kaynak kodda bir kural, burada birden fazla satır olabilir.** Örneğin `DNS` servisi tcp/53 ve udp/53 olarak iki
  satıra açılır.
- **Not alanı her zaman kaynak kuralın adıyla başlar** (`PERSONEL-INTERNET: ...`). Kampüs kurallarında porta
  indirgenemeyen uygulamalar notta `[App-ID: zoom, ms-teams]` şeklinde yazılıdır.
- **Kullanıcı tabanlı kurallarda grup `from` alanındadır**, ör. `net-ogrenci (grp-ogrenci)`.
- **Hız limitli yayınlar `limit` aksiyonuyla görünür.** Cihazda bunlar FortiOS'ta DoS politikasına, PAN-OS'ta Zone
  Protection profiline dönüşür.
- **Hiçbir yerde public SSH, RDP, SMB ya da veritabanı portu yoktur.** Kenarda `reject` değil, sessiz `deny`
  kullanılır.

## Uzaktan Erişim ve İzleme

**Uzaktan erişim:** Public SSH yerine **rol bazlı ZTNA** kullanılır. Erişim AD grubu, MFA ve cihaz uyumluluğuyla
verilir:

| Grup | Erişebildiği yer |
|---|---|
| `grp-uzaktan-calisan` | ERP ve dosya sunucusu |
| `grp-yazilim` | GitLab / DEV / TEST |
| `grp-bt-admin` | Yönetim VLAN'ındaki bastion |

Tünel ve ZTNA girişleri yalnızca TR / GB IP'lerinden kabul edilir.

**Sorumluluk:**
- **Güvenlik alarmları:** SOC Yöneticisi. L1 analistler 7/24 dış kaynaktan (MSSP), L2 / L3 kurum içinden.
- **Ağ erişilebilirliği:** NOC Yöneticisi.
- **P1 olayda karar:** CISO.

**Uygulama ve güvenlik izleme ayrıdır:**
- Uygulama sağlığı (ERP / LMS / web up-down, hat doluluğu): Zabbix → NOC kanalı.
- Güvenlik olayları (IPS, DLP, kimlik hataları, kritik red kurallarına isabet): Wazuh → SOC.

Bazı red kuralları normal işleyişte **hiç** tetiklenmemelidir. Tetiklenirlerse ya yanlış yapılandırma ya da saldırgan
vardır; bu yüzden doğrudan SOC alarmına bağlıdırlar:
- geliştiricinin PROD'a erişimi
- kurumsalın Ar-Ge'ye erişimi
- izole labdan dışarı paket

P1 / P2 alarmlar nöbetçi çağrı sistemine ve SOC Telegram kanalına düşer.

**Log saklama:** 90 gün sıcak, **2 yıl** değiştirilemez arşiv (5651, KVKK). Londra'nın ham logları UK'de kalır.

**Yedek ve yama:** Config'ler hem Git'te hem FortiManager / Panorama revizyonlarında tutulur. Firmware her ay
güncellenir; CISA KEV listesine giren bir firewall zafiyetinin yaması 72 saat içinde uygulanır.

## CVE Takibi

| CVE | Durum | Geçici önlem → Kalıcı çözüm |
|---|---|---|
| CVE-2024-21762 (FortiOS SSL-VPN) | Önlem alındı | SSL-VPN kapalı, uzaktan erişim ZTNA → firmware 7.4.3+ |
| CVE-2024-3400 (PAN-OS GlobalProtect) | Etkilenmiyor | GlobalProtect kullanılmıyor; tehdit imzası açık |
| CVE-2024-55591 (FortiOS yönetim arayüzü) | Etkilenmiyor | 7.4 kolu; yönetim arayüzü internete kapalı |

Yönetim ve VPN arayüzü saldırılarında firewall doğru katmandır: arayüzü kapatmak saldırıyı keser. Bir uygulama
zafiyetinde ise çözüm WAF kuralı ve yamadır; normal bir firewall kuralı bunu durduramaz.

## Bilinen Sınırlar

- Throughput ve fiyatlar datasheet'lere dayanan **yaklaşık** değerlerdir; satın alma öncesi teklif ve POC gerekir.
- Üretilen FortiOS / PAN-OS config'leri sözdizimine göre hazırlandı, gerçek cihazda lab testi yapılmadı.
- Sonraki adımlar:
  - tüm ofislerde 802.1X / NAC
  - veri merkezinde iş yükü bazlı mikro segmentasyon
