# OS-26 — Çalıştırma ve doğrulama

Komutları kendi Linux lab/sanal makinenizde, repo kökünden çalıştırın.
Araç Python 3.11+ standart kütüphanesini kullanır; paket kurulumu veya `sudo`
gerektirmez. Yalnızca belirtilen dizinin izin ve sahiplik metadatasını okur.

## Tek komutla kullanım

```bash
python3 linux-lab/scripts/permission_audit.py /kendi/lab/dizininiz
python3 linux-lab/scripts/permission_audit.py /kendi/lab/dizininiz --json
```

Varsayılan politika: sahip mevcut kullanıcının UID'si; dosyalar en fazla `0644`,
dizinler en fazla `0755`. Daha dar izinler uygundur. Grup kontrolü için `--group`
verin; kullanıcı/grup adları ve sayısal UID/GID kabul edilir. Çalıştırılabilir
dosyalar içeren bir labda `--file-mode 0755` gibi bilinçli bir politika seçin.

```bash
python3 linux-lab/scripts/permission_audit.py /kendi/lab/dizininiz \
  --owner "$(id -u)" --group "$(id -g)" --file-mode 0755 --dir-mode 0755
```

| Çıkış kodu | Anlamı |
|---|---|
| `0` | Tarama tamamlandı; seçilen politikaya göre bulgu yok. |
| `1` | Tarama tamamlandı; incelenmesi gereken bulgular var. Bu bir çökme değildir. |
| `2` | Yanlış kullanım, erişim hatası veya eksik tarama. |

`complete: true`, kapsam içindeki taramanın tamamlandığını belirtir; bulgu
olmadığını söylemez. JSON'daki `findings`, dosya başına kuralları ve yalnızca
öneri olan komutları argv dizileri halinde taşır. `errors` okunamayan yolları
gösterir. Metin raporu aynı bilgileri okunabilir biçimde verir.

## Tekrarlanabilir küçük lab

Aşağıdaki kurulum yalnızca yeni oluşturduğu geçici labda örnek dosyalar oluşturur.
Denetleyicinin kendisi dosyalara yazmaz. Aynı terminal oturumunda devam edin:

```bash
os26_lab=$(mktemp -d /tmp/os26-demo.XXXXXX)
printf 'Lab public sample\n' > "$os26_lab/public.txt"
printf 'Lab private sample\n' > "$os26_lab/private.txt"
printf 'Lab team sample\n' > "$os26_lab/team.txt"
mkdir "$os26_lab/shared"
chmod 0666 "$os26_lab/public.txt"
chmod 0600 "$os26_lab/private.txt"
chmod 0660 "$os26_lab/team.txt"
chmod 0777 "$os26_lab/shared"

python3 linux-lab/scripts/permission_audit.py "$os26_lab"
echo "Denetleyici cikis kodu: $?"
```

Beklenen: `Scan: complete`, `Audited: 5`, `Entries with findings: 3`, çıkış `1`.
`public.txt` ve `shared` için `world-writable` ve `over-permissive-mode`,
`team.txt` için `over-permissive-mode` bulunur. `private.txt` için bulgu yoktur.
Rapordaki `chmod`/`chown` önerileri otomatik çalıştırılmaz.

JSON çıktısını ve dosyaların değişmediğini görün:

```bash
python3 linux-lab/scripts/permission_audit.py "$os26_lab" --json | python3 -m json.tool
stat -c '%a %u:%g %n' "$os26_lab"/*
```

İzinler hâlâ `666`, `600`, `660`, `777` olmalıdır. Boru hattının son çıkış kodu
`json.tool`'a aittir; denetleyicinin çıkışını bir önceki doğrudan çalıştırmada
kontrol ettik. JSON içinde `complete: true` ve üç bulgulu kayıt görülmelidir.

Gerçek sahipliği değiştirmeden sahiplik sapmasını gösterin: beklenen UID'yi
bilerek farklı seçiyoruz; bu komut herhangi bir `chown` işlemi yapmaz.

```bash
python3 linux-lab/scripts/permission_audit.py "$os26_lab" --owner "$(( $(id -u) + 1 ))"
```

Beklenen: kök dizin dahil beş kayıtta `owner-drift`, çıkış `1`.

Önerileri bu küçük lab için değerlendirip izinleri **kendiniz** düzeltin:

```bash
chmod 0644 "$os26_lab/public.txt"
chmod 0640 "$os26_lab/team.txt"
chmod 0755 "$os26_lab/shared"
python3 linux-lab/scripts/permission_audit.py "$os26_lab"
echo "Denetleyici cikis kodu: $?"
```

Beklenen: `No findings under this policy.`, `Entries with findings: 0`, çıkış `0`.

## Otomatik testler

```bash
python3 -m venv .venv-test
.venv-test/bin/python -m pip install pytest
.venv-test/bin/python -m pytest android-lab/lab/tests/test_permission_audit.py -q

# Diger lablarin genel test bagimliliklari:
.venv-test/bin/python -m pip install requests -r android-lab/lab/requirements.txt
source .venv-test/bin/activate
./scripts/run-tests.sh
npx --yes --package lat.md lat check
```

Var olan `.venv-test` ve pytest kurulumu kullanılabilir. OS-26 için beklenen
sonuç **41 passed**. Testler geçici dosyalar kullanır; ağ, `sudo` veya gerçek
sahiplik değişikliği gerektirmez. `lat`, proje belgelerinin grafik kontrolüdür;
denetleyicinin bağımlılığı değildir. Genel runner diğer labları da test eder.

## Kaydedilen geliştirme doğrulaması

Linux x86_64, Python 3.12.14 üzerinde OS-26 testleri **41 passed** verdi.
Yukarıdaki lab senaryosunda 5 girdi denetlendi: önce 3 bulgu/çıkış `1`, farklı
beklenen UID ile 5 sahiplik bulgusu/çıkış `1`, elle düzeltmeden sonra 0 bulgu/çıkış
`0` alındı. Denetleyicinin izinleri, UID/GID'yi, mtime/ctime'ı değiştirmediği
kontrol edildi. Bunlar geliştirme ortamının sonuçlarıdır.

Genel kontroller, aynı ortamda değişiklik içermeyen upstream
`5924675c2edce5f88dbf68b46f3504d8dba2a051` ile karşılaştırıldı:

| Kontrol | Değiştirilmemiş upstream | OS-26 dalı |
|---|---|---|
| Android test paketi | 170 geçti, 5 başarısız, 2 atlandı | 211 geçti, aynı 5 başarısız, 2 atlandı |
| Source Lab / Cleanup referans | 176 / 35 geçti | 176 / 35 geçti |
| Cleanup engine | 228 test; 3 başarısız, 6 hata | Aynı testlerde 3 başarısız, 6 hata |
| Kabuk sözdizimi | 71 script geçti | 71 script geçti |
| `lat check` | `cleanup-lab.md` özet paragrafı 339 > 250 karakter | Aynı tek hata; OS-26 düğümünde hata yok |

Android'deki aynı beş hata, Cleanup konsolunun üç testi, Source konsolunun
`test_merge_background_plan_and_build` ve web arayüzünün
`test_lab_start_requires_a_previewed_plan` testleridir. Genel runner iki dalda da
`4 passed, 2 failed, 3 skipped` verdi; Cargo ve dashboard bağımlılıkları yoktu,
grafik kontrolü ayrıca çalıştırıldı. Bu nedenle genel paket tamamen geçti
olarak işaretlenmedi; OS-26'ya özgü testlerin tamamı geçti.

## Kapsam ve sınırlamalar

- Sembolik bağlantılar (bozuk olanlar dahil), özel dosyalar ve farklı dosya
  sistemindeki alt yollar sayılarak atlanır. Kökün kendisi sembolik bağlantı
  olamaz; `/` yerine belirli bir lab dizini verilmelidir.
- Varsayılan sınır kök dahil 10.000 girdidir; `--max-entries` ile 1–1.000.000
  arasında ayarlanır. Sınır aşımı veya erişim hatası `complete: false`, çıkış `2`
  üretir; temiz rapor gibi sunulmaz.
- Bu bir Unix mod bitleri/UID/GID kontrolüdür. ACL'ler, capabilities, SELinux,
  içerik sırları ve inode'ların başka hard-link yolları incelenmez. Aynı cihazdaki
  bind mount'lar cihaz numarasıyla ayırt edilemez. Eşzamanlı değişen bir dizinin
  atomik görüntüsü değildir; sakin, sahip olunan bir lab üzerinde kullanın.
- Herkese yazma izni, izin maskesi geniş seçilse bile raporlanır. Sticky bitli
  paylaşımlı dizinlerin amacı ayrıca değerlendirilir; sticky/setgid dizin bitleri
  mod önerisinde korunur. Düzenli dosyalardaki setuid/setgid ayrıca raporlanır.
- `chmod` önerileri yeni izin eklemez, yalnızca işaretlenen bitleri kaldırır.
  `chown` başka mod bitlerini etkileyebilir; önerileri körlemesine veya topluca
  çalıştırmayın. Özel karakterli yollar metinde kaçışlanır, JSON'da korunur.

## Kanıt videosu (2–4 dakika)

1. `mertksll/os-lab` fork'unu ve kabul edilmiş rezervasyon [#112](https://github.com/keyvanarasteh/os-lab/pull/112) kaydını gösterin.
2. `git remote -v`, `git branch --show-current`, `git log -3 --oneline` ile akışı açıklayın.
3. Yukarıdaki küçük labda bulgulu ve elle düzeltildikten sonraki temiz raporu gösterin.
4. OS-26 testlerini çalıştırın; genel kontrolün kayıtlı sonucunu doğru biçimde açıklayın.
5. Kendi lab gözleminizi bu belgeye ekleyerek anlamlı bir commit ve push gösterin;
   mevcut uygulama PR'ının güncellendiğini açın.
6. Video bağlantısını PR'a ekleyip dersin Telegram grubunda paylaşın.

Öğrencinin kendi VM çıktısı ve kanıt videosu henüz bu aşamada alınmadı.
