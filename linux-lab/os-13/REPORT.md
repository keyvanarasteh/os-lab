# OS-13 Vize Projesi Raporu — apt update/upgrade Safe Wrapper (Order + Dry-Run)

**Öğrenci:** Emirhan Çırpın (2620511067)
**GitHub:** @Nbrsad
**Ders:** MYO062

## 1. Projede Ne Yaptım?

**OS-13 (apt update/upgrade Safe Wrapper — Order + Dry-Run)** görevi kapsamında,
`apt` ile paket güncellemenin sırasını kodla zorunlu kılan ve varsayılan olarak
hiçbir şeyi değiştirmeyen bir Bash aracı geliştirdim:

- **`linux-lab/scripts/os-13-apt-safe-wrapper.sh`:** Üç adımlı tek bir sıra
  yürütür — `apt-get update` → `apt-get -s upgrade` (simülasyon) →
  `apt-get -y upgrade`. Sıra yorumda değil kodda: 3. adım, 1. adım aynı
  çalıştırmada `exit 0` vermeden çalışmıyor.
- **Guard (koruma):** `apt-get update` hata kodu döndürürse betik upgrade'i
  başlatmadan `1` ile çıkar. Ayrıca `update` `exit 0` verip "Some index files
  failed to download" dediğinde de durur; bu sessiz yarı-başarı bilinçli olarak
  yalnızca `--allow-partial` ile geçilebilir.
- **Dry-run varsayılan:** Argümansız çalıştırma yalnızca planı ve `apt-get -s`
  çıktısını gösterir; `update` ve upgrade çağrılmaz, root gerekmez.
- **Okunur çıktı + log:** Her apt komutu zaman damgasıyla tek bir log dosyasına
  yazılır (`${TMPDIR:-/tmp}/os-13-apt-last-<uid>.log`, mod `0600`, symlink
  takılmaz), ekrana özet ve "n paket yükselecek,
  m geride tutuldu (kept back)" satırı basılır.
- **Anlaşılır hata:** Kilit (`Could not get lock`), DNS (`Temporary failure
  resolving`), disk dolu, eksik GPG anahtarı ve 404/hash uyuşmazlığı için
  "ne yapmalı" ipucu basar (OS-15/25/37'ye yönlendirir).
- **`--dist-upgrade`, `--yes`, `--noninteractive`, `--allow-partial`,
  `--allow-removals`:** Küçük
  ama gerçek seçenekler; `--noninteractive` dpkg conffile sorusunda etkileşimsiz
  çalıştırmanın asılı kalmasını engeller.
- **`linux-lab/tests/test_os13_apt_safe_wrapper.py`:** 23 birim testi. Testler
  `PATH`'e konan stub bir `apt-get` ile çalışır: ağ yok, root yok, gerçek paket
  değişmez; ölçülen şey çağrı sırası ve guard davranışıdır.
- **Doküman:** `linux-lab/os-13/VERIFY.md` (çalıştırma komutları, beklenen çıktı,
  test tablosu, video senaryosu) ve `linux-lab/README.md` içinde kısa bir bölüm.

## 2. Git ve Pull Request (PR) Sürecinde Ne Öğrendim?

- Görevi **önce rezerve etmeyi** öğrendim: `reservations/OS-13.json` dosyası tek
  başına bir PR; bu, aynı görevi iki kişinin yapmasını engelliyor
  ("Reserve via PR" akışı).
- Repoyu fork edip `upstream` ile senkron tutmayı, ana dalı (`master`) temiz
  bırakıp işi ayrı bir dalda (`feat/os-13-apt-safe-wrapper`) yürütmeyi uyguladım.
- **Conventional Commits** ile anlamlı, tek işe odaklı commit'ler yazmayı;
  PR şablonunu (özet, tip, bileşen, nasıl test edildi) doldurmayı öğrendim.
- Değişikliği göndermeden önce yerel kapıyı çalıştırmayı öğrendim:
  `bash -n linux-lab/scripts/os-13-apt-safe-wrapper.sh` ve
  `./scripts/run-tests.sh --quick` (CI yok; kontrolü katkıcı yapıyor).
- En çok işime yarayan fikir: **"çalıştı" demek yerine ölçmek** — betik upgrade
  sonrası yeniden `apt-get -s upgrade` çalıştırıp kalan paket sayısını yazıyor,
  testler de "hangi komut hangi sırada çağrıldı"yı doğruluyor.
- Bir de şunu gördüm: `apt-get update` her zaman "başarılı" demek değil —
  `exit 0` olsa bile eksik index ile dönebiliyor. Gerçek bir tehlike bu sessiz
  durum; sıra zorlaması tek başına yetmiyor, çıktıyı da denetlemek gerekiyor.
- Sourcery incelemesi 13 bulgu verdi; 12'sini kapattım (biri zaten
  dokümante edilmişti). Kritik olan log symlink'iydi: root çalıştırmada
  `/tmp` altındaki log yolu bir kullanıcı symlink'i olabilir ve hedef dosyayı
  ezerek silebilir. Artık log `0600`, kullanıcıya özel ve symlink takılmıyor.
  Ayrıca apply komutundaki tekrarlanan alt komut, simülasyon-apply arası
  plan değişimi, sudo ile `DEBIAN_FRONTEND` geçişi, `SUDO` seçenekli ön ekler,
  sadece kaldırma içeren planlar, başarısız post-check'ın `0` dönmesi ve
  `--quick` kapısının `bash -n` atlaması giderildi.
