//! Shared engine state: window metadata, the event log and the injection registry.
//!
//! Everything here is `Send + Sync` on purpose: the control HTTP thread reads and
//! mutates it directly, while the main thread's tao event loop updates it from the
//! webview callbacks (navigation, page load, IPC bridge).

use std::collections::{BTreeMap, VecDeque};

use serde::{Deserialize, Serialize};

/// Ring-buffer capacity for captured page/engine events.
pub const EVENT_LOG_CAPACITY: usize = 5000;

/// Upper bound applied to strings captured from a page (bridge payloads, eval results).
pub const MAX_CAPTURED_BYTES: usize = 8 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Injection {
    pub id: String,
    pub name: String,
    pub code: String,
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Profile {
    pub id: String,
    pub name: String,
    /// Ephemeral profiles run the webview in incognito/private mode; nothing is persisted.
    pub ephemeral: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowMeta {
    pub id: u64,
    pub url: String,
    pub profile: String,
    pub user_agent: Option<String>,
    pub viewport: String,
    /// Current logical size in CSS pixels; the preview panel reads it.
    pub size: [u32; 2],
    pub created_at: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct EventEntry {
    pub seq: u64,
    pub ts: u64,
    pub window_id: Option<u64>,
    pub kind: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, Default)]
pub struct SharedState {
    pub port: u16,
    pub started_at: u64,
    pub next_window_id: u64,
    pub windows: BTreeMap<u64, WindowMeta>,
    pub events: VecDeque<EventEntry>,
    pub injections: Vec<Injection>,
    pub profiles: Vec<Profile>,
    next_event_seq: u64,
}

impl SharedState {
    pub fn new(port: u16) -> Self {
        Self {
            port,
            started_at: now_ms(),
            next_window_id: 1,
            ..Self::default()
        }
    }

    pub fn allocate_window_id(&mut self) -> u64 {
        let id = self.next_window_id;
        self.next_window_id += 1;
        id
    }

    /// Append an event, trimming the ring buffer and truncating oversized payloads.
    pub fn push_event(
        &mut self,
        window_id: Option<u64>,
        kind: &str,
        mut payload: serde_json::Value,
    ) -> u64 {
        truncate_json(&mut payload, MAX_CAPTURED_BYTES);
        self.next_event_seq += 1;
        let seq = self.next_event_seq;
        self.events.push_back(EventEntry {
            seq,
            ts: now_ms(),
            window_id,
            kind: kind.to_string(),
            payload,
        });
        while self.events.len() > EVENT_LOG_CAPACITY {
            self.events.pop_front();
        }
        seq
    }

    /// Events with a sequence number greater than `since`, capped at `limit`.
    pub fn events_since(&self, since: u64, limit: usize) -> Vec<&EventEntry> {
        self.events
            .iter()
            .filter(|entry| entry.seq > since)
            .take(limit)
            .collect()
    }

    pub fn register_injection(&mut self, name: String, code: String) -> Result<Injection, String> {
        let name = name.trim().to_string();
        if name.is_empty() {
            return Err("injection name must not be empty".to_string());
        }
        if code.trim().is_empty() {
            return Err("injection code must not be empty".to_string());
        }
        if let Some(existing) = self.injections.iter_mut().find(|i| i.name == name) {
            existing.code = code;
            existing.enabled = true;
            return Ok(existing.clone());
        }
        let injection = Injection {
            id: format!("inj-{}", now_ms()),
            name,
            code,
            enabled: true,
        };
        self.injections.push(injection.clone());
        Ok(injection)
    }

    pub fn remove_injection(&mut self, id: &str) -> bool {
        let before = self.injections.len();
        self.injections.retain(|injection| injection.id != id);
        self.injections.len() != before
    }

    pub fn enabled_injections(&self) -> Vec<String> {
        self.injections
            .iter()
            .filter(|injection| injection.enabled)
            .map(|injection| injection.code.clone())
            .collect()
    }

    pub fn upsert_profile(&mut self, id: String, name: String, ephemeral: bool) -> Profile {
        if let Some(existing) = self.profiles.iter_mut().find(|p| p.id == id) {
            existing.name = name;
            existing.ephemeral = ephemeral;
            return existing.clone();
        }
        let profile = Profile {
            id,
            name,
            ephemeral,
        };
        self.profiles.push(profile.clone());
        profile
    }

    pub fn default_profiles() -> Vec<Profile> {
        vec![
            Profile {
                id: "default".to_string(),
                name: "Default".to_string(),
                ephemeral: false,
            },
            Profile {
                id: "ephemeral".to_string(),
                name: "Ephemeral (private)".to_string(),
                ephemeral: true,
            },
        ]
    }
}

pub fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}

/// Depth-limited truncation so captured page payloads can never balloon the log.
fn truncate_json(value: &mut serde_json::Value, max_bytes: usize) {
    match value {
        serde_json::Value::String(text) => {
            if text.len() > max_bytes {
                *text = format!("{}…[truncated {} bytes]", &text[..max_bytes], text.len());
            }
        }
        serde_json::Value::Array(items) => {
            for item in items {
                truncate_json(item, max_bytes);
            }
        }
        serde_json::Value::Object(map) => {
            for item in map.values_mut() {
                truncate_json(item, max_bytes);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn events_are_numbered_and_capped() {
        let mut state = SharedState::new(5077);
        for index in 0..(EVENT_LOG_CAPACITY + 50) {
            state.push_event(Some(1), "console", serde_json::json!({ "i": index }));
        }
        assert_eq!(state.events.len(), EVENT_LOG_CAPACITY);
        // The ring keeps the newest entries only.
        let last = state.events.back().unwrap();
        assert_eq!(last.payload["i"], EVENT_LOG_CAPACITY + 49);
        let window = state.events_since(0, 10);
        assert_eq!(window.len(), 10);
        assert!(window.iter().all(|entry| entry.seq > 0));
    }

    #[test]
    fn events_since_filters_by_sequence() {
        let mut state = SharedState::new(5077);
        let first = state.push_event(None, "injected", serde_json::json!({}));
        let second = state.push_event(None, "console", serde_json::json!({}));
        assert_ne!(first, second);
        let after = state.events_since(first, 100);
        assert_eq!(after.len(), 1);
        assert_eq!(after[0].seq, second);
    }

    #[test]
    fn oversized_payloads_are_truncated() {
        let mut state = SharedState::new(5077);
        state.push_event(
            None,
            "console",
            serde_json::json!({ "text": "x".repeat(MAX_CAPTURED_BYTES * 3) }),
        );
        let entry = state.events.back().unwrap();
        let text = entry.payload["text"].as_str().unwrap();
        assert!(text.len() < MAX_CAPTURED_BYTES + 64);
        assert!(text.ends_with("bytes]"));
    }

    #[test]
    fn injections_upsert_by_name() {
        let mut state = SharedState::new(5077);
        let first = state
            .register_injection("canary".into(), "1".into())
            .unwrap();
        let second = state
            .register_injection("canary".into(), "2".into())
            .unwrap();
        assert_eq!(first.id, second.id);
        assert_eq!(state.injections.len(), 1);
        assert_eq!(state.injections[0].code, "2");
        assert!(state.remove_injection(&first.id));
        assert!(state.injections.is_empty());
        assert!(!state.remove_injection("missing"));
    }

    #[test]
    fn injection_validation_rejects_blanks() {
        let mut state = SharedState::new(5077);
        assert!(state.register_injection("".into(), "1".into()).is_err());
        assert!(state.register_injection("n".into(), "  ".into()).is_err());
    }

    #[test]
    fn profiles_upsert() {
        let mut state = SharedState::new(5077);
        state.upsert_profile("research".into(), "Research".into(), false);
        state.upsert_profile("research".into(), "Research 2".into(), true);
        assert_eq!(state.profiles.len(), 1);
        assert_eq!(state.profiles[0].name, "Research 2");
        assert!(state.profiles[0].ephemeral);
    }
}
