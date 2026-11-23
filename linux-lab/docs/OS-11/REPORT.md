# OS-11 — Guided Shell-Basics Practice & Auto-Grader

- Öğrenci: Feyza Özoğlu (`feyzaozoglu`)
- Ders: MYO203 Açık Kaynak İşletim Sistemleri
- Rezervasyon: https://github.com/keyvanarasteh/os-lab/pull/264 (birleştirildi)

## Yapılan çalışma

`linux-lab/exercises/shell_basics_check.py`, seçilen lab klasöründeki örnek
`ali`, `eda`, `aleyna` alıştırmasını denetler. Her öğrenci için üç alt klasör
ve `puan.txt` dosyası bekler; her yola PASS/FAIL ve gerektiğinde ipucu verir.
Örnek profil ve kapsam sınırları VERIFY.md'de açıklanmıştır. Resmi öğrenci
notunu hesaplamaz; dosya içeriği yerine konum ve tür denetlenir.

Araç salt okunurdur, kullanıcı komutlarını çalıştırmaz, sudo veya ağ istemez.
Metin, JSON, beklenen yolları gösterme ve etkileşimli kök seçme modları vardır.
Çıkış kodları: 0 tam yapı, 1 eksik/uyuşmayan yapı, 2 kullanım/kök hatası.

## Doğrulama

Öğrencinin geliştirme ortamında 23 otomatik test geçti. 24.11'de eğitmen
yaması (okunamayan `puan.txt`, rapor satırı sahteciliği, engel türüne göre ipucu,
sembolik bağlı kök, boşluklu kök yolu) 5 test ekledi; toplam 28 test. Geçici
klasörde doğru yapı, eksik dosya ve JSON çıktısı ayrıca denendi. Ayrıntılar VERIFY.md'dedir.
Sonuç, kontrol anındaki bir görüntüdür; denetim sırasında değişen klasörler için
kök değişimi algılanır, alt yolların eşzamanlı değişimi garanti edilmez.
Öğrencinin Ubuntu çalıştırması VERIFY.md'de öğrenci beyanı olarak kayıtlıdır
(15 Kasım 2026; eğitmen yeniden çalıştırmadı). 2–4 dakikalık kanıt videosu
bağlantısı henüz eklenmedi; teslim tamamlanmış olarak sunulmamaktadır.

## Kişisel değerlendirme — lab çalışmasından sonra tamamlanacak

Feyza kendi çalıştırmasından sonra üç kısa cümleyle öğrendiği Linux komutlarını,
fork → dal → commit → push → PR deneyimini ve karşılaştığı bir durumu yazacaktır.
Henüz yapılmamış çalışmaları kişisel deneyim olarak belirtmedik.

## Yapay zekâ desteği

Kod, testler ve belge taslağı ChatGPT desteğiyle hazırlandı. Öğrenci aracı kendi
labında çalıştırmalı, çıktıyı açıklayabilmeli ve kişisel değerlendirmeyi kendi
gözlemleriyle tamamlamalıdır.
