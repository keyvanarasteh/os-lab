# macOS Lab: gaps against QcU — plan (draft PR, TODO tracker)

QcU (`/Volumes/Projects/iQ/QcU`, commit `9c9f178`) is the mac-lab engine
extracted into a standalone, zero-dependency package. Its feature map
(`docs/FEATURES.md`) lists the MIR-01…12 engine features, and os-lab already has
all of them. This plan lists what QcU has **beyond** the engine and os-lab's
macOS Lab does not, so each can be picked up as its own PR.

Method: read os-lab `master` (after #287) — `ios-lab/PLAN-macos-*.md`,
`android-lab/lab/web_ui.py` routes, `console/mcp_server.py`,
`ios-lab/mac/macos-app.sh`, `ios-lab/mac/ax-helper.swift` — and grepped for each
QcU feature. Nothing was run. Items marked *(verify)* may exist under another
name; confirm before starting.

Guardrails stay as shipped: read-only by default, preview → confirm, armed
mode, localhost-only POSTs with `X-OSLab: 1`, honest permission labeling.

## Already at parity (no work)

Element tree with priority trim, diff overlay, click family, type without
Return, allowlisted keys, scroll, paste, set-value, perform, verify-after-act,
`STALE_PATH`, MJPEG mirror, audit log, native AX helper, windows/menubar/focused,
safety layer (confirm even when armed, `SCREEN_LOCKED`, `INPUT_BUSY`, allowlist,
panic stop), MCP server and `macos_task`.

## TODO

### Safety and protocol

- [x] **Named arm owner and handoff.** QcU: a second owner gets
      `ARMED_BY_OTHER`. os-lab: `INPUT_BUSY` only. Decide whether to add the
      owner name to the refusal.
- [x] **Capability handshake.** QcU `qcu.capabilities` tells a client what the
      driver supports (deep sessions, set-value, …). os-lab has no mac
      equivalent *(verify)*.
- [x] **`element.search`.** Find elements by label/value substring (max 50) so
      agents do not read the whole tree. Also a `find` in the REPL.
- [x] **`displays.list` as an API.** Today displays are only printed by
      `macos-app.sh doctor`; expose origin, size and scale as JSON (MIR-03 data).

### Observation stream

- [x] **Live SSE audit feed** (`GET …/events`, heartbeat 15 s). os-lab has the
      list route and a JSON download only. The audit panel could update live.

### Setup and permissions

- [x] **Accessibility prompt.** QcU fires the consent dialog through the helper
      (`qcu setup`) and deep-links the Screen Recording pane. os-lab shows the
      status only *(verify)*; add a "Request access" action that stays previewed.
- [x] **Doctor names the app that needs the permission** (`responsible-app.ts`:
      the Terminal/IDE that launched the helper, not "the helper").
- [x] **One-step bootstrap.** QcU `QcU.command` / `install.sh` / idempotent
      `qcu setup` build the helper automatically; os-lab asks the user to press
      "Build AX helper". Fold into `setup-mac.sh` and `mac-doctor`.
- [x] **One config file with precedence** (env > file > defaults). os-lab has
      `agent-apps.json` and env vars only.

### Architecture and testing

- [x] **Driver seam with a fake driver.** QcU runs 43 tests with no Mac. os-lab's
      mac tests patch helpers; a small fake would let CI cover the act/verify
      paths on Linux.
- [ ] **Deep inspect without Appium** *(decision, not code).* QcU identifies elements natively (window +
      path + revision). os-lab deep-inspect and the REPL still need Appium mac2
      (MIR-05); decide whether to keep both.

### Out of scope here

- Standalone JSON-RPC 2.0 contract over stdio/HTTP and the typed SDK
  (`QcUClient`). These are QcU's product; os-lab should call QcU if it ever
  needs them, not copy them.
- A local status page. The dashboard already serves this.

## Implemented on this branch

All checked items above, with these shapes: `GET /api/labs/macos/{displays,capabilities,permissions,events}`,
`GET …/apps/<id>/search?q=`, `POST …/permission/request` (consent only: fires the
dialog or opens the pane; not part of the preview pipeline), MCP `macos_search` /
`macos_displays` / `macos_capabilities` / `macos_permissions` (still no arm tool),
`ARMED_BY_OTHER`, `ios-lab/mac/mac-lab.json` (env > file > defaults, clamped),
`OSLAB_AX_HELPER` + `ios-lab/mac/fake-ax-helper.py`, `make mac-setup` building
the helper, and `android-lab/lab/tests/test_macos_parity.py` (13 tests, Linux-safe).
Dashboard: `dashboard/src/views/macos-engine-panel.tsx` (capabilities, permissions with Request access, displays, element search, live audit feed). Not done: the Appium decision above.
Nothing here was exercised against a real input grant on a Mac.

## Caveats

- QcU's own notes say its macOS input actions are untested until Accessibility
  is granted; only read-only paths were verified on a real Mac.
- Suggested order: safety/protocol items first (small, no new permissions),
  then setup, then the fake driver.

## Verification (when items are implemented)

- `python3 -m compileall` for the console, `bash -n` for scripts, `lat check`
  after `lat.md` updates, dashboard `npm run check` / `test:i18n` / `build`.
- Live runs on a Mac recorded in `ios-lab/VERIFY.md`.
