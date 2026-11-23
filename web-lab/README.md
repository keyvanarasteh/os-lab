# Web Lab

A local security lab for studying **in-app / embedded browsers**: real webview
windows (WKWebView on macOS, WebView2 on Windows, WebKitGTK on Linux) whose
every page can be observed and instrumented from the os-lab console. The same
category of component apps embed for help pages, OAuth flows and chat-side
browsers — this lab makes one available as a controlled research instrument.

Part of [os-lab](../README.md). Run everything from the repository root:

```bash
./labctl web doctor              # cargo + platform webview check
./labctl web setup               # build the engine (cargo build --release)
./labctl web up                  # start the engine on 127.0.0.1:5077
./labctl web open https://example.com
```

Then use the console (`./labctl ui`) → **Web Lab** workbench to open windows,
inject scripts and read the captured telemetry. The engine talks to nothing but
the local console: it binds to `127.0.0.1` only and never uploads data.

## What the lab does

The Rust engine (`browser/`, crate `weblab`) hosts webview windows and exposes
a small JSON control API (`/api/web/*`) that the console proxies. The console
dashboard renders the workbench; the engine does the work.

### Injection abilities

| Ability | Mechanism | Notes |
|:--|:--|:--|
| Init scripts (before page JS, every navigation) | wry initialization scripts | Registered injections apply to windows opened afterwards; already-open windows are re-injected by eval |
| On-demand JavaScript | `evaluate_script` | Result comes back asynchronously as an `eval-result` event |
| Console capture | bootstrap init script wraps `console.*` | levels log/info/warn/error/debug |
| Error capture | `window.onerror`, `unhandledrejection` | |
| Network observation | bootstrap wraps `fetch` and `XMLHttpRequest` | URL, method, status, duration; no request/response bodies in v1 |
| Bridge | `window.ipc.postMessage` IPC handler | Page→engine messages become events; 8 KiB capture cap |
| Cookies (JS-visible) | eval of `document.cookie` | **HttpOnly cookies are out of reach of this layer** — documented limitation |
| Storage snapshot | eval over `localStorage`/`sessionStorage` | |
| User-agent override | per-window `with_user_agent` | |
| Viewport presets | window size presets (mobile/tablet/desktop) | Real emulation (DPR, meta viewport quirks) is not claimed |
| Isolated profiles | per-profile web-context data directories; `ephemeral` runs incognito | Directory isolation is honoured on Linux/WebKitGTK and Windows/WebView2; on macOS persistent data lives in the shared `WKWebsiteDataStore` — use `ephemeral` for clean sessions |
| Navigation log | navigation + page-load handlers | Every attempted navigation is recorded |
| Live preview + device toggle | `GET /api/web/windows/{id}/screenshot` (JPEG, base64) and `POST /api/web/windows/{id}/viewport` | macOS capture via WebKit snapshots (no Screen Recording permission); view-only — interactions happen in the real window |

Deliberately out of scope for v1 (tracked in the lab TODO): Chrome session
import, request/response body capture, protocol-level interception (a CDP
attach mode), non-macOS window capture, click-forwarding into the preview.

## Authorization and scope

The lab drives a browser on **your** host against targets you choose. Only
analyze applications and sites you own or are explicitly authorized to test —
the same ground rules as the rest of os-lab. The engine adds no privilege, has
no remote interface, and keeps all evidence under `storage/`.

## Layout

- `browser/` — Rust crate `weblab`: tao event loop, wry webviews, loopback
  control API (`server.rs`), injection registry (`bootstrap.rs`, `state.rs`)
- `Makefile` — `preflight/doctor`, `setup`, `up`, `stop`, `status`, `open`,
  `events`, `test`, `clean` (`./labctl web <target>` delegates here)
- `knowledge/` — the injection model and session/profile model
- `storage/` — runtime data (gitignored): engine log, pid, per-profile data

## Platform notes

- **macOS** (primary): WKWebView is a system framework; `cargo` + Xcode CLT.
- **Windows**: WebView2 runtime ships with Windows 10/11.
- **Linux**: WebKitGTK 4.1 development packages are required
  (`libwebkit2gtk-4.1-dev`, `libgtk-3-dev`); `make doctor` checks for them.

## Checks

```bash
make test                                   # engine unit tests
cd browser && cargo fmt --check && cargo clippy --all-targets -- -D warnings
```

Console-side checks follow the repository standard: `npm run check`,
`npm run test:i18n`, `npm run build`, `npm run test:e2e` from `dashboard/`.
