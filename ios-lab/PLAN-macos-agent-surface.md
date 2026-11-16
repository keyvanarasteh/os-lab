# macOS Lab agent surface — plan (draft PR, stacked on #227)

Design for the six tasks that bring the app mirror to computer-use-agent level
(MIR-07…12), stacked on the MIR-01…06 branch. The reference model is the
computer-use runtime (accessibility-first element actions, diffed trees,
error taxonomy, single-owner control) shared by Claude computer-use and
ChatGPT's operator loop: **observe → decide → act → verify**, element-scoped
first, coordinates last. Every task keeps the shipped guardrails and adds an
explicit agent-safety layer; nothing here bypasses preview → confirm, armed
mode, localhost-only POSTs or the audit log.

Surfaces: `ios-lab/mac/ax-helper.swift` (new), `ios-lab/mac/macos-app.sh`,
`console/oslab.py`, `android-lab/lab/web_ui.py`, `console/mcp_server.py`
(new) and the mirror panel.

---

## MIR-09 — Native AX helper (the keystone)

`ios-lab/mac/ax-helper.swift`, compiled with `swiftc` (Xcode CLT) into
`ios-lab/mac/build/ax-helper` on first use; `macos-app.sh build-ax-helper`
and a doctor probe (`swiftc` present? helper builds?). The console uses the
helper when present and falls back to the current osascript path otherwise,
reporting which engine served the read.

Commands (JSON on stdout, exit 1 with `{"error": …, "code": …}` on failure):

- `tree --pid N [--window INDEX] [--depth D] [--max M]` — full attribute tree:
  role, subrole, title, label, value, placeholder, focused, enabled, rect,
  actions (AXActionNames), children. Window pinning: the AX window is matched
  to a CG window by position+size (no private APIs).
- `windows --pid N` — AX windows with position, size, title, subrole, main,
  focused, minimized; sheets and alerts flagged via subrole.
- `menubar --pid N` — menu-bar tree (menus → items, with enabled + shortcut).
- `read --pid N --path a.b.c [--attr AXValue|AXFocused|…]` — one attribute.
- `set --pid N --path a.b.c --value V` — AXValue set (settable elements only).
- `perform --pid N --path a.b.c --action AXPress|AXShowMenu|…` — only actions
  the element advertises.
- `focused --pid N` — the focused element (path + attributes).

Element addressing is a **path** (child-index chain from the app element) plus
a content hash of the addressed element's identity (role+title+rect) so stale
paths fail closed with `STALE_PATH` instead of acting on the wrong node.

## MIR-08 — Rich observation and action semantics

- The elements endpoint returns, per element: `value`, `placeholder`,
  `enabled`, `focused`, `actions`, `engine` (`ax-helper` | `osascript` |
  `mac2`), and keeps `revision`/diff. The 150 cap becomes a priority trim
  (ancestors + interactive roles kept, decorative dropped) with a
  `trimmed: true` marker instead of a blind cut.
- Every input endpoint (click/input/element action) responds
  `{"ok": true, "actionSent": true, "verify": {…}}` where verify re-reads the
  target (AXValue for type/setValue, AXFocused after key) and reports
  `before`/`after`/`changed` — honest "the API accepted it" vs "the app
  changed" semantics.
- Error taxonomy on refusal paths: `NOT_ARMED`, `PERMISSION_DENIED`
  (Accessibility probe), `STALE_PATH`, `NOT_SETTABLE`, `ACTION_UNAVAILABLE`,
  `APP_QUIT`, `SCREEN_LOCKED`, `INPUT_BUSY`, each human-readable; `retry`
  hint (`reobserve` | `retry` | `never`).

## MIR-07 — Element action surface

Plan/armed support for the full action family (fields: `elementPath` or
`elementId` (mac2), plus kind and payload):

- `setValue` (AX set, settable only; falls back to select-all + type via mac2),
- advertised AX actions (`perform`),
- `scroll` (direction + pages; AXScrollToVisible first, CGEvent wheel
  fallback), `drag` (from element/point to point, with modifiers),
- `selectText` (prefix/suffix disambiguation inside one editable element),
- `paste` (text/md/html via the pasteboard, through a confirm dialog),
- key chords with modifiers (`cmd+c`, `alt+tab`-style), key repeat and hold,
- click `modifiers` (cmd/shift/option/control) and `clickCount` up to 3.

mac2 carries scroll/drag/paste/keys through W3C actions; AX carries
setValue/perform/select. Coordinates remain the last fallback and say so.

## MIR-10 — Windows, menus and dialogs

- `GET /api/labs/macos/apps/<pid>/windows` — the AX window list (sheets and
  alerts flagged) beside the CG list; the panel can pin a window id.
- `GET /api/labs/macos/apps/<pid>/menubar` — menu tree; clicking a menu item
  is a previewed action (`AXPress` on the item) — one of the few ways to
  reach functionality hotspots and AX cannot see.
- Sheet/alert detection: when the pinned window's tree reports a modal
  child/subrole, the panel surfaces it ("a dialog is open — act on it or
  dismiss with Escape") instead of clicking through it blindly.
- Background reads: the helper never activates the app for observation;
  activation happens only in the existing input actions, as today.

## MIR-11 — Agent safety layer

- **Risk classes** on every action: `low` (read-only), `coordinate-click`
  (armed-immediate as today), `typing` (armed-immediate, audited), and
  **`submit`** — Enter/Return keys, pastes, setValue into fields the tree
  marks as submit-capable (buttons/fields in forms) — always require an
  explicit confirm dialog, even when armed.
- **Panic stop**: `POST /api/labs/macos/stop` — disarms control, closes all
  deep-inspect sessions, kills stream handlers, records one audit row. The
  panel keeps a persistent Stop control while anything is open.
- **Single-owner input**: a lock keyed by the panel session; a second client
  arming control gets `INPUT_BUSY` with the owner's start time instead of
  silent double control.
- **Screen-lock detection**: `CGSessionCopyCurrentDictionary` /
  `CGDisplayIsAsleep` probe before armed actions; locked → `SCREEN_LOCKED`
  refusal (this is what CUA reports too).
- **App allowlist**: `ios-lab/mac/agent-apps.json` (empty = mirror-visible
  apps only, unchanged); when set, deep-inspect sessions and armed actions
  against other apps are refused. Validated like lab scope.

## MIR-12 — MCP tool surface and task runner

`console/mcp_server.py` — a stdio MCP server (JSON-RPC 2.0, stdlib only)
run with `make -C ios-lab mac-mcp` or `python3 console/mcp_server.py`:

- tools: `macos_apps`, `macos_get_app_state` (tree+screenshot, diffed by
  revision), `macos_screenshot`, `macos_click` (element path or point),
  `macos_type`, `macos_key`, `macos_scroll`, `macos_set_value`,
  `macos_perform`, `macos_stop`;
- read-only tools are always available to a local MCP client; every input
  tool rides the same armed state, risk classes, audit and single-owner lock
  as the panel — the model in ZCode/Claude becomes the decision loop, the
  console stays the guarded actuator;
- **task runner**: `macos_task` takes `{steps: [{tool, args}…], maxSteps,
  stopOnError}` (a scripted, auditable sequence — no model in the lab),
  runs it against the same surface, writes one audit row per step and
  returns a per-step transcript for reproducible security reports.

## Verification

- Helper: `swiftc` build, live `tree`/`windows`/`menubar`/`set`/`perform`
  runs against Finder/Notes on this Mac; osascript fallback when the helper
  is absent (rename the binary and re-run the endpoint).
- Safety: locked-input refusal paths, allowlist refusal, panic stop leaving
  no sessions/streams, `INPUT_BUSY` from a second client.
- Dashboard checks, `lat check`, e2e; screenshots of the new panel states
  recorded in VERIFY.md before the PR leaves draft.
