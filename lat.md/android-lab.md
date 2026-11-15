# android-lab

An Android application security and reverse-engineering lab built on
`budtmo/docker-android`, MobSF, mitmproxy, Frida and containerized RE tools. It
is a multi-container stack with several execution paths.

The lab root is [[android-lab]]; the runnable core is [[android-lab/lab]] with
compose [[android-lab/lab/docker-compose.yml]] and runbook
[[android-lab/lab/README.md]].

## Execution paths

The lab runs in several modes depending on host capabilities.

- **Dynamic (KVM):** the full emulator stack via [[android-lab/lab/docker-compose.yml]]
  — noVNC :6080, ADB :5555, MobSF :8000, mitmproxy :8080/:8081.
- **Static (KVM-free):** MobSF + mitmproxy + tools only, via
  [[android-lab/lab/docker-compose.win.yml]], for hosts without `/dev/kvm`.
- **Windows zero-admin:** a PowerShell orchestrator [[android-lab/lab/lab.ps1]]
  that provisions a VirtualBox/Podman userland lab without elevation; runbook
  [[android-lab/lab/README-WINDOWS.md]]. It is UTF-8 **with BOM** so it parses
  under Windows PowerShell 5.1, and defines `Send-VmKeyString` at script scope.
  `lab.ps1 win-preflight` runs [[android-lab/lab/scripts/win_preflight.py]]
  (PENT-23): a read-only, no-admin VT-x/Hyper-V/VirtualBox/WSL2/Podman
  readiness check that marks each fix admin or no-admin and recommends a lab
  model; scenarios replay from `tests/fixtures/win_preflight/`.
- **Ubuntu Server:** host provisioning via [[android-lab/lab/scripts/setup-ubuntu.sh]]
  and runbook [[android-lab/lab/README-UBUNTU.md]].

## Workflows

Two end-to-end workflows are wrapped by the [[android-lab/lab/Makefile]].

- **WF1 (static):** MobSF scan + JADX decompile + report —
  [[android-lab/lab/scripts/wf1-static.sh]].
- **WF2 (dynamic):** emulator + mitmproxy + Frida instrumentation —
  [[android-lab/lab/scripts/wf2-dynamic.sh]].

The orchestrator entry point is [[android-lab/lab/orchestrator.py]], with a web
console in [[android-lab/lab/web_ui.py]].

## Web console

[[android-lab/lab/web_ui.py]] is the standard-library server behind the
browser console for every lab, not just Android.

It serves the [[dashboard]] and a JSON API: the Android workbench (health,
logs with a `running` flag, clear logs, run, stop, devices, reports, staged
APKs, Frida hooks, upload and the `artifacts/` file server, which refuses paths
outside that folder) and the lab endpoints from [[console/oslab.py]] (host,
plan, start, jobs, cancel, config, monitor).

## Classic console

A self-contained fallback page with no build step, served at `/classic/` and
at `/` when no dashboard build exists.

It lives in [[android-lab/lab/web/index.html]], [[android-lab/lab/web/app.css]]
and [[android-lab/lab/web/app.js]] and follows the same qLar shell design for
the Android workbench pages.

## Analysis components

Reusable analysis scripts live in [[android-lab/lab/scripts]].

They include the deep analyzer [[android-lab/lab/scripts/app_analyzer.py]], the
report generator [[android-lab/lab/scripts/app_reporter.py]], the MobSF client
[[android-lab/lab/scripts/mobsf_client.py]], the secret scanner
[[android-lab/lab/scripts/secret_scanner.py]], the agentic Frida-hook generator
[[android-lab/lab/scripts/agentic_engine.py]] and the APK patcher
[[android-lab/lab/scripts/apk_patcher.py]]. Prebuilt Frida hooks are in
[[android-lab/lab/hooks]].

### Pinning detector

[[android-lab/lab/scripts/pinning_detector.py]] (PENT-11) classifies how an APK or decompiled
tree pins TLS, statically, before any dynamic work.

It decodes binary manifest and `res/xml` Network Security Config files itself (counting `<pin-set>`
configs as strong evidence only when matched to a manifest `@xml/<name>` resource path, and
deduplicating identical copies), then scores OkHttp `sha256/` and `sha1/` pin literals, custom
TrustManager key checks, TrustKit and cross-platform plugins, Flutter, native `.so` verification and
bundled certificates. Generic TLS API usage and library-only class presence stay `low` confidence.
Scans enforce per-file and aggregate file/byte limits, expose coverage metadata (`scan_complete`,
`skipped`, `skipped_count`, `scan_truncated`), return `incomplete_scan` instead of `none_detected`
when inputs were skipped, escape untrusted paths in Markdown, and publish JSON + Markdown report
pairs atomically with output-directory exclusion in non-`--json` runs. Output is a ranked method
list with evidence, a `pinned` / `likely_pinned` / `possible` / `none_detected` /
`incomplete_scan` status, weak-validation flags and the matching lab hook as next step. It reads
local files only (`make pinning APK=`); tests are in
[[android-lab/lab/tests/test_pinning_detector.py]].

### Policy-driven Interceptor runner

[[android-lab/lab/hooks/tamper_policy.js]] and [[android-lab/lab/scripts/tamper_runner.py]]
(PENT-07) drive policy-based Frida `Interceptor` hooks (`onEnter` argument inspection
and tampering, `onLeave` return-value inspection and `retval.replace`) against the
deterministic lab authentication harness [[android-lab/lab/tests/targets/hedef.c]].

A fail-closed scope guard refuses external targets, symlink escapes, and unauthorized
functions before any instrumentation runs. The runner supports both live Frida injection
and an offline deterministic mode for headless CI, verified against golden-file fixtures
in [[android-lab/lab/tests/test_tamper_runner.py]].

## Tests

The lab ships a pytest suite in [[android-lab/lab/tests]].

It covers the analyzer, reporter, MobSF client, secret scanner, pinning detector, patcher, flow
parser, agentic engine and web UI, and runs in CI — see
[[tooling#Local test runner]].
