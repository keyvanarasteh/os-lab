# Kalkan A.Ş.

## 1. Projenin Genişletilmiş Amacı ve Kapsamı
Bu proje, uluslararası çapta faaliyet gösteren ve Ankara, İstanbul, Londra ofislerinin yanı sıra devasa bir akademik şube (10.000+ öğrenci) ile yüksek gizlilik gerektiren Ar-Ge ve Yazılım ekiplerini barındıran devasa bir yapının siber güvenlik mimarisini kurgulamaktadır. 

Mimarimiz sadece sınır güvenliğini (Perimeter Security) sağlayan donanım tabanlı Yeni Nesil Güvenlik Duvarlarından (NGFW - Palo Alto, FortiGate, Check Point vb.) ibaret değildir. "Savunma Derinliği" (Defense in Depth) prensibince, ağın içindeki sunucuların bizzat kendilerini koruyabilmeleri adına İşletim Sistemi (OS) seviyesinde yapılandırılan, Keyvan Arasteh'in İşletim Sistemleri Laboratuvarı (os-lab) firewall konseptlerinden ilham alan **UFW (Uncomplicated Firewall) ve iptables** entegrasyonlarını da kapsamaktadır.

## 2. Karma Mimari Yaklaşım (Zero Trust + Host-Based Security)
Kurumsal ağ mimarisinde iki katmanlı bir savunma hattı uygulanmaktadır:
* **Ağ Katmanı (Network Layer):** Şubeler arası VPN tünellerini, kampüs ağının yük dengesini, L7 uygulama denetimlerini ve SSL şifre çözme (SSL Decryption) işlemlerini üstlenen donanımsal NGFW cihazları.
* **Uç Nokta ve Sunucu Katmanı (Host-Based Layer):** DMZ ve iç ağda çalışan Ubuntu/Linux sunucuların üzerinde çalışan, doğrudan çekirdek (kernel) seviyesinde netfilter kancalarına takılan UFW kuralları. Bir saldırgan donanımsal firewall'u atlatıp iç ağa sızsa bile, her sunucu kendi kapılarını UFW ile koruyacaktır.

## 3. Depo (Repository) Yapısı
Bu depo, profesyonel bir ağ güvenliği dokümantasyonu standartlarına göre hazırlanmıştır:
* **Kök Dizin Dosyaları:** Şirket genelindeki ortak standartları, UFW kurulumlarını, `ufw-logger` ve Telegram entegrasyonlu izleme mimarisini (SOC) barındırır.
* **Şube Klasörleri (01-06):** O lokasyona özel kapasite analizlerini, IP/VLAN segmentasyon tablolarını, cihaz seçimlerini ve teknik kurulum talimatlarını barındırır.

## 4. Şirket ve Şube Envanteri (`company.json`)
Projenin temel konfigürasyonu olan `company.json` dosyası, aşağıdaki 5 temel şube ve birimin ağ altyapısını, popülasyonunu, donanım seçimlerini, gerekçelerini ve alternatif ürün kıyaslamalarını eksiksiz olarak barındırmaktadır:

* **01. Ankara Bölge Müdürlüğü (`ankara-office`):** 
  * *Rol:* İdari ve Satış Merkezi (Branch)
  * *Popülasyon:* 150 idari personel, 10 IT desteği.
  * *Ağ ve CIDR:* `10.1.10.0/24` (VLAN 10 İdari, VLAN 20 Satış).
  * *Donanım Tercihi:* FortiGate 200F ve Host-Based UFW katmanı.
  * *Gerekçe:* Application-Aware SD-WAN hat yedekliliği ve SPU CP9 ASIC şifreleme hızlandırma.
* **02. İstanbul Genel Merkez ve Veri Merkezi (`istanbul-office`):** 
  * *Rol:* Ana Veri Merkezi (Headquarters / DMZ Hub)
  * *Popülasyon:* 300 yönetim/finans çalışanı, 20 SOC analisti.
  * *Ağ ve CIDR:* `10.1.100.0/24` (VLAN 100 Yönetim, VLAN 200 DMZ).
  * *Donanım Tercihi:* Palo Alto PA-1410 High Availability Cluster (Active-Passive).
  * *Gerekçe:* Single-Pass mimarisi, Active Directory User-ID entegrasyonu ve SSL Inbound Inspection.
* **03. Londra Uydu Şube (`london-office`):** 
  * *Rol:* Uluslararası Satış ve Hukuk Ofisi (Remote Branch)
  * *Popülasyon:* 50 satış/hukuk personeli, 2 yerel IT asistanı.
  * *Ağ ve CIDR:* `10.3.10.0/24` (VLAN 10 Londra Corp).
  * *Donanım Tercihi:* Cisco Meraki MX68.
  * *Gerekçe:* Zero-Touch Provisioning (ZTP) ve bulut tabanlı tek panelden yönetim kolaylığı (Teknik uzmanın olmadığı uydu şube için ideal).
* **04. Üniversite Kampüsü (`academic-branch`):** 
  * *Rol:* Akademik Yerleşke (Campus Network)
  * *Popülasyon:* 10.000+ öğrenci (BYOD), 500 akademisyen.
  * *Ağ ve CIDR:* `10.20.0.0/16` (VLAN 100 Eduroam, VLAN 200 Faculty).
  * *Donanım Tercihi:* FortiGate 4400F (NP7 ASIC Hyperscale).
  * *Gerekçe:* Milyonlarca eşzamanlı oturum yönetimi, hat hızında (line-rate) DDoS koruması ve 5651 yasal loglama uyumluluğu.
* **05. Yazılım Geliştirme ve DevOps Şubesi (`software-team`):** 
  * *Rol:* Yazılım Geliştirme ve Staging Merkezi
  * *Popülasyon:* 140 geliştirici ve DevOps mühendisi.
  * *Ağ ve CIDR:* `10.5.50.0/24` (VLAN 50 Workstations, VLAN 60 Staging).
  * *Donanım Tercihi:* Check Point Quantum 6400.
  * *Gerekçe:* SmartConsole ve REST API / Terraform entegrasyonu sayesinde CI/CD süreçlerinde otomatik kural oluşturma (IaC) desteği.

## 5. Erişim Matrisi ve Güvenlik Duvarı Kuralları (Firewall Rules)
Tüm şube ve birimlerde **"Default Deny" (Varsayılan olarak Reddet)** prensibi katı bir şekilde uygulanmaktadır. Trafik akış matrisi şu kurallara dayanır:
* **Stateful Inspection:** Established/Related bağlantı paketleri otomatik olarak onaylanır; yetkisiz dışarıdan gelen bağlantılar düşürülür.
* **Öğrenci İzolasyonu:** Akademik şubedeki 10.000+ öğrenci internet ve DNS (`80, 443, 53`) dışındaki hiçbir iç ağ kaynağına (idari, sunucu, yazılım) erişemez.
* **Yazılım Ayrıcalıkları:** Yazılım ekibi CI/CD süreçleri gereği tüm iç ağlara kontrollü erişim hakkına sahiptir; ancak tüm hareketler denetlenir ve loglanır.
* **SSH Koruması:** Firewall ve kritik sunucuların SSH (`22`) portları yalnızca IT/SOC ve Ankara/Yazılım yönetim ağlarından kabul edilir.

## 6. Saldırı ve Savunma (Attack-Defense) Simülasyon Senaryoları
Sistemin dayanıklılığını kanıtlamak amacıyla koşturulan proaktif senaryolar:
1. **Ankara SMB Lateral Movement:** Satış ağından dosya sunucusuna yönelik yetkisiz port taramaları UFW `default deny incoming` politikası ile engellenmiştir.
2. **İstanbul SSH Brute-Force & UFW Logger:** DMZ sunucularına saniyede gelen ardışık başarısız SSH denemeleri `ufw-logger` daemon'ı tarafından yakalanmış, Telegram Bot API üzerinden SOC ekibine anlık uyarı geçilmiş ve Palo Alto tarafından dış IP karantinaya alınmıştır.
3. **Akademik SYN Flood Testi:** 10 Gbps üstü simüle edilmiş trafik FortiGate NP7 işlemcileri tarafından donanımsal olarak düşürülmüştür (Line-rate drop).

## 7. İzleme, Loglama ve Otomasyon
* **SIEM Entegrasyonu:** Merkezi Splunk ve QRadar core sistemleri.
* **Host Seviyesi Loglama:** `/var/log/ufw.log` dosyaları üzerinden systemd servisleri ile eşzamanlı `tail -f` takibi.
* **Alarm Mekanizması:** Kritik güvenlik ihlallerinde Telegram kanalına otomatik JSON bildirimleri.
