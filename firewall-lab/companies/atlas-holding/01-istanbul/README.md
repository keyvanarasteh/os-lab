# İstanbul Ofisi

Genel merkezdir. ERP, Git, SOC ve izleme sunucuları burada çalışır. Diğer şubelerin IPsec tünelleri de burada sonlanır.

[Ana sayfaya dön](../README.md)

## Kişi sayıları ve bant genişliği

| Grup | Kişi | Etkin hız | Gereken |
|---|---:|---:|---:|
| Personel | 250 | 2,1 Mbps | 525 Mbps |
| Yazılım | 60 | 8 Mbps | 480 Mbps |
| Teknik | 25 | 4 Mbps | 100 Mbps |
| Ar-Ge | 15 | 10,5 Mbps | 157,5 Mbps |
| **Toplam** | **350** | | **1.262,5 Mbps** |

`1.262,5 × 1,25 = 1.578 Mbps`. Satılan bir üst hız **2 Gbps ana hat**, yedek olarak **1 Gbps** seçildi.

**Kullanım profili:** Mesai saatlerinde görüntülü görüşme ve ERP yoğundur. Yazılım ekibi paket indirme ve Git trafiği üretir. Şube tünelleri de bu hattan geçer.

**VLAN başına bant genişliği (Mbps):**

| Trafik | Garanti | En yüksek | Yedek hatta |
|---|---:|---:|---:|
| Personel (VLAN 20) | 525 | 1.200 | 300 |
| Yazılım (VLAN 30) | 480 | 1.000 | 200 |
| Ar-Ge (VLAN 40, proxy ile) | 160 | 400 | 50 |
| Teknik (VLAN 50) | 100 | 300 | 80 |
| Sunucular ve şube tünelleri (VLAN 60, 61, 63, 64) | 400 | 800 | 300 |
| DMZ (VLAN 70) | 100 | 300 | 50 |
| Yönetim (VLAN 10) | 20 | 50 | 20 |
| Misafir (VLAN 85) | 0 | 20 | 0 |
| **Toplam** | **1.785** | | **1.000** |

## VLAN ve IP planı

| VLAN | Ağ | Alt ağ | Kullanılabilir | Hesap |
|---:|---|---|---:|---|
| 10 | Yönetim | 10.1.10.0/26 | 62 | Ağ cihazları |
| 20 | Personel | 10.1.20.0/22 | 1.022 | 250 × 2 × 1,3 = 650 |
| 30 | Yazılım | 10.1.30.0/24 | 254 | 60 × 2 × 1,3 = 156 |
| 40 | Ar-Ge | 10.1.40.0/26 | 62 | 15 × 2 × 1,3 = 39 |
| 50 | Teknik | 10.1.50.0/25 | 126 | 25 × 2 × 1,3 = 65 |
| 60 | Sunucu | 10.1.60.0/24 | 254 | Altyapı ve uygulama |
| 61 | Yönetim araçları | 10.1.61.0/27 | 30 | Bastion, izleme, merkezî yönetim |
| 63 | Veri | 10.1.63.0/26 | 62 | Veritabanları |
| 64 | Sınır servisleri | 10.1.64.0/26 | 62 | Proxy ve kamera kayıt |
| 70 | DMZ | 10.1.70.0/27 | 30 | Kurumsal web sitesi |
| 80 | IoT | 10.1.80.0/25 | 126 | Kamera, yazıcı, kartlı geçiş |
| 85 | Misafir | 10.1.85.0/24 | 254 | Ziyaretçiler |

**Sunucular:**

| VLAN | Nesne | Adres | Görev |
|---:|---|---|---|
| 60 | `ist-dns` | `10.1.60.2` | DNS, DHCP, NTP |
| 60 | `ist-ad` | `10.1.60.3` | Active Directory, RADIUS |
| 60 | `ist-erp` | `10.1.60.31` | ERP |
| 60 | `ist-git` | `10.1.60.32` | Git ve CI |
| 61 | `bastion` | `10.1.61.5` | Oturum kaydeden yönetim sunucusu |
| 61 | `fortimanager` | `10.1.61.6` | Güvenlik duvarı yönetimi |
| 61 | `wazuh` | `10.1.61.10` | SIEM, log toplayıcı |
| 61 | `zabbix` | `10.1.61.20` | İzleme |
| 61 | `glpi` | `10.1.61.21` | Olay kaydı |
| 61 | `grafana` | `10.1.61.22` | Panel |
| 63 | `ist-web-db` | `10.1.63.30` | Web sitesi veritabanı |
| 63 | `ist-erp-db` | `10.1.63.31` | ERP veritabanı |
| 64 | `ist-proxy` | `10.1.64.40` | Çıkış proxy'si |
| 64 | `ist-kamera-kayit` | `10.1.64.50` | Kamera kayıt |
| 70 | `ist-waf-vip` | `10.1.70.10` | WAF sanal adresi |
| 70 | `ist-web-uyg` | `10.1.70.11` | Web uygulaması |
| 70 | `ist-waf-1`, `ist-waf-2` | `10.1.70.12`, `10.1.70.13` | WAF düğümleri |
| 80 | `ist-yazici` | `10.1.80.20` | Yazıcı |

**VPN havuzları:** `vpn-personel` `10.1.200.0/22`, `vpn-gelistirici` `10.1.204.0/24`, `vpn-yonetici` `10.1.205.0/25`, `vpn-hoca` `10.1.208.0/22`.

## En iyi 5 güvenlik duvarı

Ana hat: 2 Gbps. Fiyat tek cihazın lisans ve destek hariç donanım fiyatıdır. Check Point fiyatına 1 yıllık SandBlast aboneliği dahildir, doğrudan karşılaştırılmaz.

| Model | Koruma hızı | Hat yükü | Fiyat (USD, adet) | Karar |
|---|---:|---:|---:|---|
| **FortiGate 200G ×2** | 6 Gbps | %33 | 8.920 | **Seçildi:** en ucuzu değil, ama VPN merkezi ve TLS denetimi için pay bırakır, ortak yönetime girer |
| Palo Alto PA-3410 | 7,5 Gbps | %27 | 25.140 | Güçlü uygulama denetimi var, ancak benzer kapasite için yaklaşık üç kat pahalı |
| Check Point Force 3950 | 5,5 Gbps | %36 | 12.050 (1 yıl abonelik dahil) | Yeterli, ancak Fortinet yönetimine girmez |
| Cisco Firepower 1150 | 4,9 Gbps | %41 | 7.830 | Yeterli ve daha ucuz, ancak kapasitesi en düşük ve veri sayfası eski |
| Sophos XGS 2300 | 5,9 Gbps | %34 | 4.290 | En ucuz seçenek, ancak VPN merkezi için SD-WAN ve ortak yönetimde Fortinet'i tercih ettik |

**Neden hattın gerektirdiğinden büyük?** Bütün şube tünelleri ve merkezî servis trafiği bu cihazdan geçer. Sunucu segmentleri arasındaki trafik de artık bu cihazdan geçer. Bu nedenle İzmir'deki 120G yerine 200G seçildi.

**Seçilen modelin kapasite kontrolü:**

| Ölçüt | Tahmini ihtiyaç | FortiGate 200G |
|---|---:|---:|
| TLS denetimi | (525 + 480 + 100) × 1,25 = 1.381 Mbps | 7 Gbps |
| Eşzamanlı oturum | 350 × 2 × 100 × 1,3 = 91.000 | 11 milyon |

## Kural seti

Sıra: [O1-O6](../README.md#6-ortak-kurallar) → aşağıdaki kurallar → O7. Adların karşılığı [NESNELER.md](../NESNELER.md) dosyasındadır.

| No | Kaynak | Hedef | Servis | İşlem | Neden? |
|---:|---|---|---|---|---|
| 1 | `internet` | `ist-waf-vip` | tcp/443 | Hız sınırı, IPS | Kurumsal site yalnızca DMZ'deki WAF üzerinden yayınlanır |
| 2 | `ist-web-uyg` | `ist-web-db` | tcp/5432 | İzin, log | Web uygulaması yalnızca kendi veritabanına ulaşır |
| 3 | `ist-v20-personel` | `ist-erp` | tcp/443 | İzin | Personelin iş uygulaması |
| 4 | `sube-personel` | `ist-erp` | tcp/443 | İzin | Diğer şubeler de merkezî ERP'yi kullanır |
| 5 | `ist-v30-yazilim` | `ist-git` | tcp/22, tcp/443 | İzin | Yazılım ekibinin kod erişimi |
| 6 | `sube-yazilim` | `ist-git` | tcp/22, tcp/443 | İzin | Tek kod deposu kullanılır |
| 7 | `ist-v50-teknik` | `ist-yonetilen-sunucular` | tcp/22, tcp/443, tcp/3389 | İzin, log | Sunucu yönetimi yalnızca teknik ekipte |
| 8 | `ist-v40-arge` | `ist-proxy` | tcp/3128 | İzin | Ar-Ge internete yalnızca proxy ile çıkar |
| 9 | `ist-proxy` | `internet` | tcp/80, tcp/443 | İzin, web filtresi | Çıkış tek noktadan denetlenir |
| 10 | `ist-v40-arge` | `internet` | tümü | Reject, alarm | Proxy dışı çıkış veri sızıntısı işareti olabilir; uygulama hemen hata alır |
| 11 | `ist-kurumsal` | `internet` | tcp/80, tcp/443 | İzin, IPS, TLS denetimi, `up-kurumsal` | Normal internet erişimi |
| 12 | `ist-v30-yazilim` | `onayli-git` | tcp/22 | İzin | Dış depolara SSH yalnızca onaylı adreslere gider |
| 13 | `ist-v80-iot` | `ist-kamera-kayit` | tcp/554 | İzin | Kameraların internete ihtiyacı yoktur |
| 14 | `ist-v85-misafir` | `internet` | tcp/53, udp/53, tcp/80, tcp/443 | İzin, 20 Mbps VLAN sınırı, `up-misafir` | Misafir iç ağa erişmez, yalnızca internete çıkar |
| 15 | `ist-yazici-istemcileri` | `ist-yazici` | tcp/631, tcp/9100 | İzin | Yazıcılar IoT ağında olduğu için baskı ayrı izin ister |
| 16 | `ist-v70-dmz` | `ist-proxy` | tcp/3128 | İzin, log | DMZ sunucusu güncellemesini internete doğrudan çıkmadan alır |
| 17 | `ist-izleme-kaynaklari` | `zabbix` | tcp/10051 | İzin | Sunucular izleme verisini merkeze gönderir, Zabbix içeri bağlanmaz |
| 18 | `wan-subeler` | `wan-istanbul` | udp/500, udp/4500 | İzin | Şube tünelleri yalnızca bilinen adreslerden kurulur |
| 19 | `internet` | `wan-istanbul` | udp/500, udp/4500 | Hız sınırı | Çalışanlar her yerden bağlanır, deneme saldırıları sınırlanır |
| 20 | `vpn-personel` | `ist-erp` | tcp/443 | İzin, log | Personel uzaktan yalnızca ERP'ye ulaşır |
| 21 | `vpn-gelistirici` | `ist-git` | tcp/22, tcp/443 | İzin, log | Geliştirici uzaktan yalnızca koda ulaşır |
| 22 | `vpn-hoca` | `ank-obs` | tcp/443 | İzin, log | Hoca evden not girebilir |
| 23 | `vpn-yonetici` | `bastion` | tcp/22, tcp/443 | İzin, log | Yönetici uzaktan yalnızca bastion'a ulaşır, cihazlara oradan geçer |
| 24 | `ist-erp` | `ist-erp-db` | tcp/5432 | İzin, log | ERP yalnızca kendi veritabanına ulaşır |
| 25 | `ist-guncelleme-kaynaklari` | `ist-proxy` | tcp/3128 | İzin | İç sunucular güncellemeyi proxy'den alır |
| 26 | `bastion` | `ist-yonetilen-sunucular` | tcp/22, tcp/443, tcp/3389 | İzin, log | Uzaktaki yönetici sunuculara kayıtlı oturumla geçer |
| 27 | `bastion` | `ist-v63-veri` | tcp/22 | İzin, log | Veritabanı yönetimi yalnızca bastion'dan yapılır |
| 28 | `ist-v50-teknik` | `bastion` | tcp/22, tcp/443 | İzin, log | Ofisteki teknik ekip de cihazlara bastion'dan geçer |
| 29 | `ist-v50-teknik` | `ist-panel-sunuculari` | tcp/443 | İzin, log | SOC ve operasyon panellere HTTPS ile ulaşır |
| 30 | `sube-fw-tunel` | `fortimanager` | tcp/541 | İzin, log | Şube güvenlik duvarları tek panelden yönetilir |
| 31 | `ist-v61-yonetim-araclari` | `ist-ad` | tcp/636 | İzin | Bastion ve paneller dizin hesabı kullanır |
| 32 | `ank-radius` | `ist-ad` | tcp/636 | İzin | Kampüs RADIUS'u kullanıcıları merkezî dizinden doğrular |

**Şubeler arası izinlerin karşılığı** [ana sayfada](../README.md#şubeler-arası-akışlar) yazılıdır. Bir şube izni, buradaki karşılığı olmadan çalışmaz.

## İzleme

**Yerel sorumlu:** İstanbul teknik sorumlusu. SOC ekibi de bu ofiste çalışır.

| İzlenen | Eşik | Seviye | İlk müdahale |
|---|---|---|---|
| Ana hat doluluğu | 5 dakika boyunca 1,7 Gbps üzeri (%85) | Orta | L1 |
| Yedek hat doluluğu | 5 dakika boyunca 850 Mbps üzeri (%85) | Orta | L1 |
| Şube tüneli koptu | 2 dakika | Kritik | L2: şubeler ERP ve Git'e ulaşamaz |
| ERP yanıt süresi | 5 dakika boyunca 2 saniye üzeri | Yüksek | L1, ERP ekibi bilgilendirilir |
| Wazuh veya Zabbix durdu | 2 dakika | Kritik | L2: izleme durursa diğer alarmlar da gelmez |
| WAF veya web sunucusunda kritik saldırı imzası | Anında | Yüksek | L1, gerekirse L2 |
| DMZ'den iç ağa izinsiz bağlantı denemesi | Anında | Kritik | Nöbetçi L2 aranır: sunucu ele geçirilmiş olabilir, ağdan ayrılır |
| Sınır servislerinden (VLAN 64) iç sunuculara deneme | Anında | Yüksek | L1: proxy veya kamera kayıt sunucusu ele geçirilmiş olabilir |
| Sunucu güvenlik duvarında beklenmeyen ret | 5 dakikada 20 ret | Orta | L1: aynı VLAN içinde yayılma denemesi olabilir |

## Şubeye özel kurulum ve testler

1. Şubeler bu cihaza bağlandığı için IPsec merkezini kurmadan diğer şubelere geçilmez.
2. Wazuh ve Zabbix sunucuları, ilk log akışından önce VLAN 61'de hazır olur.

**Durum** sütunu testin gerçekten çalıştırılıp çalıştırılmadığını gösterir. **Paket** gerçek Linux paket testidir ([sonuçlar](../lab/sonuclar/PAKET.md)) ve FortiGate üzerinde yapılmamıştır.

| Test | Beklenen sonuç | Durum |
|---|---|---|
| Ana hattı kes | Yedek hat devreye girer, alarm oluşur | Çalıştırılmadı: SD-WAN lab dışında |
| Aktif cihazı kapat | Pasif cihaz devralır, kritik alarm oluşur | Çalıştırılmadı: HA lab dışında |
| VLAN 20'den `10.1.10.1` adresine HTTPS dene | Engellenir, O3 alarmı oluşur | Paket `G5-10`: engellendi. Alarm sınanmadı |
| VLAN 40'tan proxy olmadan internete çık | Engellenir, kural 10 alarmı oluşur | Paket `G3-04`: engellendi. Alarm sınanmadı |
| İnternetten WAN IP'sine SSH dene | Bağlantı kurulamaz | Paket `G5-16` |
| VLAN 20'den yazıcıya baskı gönder | Çalışır (kural 15) | Paket `G9-15` |
| VLAN 80'den internete çık | O7 ile engellenir | Paket `G9-01` |
| İnternetten `10.1.70.11` adresine bağlan | O7 ile engellenir, yalnızca WAF yayındadır | Paket `G6-03` |
| Web sitesine örnek SQL enjeksiyonu isteği gönder | WAF engeller, Wazuh'ta log oluşur | [Duman testi](../waf/sonuclar/DUMAN.md): ModSecurity engelledi. Log yolu paket `G12-01`, Wazuh kaydı sınanmadı |
| Personel VPN profiliyle Git'e bağlan | O7 ile engellenir, yalnızca ERP açıktır | Paket `G4-02`. VPN yazılımı sınanmadı, havuz adresi kullanıldı |
| Yönetici VPN'inden `10.1.10.1` adresine doğrudan bağlan | O3 ile engellenir | Paket `G5-01` |
| Bastion üzerinden `10.1.10.1` adresine bağlan | Çalışır, oturum kaydedilir | Paket `G5-02`. Oturum kaydı sınanmadı |
| Proxy'den ERP'ye bağlan | O7 ile engellenir | Paket `G11-01` |
| ERP'den Git sunucusuna SSH yap (aynı VLAN) | Sunucu güvenlik duvarı engeller | Paket `S-06`. Çevre güvenlik duvarı bu trafiği görmez |
