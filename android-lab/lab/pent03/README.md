# PENT-03 — scripts, hooks and tests

> **Öğrenci:** Burak Özdemir · 2520191014 — **Ders:** MYO062 (Vize Seçenek 3 → PENT-03)
> **Kanıt Videosu (2–4 dk):** https://drive.google.com/file/d/1EkefgWf0mzZ19vQw48SmSnomJjOPKwCJ/view?usp=sharing
> **Rapor:** [`docs/tasks/PENT-03/REPORT.md`](../../../docs/tasks/PENT-03/REPORT.md)

Standard-library-only Python modules and Frida hooks that make up the PENT-03
pipeline. Every module exposes an importable API plus a `main()` CLI, and keeps
*pure* helpers (argv/URL/filename/hash builders) separate from *side-effecting*
runners so the suite tests offline.

## scripts/

| Module | Purpose | CLI |
|--------|---------|-----|
| `scope.py` | Authorization gate: allow only lab emulators / lab packages / loopback proxy hosts. Every other module calls `assert_in_scope()` first. | `python3 scope.py --serial … --package …` |
| `adb.py` | Thin, testable adb wrapper — argv builders + runners, boot-wait, props, ABI/SDK, root/remount. | `python3 adb.py abi` |
| `deploy_frida.py` | Detect ABI → resolve version → download `frida-server-<ver>-android-<arch>.xz` → decompress → push → start as root. | `python3 deploy_frida.py -s emulator-5554` |
| `install_ca.py` | Compute `subject_hash_old`, push the mitmproxy CA to `/system/etc/security/cacerts/<hash>.0`. | `python3 install_ca.py -s emulator-5554` |
| `sslpinning_bypass.py` | Run `objection … android sslpinning disable`; fall back to the Frida universal hook. | `python3 sslpinning_bypass.py com.securebank.mobile` |
| `pipeline.py` | Orchestrate `scope → boot → frida → ca → proxy → unpin` with a per-step log, `--dry-run` and `--report`. | `python3 pipeline.py com.securebank.mobile --dry-run` |
| `report.py` | Write a timestamped JSON + Markdown audit report of a run. | `python3 report.py runs/<run>.json` |
| `mitm_addon.py` | mitmproxy addon that logs intercepted flows + a per-host summary. | `mitmdump -s mitm_addon.py` |

`install_ca.py` auto-selects the CA method by device SDK: writable-`/system`
(API ≤ 33) or the Conscrypt-APEX `tmpfs` overlay (API ≥ 34 / Android 14). Force
it with `--method writable-system|apex-tmpfs`.

### Scope escape hatches

For a known lab outside the built-in allowlists, widen scope via env vars
(comma-separated) instead of editing code:

```bash
export OSLAB_EXTRA_SERIALS="emulator-5556,192.168.56.101:5555"
export OSLAB_EXTRA_PACKAGES="com.myorg.testapp"
export OSLAB_EXTRA_PROXY_HOSTS="mitmproxy"
```

## hooks/

One concern per file, each with a header comment saying what it bypasses and how
to load it. `frida-server` must be running (deploy it first).

- **`ssl-pinning-universal.js`** — neutralises pin checks across Conscrypt
  `TrustManagerImpl`, `SSLContext.init`, OkHttp `CertificatePinner`, the Network
  Security Config trust manager, `HostnameVerifier`, and `WebViewClient`.

  ```bash
  frida -U -f com.securebank.mobile -l hooks/ssl-pinning-universal.js --no-pause
  ```

- **`root-bypass.js`** — hides root from `File.exists` su/Magisk probes,
  `Runtime.exec("su")`, `Build.TAGS`, and RootBeer.

  ```bash
  frida -U -f com.securebank.mobile -l hooks/root-bypass.js --no-pause
  ```

- **`method-trace.js`** — traces every method of one or more Java classes
  (args + return values) to inspect app internals. Pick classes via `-P`.

  ```bash
  frida -U -f com.securebank.mobile -l hooks/method-trace.js --no-pause \
        -P '{"classes":["com.securebank.mobile.net.ApiClient"]}'
  ```

## tests/

Offline pytest suite — no device, no network, no root. adb/openers/runners are
injected or monkeypatched, and the only shell-out (openssl, for the CA subject
hash) runs against a locally generated self-signed cert.

```bash
./run-tests.sh          # full offline suite (75 tests)
cd tests && python3 -m pytest -q
```
