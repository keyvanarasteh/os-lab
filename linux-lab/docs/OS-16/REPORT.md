# OS-16 — Sunucuya ilk bakış raporu

**Öğrenci:** Gözde Kazma (@gozdekazma)

**Ders:** MYO203 — Açık Kaynak İşletim Sistemleri

**Rezervasyon:** [#113](https://github.com/keyvanarasteh/os-lab/pull/113)

## Yapılan çalışma

`server_firstlook.py`, Linux sunucusuna ilk girişte gereken bilgileri tek
çalıştırmada toplar. `uname`, `lsb_release`, `inxi`, `free`, `df` ve `systemctl`
çıktılarından okunabilir metin ve JSON üretir. Mimari notu, `x86_64` ile `amd64`
gibi farklı adların paket seçimindeki anlamını açıklar. Kod yalnızca Python
standart kütüphanesini kullanır.

Komut bulunamadığında veya systemd çalışmadığında rapor diğer bölümlerle devam
eder; eksik veri açıkça işaretlenir. Her komuta zaman sınırı uygulanır. Araç
paket kurmaz, servis başlatıp durdurmaz ve ağdaki başka sistemlere bağlanmaz.
Otomatik testler hem başarılı hem hatalı komut çıktılarıyla davranışı kontrol eder.

## Git ve PR akışındaki kavramlar

- Fork, ana projenin GitHub hesabındaki kopyasıdır; clone çalışma ortamına indirir.
- `feat/server-firstlook` dalı, bu görevi ana daldan ayrı geliştirir.
- Commit değişikliklerin kayıt noktasıdır; push commit'leri uzak dala gönderir.
- Pull Request, değişikliğin hocanın deposuna alınmasını isteyen inceleme kaydıdır.
- Rezervasyon PR'ı ile çalışan uygulamanın PR'ı farklı amaçlara hizmet eder.
- Aynı dala yeni commit gönderildiğinde açık PR güncellenir; tekrar PR açılmaz.

## Linux labında gözlemlenen sonuçlar

Paylaşılan terminal çıktıları Ubuntu 26.04.1 LTS, `7.0.0-30-generic` kernel
ve `x86_64` mimarisini doğruladı. Metin ve JSON raporları çalıştı. İlk raporda
eksik görünen `inxi` kurulduktan sonra bütün komutlar `ok`, veri toplama durumu
`complete` oldu. Araç 197 servis içinde başarısız olan
`systemd-networkd-wait-online.service` servisini gösterdi.

Test hazırlığında eksik `python3.14-venv` paketi nedeniyle sanal ortam
oluşturulamıyordu; paket kurularak bu aşama düzeltildi.
OS-16'nın kendi testleri aynı Ubuntu labında ayrıca çalıştırıldı ve
**21 passed in 0.02s** sonucu alındı. Genel kontrolde
Android/lab grubunda 195 test geçti, web-ui testinde 1 hata kaldı; Source Lab'da
176 test geçti. Cleanup Lab'ın relocation/safety testlerinde de hatalar kaldı.
OS-16'nın 21 testinin tamamı geçti. Ayrıntılar [VERIFY.md](VERIFY.md) içindedir;
genel repo kontrolünün tamamen geçtiği iddia edilmemektedir.

## Kişisel öğrenme değerlendirmesi

Fork işlemini Keyvan hocanın derste gösterdiği adımlardan öğrenerek os-lab projesinin bir kopyasını kendi GitHub hesabıma aldım. Bu projede ayrı bir dal üzerinde çalışmanın amacını ve hazırlanan aracı Linux ortamında test ederek sonuçlarını kontrol etmeyi öğrendim. Commit ile değişikliklerin kaydedildiğini, push ile GitHub’a gönderildiğini ve Pull Request ile ana projeye eklenmek üzere incelemeye sunulduğunu öğrendim.

## Destek ve kanıt videosu

Kod, testler ve belge hazırlığında ChatGPT desteği kullanılmıştır.
Yukarıdaki gözlemler paylaşılan gerçek terminal kayıtlarına dayanır.

- 2–4 dakikalık kanıt videosu: **henüz eklenmedi**.

Tekrar çalıştırma komutları ve video sırası [VERIFY.md](VERIFY.md) içindedir.
