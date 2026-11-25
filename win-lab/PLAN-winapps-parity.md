# Windows Apps Lab — parity gaps against the macOS lab

The Windows Apps Lab (`console/winapps.py`) started from #225 as a read-only phase: a window
inventory, one window screenshot and a doctor probe. Since then #316 and #318 added UI Automation,
guarded input and streaming, #299 added the policy guard and its audit trail, and #319 the input
gate, so the whole safety section below is done. The macOS lab
([[ios-lab/PLAN-macos-mirror-roadmap.md]], [[ios-lab/PLAN-macos-agent-surface.md]]) is several phases
ahead. This file tracks every gap as a TODO so each can become its own small PR. The phase plan itself
is #211; the ids below are proposed `WINMIR-xx` names mapped to the macOS `MIR-xx` they mirror.

Status key: `[ ]` not started or only partly done (the note says what is left), `[x]` done.

## Already at parity

- [x] Window inventory with app, title, class, bounds and process (`macos_windows` ↔ `winapps_windows`)
- [x] Single-window screenshot as PNG (`macos_window_screenshot` ↔ `winapps_window_screenshot`)
- [x] Doctor/readiness probe (`GET /api/labs/winapps/doctor`)
- [x] Local-only mounting, never on public Pages; privacy table updated

## Control and safety (macOS MIR-11 / `_macos_control_gate`)

Everything in this section must exist **before** any input action is added. Do not ship input without it.

- [x] **WINMIR-11a Arm / disarm** with a live timeout and one owner: the control lock (`winapps_control_arm`, #316/#318);
      the input gate's `arm`/`disarm` are audited doors to it (#319)
- [x] **WINMIR-11b Panic stop**: disarms, ends every mirror stream and writes an audit row (`winapps_panic_stop`,
      `winapps_input_gate.panic_stop`); Windows has no deep-inspect sessions to close yet (see WINMIR-05)
- [x] **WINMIR-11c Locked-screen guard**: `winapps.desktop_locked()` (`OpenInputDesktop`) refuses input with
      `SCREEN_LOCKED` (#319); unit-tested only, not yet observed on a real lock screen or UAC prompt
- [x] **WINMIR-11d App allowlist**: `win-lab/winapps-policy.json`, default-deny for input even for a person (#319)
- [x] **WINMIR-11e Confirm flag**: every action needs an explicit preview confirmation (#316), and paste or Enter
      needs `confirm: true` at the gate as well (#319)
- [x] **WINMIR-11f Read-side title filter**: password managers, private browsing and banking hints are restricted
      for everyone, for reads and input alike; a broken policy restricts every window (#299, #319)

## Input (MIR-01)

- [x] **WINMIR-01a Click** (`winapps_control_click`, `SendInput`, with foreground and hit-point checks; #316)
- [x] **WINMIR-01b Double and right click, type, key, scroll** (`winapps_control_input`, #318)
- [ ] **WINMIR-01b' Paste**: the gate already treats paste as submit-class (#319), but there is no paste action yet
- [ ] **WINMIR-01c UIPI handling**: input to an elevated window from a standard-user console is silently dropped;
      detect it (the inventory already reports `elevated`) and refuse with a clear reason
- [ ] **WINMIR-01d Frame verification** (before/after capture) as in `_macos_audit` rows

## Element tree and actions (MIR-02, MIR-07, MIR-08, MIR-09, MIR-10)

- [x] **WINMIR-09 Native UI Automation helper**: decided on ctypes + COM UIA inside `winapps.py`, so it stays
      stdlib-only (#316)
- [x] **WINMIR-02a Element tree read** (`winapps_window_elements`, `winapps_search_elements`) with a revision token (#316)
- [ ] **WINMIR-02b Diff overlay** between two reads (`revision` query parameter)
- [ ] **WINMIR-07 Element read / set / perform** (`macos_ax_read`, `macos_ax_set`, `macos_ax_perform`) — armed and audited
- [ ] **WINMIR-10a Menu bar and focused element** (`macos_ax_menubar`, `macos_ax_focused`)
- [ ] **WINMIR-10b Child windows, dialogs and menus** (`macos_ax_windows`)
- [ ] **WINMIR-05 Deep-inspect sessions** with stable element ids (macOS uses Appium mac2; Windows: WinAppDriver or UIA ids)

## Display correctness and streaming (MIR-03, MIR-04)

- [ ] **WINMIR-03 Multi-monitor and mixed-DPI** capture and coordinate mapping: per-monitor DPI awareness landed
      (#318); mixed-DPI and multi-monitor are still *not verified* on hardware
- [x] **WINMIR-04 Streaming mirror**: a bounded multipart stream (`winapps_window_stream`) that the panic stop ends (#318)
- [ ] **Capture gaps**: occluded windows, GPU-accelerated Chrome/Edge, UWP and DRM/`WDA_EXCLUDEFROMCAPTURE` windows
      (PrintWindow returns black or stale pixels) — detect and say so instead of showing a blank frame

## Audit (MIR-06)

- [ ] **WINMIR-06 Session audit log**: daily `.jsonl` with coalescing and no titles (#299) and the control audit
      (#318) are done; thumbnails and a panel download are still missing
- [x] Every armed action, arm/disarm, panic stop and refusal writes a row; auditing never raises (#299, #318, #319)

## Agent surface (MIR-12) and platform integration

- [ ] **WINMIR-12a MCP tools**: the read-only `winapps_apps`, `winapps_screenshot`, `winapps_doctor`,
      `winapps_capabilities` and `winapps_audit` landed with no arm tool (#299); click and type tools behind the gate
      are still missing
- [ ] **WINMIR-12b `console/capabilities.json`** entries for the winapps lab (macOS has full per-action entries)
- [ ] **`labctl` / CLI wrapper** (`ios-lab/mac/macos-app.sh` equivalent); `winapps` has `labctl: None` today
- [ ] **Dashboard parity**: the element hotspots, action preview and confirm, arm/stop controls and the stream landed
      (#316/#318) and restricted windows are filtered (#299); the session panel, audit panel and a teaser for when
      the lab is not ready are still missing
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
