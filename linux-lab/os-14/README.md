
# OS-14 - Node.js ve Python Kurulum Araci

## Amac
Ubuntu/Debian sistemlerde Node.js ve Python
araclarinin kurulumunu ve surum kontrolunu
kolaylastirmak.

## Ozellikler
- Node.js surumunu kontrol eder.
- npm surumunu kontrol eder.
- Python 3 surumunu kontrol eder.
- python komutunun durumunu kontrol eder.
- Eksik paketlerin kurulumunu destekler.
- NodeSource uzerinden Node.js kurulumu yapar.

## Kullanim

Surumleri kontrol etmek:

```bash
bash install.sh --check
```

Kurulum yapmak:

```bash
sudo bash install.sh --install
```

## Gereksinimler
- Ubuntu veya Debian
- apt paket yoneticisi
- Internet baglantisi
- Kurulum icin yonetici yetkisi

## Guvenlik
Kurulum sistem paketlerini degistirir.
Once test ortaminda denenmelidir.



## Test Sonuçları

Test ortamı: Ubuntu (WSL)

Çalıştırılan komut:
`bash install.sh --check`

Kontrol sonuçları:
- Node.js: v22.22.1 - Başarılı
- npm: 9.2.0 - Başarılı
- Python 3: 3.14.4 - Başarılı
- python komutu: Python 3.14.4 - Başarılı

Sonuç: Sistem kontrolü başarıyla tamamlandı.
Node.js, npm ve Python sürümleri doğrulandı.

Not: Kurulum modu henüz test edilmedi.


