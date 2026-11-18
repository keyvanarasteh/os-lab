# Lab target

The pipeline's default target is the fictional **SecureBank**
(`com.securebank.mobile`, described in `securebank.json`). It is a stand-in for
a real banking app: TLS with certificate pinning plus basic root detection, so a
run exercises every stage — `frida` → `ca` → `proxy` → `unpin`.

## No binaries in git

Per the os-lab rules, **no APK is committed here** — you download or build the
target at setup time. Two ways to get a working target:

### 1. Build your own SecureBank

Any minimal Android app that pins its API certificate (OkHttp `CertificatePinner`
and/or a `network_security_config.xml` pin-set) works. Install it on the
emulator with `adb install app.apk`; the package id `com.securebank.mobile` is
already in scope.

### 2. Use a public intentionally-vulnerable app (for practice)

Well-known, openly published training apps — download the APK from their
official releases, then widen scope for their package id:

| App | Package | Source |
|-----|---------|--------|
| DIVA (Damn Insecure & Vulnerable App) | `jakhar.aseem.diva` | published training APK |
| InsecureBankv2 | `com.android.insecurebankv2` | published training APK |
| OWASP MASTG crackmes | various | OWASP MAS project |

```bash
adb install diva.apk
export OSLAB_EXTRA_PACKAGES="jakhar.aseem.diva"
python3 ../scripts/pipeline.py jakhar.aseem.diva --report ../../../runs
```

> Only ever run this against apps you own or are authorized to test, on an
> isolated lab emulator. The scope guard refuses anything else by default.
