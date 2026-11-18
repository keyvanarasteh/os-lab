# PENT-10 — Electron App Unpacker & Injection-Point Mapper

| Field | Value |
|---|---|
| Task | PENT-10 (MYO062) |
| Author | Mehmet Berkle Yavuz (`Berrkle`) |
| Branch | `feat/electron-injection-mapper` (base `d7cfc18`) |
| Deliverables | [`source-lab/engine/source_lab/electron/inject_map.py`](../../../source-lab/engine/source_lab/electron/inject_map.py) (v1.0.1), [`__main__.py`](../../../source-lab/engine/source_lab/electron/__main__.py), [`__init__.py`](../../../source-lab/engine/source_lab/electron/__init__.py), tests [`tests/test_electron_inject.py`](../../../source-lab/engine/tests/test_electron_inject.py), this report |
| Reservation | [`reservations/PENT-10.json`](../../../reservations/PENT-10.json) |
| Demo video | `https://drive.google.com/file/d/1X-joayZ28onqNDNmInpn6esQ4nwoD7L5/view` — see §6 |

## 1. Scope

`source_lab.electron` is a **static, offline** unpacker and injection-point mapper for
Electron applications. It takes either an app directory or an `app.asar` archive, unpacks
it, finds the main / preload / renderer entry points, and reports the configuration and
code patterns that let a renderer-side problem (an XSS, a malicious remote page, a tampered
local resource) reach the main process or Node — the lab Electron injection case this
reproduces. Standard library only; Python 3.11+.

- **Unpack.** `app.asar` is parsed with the repo's own Chromium-pickle reader
  (`source_lab.sourcemap.archives.asar`), so no `asar` npm tool and no disk extraction are
  needed. Path-traversal members, symlinks and the entry/size caps enforced by that reader
  are inherited. Loose files and an `app.asar.unpacked` overlay are read from disk.
- **Offline & read-only.** Application code is read as text, never executed. Host names are
  classified lexically — no DNS lookup, nothing is contacted. The tool never writes inside
  the analyzed tree and never follows symlinks.
- **Bounded & linear.** Each file is capped at 2 MiB, the walk at `--max-files` (default
  4000) and 64 MiB total; every scan is linear-time regex over the text.
- **Sanitized output.** Control, bidi and zero-width characters in any app-supplied string
  are escaped (`\uXXXX`) in text and Markdown output, so a crafted filename or snippet can't
  corrupt the console.
- **Authorized targets only.** The report repeats that findings are *potential* injection
  points derived from source text, not observed behaviour, and that the tool is for apps you
  own or are authorized to assess.

## 2. What it reports

Each finding carries a stable `id`, severity, the affected surface, `file:line`, the code
snippet, a rationale and a concrete fix.

- **BrowserWindow / `webPreferences`:** `nodeIntegration`, `contextIsolation`, `sandbox`,
  `webSecurity`, `allowRunningInsecureContent`, `enableRemoteModule`,
  `nodeIntegrationInWorker`/`InSubFrames`, `experimentalFeatures`, `webviewTag`; a window
  whose `webPreferences` never sets `contextIsolation` is reported as info.
- **Navigation:** `loadURL` to a non-local `http(s)` origin, and remote content loaded with
  no `setWindowOpenHandler` / `will-navigate` guard.
- **Preload bridge:** `contextBridge.exposeInMainWorld` that hands the renderer the raw
  `ipcRenderer`, `require`, `child_process` or `fs`, and `window.X = require(...)`.
- **IPC → shell:** a file with `ipcMain` handlers plus a concatenated `child_process`
  `exec`/`spawn` (command-injection bridge).
- **Dynamic code & CSP:** `eval` / `new Function`, `shell.openExternal` with a non-literal
  argument, and renderer HTML with no CSP or an `unsafe-eval` / `unsafe-inline` CSP.

Exit code: `0` = complete scan with no high/medium findings, `1` = high/medium findings **or an
incomplete scan** (a cap was hit, or a member was truncated, missing or unreadable; the report
then carries `"complete": false`), `2` = usage/input error.

## 3. Usage

```
python3 -m source_lab.electron <app_dir | app.asar> [--format text|md|json] [-o OUT] [--max-files N]
```

## 4. Verification

A deliberately weak demo app (an `app.asar` with `nodeIntegration:true`,
`contextIsolation:false`, `webSecurity:false`, a preload that exposes raw `ipcRenderer`
and `window.fs = require('fs')`, an IPC handler shelling out with string concatenation, a
remote `loadURL`, an `eval` renderer and a CSP-less page) and a hardened variant were run:

```
$ python3 -m source_lab.electron demo/vuln-app
electron: True   asar: resources/app.asar   source files: 6
findings: 6 high, 3 medium, 2 low, 0 info
[HIGH] nodeIntegration enabled                       main.js:7
[HIGH] contextIsolation disabled                     main.js:8
[HIGH] webSecurity disabled                          main.js:10
[HIGH] IPC handler shells out with a concatenated command   main.js:16
[HIGH] contextBridge exposes the raw ipcRenderer object     preload.js:2
[HIGH] require() attached to window in preload       preload.js:3
[MED ] sandbox disabled                              main.js:9
[MED ] remote content loaded via loadURL             main.js:14
[MED ] dynamic code execution (eval/new Function)    renderer.js:2
[LOW ] renderer HTML has no Content-Security-Policy  index.html:1
[LOW ] remote navigation without a navigation guard  main.js:14
EXIT=1

$ python3 -m source_lab.electron demo/secure-app
findings: 0 high, 0 medium, 0 low, 1 info
EXIT=0
```

The `vuln-app` run demonstrates the unpacker reading six source members from inside
`resources/app.asar`; the hardened run shows a correctly scoped `contextBridge` reported as
info only (never dropped silently) and a clean exit.

## 5. Tests

`tests/test_electron_inject.py` has 20 offline tests: the 5 original ones (vulnerable asar
flags every injection point; hardened app has zero high/medium and keeps the scoped bridge
as info; a directory target with an embedded `app.asar` plus a loose file; output formats
and CLI exit codes; determinism and control-char escaping) and 15 regression tests added
after review (weak CSP with quoted tokens and either attribute order; `.cjs` preloads;
malformed `package.json`; extensionless/directory `main`; incomplete scans fail; symlinks
and symlinked targets; truncated archives; `.asar.unpacked` overlay; `node_modules` inside
archives; generic IPC forwarders; dynamic `openExternal`; FIFOs; unreadable archives;
packaged-manifest priority). Every fixture is synthesized in `tmp_path` using the real asar pickle layout —
nothing is executed or contacted.

```
$ cd source-lab/engine && python3 -m pytest tests -q
196 passed
```

`./scripts/run-tests.sh`'s Source Lab engine stage passes. (Two unrelated suites —
`android-lab` console tests that assert macOS host behaviour, and `cleanup-lab/engine` —
fail on a fresh master checkout in a Linux-only clean room and are untouched by this change;
they pass in the lab's own environment.)

## 6. Demo video

A 2–4 min screen recording: the weak app flagged (exit 1) and the hardened app clean
(exit 0), showing run → output → verification. Uploaded as an unlisted link
(`https://drive.google.com/file/d/1X-joayZ28onqNDNmInpn6esQ4nwoD7L5/view`); no personal paths or unauthorized targets on screen.

## 7. Review fixes (v1.0.1)

After review the analyzer was fixed for: weak CSP not detected, `.cjs`/`.mjs` preloads
skipped, crash on malformed `package.json`, valid `main` entries not resolving, and
incomplete scans passing CI. The Sourcery findings on symlink boundaries, truncated and
unpacked archives, shared scan budgets, `node_modules` inside archives, generic IPC
forwarders, dynamic `openExternal` URLs, FIFOs, archive I/O errors, packaged-manifest
priority and report escaping were fixed as well. Every review thread was answered as
fixed or out of scope with a reason.

## 8. Limitations

Static analysis sees configuration and literal patterns, not values computed at runtime: a
`webPreferences` object assembled dynamically, a `loadURL` built from a variable, or a flag
set through a helper are not resolved; aliased `eval`, cross-file navigation guards and
commented-out `webPreferences` values need a real JS parser and are out of scope. The tool reports the surface to review, not a proof
of exploitability, and is scoped to Electron apps you own or are authorized to assess.
