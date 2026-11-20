# PENT-06: Frida-Trace Auto-Tracer & Call-Map Builder — Teknik Görev Raporu

| Alan | Değer |
| :--- | :--- |
| **Öğrenci Adı Soyadı** | Batuhan Seydi Çelik |
| **Öğrenci Numarası** | 2520191006 |
| **Kanıt Videosu** | [https://drive.google.com/file/d/1nJ0GxygvfFaJoj1dU84pFSBFZg-pUnDH/view](https://drive.google.com/file/d/1nJ0GxygvfFaJoj1dU84pFSBFZg-pUnDH/view) |
| **Görev Kodu (Task ID)** | `PENT-06` |
| **Ders / Modül Referansı** | `MYO062` / Teached `05.10` (`frida-trace`, `süreç -> fonksiyon -> hook`) |
| **Hedef Alt Sistem** | `android-lab/lab`, `console/oslab.py`, `labctl`, `dashboard` |
| **Şema Sürümü** | `schema_version: "1.0"` |
| **Durum** | Tamamlandı & Doğrulandı (`12 passed`) |

---

## 1. Proje Başlığı ve Özet (PENT-06: Frida Tracer & Call-Map Builder)

**PENT-06 (`frida-trace` Auto-Tracer & Call-Map Builder)** görevi kapsamında, `os-lab` (`android-lab`) ortamındaki yetkilendirilmiş hedef süreçlerin (Android paketleri, native `.so` modülleri, Java sınıfları ve Objective-C metotları) çalışma zamanı (runtime) fonksiyon çağrılarını otomatik olarak keşfeden, argüman/dönüş değeri anlık görüntülerini (snapshots) yakalayan ve hiyerarşik bir **JSON Çağrı Haritası (Call-Map)** ile açıklamalı oturum günlüğü (**Annotated Session Log**) üreten uçtan uca bir dinamik analiz altyapısı geliştirilmiştir.

### Temel Çıktılar ve Entegrasyon Noktaları
- **Çekirdek İzleyici ve Ayrıştırıcı Modül:** `android-lab/lab/scripts/trace_runner.py`
- **Kanca (Hook) Giriş Noktası:** `android-lab/lab/hooks/trace_runner.py` (CLI ve API uyumluluğu için birebir sarmalayıcı)
- **Komut Satırı ve Orkestrasyon Entegrasyonu:**
  - `labctl android trace` (ve `labctl trace`) alt komutu
  - `android-lab/lab/orchestrator.py` (`trace` ve kilitli `clean` aksiyonları)
  - `android-lab/lab/Makefile` (`make trace` hedefi, ortam değişkenleri üzerinden kabuk enjeksiyonuna karşı korumalı)
- **Web Konsolu ve Gösterge Paneli (Dashboard):**
  - `console/oslab.py` üzerinde `trace` aksiyon planlaması (`oslab.plan()`), hedef/glob doğrulaması ve `Inspect` aksiyon grubu kaydı
  - `dashboard/src/views/lab-page.tsx` ve `dashboard/src/lib/api.ts` üzerinde canlı hedef/glob önizleme arayüzü
- **Birim ve Entegrasyon Test Paketi:** `android-lab/lab/tests/test_trace_runner.py`

---

## 2. Mimari ve Uygulama Detayları

### 2.1. Kapsam Koruması (Scope Guard) ve Girdi Doğrulama
Dinamik enstrümantasyonun yalnızca laboratuvar kapsamındaki hedeflerde çalışmasını garanti altına almak amacıyla çok katmanlı doğrulama uygulanmıştır:
- **Hedef Doğrulama (`validate_target`)**: Boş hedefleri, CLI bayrak enjeksiyonlarını (`-` ile başlayan girdiler), kabuk (shell) meta karakterlerini (`;|&$\`\n\r\0><`) ve kritik sistem süreçlerini (`FORBIDDEN_TARGETS`: `init`, `systemd`, `sshd`, `launchd`, `kernel_task`, `lsass.exe`, `csrss.exe` ve ayrılmış PID değerleri `0`, `1`, `00`, `01`) reddeder.
- **Sembol Glob Doğrulama (`validate_symbol_glob`)**: Native C (`*auth*`, `libauth.so!check_*`), Java (`com.testlab.*!verify*`) ve Objective-C (`-[NSURLSession *]`, `+[Keychain *]`) desenlerini destekler; kabuk enjeksiyonu ve geçersiz CLI bayraklarını engeller. `_normalize_cli_argv()` yardımıyla `-` ile başlayan Objective-C desenleri (`-[Class selector]`) `argparse` katmanında `--flag=value` formatına dönüştürülerek güvenle işlenir.
- **Taşıma Katmanı Doğrulaması (`build_frida_trace_cmd`)**: USB (`-U`), özel cihaz kimliği (`-D <id>`, `-U` ile çakışmadan) ve uzak sunucu (`-H <host>`) modlarını tipli argüman dizisi olarak üretir (`shell=False`). Yalnızca hiçbir dahil etme deseni (`-i`, `-I`, `-j`, `-m`) verilmediğinde varsayılan `*` desenine düşer.

### 2.2. Otomatik Handler Enstrümantasyonu (`defineHandler`)
`frida-trace` tarafından üretilen `__handlers__/<module>/<symbol>.js` taslak dosyaları, canlı süreç başlatılmadan hemen önce `instrument_handlers_dir()` tarafından taranır:
- **Özel Handler Koruması (`_is_frida_stub_handler`)**: Yalnızca değiştirilmemiş standart Frida taslakları (veya boş dosyalar) güncellenir; analistin elle özelleştirdiği `.js` dosyaları korunur.
- **Yapılandırılmış Telemetri (`generate_handler_script`)**: `onEnter` ve `onLeave` kancaları; iş parçacığı bazlı (`globalThis.__oslabDepthByTid`) çağrı derinliğini (`depth`), zaman damgalarını (`timestamp_ms`), çağrı süresini (`duration_ms`), argüman anlık görüntülerini (UTF-8 C-string işaretçi çözümlemesi ve isteğe bağlı `arg_types` imza metaverisiyle) ve dönüş değerini (`retval`) `[OSLAB_TRACE]` önekli JSON satırları olarak yayınlar.

### 2.3. Çoklu Format Ayrıştırıcı ve Call-Map Oluşturucu
`parse_trace_output()` ve `build_call_map()` fonksiyonları dört farklı izleme formatını tek bir deterministik modele dönüştürür:
1. **Fonksiyon Keşif Satırları:** `symbol: Auto-generated handler at ".../__handlers__/module/symbol.js"`
2. **Standart `frida-trace` Çağrı Ağaçları:** İş parçacığı başlıkları (`/* TID 0x1a2b */`), girinti boruları (`|`), giriş çağrıları ve dönüş okları (`<=`, `<-`, `=>`, `->`)
3. **Yapılandırılmış `[OSLAB_TRACE]` JSON Olayları:** `enter` ve `leave` olaylarının iş parçacığı bazlı yığın (stack) eşleştirmesi
4. **Objective-C Metot İzleri:** `-[Class selector:arg] => retval`

Üretilen JSON Çağrı Haritası (`schema_version: "1.0"`, `task_id: "PENT-06"`) aşağıdaki ana bileşenleri içerir:
- `summary`: `discovered_count`, `functions_called_count`, `total_calls`, `unique_edges`, `threads_observed`, `max_depth`, `uncalled_functions`, `entry_points`, `truncated`
- `discovered_functions`: Keşfedilen her sembolün modül, tam ad (`module!symbol`), handler yolu ve çağrılma sayısı (`call_count`)
- `functions`: Fonksiyon bazında çağrılma sayısı, çağıranlar (`callers`), çağrılanlar (`callees`), argüman anlık görüntüleri (`arg_snapshots`) ve dönüş değerleri (`return_values`)
- `call_sequence`: Kronolojik çağrı dizisi (`call_id`, `parent_call_id`, `caller`, `children_call_ids`, `depth`, `thread_id`, `args`, `retval`, `duration_ms`)
- `call_graph`: Yönlü `caller -> callee` kenarları ve frekansları

### 2.4. Bellek Sınırları, Hassas Veri Maskeleme ve Atomik Dosya Yayını
- **Bellek ve Çıktı Sınırları:** Yüksek hacimli hedeflerde bellek tükenmesini önlemek için canlı `frida-trace` çıktısı ve girdi günlükleri `MAX_RAW_OUTPUT_BYTES` (4 MiB) ile, ayrıştırılan çağrılar `MAX_PARSED_CALLS` (5.000) ile ve fonksiyon başına anlık görüntüler `MAX_SNAPSHOTS_PER_FUNCTION` (250) ile sınırlandırılmıştır. Sınır aşıldığında `"truncated": True` olarak raporlanır.
- **Hassas Veri Maskeleme (`redact_call_map`, `redact_trace_text`)**: Parola, anahtar, oturum jetonu (`Bearer`, `tok_*`, JWT `eyJ...`, şifreli yükler) içeren argüman ve dönüş değerleri varsayılan olarak (`redact=True`) `[REDACTED]` ile maskelenir. Ham yakalama yalnızca açık `--unsafe-plaintext` bayrağıyla etkinleştirilebilir.
- **Atomik Yayınlama ve Kilit (`artifact_lock`, `_publish_artifacts_atomically`)**: Eşzamanlı `trace` ve `clean` işlemlerinde JSON ve Markdown çıktılarının uyumsuz kalmasını önlemek için süreçler arası kilit (`oslab-android-trace-artifacts.lock`) kullanılır; her iki dosya önce geçici dosyalara yazılıp `fsync` edilir ve ardından `os.replace` ile atomik olarak yayınlanır.

---

## 3. Test ve Doğrulama Sonuçları

Geliştirilen modül, canlı bir Android emülatörü veya fiziksel cihaz gerektirmeden CI ortamında deterministik olarak çalışabilen 12 kapsamlı `pytest` testi (`android-lab/lab/tests/test_trace_runner.py`) ile doğrulanmıştır.

### 3.1. Çalıştırılan Test Komutu ve Çıktısı

```text
$ pytest android-lab/lab/tests/test_trace_runner.py -v --no-header -p no:cacheprovider
============================= test session starts =============================
collecting ... collected 12 items

android-lab/lab/tests/test_trace_runner.py::test_hooks_and_scripts_entry_points_expose_same_api PASSED [  8%]
android-lab/lab/tests/test_trace_runner.py::test_validate_target_accepts_lab_targets_and_rejects_unsafe_inputs PASSED [ 16%]
android-lab/lab/tests/test_trace_runner.py::test_validate_symbol_glob_accepts_valid_globs_and_rejects_injection PASSED [ 25%]
android-lab/lab/tests/test_trace_runner.py::test_build_frida_trace_cmd_constructs_typed_argument_list PASSED [ 33%]
android-lab/lab/tests/test_trace_runner.py::test_parse_args_string_snapshots_diverse_argument_types PASSED [ 41%]
android-lab/lab/tests/test_trace_runner.py::test_generate_and_instrument_handlers_dir PASSED [ 50%]
android-lab/lab/tests/test_trace_runner.py::test_build_call_map_from_standard_frida_trace_fixture PASSED [ 58%]
android-lab/lab/tests/test_trace_runner.py::test_parse_oslab_structured_json_and_objc_trace_lines PASSED [ 66%]
android-lab/lab/tests/test_trace_runner.py::test_run_trace_session_writes_json_and_annotated_session_log PASSED [ 75%]
android-lab/lab/tests/test_trace_runner.py::test_run_trace_session_with_mocked_frida_trace_subprocess PASSED [ 83%]
android-lab/lab/tests/test_trace_runner.py::test_cli_simulate_and_scope_guard_exit_codes PASSED [ 91%]
android-lab/lab/tests/test_trace_runner.py::test_oslab_console_plan_supports_android_trace_action PASSED [100%]

============================= 12 passed in 0.30s ==============================
```

### 3.2. Test Kapsamı Özeti
1. **`test_hooks_and_scripts_entry_points_expose_same_api`**: `hooks/trace_runner.py` ve `scripts/trace_runner.py` giriş noktalarının aynı sembol ve API yüzeyini sunduğunu doğrular.
2. **`test_validate_target_accepts_lab_targets_and_rejects_unsafe_inputs`**: Geçerli paket/PID hedeflerinin kabul edildiğini; `sshd`, `init`, `0`, `1`, bayrak enjeksiyonu ve kabuk meta karakterlerinin `TraceScopeError` ile reddedildiğini doğrular.
3. **`test_validate_symbol_glob_accepts_valid_globs_and_rejects_injection`**: Native, Java ve Objective-C sembol desenlerinin kabul edildiğini ve enjeksiyon girişimlerinin engellendiğini doğrular.
4. **`test_build_frida_trace_cmd_constructs_typed_argument_list`**: USB (`-U`), özel cihaz (`-D`), uzak sunucu (`-H`), spawn (`-f`) ve attach (`-p` / `-n`) argüman vektörlerinin doğru üretildiğini doğrular.
5. **`test_parse_args_string_snapshots_diverse_argument_types`**: İşaretçi açıklamaları (`0x7ff90100 ("student_lab")`), işaretli/işaretsiz tamsayılar, dizeler, JSON nesneleri ve `arg_types` metaverisinin doğru ayrıştırıldığını doğrular.
6. **`test_generate_and_instrument_handlers_dir`**: Frida taslak dosyalarının `[OSLAB_TRACE]` telemetrisiyle güncellendiğini ve kullanıcı tarafından yazılmış özel `.js` handler dosyalarının korunduğunu doğrular.
7. **`test_build_call_map_from_standard_frida_trace_fixture`**: Çok seviyeli (`max_depth: 2`) kimlik doğrulama ve kripto çağrı ağacından `call_sequence`, `call_graph` ve `functions` yapılarının eksiksiz üretildiğini doğrular.
8. **`test_parse_oslab_structured_json_and_objc_trace_lines`**: Yapılandırılmış `[OSLAB_TRACE]` JSON satırları ile Objective-C (`-[NSURLSession dataTaskWithRequest:...]`) izlerinin iç içe derinlik ve süreleriyle ayrıştırıldığını doğrular.
9. **`test_run_trace_session_writes_json_and_annotated_session_log`**: Oturum sonunda hem `call-map.json` hem de `trace-session.md` dosyalarının varsayılan hassas veri maskelemesiyle (`[REDACTED]`) üretildiğini doğrular.
10. **`test_run_trace_session_with_mocked_frida_trace_subprocess`**: Canlı `frida-trace` alt sürecinin doğru argümanlarla başlatıldığını, handler enstrümantasyonunun süreç başlamadan önce çalıştığını ve sıfır dışı çıkış kodlarında `RuntimeError` fırlatıldığını doğrular.
11. **`test_cli_simulate_and_scope_guard_exit_codes`**: CLI `--simulate`, `--unsafe-plaintext` ve kapsam dışı hedef çıkış kodlarının (`0` ve `2`) doğruluğunu test eder.
12. **`test_oslab_console_plan_supports_android_trace_action`**: `console/oslab.py` üzerindeki `plan()` fonksiyonunun Android `trace` aksiyonunu, hedef/glob doğrulamasını ve sıfır dolgulu PID (`"00"`, `"01"`) engellemesini doğru uyguladığını doğrular.

---

## 4. Karşılaşılan Zorluklar ve Çözümleri

### 4.1. Tauri İmzalama (Signing Key) ve Fork Güvenliği Kısıtlamaları
- **Karşılaşılan Durum:** CI/CD iş akışlarında (GitHub Actions üzerindeki masaüstü/paketleme iş akışları) bir çatal (fork) deposundan veya harici PR üzerinden tetiklenen derlemelerde, GitHub güvenlik modeli gereği depoya ait özel imzalama sırları (`TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` ve Windows Authenticode / SignPath sertifikaları) çatal iş akışı ortamına aktarılmamaktadır. Bu nedenle uygulama ve gösterge paneli derleme (compile/build) adımları tamamen başarılı olmasına rağmen, son paket imzalama (bundler signing) adımında imzalama anahtarı eksikliği kaynaklı beklenen bir kısıtlama oluşmaktadır.
- **Çözüm ve Doğrulama Yaklaşımı:** Bu durum kod veya mimari bir hata olmayıp CI ortamının çatal (fork) güvenlik politikasından kaynaklanan kasıtlı bir koruma mekanizmasıdır (`lat.md/tooling.md` içinde de belirtildiği üzere resmi imzalama yalnızca ana depo sırlarıyla veya açık onaylı sürüm iş akışlarında gerçekleştirilir). Yerel doğrulama ve CI birim/entegrasyon aşamaları `scripts/run-tests.sh --quick`, `pytest` ve `python scripts/build-content.py --check` üzerinden imzalama anahtarına bağımlı olmaksızın eksiksiz olarak çalıştırılmış ve tüm kontrollerden başarıyla geçmiştir.

### 4.2. Kabuk Enjeksiyonu, Eşzamanlılık ve Bellek Güvenliği İyileştirmeleri
- **Make Hedeflerinde Kabuk Genişletmesi:** `Makefile` içindeki `trace` hedefinde `$(PKG)` ve `$(GLOB)` değişkenlerinin doğrudan çift tırnaklı kabuk komutuna yerleştirilmesi yerine `trace: export PKG` ve `trace: export GLOB` kullanılarak değerlerin doğrudan Python `os.environ` üzerinden okunması sağlanmış, kabuk enjeksiyonu riski tamamen ortadan kaldırılmıştır.
- **Objective-C Sembol Globlarında Tire (`-`) Çakışması:** `-[NSURLSession *]` gibi `-` ile başlayan argümanların `argparse` tarafından bilinmeyen bayrak olarak reddedilmesi sorunu `_normalize_cli_argv()` ön işlemcisiyle çözülmüştür.
- **Atomik Çıktı ve Kilit Mekanizması:** Eşzamanlı izleme veya temizleme (`clean`) işlemleri sırasında yarım kalmış dosya okunmasını engellemek için sistem geçici dizininde kilit dosyası (`artifact_lock`) ve atomik `os.replace` yayınlama mekanizması devreye alınmıştır.

---

## 5. Sonuç ve Kullanım Talimatları

**PENT-06** göreviyle birlikte `android-lab` ortamı; yetkilendirilmiş hedeflerde çalışma zamanı fonksiyon keşfi, argüman/dönüş değeri yakalama, hassas veri maskeleme ve yapılandırılmış JSON çağrı haritası üretme yeteneklerine kavuşmuştur.

### 5.1. Hızlı Kullanım Komutları

**1. Deterministik Simülasyon Modu (Cihaz/Emülatör Gerektirmez):**
```bash
python3 android-lab/lab/hooks/trace_runner.py \
  --target com.testlab.vulnerable \
  -i "*auth*" -i "check_*" \
  --simulate \
  --out android-lab/lab/artifacts/traces/call-map.json \
  --session-log android-lab/lab/artifacts/traces/trace-session.md
```

**2. Kaydedilmiş Bir `frida-trace` Günlüğünden Çağrı Haritası Üretme:**
```bash
python3 android-lab/lab/scripts/trace_runner.py \
  --target com.testlab.vulnerable \
  --input-log path/to/frida-trace.log \
  --action login_flow \
  --out android-lab/lab/artifacts/traces/call-map.json \
  --session-log android-lab/lab/artifacts/traces/trace-session.md
```

**3. Canlı Android Lab Hedefini İzleme (`labctl` veya `make` ile):**
```bash
# labctl üzerinden
./labctl android trace --target com.testlab.vulnerable --include "*auth*" --timeout 15

# Makefile üzerinden
make -C android-lab/lab trace PKG=com.testlab.vulnerable GLOB='*auth*'
```

**4. Test Paketini Çalıştırma:**
```bash
pytest android-lab/lab/tests/test_trace_runner.py -v
```
