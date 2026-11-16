//! CLN-30: OS notification delivery for the cleanup lab's event outbox.
//!
//! The console appends typed events at the lab's lifecycle hooks (job
//! completions, the automated hook clean, monitor evaluations). One watcher
//! thread polls the outbox endpoint over the loopback socket — the same
//! no-HTTP-client idiom as `console::healthy` — and delivers new events as
//! OS notifications on all three desktop platforms. While the main window is
//! focused and on the dashboard the delivery is skipped: the page's own
//! toast stack already shows the event, and a hidden page is covered by the
//! OS banner instead.
//!
//! Clicking a delivered notification (or its action button) focuses the app
//! and routes into the dashboard through the same allowlist the `oslab://`
//! deep links use — a notification can never navigate somewhere unexpected.
//!
//! The delivery report lands in a runtime file the console serves back to
//! the dashboard (`OSLAB_NOTIFICATIONS_RUNTIME`), so the notifications card
//! can say honestly whether the desktop app is connected and whether the
//! last delivery worked. Honest degradation: a machine without a
//! notification facility records the delivery error, never a fake success.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde::Deserialize;
use tauri::{AppHandle, Manager};
use tauri_plugin_notification::{Action, ActionType, NotificationExt};

/// How often the outbox is polled. The dashboard polls the same data at 5 s;
/// the watcher only has to beat the user's patience, not a stopwatch.
const POLL: Duration = Duration::from_secs(5);

#[derive(Deserialize)]
struct Outbox {
    #[serde(default)]
    events: Vec<OutboxEvent>,
}

#[derive(Deserialize)]
struct OutboxEvent {
    id: u64,
    #[serde(default)]
    title: String,
    #[serde(default)]
    body: String,
    #[serde(default)]
    route: Option<String>,
    #[serde(default)]
    actions: Vec<OutboxAction>,
}

#[derive(Deserialize)]
struct OutboxAction {
    #[serde(default)]
    id: String,
    #[serde(default)]
    route: Option<String>,
}

/// The delivery report the console reads (via `OSLAB_NOTIFICATIONS_RUNTIME`)
/// and merges into `GET /api/cleanup/notifications`. Absent means the
/// console runs without the desktop app.
#[derive(serde::Serialize)]
struct RuntimeReport {
    platform: &'static str,
    appVersion: String,
    lastDeliveryAt: Option<u64>,
    lastDeliveryOk: Option<bool>,
    lastError: Option<String>,
}

/// Delivered notification id (the outbox event id) → its route, for the
/// click → deep-link round trip.
static ROUTES: Mutex<HashMap<i32, String>> = Mutex::new(HashMap::new());
/// The outbox cursor: the last event id the watcher saw.
static LAST_SEEN: AtomicU64 = AtomicU64::new(0);

/// One watcher thread for the app's lifetime (a daemon: process exit ends it).
/// On the first successful poll the cursor is adopted without delivering, so
/// an app restart never replays the whole stored outbox — the same page-load
/// semantics the dashboard's toast stack uses.
pub fn start_outbox_watcher(app: AppHandle) {
    let handled = register_click_handler(&app);
    std::thread::Builder::new()
        .name("notifications-outbox".into())
        .spawn(move || {
            let mut initialized = false;
            loop {
                std::thread::sleep(POLL);
                if let Err(error) = poll_outbox(&app, &mut initialized, handled) {
                    report(app.clone(), None, Some(error));
                }
            }
        })
        .ok(); // losing the watcher degrades to in-app notifications only
}

/// `GET /api/cleanup/notifications/outbox?since=` over a plain loopback
/// socket, then deliver everything the cursor has not seen.
fn poll_outbox(app: &AppHandle, initialized: &mut bool, handled: bool) -> Result<(), String> {
    let Some(url) = app.state::<crate::console::Console>().running_url() else { return Ok(()) };
    let Some(port) = url.rsplit(':').next().and_then(|p| p.trim_end_matches('/').parse::<u16>().ok()) else {
        return Err("The console URL has no port".into());
    };
    if !*initialized {
        // Adopt: the newest stored id becomes the cursor, nothing delivers.
        let body = console_get(port, "/api/cleanup/notifications/outbox?since=0")?;
        *initialized = true;
        if let Ok(outbox) = serde_json::from_str::<Outbox>(&body) {
            if let Some(newest) = outbox.events.iter().map(|event| event.id).max() {
                LAST_SEEN.store(newest, Ordering::SeqCst);
            }
        }
        report(app.clone(), None, None);
        return Ok(());
    }
    let since = LAST_SEEN.load(Ordering::SeqCst);
    let body = console_get(port, &format!("/api/cleanup/notifications/outbox?since={since}"))?;
    let outbox: Outbox = serde_json::from_str(&body).map_err(|e| format!("The outbox payload is not valid JSON: {e}"))?;
    for event in outbox.events.iter().filter(|event| event.id > since) {
        deliver(app, event, handled);
    }
    if let Some(newest) = outbox.events.iter().map(|event| event.id).max() {
        if newest > since {
            LAST_SEEN.store(newest, Ordering::SeqCst);
        }
    }
    Ok(())
}

/// Deliver one event. Focused-dashboard skips keep the cursor semantics:
/// the in-app toast owns the moment, the OS banner owns every other one.
fn deliver(app: &AppHandle, event: &OutboxEvent, handled: bool) {
    if suppressed(app) {
        return;
    }
    let id = i32::try_from(event.id).unwrap_or(i32::MAX);
    if let Some(route) = event.route.clone() {
        ROUTES.lock().unwrap_or_else(|poisoned| poisoned.into_inner()).insert(id, route);
    }
    let mut builder = app
        .notification()
        .builder()
        .id(id)
        .title(event.title.clone())
        .body(event.body.clone());
    if handled && !event.actions.is_empty() {
        builder = builder.action_type_id("oslab-open");
    }
    match builder.show() {
        Ok(()) => report(app.clone(), Some(true), None),
        Err(error) => report(app.clone(), Some(false), Some(error.to_string())),
    }
}

/// The main window focused on a dashboard page: the page's toast stack shows
/// the event already. On the launcher (or unfocused/hidden) the OS delivers.
fn suppressed(app: &AppHandle) -> bool {
    let Some(window) = app.get_webview_window("main") else { return false };
    if !window.is_focused().unwrap_or(false) {
        return false;
    }
    window.url().map(|u| u.scheme() == "http" || u.scheme() == "https").unwrap_or(false)
}

/// A single registered action type; without a handler and a type the OS
/// buttons would not appear at all. `tap` covers a click on the banner body.
fn register_click_handler(app: &AppHandle) -> bool {
    let open = ActionType::builder("oslab-open")
        .actions(vec![Action::builder("open", "Open").build()])
        .build();
    if let Err(error) = app.notification().register_action_types(vec![open]) {
        report(app.clone(), None, Some(format!("Action buttons are unavailable: {error}")));
        return false;
    }
    let handler_app = app.clone();
    let _ = app.notification().on_action(move |performed| {
        let Some(window) = handler_app.get_webview_window("main") else { return };
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
        // Route the exact notification when the platform reports it; a bare
        // `tap` without identity falls back to the newest delivered route.
        let routes = ROUTES.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let route = performed
            .notification()
            .and_then(|notification| routes.get(&notification.id()))
            .or_else(|| routes.values().next_back())
            .cloned();
        drop(routes);
        if let Some(route) = route {
            crate::navigate_widget_route(&handler_app, &route);
        }
    });
    true
}

/// Rewrite the delivery report; best-effort — the dashboard treats a missing
/// file as "desktop app not detected".
fn report(app: AppHandle, ok: Option<bool>, error: Option<String>) {
    let Ok(dir) = crate::data_dir(&app) else { return };
    let payload = RuntimeReport {
        platform: if cfg!(target_os = "macos") {
            "macos"
        } else if cfg!(target_os = "windows") {
            "windows"
        } else {
            "linux"
        },
        appVersion: app.package_info().version.to_string(),
        lastDeliveryAt: ok.map(|_| std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs()),
        lastDeliveryOk: ok,
        lastError: error,
    };
    if let Ok(blob) = serde_json::to_string(&payload) {
        let _ = std::fs::create_dir_all(&dir);
        let _ = std::fs::write(dir.join("notifications-runtime.json"), blob);
    }
}

/// `GET <path>` over a plain socket: no HTTP client, no CORS, loopback only.
/// The console answers `Connection: close`, so the body ends at EOF.
fn console_get(port: u16, path: &str) -> Result<String, String> {
    use std::io::{Read, Write};
    use std::net::SocketAddr;
    use std::net::TcpStream;

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(800))
        .map_err(|e| format!("The console did not accept the outbox connection: {e}"))?;
    let _ = stream.set_read_timeout(Some(Duration::from_millis(1500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(800)));
    let request = format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\nConnection: close\r\n\r\n");
    stream.write_all(request.as_bytes()).map_err(|e| format!("The outbox request could not be sent: {e}"))?;
    let mut raw = Vec::new();
    stream.read_to_end(&mut raw).map_err(|e| format!("The outbox response was cut off: {e}"))?;
    let raw = String::from_utf8_lossy(&raw).into_owned();
    let (head, body) = raw.split_once("\r\n\r\n").ok_or("The outbox response has no header block")?;
    let ok = head.split_once(' ').map(|(_, rest)| rest.starts_with("200")).unwrap_or(false);
    if !ok {
        return Err(format!("The outbox answered {}", head.lines().next().unwrap_or("nothing")));
    }
    Ok(body.to_string())
}

/// The runtime report path, shared with `console.rs` through the spawn env.
pub fn runtime_file_name() -> &'static str {
    "notifications-runtime.json"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outbox_payload_is_typed_and_optional_fields_survive() {
        let outbox: Outbox = serde_json::from_str(
            r#"{"events": [
                {"id": 3, "title": "Scan finished", "body": "Found 12 items.", "route": "results",
                 "actions": [{"id": "open", "label": "Open", "route": "results"}]},
                {"id": 4, "title": "Monitor recovered"}
            ]}"#,
        )
        .unwrap();
        assert_eq!(outbox.events.len(), 2);
        assert_eq!(outbox.events[0].actions[0].route.as_deref(), Some("results"));
        assert_eq!(outbox.events[1].route, None);
        assert!(outbox.events[1].actions.is_empty());
    }

    #[test]
    fn console_get_reports_server_errors_without_a_body() {
        // A listener that answers 404 — the helper must refuse, not parse.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = std::thread::spawn(move || {
            use std::io::{Read, Write};
            if let Ok((mut s, _)) = listener.accept() {
                let mut buf = [0u8; 512];
                let _ = s.read(&mut buf);
                let _ = s.write_all(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 2\r\n\r\n{}");
            }
        });
        let error = console_get(port, "/api/cleanup/notifications/outbox").unwrap_err();
        assert!(error.contains("404"), "{error}");
        handle.join().unwrap();
    }

    #[test]
    fn console_get_returns_the_body_on_200() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = std::thread::spawn(move || {
            use std::io::{Read, Write};
            if let Ok((mut s, _)) = listener.accept() {
                let mut buf = [0u8; 512];
                let _ = s.read(&mut buf);
                let _ = s.write_all(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{\"events\": []}");
            }
        });
        assert_eq!(console_get(port, "/api/cleanup/notifications/outbox?since=0").unwrap(), "{\"events\": []}");
        handle.join().unwrap();
    }
}
