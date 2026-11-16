//! Loopback control API served with `tiny_http`: reads mutate `SharedState` directly,
//! window commands travel through the event-loop proxy so webviews stay on the main
//! thread. Binds to 127.0.0.1 only — the console is the single client.

use std::io::Read;
use std::sync::mpsc::channel;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Value};
use tao::event_loop::EventLoopProxy;
use tiny_http::{Header, Method, Response, Server};

use crate::app::UserEvent;
use crate::protocol::{
    normalize_url, parse_route, EvalRequest, InjectionRequest, NavigateRequest, OpenWindowRequest,
    ProfileRequest, Route, ViewportRequest, WindowAction,
};
use crate::state::SharedState;

const REPLY_TIMEOUT: Duration = Duration::from_secs(15);
const MAX_BODY_BYTES: usize = 512 * 1024;
const MAX_EVENT_PAGE: usize = 500;

/// The control thread hands window commands to the main-thread event loop through
/// this sink; the indirection keeps route handling testable without a real loop.
pub trait EventSink {
    fn send_user_event(&self, event: UserEvent) -> Result<(), String>;
}

impl EventSink for EventLoopProxy<UserEvent> {
    fn send_user_event(&self, event: UserEvent) -> Result<(), String> {
        self.send_event(event)
            .map_err(|_| "engine event loop is closed".to_string())
    }
}

#[derive(Debug)]
pub struct ApiError {
    pub status: u16,
    pub message: String,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: 400,
            message: message.into(),
        }
    }

    fn not_found(message: impl Into<String>) -> Self {
        Self {
            status: 404,
            message: message.into(),
        }
    }
}

/// Blocks serving control requests until the process exits. Run on a worker thread.
pub fn serve(port: u16, state: Arc<Mutex<SharedState>>, proxy: EventLoopProxy<UserEvent>) {
    let address = format!("127.0.0.1:{port}");
    let server = match Server::http(&address) {
        Ok(server) => server,
        Err(error) => {
            eprintln!("weblab: cannot bind control API on {address}: {error}");
            std::process::exit(1);
        }
    };
    for mut request in server.incoming_requests() {
        let method = request.method().clone();
        let raw_url = request.url().to_string();
        let (path, query) = split_query(&raw_url);
        let mut body = String::new();
        let _ = request
            .as_reader()
            .take(MAX_BODY_BYTES as u64)
            .read_to_string(&mut body);

        let (status, payload) = match handle(&method, path, query, &body, &state, &proxy) {
            Ok(payload) => (200, payload),
            Err(error) => (error.status, json!({ "error": error.message })),
        };
        let response = Response::from_string(payload.to_string())
            .with_status_code(status)
            .with_header(
                Header::from_bytes(&b"Content-Type"[..], &b"application/json"[..])
                    .expect("static header"),
            );
        let _ = request.respond(response);
    }
}

fn split_query(raw: &str) -> (&str, &str) {
    match raw.split_once('?') {
        Some((path, query)) => (path, query),
        None => (raw, ""),
    }
}

fn handle(
    method: &Method,
    path: &str,
    query: &str,
    body: &str,
    state: &Arc<Mutex<SharedState>>,
    sink: &dyn EventSink,
) -> Result<Value, ApiError> {
    let route = parse_route(method.as_str(), path);
    match route {
        Route::Health => {
            let state = state.lock().expect("engine state poisoned");
            Ok(json!({
                "ok": true,
                "engine": "weblab",
                "version": env!("CARGO_PKG_VERSION"),
                "port": state.port,
                "windows": state.windows.len(),
                "eventCount": state.events.len(),
            }))
        }
        Route::Overview => {
            let state = state.lock().expect("engine state poisoned");
            Ok(json!({
                "ok": true,
                "version": env!("CARGO_PKG_VERSION"),
                "port": state.port,
                "startedAt": state.started_at,
                "windows": state.windows.values().collect::<Vec<_>>(),
                "injections": state.injections,
                "profiles": state.profiles,
                "eventCount": state.events.len(),
                "lastEventSeq": state.events.back().map(|entry| entry.seq).unwrap_or(0),
            }))
        }
        Route::Windows => match method {
            Method::Get => {
                let state = state.lock().expect("engine state poisoned");
                Ok(json!({ "windows": state.windows.values().collect::<Vec<_>>() }))
            }
            Method::Post => {
                let request: OpenWindowRequest = serde_json::from_str(body).map_err(|error| {
                    ApiError::bad_request(format!("invalid open request: {error}"))
                })?;
                normalize_url(&request.url).map_err(ApiError::bad_request)?;
                let (reply, receiver) = channel();
                sink.send_user_event(UserEvent::Open { request, reply })
                    .map_err(|message| ApiError {
                        status: 503,
                        message,
                    })?;
                let id = receiver
                    .recv_timeout(REPLY_TIMEOUT)
                    .map_err(|_| ApiError {
                        status: 503,
                        message: "engine did not answer".into(),
                    })?
                    .map_err(ApiError::bad_request)?;
                Ok(json!({ "ok": true, "windowId": id }))
            }
            _ => Err(ApiError::bad_request("method not allowed")),
        },
        Route::WindowViewport { id } => {
            let request: ViewportRequest = serde_json::from_str(body).map_err(|error| {
                ApiError::bad_request(format!("invalid viewport request: {error}"))
            })?;
            let (label, width, height) = request.resolve().map_err(ApiError::bad_request)?;
            let argument = Some(
                json!({
                    "width": width as u32,
                    "height": height as u32,
                    "viewport": label,
                })
                .to_string(),
            );
            let (reply, receiver) = channel();
            sink.send_user_event(UserEvent::Window {
                id,
                action: WindowAction::Resize,
                argument,
                reply,
            })
            .map_err(|message| ApiError {
                status: 503,
                message,
            })?;
            let applied = receiver
                .recv_timeout(REPLY_TIMEOUT)
                .map_err(|_| ApiError {
                    status: 503,
                    message: "engine did not answer".into(),
                })?
                .map_err(ApiError::bad_request)?;
            Ok(json!({
                "ok": true,
                "applied": applied,
                "viewport": label,
                "size": [width as u32, height as u32],
            }))
        }
        Route::WindowScreenshot { id } => {
            let slot = Arc::new(Mutex::new(None));
            let (done, receiver) = channel();
            sink.send_user_event(UserEvent::Screenshot {
                id,
                slot: Arc::clone(&slot),
                done,
            })
            .map_err(|message| ApiError {
                status: 503,
                message,
            })?;
            // The main thread fills the slot and pings exactly once, whether the
            // capture succeeded or not; this thread only waits.
            receiver
                .recv_timeout(REPLY_TIMEOUT)
                .map_err(|_| ApiError {
                    status: 503,
                    message: "the capture did not answer in time".into(),
                })?;
            let outcome = slot
                .lock()
                .expect("capture slot poisoned")
                .take()
                .ok_or_else(|| ApiError {
                    status: 503,
                    message: "the capture answered without a result".into(),
                })?;
            let data_base64 = outcome.map_err(|message| ApiError {
                status: 500,
                message,
            })?;
            Ok(json!({
                "ok": true,
                "format": "jpeg",
                "dataBase64": data_base64,
            }))
        }
        Route::WindowDelete { id } => {
            let (reply, receiver) = channel();
            sink.send_user_event(UserEvent::Close { id, reply })
                .map_err(|message| ApiError {
                    status: 503,
                    message,
                })?;
            let removed = receiver
                .recv_timeout(REPLY_TIMEOUT)
                .map_err(|_| ApiError {
                    status: 503,
                    message: "engine did not answer".into(),
                })?
                .map_err(ApiError::not_found)?;
            Ok(json!({ "ok": true, "closed": removed }))
        }
        Route::WindowAction { id, action } => {
            let argument = match action {
                WindowAction::Navigate => Some(
                    serde_json::from_str::<NavigateRequest>(body)
                        .map_err(|error| {
                            ApiError::bad_request(format!("invalid navigate request: {error}"))
                        })?
                        .url,
                ),
                WindowAction::Eval => Some(
                    serde_json::from_str::<EvalRequest>(body)
                        .map_err(|error| {
                            ApiError::bad_request(format!("invalid eval request: {error}"))
                        })?
                        .code,
                ),
                _ => None,
            };
            let (reply, receiver) = channel();
            sink.send_user_event(UserEvent::Window {
                id,
                action: action.clone(),
                argument,
                reply,
            })
            .map_err(|message| ApiError {
                status: 503,
                message,
            })?;
            let applied = receiver
                .recv_timeout(REPLY_TIMEOUT)
                .map_err(|_| ApiError {
                    status: 503,
                    message: "engine did not answer".into(),
                })?
                .map_err(ApiError::bad_request)?;
            Ok(json!({ "ok": true, "applied": applied }))
        }
        Route::Injections => match method {
            Method::Get => {
                let state = state.lock().expect("engine state poisoned");
                Ok(json!({ "injections": state.injections }))
            }
            Method::Post => {
                let request: InjectionRequest = serde_json::from_str(body).map_err(|error| {
                    ApiError::bad_request(format!("invalid injection request: {error}"))
                })?;
                let mut state = state.lock().expect("engine state poisoned");
                let injection = state
                    .register_injection(request.name, request.code)
                    .map_err(ApiError::bad_request)?;
                Ok(json!({ "ok": true, "injection": injection }))
            }
            _ => Err(ApiError::bad_request("method not allowed")),
        },
        Route::InjectionDelete { id } => {
            let mut state = state.lock().expect("engine state poisoned");
            let removed = state.remove_injection(&id);
            if removed {
                Ok(json!({ "ok": true, "removed": true }))
            } else {
                Err(ApiError::not_found(format!("unknown injection: {id}")))
            }
        }
        Route::Events => {
            let since = query
                .split('&')
                .find_map(|pair| pair.strip_prefix("since="))
                .and_then(|value| value.parse::<u64>().ok())
                .unwrap_or(0);
            let state = state.lock().expect("engine state poisoned");
            let entries = state.events_since(since, MAX_EVENT_PAGE);
            let last = state.events.back().map(|entry| entry.seq).unwrap_or(0);
            Ok(json!({
                "events": entries,
                "lastSeq": last,
                "count": entries.len(),
            }))
        }
        Route::Profiles => match method {
            Method::Get => {
                let state = state.lock().expect("engine state poisoned");
                Ok(json!({ "profiles": state.profiles }))
            }
            Method::Post => {
                let request: ProfileRequest = serde_json::from_str(body).map_err(|error| {
                    ApiError::bad_request(format!("invalid profile request: {error}"))
                })?;
                let mut state = state.lock().expect("engine state poisoned");
                let profile = state.upsert_profile(request.id, request.name, request.ephemeral);
                Ok(json!({ "ok": true, "profile": profile }))
            }
            _ => Err(ApiError::bad_request("method not allowed")),
        },
        Route::EngineStop => {
            sink.send_user_event(UserEvent::Shutdown)
                .map_err(|message| ApiError {
                    status: 503,
                    message,
                })?;
            Ok(json!({ "ok": true, "stopping": true }))
        }
        Route::Unknown => Err(ApiError::not_found(format!("no route for {method} {path}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{Viewport, DEFAULT_PORT};
    use std::sync::Mutex as StdMutex;

    fn state() -> Arc<Mutex<SharedState>> {
        Arc::new(Mutex::new(SharedState::new(DEFAULT_PORT)))
    }

    /// A sink that accepts every command without an event loop. The paths exercised
    /// here either never send events or fail validation before reaching the sink.
    struct RecordingSink {
        sent: StdMutex<Vec<String>>,
    }

    impl RecordingSink {
        fn new() -> Self {
            Self {
                sent: StdMutex::new(Vec::new()),
            }
        }
    }

    impl EventSink for RecordingSink {
        fn send_user_event(&self, event: UserEvent) -> Result<(), String> {
            self.sent.lock().unwrap().push(format!("{event:?}"));
            Ok(())
        }
    }

    #[test]
    fn health_and_events_read_from_state() {
        let shared = state();
        shared.lock().unwrap().push_event(
            None,
            "injected",
            json!({ "href": "https://example.com" }),
        );
        let sink = RecordingSink::new();
        let health = handle(&Method::Get, "/healthz", "", "", &shared, &sink).unwrap();
        assert_eq!(health["ok"], json!(true));
        let events = handle(
            &Method::Get,
            "/api/web/events",
            "since=0",
            "",
            &shared,
            &sink,
        )
        .unwrap();
        assert_eq!(events["count"], json!(1));
        assert_eq!(events["events"][0]["kind"], json!("injected"));
    }

    #[test]
    fn injections_round_trip_over_the_api() {
        let shared = state();
        let sink = RecordingSink::new();
        let created = handle(
            &Method::Post,
            "/api/web/injections",
            "",
            r#"{"name":"canary","code":"window.__canary = true;"}"#,
            &shared,
            &sink,
        )
        .unwrap();
        assert_eq!(created["ok"], json!(true));
        let id = created["injection"]["id"].as_str().unwrap().to_string();
        let deleted = handle(
            &Method::Delete,
            &format!("/api/web/injections/{id}"),
            "",
            "",
            &shared,
            &sink,
        )
        .unwrap();
        assert_eq!(deleted["removed"], json!(true));
    }

    #[test]
    fn bad_bodies_fail_with_400() {
        let shared = state();
        let sink = RecordingSink::new();
        let error = handle(
            &Method::Post,
            "/api/web/windows",
            "",
            "not json",
            &shared,
            &sink,
        )
        .unwrap_err();
        assert_eq!(error.status, 400);
        let error = handle(
            &Method::Post,
            "/api/web/windows/1/navigate",
            "",
            "{}",
            &shared,
            &sink,
        )
        .unwrap_err();
        assert_eq!(error.status, 400);
    }

    #[test]
    fn unknown_routes_fail_with_404() {
        let shared = state();
        let sink = RecordingSink::new();
        let error = handle(&Method::Get, "/api/web/nope", "", "", &shared, &sink).unwrap_err();
        assert_eq!(error.status, 404);
    }

    #[test]
    fn open_request_deserializes_viewport() {
        let request: OpenWindowRequest =
            serde_json::from_str(r#"{"url":"example.com","viewport":"mobile"}"#).unwrap();
        assert_eq!(request.viewport, Viewport::Mobile);
    }

    /// A sink that completes every dispatched command immediately, so endpoint
    /// round-trips can be tested without a real event loop.
    struct ReplyingSink;

    impl EventSink for ReplyingSink {
        fn send_user_event(&self, event: UserEvent) -> Result<(), String> {
            match event {
                UserEvent::Window { reply, .. } => {
                    let _ = reply.send(Ok(true));
                }
                UserEvent::Screenshot { slot, done, .. } => {
                    *slot.lock().unwrap() = Some(Ok("Zm9v".to_string()));
                    let _ = done.send(());
                }
                UserEvent::Close { reply, .. } => {
                    let _ = reply.send(Ok(true));
                }
                UserEvent::Open { reply, .. } => {
                    let _ = reply.send(Ok(9));
                }
                UserEvent::Shutdown => {}
            }
            Ok(())
        }
    }

    #[test]
    fn viewport_endpoint_round_trips_a_preset() {
        let shared = state();
        let reply = handle(
            &Method::Post,
            "/api/web/windows/4/viewport",
            "",
            r#"{"viewport":"mobile"}"#,
            &shared,
            &ReplyingSink,
        )
        .unwrap();
        assert_eq!(reply["ok"], json!(true));
        assert_eq!(reply["viewport"], json!("mobile"));
        assert_eq!(reply["size"], json!([390, 844]));
    }

    #[test]
    fn viewport_endpoint_refuses_half_a_pair() {
        let shared = state();
        let error = handle(
            &Method::Post,
            "/api/web/windows/4/viewport",
            "",
            r#"{"width":390}"#,
            &shared,
            &ReplyingSink,
        )
        .unwrap_err();
        assert_eq!(error.status, 400);
        let error = handle(
            &Method::Post,
            "/api/web/windows/4/viewport",
            "",
            "not json",
            &shared,
            &ReplyingSink,
        )
        .unwrap_err();
        assert_eq!(error.status, 400);
    }

    #[test]
    fn screenshot_endpoint_returns_the_base64_payload() {
        let shared = state();
        let reply = handle(
            &Method::Get,
            "/api/web/windows/2/screenshot",
            "",
            "",
            &shared,
            &ReplyingSink,
        )
        .unwrap();
        assert_eq!(reply["ok"], json!(true));
        assert_eq!(reply["format"], json!("jpeg"));
        assert_eq!(reply["dataBase64"], json!("Zm9v"));
    }

    #[test]
    fn screenshot_endpoint_reports_capture_failures() {
        struct FailingSink;
        impl EventSink for FailingSink {
            fn send_user_event(&self, event: UserEvent) -> Result<(), String> {
                if let UserEvent::Screenshot { slot, done, .. } = event {
                    *slot.lock().unwrap() =
                        Some(Err("window capture is macOS-only right now".to_string()));
                    let _ = done.send(());
                }
                Ok(())
            }
        }
        let shared = state();
        let error = handle(
            &Method::Get,
            "/api/web/windows/2/screenshot",
            "",
            "",
            &shared,
            &FailingSink,
        )
        .unwrap_err();
        assert_eq!(error.status, 500);
        assert!(error.message.contains("macOS-only"));
    }
}
