"""CLA-02: where the Android AVD folder lives, and when to suggest moving it.

The move itself is CLN-27's relocation of ``simulators.android-avd``
(copy → verify → aside → symlink/junction → verify → remove). This module
adds the setup around it on macOS, Linux and Windows:

* a saved **destination** volume and a free-space floor for the system disk
  (private JSON in the cleanup state folder);
* a read-only **status**: the folder is on the system disk, linked to another
  volume, or linked to a volume that is not connected;
* a **suggestion**: ``setup`` when the folder is still on the system disk and
  another volume can take it; ``move`` when a saved destination is connected
  and the system disk is below the floor; ``reconnect`` when the linked disk
  is missing. The dashboard auto-check uses all three. The monitor notifies
  only for ``move`` and ``reconnect``. Nothing moves on its own.

Windows uses a directory junction (no Developer Mode). Do not write
``ANDROID_AVD_HOME`` into the user's shell; a home-side link is enough.
Never relocate the whole SDK.
"""
from __future__ import annotations

import json
import ntpath
import os

from . import paths, volumes
from .catalog import load as catalog_load, resolve as catalog_resolve
from .devcache import valid_path
from .paths import state_dir
from .relocation import _is_link, _link_target

ENTRY_ID = "simulators.android-avd"
STORE = "emulator-storage.json"
VERSION = 1
GIB = 1024 ** 3
DEFAULT_FLOOR = 20 * GIB
MIN_FLOOR = 1 * GIB
MAX_FLOOR = 2048 * GIB
DESTINATION_KINDS = ("internal", "removable")
SDK_ENV = ("ANDROID_SDK_ROOT", "ANDROID_HOME")


class StorageConfigError(ValueError):
    """A config the schema refused; the message says what is wrong."""


def default_config():
    return {"destination": None, "suggest": True, "floorBytes": DEFAULT_FLOOR}


def _absolute_destination(destination, platform):
    if not isinstance(destination, str) or not destination or len(destination) > 1024 or "\0" in destination:
        return False
    if platform == "windows":
        drive, tail = ntpath.splitdrive(destination.replace("/", "\\"))
        return bool(drive) and tail.startswith("\\")
    return destination.startswith("/")


def validate_config(config, platform="linux"):
    if not isinstance(config, dict):
        raise StorageConfigError("config must be an object")
    unknown = set(config) - {"destination", "suggest", "floorBytes"}
    if unknown:
        raise StorageConfigError("unexpected key(s): {0}".format(", ".join(sorted(unknown))))
    merged = {**default_config(), **config}
    destination = merged["destination"]
    if destination is not None and not _absolute_destination(destination, platform):
        raise StorageConfigError("destination must be an absolute volume mount point or null")
    if not isinstance(merged["suggest"], bool):
        raise StorageConfigError("suggest must be true or false")
    floor = merged["floorBytes"]
    if not isinstance(floor, int) or isinstance(floor, bool) or not MIN_FLOOR <= floor <= MAX_FLOOR:
        raise StorageConfigError("floorBytes must be between 1 GiB and 2048 GiB")
    return {"destination": destination, "suggest": merged["suggest"], "floorBytes": floor}


def _store_path(env=None, platform=None):
    return os.path.join(state_dir(env, platform), STORE)


def load(env=None, platform=None):
    platform = platform or paths.platform_id()
    try:
        with open(_store_path(env, platform), encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {"config": default_config(), "configError": None}
    except (OSError, ValueError) as exc:
        return {"config": default_config(), "configError": "The emulator storage settings are unreadable: {0}".format(exc)}
    try:
        if not isinstance(raw, dict):
            raise StorageConfigError("unknown shape")
        return {"config": validate_config(raw.get("config"), platform), "configError": None}
    except StorageConfigError as exc:
        return {"config": default_config(), "configError": "The emulator storage settings are invalid: {0}".format(exc)}


def save(config, *, env=None, platform=None, destinations=None):
    platform = platform or paths.platform_id()
    validated = validate_config(config, platform)
    if validated["destination"] is not None and destinations is not None and validated["destination"] not in destinations:
        raise StorageConfigError("destination must be one of the offered volumes")
    path = _store_path(env, platform)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temporary = "{0}.tmp-{1}".format(path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"version": VERSION, "config": validated}, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return {"config": validated, "configError": None}


def sdk_root(platform, env):
    """User SDK root from ANDROID_SDK_ROOT / ANDROID_HOME or the platform default."""
    home = paths.home_dir(env)
    for key in SDK_ENV:
        found = valid_path(env.get(key), platform, home)
        if found:
            return found
    if platform == "macos":
        candidate = os.path.join(home, "Library", "Android", "sdk")
    elif platform == "windows":
        local = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        candidate = os.path.join(local, "Android", "Sdk")
    else:
        candidate = os.path.join(home, "Android", "Sdk")
    return candidate if os.path.isdir(candidate) else None


def _volume_of(path, rows, platform="linux"):
    """The mounted volume holding ``path`` (longest mount-point prefix), or None."""
    if not path:
        return None
    best = None
    for row in rows:
        mount = row.get("mountPoint") or ""
        if not mount:
            continue
        if platform == "windows":
            left = path.replace("/", "\\")
            right = mount.replace("/", "\\")
            if left.lower() == right.lower() or left.lower().startswith(right.rstrip("\\").lower() + "\\"):
                if best is None or len(right) > len(best["mountPoint"]):
                    best = row
            continue
        if path == mount or path.startswith(mount.rstrip("/") + "/"):
            if best is None or len(mount) > len(best["mountPoint"]):
                best = row
    return best


def _folder(root, platform, env):
    entry = next((item for item in catalog_load(root, env) if item["id"] == ENTRY_ID), None)
    if entry is None:
        return None
    found = [item["path"] for item in catalog_resolve(entry, platform, env) if item.get("path")]
    return found[0] if found else None


def _broken_ancestor(folder):
    """A linked parent whose target is gone (its disk is unplugged), or None."""
    current = os.path.dirname(folder)
    while current and current != os.path.dirname(current):
        if _is_link(current):
            try:
                target = _link_target(current)
            except OSError:
                return None
            return None if os.path.isdir(target) else os.path.join(target, os.path.relpath(folder, current))
        current = os.path.dirname(current)
    return None


def location(folder, rows, home=None, platform="linux"):
    """(state, target, volume row) for the AVD folder; read-only lstat/readlink."""
    if not folder:
        return "missing", None, None
    if not os.path.lexists(folder):
        broken = _broken_ancestor(folder)
        return ("disk-missing", broken, _volume_of(broken, rows, platform)) if broken else ("missing", None, None)
    if _is_link(folder):
        try:
            target = _link_target(folder)
        except OSError:
            return "disk-missing", folder, None
        volume = _volume_of(target, rows, platform)
        if not os.path.isdir(target):
            return "disk-missing", target, volume
        return "linked", target, volume
    real = os.path.realpath(folder)
    volume = _volume_of(real, rows, platform)
    if home is not None and volume is not None and volume["mountPoint"] != home["mountPoint"]:
        return "linked", real, volume
    return "local", folder, volume


def suggestion(config, state, home, destination, offered=None):
    """What the page should offer next, from pure inputs; never acts by itself."""
    if state == "disk-missing":
        return {"action": "reconnect", "reason": "The disk that holds the emulators is not connected."}
    if state != "local":
        return {"action": None, "reason": ""}
    has_disk = bool(offered) if offered is not None else destination is not None
    if (config["suggest"] and config["destination"] and destination is not None
            and home is not None and isinstance(home.get("freeBytes"), int)
            and home["freeBytes"] < config["floorBytes"]):
        return {"action": "move", "reason": "The system disk is below the free-space floor."}
    if has_disk:
        return {"action": "setup", "reason": "Android Virtual Devices are still on the system disk."}
    return {"action": None, "reason": ""}


def status(root, *, platform=None, env=None, inventory=None):
    """Folder location, saved config, offered destinations and the current suggestion."""
    platform = platform or paths.platform_id()
    env = os.environ if env is None else env
    if platform not in ("macos", "linux", "windows"):
        return {"available": False, "reason": "Android emulator storage is desktop only"}
    snapshot = inventory if inventory is not None else volumes.inventory(platform, env)
    rows = snapshot.get("volumes", [])
    home = next((row for row in rows if row.get("isHome")), None)
    loaded = load(env, platform)
    config = loaded["config"]
    folder = _folder(root, platform, env)
    sdk = sdk_root(platform, env)
    folder_exists = bool(folder and os.path.lexists(folder))
    if not folder_exists and not sdk:
        return {"available": False, "reason": "No Android SDK or AVD folder on this computer",
                "entryId": ENTRY_ID, "folder": folder, "sdkRoot": None, "hasSdk": False,
                "state": "missing", "target": None, "volume": None, "home": None,
                "config": config, "configError": loaded["configError"], "destinations": [],
                "suggestion": {"action": None, "reason": ""}}
    state, target, volume = location(folder, rows, home, platform)
    offered = [row for row in rows if row.get("kind") in DESTINATION_KINDS and isinstance(row.get("freeBytes"), int)
               and (home is None or row["mountPoint"] != home["mountPoint"])]
    destination = next((row for row in offered if row["mountPoint"] == config["destination"]), None)
    return {
        "available": True, "reason": "", "entryId": ENTRY_ID,
        "folder": folder, "state": state, "target": target, "sdkRoot": sdk, "hasSdk": bool(sdk),
        "volume": volume and {"mountPoint": volume["mountPoint"], "name": volume.get("name"), "kind": volume.get("kind")},
        "home": home and {"mountPoint": home["mountPoint"], "freeBytes": home.get("freeBytes"), "totalBytes": home.get("totalBytes")},
        "config": config, "configError": loaded["configError"],
        "destinations": [{"mountPoint": row["mountPoint"], "name": row.get("name"), "kind": row["kind"],
                          "freeBytes": row["freeBytes"], "totalBytes": row.get("totalBytes")} for row in offered],
        "suggestion": suggestion(config, state, home, destination, offered),
        "linkKind": "junction" if platform == "windows" else "symlink",
    }


def notification(report):
    """(title, message) for a monitor tick, or None. Only ``move`` and ``reconnect`` notify."""
    action = (report or {}).get("suggestion", {}).get("action")
    if action == "move":
        return ("Move Android emulators off the system disk",
                "AVDs use the system disk. Open Cleanup Lab, Relocation, to move them to {0}.".format(
                    report["config"]["destination"]))
    if action == "reconnect":
        return ("Emulator disk is not connected",
                "Connect the disk that holds your Android emulators before opening Android Studio.")
    return None
