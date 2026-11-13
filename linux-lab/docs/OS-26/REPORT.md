# OS-26 — Dosya izinleri ve sahiplik denetleyicisi

**Öğrenci:** Mustafa Mert Köksal (@mertksll)

**Ders:** MYO203 — Açık Kaynak İşletim Sistemleri

**Rezervasyon:** [#112](https://github.com/keyvanarasteh/os-lab/pull/112)

**Uygulama PR'ı:** [#191](https://github.com/keyvanarasteh/os-lab/pull/191)

## Yapılan çalışma

`permission_audit.py`, seçilen Linux lab dizinindeki dosya ve dizinlerin Unix
izinlerini, UID ve GID bilgilerini denetler. Herkese yazılabilir yolları, seçilen
izin sınırını aşan bitleri ve beklenen sahiplikten sapmaları metin veya JSON
olarak raporlar. Önerilen `chmod` ve `chown` komutlarını gösterir; çalıştırmaz.

Denetleyici dosya içeriklerini okumaz, izinleri değiştirmez ve sembolik bağlantı
hedeflerini takip etmez. Erişim hataları ve tarama sınırı raporu eksik olarak
işaretler. Testler gerçek geçici dosyalarda izinleri, JSON çıktısını, çıkış
kodlarını, bağlantıları ve dosyaların değişmeden kaldığını kontrol eder.

## Ubuntu lab gözlemleri

Mert hesabında OS-26'nın 41 testi geçti. Beş girdili örnek labda üç izin
bulgusu raporlandı; izinler elle düzeltildikten sonra bulgu sayısı sıfıra indi.
Beklenen UID farklı seçilince beş sahiplik bulgusu görüldü; normal politika ile
JSON raporu tam tarama ve boş bulgu/hata listeleri verdi.

Genel test paketi de çalıştırıldı. Diğer bileşenlerde kalan hatalar ve atlanan
kontroller, OS-26 sonuçlarıyla birlikte [VERIFY.md](VERIFY.md) içinde kaydedildi.

## Git ve PR akışı

Fork: `mertksll/os-lab`. Görev rezervasyonu ayrı PR olarak kabul edildi.
Uygulama `feat/permission-auditor` dalında hazırlandı. Commit değişiklikleri
kaydeder, push uzak dala aktarır; uygulama PR'ı incelemeye sunar. Aynı dala yeni
commit gönderilmesi mevcut PR'ı günceller.

## Kişisel değerlendirme ve teslim

Bu belge teknik çalışma taslağıdır. Linux lab gözlemleri eklendi; Git/PR
sürecinde öğrenilenleri anlatan kişisel değerlendirme ve 2–4 dakikalık kanıt
videosu henüz eklenmedi. Terminal çıktıları kanıt videosunun yerine geçmez.

Kod, testler ve belge taslağı ChatGPT desteğiyle hazırlanmıştır. Çalıştırma
komutları, beklenen çıktılar ve doğrulama sonuçları [VERIFY.md](VERIFY.md) içindedir.
