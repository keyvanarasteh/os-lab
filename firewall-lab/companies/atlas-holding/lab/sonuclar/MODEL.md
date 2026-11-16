# Model sonuçları

Bu dosyayı `lab/politika.py hepsi` üretir, elle düzenlenmez.

Model, `company.json` kurallarını ilk eşleşme mantığıyla **hesaplar, paket göndermez**. Kuralların tutarlılığını gösterir. IPS, uygulama tanıma, WAF, HA, hız sınırı veya FortiGate davranışı hakkında bir şey kanıtlamaz. Gerçek paket testleri ayrı rapordadır: [PAKET.md](PAKET.md).

## Özet

| Denetim | Sonuç |
|---|---:|
| Yapısal ve tutarlılık hatası | 0 |
| Gereksinim testleri | 254 / 254 |
| Bozma deneyleri: test kaldı | 5 / 5 |
| Öğrenci DHCP havuzu (8 VLAN) | 32512 adres |
| Bugünkü hedef 25.000 cihaz | %76.9 |
| Büyüme hedefi 32.500 cihaz | %99.96, kalan 12 adres |
| Şubeler arası izin satırı, iki uçta doğrulandı | 76 |
| README tablolarından açılan kural satırı, company.json ile aynı | 367 |
| HA çifti toplamı: yalnızca donanım / donanım + 3 yıl paket | 93460 / 295880 USD |

## Yapısal hatalar

Yok.

## Kalan testler

Yok.

## Kural kapsamı

Numaralı her kuralın en az bir testte karar verip vermediğini gösterir. Bir kuralın sınanması, o kuralın doğru olduğunu tek başına kanıtlamaz.

| Güvenlik duvarı | Numaralı kural | Karar veren | Hiç karar vermeyen |
|---|---:|---:|---|
| istanbul | 39 | 39 | yok |
| izmir | 22 | 22 | yok |
| amsterdam | 20 | 20 | yok |
| ankara-akademik | 34 | 34 | yok |

## Bozma deneyleri

Kurallar bellekte bozulur, testlerin bunu yakalayıp yakalamadığı ölçülür. Yakalamayan test işe yaramaz.

| Yapılan bozma | Beklenen etki | Kalan test sayısı | Beklenen testler kaldı mı? |
|---|---|---:|---|
| Eski kural 5 geri kondu: öğrenci → internet, portsuz ret | Web erişimi kesilir | 4 | Evet |
| Ankara kural 4, kural 3'ün üstüne alındı | Öğrenciler LMS'e ulaşamaz | 8 | Evet |
| Ankara'da O4 silindi | İstemciler IP ve DNS alamaz | 5 | Evet |
| İstanbul'da O3, O2'nin üstüne alındı | Zabbix cihazları okuyamaz | 4 | Evet |
| İstanbul kural 4 silindi: şube personeli için merkez izni yok | Şube izni tek başına yetmez | 3 | Evet |

## Tüm testler

| No | Akış | Kaynak → hedef | Servis | Beklenen | Model | Karar veren kural | Sonuç |
|---|---|---|---|---|---|---|---|
| G1-01 | Öğrenci (Yurt 1) LMS'e ulaşır | `10.4.128.100` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G1-02 | Öğrenci (Yurt 2) LMS'e ulaşır | `10.4.144.100` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G1-03 | Öğrenci (Kütüphane) LMS'e ulaşır | `10.4.160.100` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G1-04 | Öğrenci (Mühendislik) LMS'e ulaşır | `10.4.176.100` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G1-05 | Öğrenci (Fen-Edebiyat) LMS'e ulaşır | `10.4.192.100` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G1-06 | Öğrenci (İİBF) LMS'e ulaşır | `10.4.208.100` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G1-07 | Öğrenci (Yemekhane) LMS'e ulaşır | `10.4.224.100` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G1-08 | Öğrenci (Açık alan) LMS'e ulaşır | `10.4.240.100` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G1-09 | Öğrenci (Yurt 1) HTTPS ile internete çıkar | `10.4.128.100` → `198.51.100.10` | tcp/443 | izin | izin | ank:5 | Geçti |
| G1-10 | Öğrenci (Yurt 1) HTTP ile internete çıkar | `10.4.128.100` → `198.51.100.10` | tcp/80 | izin | izin | ank:5 | Geçti |
| G1-11 | Öğrenci (Mühendislik) HTTPS ile internete çıkar | `10.4.176.100` → `198.51.100.10` | tcp/443 | izin | izin | ank:5 | Geçti |
| G1-12 | Öğrenci (Açık alan) HTTP ile internete çıkar | `10.4.240.100` → `198.51.100.10` | tcp/80 | izin | izin | ank:5 | Geçti |
| G1-13 | Öğrenci ERP'ye ulaşamaz | `10.4.128.100` → `10.1.60.31` | tcp/443 | red | red | ank:4 | Geçti |
| G1-14 | Öğrenci kampüs ağ cihazı yönetimine ulaşamaz | `10.4.128.100` → `10.4.10.1` | tcp/443 | red | red | ank:O3 | Geçti |
| G1-15 | Öğrenci merkez ağ cihazı yönetimine ulaşamaz | `10.4.128.100` → `10.1.10.1` | tcp/22 | red | red | ank:O3 | Geçti |
| G1-16 | Öğrenci İzmir'in özel ağına ulaşamaz | `10.4.128.100` → `10.2.60.20` | tcp/443 | red | red | ank:4 | Geçti |
| G1-17 | Öğrenci Amsterdam'ın özel ağına ulaşamaz | `10.4.128.100` → `10.3.60.20` | tcp/443 | red | red | ank:4 | Geçti |
| G1-18 | Öğrenci öğrenci bilgi sistemine ulaşamaz | `10.4.128.100` → `10.4.60.31` | tcp/443 | red | red | ank:4 | Geçti |
| G1-19 | Öğrenci LMS veritabanına ulaşamaz | `10.4.128.100` → `10.4.63.30` | tcp/5432 | red | red | ank:4 | Geçti |
| G1-20 | Öğrenci WAF'ı atlayıp LMS uygulamasına ulaşamaz | `10.4.128.100` → `10.4.70.11` | tcp/8080 | red | red | ank:4 | Geçti |
| G1-21 | Öğrenci yazıcıya ulaşamaz | `10.4.128.100` → `10.4.80.20` | tcp/631 | red | red | ank:4 | Geçti |
| G1-22 | Öğrenci başka binadaki öğrenciye ulaşamaz | `10.4.128.100` → `10.4.192.100` | tcp/445 | red | red | ank:4 | Geçti |
| G1-23 | Öğrenci internete yalnızca web portlarıyla çıkar (TCP 6881) | `10.4.128.100` → `198.51.100.10` | tcp/6881 | red | red | ank:O7 | Geçti |
| G1-24 | Öğrenci internete yalnızca web portlarıyla çıkar (UDP 6881) | `10.4.128.100` → `198.51.100.10` | udp/6881 | red | red | ank:O7 | Geçti |
| G1-25 | Öğrenci QUIC kullanamaz, tarayıcı TCP 443'e döner | `10.4.128.100` → `198.51.100.10` | udp/443 | red | red | ank:O7 | Geçti |
| G1-26 | Öğrenci internete SSH yapamaz | `10.4.128.100` → `198.51.100.10` | tcp/22 | red | red | ank:O7 | Geçti |
| G1-27 | Öğrenci dış DNS kullanamaz, şube DNS'ini kullanır | `10.4.128.100` → `198.51.100.10` | udp/53 | red | red | ank:O7 | Geçti |
| G2-01 | İstanbul misafiri internete çıkar | `10.1.85.10` → `198.51.100.10` | tcp/443 | izin | izin | ist:14 | Geçti |
| G2-02 | İzmir misafiri internete çıkar | `10.2.85.10` → `198.51.100.10` | tcp/443 | izin | izin | izm:11 | Geçti |
| G2-03 | Amsterdam misafiri internete çıkar | `10.3.85.10` → `198.51.100.10` | tcp/80 | izin | izin | ams:10 | Geçti |
| G2-04 | Ankara misafiri internete çıkar | `10.4.85.10` → `198.51.100.10` | tcp/443 | izin | izin | ank:18 | Geçti |
| G2-05 | Misafir dış DNS kullanır | `10.4.85.10` → `198.51.100.10` | udp/53 | izin | izin | ank:18 | Geçti |
| G2-06 | İstanbul misafiri ERP'ye ulaşamaz | `10.1.85.10` → `10.1.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G2-07 | İstanbul misafiri personel ağına ulaşamaz | `10.1.85.10` → `10.1.20.10` | tcp/445 | red | red | ist:O7 | Geçti |
| G2-08 | İzmir misafiri Ar-Ge verisine ulaşamaz | `10.2.85.10` → `10.2.60.20` | tcp/443 | red | red | izm:O7 | Geçti |
| G2-09 | Amsterdam misafiri personel ağına ulaşamaz | `10.3.85.10` → `10.3.20.1` | tcp/443 | red | red | ams:O7 | Geçti |
| G2-10 | Amsterdam misafiri müşteri verisine ulaşamaz | `10.3.85.10` → `10.3.60.20` | tcp/443 | red | red | ams:O7 | Geçti |
| G2-11 | Ankara misafiri öğrenci bilgi sistemine ulaşamaz | `10.4.85.10` → `10.4.60.31` | tcp/443 | red | red | ank:4 | Geçti |
| G2-12 | Ankara misafiri tünelden ERP'ye ulaşamaz | `10.4.85.10` → `10.1.60.31` | tcp/443 | red | red | ank:4 | Geçti |
| G2-13 | Misafir LMS'i iç adresten kullanamaz | `10.4.85.10` → `10.4.70.10` | tcp/443 | red | red | ank:4 | Geçti |
| G2-14 | Misafir ağ cihazı yönetimine ulaşamaz | `10.1.85.10` → `10.1.10.1` | tcp/443 | red | red | ist:O3 | Geçti |
| G3-01 | İstanbul Ar-Ge proxy'ye ulaşır | `10.1.40.10` → `10.1.64.40` | tcp/3128 | izin | izin | ist:8 | Geçti |
| G3-02 | İzmir Ar-Ge proxy'ye ulaşır | `10.2.40.10` → `10.2.64.10` | tcp/3128 | izin | izin | izm:2 | Geçti |
| G3-03 | Ankara Ar-Ge proxy'ye ulaşır | `10.4.40.10` → `10.4.64.10` | tcp/3128 | izin | izin | ank:11 | Geçti |
| G3-04 | İstanbul Ar-Ge doğrudan internete çıkamaz, hemen hata alır | `10.1.40.10` → `198.51.100.10` | tcp/443 | reject | reject | ist:10 | Geçti |
| G3-05 | İzmir Ar-Ge doğrudan internete çıkamaz, hemen hata alır | `10.2.40.10` → `198.51.100.10` | tcp/443 | reject | reject | izm:4 | Geçti |
| G3-06 | Ankara Ar-Ge doğrudan internete çıkamaz, hemen hata alır | `10.4.40.10` → `198.51.100.10` | tcp/443 | reject | reject | ank:13 | Geçti |
| G3-07 | Ar-Ge başka portla da doğrudan çıkamaz | `10.2.40.10` → `198.51.100.10` | tcp/22 | reject | reject | izm:4 | Geçti |
| G3-08 | İstanbul proxy'si internete çıkar | `10.1.64.40` → `198.51.100.10` | tcp/443 | izin | izin | ist:9 | Geçti |
| G3-09 | İzmir proxy'si internete çıkar | `10.2.64.10` → `198.51.100.10` | tcp/80 | izin | izin | izm:3 | Geçti |
| G3-10 | Ankara proxy'si internete çıkar | `10.4.64.10` → `198.51.100.10` | tcp/443 | izin | izin | ank:12 | Geçti |
| G3-11 | Ar-Ge kendi verisine ulaşır | `10.2.40.10` → `10.2.60.20` | tcp/443 | izin | izin | izm:1 | Geçti |
| G3-12 | Personel Ar-Ge verisine ulaşamaz | `10.2.20.10` → `10.2.60.20` | tcp/443 | red | red | izm:O7 | Geçti |
| G4-01 | Personel VPN'i ERP'ye ulaşır | `10.1.200.10` → `10.1.60.31` | tcp/443 | izin | izin | ist:20 | Geçti |
| G4-02 | Personel VPN'i Git'e ulaşamaz | `10.1.200.10` → `10.1.60.32` | tcp/443 | red | red | ist:O7 | Geçti |
| G4-03 | Personel VPN'i bastion'a ulaşamaz | `10.1.200.10` → `10.1.61.5` | tcp/22 | red | red | ist:O7 | Geçti |
| G4-04 | Personel VPN'i öğrenci bilgi sistemine ulaşamaz | `10.1.200.10` → `10.4.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G4-05 | Geliştirici VPN'i Git'e SSH ile ulaşır | `10.1.204.10` → `10.1.60.32` | tcp/22 | izin | izin | ist:21 | Geçti |
| G4-06 | Geliştirici VPN'i Git'e HTTPS ile ulaşır | `10.1.204.10` → `10.1.60.32` | tcp/443 | izin | izin | ist:21 | Geçti |
| G4-07 | Geliştirici VPN'i ERP'ye ulaşamaz | `10.1.204.10` → `10.1.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G4-08 | Geliştirici VPN'i veritabanına ulaşamaz | `10.1.204.10` → `10.1.63.31` | tcp/5432 | red | red | ist:O7 | Geçti |
| G4-09 | Hoca VPN'i öğrenci bilgi sistemine iki güvenlik duvarından geçerek ulaşır | `10.1.208.10` → `10.4.60.31` | tcp/443 | izin | izin | ist:22 ank:23 | Geçti |
| G4-10 | Hoca VPN'i ERP'ye ulaşamaz | `10.1.208.10` → `10.1.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G4-11 | Hoca VPN'i LMS veritabanına ulaşamaz | `10.1.208.10` → `10.4.63.30` | tcp/5432 | red | red | ist:O7 | Geçti |
| G4-12 | Yönetici VPN'i bastion'a ulaşır | `10.1.205.10` → `10.1.61.5` | tcp/22 | izin | izin | ist:23 | Geçti |
| G4-13 | Yönetici VPN'i ERP'ye doğrudan ulaşamaz | `10.1.205.10` → `10.1.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G4-14 | Çalışan internetten VPN'e bağlanır | `198.51.100.10` → `wan-istanbul` | udp/4500 | izin | izin | ist:19 | Geçti |
| G5-01 | Yönetici VPN'i cihaza doğrudan bağlanamaz | `10.1.205.10` → `10.1.10.1` | tcp/443 | red | red | ist:O3 | Geçti |
| G5-02 | Bastion İstanbul cihazına ulaşır | `10.1.61.5` → `10.1.10.1` | tcp/443 | izin | izin | ist:O1 | Geçti |
| G5-03 | Bastion İzmir cihazına tünelden ulaşır | `10.1.61.5` → `10.2.10.1` | tcp/22 | izin | izin | ist:O1 izm:O1 | Geçti |
| G5-04 | Bastion Amsterdam cihazına tünelden ulaşır | `10.1.61.5` → `10.3.10.1` | tcp/443 | izin | izin | ist:O1 ams:O1 | Geçti |
| G5-05 | Bastion Ankara cihazına tünelden ulaşır | `10.1.61.5` → `10.4.10.1` | tcp/22 | izin | izin | ist:O1 ank:O1 | Geçti |
| G5-06 | Zabbix İstanbul cihazını okur | `10.1.61.20` → `10.1.10.1` | udp/161 | izin | izin | ist:O2 | Geçti |
| G5-07 | Zabbix İzmir cihazını okur | `10.1.61.20` → `10.2.10.1` | udp/161 | izin | izin | ist:O2 izm:O2 | Geçti |
| G5-08 | Zabbix Amsterdam cihazını okur | `10.1.61.20` → `10.3.10.1` | udp/161 | izin | izin | ist:O2 ams:O2 | Geçti |
| G5-09 | Zabbix Ankara cihazını okur | `10.1.61.20` → `10.4.10.1` | udp/161 | izin | izin | ist:O2 ank:O2 | Geçti |
| G5-10 | Personel cihaz yönetimine ulaşamaz | `10.1.20.10` → `10.1.10.1` | tcp/443 | red | red | ist:O3 | Geçti |
| G5-11 | Teknik ekip cihaza da doğrudan bağlanamaz, bastion kullanır | `10.1.50.10` → `10.1.10.1` | tcp/22 | red | red | ist:O3 | Geçti |
| G5-12 | Teknik ekip bastion'a ulaşır | `10.1.50.10` → `10.1.61.5` | tcp/22 | izin | izin | ist:28 | Geçti |
| G5-13 | Personel başka şubenin cihazına ulaşamaz | `10.1.20.10` → `10.4.10.1` | tcp/443 | red | red | ist:O3 | Geçti |
| G5-14 | İzmir personeli cihaz yönetimine ulaşamaz | `10.2.20.10` → `10.2.10.1` | tcp/443 | red | red | izm:O3 | Geçti |
| G5-15 | Amsterdam misafiri cihaz yönetimine ulaşamaz | `10.3.85.10` → `10.3.10.1` | tcp/443 | red | red | ams:O3 | Geçti |
| G5-16 | İnternetten WAN adresine SSH kapalı | `198.51.100.10` → `wan-istanbul` | tcp/22 | red | red | ist:eslesme-yok | Geçti |
| G5-17 | İnternetten WAN adresine RDP kapalı | `198.51.100.10` → `wan-ankara` | tcp/3389 | red | red | ank:eslesme-yok | Geçti |
| G5-18 | Yönetim ağındaki sıradan cihaz FortiManager'a bağlanamaz, yalnızca güvenlik duvarı bağlanır | `10.2.10.1` → `10.1.61.6` | tcp/541 | red | red | izm:O7 | Geçti |
| G5-19 | İzmir güvenlik duvarı FortiManager'a tünelden bağlanır | `172.31.2.2` → `10.1.61.6` | tcp/541 | izin | izin | ist:30 | Geçti |
| G5-20 | Amsterdam güvenlik duvarı FortiManager'a tünelden bağlanır | `172.31.3.2` → `10.1.61.6` | tcp/541 | izin | izin | ist:30 | Geçti |
| G5-21 | Ankara güvenlik duvarı FortiManager'a tünelden bağlanır | `172.31.4.2` → `10.1.61.6` | tcp/541 | izin | izin | ist:30 | Geçti |
| G5-22 | Personel FortiManager panelini göremez | `10.1.20.10` → `10.1.61.6` | tcp/443 | red | red | ist:O7 | Geçti |
| G5-23 | Teknik ekip ve SOC Wazuh paneline ulaşır | `10.1.50.10` → `10.1.61.10` | tcp/443 | izin | izin | ist:29 | Geçti |
| G5-24 | Teknik ekip ve SOC GLPI'a ulaşır | `10.1.50.10` → `10.1.61.21` | tcp/443 | izin | izin | ist:29 | Geçti |
| G5-25 | Teknik ekip Wazuh'a doğrudan SSH yapamaz, bastion kullanır | `10.1.50.10` → `10.1.61.10` | tcp/22 | red | red | ist:O7 | Geçti |
| G5-26 | Personel Wazuh paneline ulaşamaz | `10.1.20.10` → `10.1.61.10` | tcp/443 | red | red | ist:O7 | Geçti |
| G6-01 | İnternet kurumsal siteye WAF üzerinden ulaşır | `198.51.100.10` → `wan-istanbul` | tcp/443 | izin | izin | ist:1 | Geçti |
| G6-02 | İnternet LMS'e WAF üzerinden ulaşır | `198.51.100.10` → `wan-ankara` | tcp/443 | izin | izin | ank:1 | Geçti |
| G6-03 | İnternet web uygulamasına doğrudan ulaşamaz | `198.51.100.10` → `10.1.70.11` | tcp/8080 | red | red | ist:O7 | Geçti |
| G6-04 | İnternet LMS uygulamasına doğrudan ulaşamaz | `198.51.100.10` → `10.4.70.11` | tcp/8080 | red | red | ank:O7 | Geçti |
| G6-05 | İnternet web veritabanına ulaşamaz | `198.51.100.10` → `10.1.63.30` | tcp/5432 | red | red | ist:O7 | Geçti |
| G6-06 | İnternet LMS veritabanına ulaşamaz | `198.51.100.10` → `10.4.63.30` | tcp/5432 | red | red | ank:O7 | Geçti |
| G6-07 | İnternet ERP'ye ulaşamaz | `198.51.100.10` → `10.1.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G6-08 | İnternet Ar-Ge verisine ulaşamaz | `198.51.100.10` → `10.2.60.20` | tcp/443 | red | red | izm:O7 | Geçti |
| G6-09 | İzmir'in internete açık servisi yoktur | `198.51.100.10` → `wan-izmir` | tcp/443 | red | red | izm:eslesme-yok | Geçti |
| G6-10 | Amsterdam'ın internete açık servisi yoktur | `198.51.100.10` → `wan-amsterdam` | tcp/443 | red | red | ams:eslesme-yok | Geçti |
| G6-11 | Web uygulaması kendi veritabanına ulaşır | `10.1.70.11` → `10.1.63.30` | tcp/5432 | izin | izin | ist:2 | Geçti |
| G6-12 | LMS kendi veritabanına ulaşır | `10.4.70.11` → `10.4.63.30` | tcp/5432 | izin | izin | ank:2 | Geçti |
| G6-13 | Web uygulaması ERP veritabanına ulaşamaz | `10.1.70.11` → `10.1.63.31` | tcp/5432 | red | red | ist:O7 | Geçti |
| G6-14 | DMZ ERP'ye ulaşamaz | `10.1.70.11` → `10.1.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G6-15 | DMZ öğrenci bilgi sistemine ulaşamaz | `10.4.70.11` → `10.4.60.31` | tcp/443 | red | red | ank:O7 | Geçti |
| G6-16 | WAF internete doğrudan çıkamaz | `10.1.70.12` → `198.51.100.10` | tcp/443 | red | red | ist:O7 | Geçti |
| G6-17 | DMZ güncellemeyi proxy'den alır | `10.1.70.11` → `10.1.64.40` | tcp/3128 | izin | izin | ist:16 | Geçti |
| G6-18 | Ankara DMZ güncellemeyi proxy'den alır | `10.4.70.12` → `10.4.64.10` | tcp/3128 | izin | izin | ank:20 | Geçti |
| G7-01 | İzmir personeli ERP'ye ulaşır | `10.2.20.10` → `10.1.60.31` | tcp/443 | izin | izin | izm:5 ist:4 | Geçti |
| G7-02 | Amsterdam personeli ERP'ye ulaşır | `10.3.20.10` → `10.1.60.31` | tcp/443 | izin | izin | ams:5 ist:4 | Geçti |
| G7-03 | Ankara personeli ERP'ye ulaşır | `10.4.20.10` → `10.1.60.31` | tcp/443 | izin | izin | ank:8 ist:4 | Geçti |
| G7-04 | İzmir yazılımcısı Git'e ulaşır | `10.2.30.10` → `10.1.60.32` | tcp/443 | izin | izin | izm:6 ist:6 | Geçti |
| G7-05 | Amsterdam yazılımcısı Git'e ulaşır | `10.3.30.10` → `10.1.60.32` | tcp/22 | izin | izin | ams:6 ist:6 | Geçti |
| G7-06 | Ankara yazılımcısı Git'e ulaşır | `10.4.30.10` → `10.1.60.32` | tcp/443 | izin | izin | ank:14 ist:6 | Geçti |
| G7-07 | Şube personeli Git'e ulaşamaz | `10.2.20.10` → `10.1.60.32` | tcp/443 | red | red | izm:O7 | Geçti |
| G7-08 | Şube yazılımcısı ERP'ye ulaşamaz | `10.2.30.10` → `10.1.60.31` | tcp/443 | red | red | izm:O7 | Geçti |
| G7-09 | Şubeden şubeye doğrudan geçilemez | `10.4.20.10` → `10.2.20.10` | tcp/443 | red | red | ank:O7 | Geçti |
| G7-10 | Şubeden şubeye doğrudan geçilemez | `10.2.30.10` → `10.3.30.10` | tcp/22 | red | red | izm:O7 | Geçti |
| G7-11 | ERP şubedeki personele bağlantı başlatamaz, yalnızca yanıt verir | `10.1.60.31` → `10.4.20.10` | tcp/443 | red | red | ist:O7 | Geçti |
| G7-12 | İzmir sunucusu izleme verisini gönderir | `10.2.60.20` → `10.1.61.20` | tcp/10051 | izin | izin | izm:13 ist:17 | Geçti |
| G7-13 | İzmir proxy'si izleme verisini gönderir | `10.2.64.10` → `10.1.61.20` | tcp/10051 | izin | izin | izm:13 ist:17 | Geçti |
| G7-14 | Ankara sunucusu izleme verisini gönderir | `10.4.60.2` → `10.1.61.20` | tcp/10051 | izin | izin | ank:21 ist:17 | Geçti |
| G7-15 | LMS izleme verisini gönderir | `10.4.70.11` → `10.1.61.20` | tcp/10051 | izin | izin | ank:21 ist:17 | Geçti |
| G7-16 | LMS veritabanı izleme verisini gönderir | `10.4.63.30` → `10.1.61.20` | tcp/10051 | izin | izin | ank:21 ist:17 | Geçti |
| G7-17 | Şube kullanıcısı izleme portuna ulaşamaz | `10.2.20.10` → `10.1.61.20` | tcp/10051 | red | red | izm:O7 | Geçti |
| G7-18 | İzmir merkeze tünel kurar | `wan-izmir` → `wan-istanbul` | udp/500 | izin | izin | ist:18 | Geçti |
| G7-19 | Amsterdam merkeze tünel kurar | `wan-amsterdam` → `wan-istanbul` | udp/4500 | izin | izin | ist:18 | Geçti |
| G7-20 | Ankara merkeze tünel kurar | `wan-ankara` → `wan-istanbul` | udp/500 | izin | izin | ist:18 | Geçti |
| G7-21 | Merkez İzmir'e tünel kurar | `wan-istanbul` → `wan-izmir` | udp/500 | izin | izin | izm:14 | Geçti |
| G7-22 | Merkez Amsterdam'a tünel kurar | `wan-istanbul` → `wan-amsterdam` | udp/4500 | izin | izin | ams:13 | Geçti |
| G7-23 | Merkez Ankara'ya tünel kurar | `wan-istanbul` → `wan-ankara` | udp/500 | izin | izin | ank:22 | Geçti |
| G7-24 | Yabancı adres İzmir'e tünel kuramaz | `198.51.100.10` → `wan-izmir` | udp/500 | red | red | izm:eslesme-yok | Geçti |
| G7-25 | Yabancı adres Ankara'ya tünel kuramaz | `198.51.100.10` → `wan-ankara` | udp/4500 | red | red | ank:eslesme-yok | Geçti |
| G7-26 | Kampüs erişim noktası 802.1X için RADIUS'a ulaşır | `10.4.10.1` → `10.4.60.3` | udp/1812 | izin | izin | ank:25 | Geçti |
| G7-27 | Kampüs RADIUS'u merkez dizine ulaşır | `10.4.60.3` → `10.1.60.3` | tcp/636 | izin | izin | ank:26 ist:32 | Geçti |
| G7-28 | Öğrenci RADIUS sunucusuna ulaşamaz | `10.4.128.100` → `10.4.60.3` | udp/1812 | red | red | ank:4 | Geçti |
| G8-01 | İstanbul personeli DHCP alır | `10.1.20.10` → `10.1.60.2` | udp/67 | izin | izin | ist:O4 | Geçti |
| G8-02 | İstanbul personeli DNS kullanır | `10.1.20.10` → `10.1.60.2` | udp/53 | izin | izin | ist:O4 | Geçti |
| G8-03 | İstanbul personeli büyük DNS yanıtlarını alır | `10.1.20.10` → `10.1.60.2` | tcp/53 | izin | izin | ist:O4 | Geçti |
| G8-04 | İstanbul personeli NTP kullanır | `10.1.20.10` → `10.1.60.2` | udp/123 | izin | izin | ist:O4 | Geçti |
| G8-05 | Ar-Ge DHCP alır | `10.2.40.10` → `10.2.60.2` | udp/67 | izin | izin | izm:O4 | Geçti |
| G8-06 | Ar-Ge şube DNS'ini kullanır | `10.2.40.10` → `10.2.60.2` | udp/53 | izin | izin | izm:O4 | Geçti |
| G8-07 | Kamera DHCP alır | `10.3.80.10` → `10.3.60.2` | udp/67 | izin | izin | ams:O4 | Geçti |
| G8-08 | Amsterdam personeli NTP kullanır | `10.3.20.10` → `10.3.60.2` | udp/123 | izin | izin | ams:O4 | Geçti |
| G8-09 | Öğrenci (Yurt 1) DHCP alır, öğrenci reddine takılmaz | `10.4.128.100` → `10.4.60.2` | udp/67 | izin | izin | ank:O4 | Geçti |
| G8-10 | Öğrenci (Açık alan) DHCP alır, öğrenci reddine takılmaz | `10.4.240.100` → `10.4.60.2` | udp/67 | izin | izin | ank:O4 | Geçti |
| G8-11 | Öğrenci şube DNS'ini kullanır | `10.4.128.100` → `10.4.60.2` | udp/53 | izin | izin | ank:O4 | Geçti |
| G8-12 | Öğrenci NTP kullanır | `10.4.128.100` → `10.4.60.2` | udp/123 | izin | izin | ank:O4 | Geçti |
| G8-13 | İstanbul misafiri DHCP alır | `10.1.85.10` → `10.1.60.2` | udp/67 | izin | izin | ist:O4 | Geçti |
| G8-14 | İzmir misafiri DHCP alır | `10.2.85.10` → `10.2.60.2` | udp/67 | izin | izin | izm:O4 | Geçti |
| G8-15 | Ankara misafiri DHCP alır | `10.4.85.10` → `10.4.60.2` | udp/67 | izin | izin | ank:O4 | Geçti |
| G8-16 | İstanbul misafiri iç DNS'i kullanamaz | `10.1.85.10` → `10.1.60.2` | udp/53 | red | red | ist:O4 | Geçti |
| G8-17 | Ankara misafiri iç DNS'i kullanamaz | `10.4.85.10` → `10.4.60.2` | udp/53 | red | red | ank:O4 | Geçti |
| G8-18 | VPN kullanıcısı iç adları çözer | `10.1.200.10` → `10.1.60.2` | udp/53 | izin | izin | ist:O4 | Geçti |
| G8-19 | Şube DNS sunucusu dış adres çözer | `10.1.60.2` → `198.51.100.10` | tcp/53 | izin | izin | ist:O6 | Geçti |
| G8-20 | Şube NTP sunucusu dışarıdan saat alır | `10.2.60.2` → `198.51.100.10` | udp/123 | izin | izin | izm:O6 | Geçti |
| G8-21 | Amsterdam DNS sunucusu dış adres çözer | `10.3.60.2` → `198.51.100.10` | udp/53 | izin | izin | ams:O6 | Geçti |
| G8-22 | Ankara NTP sunucusu dışarıdan saat alır | `10.4.60.2` → `198.51.100.10` | udp/123 | izin | izin | ank:O6 | Geçti |
| G9-01 | İstanbul IoT internete çıkamaz | `10.1.80.10` → `198.51.100.10` | tcp/443 | red | red | ist:O7 | Geçti |
| G9-02 | İzmir IoT internete çıkamaz | `10.2.80.10` → `198.51.100.10` | tcp/443 | red | red | izm:O7 | Geçti |
| G9-03 | Amsterdam IoT internete çıkamaz | `10.3.80.10` → `198.51.100.10` | tcp/80 | red | red | ams:O7 | Geçti |
| G9-04 | Ankara IoT internete çıkamaz | `10.4.80.10` → `198.51.100.10` | tcp/443 | red | red | ank:O7 | Geçti |
| G9-05 | Kamera ERP'ye ulaşamaz | `10.1.80.10` → `10.1.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G9-06 | Personel doğrudan SMTP yapamaz | `10.1.20.10` → `198.51.100.10` | tcp/25 | red | red | ist:O7 | Geçti |
| G9-07 | Personel sunucuya RDP yapamaz | `10.1.20.10` → `10.1.60.31` | tcp/3389 | red | red | ist:O7 | Geçti |
| G9-08 | İzmir personeli internete SSH yapamaz | `10.2.20.10` → `198.51.100.10` | tcp/22 | red | red | izm:O7 | Geçti |
| G9-09 | Amsterdam personeli internete SSH yapamaz | `10.3.20.10` → `198.51.100.10` | tcp/22 | red | red | ams:O7 | Geçti |
| G9-10 | Hoca internete SSH yapamaz | `10.4.88.10` → `198.51.100.10` | tcp/22 | red | red | ank:O7 | Geçti |
| G9-11 | Yazılımcı onaysız adrese SSH yapamaz | `10.1.30.10` → `198.51.100.10` | tcp/22 | red | red | ist:O7 | Geçti |
| G9-12 | Yazılımcı onaylı Git adresine SSH yapar | `10.1.30.10` → `github.com` | tcp/22 | izin | izin | ist:12 | Geçti |
| G9-13 | İzmir yazılımcısı onaylı Git adresine SSH yapar | `10.2.30.10` → `gitlab.com` | tcp/22 | izin | izin | izm:9 | Geçti |
| G9-14 | Onaylı adrese başka port kapalı | `10.1.30.10` → `github.com` | tcp/8080 | red | red | ist:O7 | Geçti |
| G9-15 | Personel yazıcıya baskı gönderir | `10.1.20.10` → `10.1.80.20` | tcp/631 | izin | izin | ist:15 | Geçti |
| G9-16 | Personel internete çıkar | `10.1.20.10` → `198.51.100.10` | tcp/443 | izin | izin | ist:11 | Geçti |
| G9-17 | Hoca ERP'ye ulaşamaz | `10.4.88.10` → `10.1.60.31` | tcp/443 | red | red | ank:O7 | Geçti |
| G9-18 | Laboratuvar öğrenci bilgi sistemine ulaşamaz | `10.4.110.10` → `10.4.60.31` | tcp/443 | red | red | ank:O7 | Geçti |
| G9-19 | Laboratuvar dosya sunucusuna ulaşır | `10.4.110.10` → `10.4.60.40` | tcp/445 | izin | izin | ank:9 | Geçti |
| G9-20 | Laboratuvar internete çıkar | `10.4.110.10` → `198.51.100.10` | tcp/443 | izin | izin | ank:10 | Geçti |
| G9-21 | Hoca not girer | `10.4.88.10` → `10.4.60.31` | tcp/443 | izin | izin | ank:6 | Geçti |
| G9-22 | Personel öğrenci işlemi yapar | `10.4.20.10` → `10.4.60.31` | tcp/443 | izin | izin | ank:7 | Geçti |
| G9-23 | Hoca yazıcıya baskı gönderir | `10.4.88.10` → `10.4.80.20` | tcp/9100 | izin | izin | ank:19 | Geçti |
| G10-01 | CRM İstanbul'a veri gönderemez | `10.3.60.20` → `10.1.60.31` | tcp/443 | red | red | ams:3 | Geçti |
| G10-02 | Amsterdam sunucuları merkezî izleme akışına girmez | `10.3.60.20` → `10.1.61.20` | tcp/10051 | red | red | ams:3 | Geçti |
| G10-03 | Amsterdam logu Türkiye'ye gitmez | `10.3.60.10` → `10.1.61.10` | tcp/6514 | red | red | ams:3 | Geçti |
| G10-04 | Amsterdam cihaz logu da Türkiye'ye gitmez | `10.3.10.1` → `10.1.61.10` | tcp/6514 | red | red | ams:O7 | Geçti |
| G10-05 | Amsterdam cihaz logu yerel toplayıcıya gider | `10.3.10.1` → `10.3.60.10` | tcp/6514 | izin | izin | ams:O5 | Geçti |
| G10-06 | Merkez tünelden CRM'e ulaşamaz | `172.31.3.1` → `10.3.60.20` | tcp/443 | red | red | ams:4 | Geçti |
| G10-07 | İstanbul teknik ekibi müşteri verisine ulaşamaz | `10.1.50.10` → `10.3.60.20` | tcp/443 | red | red | ist:O7 | Geçti |
| G10-08 | Amsterdam personeli CRM'e ulaşır | `10.3.20.10` → `10.3.60.20` | tcp/443 | izin | izin | ams:1 | Geçti |
| G10-09 | Yerel teknik ekip sunucuyu yönetir | `10.3.50.10` → `10.3.60.20` | tcp/22 | izin | izin | ams:2 | Geçti |
| G10-10 | CRM onaysız siteye çıkamaz | `10.3.60.20` → `198.51.100.10` | tcp/443 | red | red | ams:O7 | Geçti |
| G10-11 | Sunucu onaylı adresten güncelleme alır | `10.3.60.20` → `archive.ubuntu.com` | tcp/443 | izin | izin | ams:12 | Geçti |
| G10-12 | Onaylı adrese başka port kapalı | `10.3.60.20` → `archive.ubuntu.com` | tcp/22 | red | red | ams:O7 | Geçti |
| G11-01 | Proxy ERP'ye ulaşamaz | `10.1.64.40` → `10.1.60.31` | tcp/443 | red | red | ist:O7 | Geçti |
| G11-02 | Proxy bastion'a ulaşamaz | `10.1.64.40` → `10.1.61.5` | tcp/22 | red | red | ist:O7 | Geçti |
| G11-03 | Kamera kayıt sunucusu veritabanına ulaşamaz | `10.1.64.50` → `10.1.63.31` | tcp/5432 | red | red | ist:O7 | Geçti |
| G11-04 | ERP kendi veritabanına ulaşır | `10.1.60.31` → `10.1.63.31` | tcp/5432 | izin | izin | ist:24 | Geçti |
| G11-05 | ERP web veritabanına ulaşamaz | `10.1.60.31` → `10.1.63.30` | tcp/5432 | red | red | ist:O7 | Geçti |
| G11-06 | Git ERP veritabanına ulaşamaz | `10.1.60.32` → `10.1.63.31` | tcp/5432 | red | red | ist:O7 | Geçti |
| G11-07 | ERP bastion'a ulaşamaz | `10.1.60.31` → `10.1.61.5` | tcp/22 | red | red | ist:O7 | Geçti |
| G11-08 | ERP Wazuh paneline ulaşamaz | `10.1.60.31` → `10.1.61.10` | tcp/443 | red | red | ist:O7 | Geçti |
| G11-09 | Veritabanı internete çıkamaz | `10.1.63.31` → `198.51.100.10` | tcp/443 | red | red | ist:O7 | Geçti |
| G11-10 | Veritabanı ERP'ye bağlantı başlatamaz | `10.1.63.31` → `10.1.60.31` | tcp/22 | red | red | ist:O7 | Geçti |
| G11-11 | ERP güncellemeyi proxy'den alır | `10.1.60.31` → `10.1.64.40` | tcp/3128 | izin | izin | ist:25 | Geçti |
| G11-12 | Veritabanı güncellemeyi proxy'den alır | `10.1.63.31` → `10.1.64.40` | tcp/3128 | izin | izin | ist:25 | Geçti |
| G11-13 | Wazuh bildirimlerini proxy'den gönderir | `10.1.61.10` → `10.1.64.40` | tcp/3128 | izin | izin | ist:25 | Geçti |
| G11-14 | Bastion ERP sunucusunu yönetir | `10.1.61.5` → `10.1.60.31` | tcp/22 | izin | izin | ist:26 | Geçti |
| G11-15 | Bastion DMZ sunucusunu yönetir | `10.1.61.5` → `10.1.70.11` | tcp/22 | izin | izin | ist:26 | Geçti |
| G11-16 | Bastion veritabanı sunucusunu yönetir | `10.1.61.5` → `10.1.63.31` | tcp/22 | izin | izin | ist:27 | Geçti |
| G11-17 | Bastion veritabanı portuna doğrudan bağlanamaz | `10.1.61.5` → `10.1.63.31` | tcp/5432 | red | red | ist:O7 | Geçti |
| G11-18 | Teknik ekip veritabanına bastion'sız bağlanamaz | `10.1.50.10` → `10.1.63.31` | tcp/22 | red | red | ist:O7 | Geçti |
| G11-19 | Teknik ekip sunucuya RDP yapar | `10.1.50.10` → `10.1.60.31` | tcp/3389 | izin | izin | ist:7 | Geçti |
| G11-20 | Kamera kayıt sunucusuna ulaşır | `10.1.80.10` → `10.1.64.50` | tcp/554 | izin | izin | ist:13 | Geçti |
| G11-21 | Kamera proxy'ye ulaşamaz | `10.1.80.10` → `10.1.64.40` | tcp/3128 | red | red | ist:O7 | Geçti |
| G11-22 | LMS veritabanı öğrenci bilgi sistemine ulaşamaz | `10.4.63.30` → `10.4.60.31` | tcp/443 | red | red | ank:O7 | Geçti |
| G11-23 | Öğrenci bilgi sistemi LMS veritabanına ulaşamaz | `10.4.60.31` → `10.4.63.30` | tcp/5432 | red | red | ank:O7 | Geçti |
| G11-24 | Ankara proxy'si öğrenci bilgi sistemine ulaşamaz | `10.4.64.10` → `10.4.60.31` | tcp/443 | red | red | ank:O7 | Geçti |
| G11-25 | Öğrenci bilgi sistemi güncellemeyi proxy'den alır | `10.4.60.31` → `10.4.64.10` | tcp/3128 | izin | izin | ank:24 | Geçti |
| G11-26 | Kampüs teknik ekibi veritabanı sunucusunu yönetir | `10.4.50.10` → `10.4.63.30` | tcp/22 | izin | izin | ank:27 | Geçti |
| G11-27 | Teknik ekip veritabanı portuna doğrudan bağlanamaz | `10.4.50.10` → `10.4.63.30` | tcp/5432 | red | red | ank:O7 | Geçti |
| G11-28 | İzmir proxy'si Ar-Ge verisine ulaşamaz | `10.2.64.10` → `10.2.60.20` | tcp/443 | red | red | izm:O7 | Geçti |
| G11-29 | Ar-Ge sunucusu güncellemeyi proxy'den alır | `10.2.60.20` → `10.2.64.10` | tcp/3128 | izin | izin | izm:15 | Geçti |
| G11-30 | Amsterdam kamera kayıt sunucusu CRM'e ulaşamaz | `10.3.64.50` → `10.3.60.20` | tcp/443 | red | red | ams:O7 | Geçti |
| G11-31 | Amsterdam kamera kayıt logu yerel toplayıcıya gider | `10.3.64.50` → `10.3.60.10` | tcp/6514 | izin | izin | ams:O5 | Geçti |
| G12-01 | İstanbul WAF logu Wazuh'a ulaşır | `10.1.70.12` → `10.1.61.10` | tcp/6514 | izin | izin | ist:O5 | Geçti |
| G12-02 | Ankara WAF logu Wazuh'a ulaşır | `10.4.70.12` → `10.1.61.10` | tcp/6514 | izin | izin | ank:O5 ist:O5 | Geçti |
| G12-03 | İzmir DHCP logu İstanbul'a ulaşır | `10.2.60.2` → `10.1.61.10` | tcp/6514 | izin | izin | izm:O5 ist:O5 | Geçti |
| G12-04 | Ankara DHCP logu İstanbul'a ulaşır | `10.4.60.2` → `10.1.61.10` | tcp/6514 | izin | izin | ank:O5 ist:O5 | Geçti |
| G12-05 | İstanbul DHCP logu Wazuh'a ulaşır | `10.1.60.2` → `10.1.61.10` | tcp/6514 | izin | izin | ist:O5 | Geçti |
| G12-06 | Ankara cihaz logu Wazuh'a ulaşır | `10.4.10.1` → `10.1.61.10` | tcp/6514 | izin | izin | ank:O5 ist:O5 | Geçti |
| G12-07 | İzmir cihaz logu Wazuh'a ulaşır | `10.2.10.1` → `10.1.61.10` | tcp/6514 | izin | izin | izm:O5 ist:O5 | Geçti |
| G12-08 | İstanbul cihaz logu Wazuh'a ulaşır | `10.1.10.1` → `10.1.61.10` | tcp/6514 | izin | izin | ist:O5 | Geçti |
| G12-09 | Kullanıcı ağları log toplayıcıya yazamaz | `10.1.20.10` → `10.1.61.10` | tcp/6514 | red | red | ist:O7 | Geçti |
| G12-10 | Öğrenci log toplayıcıya yazamaz | `10.4.128.100` → `10.1.61.10` | tcp/6514 | red | red | ank:4 | Geçti |
| G13-01 | İstanbul personeli ERP'ye ulaşır | `10.1.20.10` → `10.1.60.31` | tcp/443 | izin | izin | ist:3 | Geçti |
| G13-02 | İstanbul yazılımcısı Git'e ulaşır | `10.1.30.10` → `10.1.60.32` | tcp/22 | izin | izin | ist:5 | Geçti |
| G13-03 | Bastion kullanıcıyı dizinden doğrular | `10.1.61.5` → `10.1.60.3` | tcp/636 | izin | izin | ist:31 | Geçti |
| G13-04 | İzmir teknik ekibi sunucuyu yönetir | `10.2.50.10` → `10.2.60.20` | tcp/3389 | izin | izin | izm:7 | Geçti |
| G13-05 | İzmir personeli internete çıkar | `10.2.20.10` → `198.51.100.10` | tcp/443 | izin | izin | izm:8 | Geçti |
| G13-06 | İzmir kamerası kayıt sunucusuna ulaşır | `10.2.80.10` → `10.2.64.50` | tcp/554 | izin | izin | izm:10 | Geçti |
| G13-07 | İzmir Ar-Ge yazıcıya baskı gönderir | `10.2.40.10` → `10.2.80.20` | tcp/9100 | izin | izin | izm:12 | Geçti |
| G13-08 | Amsterdam personeli internete çıkar | `10.3.20.10` → `198.51.100.10` | tcp/443 | izin | izin | ams:7 | Geçti |
| G13-09 | Amsterdam yazılımcısı onaylı Git adresine SSH yapar | `10.3.30.10` → `github.com` | tcp/22 | izin | izin | ams:8 | Geçti |
| G13-10 | Amsterdam kamerası kayıt sunucusuna ulaşır | `10.3.80.10` → `10.3.64.50` | tcp/554 | izin | izin | ams:9 | Geçti |
| G13-11 | Amsterdam teknik ekibi yazıcıya baskı gönderir | `10.3.50.10` → `10.3.80.20` | tcp/631 | izin | izin | ams:11 | Geçti |
| G13-12 | Kampüs teknik ekibi DMZ sunucusunu yönetir | `10.4.50.10` → `10.4.70.11` | tcp/22 | izin | izin | ank:15 | Geçti |
| G13-13 | Hoca internete çıkar | `10.4.88.10` → `198.51.100.10` | tcp/443 | izin | izin | ank:16 | Geçti |
| G13-14 | Kampüs kamerası kayıt sunucusuna ulaşır | `10.4.80.10` → `10.4.64.50` | tcp/554 | izin | izin | ank:17 | Geçti |
| G13-15 | Kampüs personeli LMS'e ulaşır | `10.4.20.10` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G13-16 | Laboratuvar LMS'e ulaşır | `10.4.110.10` → `10.4.70.10` | tcp/443 | izin | izin | ank:3 | Geçti |
| G13-17 | LMS kullanmayan ağlar kampüs içinden WAF'a ulaşamaz | `10.4.30.10` → `10.4.70.10` | tcp/443 | red | red | ank:O7 | Geçti |
