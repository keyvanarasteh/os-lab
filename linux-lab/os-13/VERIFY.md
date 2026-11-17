# OS-13 Doğrulama (Verification) — apt update/upgrade Safe Wrapper (Order + Dry-Run)

Bu belge, `linux-lab/scripts/os-13-apt-safe-wrapper.sh` betiğinin neyi garanti
ettiğini, nasıl çalıştırıldığını ve beklenen çıktısını gösterir. Tüm çalıştırma
yetkili lab/sanal makine içindedir.

## 1. Neyi doğruluyoruz?

| # | Garanti | Nasıl kanıtlanır |
|---|---|---|
| G1 | **Sıra zorunlu**: `apt-get update` → `apt-get -s upgrade` → `apt-get -y upgrade` | Betikte 3. adım, 1. adım aynı çalıştırmada `exit 0` vermeden çalışmıyor; testte çağrı sırası denetleniyor |
| G2 | **Kırık index'te guard**: `update` başarısızsa upgrade hiç başlamaz | `apt-get update` hata kodu → `GUARD` mesajı + çıkış kodu `1`, upgrade çağrısı yok |
| G3 | **Kısmi index'te guard**: `update` `exit 0` verse bile "Failed to fetch" varsa durur | Uyarı satırı yakalanıyor; `--allow-partial` bilinçli istisna |
| G4 | **Dry-run varsayılan**: hiçbir şeyi değiştirmez | `apt-get update` ve upgrade çağrılmıyor; yalnızca `-s` (simülasyon) |
| G5 | **Görünürlük**: tüm komut ve çıktı log'da | `${TMPDIR:-/tmp}/os-13-apt-last-<uid>.log` (0600, symlink takılmaz) |
| G6 | **Uygulama sonrası ölçüm**: "bitti" demek yerine yeniden simüle eder | Post-check `apt-get -s upgrade` + kalan paket sayısı |
| G7 | **Gözden geçirilen plan = uygulanan plan**: apply öncesi yeniden simülasyon | Plan değiştiyse `GUARD`, upgrade çağrılmaz |
| G8 | **Kaldırma planı gizli kalmaz**: `Remv` satırları listelenir | `--yes` ile kaldırma için `--allow-removals` zorunlu |

## 2. Çalıştırma komutları

Lab/sanal makine içinde, repo kökünden:

```bash
# 1) Sözdizimi (PR öncesi zorunlu kontrolün bir parçası)
bash -n linux-lab/scripts/os-13-apt-safe-wrapper.sh

# 2) Yardım
bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --help

# 3) Dry-run (varsayılan): plan + simülasyon, sisteme dokunmaz, root gerekmez
bash linux-lab/scripts/os-13-apt-safe-wrapper.sh

# 4) Gerçek uygulama: sırayla update -> simülasyon -> upgrade (onay ister)
sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --apply

# 5) Etkileşimsiz uygulama (conffile sorularında asılı kalmamak için)
sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --apply --yes --noninteractive

# 6) Genişletilmiş plan (yeni paket/kaldırma içerebilir)
sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --dist-upgrade

# 7) Kaldırma içeren planı etkileşimsiz uygulamak için ek onay
sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --dist-upgrade --apply --yes --allow-removals
```

Çıkış kodları: `0` temiz, `1` guard veya apt adımı başarısız, `2` kullanım hatası.

## 3. Beklenen çıktı

### 3.1 Dry-run (varsayılan) — sistem değişmez

```text
OS-13 apt update/upgrade safe wrapper 1.0.0
------------------------------------------------------------------------
mode     : dry-run (plan only, nothing on this system changes)
step 3   : apt-get -y upgrade
apt-get  : apt-get
distro   : Ubuntu 26.04 LTS
free     : 18432 MB on /var/cache/apt
log      : /tmp/os-13-apt-last-1000.log
[ok]   preflight: apt-get is usable

== step 1/3 - refresh the package index (apt-get update) ==
[plan] apt-get update
       skipped: it rewrites /var/lib/apt/lists. --apply runs it for real
       and gates the upgrade on its exit code.

== step 2/3 - simulate the upgrade plan (apt-get -s upgrade) ==
    # 2026-11-15T09:12:44Z
    $ apt-get -s upgrade
    Reading package lists... Done
    Building dependency tree... Done
    Reading state information... Done
    Calculating upgrade... Done
    The following packages will be upgraded:
      bash curl libc6
    3 upgraded, 0 newly installed, 0 to remove and 2 not upgraded.
    Inst bash [5.2.21-2ubuntu4] (5.2.21-2ubuntu4.1 Ubuntu:24.04/noble-updates [amd64])
    Inst curl [8.5.0-2ubuntu10.2] (8.5.0-2ubuntu10.3 Ubuntu:24.04/noble-updates [amd64])
    Inst libc6 [2.39-0ubuntu8.2] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-updates [amd64])

packages that would be upgraded:
    - bash
    - curl
    - libc6

[warn] 2 package(s) kept back: phased updates or new dependencies.
[warn] upgrade leaves them alone on purpose; --dist-upgrade shows the wider plan.
[ok]   plan: 3 package(s) upgradeable, 2 kept back

== step 3/3 - apply (apt-get -y upgrade) ==
[plan] apt-get -y upgrade
       skipped in dry-run; nothing was modified.
------------------------------------------------------------------------
summary
  order     : update -> simulate -> upgrade
  update    : skipped (dry-run)
  plan      : 3 package(s) to upgrade, 2 kept back
  log       : /tmp/os-13-apt-last-1000.log

nothing was changed. Run the same order for real with:
  sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --apply
```

### 3.2 Guard — `apt-get update` başarısız (örnek: DNS/mirror)

```text
== step 1/3 - refresh the package index (apt-get update) ==
    # 2026-11-15T09:20:02Z
    $ sudo apt-get update
    Err:1 http://archive.ubuntu.com/ubuntu noble InRelease
      Temporary failure resolving 'archive.ubuntu.com'
    Reading package lists... Done
    E: Failed to fetch http://archive.ubuntu.com/ubuntu/dists/noble/InRelease  Temporary failure resolving 'archive.ubuntu.com'
[warn] hint: DNS: the mirror name does not resolve; check the resolver before blaming apt (OS-37)
[fail] apt-get update exited 100.
[fail] GUARD: upgrade refused - the plan would be built on stale indexes.
```

Çıkış kodu `1`'dir ve `apt-get -y upgrade` **hiç çağrılmaz**: sistem yarım
kalmaz. (Aynı davranış `exit 0` + "Some index files failed to download" için de
geçerlidir; `--allow-partial` verilmedikçe upgrade başlamaz.)

### 3.3 Apply — sıra korunur ve sonuç ölçülür

```text
== step 1/3 - refresh the package index (apt-get update) ==
[ok]   index refreshed

== step 2/3 - simulate the upgrade plan (apt-get -s upgrade) ==
[ok]   plan: 3 package(s) upgradeable, 2 kept back

== step 3/3 - apply the upgrade (apt-get -y upgrade) ==
    $ sudo apt-get -y upgrade
    Setting up bash (5.2.21-2ubuntu4.1) ...
    Setting up libc6 (2.39-0ubuntu8.4) ...
    Setting up curl (8.5.0-2ubuntu10.3) ...
[ok]   upgrade finished
[ok]   post-check: no upgradeable package left
------------------------------------------------------------------------
summary
  order     : update -> simulate -> upgrade
  update    : ok
  plan      : 3 package(s) to upgrade, 2 kept back
  remaining : 0 package(s) still upgradeable
  log       : /tmp/os-13-apt-last-1000.log
```

## 4. Otomatik testler (offline, root/ağ gerekmez)

Testler `PATH` üzerine konan bir **stub `apt-get`** ile çalışır: gerçek paket
veritabanına, ağa veya sisteme dokunulmaz; ölçülen şey sıra ve guard davranışıdır.

```bash
python3 -m unittest discover -s linux-lab/tests -p 'test_os13*' -v
```

Sonuç: **23 test, OK**

| Test | Doğruladığı |
|---|---|
| `test_script_parses` | `bash -n` temiz |
| `test_help_exits_zero_and_calls_nothing` | `--help` çıkış `0`, hiçbir apt çağrısı yok |
| `test_unknown_argument_is_a_usage_error` | bilinmeyen argüman → çıkış `2` |
| `test_dry_run_is_default_and_runs_no_change` | yalnızca `--version` ve `-s upgrade` çağrıldı |
| `test_failed_update_stops_before_upgrade` | update hatası → `GUARD`, upgrade çağrılmadı |
| `test_order_is_update_then_simulate_then_upgrade` | çağrı sırası: `update`, `-s upgrade`, re-check `-s upgrade`, `-y upgrade` |
| `test_apply_does_not_duplicate_the_subcommand` | apply komutu `apt-get -y upgrade`; `upgrade -y upgrade` değil |
| `test_partial_index_failure_is_a_guard` | `Failed to fetch` → guard |
| `test_allow_partial_continues_on_request` | `--allow-partial` ile devam |
| `test_empty_plan_skips_the_upgrade` | yapılacak iş yoksa upgrade atlanır |
| `test_dist_upgrade_selection_is_honoured` | `--dist-upgrade` doğru alt komuta gider |
| `test_noninteractive_keeps_local_configs` | `--noninteractive` → `Dpkg::Options::=--force-confold` |
| `test_noninteractive_frontend_is_on_the_command_line` | `DEBIAN_FRONTEND` sudo üzerinden de gider |
| `test_sudo_prefix_with_options_is_split` | `SUDO="sudo -n"` gibi ön ekler ayrıştırılır |
| `test_plan_change_between_sim_and_apply_is_a_guard` | plan değiştiyse apply iptal |
| `test_failed_post_check_is_not_a_success` | post-check başarısızsa çıkış `1` |
| `test_removal_plan_is_not_applied_unattended_without_ack` | kaldırma için `--allow-removals` gerekir |
| `test_allow_removals_permits_the_plan` | `--allow-removals` ile kaldırma uygulanır |
| `test_removal_only_plan_is_not_treated_as_empty` | sadece `Remv` olan plan boş sayılmaz |
| `test_log_file_is_created_private` | log `0600` |
| `test_log_symlink_is_not_followed` | log yolu symlink ise hedefi ezmez |
| `test_unwritable_log_falls_back_and_still_runs` | yazılamayan log'da özel log'a düşer |
| `test_default_log_path_includes_the_uid` | varsayılan log kullanıcıya özel |

## 5. PR öncesi zorunlu kontrol

```bash
./scripts/run-tests.sh --quick
```

Bu, `linux-lab/tests` (OS-30 + OS-13) birim testlerini **ve** depo geneli
`bash -n` sözdizimi kapısını çalıştırır. Depodaki 83 `*.sh` dosyası `bash -n`
ile temiz geçer.

## 6. Lab VM'de canlı doğrulama (kanıt videosu senaryosu, 2–4 dk)

1. `bash -n linux-lab/scripts/os-13-apt-safe-wrapper.sh` → sessiz, çıkış `0`.
2. `bash linux-lab/scripts/os-13-apt-safe-wrapper.sh` → dry-run planı görünür,
   `apt-get update` **çalışmaz** (ekranda `[plan]` satırı).
3. Guard'ı göster: geçici bozuk bir kaynak ekle, sonra betiği çalıştır:
   ```bash
   echo 'deb http://olmayan-mirror.invalid/ubuntu noble main' | sudo tee /etc/apt/sources.list.d/os13-broken.list
   sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --apply --yes
   sudo rm -f /etc/apt/sources.list.d/os13-broken.list     # temizlik
   ```
   Beklenen: `GUARD` satırları, çıkış kodu `1`, upgrade hiç başlamadı.
4. `sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --apply` → sırayla
   update, simülasyon, onay, upgrade, post-check.
5. Kapanış: `git log --oneline -1` + PR linkini ekranda göster.

## 7. Sınırlar (bilinçli olarak kapsam dışı)

- `snap`/`flatpak`/`pip` güncellemeleri kapsam dışı; bu betik `apt-get` sırasını yönetir.
- `autoremove`/`autoclean` çalıştırmaz (bu OS-15'in işi), yeniden başlatma yapmaz;
  yalnızca `/var/run/reboot-required` varsa uyarır.
- `--yes` + `--noninteractive` birlikte kullanılmadıkça dpkg conffile sorusu
  etkileşimli çalıştırmada sorulur; etkileşimsiz işlerde ikisini birlikte kullanın.
- Kısmi index hatasını `--allow-partial` ile geçmek bilinçli bir override'dır:
  eski metadata ile upgrade planlanır, log bunu kaydeder.
- Kaldırma içeren bir plan (`--dist-upgrade`) etkileşimli çalıştırmada ayrıca
  gösterilir; `--yes` ile uygulanması `--allow-removals` ister.
- Apply öncesi plan yeniden simüle edilir; başka bir apt işlemi planı
  değiştirdiyse wrapper uygulamaz.
- Log dosyası `0600` modunda oluşturulur, symlink takılmaz; aynı yolu iki
  çalıştırma kullanırsa ikinci çalıştırma özel bir log'a yazar.
