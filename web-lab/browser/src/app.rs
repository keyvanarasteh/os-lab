//! Main-thread application: owns the tao event loop, the wry windows and every
//! webview. Windows are only ever created or touched inside the event loop, while
//! the control HTTP thread talks to it through `EventLoopProxy` commands.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};

use serde_json::json;
use tao::event::WindowEvent;
use tao::event_loop::{ControlFlow, EventLoopWindowTarget};
use tao::window::{Window, WindowBuilder, WindowId};
use wry::{PageLoadEvent, WebContext, WebView, WebViewBuilder};

use crate::bootstrap;
use crate::capture::{self, CaptureSlot};
use crate::protocol::{normalize_url, OpenWindowRequest, WindowAction};
use crate::state::{SharedState, WindowMeta};

/// A command from the control HTTP thread into the main-thread event loop.
#[derive(Debug)]
pub enum UserEvent {
    Open {
        request: OpenWindowRequest,
        reply: Sender<Result<u64, String>>,
    },
    Close {
        id: u64,
        reply: Sender<Result<bool, String>>,
    },
    Window {
        id: u64,
        action: WindowAction,
        argument: Option<String>,
        reply: Sender<Result<bool, String>>,
    },
    Screenshot {
        id: u64,
        slot: CaptureSlot,
        done: Sender<()>,
    },
    Shutdown,
}

pub struct App {
    pub state: Arc<Mutex<SharedState>>,
    pub data_root: PathBuf,
    windows: HashMap<u64, WindowHandle>,
}

struct WindowHandle {
    #[allow(dead_code)]
    window: Window,
    webview: WebView,
    /// wry requires the web context to outlive the webview it built.
    _web_context: Option<WebContext>,
}

impl App {
    pub fn new(state: Arc<Mutex<SharedState>>, data_root: PathBuf) -> Self {
        Self {
            state,
            data_root,
            windows: HashMap::new(),
        }
    }

    fn log_event(&self, window_id: Option<u64>, kind: &str, payload: serde_json::Value) {
        self.state
            .lock()
            .expect("engine state poisoned")
            .push_event(window_id, kind, payload);
    }

    pub fn handle_user_event(
        &mut self,
        event: UserEvent,
        window_target: &EventLoopWindowTarget<UserEvent>,
        control_flow: &mut ControlFlow,
    ) {
        match event {
            UserEvent::Open { request, reply } => self.open_window(request, reply, window_target),
            UserEvent::Close { id, reply } => {
                let removed = self.remove_window(id, "closed by console");
                let _ = reply.send(if removed {
                    Ok(true)
                } else {
                    Err(format!("unknown window: {id}"))
                });
            }
            UserEvent::Window {
                id,
                action,
                argument,
                reply,
            } => self.run_window_action(id, &action, &argument, reply),
            UserEvent::Screenshot { id, slot, done } => {
                self.begin_screenshot(id, slot, done);
            }
            UserEvent::Shutdown => {
                self.log_event(None, "engine", json!({ "message": "shutdown requested" }));
                *control_flow = ControlFlow::Exit;
            }
        }
    }

    pub fn handle_window_event(&mut self, window_id: WindowId, event: WindowEvent) {
        if let WindowEvent::CloseRequested = event {
            let id = self
                .windows
                .iter()
                .find(|(_, handle)| handle.window.id() == window_id)
                .map(|(id, _)| *id);
            if let Some(id) = id {
                self.remove_window(id, "user closed the window");
            }
            // Keep serving even when the last window is gone.
        }
    }

    fn remove_window(&mut self, id: u64, reason: &str) -> bool {
        let removed = self.windows.remove(&id).is_some();
        if removed {
            self.state
                .lock()
                .expect("engine state poisoned")
                .windows
                .remove(&id);
            self.log_event(Some(id), "window-closed", json!({ "reason": reason }));
        }
        removed
    }

    fn open_window(
        &mut self,
        request: OpenWindowRequest,
        reply: Sender<Result<u64, String>>,
        window_target: &EventLoopWindowTarget<UserEvent>,
    ) {
        let url = match normalize_url(&request.url) {
            Ok(url) => url,
            Err(error) => {
                let _ = reply.send(Err(error));
                return;
            }
        };
        let (id, injections) = {
            let mut state = self.state.lock().expect("engine state poisoned");
            let id = state.allocate_window_id();
            (id, state.enabled_injections())
        };

        let (width, height) = request.viewport.logical_size();
        let window = match WindowBuilder::new()
            .with_title(format!("Web Lab — window {id}"))
            .with_inner_size(tao::dpi::LogicalSize::new(width, height))
            .build(window_target)
        {
            Ok(window) => window,
            Err(error) => {
                let _ = reply.send(Err(format!("failed to create window: {error}")));
                return;
            }
        };

        // Named persistent profiles get their own data directory; ephemeral profiles
        // run incognito instead. On macOS the system stores persistent data in the
        // shared WKWebsiteDataStore, so directory isolation is honoured on
        // Linux/WebKitGTK and Windows/WebView2 — documented in the lab README.
        let ephemeral = request.profile == "ephemeral";
        let mut web_context = None;
        if !ephemeral {
            let directory = self
                .data_root
                .join("profiles")
                .join(sanitize_profile(&request.profile));
            if let Err(error) = std::fs::create_dir_all(&directory) {
                let _ = reply.send(Err(format!("failed to create profile directory: {error}")));
                return;
            }
            web_context = Some(WebContext::new(Some(directory)));
        }

        let state = Arc::clone(&self.state);
        let navigation_state = Arc::clone(&self.state);
        let page_load_state = Arc::clone(&self.state);
        let ipc_window_id = id;
        let nav_window_id = id;

        let mut builder = match web_context.as_mut() {
            Some(context) => WebViewBuilder::new_with_web_context(context),
            None => WebViewBuilder::new(),
        };
        builder = builder
            .with_url(&url)
            .with_incognito(ephemeral)
            .with_initialization_script(bootstrap::BOOTSTRAP_JS)
            .with_ipc_handler(move |request| {
                let body = request.into_body();
                let message = parse_bridge_message(&body);
                let mut state = state.lock().expect("engine state poisoned");
                match message {
                    Some((kind, payload)) => {
                        state.push_event(Some(ipc_window_id), &kind, payload);
                    }
                    None => {
                        state.push_event(Some(ipc_window_id), "bridge", json!({ "raw": body }));
                    }
                }
            })
            .with_navigation_handler(move |target| {
                navigation_state
                    .lock()
                    .expect("engine state poisoned")
                    .push_event(Some(nav_window_id), "navigation", json!({ "url": target }));
                true
            })
            .with_on_page_load_handler(move |event: PageLoadEvent, url: String| {
                let phase = match event {
                    PageLoadEvent::Started => "started",
                    PageLoadEvent::Finished => "finished",
                };
                let mut state = page_load_state.lock().expect("engine state poisoned");
                if let Some(meta) = state.windows.get_mut(&id) {
                    meta.url = url.clone();
                }
                state.push_event(Some(id), "page-load", json!({ "phase": phase, "url": url }));
            });

        if let Some(user_agent) = request.user_agent.as_ref() {
            builder = builder.with_user_agent(user_agent.clone());
        }

        let webview = match builder.build(&window) {
            Ok(webview) => webview,
            Err(error) => {
                let _ = reply.send(Err(format!("failed to create webview: {error}")));
                return;
            }
        };

        let (meta_width, meta_height) = request.viewport.logical_size();
        let meta = WindowMeta {
            id,
            url,
            profile: request.profile,
            user_agent: request.user_agent,
            viewport: request.viewport.as_str().to_string(),
            size: [meta_width as u32, meta_height as u32],
            created_at: crate::state::now_ms(),
        };
        self.log_event(
            Some(id),
            "window-opened",
            json!({ "url": meta.url, "profile": meta.profile, "viewport": meta.viewport }),
        );
        self.state
            .lock()
            .expect("engine state poisoned")
            .windows
            .insert(id, meta);
        self.windows.insert(
            id,
            WindowHandle {
                window,
                webview,
                _web_context: web_context,
            },
        );
        // Injections captured for future use; this window already received them
        // because initialization scripts are baked in at build time.
        let _ = injections;
        let _ = reply.send(Ok(id));
    }

    /// Ask WebKit for a snapshot of the window's web view. The request is
    /// dispatched here and the completion fills `slot` + pings `done` later on
    /// this same runloop — the control thread waits, this thread never blocks.
    fn begin_screenshot(&mut self, id: u64, slot: CaptureSlot, done: std::sync::mpsc::Sender<()>) {
        let Some(handle) = self.windows.get(&id) else {
            *slot.lock().expect("capture slot poisoned") = Some(Err(format!("unknown window: {id}")));
            let _ = done.send(());
            return;
        };
        let ns_view = {
            #[cfg(target_os = "macos")]
            {
                use tao::platform::macos::WindowExtMacOS;
                handle.window.ns_view()
            }
            #[cfg(not(target_os = "macos"))]
            {
                std::ptr::null_mut()
            }
        };
        let outcome = unsafe { capture::begin_webview_jpeg(ns_view, slot, done) };
        if let Err(message) = outcome {
            // begin_* already reported its own failures into the slot, but a
            // dispatch error here means the slot was never filled.
            self.log_event(Some(id), "error", json!({ "capture": message }));
        }
    }

    fn run_window_action(
        &mut self,
        id: u64,
        action: &WindowAction,
        argument: &Option<String>,
        reply: Sender<Result<bool, String>>,
    ) {
        if let WindowAction::Resize = action {
            self.run_resize(id, argument.as_deref(), reply);
            return;
        }
        let Some(handle) = self.windows.get(&id) else {
            let _ = reply.send(Err(format!("unknown window: {id}")));
            return;
        };
        let result: Result<(), wry::Error> = match (action, argument) {
            (WindowAction::Navigate, Some(url)) => match normalize_url(url) {
                Ok(target) => handle.webview.load_url(&target),
                Err(error) => {
                    let _ = reply.send(Err(error));
                    return;
                }
            },
            (WindowAction::Navigate, None) => {
                let _ = reply.send(Err("navigate needs a url".to_string()));
                return;
            }
            (WindowAction::Eval, Some(code)) => {
                let eval_id = format!("ev-{}", crate::state::now_ms());
                self.state
                    .lock()
                    .expect("engine state poisoned")
                    .push_event(Some(id), "eval-request", json!({ "evalId": eval_id }));
                handle
                    .webview
                    .evaluate_script(&bootstrap::eval_wrapper(&eval_id, code))
            }
            (WindowAction::Eval, None) => {
                let _ = reply.send(Err("eval needs code".to_string()));
                return;
            }
            (WindowAction::Cookies, _) => {
                let eval_id = format!("ck-{}", crate::state::now_ms());
                handle
                    .webview
                    .evaluate_script(&bootstrap::cookie_reader(&eval_id))
            }
            (WindowAction::Storage, _) => {
                let eval_id = format!("st-{}", crate::state::now_ms());
                handle
                    .webview
                    .evaluate_script(&bootstrap::storage_reader(&eval_id))
            }
            (WindowAction::Reload, _) => {
                let url = self
                    .state
                    .lock()
                    .expect("engine state poisoned")
                    .windows
                    .get(&id)
                    .map(|meta| meta.url.clone());
                match url {
                    Some(url) => handle.webview.load_url(&url),
                    None => Ok(()),
                }
            }
            (WindowAction::Back, _) => handle.webview.evaluate_script("history.back();"),
            (WindowAction::Forward, _) => handle.webview.evaluate_script("history.forward();"),
            // Resize is handled above with its own early return; this arm only
            // keeps the match exhaustive.
            (WindowAction::Resize, _) => Ok(()),
        };
        match result {
            Ok(()) => {
                let _ = reply.send(Ok(true));
            }
            Err(error) => {
                let _ = reply.send(Err(format!("window action failed: {error}")));
            }
        }
    }

    /// Resize the window and record the new logical size. The server already
    /// resolved and clamped the request; this only applies it.
    fn run_resize(&mut self, id: u64, argument: Option<&str>, reply: Sender<Result<bool, String>>) {
        let parsed: serde_json::Value = match argument.map(serde_json::from_str) {
            Some(Ok(value)) => value,
            _ => {
                let _ = reply.send(Err("resize needs width and height".to_string()));
                return;
            }
        };
        let (Some(width), Some(height)) = (
            parsed.get("width").and_then(|value| value.as_u64()),
            parsed.get("height").and_then(|value| value.as_u64()),
        ) else {
            let _ = reply.send(Err("resize needs width and height".to_string()));
            return;
        };
        let (Ok(width), Ok(height)) = (u32::try_from(width), u32::try_from(height)) else {
            let _ = reply.send(Err("resize dimensions are out of range".to_string()));
            return;
        };
        let label = parsed
            .get("viewport")
            .and_then(|value| value.as_str())
            .unwrap_or("custom")
            .to_string();
        let Some(handle) = self.windows.get(&id) else {
            let _ = reply.send(Err(format!("unknown window: {id}")));
            return;
        };
        handle.window.set_inner_size(tao::dpi::LogicalSize::new(
            f64::from(width),
            f64::from(height),
        ));
        {
            let mut state = self.state.lock().expect("engine state poisoned");
            if let Some(meta) = state.windows.get_mut(&id) {
                meta.size = [width, height];
                meta.viewport = label.clone();
            }
        }
        self.log_event(
            Some(id),
            "viewport-changed",
            json!({ "viewport": label, "size": [width, height] }),
        );
        let _ = reply.send(Ok(true));
    }
}

/// Bridge messages are `{type, payload}` JSON; page-visible kinds are passed through
/// as events.
fn parse_bridge_message(body: &str) -> Option<(String, serde_json::Value)> {
    let parsed: serde_json::Value = serde_json::from_str(body).ok()?;
    let kind = parsed.get("type")?.as_str()?.to_string();
    let payload = parsed
        .get("payload")
        .cloned()
        .unwrap_or(serde_json::Value::Null);
    Some((kind, payload))
}

fn sanitize_profile(profile: &str) -> String {
    profile
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '-' || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect()
}
