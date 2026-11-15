# ios-lab

An iOS Simulator lab with two paths: a macOS VM in `dockurr/macos` on Ubuntu
Server, or native Xcode / `xcrun simctl` / Appium on real macOS (Apple's EULA
restricts macOS virtualization to Apple hardware).

See [[ios-lab]], the Ubuntu service [[ios-lab/docker-compose.yml]], the native
scripts [[ios-lab/mac]] and the runbook [[ios-lab/README.md]].

## Ubuntu path (macOS VM)

The `macos` service exposes a web viewer (:8006) and VNC (:5900) and requires
KVM, following the shared VM pattern.

Host provisioning is [[ios-lab/scripts/setup-ubuntu.sh]]; readiness is
[[ios-lab/scripts/wait-ready.sh]]; a GPU override is
[[ios-lab/docker-compose.gpu.yml]]. Research is in
[[ios-lab/knowledge/setup-ubuntu.md]].

## Native macOS path

On macOS the lab drives the real Simulator toolchain through `make -C ios-lab
mac-*`.

Environment checks [[ios-lab/mac/doctor-mac.sh]], setup
[[ios-lab/mac/setup-mac.sh]], simulator control [[ios-lab/mac/run-simulator.sh]]
and [[ios-lab/mac/stop-simulator.sh]], Appium [[ios-lab/mac/appium.sh]], idb
[[ios-lab/mac/idb.sh]] and the XCUITest smoke run
[[ios-lab/mac/xcuitest.sh]]; device presets in [[ios-lab/mac/profiles]].
`labctl` refuses the Ubuntu path on macOS — see [[labctl#Lab dispatch]].

Optional automation follows the same install/start/stop pattern as Appium:
`idb.sh install` puts the client in `~/.oslab/idb` and takes the companion
from Meta's facebook/fb Homebrew tap, `idb.sh start` runs a companion for the
booted simulator, and
`xcuitest.sh smoke` creates a real XCUITest session through the running
Appium server to prove the whole chain. All of them appear on the iOS Lab
page as previewed actions and stay optional — the simulator runs without
them.

The macOS Lab shares this directory but drives **macOS applications**, not
the simulator: [[ios-lab/mac/macos-app.sh]] reports status and doctor state and
runs one Appium mac2 session that activates Finder
(`macos-app.sh smoke`). Its only requirements are Homebrew, Node and
Appium (mac2 driver) — Xcode and the iOS runtimes belong to the iOS Lab —
and mac2 needs Accessibility permission in System Settings to control
applications. `appium.sh install` installs both the XCUITest and mac2
drivers, so one Appium server serves both lab pages.

Beyond the one-shot smoke run, [[ios-lab/mac/macos-repl.mjs]] keeps a mac2
session open for interactive work from a terminal
(`make -C ios-lab mac-app-repl APP=<bundle-id>`): it prints the app's
accessibility tree, finds elements by label and clicks or types into them
by number, and saves screenshots into artifacts/. It is a local operator
tool — the web console never runs interactive sessions and keeps its
preview → confirm model for every action it does run.

The dashboard's simulator panel (see [[dashboard]]) drives the same scripts:
`start` accepts a `device` (a UDID or unique name, validated against
`xcrun simctl` by the console) so the panel can boot the device picked in its
frame, and read-only `/api/labs/ios/simulator` and
`/api/labs/ios/screenshot` endpoints feed the panel's device list and live
screen.

The drawer also answers two questions the scripts never could. **Where is
Xcode?** `xcode_status()` follows `xcode-select`/PATH (never an assumed
install path) and now reports `developerDir` and the resolved `xcodeApp`, so a
copy of Xcode installed on a non-system volume is shown at its real location
(the drawer prints it; `doctor-mac.sh` prints the resolved
`xcrun --find xcodebuild` path). **What real devices exist?** Read-only
`GET /api/labs/ios/devices` (`ios_devices()` → `xcrun devicectl list devices
--json-output`, `visibilityClass != "simulators"` filters the simulator rows
out) lists paired or connected iPhones and iPads with their tunnel state.
The iOS Actions card lists real devices and checks reachability automatically
on each inventory refresh. A successful `devicectl info details` response alone
does not prove reachability: a paired device is marked connected only when its
current tunnel state is `connected`. The simulator panel docks beside the lab on desktop
and overlays the page on phones and smaller tablets. Offline devices fade
into the list with a small badge; the tunnel reason stays under Device details.
The Actions card places connected phones and booted simulators in compact
side-by-side card groups; selecting either opens its screen in the panel.
The real-device control setup warning appears beside a device only when its
check reports Developer Mode disabled; WDA signing is not probed by this check.
The device picker accepts a real device: `GET /api/labs/ios/screenshot?udid=…`
uses `xcrun devicectl device
capture screenshot` to show its screen, while the simulator path still uses
`simctl io <selected-udid> screenshot` through `?device=…`, so multiple booted
simulators cannot show one another's screens. An offline selection shows a quiet status instead
of repeatedly attempting capture. A connected device can still refuse capture
if trust or permissions are missing; the frame shows that error and offers a
retry. Capturing a screen is read-only. Driving the device still needs
Developer Mode and a WebDriverAgent signed to the user's team for Appium.

When the home volume is under disk pressure (`/api/cleanup/volumes` warning
or below 20 GiB free) and the panel shows a booted simulator, it shows a nudge with the volume's free space
linking to the Cleanup Lab's `/cleanup/relocation/` tab, where
`simulators.coresimulator-devices` moves the CoreSimulator devices folder to
another volume behind the CLN-27 symlink flow (see [[cleanup-lab]]; runtimes
stay system-managed). The nudge is a read-only hint — it hides on fetch
failure and never moves anything itself.

The panel's Xcode path and resource meters are behind the Host details icon,
closed by default. The low-disk nudge and any watchdog operation error stay
visible outside those details.

The drawer also watches resources so a heavy simulator cannot stall the Mac
unnoticed: `GET /api/labs/ios/resources` (`ios_resources()`) samples host RAM
via `vm_stat` (free + inactive + speculative count as available), CPU busy
percent from `host_statistics64` tick deltas between polls (None on the first
sample — honest, not zero), and what Simulator.app and its helpers cost from
`ps`. Meters harden at warn (85/85) and critical (92/95); only when a simulator
is booted and Simulator.app is running do two critical polls in a row open an
alert dialog. Its one-click stops still ride the console's
previewed plan → token flow — stop every simulator (`stop-simulator.sh`), or
stop only the device selected in the drawer (the stop action takes the same
`--device` argument start does). A per-session arm
(`Stop simulators automatically…`) fires that stop without the dialog when
the threshold holds; the dialog never shows while armed. Lab-page action and
job cards stay compact by default — the command, effects and output collapse
behind a header toggle and output opens by itself only when a job fails.

The macOS Lab page mirrors real application windows instead. The window
list comes from CoreGraphics through ctypes (the osascript ObjC bridge is
unstable on current macOS), captures from `screencapture -l` (Screen
Recording permission) and element hotspots from
[[ios-lab/mac/ax-elements.applescript]] over System Events (Accessibility
permission). `macos-app.sh click` brings the owning app forward and posts
one CGEvent click; the mirror previews it like any action, and clicks land
without a preview only while control mode is armed.

The app mirror roadmap (MIR-01…06, see
[[ios-lab/PLAN-macos-mirror-roadmap.md]]) extends the same pipeline:

- **Input family (MIR-01)** — `macos-app.sh input <pid> <x> <y> <kind>`
  posts double-clicks, right-clicks, typed text and one allowlisted key.
  Typed text is echoed in its preview and never sends Return; Enter is its
  own explicit `key enter` action. Right-click or long-press a hotspot for
  the menu; the panel routes everything through the same preview → confirm
  (or armed) flow as the single click.
- **Diff overlay (MIR-02)** — `GET …/elements?revision=` returns
  `{added, removed, changed}` against the cached previous tree when the
  revision token matches; the panel rings new hotspots and fades removed
  ones. The 150-element cap is unchanged.
- **Display scale (MIR-03)** — every window record carries its display's
  backing scale (CGDisplayMode pixel-to-point ratio through ctypes;
  `CGWindowCopyScreenInfo` is not exported on current macOS), and
  `macos-app.sh doctor` prints a displays report (origins, sizes, scales).
  Hotspot math stays in points end to end.
- **Streaming mirror (MIR-04)** — `GET …/stream?fps=` streams multipart
  MJPEG with no-store headers; the loop stops on client disconnect or after
  ten minutes. The panel fetches it with an AbortController (pauses on
  hidden tabs, picks the fps from pointer proximity) and falls back to the
  1.5 s poll when the stream fails.
- **Deep inspect (MIR-05)** — the console opens one Appium mac2 session per
  app bundle id (resolving an app name via `id of app …` when asked), only
  while control mode is armed, and closes it on disarm, panel hide, tab
  unload or app quit. Hotspot actions then carry stable WebDriver element
  ids; without a session they stay CGEvent coordinates. A previewed element
  action runs `macos-app.sh element <session> <element> <kind>` as a job.
- **Audit log (MIR-06)** — every host action the console performs for the
  mirror (armed clicks and input, deep-inspect sessions, arm/disarm, and
  the confirmed halves of previewed actions with their token digest) lands
  in a bounded ring plus `ios-lab/artifacts/macos-audit-<date>.jsonl`, with
  a small frame thumbnail per action. `GET /api/labs/macos/audit` lists the
  rows and `/api/labs/macos/audit.json` downloads the file; nothing leaves
  this Mac.

The agent surface (MIR-07…12, see
[[ios-lab/PLAN-macos-agent-surface.md]]) turns the mirror into a guarded
surface a computer-use agent can drive — the observe → act → verify loop
the computer-use runtimes share, with the guardrails intact:

- **Native AX helper (MIR-09)** — `ios-lab/mac/ax-helper.swift`, compiled on
  demand (`make -C ios-lab mac-ax-helper`, CLT only) into
  `ios-lab/mac/build/`, replaces the System Events osascript for tree reads:
  full attribute trees in milliseconds with value, placeholder, enabled and
  focused state and advertised AX actions, window pinning, menu-bar trees
  and one-attribute reads. Elements carry a child-index path whose identity
  hash fails closed (`STALE_PATH`) when the tree moved. Element reads
  report their engine and fall back to osascript honestly.
- **Rich observation (MIR-08)** — the elements endpoint returns values,
  placeholders, enabled/focused state, actions and paths under a priority
  trim (interactive elements and ancestors kept, 400 cap, `trimmed` marker);
  input actions answer `actionSent` with a verify-after-act focused-element
  read; refusals carry machine codes (`NOT_ARMED`, `STALE_PATH`,
  `CONFIRM_REQUIRED`, `SCREEN_LOCKED`, `INPUT_BUSY`, …) with retry hints.
- **Element actions (MIR-07)** — `macos-set-value` and `macos-perform`
  previewed actions write values into settable elements and run advertised
  AX actions through the helper; the input family gains `scroll` (vertical,
  1–10 pages) and `paste` (clipboard replaced). The panel's hotspot menu
  offers all of it, coordinates last.
- **Windows and menus (MIR-10)** — read-only
  `/api/labs/macos/apps/<pid>/windows|menubar|focused` endpoints expose AX
  windows (sheets and alerts flagged), the menu-bar tree and the focused
  element without activating anything.
- **Agent safety (MIR-11)** — submit-class actions (Enter/Return keys,
  pastes) need `confirm: true` even while armed; `POST /api/labs/macos/stop`
  is the panic stop (disarm + close sessions + end streams via the stream
  epoch); armed control has a single owner; a locked screen refuses input;
  `ios-lab/mac/agent-apps.json` optionally allowlists the apps agents may
  drive.
- **MCP surface (MIR-12)** — `console/mcp_server.py` (stdlib stdio MCP,
  `make -C ios-lab mac-mcp`) exposes observe/act/verify/stop tools to
  computer-use agents. Read-only tools are always available; every input
  rides armed control, the audit log and the confirm gates, and there is
  deliberately no arm tool — the human arms from the dashboard. `macos_task`
  runs a scripted sequence (max 25 steps) with one audit row per step for
  reproducible security reports.
- **Cleanup panel audit** — [[ios-lab/mac/cleanup-panel-verify.sh]]
  (`make -C ios-lab mac-cleanup-verify`) reproduces the 2026-11-15 cleaner
  audit against the running desktop app: it discovers the console port from
  the spawned `web_ui.py` process, probes every `/api/cleanup/*` endpoint the
  panel reads (flagging the Space Explorer 404 fixed in PR #248 instead of
  failing), runs the default and full 64-entry measurement scans, and writes
  a dated report under `ios-lab/artifacts/`. `BOOKMARK=1` applies the
  quick-clean bookmark policy — low-risk entries of at least 50 MB, largest
  first, capped at 8; high/medium-risk and privacy entries stay in the
  plan → confirm flow. `RECORD=1` wraps the run in a `screencapture` video;
  [[ios-lab/mac/README-cleanup-verify.md]] documents the manual runbook.

## Research

The top iOS-in-Docker options, networking and operational limits.

They are documented across [[ios-lab/knowledge]] (docker-options, networking,
operations, usecases, references) and [[ios-lab/knowledge/setup-mac.md]].
