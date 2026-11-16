# Ankara Akademik Şube

Kampüste 10.000 öğrenci, 400 hoca ve 200 personel bulunur. Şirketin en büyük şubesidir ve toplam trafiğin yaklaşık üçte ikisini üretir.

[Ana sayfaya dön](../README.md)

## Kişi sayıları ve bant genişliği

| Grup | Kişi | Etkin hız | Gereken |
|---|---:|---:|---:|
| Personel | 200 | 2,1 Mbps | 420 Mbps |
| Hoca | 400 | 1,5 Mbps | 600 Mbps |
| Öğrenci | 10.000 | 0,375 Mbps | 3.750 Mbps |
| Yazılım | 10 | 8 Mbps | 80 Mbps |
| Teknik | 30 | 4 Mbps | 120 Mbps |
| Ar-Ge | 20 | 10,5 Mbps | 210 Mbps |
| **Toplam** | **10.660** | | **5.180 Mbps** |

`5.180 × 1,25 = 6.475 Mbps`. Satılan bir üst hız **10 Gbps ana hat**, yedek olarak **5 Gbps** seçildi.

**Kullanım profili:** Trafiğin en büyük kısmı öğrenci Wi-Fi'sinden gelir. Video, güncelleme ve LMS yoğundur. Sınav dönemlerinde LMS'in çalışması internetin hızından daha önemlidir.

**VLAN başına bant genişliği (Mbps):**

| Trafik | Garanti | En yüksek | Yedek hatta |
|---|---:|---:|---:|
| Öğrenci (VLAN 100-107, ortak sınır) | 3.750 | 6.000 | 3.000 |
| LMS ve DMZ (VLAN 70) | 1.000 | 3.000 | 380 |
| Hoca (VLAN 90) | 600 | 1.500 | 600 |
| Personel (VLAN 20) | 420 | 1.000 | 420 |
| Ar-Ge (VLAN 40, proxy ile) | 210 | 500 | 210 |
| Sunucular (VLAN 60, 63, 64) | 200 | 500 | 120 |
| Teknik (VLAN 50) | 120 | 300 | 120 |
| Laboratuvar (VLAN 110) | 100 | 300 | 50 |
| Yazılım (VLAN 30) | 80 | 200 | 80 |
| Yönetim (VLAN 10) | 20 | 50 | 20 |
| Misafir (VLAN 85) | 0 | 50 | 0 |
| **Toplam** | **6.500** | | **5.000** |

- **Öğrenci başına sınır:** Tek bir cihaz en çok 10 Mbps kullanır, böylece birkaç kişi ağı dolduramaz. Bu, güvenlik duvarı kuralı değil, trafik şekillendirmedir.
- **LMS önceliği:** LMS her zaman en yüksek önceliktedir. Kampüsten LMS'e erişim şube içinde kaldığı için internet hattını kullanmaz; yukarıdaki LMS değerleri uzaktan bağlananlar içindir. Kampüs trafiği yine de WAF'tan geçer ([kapasite planı](../waf/README.md)).

## VLAN ve IP planı

| VLAN | Ağ | Alt ağ | Kullanılabilir | Hesap |
|---:|---|---|---:|---|
| 10 | Yönetim | 10.4.10.0/26 | 62 | Ağ cihazları ve erişim noktaları |
| 20 | Personel | 10.4.20.0/22 | 1.022 | 200 × 2 × 1,3 = 520 |
| 30 | Yazılım | 10.4.30.0/27 | 30 | 10 × 2 × 1,3 = 26 |
| 40 | Ar-Ge | 10.4.40.0/26 | 62 | 20 × 2 × 1,3 = 52 |
| 50 | Teknik | 10.4.50.0/25 | 126 | 30 × 2 × 1,3 = 78 |
| 60 | Sunucu | 10.4.60.0/24 | 254 | Altyapı ve uygulama |
| 63 | Veri | 10.4.63.0/26 | 62 | LMS veritabanı |
| 64 | Sınır servisleri | 10.4.64.0/26 | 62 | Proxy ve kamera kayıt |
| 70 | DMZ | 10.4.70.0/26 | 62 | LMS |
| 80 | IoT | 10.4.80.0/24 | 254 | Kamera, yazıcı, kartlı geçiş |
| 85 | Misafir | 10.4.85.0/24 | 254 | Ziyaretçiler |
| 90 | Hoca | 10.4.88.0/21 | 2.046 | 400 × 2 × 1,3 = 1.040 |
| 110 | Laboratuvar | 10.4.110.0/23 | 510 | 300 bilgisayar × 1,3 = 390 |

### Öğrenci ağı

**`10.4.128.0/17` bir VLAN değildir.** Öğrencilere ayrılmış adres rezervi ve kurallarda kullanılan özettir (`ank-ogrenci`). Hiçbir arayüze atanmaz. Gerçek ağlar bu bloğu tam olarak bölen sekiz `/20` VLAN'dır.

Bina dağılımı planlama varsayımıdır. Gerçek bina ve erişim noktası envanteri kurulumdan önce doğrulanır.

| VLAN | Bina | Alt ağ | Ağ geçidi | Ayrılmış | DHCP havuzu | Kullanılabilir |
|---:|---|---|---|---|---|---:|
| 100 | Yurt 1 | 10.4.128.0/20 | `10.4.128.1` | `10.4.128.2`-`10.4.128.30` | `10.4.128.31`-`10.4.143.254` | 4.064 |
| 101 | Yurt 2 | 10.4.144.0/20 | `10.4.144.1` | `10.4.144.2`-`10.4.144.30` | `10.4.144.31`-`10.4.159.254` | 4.064 |
| 102 | Kütüphane | 10.4.160.0/20 | `10.4.160.1` | `10.4.160.2`-`10.4.160.30` | `10.4.160.31`-`10.4.175.254` | 4.064 |
| 103 | Mühendislik | 10.4.176.0/20 | `10.4.176.1` | `10.4.176.2`-`10.4.176.30` | `10.4.176.31`-`10.4.191.254` | 4.064 |
| 104 | Fen-Edebiyat | 10.4.192.0/20 | `10.4.192.1` | `10.4.192.2`-`10.4.192.30` | `10.4.192.31`-`10.4.207.254` | 4.064 |
| 105 | İİBF | 10.4.208.0/20 | `10.4.208.1` | `10.4.208.2`-`10.4.208.30` | `10.4.208.31`-`10.4.223.254` | 4.064 |
| 106 | Yemekhane ve sosyal alan | 10.4.224.0/20 | `10.4.224.1` | `10.4.224.2`-`10.4.224.30` | `10.4.224.31`-`10.4.239.254` | 4.064 |
| 107 | Spor ve açık alan | 10.4.240.0/20 | `10.4.240.1` | `10.4.240.2`-`10.4.240.30` | `10.4.240.31`-`10.4.255.254` | 4.064 |
| | **Toplam** | | | | | **32.512** |

Her `/20` 4.096 adrestir. Ağ ve yayın adresi, ağ geçidi ve ileride kullanım için ayrılan 29 adres çıkınca havuzda 4.064 adres kalır. Erişim noktaları bu ağlarda değil, VLAN 10'dadır.

**Kapasite yeniden hesaplandı:**

| Durum | Cihaz | Sekiz VLAN'ın doluluğu | VLAN başına ortalama |
|---|---:|---:|---:|
| Bugün: 10.000 × 2,5 | 25.000 | %76,9 | 3.125 |
| %85 alarm eşiği | 27.635 | %85,0 | 3.454 |
| Büyüme hedefi: 25.000 × 1,3 | 32.500 | **%99,96** | 4.063 |

**Sonuç:** Bugünkü ihtiyaç rahatça sığar. Büyüme hedefi ise yalnızca kâğıt üzerinde sığar: 12 adres kalır ve bütün binaların eşit dolması gerekir, oysa binalar eşit dolmaz. Bu nedenle `/17` tek başına büyüme hedefi için yeterli **sayılmaz**. Bir VLAN `%85`'e ulaştığında aşağıdaki rezerv açılır:

| Kademe | Eklenen | Toplam havuz | 32.500 cihazda doluluk |
|---|---|---:|---:|
| Başlangıç | 8 × `/20` | 32.512 | %99,96 |
| Kademe 1 | `10.4.112.0/20`, yeni VLAN | 36.576 | %88,9 |
| Kademe 2 | `10.4.96.0/21`, yeni VLAN | 38.592 | %84,2 |

Rezerv bloklar bugün boştur ve başka VLAN ile çakışmaz. Açıldıklarında `ank-ogrenci` nesnesine ve kural 3, 4 ve 5'e eklenir, çünkü `/17` özetinin dışındadır.

**32.500 değeri üst sınırdır:** Bütün öğrencilerin bütün cihazlarının aynı anda bağlı olduğunu varsayar. Gerçek doluluk Zabbix'teki DHCP alarmıyla izlenir ve plan buna göre güncellenir.

**İstemci izolasyonu:** Öğrenci SSID'lerinde istemci izolasyonu açıktır, aynı VLAN'daki iki öğrenci birbirini göremez. Bu kontrol erişim noktasındadır, çünkü aynı VLAN trafiği güvenlik duvarından geçmez. Farklı binalar arasındaki trafik güvenlik duvarından geçer ve kural 4 ile engellenir.

**DHCP relay:** Her öğrenci VLAN arayüzünde relay açıktır ve istekleri `ank-dns` `10.4.60.2` sunucusuna iletir. Sunucuda VLAN başına ayrı kapsam vardır, kapsam relay adresine göre seçilir. Kira süresi 1 saattir, çünkü binalar arasında dolaşan cihaz eski VLAN'daki kirasını süre bitene kadar tutar. Sunucu bu adresleri ve 802.1X kayıtlarını 5651 için Wazuh'a gönderir (O5).

**Bina değişince ne olur?** Cihaz yeni bir IP alır ve açık bağlantılar kopar. Bu yüzden LMS oturumu IP adresine bağlanmamalıdır. Sınav sırasında bina değiştirmek sınavı kesebilir; LMS ekibi bunu doğrular.

**Sunucular:**

| VLAN | Nesne | Adres | Görev |
|---:|---|---|---|
| 60 | `ank-dns` | `10.4.60.2` | DNS, DHCP, NTP |
| 60 | `ank-radius` | `10.4.60.3` | Yerel RADIUS: tünel kopsa da 802.1X çalışır |
| 60 | `ank-obs` | `10.4.60.31` | Öğrenci bilgi sistemi |
| 60 | `ank-dosya` | `10.4.60.40` | Laboratuvar dosya sunucusu |
| 63 | `ank-lms-db` | `10.4.63.30` | LMS veritabanı |
| 64 | `ank-proxy` | `10.4.64.10` | Çıkış proxy'si |
| 64 | `ank-kamera-kayit` | `10.4.64.50` | Kamera kayıt |
| 70 | `ank-waf-vip` | `10.4.70.10` | WAF sanal adresi |
| 70 | `ank-lms-uyg` | `10.4.70.11` | LMS uygulaması |
| 70 | `ank-waf-1`, `ank-waf-2` | `10.4.70.12`, `10.4.70.13` | WAF düğümleri |
| 80 | `ank-yazici` | `10.4.80.20` | Yazıcı |

## En iyi 5 güvenlik duvarı

Ana hat: 10 Gbps. Fiyat tek cihazın lisans ve destek hariç donanım fiyatıdır. Check Point fiyatına 1 yıllık SandBlast aboneliği dahildir, doğrudan karşılaştırılmaz.

| Model | Koruma hızı | Hat yükü | Fiyat (USD, adet) | Karar |
|---|---:|---:|---:|---|
| **FortiGate 900G ×2** | 30 Gbps | %33 | 32.320 | **Seçildi:** en ucuzu değil, ama hattın üç katı kapasite TLS denetimi ve büyüme için pay bırakır, ortak yönetime girer |
| Palo Alto PA-3440 | 12,8-20 Gbps | %50-78 | 64.040 | Yeterli, ancak kaynaklardaki hız farklı ve yaklaşık iki kat pahalı |
| Check Point Force 9300 | 10,5 Gbps | %95 | 42.990 (1 yıl abonelik dahil) | Hattı karşılar, ancak neredeyse hiç pay bırakmaz |
| Cisco Secure Firewall 3110 | 17 Gbps | %59 | 23.740 | Daha ucuz ve hızı yeterli, ancak tahmini oturum sayısında sınıra yaklaşıyor ve ortak yönetim dışında kalıyor |
| Sophos XGS 3300 | 12 Gbps | %83 | 6.700 | Çok daha ucuz, ancak değer ideal koşullarda ölçülmüş, pay düşük ve oturum kapasitesi doğrulanamadı |

**Diğer FortiGate modelleri neden seçilmedi?**

- **400F (9 Gbps):** 10 Gbps hattın altında kalır.
- **1000F (13 Gbps):** Hattı karşılar, ancak 900G'nin koruma hızı çok daha yüksektir.

**Kampüs için kapasite kontrolü:** Bu şubede belirleyici ölçütlerden biri eşzamanlı oturumdur, çünkü çok sayıda cihaz aynı anda bağlıdır.

```text
Tahmini oturum = (25.000 öğrenci cihazı × 50 + 660 çalışan × 2 cihaz × 100) × 1,3 = 1.796.600
TLS denetimi   = (420 + 600 + 80 + 120) × 1,25 = 1.525 Mbps
```

| Model | TLS denetimi hızı | En yüksek oturum | Oturum yükü |
|---|---:|---:|---:|
| **FortiGate 900G** | 16,7 Gbps | 28 milyon | %6 |
| Palo Alto PA-3440 | Bulunamadı | 3 milyon | %60 |
| Check Point Force 9300 | Bulunamadı | 2,75 milyon (temel sürüm) | %65 |
| Cisco Secure Firewall 3110 | 4,8 Gbps | 2 milyon | %90 |
| Sophos XGS 3300 | 3,7 Gbps | Bulunamadı | Hesaplanamadı |

Üreticiler bu değerleri farklı testlerle ölçtüğü için tablo birebir karşılaştırma değil, yeterlilik kontrolüdür. Bulunamayan değerler üretici teklifinden doğrulanmalıdır.

## Kural seti

Sıra: [O1-O6](../README.md#6-ortak-kurallar) → aşağıdaki kurallar → O7. Adların karşılığı [NESNELER.md](../NESNELER.md) dosyasındadır.

| No | Kaynak | Hedef | Servis | İşlem | Neden? |
|---:|---|---|---|---|---|
| 1 | `internet` | `ank-waf-vip` | tcp/443 | Hız sınırı, IPS | LMS, mobil uygulama ve API yalnızca WAF üzerinden yayınlanır |
| 2 | `ank-lms-uyg` | `ank-lms-db` | tcp/5432 | İzin, log | LMS yalnızca kendi veritabanına ulaşır |
| 3 | `ank-lms-istemcileri` | `ank-waf-vip` | tcp/443 | İzin, en yüksek öncelik | Sınavda öğrenci ve hoca LMS'e ulaşabilmeli |
| 4 | `ank-ogrenci-ve-misafir` | `ozel-10-8` | tümü | Red, log | Öğrenci ve misafir iç ağa geçemez; kural 3 ve O4 bundan önce gelir |
| 5 | `ank-ogrenci` | `internet` | tcp/80, tcp/443 | İzin, IPS, cihaz başına 10 Mbps, `up-ogrenci` | Öğrencinin web erişimi; gizlilik ve kapasite nedeniyle TLS denetimi yok |
| 6 | `ank-v90-hoca` | `ank-obs` | tcp/443 | İzin, log | Hocanın not girişi |
| 7 | `ank-v20-personel` | `ank-obs` | tcp/443 | İzin, log | Personelin öğrenci işlemleri |
| 8 | `ank-v20-personel` | `ist-erp` | tcp/443 | İzin | Merkezî iş uygulaması |
| 9 | `ank-v110-lab` | `ank-dosya` | tcp/445 | İzin | Ders dosyalarına erişim |
| 10 | `ank-v110-lab` | `internet` | tcp/80, tcp/443 | İzin, IPS, VLAN sınırı, `up-kurumsal` | Lab internete çıkar, iç sistemlere çıkamaz |
| 11 | `ank-v40-arge` | `ank-proxy` | tcp/3128 | İzin | Ar-Ge internete yalnızca proxy ile çıkar |
| 12 | `ank-proxy` | `internet` | tcp/80, tcp/443 | İzin, web filtresi | Çıkış tek noktadan denetlenir |
| 13 | `ank-v40-arge` | `internet` | tümü | Reject, alarm | Proxy dışı çıkış veri sızıntısı işareti olabilir; uygulama hemen hata alır |
| 14 | `ank-v30-yazilim` | `ist-git` | tcp/22, tcp/443 | İzin | Tek kod deposu kullanılır |
| 15 | `ank-v50-teknik` | `ank-yonetilen-sunucular` | tcp/22, tcp/443, tcp/3389 | İzin, log | Sunucu yönetimi yalnızca teknik ekipte |
| 16 | `ank-kurumsal` | `internet` | tcp/80, tcp/443 | İzin, IPS, TLS denetimi, `up-kurumsal` | Kurum cihazlarının internet erişimi |
| 17 | `ank-v80-iot` | `ank-kamera-kayit` | tcp/554 | İzin | Kameraların internete ihtiyacı yoktur |
| 18 | `ank-v85-misafir` | `internet` | tcp/53, udp/53, tcp/80, tcp/443 | İzin, 50 Mbps VLAN sınırı, `up-misafir` | Misafir yalnızca internete çıkar |
| 19 | `ank-yazici-istemcileri` | `ank-yazici` | tcp/631, tcp/9100 | İzin | Yazıcılar IoT ağında olduğu için baskı ayrı izin ister |
| 20 | `ank-v70-dmz` | `ank-proxy` | tcp/3128 | İzin, log | DMZ sunucusu güncellemesini internete doğrudan çıkmadan alır |
| 21 | `ank-izleme-kaynaklari` | `zabbix` | tcp/10051 | İzin | Sunucu ve LMS durumu merkezden izlenir |
| 22 | `wan-istanbul` | `wan-ankara` | udp/500, udp/4500 | İzin | IPsec tüneli yalnızca merkezin adresinden kurulur |
| 23 | `vpn-hoca` | `ank-obs` | tcp/443 | İzin, log | Hoca evden not girebilir |
| 24 | `ank-guncelleme-kaynaklari` | `ank-proxy` | tcp/3128 | İzin | İç sunucular güncellemeyi proxy'den alır |
| 25 | `ank-v10-yonetim` | `ank-radius` | udp/1812, udp/1813 | İzin | Erişim noktaları 802.1X kimliğini yerelde doğrular |
| 26 | `ank-radius` | `ist-ad` | tcp/636 | İzin | RADIUS kullanıcıları merkezî dizinden doğrular |
| 27 | `ank-v50-teknik` | `ank-v63-veri` | tcp/22 | İzin, log | Veritabanı yalnızca SSH ile yönetilir |

**Sıra neden önemli?**

- **Kural 1'in kaynağı `internet` olmalıdır.** `any` olursa misafir LMS'e ulaşır ve kural 3 ölü kalır. Testler bu hatayı önceki tasarımda buldu.
- **Kural 3, kural 4'ten önce gelir.** Yoksa öğrenciler LMS'e ulaşamaz.
- **Kural 4, kural 5'ten önce gelir.** Kural 5'in hedefi internettir, ama iç ağ reddi önce uygulanır.

**Torrent nasıl engelleniyor?** İki ayrı katmanda, ve ikisi de tam çözüm değildir:

- **L3/L4 (kural 5):** Öğrenci internete yalnızca TCP 80 ve 443 ile çıkar, gerisi O7'ye düşer. Klasik torrent trafiği ve QUIC bu yüzden geçemez. Bu, kuralın yan etkisidir, torrent engeli değildir.
- **Uygulama denetimi (`up-ogrenci`):** P2P kategorisini cihaz üzerindeki imzalarla engeller ([ngfw-profilleri.json](../ngfw-profilleri.json)). Öğrencide TLS derin denetimi kapalıdır, bu yüzden 443 üzerinden şifreli P2P tanınmayabilir. **Bu risk kapatılmış sayılmaz.** Etkisi cihaz başına 10 Mbps sınırı ve oturum alarmıyla sınırlanır. Bu davranış FortiGate üzerinde sınanmadı.

## İzleme

**Yerel sorumlu:** Kampüs BT nöbetçisi. Sınav takvimi SOC'a en az bir hafta önceden bildirilir.

| İzlenen | Eşik | Seviye | İlk müdahale |
|---|---|---|---|
| Ana hat doluluğu | 5 dakika boyunca 8,5 Gbps üzeri (%85) | Orta | L1 |
| Yedek hat doluluğu | 5 dakika boyunca 4,25 Gbps üzeri (%85) | Orta | L1 |
| Öğrenci trafiği | 5 dakika boyunca 5,4 Gbps üzeri (6 Gbps sınırının %90'ı) | Orta | L1 |
| LMS yanıt süresi | 5 dakika boyunca 2 saniye üzeri | Yüksek, sınav saatinde Kritik | L2 ve kampüs BT nöbetçisi |
| WAF veya LMS sunucusunda kritik saldırı imzası | Anında | Yüksek | L1, gerekirse L2 |
| DMZ'den iç ağa izinsiz bağlantı denemesi | Anında | Kritik | Nöbetçi L2 aranır: sunucu ele geçirilmiş olabilir, ağdan ayrılır |
| Eşzamanlı oturum | 1,8 milyon üzeri | Orta | L1: tahmin aşıldı, plan güncellenir |
| Bir öğrenci VLAN'ının DHCP havuzu | %85 dolu (3.454 adres) | Orta | Kampüs BT nöbetçisi: rezerv kademesi değerlendirilir |
| Kural 4: aynı cihazdan iç ağa deneme | 5 dakikada 100 red | Yüksek | L1: cihaz taraması veya zararlı yazılım olabilir |
| Kural 13: Ar-Ge proxy dışı çıkış denemesi | Anında | Yüksek | L1 |
| Tek öğrenci cihazının oturum sayısı | 10 dakika boyunca 500 üzeri (başlangıç varsayımı) | Orta | L1: şifreli P2P veya zararlı yazılım olabilir |

## Şubeye özel kurulum ve testler

1. Geçiş sınav dönemi dışında ve gece yapılır.
2. Öğrenci Wi-Fi'si en sona bırakılır. Önce personel ve hoca ağları test edilir.
3. Öğrenci girişi kimlik doğrulamalı (802.1X) yapılır, böylece olaylar bir kullanıcıya bağlanabilir. Erişim noktaları yerel RADIUS'a gider, RADIUS kullanıcıyı İstanbul'daki dizinden doğrular.

**Durum** sütunu testin gerçekten çalıştırılıp çalıştırılmadığını gösterir. **Paket** gerçek Linux paket testidir ([sonuçlar](../lab/sonuclar/PAKET.md)) ve FortiGate üzerinde yapılmamıştır.

| Test | Beklenen sonuç | Durum |
|---|---|---|
| Ana hattı kes | Yedek hat devreye girer, öğrenci sınırı 3 Gbps'e iner | Çalıştırılmadı: SD-WAN ve QoS lab dışında |
| Öğrenci VLAN'ından LMS'e bağlan | WAF üzerinden çalışır | Paket `G1-01`-`G1-08`, sekiz VLAN'dan |
| Öğrenci VLAN'ından internete HTTP ve HTTPS | Çalışır | Paket `G1-09`-`G1-12` |
| İnternetten `10.4.70.11` adresine bağlan | O7 ile engellenir, yalnızca WAF yayındadır | Paket `G6-04` |
| LMS API'sine sınırı aşan sayıda istek gönder | Ters proxy sınırlar, log oluşur | Çalıştırılmadı: [plana bakın](../waf/README.md) |
| Öğrenci VLAN'ından `10.4.60.31` adresine bağlan | Kural 4 ile engellenir | Paket `G1-18` |
| Öğrenciden ERP, yönetim ve diğer şubelere bağlan | Engellenir | Paket `G1-13`-`G1-17` |
| Başka binadaki öğrenciye bağlan | Kural 4 ile engellenir | Paket `G1-22` |
| Öğrenciden web dışı portla internete çık | O7 ile engellenir | Paket `G1-23`-`G1-27` |
| Öğrenci cihazından torrent başlat | `up-ogrenci` engeller, log oluşur | **Çalıştırılmadı:** uygulama tanıma FortiGate gerektirir |
| Hoca VLAN'ından yazıcıya baskı gönder | Çalışır (kural 19) | Paket `G9-23` |
| Öğrenci VLAN'ından yazıcıya bağlan | Kural 4 ile engellenir | Paket `G1-21` |
| Misafirden LMS'e iç adresle bağlan | Kural 4 ile engellenir | Paket `G2-13` |
| Yük testi: LMS'e çoklu sınav oturumu aç | Öğrenci interneti yoğunken LMS yanıt vermeye devam eder | **Çalıştırılmadı:** [kabul ölçütleri](../waf/README.md#kabul-ölçütleri) |
