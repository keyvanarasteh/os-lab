"""Typed engine settings in private state: the shred policy (CLN-14).

One small JSON file (``settings.json``) in the same private folder as the audit
history, held to the same discipline as :mod:`cleanup_lab.history`: a ``0700``
folder that may not be a symlink, a ``0600`` file that may not be a symlink,
and an atomic write (temporary file + ``os.replace`` + fsync) so a reader never
sees a half-written policy.

The store is typed and closed. Keys and values are validated on the way in
(:class:`ValueError` for an unknown key or value — the console turns that into
a 400) and on the way out: a missing file means the default (``off``), while a
file that cannot be parsed, holds an unknown shape, or sits with loose
permissions raises :class:`SettingsError`. Shred fails closed on that error —
its plan is refused with ``shred-settings-corrupt`` — and Trash/delete plans
never read this store at all, so a broken settings file can never block them.
"""
from __future__ import annotations

import json
import os
import stat

from .paths import platform_id, state_dir

#: The typed keys and their allowed values; the first value is the default.
SETTINGS = {"shredPolicy": ("off", "1-pass", "3-pass")}
#: The default value of every typed key.
DEFAULTS = {key: allowed[0] for key, allowed in SETTINGS.items()}
#: Where the settings file lives inside the private state folder.
SETTINGS_NAME = "settings.json"


class SettingsError(RuntimeError):
    """The settings store cannot be trusted; shred must fail closed."""


def _private_state(env=None, platform=None, *, create=False):
    """The private state folder, with history.py's discipline (0700, no symlink)."""
    folder = state_dir(env, platform)
    if create:
        os.makedirs(folder, mode=0o700, exist_ok=True)
    if not os.path.isdir(folder) or os.path.islink(folder):
        raise SettingsError("The cleanup state folder is missing or is a symlink.")
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        raise SettingsError("The cleanup state folder must be private (mode 0700).")
    return folder


def _validate(values):
    """Reject anything that is not the typed shape; return the cleaned mapping."""
    if not isinstance(values, dict):
        raise ValueError(
            "Settings must be an object with the keys: {0}.".format(", ".join(sorted(SETTINGS)))
        )
    cleaned = {}
    for key, value in values.items():
        if key not in SETTINGS:
            raise ValueError("Unknown setting: {0}".format(key))
        allowed = SETTINGS[key]
        if value not in allowed:
            raise ValueError("{0} must be one of: {1}.".format(key, ", ".join(allowed)))
        cleaned[key] = value
    return cleaned


def _load(path):
    """Parse the settings file; a missing file means the defaults, a broken one is fatal."""
    if os.path.islink(path):
        raise SettingsError("The settings file must not be a symlink.")
    if not os.path.exists(path):
        return dict(DEFAULTS)
    try:
        if os.name != "nt" and stat.S_IMODE(os.stat(path).st_mode) & 0o077:
            raise SettingsError("The settings file must be private (mode 0600).")
        with open(path, "r", encoding="utf-8") as handle:
            values = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SettingsError("The settings file cannot be read: {0}".format(exc)) from exc
    if not isinstance(values, dict):
        raise SettingsError("The settings file must hold an object.")
    for key, value in values.items():
        if key not in SETTINGS or value not in SETTINGS[key]:
            raise SettingsError(
                "The settings file holds an unknown key or value: {0}".format(key)
            )
    return values


def get(key, *, env=None, platform=None):
    """The value of one typed setting; a missing file means the default."""
    if key not in SETTINGS:
        raise ValueError("Unknown setting: {0}".format(key))
    folder = _private_state(env, platform)
    values = _load(os.path.join(folder, SETTINGS_NAME))
    return values.get(key, DEFAULTS[key])


def set(values, *, env=None, platform=None):
    """Merge validated values into the store atomically; return the stored mapping.

    Unknown keys or values raise :class:`ValueError`. An unwritable or corrupt
    store raises :class:`SettingsError` — shred then fails closed and Trash is
    unaffected. The write is a temporary file (``0600``) that is fsynced and
    ``os.replace``d into place, so a crash never leaves a half-written policy.
    """
    cleaned = _validate(values)
    folder = _private_state(env, platform, create=True)
    path = os.path.join(folder, SETTINGS_NAME)
    stored = _load(path)
    stored.update(cleaned)
    body = json.dumps(stored, sort_keys=True, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path + ".tmp", flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise SettingsError("The settings file cannot be written: {0}".format(exc)) from exc
    try:
        os.replace(path + ".tmp", path)
    except OSError as exc:
        raise SettingsError("The settings file cannot be replaced: {0}".format(exc)) from exc
    try:
        dir_fd = os.open(folder, os.O_RDONLY)
    except OSError:
        dir_fd = None
    if dir_fd is not None:
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)
    return dict(stored)


def shred_policy(*, env=None, platform=None):
    """``(policy, problem)`` for the shred gate; never raises.

    ``policy`` is ``off`` unless the store says otherwise; ``problem`` is ``None``
    or ``{"code": "settings-corrupt", "message": ...}``. Only shred plans read
    this (via ``cleanup_lab.clean.build_plan``); Trash and delete never do, so a
    broken store cannot block them.
    """
    target = platform or platform_id()
    if not os.path.exists(state_dir(env, target)):
        return DEFAULTS["shredPolicy"], None
    try:
        return get("shredPolicy", env=env, platform=target), None
    except SettingsError as exc:
        return DEFAULTS["shredPolicy"], {"code": "settings-corrupt", "message": str(exc)}


def all_values(env=None, platform=None):
    """``(settings with defaults filled, problem)`` — never raises.

    The shape of :func:`shred_policy` for the whole store: a missing folder
    means the defaults, a store that cannot be trusted reports
    ``{"code": "settings-corrupt", "message": ...}`` instead of raising, and
    the caller decides what fail-closed means for it (shred refuses; the
    settings page shows the error).
    """
    target = platform or platform_id()
    folder = state_dir(env, target)
    if not os.path.exists(folder):
        return dict(DEFAULTS), None
    try:
        values = _load(os.path.join(folder, SETTINGS_NAME))
    except SettingsError as exc:
        return dict(DEFAULTS), {"code": "settings-corrupt", "message": str(exc)}
    merged = dict(DEFAULTS)
    merged.update(values)
    return merged, None
