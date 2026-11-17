# Web Lab

Web Lab is the embedded-browser lab: a Rust engine (`weblab`) hosts real webview
windows whose pages can be instrumented with JavaScript and observed through a
captured event log. It studies the in-app browser component that apps embed.

## Architecture

[[web-lab/browser]] is a standalone crate: `wry` + `tao` (the webview stack
under the Tauri app) with no async runtime. The tao event loop owns every
webview on the main thread; a `tiny_http` thread serves 127.0.0.1 commands.

[[web-lab/browser/src/bootstrap.rs#BOOTSTRAP_JS]] is the injected telemetry
bootstrap plus the self-contained eval wrapper; results travel back over the
wry IPC bridge and become events.
[[web-lab/knowledge/injection-model.md]] records the three injection layers
and their deliberate limits (no HttpOnly cookies, no body capture).

## Engine-style lab

Like [[source-lab]], Web Lab boots no VM: `./labctl web <command>` execs
`make -C web-lab` ([[web-lab/Makefile]]).

[[web-lab/scripts/setup-ubuntu.sh]] installs the Rust toolchain via rustup if
cargo is missing, then builds the engine with `cargo build --release`.
For desktop distribution, [[app/scripts/stage-runtime.mjs]] bundles the Web Lab
manifest and pre-built engine binary into the staged app resources, enabling
ready-to-use in-app browsing without requiring host Cargo installation.

Profiles are webview data directories (or incognito for `ephemeral`);
[[web-lab/knowledge/sessions.md]] documents the per-platform isolation limits
and that nothing is persisted outside `web-lab/storage/`.

## Console integration

[[console/web_api.py]] reports readiness, starts/stops the engine process and
proxies the engine's JSON API; [[android-lab/lab/web_ui.py#LabHttpHandler]]
mounts `/api/web/*` beside the Cleanup Lab routes. `console/oslab.py`
registers the lab (`native-rust` provider and action plans).

The dashboard's generic lab page covers readiness and actions; the workbench
at `/web-lab/` ([[dashboard/src/views/web-lab/pages.tsx]]) opens windows,
manages injections, runs eval and tails the event log. A docked right panel
is open by default (collapsible to the centered workbench or expandable to
full width) showing a live preview of the active window: window tabs bar,
address bar navigation, back/reload/forward buttons, polled JPEG snapshots from
`GET /api/web/windows/{id}/screenshot`, and a device size toggle that resizes
the real window through `POST /api/web/windows/{id}/viewport` (presets plus a
custom width/height pair, clamped to 200–4000). The preview is view-only —
clicks happen in the real window — and capture is macOS-only:
[[web-lab/browser/src/capture.rs]] asks the embedded WKWebView for a snapshot
through tao's `ns_view`, so the window server never sees another process's pixels
and no Screen Recording permission is needed; other hosts answer with a clear
refusal. Both routes return JSON (base64 payload), so the console proxy passes
them through unchanged. It is a console-only route: it appears in neither the
Pages deploy keep-list nor the public navigation.

## Safety stance

The engine binds to loopback only, starts no privilege, and keeps captures in
memory (capped ring buffer, 8 KiB per string). Targets must be owned or
explicitly authorized — the same ground rules as every lab.
