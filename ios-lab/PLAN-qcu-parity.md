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


## Round 2: the QcU port (branch feat/qcu-port-safety-and-repl)

Five agreed capabilities ported from QcU (commit 9c9f178), one commit each; guardrails
unchanged. Token-path finding: the macOS mirror's previewed actions (macos-click,
macos-input, macos-element, macos-set-value, macos-perform, macos-scroll) ride the shared
`/api/labs/plan` → `/api/labs/start` flow with the module-global `SIGNER` — there is no
separate macOS token path — so the stamp fix landed in `PlanSigner`, which also serves every
other lab's preview and the Source Lab confirm flow (same sign/verify contract; stamps now
expire and cannot be replayed). Armed mirror routes bypass preview stamps by design
(armed control is their gate) and are unchanged.

- [x] **Fail-closed app allowlist** (QcU safety/allowlist.ts). Missing file or `[]` still
      allows all; a present-but-unreadable, malformed or non-string-list file refuses with
      `ALLOWLIST_INVALID` naming the file and the problem.
- [x] **Expiring, one-use preview stamps** (QcU safety/confirm.ts). `PlanSigner` stamps carry
      the canonical request digest with issue/expiry seconds under an HMAC
      (`v1.<issued>.<expires>.<mac>`), default TTL 60 s (`OSLAB_MAC_PREVIEW_TTL` /
      mac-lab.json `previewTtl`, clamped 5–3600), consumed on the first successful verify —
      replay refused, failed verifies do not consume, the pending table is pruned and capped
      (64). The audit row records the stamp digest as `tokenDigest`.
- [x] **Wider key list and configurable limits** (QcU engine/config.ts). Home, End, PageUp,
      PageDown join the allowlist (console, script, dashboard); type/paste max length and the
      element-tree cap are configurable (`OSLAB_MAC_TYPE_MAX` / `_PASTE_MAX` / `_TREE_SIZE`),
      defaults unchanged; the script's backstop caps read the same env vars.
- [x] **Native REPL parity** (QcU cli/repl.ts). ios-lab/mac/macos-repl.mjs (Appium mac2) is
      replaced by console/macos_repl.py: one long-lived session over the native AX helper
      path with apps/tree/find/click/type/shot plus key, scroll, paste, set-value, perform,
      arm, disarm, confirm, stop. One session holds the arm, the element cache and the
      signer — the QcU per-command-engine pitfall is avoided. State-changing commands go
      through preview → confirm stamps or the armed gates; no bypass. Tests drive the fake
      helper on Linux CI.
- [x] **Whole-display capture and streaming** (QcU drivers/mac/mac-driver.ts). Display
      records carry their CG id; `GET /api/labs/macos/displays/<id>/screenshot` and `…/stream`
      validate the id against the displays list (`screencapture -D`) with the same host,
      permission and panic-stop behaviour as the window path; the MCP macos_screenshot tool
      takes displayId; the mirror picker gains a Whole-displays group (observe only).

### Design notes (no code) — port only if X

- **JSON-RPC stdio/HTTP engine + docs/PROTOCOL.md.** Port only if a second non-dashboard
  consumer needs the lab over a stable wire protocol (an agent runtime that cannot run the
  MCP stdio server, or remote operation). Recommendation: keep for now — the MCP server and
  the local HTTP API already cover both known consumers, and a protocol copy doubles the
  compatibility surface to maintain.
- **Typed client SDK (QcUClient).** Port only if that protocol lands and a second codebase
  starts calling it. Recommendation: skip — the dashboard's thin `api.ts` plus the MCP tools
  are the typed clients; an SDK would re-wrap the same endpoints.
- **Standalone macOS setup/status service.** Port only if the console ever needs to run
  without the dashboard (headless Mac automation). Recommendation: keep for now — the
  console already serves status/permissions/displays JSON and the scripts remain runnable
  by hand.
- **Platform driver interface + fake driver.** Port only if a second platform (Windows app
  mirror parity, Linux desktop) starts driving the same act/verify paths. Recommendation:
  partial — the fake AX helper (OSLAB_AX_HELPER) already gives CI the seam for macOS; a
  general interface can wait for the second platform.

Not ported, as agreed: deep-inspect sessions (unsupported on macOS per QcU; os-lab keeps its
Appium mac2 deep inspect — the decision item above stays open), QcU's per-command CLI
design, and everything already at parity.
