# Windows Apps Lab native app mirror — verification

Date: 2026-11-16 (revision of the 2026-11-15 run)
Host: Microsoft Windows 11 Pro, 10.0.26300, x64
Shell: Windows PowerShell 5.1.26100.9818
Node.js: v24.20.0
Privilege used: standard user (`elevated=false`, read from the process token)
WSL used by this feature: no

This feature is read-only. It mirrors one visible desktop window; it does not
start or stop processes, does not read process command lines and does not send
input. Window titles are private and are never committed; only application
names and counts appear below.

## 1. Native collector

```powershell
python console/winapps.py
python console/winapps.py --doctor
```

Observed on this host, with real applications open:

- Before the revision the inventory returned 6 windows. Three of them were
  DWM-cloaked (`DwmGetWindowAttribute(DWMWA_CLOAKED) != 0`): suspended UWP
  frames that Win32 reports as visible but that are not on screen.
- After the revision it returns **3** windows (Discord, Explorer, Windows
  Terminal), all with `cloaked=0`.
- `--doctor` observed: `available=True, desktop=True, sessionId=1,
  elevated=False, capture=True, windows=3`. `elevated` comes from the real
  process token; the earlier revision returned a constant `False`.

## 2. Window capture

For each of the 3 listed windows the PNG returned by
`winapps_window_screenshot` was decoded with an independent reader: signature,
every chunk CRC, IHDR (`8-bit RGBA`), decompressed length equal to
`height * (1 + width * 4)`, and the alpha bytes sampled.

Observed: all 3 decoded without error, every CRC matched, every sampled alpha
byte was 255, and each image contained between 17 and 82 distinct colours
(not a blank surface). Capture took 10–28 ms per window in this single run
(166–480 ms for the previous revision, which re-enumerated every window and
converted pixels in a Python loop).

This shows the PNG is well formed and non-blank for these windows. It does not
prove capture of every window kind: see section 7.

Resource and edge-case checks on the same host (`GetGuiResources` and
`GetProcessHandleCount` before and after):

- 280 captures, 300 inventories and 300 stale-id refusals left the process at
  GDI objects 0 → 0 and handles 125 → 125, so no handle or GDI leak was observed.
- Window ids `0`, `-5`, `4294967296`, a 23-digit number, an Arabic-Indic digit and
  `1e3` were all refused with a `WinAppError`, never an unhandled exception.
- `GetThreadDpiAwarenessContext` reports per-monitor-v2 awareness after import.

## 3. Real browser against the real backend

`python android-lab/lab/web_ui.py 5077` was started and `/labs/winapps/` was
opened in Chromium through Playwright, with no mocks.

Observed: the page listed 3 windows and the mirror `<img>` was visible at
616 × 698 px for a 316 × 358 px window (same aspect ratio, capped at 70% of the
viewport height). The previous revision's own build left the mirror `<img>`
**hidden** (zero-height container) even when a screenshot arrived; the new E2E
test below fails against that build and passes against this one.

## 4. Backend tests

```powershell
python -m pytest android-lab/lab/tests/test_winapps.py android-lab/lab/tests/test_web_ui.py -q
```

Observed: `test_winapps.py` 18 passed. Together with `test_web_ui.py`:
**37 passed, 1 failed**. The failure is
`test_lab_start_requires_a_previewed_plan` (expects 409, gets 400). It fails the
same way on an unmodified checkout of `origin/master` on this host, so it is not
caused by this change.

`test_winapps.py` fakes every Win32 call and patches `sys.platform`, so it does
not depend on the host OS. It covers: non-Windows inventory and screenshot
refusal, invalid and stale window ids, no-caption / tool-window / shell-class /
hidden / minimized / empty-rect exclusion, cloaked exclusion, elevation true /
false / unknown, the oversized-window refusal, a PNG encoder round trip (CRC,
IHDR, filter byte, BGRA→RGBA, opaque alpha) and `doctor()` with and without an
interactive desktop. `test_web_ui.py` covers the inventory, screenshot (PNG
and 400 for a stale window) and doctor endpoints, and 501 when the module is
missing. These tests were run only on Windows; the Linux/macOS behaviour is
the faked-platform path, not a run on those systems.

## 5. Dashboard

From `dashboard/`:

```powershell
npm run check          # tsc --noEmit: passed
npm run test:i18n      # 2509 keys match across 7 locales; no new untranslated TSX strings.
npm run build          # 514 page(s) built
npx playwright test winapps.spec.ts   # 4 passed
npx playwright test                   # 65 passed, 1 failed, 1 skipped
```

The one failure is `how-to-use.spec.ts` "Workspace prompt includes task…". On
this host `core.autocrlf=true` checks sources out as CRLF while a `<textarea>`
value is LF-normalized, so the compared prompts differ in line endings only. It
is unrelated to this change; it was not re-run on `master`.

`winapps.spec.ts` checks: the mirror is painted (visible, non-zero, 4:3 for a
320 × 240 window); the selected window and size are shown; an elevated window is
marked and a failed capture is reported; the unavailable state is explicit; no
inventory request is made on a non-Windows host; no "Arm control" button exists.
Public-Pages mounting is gated in code by `PUBLIC_SITE_MODE !== "pages"` and is
**not** covered by an automated test here.

## 6. Desktop runtime integrity

From `app/`: `npm run test:stage` → 8 tests, 0 failed. `console/winapps.py` is
in both the staging and bundle integrity lists. `cargo test` was not re-run for
this revision (no Rust change since the previous run).

## 7. Agent safety layer (WINMIR-11d, 11f, 06, 12a, 12b)

What was added: `console/winapps_guard.py` (policy, restricted windows, audit and the only door
the web endpoints and the MCP server use), read-only `winapps_*` MCP tools and a `lab-winapps`
capabilities entry.

### Real-host check (Windows 11, standard user)

A script started a real stdio session with `python console/mcp_server.py` against this desktop. It
owned two windows of its own (`python`, titles `winapps-demo allowed` and
`winapps-demo [InPrivate]`) and used a temporary policy file allowing only `python`. No other
application was touched, and other windows' titles were not printed.

Observed, re-run on the tree after merging current `origin/master` (that merge only moved the Win32
structure definitions in `console/winapps.py` out of the Windows-only block, with no behaviour change):

- `serverInfo.name` was `os-lab-windows`; the winapps tools were `winapps_apps`,
  `winapps_screenshot`, `winapps_capabilities`, `winapps_doctor`, `winapps_audit`. No arm or input tool.
- The person's view listed 6 windows. The `[InPrivate]` demo window was flagged
  `private-window` and its title replaced by `(restricted)`.
- The agent's `winapps_apps` returned exactly 1 window (`python`) and `withheld: 5`. The restricted
  window was not in it.
- `winapps_screenshot` of the allowlisted window returned a PNG (valid signature, 4,694 bytes).
- The restricted window gave `RESTRICTED_WINDOW`; a window of an app that is not on the allowlist
  gave `APP_NOT_ALLOWED`; window id `0` gave `INVALID_WINDOW`. All were `isError`.
- `winapps_doctor`: `desktop=True, elevated=False, capture=True`.
- The audit held 6 rows (list, screenshot, three refusals, doctor) and the daily JSONL file had 6
  lines; neither contained a window title.

Not verified on a real host: a real password manager or banking page (the restricted case used a
title hint on a window this script owned), and an elevated window.

### Tests

```text
pytest test_winapps.py test_winapps_guard.py test_mcp_winapps.py : 116 passed
pytest android-lab/lab/tests (whole backend)                     : 583 passed, 5 failed, 17 skipped
app: npm run test:stage                                          : 9 passed
dashboard: tsc, test:i18n (2767 keys, 7 locales), build (532 pages)
playwright winapps.spec.ts                                       : 8 passed
playwright (full suite)                                          : 70 passed, 23 failed, 1 skipped
```

The 5 backend failures (`test_apk_patcher`, `test_cleanup_console`, two in `test_macos_parity`,
and `test_lab_start_requires_a_previewed_plan`) do not involve this lab and fail on this host
without this change. Re-run after merging current `origin/master` into this branch: the earlier
failures caused by the Windows Apps Lab itself (a missing `lab-winapps` capability item and two stale
lab-state expectations) were fixed on `master` in the meantime, and the merge kept that version.

The 23 Playwright failures are all in `health-and-content.spec.ts` and `how-to-use.spec.ts`. The same
suite run on an unmodified copy of this branch's base commit fails 23 as well (21 identical tests; two
differ in opposite directions because this host checks files out as CRLF while the copy is LF). No
failure is in `winapps.spec.ts`.

Not run: `cargo test` for the runtime bundle list (only the staging test ran), and `lat check` (the
CLI is not installed on this host).

### Limits of this layer

- The allowlist binds the MCP path. The local HTTP address serves the person's panel, so an agent
  that can run commands on this machine can still request unrestricted windows there. This guards
  against agent mistakes, not a hostile local user; a secret the agent does not hold on that address
  is a later phase.
- The restricted-window filter reads process names and titles only. A banking page titled
  "Welcome" is not caught unless a hint is added to the policy file.
- A title can change during a capture; the pixels are discarded if it became restricted, but a
  window that changes right after the check is still seen.
- In a packaged install the lab folder may be read-only: point `OSLAB_WINAPPS_POLICY` and
  `OSLAB_WINAPPS_AUDIT_DIR` at writable paths, or the audit stays in memory.
- The capabilities entry's new English text is not yet translated into the 7 locales.
- The audit trail is per process (the HTTP console and each MCP server keep their own rows and
  `seq` numbers, appending to one daily file) and the file keeps only a coalesced row's first count.
- Added after an automated review of this PR: the post-capture check and the doctor probe use the
  current policy and window; unknown policy keys are an error and valid restrictions survive an
  invalid allowlist; the agent's audit view hides other audiences and refusal app names; agent
  captures are capped at 4K and every capture has a 15 s deadline; the panel clears the previous
  window's image when the selection changes and no longer starves a slow capture.

## 8. Input gate (WINMIR-11a, 11b, 11c, 11d, 11e)

`console/winapps_input_gate.py` decides whether one input action may run and never sends input
itself; this change adds no `SendInput`. Observed on this host (Windows 11, standard user) with
two windows this script owned (`python`, one titled `[InPrivate]`) and a policy allowing only
`python`:

- `desktop_locked()` returned `False` on the unlocked desktop.
- A click while disarmed: `NOT_ARMED`. After `arm panel-1` (30 s): a second owner got `INPUT_BUSY`.
- A click on the allowlisted window was authorized; on the `[InPrivate]` window `RESTRICTED_WINDOW`;
  on another application's window `APP_NOT_ALLOWED`.
- A paste without confirmation: `CONFIRM_REQUIRED`; with `confirm=True` it was authorized.
- The panic stop disarmed (epoch 1) and the next click was `NOT_ARMED`.
- The audit held arm, authorization and refusal rows with codes; no window title and no owner name.

```text
pytest test_winapps_input_gate.py                               : 60 passed
pytest test_winapps*.py test_mcp_winapps.py test_web_ui.py      : 210 passed
pytest android-lab/lab/tests (whole backend)                    : 764 passed, 2 failed, 73 skipped
app: npm run test:stage                                         : 9 passed
```

Not verified on a real host: a locked screen or UAC prompt (the lock check is unit-tested with a
fake `OpenInputDesktop` only), and any real input, because none is sent. The gate is a guard
against mistakes, not a hostile local user: a process that can reach the local HTTP address with
the `X-OSLab` header can arm it.

The 2 backend failures (`test_apk_patcher`, `test_cleanup_console`) do not involve this lab and fail
on this host without this change.

## 9. Scope and limits

- This proves the read-only phase: window inventory, window capture and a
  doctor probe. UIA hotspots, previewed clicks, typing and armed control are
  follow-up phases (`WINMIR-02…06`).
- Capture uses `PrintWindow` with `PW_RENDERFULLCONTENT`. Not verified here:
  elevated windows (no elevated window was available to a standard-user
  session; an elevated token that Windows refuses to report is returned as
  `elevated: null`, not guessed), Chrome/Edge and UWP content, occluded
  windows, mixed-DPI multi-monitor setups and Windows 10. UAC secure-desktop
  prompts cannot be captured at all.
- Minimized windows are not listed; they have no on-screen surface.
- The CI jobs `release-win` and `release-linux` fail with "updater signing key
  is missing (TAURI_SIGNING_PRIVATE_KEY)". That is a missing repository secret
  for the Tauri release build, not a test failure in this change.
- No process was started or terminated by this feature or its tests, and no
  host data from this verification was sent off-machine.
