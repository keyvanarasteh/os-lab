# İzmir Ofisi

Ar-Ge merkezidir. Şirketin en fazla Ar-Ge personeli ve fikri mülkiyet açısından en hassas verisi burada bulunur.

[Ana sayfaya dön](../README.md)

## Kişi sayıları ve bant genişliği

| Grup | Kişi | Etkin hız | Gereken |
|---|---:|---:|---:|
| Personel | 120 | 2,1 Mbps | 252 Mbps |
| Yazılım | 25 | 8 Mbps | 200 Mbps |
| Teknik | 12 | 4 Mbps | 48 Mbps |
| Ar-Ge | 40 | 10,5 Mbps | 420 Mbps |
| **Toplam** | **197** | | **920 Mbps** |

`920 × 1,25 = 1.150 Mbps`. 1 Gbps yetmediği için **2 Gbps ana hat**, yedek olarak **1 Gbps** seçildi.

**Kullanım profili:** Ar-Ge, büyük veri setleri indirir ve test ortamları çalıştırır. Trafiğin yaklaşık yarısı bu ekipten gelir. Git ve ERP erişimi İstanbul tüneli üzerinden yapılır.

**VLAN başına bant genişliği (Mbps):**

| Trafik | Garanti | En yüksek | Yedek hatta |
|---|---:|---:|---:|
| Personel (VLAN 20) | 260 | 800 | 260 |
| Yazılım (VLAN 30) | 200 | 600 | 200 |
| Ar-Ge (VLAN 40, proxy ile) | 420 | 1.200 | 420 |
| Teknik (VLAN 50) | 50 | 200 | 50 |
| Sunucular (VLAN 60, 64) | 100 | 300 | 60 |
| Yönetim (VLAN 10) | 10 | 50 | 10 |
| Misafir (VLAN 85) | 0 | 10 | 0 |
| **Toplam** | **1.040** | | **1.000** |

## VLAN ve IP planı

| VLAN | Ağ | Alt ağ | Kullanılabilir | Hesap |
|---:|---|---|---:|---|
| 10 | Yönetim | 10.2.10.0/26 | 62 | Ağ cihazları |
| 20 | Personel | 10.2.20.0/23 | 510 | 120 × 2 × 1,3 = 312 |
| 30 | Yazılım | 10.2.30.0/25 | 126 | 25 × 2 × 1,3 = 65 |
| 40 | Ar-Ge | 10.2.40.0/25 | 126 | 40 × 2 × 1,3 = 104 |
| 50 | Teknik | 10.2.50.0/26 | 62 | 12 × 2 × 1,3 = 32 |
| 60 | Sunucu | 10.2.60.0/25 | 126 | Altyapı ve Ar-Ge verisi |
| 64 | Sınır servisleri | 10.2.64.0/26 | 62 | Proxy ve kamera kayıt |
| 80 | IoT | 10.2.80.0/25 | 126 | Kamera, yazıcı, kartlı geçiş |
| 85 | Misafir | 10.2.85.0/24 | 254 | Ziyaretçiler |

İnternete açık servis olmadığı için DMZ yoktur.

**Sunucular:**

| VLAN | Nesne | Adres | Görev |
|---:|---|---|---|
| 60 | `izm-dns` | `10.2.60.2` | DNS, DHCP, NTP |
| 60 | `izm-arge-veri` | `10.2.60.20` | Ar-Ge veri sunucusu |
| 64 | `izm-proxy` | `10.2.64.10` | Çıkış proxy'si |
| 64 | `izm-kamera-kayit` | `10.2.64.50` | Kamera kayıt |
| 80 | `izm-yazici` | `10.2.80.20` | Yazıcı |

**Neden proxy ayrı segmentte?** Proxy internete değer, Ar-Ge verisi şirketin en hassas verisidir. Aynı VLAN'da olsalardı aralarındaki trafik güvenlik duvarından geçmezdi.

## En iyi 5 güvenlik duvarı

Ana hat: 2 Gbps. Fiyat tek cihazın lisans ve destek hariç donanım fiyatıdır. Check Point fiyatına 1 yıllık SandBlast aboneliği dahildir, doğrudan karşılaştırılmaz.

| Model | Koruma hızı | Hat yükü | Fiyat (USD, adet) | Karar |
|---|---:|---:|---:|---|
| **FortiGate 120G ×2** | 2,8 Gbps | %71 | 4.280 | **Seçildi:** en ucuzu değil, ama hattı karşılar, 3 Gbps TLS denetimi sunar ve ortak yönetime girer |
| Palo Alto PA-460 | 2,1-3 Gbps | %67-95 | 4.750 | Yeterli, ancak kaynaklardaki hız farklı ve daha pahalı |
| Check Point Force 3920 | 3,2 Gbps | %63 | 6.020 (1 yıl abonelik dahil) | Yeterli, ancak Fortinet yönetimine girmez |
| Cisco Firepower 1140 | 3,3 Gbps | %61 | 2.860 | Daha ucuz ve yeterli, ancak Fortinet yönetimine girmez ve veri sayfası eski |
| Sophos XGS 2100 | 5,6 Gbps | %36 | 2.290 | En ucuz seçenek ve kapasitesi yüksek, ancak değer ideal koşullarda ölçülmüş ve ortak yönetim dışında kalıyor |

**Sınır:** Trafik büyür ve hat yükü sürekli %85'i geçerse model yükseltmesi gündeme gelir. Zabbix bu eğilimi gösterir.

**Seçilen modelin kapasite kontrolü:**

| Ölçüt | Tahmini ihtiyaç | FortiGate 120G |
|---|---:|---:|
| TLS denetimi | (252 + 200 + 48) × 1,25 = 625 Mbps | 3 Gbps |
| Eşzamanlı oturum | 197 × 2 × 100 × 1,3 = 51.220 | 3 milyon |

Ar-Ge trafiği proxy üzerinden web filtresinden geçer ve kural 3'te TLS denetimi olmadığı için TLS hesabına dahil değildir.

## Kural seti

Sıra: [O1-O6](../README.md#6-ortak-kurallar) → aşağıdaki kurallar → O7. Adların karşılığı [NESNELER.md](../NESNELER.md) dosyasındadır.

| No | Kaynak | Hedef | Servis | İşlem | Neden? |
|---:|---|---|---|---|---|
| 1 | `izm-v40-arge` | `izm-arge-veri` | tcp/22, tcp/443 | İzin, log | Ekip yalnızca kendi verisine ulaşır |
| 2 | `izm-v40-arge` | `izm-proxy` | tcp/3128 | İzin | Tüm çıkış kayıt altına alınır |
| 3 | `izm-proxy` | `internet` | tcp/80, tcp/443 | İzin, web filtresi | Çıkış tek noktadan denetlenir |
| 4 | `izm-v40-arge` | `internet` | tümü | Reject, alarm | Proxy dışı çıkış veri sızıntısı işareti olabilir; uygulama hemen hata alır |
| 5 | `izm-v20-personel` | `ist-erp` | tcp/443 | İzin | Merkezî iş uygulaması |
| 6 | `izm-v30-yazilim` | `ist-git` | tcp/22, tcp/443 | İzin | Tek kod deposu kullanılır |
| 7 | `izm-v50-teknik` | `izm-yonetilen-sunucular` | tcp/22, tcp/443, tcp/3389 | İzin, log | Sunucu yönetimi yalnızca teknik ekipte |
| 8 | `izm-kurumsal` | `internet` | tcp/80, tcp/443 | İzin, IPS, TLS denetimi, `up-kurumsal` | Normal internet erişimi |
| 9 | `izm-v30-yazilim` | `onayli-git` | tcp/22 | İzin | Dış depolara SSH yalnızca onaylı adreslere gider |
| 10 | `izm-v80-iot` | `izm-kamera-kayit` | tcp/554 | İzin | Kameraların internete ihtiyacı yoktur |
| 11 | `izm-v85-misafir` | `internet` | tcp/53, udp/53, tcp/80, tcp/443 | İzin, 10 Mbps VLAN sınırı, `up-misafir` | Misafir iç ağa erişmez, yalnızca internete çıkar |
| 12 | `izm-yazici-istemcileri` | `izm-yazici` | tcp/631, tcp/9100 | İzin | Yazıcılar IoT ağında olduğu için baskı ayrı izin ister |
| 13 | `izm-izleme-kaynaklari` | `zabbix` | tcp/10051 | İzin | Proxy ve sunucuların durumu merkezden izlenir |
| 14 | `wan-istanbul` | `wan-izmir` | udp/500, udp/4500 | İzin | IPsec tüneli yalnızca merkezin adresinden kurulur |
| 15 | `izm-v60-sunucu` | `izm-proxy` | tcp/3128 | İzin | Sunucular güncellemeyi proxy'den alır |

## İzleme

**Yerel sorumlu:** İzmir teknik sorumlusu. Ar-Ge ile ilgili olaylarda Ar-Ge lideri de bilgilendirilir.

| İzlenen | Eşik | Seviye | İlk müdahale |
|---|---|---|---|
| Ana hat doluluğu | 5 dakika boyunca 1,7 Gbps üzeri (%85) | Orta | L1 |
| Yedek hat doluluğu | 5 dakika boyunca 850 Mbps üzeri (%85) | Orta | L1 |
| Proxy durdu | 2 dakika | Yüksek | Yerel sorumlu: Ar-Ge internete çıkamaz |
| Kural 4: proxy dışı çıkış denemesi | Anında | Yüksek | L1: cihaz ve kullanıcı belirlenir |
| Proxy üzerinden dışarı veri yükleme | 1 saatte 20 GB üzeri | Yüksek | L2: Ar-Ge'nin normal trafiği indirmedir, yüksek yükleme veri sızıntısı olabilir |

20 GB bir başlangıç varsayımıdır. İlk ayların gerçek kullanımına göre güncellenir.

## Şubeye özel kurulum ve testler

1. Proxy sunucusu, Ar-Ge kullanıcıları ağa alınmadan önce hazır olur.
2. Ar-Ge veri sunucusunun yedeği şube içinde tutulur.

**Durum** sütunu testin gerçekten çalıştırılıp çalıştırılmadığını gösterir. **Paket** gerçek Linux paket testidir ([sonuçlar](../lab/sonuclar/PAKET.md)) ve FortiGate üzerinde yapılmamıştır.

| Test | Beklenen sonuç | Durum |
|---|---|---|
| Ana hattı kes | Yedek hat devreye girer, alarm oluşur | Çalıştırılmadı: SD-WAN lab dışında |
| VLAN 40'tan proxy olmadan internete çık | Engellenir, kural 4 alarmı oluşur | Paket `G3-05`: engellendi. Alarm sınanmadı |
| VLAN 20'den Ar-Ge verisine bağlan | O7 ile engellenir | Paket `G3-12` |
| VLAN 30'dan İstanbul Git'e bağlan | Tünel üzerinden çalışır | Paket `G7-04`. IPsec sınanmadı |
| VLAN 40'tan yazıcıya baskı gönder | Çalışır (kural 12) | Paket `G13-07` |
| Proxy'den Ar-Ge verisine bağlan | O7 ile engellenir | Paket `G11-28` |
