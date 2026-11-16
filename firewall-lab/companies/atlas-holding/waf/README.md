# WAF kapasite doğrulama planı

Bu plan, Ankara'daki WAF'ın sınav yoğunluğunu taşıyıp taşımadığını kurulumdan önce ölçmek içindir.

| Test | Durum | Sonuç |
|---|---|---|
| Duman testi: tek makine, izole ağ | **Çalıştırıldı** | [sonuclar/DUMAN.md](sonuclar/DUMAN.md). Saldırı örnekleri durdu. Kapasite kanıtı değildir |
| Kabul testi: hedef sunucu, 3 Gbps | **Çalıştırılmadı** | Hedef donanım ve yük üreteçleri yok |
| Geçiş testi: iki düğüm, VRRP | **Çalıştırılmadı** | İki düğümlü kurulum yok |

**WAF kapasitesi bugün doğrulanmış değildir.** Aşağıdaki kabul testi geçmeden ModSecurity kararı kesin sayılmaz.

## Varsayımlar

Bu değerlerin hiçbiri ölçüm değildir. Gerçek LMS verisi geldiğinde güncellenir.

| Varsayım | Değer | Dayanağı | Ne zaman güncellenir? |
|---|---:|---|---|
| Tepe bant | 3 Gbps | VLAN 70 için planlanan en yüksek değer, yani bir QoS sınırı. Gerçek LMS trafiğinden türetilmedi | İlk sınav döneminin Zabbix verisiyle |
| Ortalama yanıt | 50 KB | Sayfa, görsel ve API yanıtlarının karışımı için tahmin | WAF erişim loglarıyla |
| İstek hızı | 7.500 istek/sn | 3 Gbps = 375 MB/sn, 375 MB ÷ 50 KB | Yukarıdaki iki değer değişince |
| Eşzamanlı kullanıcı | 10.000 | Bütün öğrenciler aynı anda sınavda. Üst sınırdır, olası değil | Sınav takviminden |
| Kullanıcı başına bağlantı | 2 | Tarayıcı ve mobil uygulama | WAF ölçümüyle |
| Sınav başlangıcı | 10.000 kullanıcı 2 dakikada | Öğrenciler sınav saatinde birlikte girer | Sınav takviminden |

**Bilinen açık:** Kampüsten LMS'e giden trafik de WAF'tan geçer, ama internet hattı tablosunda yoktur. Bu yüzden WAF'ın toplam yükü 3 Gbps'i aşabilir. İlk ölçümde iç ve dış trafik ayrı raporlanır.

## İki WAF sunucusu ne sağlar, ne sağlamaz?

İki sunucu VRRP ile **aktif-pasif** çalışır, sanal adres `10.4.70.10` aynı anda yalnızca bir düğümdedir.

- **Yük dengeleme yoktur.** Kapasite tek düğümün kapasitesidir, bu yüzden bütün ölçütler tek düğüm için geçerlidir.
- **Kesintisiz geçiş iddia edilmez.** Aktif düğüm düşünce açık TLS oturumları kopar, istemci yeniden bağlanır. Geçiş süresi ölçülmedi.
- **Oturum ve ayar eşitlemesi kendiliğinden olmaz.** Sertifika, kural ve istisna dosyalarının iki düğümde aynı olduğu ayrıca denetlenir.

Aktif-aktif çalışma gerekirse önde bir yük dengeleyici gerekir. Bu tasarımda yoktur.

## Test edilecek yapılandırma

| Konu | Plan | Neden? |
|---|---|---|
| Sunucu | Düğüm başına 16 vCPU (AES-NI), 32 GB RAM, 2 × 10 GbE, işletim sistemi ve loglar için SSD | Başlangıç boyutudur, ölçülmedi. Ters vekil trafiği iki kez taşır: istemci tarafı 3 Gbps, uygulama tarafı 3 Gbps |
| TLS sonlandırma | WAF üzerinde, TLS 1.2 ve 1.3, ECDSA P-256, oturum sürdürme açık, HTTP/2 | WAF içeriği görmek için TLS'i açmak zorundadır. Bu yüzden ölçüm TLS açık yapılır |
| Arka uç | WAF → uygulama `tcp/8080`, aynı VLAN, şifresiz | Yalnızca WAF düğümlerine izinli. Şifreli arka uç istenirse kapasite yeniden ölçülür |
| Kural seti | OWASP CRS güncel 4.x sürümü, paranoia 1, anomali eşiği gelen 5 / giden 4 | Önce izleme, sonra engelleme modu. Eşik veya paranoia değişirse test tekrarlanır |
| Gövde denetimi | İstek gövdesi açık (13 MB sınır), yanıt gövdesi kapalı | Yanıt gövdesini denetlemek işlemciyi çok artırır |
| İstisnalar | LMS uç noktaları için belgeli ve dar kural istisnaları | Yanlış pozitif sınavı durdurabilir |
| Yönetim | Düğümler Wazuh'a log, Zabbix'e izleme verisi gönderir | `ank-waf-dugumleri` nesnesi, kural O5 ve kural 21 |

## Test yükü

Yük en az iki ayrı makineden üretilir. Üreteçler WAF ile aynı sunucuda veya aynı işlemcide çalışmaz.

| Senaryo | Karışım | Süre | Amacı |
|---|---|---:|---|
| S1 Isınma | Hedefin %10, %25, %50, %75'i | Adım başına 5 dk | İlk bozulma noktasını bulur |
| S2 Sürekli tepe | %80 sayfa ve dosya GET, %20 sınav POST, 50 KB ortalama yanıt | 30 dk | Asıl kabul ölçütü |
| S3 Sınav başlangıcı | 10.000 kullanıcı 2 dakikada oturum açar | 2 dk | TLS el sıkışma fırtınası |
| S4 Saldırı altında | S2 + OWASP örnek saldırıları | 10 dk | Engelleme meşru trafiği yavaşlatıyor mu? |
| S5 Geçiş | S2 sürerken aktif düğüm kapatılır | 10 dk | Geçiş süresi ve kalan düğümün dayanıklılığı |

Her senaryo önce WAF'a doğrudan, sonra FortiGate üzerinden çalıştırılır. Böylece sınırlayan katman görülür.

## Kabul ölçütleri

Bütün değerler **tek düğüm** içindir. Gerçek sunucuda ölçülmeleri gerekir.

| Ölçüt | Eşik | Gerekçe | Sonuç |
|---|---|---|---|
| Sürekli bant | ≥ 3 Gbps, 30 dk | Planlama hedefi | Çalıştırılmadı |
| İstek hızı | ≥ 7.500 istek/sn | 3 Gbps ÷ 50 KB | Çalıştırılmadı |
| Eşzamanlı kullanıcı | ≥ 10.000 kullanıcı, ≥ 20.000 açık bağlantı | Üst sınır: bütün öğrenciler, kullanıcı başına 2 bağlantı | Çalıştırılmadı |
| Yeni TLS el sıkışma | ≥ 500 /sn | 10.000 × 2 ÷ 120 sn = 167 /sn, üzerine 3 kat pay | Çalıştırılmadı |
| Gecikme, uçtan uca | p95 ≤ 500 ms, p99 ≤ 2 sn | LMS yanıt süresi alarmı 2 saniyedir, normal yük alarmı tetiklememelidir | Çalıştırılmadı |
| WAF'ın eklediği gecikme | p95 ≤ 50 ms | Kullanıcının fark edeceği sınırın altında kalsın. WAF kapalı ölçümle fark alınır | Çalıştırılmadı |
| Hata oranı | 5xx ve zaman aşımı ≤ %0,1 | 10.000 kullanıcıda her istekte 10 kişiden fazlası etkilenmesin | Çalıştırılmadı |
| Yanlış pozitif | Sınav uç noktalarında 0, genelde ≤ %0,01 | Yanlış engelleme öğrencinin sınavını keser | Çalıştırılmadı |
| İşlemci | Ortalama ≤ %70, tepe ≤ %85 | Şubedeki %80 alarm eşiğinin altında kalsın ve ani yüke pay bıraksın | Çalıştırılmadı |
| Bellek | ≤ %80, takas kullanılmaz | Takas gecikmeyi öngörülemez hâle getirir | Çalıştırılmadı |
| Saldırı örnekleri | Seçilen OWASP setinin tamamı engellenir | Yük altında da koruma sürmelidir | Çalıştırılmadı |
| Geçiş | Sanal adres ≤ 5 sn içinde taşınır, kalan düğüm yukarıdaki ölçütleri sağlar | Hedef değerdir, ölçülmedi. Kullanıcı yeniden bağlanır | Çalıştırılmadı |

**Test geçmezse:** Önce kural istisnaları ve TLS ayarı gözden geçirilir, sonra düğüm büyütülür veya önüne yük dengeleyici konur. Hâlâ geçmiyorsa ticari WAF veya Cloudflare yeniden değerlendirilir. Bu kararın KVKK sonucu da yeniden yazılır.

## Duman testinin söyledikleri

Duman testi tek makinede çalıştı, bu yüzden aşağıdaki değerler **kabul sonucu değildir**. Yalnızca boyutlandırmaya işaret eder.

- **ModSecurity pahalıdır.** Aynı dört çekirdekte WAF açıkken 50 KB yanıtla saniyede yaklaşık 3.800, kapalıyken yaklaşık 19.900 istek işlendi. Küçük yanıtta fark daha büyüktür: yaklaşık 4.700 ve 59.400. İki koşuda da işlemci %100'dü.
- **İki sunucu tek başına yetmeyebilir.** Bu oran hedef sunucuda da geçerli olursa, 7.500 istek/sn ve %70 işlemci sınırı için tek düğümde yaklaşık 11 çekirdek gerekir. Aktif-pasif çalışmada ikinci sunucu bu kapasiteyi artırmaz. Başlangıç boyutu olarak 16 vCPU seçilmesinin nedeni budur. Testteki çekirdekler sanal ve paylaşımlıdır, gerçek oran farklı olabilir.
- **Kural seti ve sürüm farklıdır.** Duman testi Ubuntu paketindeki CRS 3.3.5 ile çalıştı. Kabul testi kurulacak sürümle yapılmalıdır.

## Çalıştırma

**Duman testi** Ubuntu 24.04 üzerinde çalışır. Paketler sisteme kurulmaz, geçici klasöre açılır. Ağ izole isim alanlarındadır.

```bash
sudo bash waf/paketleri-indir.sh /tmp/waf-paket
sudo bash waf/duman-testi.sh /tmp/waf-paket/kok
```

**Kabul testi** için örnek komutlar. `<waf>` hedef WAF adresidir, üretim ağında çalıştırılmaz. Önce izole test ağında, sınav dönemi dışında çalıştırılır.

```bash
# S2: sürekli tepe. Her üreteçte çalıştırılır, üreteç sayısına göre bağlantı bölünür.
wrk -t16 -c10000 -d30m --latency https://<waf>/ornek-50kb

# S3: her istekte yeni TLS, el sıkışma kapasitesi
wrk -t16 -c2000 -d2m --latency -H "Connection: close" https://<waf>/ornek-1kb

# S4 sırasında örnek saldırı: 403 beklenir
curl -sk -o /dev/null -w '%{http_code}\n' -G --data-urlencode "id=1' OR '1'='1" https://<waf>/ders

# S5: test bitmeden aktif düğümde
systemctl stop keepalived
```

Ölçüm sırasında WAF düğümünde `mpstat 5`, `free -m` ve nginx hata logu izlenir. POST karışımı için `wrk` yerine `k6` senaryosu yazılır. Sonuçlar bu dosyadaki **Sonuç** sütununa, ortam bilgisiyle birlikte kaydedilir.
