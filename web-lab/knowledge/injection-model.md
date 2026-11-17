# The injection model

Web Lab instruments embedded browsers by separating three layers, in the order
they run:

1. **Initialization scripts** (engine → page). wry injects the telemetry
   bootstrap plus every enabled registered injection as an initialization
   script, so they run **before any page script on every navigation**. Scripts
   are baked into a webview when the window is built, so registering an
   injection affects windows opened afterwards; already-open windows are
   re-injected by eval, which runs after page scripts — the console surfaces
   this distinction instead of hiding it.
2. **On-demand eval** (engine → page). `POST /api/web/windows/{id}/eval` wraps
   the submitted code in a self-contained promise wrapper that reports the
   result (or the error) back through the bridge as an `eval-result` event.
   The wrapper does not depend on the bootstrap, so it also works on pages
   where the bootstrap has not run (for example `about:blank`).
3. **The bridge** (page → engine). wry's IPC handler receives
   `{type, payload}` JSON messages. The bootstrap sends `console`, `error`,
   `network`, `injected`; lab tooling adds `eval-result`, cookies and storage
   snapshots. Every message becomes a ring-buffer event (`GET /api/web/events`)
   capped at 8 KiB per string so a noisy page cannot balloon the log.

## What the bootstrap hooks

- `console.log/info/warn/error/debug` (original methods still run)
- `window.onerror` and `unhandledrejection`
- `window.fetch` and `XMLHttpRequest` (method, URL, status, duration; bodies
  are not captured in v1)

## Deliberate limits

- **HttpOnly cookies are out of reach**: the cookie reader evaluates
  `document.cookie`, which is the JS-visible surface only. Protocol-level
  cookie capture (including HttpOnly) belongs to a future CDP attach mode.
- **No body capture**: the network hook reports metadata, never payloads.
- **Init scripts are webview-scoped**: a registered injection cannot retro-
  actively apply to a window that already exists; the workbench says so.
- **Viewport presets resize the window**; they do not emulate DPR or mobile
  viewport quirks. Treat the preset as a framing aid, not a device lab.

## Why a bridge, not a return value

wry's `evaluate_script` is fire-and-forget across platforms, so every eval
carries an id and its result arrives as an event. That keeps one code path for
eval, cookies and storage, and it makes results part of the evidence log
instead of an ephemeral HTTP response.
