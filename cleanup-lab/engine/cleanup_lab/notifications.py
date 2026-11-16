"""CLN-30: local notifications — the lab's event outbox.

Like the monitor (CLNP-09) this module is pure, typed and store-backed: the
config and a bounded event list live as atomic JSON in the private state
folder, the clock is injectable, and no function ever touches a real
notification facility. The console appends events at the lab's lifecycle
hooks (every job's completion, the automated hook clean, monitor
evaluations); the desktop app polls ``outbox`` over the loopback API and
turns new events into OS notifications, while the dashboard renders the same
events as in-app toasts.

Titles are static English strings so the dashboard's DOM translator can
localize them from the seven locale catalogs; bodies carry dynamic numbers
and stay English everywhere (the OS layer is not localized at all). Events
never carry a raw path beyond a volume's mount point name — the widget
snapshot rule applies here too.

Delivery is honest degradation: a machine without a notification daemon
simply records the failure in the desktop app's runtime report; nothing in
this module can fail a request, a job or a monitor tick.
"""
from __future__ import annotations

import json
import os
import time

from .paths import state_dir

STORE = "notifications.json"
VERSION = 1
#: The outbox stays small: it is a notification queue, not a history.
MAX_EVENTS = 50

#: The categories a user can toggle in Settings. Every lifecycle hook maps to
#: exactly one, so the config gate is a single lookup.
CATEGORIES = (
    "job-done",
    "job-failed",
    "auto-clean",
    "monitor-warning",
    "monitor-recovered",
    "monitor-error",
)

#: Routes an action may deep-link into. The desktop app refuses anything
#: else (mirrors the app's route whitelist), so an event can never navigate
#: the dashboard somewhere unexpected.
ROUTES = (
    "dashboard", "scan", "results", "leftovers", "history", "space",
    "cleanup-bookmarks", "cleanup-monitor", "cleanup-permissions",
    "cleanup-widgets", "cleanup-notifications",
)


class NotificationsConfigError(ValueError):
    """A config the schema refused; ``message`` says exactly what is wrong."""


def default_config():
    """Everything on: the desktop app and the dashboard both gate on this."""
    return {
        "enabled": True,
        "categories": {category: True for category in CATEGORIES},
    }


def validate_config(config):
    """The engine-side schema every config passes before it is stored.

    The console validates the request first; this re-validation runs on load
    too, so a hand-edited store can never arm a nonsense gate.
    """
    if not isinstance(config, dict):
        raise NotificationsConfigError("The notifications config must be an object")
    unknown = set(config) - {"enabled", "categories"}
    if unknown:
        raise NotificationsConfigError(
            "Unknown notifications config keys: {0}".format(", ".join(sorted(unknown))))
    enabled = config.get("enabled", True)
    if not isinstance(enabled, bool):
        raise NotificationsConfigError("enabled must be true or false")
    raw_categories = config.get("categories", {})
    if not isinstance(raw_categories, dict):
        raise NotificationsConfigError("categories must be an object")
    unknown_categories = set(raw_categories) - set(CATEGORIES)
    if unknown_categories:
        raise NotificationsConfigError(
            "Unknown notification categories: {0}".format(", ".join(sorted(unknown_categories))))
    categories = {category: True for category in CATEGORIES}
    for category, value in raw_categories.items():
        if not isinstance(value, bool):
            raise NotificationsConfigError(
                "categories.{0} must be true or false".format(category))
        categories[category] = value
    return {"enabled": enabled, "categories": categories}


def _store_path(env=None, platform=None):
    return os.path.join(state_dir(env, platform), STORE)


def _write_atomic(path, payload):
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    temporary = "{0}.tmp-{1}".format(path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _clean_events(events):
    """Keep only the typed shape; a corrupt entry is dropped, never guessed."""
    cleaned = []
    for event in events[-MAX_EVENTS:]:
        if not isinstance(event, dict) or not isinstance(event.get("id"), int):
            continue
        if event.get("category") not in CATEGORIES or not isinstance(event.get("at"), (int, float)):
            continue
        actions = []
        raw_actions = event.get("actions") if isinstance(event.get("actions"), list) else []
        for action in raw_actions[:3]:
            if isinstance(action, dict) and isinstance(action.get("id"), str) and isinstance(action.get("label"), str):
                route = action.get("route")
                actions.append({
                    "id": action["id"], "label": action["label"],
                    "route": route if route in ROUTES else None,
                })
        route = event.get("route")
        cleaned.append({
            "id": event["id"],
            "at": event["at"],
            "category": event["category"],
            "title": event.get("title") if isinstance(event.get("title"), str) else "",
            "body": event.get("body") if isinstance(event.get("body"), str) else "",
            "route": route if route in ROUTES else None,
            "actions": actions,
        })
    return cleaned


def load(env=None, platform=None):
    """The persisted config + outbox, validated; corruption falls back to defaults."""
    try:
        with open(_store_path(env, platform), encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {"config": default_config(), "events": [], "configError": None}
    except (OSError, ValueError) as exc:
        return {"config": default_config(), "events": [],
                "configError": "The notifications store is unreadable: {0}".format(exc)}
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        return {"config": default_config(), "events": [],
                "configError": "The notifications store has an unknown version; defaults apply."}
    try:
        config = validate_config(raw.get("config"))
    except NotificationsConfigError as exc:
        return {"config": default_config(), "events": [],
                "configError": "The notifications config is invalid: {0}".format(exc)}
    events = raw.get("events") if isinstance(raw.get("events"), list) else []
    return {"config": config, "events": _clean_events(events), "configError": None}


def save_config(config, *, env=None, platform=None):
    """Validate, persist, and return the resulting store payload."""
    validated = validate_config(config)
    loaded = load(env, platform)
    loaded["config"] = validated
    _write_atomic(_store_path(env, platform), {
        "version": VERSION, "config": validated, "events": loaded["events"],
    })
    return loaded


def _allowed(config, category):
    if not config.get("enabled"):
        return False
    return bool(config.get("categories", {}).get(category, True))


def emit(category, title, body, *, route=None, actions=None, env=None, platform=None,
         clock=time.time):
    """Append one typed event when the config allows the category.

    Best-effort by contract: a failed store write returns a reason instead of
    raising, so a caller on a request path or the monitor thread is never
    broken by the notification side effect. ``actions`` is a list of
    ``{"id", "label", "route"}`` dicts; unknown routes are refused here so
    the desktop app can trust the field.
    """
    try:
        loaded = load(env, platform)
        if not _allowed(loaded["config"], category):
            return {"emitted": False, "reason": "disabled", "event": None}
        event = {
            "id": max((item["id"] for item in loaded["events"]), default=0) + 1,
            "at": clock(),
            "category": category,
            "title": title,
            "body": body,
            "route": route if route in ROUTES else None,
            "actions": [
                {"id": action["id"], "label": action["label"],
                 "route": action.get("route") if action.get("route") in ROUTES else None}
                for action in (actions or [])
                if isinstance(action, dict) and isinstance(action.get("id"), str)
                and isinstance(action.get("label"), str)
            ][:3],
        }
        events = (loaded["events"] + [event])[-MAX_EVENTS:]
        _write_atomic(_store_path(env, platform), {
            "version": VERSION, "config": loaded["config"], "events": events,
        })
        return {"emitted": True, "reason": None, "event": event}
    except (OSError, ValueError) as exc:
        return {"emitted": False, "reason": str(exc), "event": None}


def outbox(since, *, env=None, platform=None):
    """Events newer than ``since`` for the desktop app's watcher.

    ``since`` is the last event id the watcher saw; a pruned or unknown
    cursor yields the whole bounded outbox, so the watcher can never get
    stuck behind a truncated store.
    """
    loaded = load(env, platform)
    if not isinstance(since, int) or since < 0:
        since = 0
    events = [event for event in loaded["events"] if event["id"] > since]
    cursor = events[-1]["id"] if events else since
    return {"events": events, "cursor": cursor}


def settings_urls(platform=None):
    """The platform's notification settings panes, fixed links only.

    Modern pane first, then the legacy pane, exactly like the FDA grant
    round-trip. Linux notification settings live in each desktop
    environment, so there is no universal link: an empty list means the
    caller shows guidance text instead of a deep link.
    """
    platform = platform or os.environ.get("OSLAB_PLATFORM")
    if platform == "macos":
        return (
            "x-apple.systempreferences:com.apple.Notifications-Settings.extension",
            "x-apple.systempreferences:com.apple.preference.notifications",
        )
    if platform == "windows":
        return ("ms-settings:notifications",)
    return ()


__all__ = [
    "CATEGORIES", "MAX_EVENTS", "NotificationsConfigError", "ROUTES", "STORE", "VERSION",
    "default_config", "emit", "load", "outbox", "save_config", "settings_urls", "validate_config",
]
