"""Private Cleanup Lab policy settings; shred defaults to off."""
from __future__ import annotations

import json
import os
import stat
import tempfile

from .paths import state_dir
from .shred import LIMITATION

POLICIES = ("off", "one-pass", "three-pass")
FILE = "settings.json"


class SettingsError(ValueError):
    """The private settings file is missing privacy or has invalid data."""


def _folder(env, platform, *, create=False):
    folder = state_dir(env, platform)
    if create:
        os.makedirs(folder, mode=0o700, exist_ok=True)
    if not os.path.exists(folder):
        return None
    if os.path.islink(folder) or not os.path.isdir(folder):
        raise SettingsError("Cleanup settings folder is not a real directory")
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        raise SettingsError("Cleanup settings folder must be private")
    return folder


def read(*, env=None, platform=None):
    folder = _folder(env, platform)
    policy = "off"
    if folder:
        path = os.path.join(folder, FILE)
        if os.path.lexists(path):
            if os.path.islink(path) or (os.name != "nt" and stat.S_IMODE(os.stat(path).st_mode) & 0o077):
                raise SettingsError("Cleanup settings file must be private and not a symlink")
            try:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                raise SettingsError("Cleanup settings file cannot be read") from exc
            if not isinstance(data, dict) or set(data) != {"shredPolicy"} or data["shredPolicy"] not in POLICIES:
                raise SettingsError("Invalid shred policy")
            policy = data["shredPolicy"]
    return {"shredPolicy": policy, "shredLimitation": LIMITATION}


def update(policy, *, env=None, platform=None):
    if policy not in POLICIES:
        raise SettingsError("shredPolicy must be off, one-pass or three-pass")
    folder = _folder(env, platform, create=True)
    target = os.path.join(folder, FILE)
    read(env=env, platform=platform)
    fd, temporary = tempfile.mkstemp(prefix=".settings-", dir=folder)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"shredPolicy": policy}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return read(env=env, platform=platform)
