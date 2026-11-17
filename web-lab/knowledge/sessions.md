# Sessions and profiles

A **session** is one engine run: `weblab serve` binds the loopback control API,
and everything it captures stays under `web-lab/storage/` for that run. The
engine holds no state between runs except profile web storage.

## Profiles

| Profile | Behaviour |
|:--|:--|
| `default` | Persistent webview storage under `storage/profiles/default` |
| `ephemeral` | Incognito/private webview; nothing is written to disk |
| any custom id | Persistent webview storage under `storage/profiles/<id>` |

Profile data directories are honoured by WebKitGTK (Linux) and WebView2
(Windows). **On macOS, WKWebView keeps persistent data in the system
`WKWebsiteDataStore` shared by all windows** — wry's data directory is not
applied there. For clean-slate runs on macOS, use `ephemeral`.

## Evidence handling

- Events live in a 5 000-entry ring buffer in engine memory; nothing is
  written to disk automatically.
- `storage/engine.log` holds engine stdout/stderr only (startup line, bind
  errors) — never page content.
- The console never forwards captured events anywhere: the control API binds
  to `127.0.0.1`, and the dashboard reaches it only through the local console
  proxy.

## Operating rules

- Only point the lab at sites you own or are authorized to test; os-lab's
  ground rules (CONTRIBUTING.md) apply.
- Stop the engine (`./labctl web stop` or `POST /api/web/engine/stop`) before
  rebuilding it; the binary cannot be replaced while running.
- Profiles are disposable: delete `storage/profiles/<id>` to forget a site's
  web storage for that profile.
