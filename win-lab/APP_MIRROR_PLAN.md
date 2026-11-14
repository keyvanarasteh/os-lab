# Windows app mirror — plan (draft)

Bring the macOS Lab's app mirror abilities to **Windows applications**: a live,
draggable mirror of a real app window with its UI Automation (UIA) tree as
numbered hotspots, clicks and typing that preview first, and an armed control
mode that disarms itself. The guardrails are identical to
[[ios-lab/mac/macos-app.sh]] and the macOS mirror — read-only endpoints by
default, preview → confirm → job for anything that touches input, explicit
opt-in for immediate clicks, localhost-only POSTs behind `X-OSLab: 1` + the
Host guard.

Status: **plan only** — nothing here is implemented yet. Track the tasks in
the Contribute list (`WINMIR-01…06`, see `dashboard/src/views/win-lab-tasks.tsx`).

## Where it can run: two host paths

### Path A — native Windows host (console runs on Windows)

The console (Python) has direct access to the desktop, exactly like the macOS
Lab on a Mac. Everything is stdlib ctypes plus one user-folder package:

| Ability | macOS (shipped) | Windows (planned) |
|:--|:--|:--|
| Window list | CoreGraphics via ctypes | `user32.EnumWindows` + `GetWindowTextLengthW` / `GetClassNameW` / `GetWindowRect` / `IsWindowVisible` / `GetWindowThreadProcessId` via ctypes |
| Window capture | `screencapture -l` | `user32.PrintWindow` with `PW_RENDERFULLCONTENT` into a DIB via `gdi32.BitBlt` (ctypes; DirectComposition windows fall back to `Windows.Graphics.Capture` through a small PowerShell helper) |
| Element tree | System Events (AppleScript) | **UIA** through `pywinauto` (IUIA backend) installed into `~/.oslab/pywinauto` — the user-folder pattern of `~/.oslab/appium`, no global site-packages |
| Input | CGEvent via JXA | `user32.SendInput` via ctypes (mouse move/down/up, keyboard scan codes with `KEYEVENTF_SCANCODE`, `VK` codes for special keys) |
| Activation | System Events `frontmost` | `SetForegroundWindow` / `AttachThreadInput` dance (see pitfalls) |

Endpoint and action naming follows the macOS mirror: `/api/labs/winapps/apps`,
`…/apps/<hwnd>/screenshot`, `…/apps/<hwnd>/elements`, `POST
/api/labs/winapps/click` (armed only), and a `winapps-click` family of
previewed actions.

### Path B — Windows guest in Docker (Linux/KVM host)

The Windows Lab's guest is a VM; the Linux console cannot reach its desktop
directly. The plan adds a small **guest agent**:

- Provisioned through the existing hooks: `win-lab/oem` (`C:\OEM` +
  `install.bat`) copies the agent from `win-lab/shared` on first boot; an
  update path re-copies through the `Z:` shared drive.
- The agent is a single-file Python (embedded distribution, no installer) or
  PowerShell script that serves the same three read-only operations and the
  guarded input operation, bound to the guest's **loopback only**.
- The host console proxies to it through the compose network with the same
  guard set the web console uses (`X-OSLab: 1` header + a per-session token
  from the preview), never exposing the guest port beyond localhost on the
  host. RDP stays the interactive path; the agent is automation-only.
- Honest limitation: the agent sees the guest desktop it runs in. UAC secure
  desktop prompts are **not** automatable from either path — the UI reports
  them as unavailable rather than pretending.

## Windows-specific honesty rules (from day one)

- **Elevation**: a non-elevated console cannot read UIA or post input to
  elevated windows. The window list marks elevated windows, hotspots on them
  are disabled with a reason, and `doctor` prints the console's elevation
  state instead of hiding the problem.
- **DPI**: `SetProcessDpiAwareness(PER_MONITOR_AWARE_V2)` before any capture
  or coordinate math; hotspots stay in physical points end to end (the Retina
  lesson from macOS, mirrored).
- **Focus**: `SetForegroundWindow` fails across processes; use the
  `AttachThreadInput` + `BringWindowToTop` sequence or the UIA
  `SetForeground` fallback — and say so in the preview effects ("brings the
  app to the front").
- **Secure input fields**: password boxes expose no text through UIA; the
  tree marks them, and typing into one requires the same explicit confirm as
  Return in the macOS plan.
- **Defender/AV**: `SendInput` from a service context is a classic trigger —
  the agent path documents that the guest agent must run as the logged-in
  user, never as SYSTEM.

## Phases and todos

### Phase 1 — read-only mirror (native path) → `WINMIR-01`

- [ ] `_win_windows()` ctypes bindings: enumerate top-level visible windows, owner pid/name
      (`QueryFullProcessImageNameW`), title, class, rect; filter tool windows like macOS filters
      `kCGWindowLayer != 0`
- [ ] `GET /api/labs/winapps/apps` (endpoint shape mirrors the macOS one; lab id decision below)
- [ ] `GET /api/labs/winapps/apps/<hwnd>/screenshot` — PrintWindow with
      `PW_RENDERFULLCONTENT`, PNG encode via a minimal stdlib encoder (zlib + chunks, ~40 lines)
- [ ] Per-monitor DPI awareness set once in the console process
- [ ] Doctor: desktop session present? console elevation? capture probe result
- [ ] `WinAppPanel` reuses `MacAppPanel`'s component structure (shared props, new labels)

### Phase 2 — UIA hotspots + previewed input → `WINMIR-02`, `WINMIR-03`

- [ ] `~/.oslab/pywinauto` venv bootstrap script (`win-lab/scripts/win-uia-bootstrap.ps1` /
      `.py` for the native path), mirroring `appium.sh install`'s user-only promise
- [ ] `GET …/apps/<hwnd>/elements` — walk the UIA tree bounded (150 elements, depth 14),
      window-relative rects, role/label, `IsPassword` flagged, elevated windows marked
- [ ] `winapps-click` action family (single/double/right, type, key) with typed, validated
      request fields (`clickHwnd`, `clickX`, `clickY`, `clickPid`), plan effects naming the
      app and the point, preview → confirm → job
- [ ] Type path: clipboard-free `SendInput` unicode (`KEYEVENTF_UNICODE`), Return gated behind
      an explicit confirm in the dialog
- [ ] Hotspot menu in the panel; armed mode parity with the macOS mirror (self-expiring,
      visible badge)

### Phase 3 — guest path → `WINMIR-04`

- [ ] Guest agent (single file, loopback only, same three reads + guarded input)
- [ ] `win-lab/oem/install.bat` + `win-lab/shared` delivery and an update story through `Z:`
- [ ] Console proxy with token guard; the compose network stays private, no new published ports
- [ ] Doctor inside the guest (via the agent): session state, agent version, elevation

### Phase 4 — robust ids and streaming → `WINMIR-05`, `WINMIR-06`

- [ ] WinAppDriver/Appium-windows integration: one `windows` driver session for the selected
      app through the existing Appium install; stable element ids behind hotspots, CGEvent-equivalent
      fallback to `SendInput` coordinates
- [ ] Multipart MJPEG streaming endpoint replacing the poll, pausing on hidden tabs (parity
      with the macOS MIR-04 plan)
- [ ] Session audit log: one JSON row per action + periodic frame thumbnails under the lab's
      `artifacts/`, download from the panel (parity with MIR-06)

## Open decision: lab id

Two options for where native app automation lives:

1. **New lab id `winapps`** ("Windows Apps Lab") — exact symmetry with the `macos` lab: its own
   requirements (none beyond a desktop session), own actions, `provider_for(lab, "windows") →
   "native-windows"`. Cleanest separation from the Windows *VM* lab; costs a sidebar entry and
   `LAB_ORDER` change.
2. **Extend `win-lab` with a native mode** — the Windows Lab page grows the mirror when the
   console runs on Windows (the VM sections stay for the guest). Fewer moving parts, but the
   page mixes VM and native-app concerns.

Recommendation: option 1, mirroring `macos` exactly; decide before Phase 1 lands.

## Verification gate (per phase, before merge)

- `lat check` with the updated `lat.md/win-lab.md` / `lat.md/dashboard.md` nodes
- `py_compile` + `bash -n` / `python -m py_compile` on every touched file
- e2e on mocked endpoints mirroring the macOS preview-then-arm test
- i18n: every visible string in all seven locales (`npm run test:i18n`)
- Live gate on a real Windows machine: inventory → capture → hotspots → previewed click →
  armed click, with elevation marked on an admin window
