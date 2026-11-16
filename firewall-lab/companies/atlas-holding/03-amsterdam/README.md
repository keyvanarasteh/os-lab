# Amsterdam Ofisi

Yurt dışı satış ofisidir ve müşteri verileri nedeniyle GDPR kapsamındadır. Kişisel veriler Hollanda'daki yerel sunucuda tutulur. Ar-Ge ekibi yoktur.

[Ana sayfaya dön](../README.md)

## Kişi sayıları ve bant genişliği

| Grup | Kişi | Etkin hız | Gereken |
|---|---:|---:|---:|
| Personel | 80 | 2,1 Mbps | 168 Mbps |
| Yazılım | 20 | 8 Mbps | 160 Mbps |
| Teknik | 8 | 4 Mbps | 32 Mbps |
| **Toplam** | **108** | | **360 Mbps** |

`360 × 1,25 = 450 Mbps`. Satılan bir üst hız **500 Mbps ana hat**, yedek olarak **250 Mbps** seçildi.

**Kullanım profili:** SaaS uygulamaları, müşteri görüşmeleri ve İstanbul ile yapılan görüntülü toplantılar yoğundur. Git ve ERP erişimi tünel üzerinden yapılır.

**VLAN başına bant genişliği (Mbps):**

| Trafik | Garanti | En yüksek | Yedek hatta |
|---|---:|---:|---:|
| Personel (VLAN 20) | 170 | 350 | 110 |
| Yazılım (VLAN 30) | 160 | 300 | 80 |
| Teknik (VLAN 50) | 35 | 100 | 20 |
| Sunucular (VLAN 60, 64) | 50 | 100 | 35 |
| Yönetim (VLAN 10) | 5 | 20 | 5 |
| Misafir (VLAN 85) | 0 | 10 | 0 |
| **Toplam** | **420** | | **250** |

## VLAN ve IP planı

| VLAN | Ağ | Alt ağ | Kullanılabilir | Hesap |
|---:|---|---|---:|---|
| 10 | Yönetim | 10.3.10.0/26 | 62 | Ağ cihazları |
| 20 | Personel | 10.3.20.0/24 | 254 | 80 × 2 × 1,3 = 208 |
| 30 | Yazılım | 10.3.30.0/26 | 62 | 20 × 2 × 1,3 = 52 |
| 50 | Teknik | 10.3.50.0/27 | 30 | 8 × 2 × 1,3 = 21 |
| 60 | Sunucu | 10.3.60.0/26 | 62 | Altyapı, log toplayıcı, müşteri verisi |
| 64 | Sınır servisleri | 10.3.64.0/26 | 62 | Kamera kayıt |
| 80 | IoT | 10.3.80.0/26 | 62 | Kamera, yazıcı, kartlı geçiş |
| 85 | Misafir | 10.3.85.0/24 | 254 | Ziyaretçiler |

Ar-Ge ekibi ve internete açık servis olmadığı için VLAN 40 ve DMZ yoktur.

**Sunucular:**

| VLAN | Nesne | Adres | Görev |
|---:|---|---|---|
| 60 | `ams-dns` | `10.3.60.2` | DNS, DHCP, NTP |
| 60 | `ams-log-toplayici` | `10.3.60.10` | Yerel log toplayıcı |
| 60 | `ams-crm` | `10.3.60.20` | Müşteri (CRM) sunucusu |
| 64 | `ams-kamera-kayit` | `10.3.64.50` | Kamera kayıt |
| 80 | `ams-yazici` | `10.3.80.20` | Yazıcı |

**Neden kamera kayıt ayrı segmentte?** Kamera kayıt sunucusu güvenilmeyen IoT cihazlarıyla konuşur, CRM ise kişisel veri tutar. Aynı VLAN'da olsalardı aralarındaki trafik güvenlik duvarından geçmezdi.

## En iyi 5 güvenlik duvarı

Ana hat: 500 Mbps. Fiyat tek cihazın lisans ve destek hariç donanım fiyatıdır. Check Point fiyatına 1 yıllık SandBlast aboneliği dahildir, doğrudan karşılaştırılmaz.

| Model | Koruma hızı | Hat yükü | Fiyat (USD, adet) | Karar |
|---|---:|---:|---:|---|
| **FortiGate 70G ×2** | 1,3 Gbps | %38 | 1.210 | **Seçildi:** en ucuzu değil, ama hattın iki katından fazla kapasite ve TLS denetimi için pay bırakır, ortak yönetime girer |
| Palo Alto PA-410 | 800 Mbps | %63 | 850 | Daha ucuz ve yeterli, ancak büyüme payı düşük ve ortak yönetim dışında kalıyor |
| Check Point Spark 1600 | 1,5 Gbps | %33 | 4.010 (1 yıl abonelik dahil) | Kapasitesi yüksek, ancak ortak yönetim dışında kalıyor |
| Cisco Firepower 1010 | 880 Mbps | %57 | 1.070 | Yeterli ve biraz daha ucuz, ancak ortak yönetim dışında kalıyor ve veri sayfası eski |
| Sophos XGS 88 | 2 Gbps | %25 | 640 | Fiyat ve hız güçlü, ancak değer ideal koşullarda ölçülmüş ve ortak yönetim dışında kalıyor |

**Neden küçük ofiste de HA?** Teknik ekip küçük ve yurt dışında olduğu için arıza durumunda cihaz değişimi vakit alabilir. İkinci cihaz bu süreyi karşılar.

**Neden FortiGate 60F değil?** Koruma hızı (700 Mbps) bu hat için yeterli olsa da satıcı sayfası modelin sipariş sonuna yaklaştığını belirtiyor. Yeni kurulumda ömrü bitmek üzere olan bir model seçmek, kısa süre sonra yeniden değişim planlamak demektir.

**Seçilen modelin kapasite kontrolü:**

| Ölçüt | Tahmini ihtiyaç | FortiGate 70G |
|---|---:|---:|
| TLS denetimi | Kapalı. Açılırsa 360 × 1,25 = 450 Mbps | 1,4 Gbps |
| Eşzamanlı oturum | 108 × 2 × 100 × 1,3 = 28.080 | 1,4 milyon |

## Kural seti

Sıra: [O1-O6](../README.md#6-ortak-kurallar) → aşağıdaki kurallar → O7. Adların karşılığı [NESNELER.md](../NESNELER.md) dosyasındadır. O5'in hedefi burada yerel toplayıcıdır, log Hollanda dışına çıkmaz.

| No | Kaynak | Hedef | Servis | İşlem | Neden? |
|---:|---|---|---|---|---|
| 1 | `ams-v20-personel` | `ams-crm` | tcp/443 | İzin, log | Müşteri verisi yerel sunucudan kullanılır |
| 2 | `ams-v50-teknik` | `ams-sunucular` | tcp/22, tcp/443 | İzin, log | Sunucu yönetimi yerel teknik ekiptedir |
| 3 | `ams-sunucular` | `ams-uzak-ozel` | tümü | Red, alarm | Kişisel veri, onaysız şekilde yurt dışına aktarılamaz |
| 4 | `ams-uzak-ozel` | `ams-sunucular` | tümü | Red, alarm | Merkezden kişisel veriye doğrudan erişim engellenir |
| 5 | `ams-v20-personel` | `ist-erp` | tcp/443 | İzin | Merkezî iş uygulaması |
| 6 | `ams-v30-yazilim` | `ist-git` | tcp/22, tcp/443 | İzin | Tek kod deposu kullanılır |
| 7 | `ams-kurumsal` | `internet` | tcp/80, tcp/443 | İzin, IPS, web filtresi, `up-kurumsal` | Normal internet erişimi |
| 8 | `ams-v30-yazilim` | `onayli-git` | tcp/22 | İzin | Dış depolara SSH yalnızca onaylı adreslere gider |
| 9 | `ams-v80-iot` | `ams-kamera-kayit` | tcp/554 | İzin | Kameraların internete ihtiyacı yoktur |
| 10 | `ams-v85-misafir` | `internet` | tcp/53, udp/53, tcp/80, tcp/443 | İzin, 10 Mbps VLAN sınırı, `up-misafir` | Misafir iç ağa erişmez, yalnızca internete çıkar |
| 11 | `ams-yazici-istemcileri` | `ams-yazici` | tcp/631, tcp/9100 | İzin | Yazıcılar IoT ağında olduğu için baskı ayrı izin ister |
| 12 | `ams-sunucular` | `onayli-guncelleme` | tcp/443 | İzin, log | Proxy olmadığı için sunucular yalnızca güncelleme adreslerine çıkar |
| 13 | `wan-istanbul` | `wan-amsterdam` | udp/500, udp/4500 | İzin | IPsec tüneli yalnızca merkezin adresinden kurulur |

**TLS denetimi:** Çalışan gizliliği nedeniyle kapalı başlar. Açılması için hukuk birimi onayı gerekir.

**Onaylı güncelleme adresleri:** `onayli-guncelleme` sunucuların Ubuntu olduğu varsayımıyla yazılmıştır. İşletim sistemi kesinleşince güncellenir.

**Hukuki not:** Bu kurallar teknik bir sınır çizer. GDPR uyumu ve verinin aktarım şartları hukuk birimiyle doğrulanır.

## İzleme

**Yerel sorumlu:** Amsterdam teknik sorumlusu. Kişisel veriyle ilgili olaylarda Veri Koruma Sorumlusu da bilgilendirilir.

| İzlenen | Eşik | Seviye | İlk müdahale |
|---|---|---|---|
| Ana hat doluluğu | 5 dakika boyunca 425 Mbps üzeri (%85) | Orta | L1 |
| Yedek hat doluluğu | 5 dakika boyunca 212,5 Mbps üzeri (%85) | Orta | L1 |
| Kural 3 veya 4: tünel ile sunucu ağları arasında trafik denemesi | Anında | Yüksek | L1, Veri Koruma Sorumlusu bilgilendirilir |
| Sunuculardan onaylı olmayan adrese çıkış denemesi | Anında | Yüksek | L1: veri sızıntısı işareti olabilir |
| Güvenlik duvarı log toplayıcıya log iletemiyor | 2 dakika | Yüksek | Yerel sorumlu: kural 4 nedeniyle toplayıcı İstanbul'dan doğrudan yoklanamaz |

**Kişisel veri ihlali şüphesi:** GDPR, bildirilmesi gereken ihlallerin farkına varıldıktan sonra mümkünse 72 saat içinde denetim makamına bildirilmesini ister. SOC şüpheli olayı gecikmeden Veri Koruma Sorumlusu'na aktarır; bildirim kararını o verir.

## Şubeye özel kurulum ve testler

1. Yerel log toplayıcı, ilk log akışından önce hazır olur.
2. Teknik ekip küçük olduğu için ağ cihazları İstanbul'dan da yönetilebilir, ancak yalnızca VPN ve bastion üzerinden (O1). Sunucu ağlarına merkezden erişim yoktur (kural 4).

**Durum** sütunu testin gerçekten çalıştırılıp çalıştırılmadığını gösterir. **Paket** gerçek Linux paket testidir ([sonuçlar](../lab/sonuclar/PAKET.md)) ve FortiGate üzerinde yapılmamıştır.

| Test | Beklenen sonuç | Durum |
|---|---|---|
| Ana hattı kes | Yedek hat devreye girer, alarm oluşur | Çalıştırılmadı: SD-WAN lab dışında |
| İstanbul VLAN 50'den `10.3.60.20` adresine bağlan | Engellenir: İstanbul'da O7, trafik oradan geçerse Amsterdam'da kural 4 | Paket `G10-07`, `G10-06` |
| CRM'den İstanbul'a bağlan | Engellenir, kural 3 alarmı oluşur | Paket `G10-01`: engellendi. Alarm sınanmadı |
| VLAN 85'ten `10.3.20.1` adresine bağlan | O7 ile engellenir | Paket `G2-09` |
| CRM'den onaylı olmayan bir siteye çık | O7 ile engellenir | Paket `G10-10` |
| Amsterdam logunu Wazuh'a göndermeyi dene | Engellenir, log Hollanda'da kalır | Paket `G10-03`, `G10-04` |
