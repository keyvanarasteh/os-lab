//! os-lab desktop app.
//!
//! The dashboard (`dashboard/`) is the UI and the os-lab console is the backend. This crate is
//! the glue: a local launcher page (`ui/`) calls `console_start`, which finds an os-lab root,
//! starts `android-lab/lab/web_ui.py` on a free loopback port and returns its URL; the launcher
//! then hands the window to the dashboard. Every dashboard page and lab action therefore works
//! exactly as it does in `./labctl ui`: the same server, the same preview → token → run flow.
//!
//! The dashboard page is a plain web page on `127.0.0.1` and gets no Tauri IPC
//! (`capabilities/launcher.json` names the launcher window only). Links that leave the console
//! open in the system browser.

mod console;
mod container_runtime;
mod deeplink;
mod python_runtime;
mod runtime;
mod widget;

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tauri::{AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder};
use tauri::menu::{MenuBuilder, SubmenuBuilder};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_store::StoreExt;
use tauri_plugin_updater::UpdaterExt;

use console::{Console, Started};
use runtime::Source;

const STORE: &str = "settings.json";
const ROOT_KEY: &str = "root";
const FILES_DIR_KEY: &str = "files_dir";
const CONTAINER_WARNING_KEY: &str = "container_warning_hidden";

fn data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let default = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let selected = app.store(STORE).map_err(|e| e.to_string())?
        .get(FILES_DIR_KEY)
        .and_then(|value| value.as_str().map(PathBuf::from));
    Ok(selected.unwrap_or(default))
}

/// Copy all app-owned files before changing locations. Refuse a populated destination so an
/// unrelated folder or an older installation cannot be silently mixed with the current data.
fn copy_files_dir(from: &Path, to: &Path) -> Result<(), String> {
    let from = fs::canonicalize(from).map_err(|e| format!("Could not read {}: {e}", from.display()))?;
    let to = fs::canonicalize(to).map_err(|e| format!("Could not read {}: {e}", to.display()))?;
    if to == from || to.starts_with(&from) || from.starts_with(&to) {
        return Err("Choose a separate folder outside the current os-lab files folder.".into());
    }
    if fs::read_dir(&to).map_err(|e| e.to_string())?.next().is_some() {
        return Err("Choose an empty folder for the os-lab files.".into());
    }
    fn copy_tree(from: &Path, to: &Path, old_root: &Path, new_root: &Path) -> Result<(), String> {
        for entry in fs::read_dir(from).map_err(|e| e.to_string())? {
            let entry = entry.map_err(|e| e.to_string())?;
            let kind = entry.file_type().map_err(|e| e.to_string())?;
            let dest = to.join(entry.file_name());
            if kind.is_dir() {
                fs::create_dir(&dest).map_err(|e| format!("Could not create {}: {e}", dest.display()))?;
                copy_tree(&entry.path(), &dest, old_root, new_root)?;
            } else if kind.is_file() {
                fs::copy(entry.path(), &dest).map_err(|e| format!("Could not copy {}: {e}", dest.display()))?;
            } else if kind.is_symlink() {
                let link = fs::read_link(entry.path()).map_err(|e| e.to_string())?;
                let resolved = link.canonicalize().unwrap_or_else(|_| link.clone());
                let link = if link.is_absolute() && resolved.starts_with(old_root) {
                    new_root.join(resolved.strip_prefix(old_root).map_err(|e| e.to_string())?)
                } else { link };
                #[cfg(unix)]
                std::os::unix::fs::symlink(&link, &dest).map_err(|e| format!("Could not copy link {}: {e}", dest.display()))?;
                #[cfg(windows)]
                {
                    let source = entry.path();
                    let make = if source.is_dir() { std::os::windows::fs::symlink_dir } else { std::os::windows::fs::symlink_file };
                    make(&link, &dest).map_err(|e| format!("Could not copy link {}: {e}", dest.display()))?;
                }
            } else {
                return Err(format!("Cannot move special file {}.", entry.path().display()));
            }
        }
        Ok(())
    }
    copy_tree(&from, &to, &from, &to)?;
    // The managed interpreter record contains an absolute path, unlike the copied files.
    let record = from.join("python-path.txt");
    if let Ok(saved) = fs::read_to_string(record) {
        let path = PathBuf::from(saved.trim());
        let path = path.canonicalize().unwrap_or(path);
        if let Ok(relative) = path.strip_prefix(&from) {
            if relative.starts_with("python") && to.join(relative).is_file() {
                fs::write(to.join("python-path.txt"), to.join(relative).display().to_string())
                    .map_err(|e| format!("Could not update managed Python path: {e}"))?;
            }
        }
    }
    Ok(())
}

fn log_dir(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(data_dir(app)?.join("logs"))
}

fn chosen_root(app: &AppHandle) -> Option<PathBuf> {
    let store = app.store(STORE).ok()?;
    let value = store.get(ROOT_KEY)?;
    let path = PathBuf::from(value.as_str()?);
    runtime::is_root(&path).then_some(path)
}

/// Env → chosen checkout → development checkout → the bundled runtime in the data folder.
fn resolve_root(app: &AppHandle) -> Result<(PathBuf, Source), String> {
    resolve_root_reporting(app, &mut |_| {})
}

/// `resolve_root`, reporting how far the bundled files are along (only the bundled copy has any
/// work to report; a checkout or chosen folder is used as it is).
fn resolve_root_reporting(
    app: &AppHandle,
    report: &mut dyn FnMut(runtime::SyncProgress),
) -> Result<(PathBuf, Source), String> {
    if let Some(dir) = std::env::var_os("OSLAB_ROOT") {
        let dir = PathBuf::from(dir);
        return if runtime::is_root(&dir) {
            Ok((dir, Source::Env))
        } else {
            Err(format!("OSLAB_ROOT ({}) is not an os-lab checkout (labctl, console/ and android-lab/ are missing).", dir.display()))
        };
    }
    if let Some(dir) = chosen_root(app) {
        return Ok((dir, Source::Chosen));
    }
    if let Some(dir) = runtime::dev_checkout() {
        return Ok((dir, Source::Checkout));
    }
    let bundle = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("os-lab");
    let target = data_dir(app)?.join("os-lab");
    runtime::sync_bundle_reporting(&bundle, &target, &app.package_info().version.to_string(), report)?;
    Ok((target, Source::Bundled))
}

#[tauri::command]
async fn console_start(app: AppHandle, state: State<'_, Console>) -> Result<Started, String> {
    // Preparing the files can take minutes on a busy disk, so it runs off the async workers and
    // tells the launcher how far along it is (events: "console-progress").
    let progress_app = app.clone();
    let (root, source) = tauri::async_runtime::spawn_blocking(move || {
        let mut last = std::time::Instant::now() - std::time::Duration::from_secs(1);
        resolve_root_reporting(&progress_app, &mut |p| {
            // At most ~10 events a second, but never drop the first or the last of a phase.
            let edge = p.done == 0 || (p.total > 0 && p.done >= p.total);
            if edge || last.elapsed() >= std::time::Duration::from_millis(100) {
                last = std::time::Instant::now();
                let phase = match p.phase { runtime::SyncPhase::Check => "check", runtime::SyncPhase::Copy => "copy" };
                let _ = progress_app.emit("console-progress", serde_json::json!({
                    "step": "prepare", "phase": phase, "done": p.done, "total": p.total,
                }));
            }
        })
    })
    .await
    .map_err(|e| e.to_string())??;
    let _ = app.emit("console-progress", serde_json::json!({ "step": "console", "phase": "start", "done": 0, "total": 0 }));
    // Downloaded content packs (console/content.py) live in the app's data folder, beside but
    // never inside the bundled copy, so "reset" always returns to what shipped.
    let content = std::env::var_os("OSLAB_CONTENT_DIR").map(PathBuf::from)
        .unwrap_or(data_dir(&app)?.join("content"));
    let log = console::log_path(&log_dir(&app)?);
    let data = data_dir(&app)?;
    let version = app.package_info().version.to_string();
    let console = state.inner().clone();
    let mut started = tauri::async_runtime::spawn_blocking(move || console.start(&root, source, &log, &data, &content, &version))
        .await
        .map_err(|e| e.to_string())??;
    started.route = widget::consume_pending_mac_lab_intent()
        .map(|request| request.dashboard_route().to_string());
    Ok(started)
}

#[tauri::command]
fn console_files_dir(app: AppHandle) -> Result<String, String> {
    Ok(data_dir(&app)?.display().to_string())
}

/// Choose an empty location and copy the current files before changing the saved path.
#[tauri::command]
async fn console_choose_files_dir(app: AppHandle, state: State<'_, Console>) -> Result<Option<String>, String> {
    let app2 = app.clone();
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app2.dialog().file().set_title("Choose an empty folder for os-lab files").blocking_pick_folder()
    }).await.map_err(|e| e.to_string())?;
    let Some(picked) = picked else { return Ok(None) };
    let target = picked.into_path().map_err(|e| e.to_string())?;
    let current = data_dir(&app)?;
    fs::create_dir_all(&current).map_err(|e| format!("Could not prepare {}: {e}", current.display()))?;
    state.stop();
    let from = current.clone();
    let to = target.clone();
    tauri::async_runtime::spawn_blocking(move || copy_files_dir(&from, &to))
        .await.map_err(|e| e.to_string())??;
    let store = app.store(STORE).map_err(|e| e.to_string())?;
    store.set(FILES_DIR_KEY, target.display().to_string());
    store.save().map_err(|e| e.to_string())?;
    Ok(Some(target.display().to_string()))
}

/// Download a managed CPython only after an explicit launcher action.
#[tauri::command]
async fn python_install(app: AppHandle) -> Result<String, String> {
    let helper = app.path().resource_dir().map_err(|e| e.to_string())?
        .join("tools").join(python_runtime::helper_name()?);
    let data = data_dir(&app)?;
    tauri::async_runtime::spawn_blocking(move || python_runtime::install(&helper, &data))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn container_status() -> Result<container_runtime::Status, String> {
    tauri::async_runtime::spawn_blocking(container_runtime::status)
        .await.map_err(|e| e.to_string())
}

/// The launcher's "don't show this warning next time" preference. Only the automatic start reads
/// it; an explicit retry or the File menu still shows the current status.
#[tauri::command]
fn container_warning_hidden(app: AppHandle) -> Result<bool, String> {
    let store = app.store(STORE).map_err(|e| e.to_string())?;
    Ok(store.get(CONTAINER_WARNING_KEY).and_then(|value| value.as_bool()).unwrap_or(false))
}

/// Persist the launcher preference. Removing the key when unchecked keeps settings.json clean and
/// makes the default visible.
#[tauri::command]
fn container_warning_set_hidden(app: AppHandle, hidden: bool) -> Result<(), String> {
    let store = app.store(STORE).map_err(|e| e.to_string())?;
    if hidden {
        store.set(CONTAINER_WARNING_KEY, true);
    } else {
        store.delete(CONTAINER_WARNING_KEY);
    }
    store.save().map_err(|e| e.to_string())
}

#[tauri::command]
async fn container_recover() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(container_runtime::recover)
        .await.map_err(|e| e.to_string())?
}

/// Fetch a Docker installer whose SHA-256 is pinned to Docker's release notes, then open it.
#[tauri::command]
async fn container_get(app: AppHandle) -> Result<String, String> {
    let data = data_dir(&app)?;
    let python = console::find_python(&data)?;
    let path = tauri::async_runtime::spawn_blocking(move || container_runtime::download(&python, &data))
        .await.map_err(|e| e.to_string())??;
    app.opener().open_path(path.to_string_lossy().into_owned(), None::<String>)
        .map_err(|e| format!("Docker Desktop was downloaded but could not be opened: {e}"))?;
    Ok(path.display().to_string())
}

/// The app's own bundle: the .app that contains this executable, or None when run unbundled (dev).
#[cfg_attr(target_os = "linux", allow(dead_code))]
fn own_bundle() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    exe.ancestors().find(|p| p.extension().map_or(false, |e| e == "app")).map(PathBuf::from)
}

/// Grant helper for the dashboard's Full Disk Access guide: relaunch this app so a fresh grant
/// takes effect. Takes no argument from the page; it only restarts the app it is running in.
#[tauri::command]
fn app_relaunch(app: AppHandle) {
    app.restart();
}

/// Grant helper: start a native drag of this app's own icon so the page can offer drag-to-Settings.
/// The dragged path is never supplied by the page; it is always this app's bundle.
#[tauri::command]
#[cfg(not(target_os = "linux"))]
fn app_drag_self(window: tauri::WebviewWindow) -> Result<(), String> {
    let bundle = own_bundle().ok_or("Not running from an app bundle")?;
    let icon = drag::Image::Raw(include_bytes!("../icons/32x32.png").to_vec());
    drag::start_drag(&window, drag::DragItem::Files(vec![bundle]), icon, |_, _| {}, drag::Options::default())
        .map_err(|e| e.to_string())
}

/// Linux has no Full Disk Access grant to drag into, and the `drag` crate wants a GTK window there.
#[tauri::command]
#[cfg(target_os = "linux")]
fn app_drag_self() -> Result<(), String> {
    Err("Dragging the app is only available on macOS and Windows".into())
}

#[tauri::command]
fn console_status(state: State<'_, Console>) -> Option<String> {
    state.running_url()
}

#[tauri::command]
fn console_restart(state: State<'_, Console>) {
    state.stop();
}

#[tauri::command]
fn console_logs(app: AppHandle) -> Result<String, String> {
    Ok(console::tail(&console::log_path(&log_dir(&app)?), 200))
}

/// The updater accepts only release artifacts signed by the key embedded in tauri.conf.json.
#[derive(serde::Serialize)]
struct UpdateOffer {
    version: String,
    installable: bool,
}

#[tauri::command]
async fn app_update_check(app: AppHandle) -> Result<Option<UpdateOffer>, String> {
    app.updater().map_err(|e| e.to_string())?
        .check().await.map_err(|e| e.to_string())
        .map(|update| update.map(|item| UpdateOffer {
            version: item.version,
            installable: cfg!(not(target_os = "linux")) || std::env::var_os("APPIMAGE").is_some(),
        }))
}

#[tauri::command]
async fn app_update_install(app: AppHandle) -> Result<(), String> {
    #[cfg(target_os = "linux")]
    if std::env::var_os("APPIMAGE").is_none() {
        return Err("Debian and RPM installs must be updated with their package manager. Download the new package from the app release.".into());
    }
    let Some(update) = app.updater().map_err(|e| e.to_string())?
        .check().await.map_err(|e| e.to_string())? else {
        return Err("No newer app version is available.".into());
    };
    let progress_app = app.clone();
    update.download_and_install(
        move |chunk, total| {
            let _ = progress_app.emit("app-update-progress", serde_json::json!({
                "chunk": chunk,
                "total": total,
            }));
        },
        || {},
    ).await.map_err(|e| e.to_string())?;
    app.restart();
}

/// Pick an os-lab checkout to run instead of the bundled copy. Returns the path, or None when
/// the dialog was cancelled.
#[tauri::command]
async fn console_choose_root(app: AppHandle, state: State<'_, Console>) -> Result<Option<String>, String> {
    let app2 = app.clone();
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app2.dialog().file().set_title("Choose your os-lab checkout").blocking_pick_folder()
    })
    .await
    .map_err(|e| e.to_string())?;
    let Some(picked) = picked else { return Ok(None) };
    let path = picked.into_path().map_err(|e| e.to_string())?;
    if !runtime::is_root(&path) {
        return Err(format!(
            "{} is not an os-lab checkout: labctl, console/oslab.py and android-lab/lab/web_ui.py must exist.",
            path.display()
        ));
    }
    let store = app.store(STORE).map_err(|e| e.to_string())?;
    store.set(ROOT_KEY, path.display().to_string());
    store.save().map_err(|e| e.to_string())?;
    state.stop();
    Ok(Some(path.display().to_string()))
}

/// Forget the chosen checkout and go back to the bundled copy.
#[tauri::command]
fn console_reset_root(app: AppHandle, state: State<'_, Console>) -> Result<(), String> {
    let store = app.store(STORE).map_err(|e| e.to_string())?;
    store.delete(ROOT_KEY);
    store.save().map_err(|e| e.to_string())?;
    state.stop();
    Ok(())
}

/// Loopback pages stay in the window; everything else leaves for the system browser.
fn is_internal(url: &url::Url) -> bool {
    match url.scheme() {
        "tauri" | "asset" | "about" | "blob" | "data" => true,
        "http" | "https" => matches!(url.host_str(), Some("127.0.0.1") | Some("localhost") | Some("tauri.localhost") | Some("::1") | Some("[::1]")),
        _ => false,
    }
}

fn open_external(app: &AppHandle, url: &url::Url) {
    if matches!(url.scheme(), "http" | "https" | "mailto") {
        let _ = app.opener().open_url(url.as_str(), None::<&str>);
    }
}

fn build_window(app: &AppHandle, settings: Option<&str>) -> tauri::Result<()> {
    if let Some(old) = app.get_webview_window("main") {
        let _ = old.destroy();
    }
    let nav = app.clone();
    let popup = app.clone();
    let page = match settings {
        Some("files") => "index.html?settings=files",
        Some("updates") => "index.html?settings=updates",
        Some("container") => "index.html?settings=container",
        _ => "index.html",
    };
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App(page.into()))
        .title("os-lab")
        .inner_size(1280.0, 840.0)
        .min_inner_size(420.0, 560.0)
        .on_navigation(move |url| {
            if is_internal(url) {
                true
            } else {
                open_external(&nav, url);
                false
            }
        })
        .on_page_load(|window, payload| {
            // AGQ-01: once the dashboard page exists, replay any command that
            // arrived before the console (or the page) was ready.
            if window.label() == "main" && payload.event() == tauri::webview::PageLoadEvent::Finished {
                bridge::resume(window.app_handle());
            }
        })
        .on_new_window(move |url, _features| {
            if is_internal(&url) {
                // A new window for a console page (target=_blank): keep it in this window.
                if let Some(w) = popup.get_webview_window("main") {
                    let _ = w.eval(format!("window.location.href = {}", serde_json::to_string(url.as_str()).unwrap_or_default()));
                }
            } else {
                open_external(&popup, &url);
            }
            tauri::webview::NewWindowResponse::Deny
        })
        .build()?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    container_runtime::augment_path();
    let app = tauri::Builder::default()
        // AGQ-01: on Linux and Windows a command button starts a second instance
        // whose only argument is the URL. The deep-link plugin is not built with
        // its `deep-link` feature here, so nothing would forward that argument;
        // this callback parses the URL itself.
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
            for arg in argv.iter().skip(1) {
                if let Ok(url) = url::Url::parse(arg) {
                    bridge::route(app, &url);
                }
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_deep_link::init())
        .manage(Console::new())
        .on_menu_event(|app, event| {
            if event.id().as_ref() == "files_settings" {
                app.state::<Console>().stop();
                let _ = build_window(app, Some("files"));
            } else if event.id().as_ref() == "container_settings" {
                app.state::<Console>().stop();
                let _ = build_window(app, Some("container"));
            } else if event.id().as_ref() == "check_updates" {
                app.state::<Console>().stop();
                let _ = build_window(app, Some("updates"));
            }
        })
        .invoke_handler(tauri::generate_handler![
            console_start,
            console_status,
            console_restart,
            app_relaunch,
            app_drag_self,
            console_choose_root,
            console_reset_root,
            console_logs,
            console_files_dir,
            console_choose_files_dir,
            python_install,
            container_status,
            container_warning_hidden,
            container_warning_set_hidden,
            container_recover,
            container_get,
            app_update_check,
            app_update_install
        ])
        .setup(|app| {
            let file_menu = SubmenuBuilder::new(app, "File")
                .text("files_settings", "Files folder…")
                .text("container_settings", "Container setup…")
                .text("check_updates", "Check for app updates…")
                .separator()
                .quit()
                .build()?;
            let menu = MenuBuilder::new(app).item(&file_menu).build()?;
            app.set_menu(menu)?;
            build_window(app.handle(), None)?;
            // CLW-04: reload the macOS widgets whenever the console publishes
            // a new snapshot; CLW-03: oslab:// deep links route in place.
            widget::start_reload_watcher();
            let nav = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    bridge::route(&nav, &url);
                }
            });
            // AGQ-01: a command button may have started the app. The console is
            // not up yet, so the URLs wait for the first dashboard page load.
            if let Ok(Some(urls)) = app.deep_link().get_current() {
                for url in urls {
                    bridge::route(app.handle(), &url);
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the os-lab app");

    app.run(|handle, event| {
        if let tauri::RunEvent::Exit = event {
            // Stop the console (and the jobs in its process group) with the app.
            handle.state::<Console>().stop();
        }
        if let tauri::RunEvent::WindowEvent { event: tauri::WindowEvent::Focused(true), .. } = event {
            // CLW-05: the widget's quick-clean intent opens the app; its
            // request is picked up once, on focus, while it is still fresh.
            if let Some(w) = handle.get_webview_window("main") {
                let on_dashboard = w.url().map(|u| u.scheme() == "http" || u.scheme() == "https").unwrap_or(false);
                if on_dashboard && widget::consume_pending_quick_clean() {
                    let _ = w.eval("window.__oslabQuickClean && window.__oslabQuickClean()");
                }
                if on_dashboard {
                    if let Some(request) = widget::consume_pending_mac_lab_intent() {
                        bridge::open_path(handle, request.dashboard_route());
                    }
                }
            }
            widget::reload_timelines();
        }
    });
}

/// AGQ-01: the command bridge. One place decides what an `oslab://` URL does,
/// whether it arrived from a second instance, a deep link, or the command line.
///
/// Two rules keep this honest:
/// - Navigation is a whitelisted route; an unknown one is reported, never
///   navigated blind.
/// - `panic-stop` runs against the console's own endpoint, so its validation
///   and reply are the only source of truth. Every outcome — including a
///   refusal or a failure — reaches the page and is shown.
///
/// `quick-clean` is deliberately a page flow, not an endpoint call: the bridge
/// opens Cleanup and the page's existing plan → confirm dialog runs, so a
/// command button can never delete anything on its own.
mod bridge {
    use super::*;

    /// A command that arrived before the console answered: the first dashboard
    /// page load replays it. One at a time; the newest wins.
    static PENDING: Mutex<Option<url::Url>> = Mutex::new(None);
    /// What the dashboard still has to be told.
    static OUTBOX: Mutex<Vec<Directive>> = Mutex::new(Vec::new());

    /// A request the page renders in the user's language.
    #[derive(Clone, Default, serde::Serialize)]
    #[serde(rename_all = "camelCase")]
    pub struct Directive {
        /// `navigate`, `quick-clean`, `panic-stop`, or `refused`.
        pub command: String,
        /// Drawer route for `navigate` (a whitelisted widget route).
        #[serde(skip_serializing_if = "Option::is_none")]
        pub route: Option<String>,
        /// Whether the action succeeded; absent for navigation.
        #[serde(skip_serializing_if = "Option::is_none")]
        pub ok: Option<bool>,
        /// The console's own error text, or the closed-session count.
        #[serde(skip_serializing_if = "Option::is_none")]
        pub detail: Option<String>,
        /// The refused URL, verbatim.
        #[serde(skip_serializing_if = "Option::is_none")]
        pub url: Option<String>,
    }

    impl Directive {
        fn navigate(route: &str) -> Self {
            Directive { command: "navigate".into(), route: Some(route.into()), ..Default::default() }
        }
        fn quick_clean() -> Self {
            Directive { command: "quick-clean".into(), ok: Some(true), ..Default::default() }
        }
        fn action(command: &str, result: Result<String, String>) -> Self {
            match result {
                Ok(body) => Directive {
                    command: command.into(),
                    ok: Some(true),
                    detail: session_summary(&body),
                    ..Default::default()
                },
                Err(message) => Directive {
                    command: command.into(),
                    ok: Some(false),
                    detail: Some(message),
                    ..Default::default()
                },
            }
        }
        fn refused(url: &str) -> Self {
            Directive { command: "refused".into(), url: Some(url.to_string()), ..Default::default() }
        }
    }

    /// Parse and act on one URL.
    pub fn route(app: &AppHandle, raw: &url::Url) {
        if raw.scheme() != "oslab" {
            return;
        }
        // A command from another app must be visible, not a hidden state change.
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.unminimize();
            let _ = w.show();
            let _ = w.set_focus();
        }
        let directive = match deeplink::parse_command(raw) {
            deeplink::Command::Navigate(route) => {
                navigate(app, &route);
                Directive::navigate(&route)
            }
            deeplink::Command::Action("quick-clean") => {
                // The dashboard's Cleanup page owns the plan → confirm dialog, so
                // the bridge opens it and the page's own flow takes over.
                //
                // Ordering matters: when this needs a page change, the directive
                // waits in the outbox and `flush` delivers it on the page's own
                // load event. The page, not a timer, decides when it is ready.
                if on_cleanup_dashboard(app) {
                    Directive::quick_clean()
                } else {
                    navigate(app, "dashboard");
                    enqueue(Directive::quick_clean());
                    return;
                }
            }
            deeplink::Command::Action(action) => match deeplink::endpoint(action) {
                Some(endpoint) if console_port(app).is_some() => {
                    let port = console_port(app).expect("checked above");
                    Directive::action(action, console::post_action(port, endpoint))
                }
                // The console is still starting: remember the request and report
                // once the dashboard is up, rather than dropping the click.
                _ => {
                    defer(app, raw);
                    return;
                }
            },
            deeplink::Command::Unknown => Directive::refused(&raw.to_string()),
        };
        deliver(app, directive);
    }

    /// Hand one directive to the page. `eval` (not an event) so a page that
    /// mounted after the command still receives it exactly once.
    fn deliver(app: &AppHandle, directive: Directive) {
        let Some(w) = app.get_webview_window("main") else {
            if let Ok(mut outbox) = OUTBOX.lock() {
                outbox.push(directive);
            }
            return;
        };
        let payload = serde_json::to_string(&directive).unwrap_or_else(|_| "null".into());
        if w.eval(format!("window.__oslabCommand && window.__oslabCommand({payload})")).is_err() {
            if let Ok(mut outbox) = OUTBOX.lock() {
                outbox.push(directive);
            }
        }
    }

    /// Send whatever an earlier command left behind. Called on each dashboard
    /// page load, so the order is always: page exists, then directive.
    pub fn flush(app: &AppHandle) {
        let directives = OUTBOX.lock().map(|mut outbox| std::mem::take(&mut *outbox)).unwrap_or_default();
        for directive in directives {
            deliver(app, directive);
        }
    }

    /// Is the window already on the Cleanup dashboard (in any locale)?
    fn on_cleanup_dashboard(app: &AppHandle) -> bool {
        let Some(w) = app.get_webview_window("main") else { return false };
        let Ok(url) = w.url() else { return false };
        if !matches!(url.scheme(), "http" | "https") {
            return false;
        }
        url.path().split('/').rev().find(|part| !part.is_empty()).map(|part| part == "cleanup")
            .unwrap_or(false)
    }

    fn enqueue(directive: Directive) {
        if let Ok(mut outbox) = OUTBOX.lock() {
            outbox.push(directive);
        }
    }

    fn defer(app: &AppHandle, raw: &url::Url) {
        let _ = app;
        if let Ok(mut pending) = PENDING.lock() {
            *pending = Some(raw.clone());
        }
    }

    /// Replay the command that arrived before the console was ready.
    pub fn resume(app: &AppHandle) {
        flush(app);
        let pending = PENDING.lock().ok().and_then(|mut pending| pending.take());
        if let Some(url) = pending {
            route(app, &url);
        }
    }

    /// A path-free summary of the console's reply: how many deep-inspect
    /// sessions the stop closed.
    fn session_summary(body: &str) -> Option<String> {
        let value = serde_json::from_str::<serde_json::Value>(body).ok()?;
        let closed = value.get("sessionsClosed")?.as_array()?.len();
        Some(closed.to_string())
    }

    /// Open a dashboard path that is not a widget route (the macOS Lab page the
    /// App Intent targets), keeping the current locale prefix.
    pub fn open_path(app: &AppHandle, path: &str) {
        let Some(w) = app.get_webview_window("main") else { return };
        let Some(base) = app.state::<Console>().running_url() else { return };
        let path = w.url().ok().map(|current| localized_dashboard_path(&current, path))
            .unwrap_or_else(|| path.trim_start_matches('/').to_string());
        if let Ok(url) = url::Url::parse(&format!("{}/{path}", base.trim_end_matches('/'))) {
            let _ = w.navigate(url);
        }
    }

    fn console_port(app: &AppHandle) -> Option<u16> {
        url::Url::parse(&app.state::<Console>().running_url()?).ok()?.port()
    }

    fn navigate(app: &AppHandle, route: &str) {
        let Some(w) = app.get_webview_window("main") else { return };
        let on_dashboard = w.url().map(|u| u.scheme() == "http" || u.scheme() == "https").unwrap_or(false);
        if on_dashboard && deeplink::CLEANUP_ROUTES.contains(&route) {
            // The island router handles cleanup routes in place, without a reload.
            let _ = w.eval(format!(
                "window.__oslabNavigate && window.__oslabNavigate({})",
                serde_json::to_string(route).unwrap_or_default()
            ));
            return;
        }
        let Some(base) = app.state::<Console>().running_url() else { return };
        let path = deeplink::dashboard_path(route);
        let path = w.url().ok().map(|current| localized_dashboard_path(&current, &path)).unwrap_or(path);
        if let Ok(url) = url::Url::parse(&format!("{}/{path}", base.trim_end_matches('/'))) {
            let _ = w.navigate(url);
        }
    }
}

fn localized_dashboard_path(current: &url::Url, path: &str) -> String {
    const LOCALES: [&str; 7] = ["tr", "de", "fr", "es", "it", "fa", "ar"];
    let first = current.path_segments().and_then(|mut segments| segments.next()).unwrap_or_default();
    let prefix = if LOCALES.contains(&first) { format!("{first}/") } else { String::new() };
    format!("{prefix}{}", path.trim_start_matches('/'))
}

#[cfg(test)]
mod files_dir_tests {
    use super::*;

    #[test]
    fn relocating_files_copies_state_and_rejects_populated_or_nested_folders() {
        let base = std::env::temp_dir().join(format!("oslab-files-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        let from = base.join("from");
        let to = base.join("to");
        fs::create_dir_all(from.join("os-lab/android-lab/storage")).unwrap();
        fs::create_dir_all(from.join("python/bin")).unwrap();
        fs::create_dir_all(&to).unwrap();
        fs::write(from.join("os-lab/android-lab/storage/disk.img"), "state").unwrap();
        fs::write(from.join("python/bin/python3"), "interpreter").unwrap();
        fs::write(from.join("python-path.txt"), from.join("python/bin/python3").display().to_string()).unwrap();
        #[cfg(unix)]
        std::os::unix::fs::symlink(from.join("python/bin/python3"), from.join("python/bin/python")).unwrap();
        copy_files_dir(&from, &to).unwrap();
        let canonical_to = to.canonicalize().unwrap();
        assert_eq!(fs::read_to_string(to.join("os-lab/android-lab/storage/disk.img")).unwrap(), "state");
        assert_eq!(fs::read_to_string(to.join("python-path.txt")).unwrap(), canonical_to.join("python/bin/python3").display().to_string());
        assert_eq!(python_runtime::saved_python(&to).unwrap(), canonical_to.join("python/bin/python3").display().to_string());
        #[cfg(unix)]
        assert_eq!(fs::read_link(to.join("python/bin/python")).unwrap(), canonical_to.join("python/bin/python3"));
        assert!(copy_files_dir(&from, &to).unwrap_err().contains("empty folder"));
        assert!(copy_files_dir(&from, &from.join("os-lab")).unwrap_err().contains("separate folder"));
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn app_intent_routes_preserve_the_dashboard_locale() {
        let english = url::Url::parse("http://127.0.0.1:4330/cleanup/").unwrap();
        let turkish = url::Url::parse("http://127.0.0.1:4330/tr/cleanup/").unwrap();
        assert_eq!(localized_dashboard_path(&english, "labs/macos/"), "labs/macos/");
        assert_eq!(localized_dashboard_path(&turkish, "labs/macos/#intent=panic-stop"),
                   "tr/labs/macos/#intent=panic-stop");
        assert_eq!(localized_dashboard_path(&turkish, "labs/macos/#intent=verify-submission"),
                   "tr/labs/macos/#intent=verify-submission");
    }
}
