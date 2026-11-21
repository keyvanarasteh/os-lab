
# OS-28 - File Search & Text-Grep Teaching Wrapper Raporu

## Uygulama Özeti
Kullanıcıların belirlediği dizin ve dosya kalıplarında güvenli bir şekilde dosya araması yapmasını ve bu sonuçlar üzerinde metin (`grep`) taraması gerçekleştirerek eğitsel çıktılar üretmesini sağlayan Python tabanlı bir wrapper (`os-28-search-grep-wrapper.py`) geliştirilmiştir.

## Yapılan Güvenlik ve Mantık İyileştirmeleri
* Komut enjeksiyonu (command injection) riskini önlemek için güvenli parametre işleme yöntemleri uygulandı.
* Boşluk içeren dosya yolları ve adları için `-print0` ve `-0` parametreleri eklendi.
* Tire (`-`) ile başlayan dizin veya arama terimlerinin parametre olarak algılanmasını önlemek için normalizasyon ve ayraçlar uygulandı.
