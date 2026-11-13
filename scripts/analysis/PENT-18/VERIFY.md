# PENT-18 verification evidence

Date: 2026-11-13. Ubuntu 24.04 (WSL2), Python 3.12.3.

## Full required runner

Command: `source .venv-test/bin/activate && ./scripts/run-tests.sh`

Exit status: **0**. Raw stdout/stderr follows. Optional dashboard dependencies were not installed; the graph was checked separately.

```text

== Stage 1: android unit tests (pytest) ==
........................................................................ [ 39%]
....s.................................s................................. [ 79%]
.....................................                                    [100%]
179 passed, 2 skipped in 47.31s
[ok]   android-lab/lab test suite

== Source Lab engine tests (pytest) ==
........................................................................ [ 40%]
........................................................................ [ 81%]
................................                                         [100%]
176 passed in 14.22s
[ok]   source-lab/engine test suite

== Stage 2: android sample analysis pipeline (smoke) ==
Sample APK generated: /mnt/c/Users/RFKaya/Documents/Codex/2026-11-13/merhaba-arkada-lar-vize-hat-rlatmas/work/os-lab/android-lab/lab/scripts/vulnerable-test.apk (1921 bytes)
=== 📱 Comprehensive Android App Analyzer ===
Target: scripts/vulnerable-test.apk
[*] Scanning APK archive directly: scripts/vulnerable-test.apk

Analysis Complete:
  Security Score: 24/100 (Grade: F)
  Vulnerabilities: 6 total
    - Critical : 1
    - High     : 3
    - Medium   : 0
    - Low      : 2
  Hardcoded Secrets: 5

Data saved to: artifacts/security-scan/app-analysis.json
[*] Loading analysis data from JSON: artifacts/security-scan/app-analysis.json
=== 📄 Generating Multi-Format Security Reports ===

Reports Generated Successfully:
  🌐 Interactive HTML : artifacts/security-scan/security-report.html
  📝 Markdown Summary : artifacts/security-scan/security-report.md
  💾 CI/CD JSON Data  : artifacts/security-scan/security-report.json
[ok]   sample analysis + report generated in android-lab/lab/artifacts/security-scan

== Stage 3: shell script syntax (bash -n) ==
[ok]   all 70 shell scripts parse

== Stage 4: lat.md knowledge graph ==
[skip] lat not installed (npm i -g lat.md) — skipping graph check

== Stage 5: dashboard (typecheck + committed build is current) ==
[skip] dashboard dependencies not installed (cd dashboard && npm ci) — skipping

== Summary ==
4 passed, 0 failed, 2 skipped
All required checks passed.
```

## Knowledge graph

Windows, Node 24.13.0, lat.md 0.13.8. `lat check`: exit 0.

```text
Warning: No init version recorded — run lat init to set up agent hooks and configuration.
All checks passed in 237ms
```

## Native Windows focused tests

Python 3.14: `python -m pytest android-lab/lab/tests/test_ext_native_host.py -q --basetemp ../windows-test-run1 --tb=short`

```text
...........ss........s.... [100%]
23 passed, 3 skipped in 0.53s
```

## Real offline demonstration

These outputs were captured by running every command. The video replays the captured output, rather than claiming a desktop/live-browser recording. Exit 1 for risky input and exit 2 for scope refusal are expected.

### 01 / Yetkili, izole lab

```text
$ /mnt/c/Users/RFKaya/Documents/Codex/2026-11-13/merhaba-arkada-lar-vize-hat-rlatmas/work/os-lab/.venv-test/bin/python scripts/analysis/make_native_host_lab.py /tmp/pent18-proof-bjo94vml/owned-lab
Created owned offline fixtures: /tmp/pent18-proof-bjo94vml/owned-lab
No browser registration, network traffic or host execution.

[exit 0]
```

### 02 / Eklenti ve host manifesti

```text
$ cat /tmp/pent18-proof-bjo94vml/owned-lab/safe/extension/manifest.json /tmp/pent18-proof-bjo94vml/owned-lab/safe/host.json
{
  "manifest_version": 3,
  "name": "Owned PENT-18 lab fixture",
  "version": "1.0",
  "permissions": [
    "nativeMessaging"
  ]
}
{
  "name": "org.oslab.echo",
  "description": "Owned inert offline teaching fixture",
  "type": "stdio",
  "path": "/tmp/pent18-proof-bjo94vml/owned-lab/safe/inert_host.py",
  "allowed_origins": [
    "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"
  ]
}

[exit 0]
```

### 03 / Güvenli örneğin analizi

```text
$ /mnt/c/Users/RFKaya/Documents/Codex/2026-11-13/merhaba-arkada-lar-vize-hat-rlatmas/work/os-lab/.venv-test/bin/python scripts/analysis/ext_native_host.py /tmp/pent18-proof-bjo94vml/owned-lab/safe/extension --host /tmp/pent18-proof-bjo94vml/owned-lab/safe/host.json --lab-root /tmp/pent18-proof-bjo94vml/owned-lab --extension-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
PENT-18 | offline native-messaging audit
Coverage: 2 files, 1 hosts
[INFO] native-permission @ safe/extension/manifest.json: nativeMessaging permits a browser-to-local-process bridge
Summary: 1 info, 0 medium, 0 high
Static clues only; no host execution, browser registration or network access.

[exit 0]
```

### 04 / Sorunlu örneğin analizi

```text
$ /mnt/c/Users/RFKaya/Documents/Codex/2026-11-13/merhaba-arkada-lar-vize-hat-rlatmas/work/os-lab/.venv-test/bin/python scripts/analysis/ext_native_host.py /tmp/pent18-proof-bjo94vml/owned-lab/risky/extension --host /tmp/pent18-proof-bjo94vml/owned-lab/risky/host.json --lab-root /tmp/pent18-proof-bjo94vml/owned-lab --extension-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
PENT-18 | offline native-messaging audit
Coverage: 2 files, 1 hosts
[HIGH] caller-not-allowed @ risky/host.json: The analyzed extension's identity is absent from the host allowlist.
[HIGH] invalid-allowlist @ risky/host.json: Invalid allowed_origins entry; wildcard access is not a valid authorization.
[HIGH] writable-host-chain @ risky/inert_host.py: Host or containing lab directory is group/world writable.
[MEDIUM] dynamic-host @ risky/extension/background.js:3: Native host name is not a simple string literal; target unresolved.
[INFO] native-permission @ risky/extension/manifest.json: nativeMessaging permits a browser-to-local-process bridge
Summary: 1 info, 1 medium, 3 high
Static clues only; no host execution, browser registration or network access.

[exit 1]
```

### 05 / Yapılandırılmış JSON kanıtı

```text
$ /mnt/c/Users/RFKaya/Documents/Codex/2026-11-13/merhaba-arkada-lar-vize-hat-rlatmas/work/os-lab/.venv-test/bin/python scripts/analysis/ext_native_host.py /tmp/pent18-proof-bjo94vml/owned-lab/safe/extension --host /tmp/pent18-proof-bjo94vml/owned-lab/safe/host.json --lab-root /tmp/pent18-proof-bjo94vml/owned-lab --extension-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --json
{
  "schema_version": 1,
  "task": "PENT-18",
  "mode": "offline-static",
  "extension": {
    "manifest": "safe/extension/manifest.json",
    "manifest_version": 3,
    "native_permission": true,
    "optional_native_permission": false
  },
  "coverage": {
    "files_considered": 2,
    "supplied_hosts": 1,
    "source_matching": "lexical; comments/strings may match; computed calls may be missed",
    "binary_execution": false,
    "network_access": false,
    "limitations": [
      "No browser registration, message validation or effective privilege verification",
      "No signature verification, malware verdict or Windows ACL inspection"
    ]
  },
  "calls": [
    {
      "file": "safe/extension/background.js",
      "line": 2,
      "api": "connectNative",
      "host": "org.oslab.echo"
    }
  ],
  "hosts": [
    {
      "name": "org.oslab.echo",
      "manifest": "safe/host.json",
      "allowlist_kind": "allowed_origins",
      "caller_count": 1,
      "binary": {
        "inspected": true,
        "path": "safe/inert_host.py",
        "size": 154,
        "sha256": "173c7ca36d14827f52c55bf0d704d5b19410c5ae35ace768fc28d86da32ec5b7",
        "format": "script",
        "permissions": "POSIX mode bits"
      }
    }
  ],
  "findings": [
    {
      "rule": "native-permission",
      "severity": "info",
      "location": "safe/extension/manifest.json",
      "message": "nativeMessaging permits a browser-to-local-process bridge",
      "remediation": "Review both the extension and the native host's message validation."
    }
  ],
  "summary": {
    "info": 1,
    "medium": 0,
    "high": 0
  }
}

[exit 0]
```

### 06 / Kapsam dışına ret

```text
$ /mnt/c/Users/RFKaya/Documents/Codex/2026-11-13/merhaba-arkada-lar-vize-hat-rlatmas/work/os-lab/.venv-test/bin/python scripts/analysis/ext_native_host.py /tmp/pent18-proof-bjo94vml/owned-lab/safe/extension --lab-root /tmp/pent18-proof-bjo94vml/owned-lab/risky
analysis refused: path is outside the declared lab root

[exit 2]
```

### 07 / Otomatik regresyon testleri

```text
$ /mnt/c/Users/RFKaya/Documents/Codex/2026-11-13/merhaba-arkada-lar-vize-hat-rlatmas/work/os-lab/.venv-test/bin/python -m pytest android-lab/lab/tests/test_ext_native_host.py -q
..........................                                               [100%]
26 passed in 0.57s

[exit 0]
```

### 08 / Tam depo doğrulaması

```text
$ tail -18 ../full-tests-final.txt
Reports Generated Successfully:
  🌐 Interactive HTML : artifacts/security-scan/security-report.html
  📝 Markdown Summary : artifacts/security-scan/security-report.md
  💾 CI/CD JSON Data  : artifacts/security-scan/security-report.json
[ok]   sample analysis + report generated in android-lab/lab/artifacts/security-scan

== Stage 3: shell script syntax (bash -n) ==
[ok]   all 70 shell scripts parse

== Stage 4: lat.md knowledge graph ==
[skip] lat not installed (npm i -g lat.md) — skipping graph check

== Stage 5: dashboard (typecheck + committed build is current) ==
[skip] dashboard dependencies not installed (cd dashboard && npm ci) — skipping

== Summary ==
4 passed, 0 failed, 2 skipped
All required checks passed.

[exit 0]
```
