//! CLW-04/05: the macOS widget bridge.
//!
//! The console (Python) writes `widget-snapshot.json` into the shared App
//! Group container; this module is the host's half of the handshake:
//! - `reload_timelines` asks WidgetKit (through the embedded
//!   `OSLabWidgetReloader.framework`, dlopen'd and called over the ObjC
//!   runtime) to re-read the file now instead of waiting for the extension's
//!   15-minute policy.
//! - `consume_pending_quick_clean` picks up the widget intent's request file
//!   once, honouring a max age so a stale request never re-triggers.
//! - the watcher thread reloads whenever the snapshot file changes.
//!
//! Everything degrades honestly: no framework, no container or a non-macOS
//! host simply means "no immediate refresh" — the widget still works on its
//! own timeline policy. The file and group names are the contract shared
//! with `cleanup-lab/engine/cleanup_lab/widget.py` and `app/widget`.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub const GROUP_ID: &str = "group.com.keyvanarasteh.oslab";
pub const SNAPSHOT_FILE_NAME: &str = "widget-snapshot.json";
pub const PENDING_QUICK_CLEAN_NAME: &str = "widget-pending-quick-clean.txt";
pub const PENDING_MAC_LAB_INTENT_NAME: &str = "widget-pending-mac-lab-intent.txt";
/// The widget intent's request expires like the reference app's: an old
/// flag must never surprise the user with a cleanup plan hours later.
pub const PENDING_MAX_AGE_SECS: u64 = 120;
/// Watch cadence for snapshot changes; the reload itself is cheap and idempotent.
pub const RELOAD_WATCH_INTERVAL_SECS: u64 = 10;

/// The App Group container, when it exists on this machine. The engine uses
/// the same override so a dev console and a dev app can share a fixture dir.
fn group_container_dir() -> Option<PathBuf> {
    if let Ok(override_dir) = std::env::var("OSLAB_WIDGET_GROUP_DIR") {
        let path = PathBuf::from(override_dir);
        return path.is_dir().then_some(path);
    }
    if !cfg!(target_os = "macos") {
        return None;
    }
    let home = std::env::var_os("HOME")?;
    let path = PathBuf::from(home).join("Library/Group Containers").join(GROUP_ID);
    path.is_dir().then_some(path)
}

fn snapshot_file_in(dir: &Path) -> PathBuf {
    dir.join(SNAPSHOT_FILE_NAME)
}

fn pending_file_in(dir: &Path) -> PathBuf {
    dir.join(PENDING_QUICK_CLEAN_NAME)
}

fn pending_mac_lab_intent_file_in(dir: &Path) -> PathBuf {
    dir.join(PENDING_MAC_LAB_INTENT_NAME)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MacLabIntentRequest {
    Open,
    VerifySubmission,
    PanicStop,
}

impl MacLabIntentRequest {
    pub fn dashboard_route(self) -> &'static str {
        match self {
            Self::Open => "labs/macos/",
            Self::VerifySubmission => "labs/macos/#intent=verify-submission",
            Self::PanicStop => "labs/macos/#intent=panic-stop",
        }
    }
}

pub fn snapshot_file_path() -> Option<PathBuf> {
    group_container_dir().map(|dir| snapshot_file_in(&dir))
}

/// Consume the widget's quick-clean request: true exactly once per request,
/// and only while it is fresh. A missing, unreadable or stale file is "no".
pub fn consume_pending_quick_clean() -> bool {
    consume_pending_in(group_container_dir().as_deref())
}

/// Consume a fresh App Intent handoff exactly once. Unknown actions, malformed
/// timestamps and stale files fail closed after the request file is removed.
pub fn consume_pending_mac_lab_intent() -> Option<MacLabIntentRequest> {
    consume_pending_mac_lab_intent_in(group_container_dir().as_deref())
}

fn consume_pending_mac_lab_intent_in(dir: Option<&Path>) -> Option<MacLabIntentRequest> {
    let path = dir.map(pending_mac_lab_intent_file_in)?;
    let raw = std::fs::read_to_string(&path).ok()?;
    let _ = std::fs::remove_file(&path);
    let mut fields = raw.split_whitespace();
    let request = match fields.next()? {
        "open" => MacLabIntentRequest::Open,
        "verify-submission" => MacLabIntentRequest::VerifySubmission,
        "panic-stop" => MacLabIntentRequest::PanicStop,
        _ => return None,
    };
    let requested_at = fields.next()?.parse::<f64>().ok()?;
    if fields.next().is_some() || !requested_at.is_finite() || requested_at <= 0.0 {
        return None;
    }
    let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs_f64();
    let age = now - requested_at;
    ((-5.0..=PENDING_MAX_AGE_SECS as f64).contains(&age)).then_some(request)
}

fn consume_pending_in(dir: Option<&Path>) -> bool {
    let Some(path) = dir.map(pending_file_in) else { return false };
    let Ok(raw) = std::fs::read_to_string(&path) else { return false };
    let _ = std::fs::remove_file(&path);
    let Ok(requested_at) = raw.trim().parse::<f64>() else { return false };
    if !requested_at.is_finite() || requested_at <= 0.0 {
        return false;
    }
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    now - requested_at <= PENDING_MAX_AGE_SECS as f64
}

/// Ask WidgetKit to reload every os-lab widget timeline. Returns false when
/// the embedded reloader framework is unavailable (dev builds, other
/// platforms) — the widget then refreshes on its own policy.
#[cfg(target_os = "macos")]
pub fn reload_timelines() -> bool {
    use std::ffi::{c_char, c_void, CString};

    type Id = *mut c_void;
    extern "C" {
        fn dlopen(path: *const c_char, mode: i32) -> *mut c_void;
        fn objc_getClass(name: *const c_char) -> Id;
        fn sel_registerName(name: *const c_char) -> Id;
        fn objc_msgSend(receiver: Id, op: Id);
    }

    // The framework is embedded next to this binary: <exe>/../Frameworks/.
    let Ok(exe) = std::env::current_exe() else { return false };
    let Some(parent) = exe.parent() else { return false };
    let framework = parent.join("../Frameworks/OSLabWidgetReloader.framework/OSLabWidgetReloader");
    let Ok(framework) = CString::new(framework.to_string_lossy().as_bytes()) else { return false };
    // RTLD_NOW (2) | RTLD_LOCAL (0).
    let handle = unsafe { dlopen(framework.as_ptr(), 2) };
    if handle.is_null() {
        return false;
    }
    let Ok(class_name) = CString::new("OSLabWidgetReloader") else { return false };
    let class = unsafe { objc_getClass(class_name.as_ptr()) };
    if class.is_null() {
        return false;
    }
    let Ok(sel_name) = CString::new("reloadAllTimelines") else { return false };
    let sel = unsafe { sel_registerName(sel_name.as_ptr()) };
    if sel.is_null() {
        return false;
    }
    unsafe { objc_msgSend(class, sel) };
    true
}

#[cfg(not(target_os = "macos"))]
pub fn reload_timelines() -> bool {
    false
}

/// Reload when the snapshot file changed, debounced across callers by the
/// file's mtime (the console republishes from several threads).
pub fn reload_if_changed(last_seen: &AtomicU64) -> bool {
    let modified = snapshot_file_path()
        .and_then(|path| std::fs::metadata(&path).ok())
        .and_then(|meta| meta.modified().ok())
        .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);
    let previous = last_seen.swap(modified, Ordering::Relaxed);
    if modified == 0 || modified == previous {
        return false;
    }
    reload_timelines()
}

/// One watcher thread for the app's lifetime: reload the widget whenever the
/// console publishes a new snapshot. A daemon thread — the process exit ends it.
pub fn start_reload_watcher() {
    std::thread::Builder::new()
        .name("oslab-widget-watch".into())
        .spawn(|| {
            let last_seen = AtomicU64::new(0);
            loop {
                std::thread::sleep(Duration::from_secs(RELOAD_WATCH_INTERVAL_SECS));
                let _ = reload_if_changed(&last_seen);
            }
        })
        .ok();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_group(name: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!("oslab-widget-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        base
    }

    #[test]
    fn snapshot_and_pending_live_in_the_group_dir() {
        let base = temp_group("paths");
        assert_eq!(snapshot_file_in(&base), base.join(SNAPSHOT_FILE_NAME));
        assert_eq!(pending_file_in(&base), base.join(PENDING_QUICK_CLEAN_NAME));
        assert_eq!(pending_mac_lab_intent_file_in(&base), base.join(PENDING_MAC_LAB_INTENT_NAME));
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn a_missing_request_is_a_no() {
        let base = temp_group("none");
        assert!(!consume_pending_in(Some(&base)));
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn a_fresh_request_is_consumed_exactly_once() {
        let base = temp_group("fresh");
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64();
        std::fs::write(pending_file_in(&base), format!("{now}")).unwrap();
        assert!(consume_pending_in(Some(&base)));
        // Consumed: the file is gone, a second read is false.
        assert!(!consume_pending_in(Some(&base)));
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn a_stale_request_is_refused_and_cleared() {
        let base = temp_group("stale");
        let stale = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64() - 10_000.0;
        std::fs::write(pending_file_in(&base), format!("{stale}")).unwrap();
        assert!(!consume_pending_in(Some(&base)));
        assert!(!pending_file_in(&base).exists());
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn garbage_requests_are_refused_and_cleared() {
        let base = temp_group("junk");
        std::fs::write(pending_file_in(&base), "not a number").unwrap();
        assert!(!consume_pending_in(Some(&base)));
        assert!(!pending_file_in(&base).exists());
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn mac_lab_requests_are_typed_fresh_and_consumed_once() {
        let base = temp_group("mac-lab");
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64();
        std::fs::write(pending_mac_lab_intent_file_in(&base), format!("panic-stop\n{now}")).unwrap();
        assert_eq!(consume_pending_mac_lab_intent_in(Some(&base)), Some(MacLabIntentRequest::PanicStop));
        assert_eq!(MacLabIntentRequest::PanicStop.dashboard_route(), "labs/macos/#intent=panic-stop");
        assert_eq!(consume_pending_mac_lab_intent_in(Some(&base)), None);
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn submission_verification_routes_to_the_guarded_review_workflow() {
        let base = temp_group("submission-review");
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64();
        std::fs::write(pending_mac_lab_intent_file_in(&base), format!("verify-submission\n{now}")).unwrap();
        assert_eq!(
            consume_pending_mac_lab_intent_in(Some(&base)),
            Some(MacLabIntentRequest::VerifySubmission)
        );
        assert_eq!(
            MacLabIntentRequest::VerifySubmission.dashboard_route(),
            "labs/macos/#intent=verify-submission"
        );
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn stale_or_unknown_mac_lab_requests_fail_closed() {
        let base = temp_group("mac-lab-refuse");
        let stale = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64() - 10_000.0;
        std::fs::write(pending_mac_lab_intent_file_in(&base), format!("open\n{stale}")).unwrap();
        assert_eq!(consume_pending_mac_lab_intent_in(Some(&base)), None);
        assert!(!pending_mac_lab_intent_file_in(&base).exists());
        std::fs::write(pending_mac_lab_intent_file_in(&base), "open\n99999999999").unwrap();
        assert_eq!(consume_pending_mac_lab_intent_in(Some(&base)), None);
        assert!(!pending_mac_lab_intent_file_in(&base).exists());
        std::fs::write(pending_mac_lab_intent_file_in(&base), "arm\n99999999999").unwrap();
        assert_eq!(consume_pending_mac_lab_intent_in(Some(&base)), None);
        assert!(!pending_mac_lab_intent_file_in(&base).exists());
        let _ = std::fs::remove_dir_all(&base);
    }
}
