# OS-28 Doğrulama (VERIFY)

## Kod Uyumu Notu
- Betik (`linux-lab/scripts/os-28-search-grep-wrapper.py`) komutları `f-string` ile birleştirmek yerine argüman listeleri ve `subprocess.run` (`shell=False`) ile çalıştırır; komutlar ekranda `shlex.quote` ile gösterilir ve `find` komutu `-print0` ile çalışır (çıktı NUL karakterine göre ayrılır).

## Test Hazırlığı
```bash
mkdir -p "/tmp/os28-test/my dir"
printf 'def a():\n    pass\n' > "/tmp/os28-test/my dir/a b.py"
printf "def z(): pass\nit's here\n-x test(\n" > /tmp/os28-test/z.py
```

## Test Komutları ve Çıktıları

### 1. Sadece komut ve açıklama gösterimi (`--execute` olmadan)
```bash
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /tmp/os28-test '*.py' 'def'
```
Beklenen: `find` ve `grep` komutları argüman listesi ve `shlex.quote` görünümüyle açıklanır, komut çalıştırılmaz.

Çıktı:
```text
(======================================================================
 OS-28: File Search & Text-Grep Teaching Wrapper
======================================================================

[EĞİTSEL AÇIKLAMA] Girdilerinizden üretilen Linux Komutları:
----------------------------------------------------------------------
1. Dosya Arama Komutu (Find):
   Argüman listesi : ['find', '/tmp/os28-test', '-type', 'f', '-name', '*.py', '-print0']
   Komut görünümü  : find /tmp/os28-test -type f -name '*.py' -print0
   Açıklama:
      * find: Belirtilen dizin altında dosya ve klasör arar.
      * /tmp/os28-test: Aramanın başlatılacağı konum.
      * -type f: Sadece normal dosyaları listeler.
      * -name *.py: Wildcard (*) kullanarak dosya adını filtreler.
      * -print0: Dosya adlarını boşluk yerine NUL karakteriyle ayırır (boşluklu adlar bozulmaz).

2. Metin Tarama Komutu (Grep):
   Argüman listesi : ['grep', '-nHF', '--', 'def'] + bulunan dosyalar
   Komut görünümü  : grep -nHF -- def <bulunan dosyalar>
   Açıklama:
      * grep -n: Eşleşen satırların numarasını gösterir.
      * -H: Her sonuçta dosya adını yazar.
      * -F: Arama metnini düzenli ifade değil, düz metin olarak arar.
      * --: Arama ifadesinin tire (-) ile başlaması durumunda seçenek sanılmasını önler.
      * def: Aranan hedef kelime/metin.
      * <bulunan dosyalar>: 1. komutun bulduğu dosyalar buraya eklenir.
----------------------------------------------------------------------

[İpucu]: Komutları sistem üzerinde gerçekten çalıştırmak için sonuna '--execute' ekleyebilirsiniz.
Örnek: python3 os-28-search-grep-wrapper.py . '*.py' 'def' --execute)
```

### 2. Komutları çalıştırma ve boşluklu klasör/dosya adı (`--execute`)
```bash
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /tmp/os28-test '*.py' 'def' --execute
```
Beklenen: `my dir/a b.py` ve `z.py` bulunur, her ikisinde `def` satırı yazdırılır.

Çıktı:
```text
(======================================================================
 OS-28: File Search & Text-Grep Teaching Wrapper
======================================================================

[EĞİTSEL AÇIKLAMA] Girdilerinizden üretilen Linux Komutları:
----------------------------------------------------------------------
1. Dosya Arama Komutu (Find):
   Argüman listesi : ['find', '/tmp/os28-test', '-type', 'f', '-name', '*.py', '-print0']
   Komut görünümü  : find /tmp/os28-test -type f -name '*.py' -print0
   Açıklama:
      * find: Belirtilen dizin altında dosya ve klasör arar.
      * /tmp/os28-test: Aramanın başlatılacağı konum.
      * -type f: Sadece normal dosyaları listeler.
      * -name *.py: Wildcard (*) kullanarak dosya adını filtreler.
      * -print0: Dosya adlarını boşluk yerine NUL karakteriyle ayırır (boşluklu adlar bozulmaz).

2. Metin Tarama Komutu (Grep):
   Argüman listesi : ['grep', '-nHF', '--', 'def'] + bulunan dosyalar
   Komut görünümü  : grep -nHF -- def <bulunan dosyalar>
   Açıklama:
      * grep -n: Eşleşen satırların numarasını gösterir.
      * -H: Her sonuçta dosya adını yazar.
      * -F: Arama metnini düzenli ifade değil, düz metin olarak arar.
      * --: Arama ifadesinin tire (-) ile başlaması durumunda seçenek sanılmasını önler.
      * def: Aranan hedef kelime/metin.
      * <bulunan dosyalar>: 1. komutun bulduğu dosyalar buraya eklenir.
----------------------------------------------------------------------

[ÇALIŞTIRMA] Komutlar argüman listesiyle (shell kullanmadan) çalıştırılıyor...

Çalışan find listesi : ['find', '/tmp/os28-test', '-type', 'f', '-name', '*.py', '-print0']
Çalışan grep listesi : ['grep', '-nHF', '--', 'def'] + 2 dosya

/tmp/os28-test/z.py:1:def z(): pass
/tmp/os28-test/my dir/a b.py:1:def a():)
```

### 3. Tire (`-`) ile başlayan ve özel karakter içeren arama metni
```bash
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /tmp/os28-test '*.py' '-x test(' --execute
```
Beklenen: `--` ayıracı ve `-F` sayesinde metin seçenek ya da düzenli ifade sanılmaz, `z.py` içindeki `-x test(` satırı bulunur.

Çıktı:
```text
(======================================================================
 OS-28: File Search & Text-Grep Teaching Wrapper
======================================================================

[EĞİTSEL AÇIKLAMA] Girdilerinizden üretilen Linux Komutları:
----------------------------------------------------------------------
1. Dosya Arama Komutu (Find):
   Argüman listesi : ['find', '/tmp/os28-test', '-type', 'f', '-name', '*.py', '-print0']
   Komut görünümü  : find /tmp/os28-test -type f -name '*.py' -print0
   Açıklama:
      * find: Belirtilen dizin altında dosya ve klasör arar.
      * /tmp/os28-test: Aramanın başlatılacağı konum.
      * -type f: Sadece normal dosyaları listeler.
      * -name *.py: Wildcard (*) kullanarak dosya adını filtreler.
      * -print0: Dosya adlarını boşluk yerine NUL karakteriyle ayırır (boşluklu adlar bozulmaz).

2. Metin Tarama Komutu (Grep):
   Argüman listesi : ['grep', '-nHF', '--', '-x test('] + bulunan dosyalar
   Komut görünümü  : grep -nHF -- '-x test(' <bulunan dosyalar>
   Açıklama:
      * grep -n: Eşleşen satırların numarasını gösterir.
      * -H: Her sonuçta dosya adını yazar.
      * -F: Arama metnini düzenli ifade değil, düz metin olarak arar.
      * --: Arama ifadesinin tire (-) ile başlaması durumunda seçenek sanılmasını önler.
      * -x test(: Aranan hedef kelime/metin.
      * <bulunan dosyalar>: 1. komutun bulduğu dosyalar buraya eklenir.
----------------------------------------------------------------------

[ÇALIŞTIRMA] Komutlar argüman listesiyle (shell kullanmadan) çalıştırılıyor...

Çalışan find listesi : ['find', '/tmp/os28-test', '-type', 'f', '-name', '*.py', '-print0']
Çalışan grep listesi : ['grep', '-nHF', '--', '-x test('] + 2 dosya

/tmp/os28-test/z.py:3:-x test()
```

### 4. Tek tırnak içeren arama metni
```bash
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /tmp/os28-test '*.py' "it's" --execute
```
Beklenen: komut bozulmaz, `z.py` içindeki `it's here` satırı bulunur.

Çıktı:
```text
(======================================================================
 OS-28: File Search & Text-Grep Teaching Wrapper
======================================================================

[EĞİTSEL AÇIKLAMA] Girdilerinizden üretilen Linux Komutları:
----------------------------------------------------------------------
1. Dosya Arama Komutu (Find):
   Argüman listesi : ['find', '/tmp/os28-test', '-type', 'f', '-name', '*.py', '-print0']
   Komut görünümü  : find /tmp/os28-test -type f -name '*.py' -print0
   Açıklama:
      * find: Belirtilen dizin altında dosya ve klasör arar.
      * /tmp/os28-test: Aramanın başlatılacağı konum.
      * -type f: Sadece normal dosyaları listeler.
      * -name *.py: Wildcard (*) kullanarak dosya adını filtreler.
      * -print0: Dosya adlarını boşluk yerine NUL karakteriyle ayırır (boşluklu adlar bozulmaz).

2. Metin Tarama Komutu (Grep):
   Argüman listesi : ['grep', '-nHF', '--', "it's"] + bulunan dosyalar
   Komut görünümü  : grep -nHF -- 'it'"'"'s' <bulunan dosyalar>
   Açıklama:
      * grep -n: Eşleşen satırların numarasını gösterir.
      * -H: Her sonuçta dosya adını yazar.
      * -F: Arama metnini düzenli ifade değil, düz metin olarak arar.
      * --: Arama ifadesinin tire (-) ile başlaması durumunda seçenek sanılmasını önler.
      * it's: Aranan hedef kelime/metin.
      * <bulunan dosyalar>: 1. komutun bulduğu dosyalar buraya eklenir.
----------------------------------------------------------------------

[ÇALIŞTIRMA] Komutlar argüman listesiyle (shell kullanmadan) çalıştırılıyor...

Çalışan find listesi : ['find', '/tmp/os28-test', '-type', 'f', '-name', '*.py', '-print0']
Çalışan grep listesi : ['grep', '-nHF', '--', "it's"] + 2 dosya

/tmp/os28-test/z.py:2:it's here)
```

### 5. Geçersiz dizin
```bash
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /yok/dizin '*.py' 'def' --execute
```
Beklenen: komut çalıştırılmadan önce "Geçerli bir dizin bulunamadı" hatası verilir.

Çıktı:
```text
(======================================================================
 OS-28: File Search & Text-Grep Teaching Wrapper
======================================================================

[EĞİTSEL AÇIKLAMA] Girdilerinizden üretilen Linux Komutları:
----------------------------------------------------------------------
1. Dosya Arama Komutu (Find):
   Argüman listesi : ['find', '/yok/dizin', '-type', 'f', '-name', '*.py', '-print0']
   Komut görünümü  : find /yok/dizin -type f -name '*.py' -print0
   Açıklama:
      * find: Belirtilen dizin altında dosya ve klasör arar.
      * /yok/dizin: Aramanın başlatılacağı konum.
      * -type f: Sadece normal dosyaları listeler.
      * -name *.py: Wildcard (*) kullanarak dosya adını filtreler.
      * -print0: Dosya adlarını boşluk yerine NUL karakteriyle ayırır (boşluklu adlar bozulmaz).

2. Metin Tarama Komutu (Grep):
   Argüman listesi : ['grep', '-nHF', '--', 'def'] + bulunan dosyalar
   Komut görünümü  : grep -nHF -- def <bulunan dosyalar>
   Açıklama:
      * grep -n: Eşleşen satırların numarasını gösterir.
      * -H: Her sonuçta dosya adını yazar.
      * -F: Arama metnini düzenli ifade değil, düz metin olarak arar.
      * --: Arama ifadesinin tire (-) ile başlaması durumunda seçenek sanılmasını önler.
      * def: Aranan hedef kelime/metin.
      * <bulunan dosyalar>: 1. komutun bulduğu dosyalar buraya eklenir.
----------------------------------------------------------------------

[ÇALIŞTIRMA] Komutlar argüman listesiyle (shell kullanmadan) çalıştırılıyor...

Hata: Geçerli bir dizin bulunamadı -> /yok/dizin)
```
