# Windows Apps Lab — parity gaps against the macOS lab

The Windows Apps Lab (`console/winapps.py`, landed from #225) implements only the read-only phase
(`WINMIR-01`): a window inventory, one window screenshot and a doctor probe. The macOS lab
([[ios-lab/PLAN-macos-mirror-roadmap.md]], [[ios-lab/PLAN-macos-agent-surface.md]]) is several phases
ahead. This file tracks every gap as a TODO so each can become its own small PR. The phase plan itself
is #211; the ids below are proposed `WINMIR-xx` names mapped to the macOS `MIR-xx` they mirror.

Status key: `[ ]` not started, `[x]` done.

## Already at parity

- [x] Window inventory with app, title, class, bounds and process (`macos_windows` ↔ `winapps_windows`)
- [x] Single-window screenshot as PNG (`macos_window_screenshot` ↔ `winapps_window_screenshot`)
- [x] Doctor/readiness probe (`GET /api/labs/winapps/doctor`)
- [x] Local-only mounting, never on public Pages; privacy table updated

## Control and safety (macOS MIR-11 / `_macos_control_gate`)

Everything in this section must exist **before** any input action is added. Do not ship input without it.

- [ ] **WINMIR-11a Arm / disarm** with a live timeout and one owner (`macos_control_arm`, `_MACOS_CONTROL`)
- [ ] **WINMIR-11b Panic stop** that disarms, closes sessions and writes one audit row (`macos_panic_stop`)
- [ ] **WINMIR-11c Locked-screen guard** (`macos_screen_locked`); Windows: session lock / secure desktop detection
- [ ] **WINMIR-11d App allowlist** (`ios-lab/mac/agent-apps.json`); Windows: process or AUMID allowlist file, empty = refuse input
- [ ] **WINMIR-11e Confirm flag** for submit/overwrite-class input even while armed (`_MACOS_CONFIRM_KINDS`)
- [ ] **WINMIR-11f Read-side title filter**: password managers, banking and private-browsing windows are listed
      and captured today with no filter (the macOS side gates input, not reads — decide on both)

## Input (MIR-01)

- [ ] **WINMIR-01a Click** (`macos_control_click`); Windows: `SendInput`
- [ ] **WINMIR-01b Double and right click, type, key, paste, scroll** (`MacInputKind`)
- [ ] **WINMIR-01c UIPI handling**: input to an elevated window from a standard-user console is silently dropped;
      detect it (the inventory already reports `elevated`) and refuse with a clear reason
- [ ] **WINMIR-01d Frame verification** (before/after capture) as in `_macos_audit` rows

## Element tree and actions (MIR-02, MIR-07, MIR-08, MIR-09, MIR-10)

- [ ] **WINMIR-09 Native UI Automation helper** (the macOS keystone is `ios-lab/mac/ax-helper.swift`). Options: a small
      .NET/C# helper using UIA, or ctypes + COM; `winapps.py` is stdlib-only today, so decide and document
- [ ] **WINMIR-02a Element tree read** (`macos_window_elements`) with a revision token
- [ ] **WINMIR-02b Diff overlay** between two reads (`revision` query parameter)
- [ ] **WINMIR-07 Element read / set / perform** (`macos_ax_read`, `macos_ax_set`, `macos_ax_perform`) — armed and audited
- [ ] **WINMIR-10a Menu bar and focused element** (`macos_ax_menubar`, `macos_ax_focused`)
- [ ] **WINMIR-10b Child windows, dialogs and menus** (`macos_ax_windows`)
- [ ] **WINMIR-05 Deep-inspect sessions** with stable element ids (macOS uses Appium mac2; Windows: WinAppDriver or UIA ids)

## Display correctness and streaming (MIR-03, MIR-04)

- [ ] **WINMIR-03 Multi-monitor and mixed-DPI** capture and coordinate mapping — listed as *not verified* in `win-lab/VERIFY.md`
- [ ] **WINMIR-04 Streaming mirror** (MJPEG, `macos_window_stream`); the panel polls one PNG every 3 s today
- [ ] **Capture gaps**: occluded windows, GPU-accelerated Chrome/Edge, UWP and DRM/`WDA_EXCLUDEFROMCAPTURE` windows
      (PrintWindow returns black or stale pixels) — detect and say so instead of showing a blank frame

## Audit (MIR-06)

- [ ] **WINMIR-06 Session audit log** (`_macos_audit`, daily `.jsonl`, thumbnails) with panel view and download
- [ ] Every armed action, arm/disarm, panic stop and session open/close writes a row; auditing must never raise

## Agent surface (MIR-12) and platform integration

- [ ] **WINMIR-12a MCP tools** mirroring `macos_apps`, `macos_get_app_state`, `macos_screenshot`, `macos_click`,
      `macos_type` in `console/mcp_server.py` — with no arm tool, exactly like macOS
- [ ] **WINMIR-12b `console/capabilities.json`** entries for the winapps lab (macOS has full per-action entries)
- [ ] **`labctl` / CLI wrapper** (`ios-lab/mac/macos-app.sh` equivalent); `winapps` has `labctl: None` today
- [ ] **Dashboard parity**: element picker overlay, action menu, session panel, audit panel (`macos-app-mirror.tsx`
      is ~900 lines; `winapps-app-mirror.tsx` is ~150), plus a teaser component when the lab is not ready
- [ ] **Bonus tasks page** (`macos-lab-tasks.tsx`) for the Windows lab
- [ ] **Scope guard**: route app targets through `scope_guard.py` the way macOS input does

## Verification and CI

- [ ] **Run the winapps tests on a real Windows runner in CI.** Today they are mocked unit tests; the real-desktop
      checks were manual on one machine (Windows 11, standard user)
- [ ] Verify: Windows 10, elevated windows, Chrome/Edge/UWP content, occluded windows, mixed-DPI, public-Pages gating
- [ ] A Windows packaging check that the staged runtime contains `console/winapps.py` (the `release-win` build)
- [ ] Re-run `cargo test` for the runtime bundle list; `win-lab/VERIFY.md` notes it was not re-run

## Order

1. WINMIR-11 (arm, panic stop, lock, allowlist, confirm) and WINMIR-06 (audit) — safety before capability
2. WINMIR-09 (UIA helper) then WINMIR-02 (tree) — read-only first
3. WINMIR-01 (input) behind the gate, then WINMIR-07 / 10 / 05
4. WINMIR-03 / 04 (display correctness, streaming) and WINMIR-12 (agent surface)
