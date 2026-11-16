# WAF duman testi sonuçları

Bu dosyayı `waf/duman-testi.sh` üretir, elle düzenlenmez.

> **Bu bir kabul testi değildir.** İstemci, WAF ve uygulama tek makinede aynı işlemciyi paylaşır, trafik sanal arayüzlerden geçer. Sonuçlar 3 Gbps hedefi veya hedef sunucu hakkında bir şey söylemez. Kabul testi [waf/README.md](../README.md) dosyasındadır ve **çalıştırılmadı**.

| Ortam | Değer |
|---|---|
| Tarih | 2026-11-06 21:08 +03 |
| Ağ | Linux ağ isim alanları, gerçek ağa bağlantı yok |
| İşlemci | AMD Ryzen 5 5600 6-Core Processor, WAF için 4 çekirdek ayrıldı |
| Çekirdek | 6.6.87.2-microsoft-standard-WSL2 |
| Yazılım | nginx/1.24.0 (Ubuntu), ModSecurity 3 + OWASP CRS (Ubuntu paketi), wrk |
| Yük | 200 bağlantı, her koşu 20 sn, TLS |

## İşlev: 10 / 10

Gerçek ModSecurity ve CRS çalıştı. Örnek saldırı seti küçüktür, WAF'ın bütün saldırıları durdurduğunu göstermez. Beklenen kod meşru istekte 200, saldırıda 403'tür.

| İstek | Beklenen | Gerçek | Sonuç |
|---|---|---|---|
| Meşru: ana sayfa | 200 | 200 | Geçti |
| Meşru: parametreli sayfa | 200 | 200 | Geçti |
| Meşru: sınav cevabı POST | 200 | 200 | Geçti |
| Meşru: Türkçe metin POST | 200 | 200 | Geçti |
| SQL enjeksiyonu | 403 | 403 | Geçti |
| SQL enjeksiyonu: UNION | 403 | 403 | Geçti |
| XSS | 403 | 403 | Geçti |
| Dizin geçişi | 403 | 403 | Geçti |
| Komut enjeksiyonu | 403 | 403 | Geçti |
| POST gövdesinde SQL enjeksiyonu | 403 | 403 | Geçti |

## Yük

İşlemci, WAF için ayrılan dört çekirdeğin ortalama kullanımıdır. Değerler yalnızca WAF açık ve kapalı arasındaki farkı görmek içindir.

| Koşu | İstek/sn | Veri/sn | p50 | p99 | 2xx/3xx dışı | Soket hatası | İşlemci | Bellek |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| WAF açık, 1 KB yanıt | 4689.47 | 5.69MB | 41.84ms | 61.97ms | 0 | yok | %101 | 181 MB |
| WAF açık, 50 KB yanıt | 3814.66 | 187.18MB | 52.62ms | 73.04ms | 0 | yok | %100 | 181 MB |
| WAF açık, parametreli 1 KB | 3258.90 | 3.96MB | 60.17ms | 84.83ms | 0 | yok | %100 | 182 MB |
| WAF açık, her istekte yeni TLS | 2533.59 | 3.06MB | 4.28ms | 9.63ms | 0 | yok | %99 | 182 MB |
| WAF kapalı, 1 KB yanıt | 59444.00 | 72.17MB | 3.30ms | 8.05ms | 0 | yok | %99 | 165 MB |
| WAF kapalı, 50 KB yanıt | 19870.09 | 0.95GB | 9.80ms | 17.75ms | 0 | yok | %100 | 166 MB |
| WAF kapalı, parametreli 1 KB | 58562.16 | 71.10MB | 3.15ms | 9.25ms | 0 | yok | %99 | 166 MB |
| WAF kapalı, her istekte yeni TLS | 6853.89 | 8.29MB | 3.31ms | 10.18ms | 0 | yok | %98 | 167 MB |

## Sınanmayanlar

- VRRP ile sanal adres geçişi ve iki düğümlü çalışma
- Hedef sunucu, gerçek ağ kartı ve 3 Gbps yük
- Gerçek LMS trafiği, sınav uç noktaları ve yanlış pozitif oranı
- WAF ile uygulama arasında TLS
- FortiGate üzerinden geçiş ve IPS
