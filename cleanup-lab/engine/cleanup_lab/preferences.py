"""CUX-08: the user's cleanup suggestion preferences, stored and kept across updates.

One small JSON file in the private state folder (next to ``monitor.json`` and
``bookmarks.json``), written atomically. The file holds *choices*, never paths or
commands: a mode, entry ids the user always wants suggested or never wants
suggested, a smallest worthwhile size and an optional free-space target.

Update safety: a store written by another version is read and validated, not
discarded; ids the current catalog does not list are kept in the file (a later
catalog may list them again) and only ignored when a suggestion is built.
Corruption never guesses: the defaults apply and ``configError`` says why.
"""
from __future__ import annotations

import json
import os

from .paths import state_dir

STORE = "preferences.json"
VERSION = 1
MODES = ("auto", "recommended", "extended")
MAX_IDS = 200
MAX_MIN_ENTRY = 10 * 1024 ** 3
MAX_TARGET = 4 * 1024 ** 4


class PreferencesError(ValueError):
    """A preferences object the schema refused; the message says what is wrong."""


def default_suggestion():
    """auto: defaults on a healthy disk, more safe entries while the disk is under pressure."""
    return {"mode": "auto", "include": [], "exclude": [], "minEntryBytes": 1024 * 1024, "targetFreeBytes": None}


def _ids(value, name):
    if not isinstance(value, list) or len(value) > MAX_IDS or any(not isinstance(item, str) or not item or len(item) > 200 for item in value):
        raise PreferencesError("{0} must be a list of at most {1} entry ids".format(name, MAX_IDS))
    if len(set(value)) != len(value):
        raise PreferencesError("{0} lists an entry twice".format(name))
    return list(value)


def validate_suggestion(value):
    if not isinstance(value, dict):
        raise PreferencesError("suggestion must be an object")
    unknown = set(value) - {"mode", "include", "exclude", "minEntryBytes", "targetFreeBytes"}
    if unknown:
        raise PreferencesError("Unknown key(s): {0}".format(", ".join(sorted(unknown))))
    base = default_suggestion()
    mode = value.get("mode", base["mode"])
    if mode not in MODES:
        raise PreferencesError("mode must be one of: {0}".format(", ".join(MODES)))
    include = _ids(value.get("include", []), "include")
    exclude = _ids(value.get("exclude", []), "exclude")
    both = sorted(set(include) & set(exclude))
    if both:
        raise PreferencesError("an entry can not be both included and excluded: {0}".format(", ".join(both)))
    minimum = value.get("minEntryBytes", base["minEntryBytes"])
    if not isinstance(minimum, int) or isinstance(minimum, bool) or not 0 <= minimum <= MAX_MIN_ENTRY:
        raise PreferencesError("minEntryBytes must be a whole number of bytes between 0 and {0}".format(MAX_MIN_ENTRY))
    target = value.get("targetFreeBytes", None)
    if target is not None and (not isinstance(target, int) or isinstance(target, bool) or not 0 < target <= MAX_TARGET):
        raise PreferencesError("targetFreeBytes must be a positive whole number of bytes or null")
    return {"mode": mode, "include": include, "exclude": exclude, "minEntryBytes": minimum, "targetFreeBytes": target}


def _store_path(env=None, platform=None):
    return os.path.join(state_dir(env, platform), STORE)


def _write_atomic(path, payload):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temporary = "{0}.tmp-{1}".format(path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load(env=None, platform=None):
    """``{"suggestion": ..., "configError": str | None}``; never raises."""
    try:
        with open(_store_path(env, platform), encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {"suggestion": default_suggestion(), "configError": None}
    except (OSError, ValueError) as exc:
        return {"suggestion": default_suggestion(), "configError": "The preferences file is unreadable: {0}".format(exc)}
    if not isinstance(raw, dict) or not isinstance(raw.get("version"), int) or raw["version"] < 1:
        return {"suggestion": default_suggestion(), "configError": "The preferences file has an unknown shape; defaults apply."}
    try:
        # Another version is read like any other: unknown keys are refused, known ones kept.
        return {"suggestion": validate_suggestion(raw.get("suggestion", {})), "configError": None}
    except PreferencesError as exc:
        return {"suggestion": default_suggestion(), "configError": "The saved preferences are invalid ({0}); defaults apply.".format(exc)}


def save(suggestion, *, env=None, platform=None):
    """Validate, persist atomically, return the stored payload."""
    validated = validate_suggestion(suggestion)
    _write_atomic(_store_path(env, platform), {"version": VERSION, "suggestion": validated})
    return {"suggestion": validated, "configError": None}


__all__ = ["MODES", "PreferencesError", "default_suggestion", "load", "save", "validate_suggestion"]
