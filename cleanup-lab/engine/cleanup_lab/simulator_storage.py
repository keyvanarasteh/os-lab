"""CLS-02: where the iOS Simulator devices folder lives, and when to suggest moving it.

The move itself is CLN-27's relocation of ``simulators.coresimulator-devices``
(copy → verify → aside → symlink → verify → remove) behind its own confirm
dialog. This module adds the setup around it:

* a saved **destination** volume and a free-space floor for the system disk
  (private JSON in the cleanup state folder, like the monitor's store);
* a read-only **status**: the folder is on the system disk, linked to another
  volume, or linked to a volume that is not connected (Simulator then fails);
* a **suggestion** the dashboard and the monitor show when the system disk is
  below the floor and the folder still lives there. Nothing moves on its own:
  a suggestion opens the existing plan → confirm → run flow.

Runtimes (``/Library/Developer/CoreSimulator``) stay system-managed and are
never relocated.
"""
from __future__ import annotations

import json
import os

from . import paths, volumes
from .catalog import load as catalog_load, resolve as catalog_resolve
from .paths import state_dir

ENTRY_ID = "simulators.coresimulator-devices"
STORE = "simulator-storage.json"
VERSION = 1
GIB = 1024 ** 3
DEFAULT_FLOOR = 20 * GIB
MIN_FLOOR = 1 * GIB
MAX_FLOOR = 2048 * GIB
#: Volume kinds a store may live on. The home volume itself is never offered.
DESTINATION_KINDS = ("internal", "removable")


class StorageConfigError(ValueError):
    """A config the schema refused; the message says what is wrong."""


def default_config():
    return {"destination": None, "suggest": True, "floorBytes": DEFAULT_FLOOR}


def validate_config(config):
    if not isinstance(config, dict):
        raise StorageConfigError("config must be an object")
    unknown = set(config) - {"destination", "suggest", "floorBytes"}
    if unknown:
        raise StorageConfigError("unexpected key(s): {0}".format(", ".join(sorted(unknown))))
    merged = {**default_config(), **config}
    destination = merged["destination"]
    if destination is not None and (not isinstance(destination, str) or not destination.startswith("/")
                                    or len(destination) > 1024 or "\0" in destination):
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
    """The saved config, or the defaults with a reason when the store is unreadable."""
    try:
        with open(_store_path(env, platform), encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {"config": default_config(), "configError": None}
    except (OSError, ValueError) as exc:
        return {"config": default_config(), "configError": "The simulator storage settings are unreadable: {0}".format(exc)}
    try:
        if not isinstance(raw, dict):
            raise StorageConfigError("unknown shape")
        return {"config": validate_config(raw.get("config")), "configError": None}
    except StorageConfigError as exc:
        return {"config": default_config(), "configError": "The simulator storage settings are invalid: {0}".format(exc)}


def save(config, *, env=None, platform=None, destinations=None):
    """Validate and persist. ``destinations`` (mount points) limits where a store may go."""
    validated = validate_config(config)
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


def _volume_of(path, rows):
    """The mounted volume holding ``path`` (longest mount-point prefix), or None."""
    best = None
    for row in rows:
        mount = row.get("mountPoint") or ""
        if mount and (path == mount or path.startswith(mount.rstrip("/") + "/")):
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
    """A symlinked parent whose target is gone (its disk is unplugged), or None."""
    current = os.path.dirname(folder)
    while current and current != os.path.dirname(current):
        if os.path.islink(current):
            target = os.readlink(current)
            if not os.path.isabs(target):
                target = os.path.normpath(os.path.join(os.path.dirname(current), target))
            return None if os.path.isdir(target) else os.path.join(target, os.path.relpath(folder, current))
        current = os.path.dirname(current)
    return None


def location(folder, rows, home=None):
    """(state, target, volume row) for the devices folder; read-only lstat/readlink.

    ``linked`` covers the folder itself or a parent folder (``~/Library/Developer``
    for example) being a symlink to another volume: either way the devices are
    already off the system disk.
    """
    if not folder:
        return "missing", None, None
    if not os.path.lexists(folder):
        broken = _broken_ancestor(folder)
        return ("disk-missing", broken, _volume_of(broken, rows)) if broken else ("missing", None, None)
    if os.path.islink(folder):
        target = os.readlink(folder)
        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(os.path.dirname(folder), target))
        volume = _volume_of(target, rows)
        if not os.path.isdir(target):
            return "disk-missing", target, volume
        return "linked", target, volume
    real = os.path.realpath(folder)
    volume = _volume_of(real, rows)
    if home is not None and volume is not None and volume["mountPoint"] != home["mountPoint"]:
        return "linked", real, volume
    return "local", folder, volume


def suggestion(config, state, home, destination):
    """What the page should offer next, from pure inputs; never acts by itself."""
    if state == "disk-missing":
        return {"action": "reconnect", "reason": "The disk that holds the simulators is not connected."}
    if state != "local" or not config["suggest"] or not config["destination"]:
        return {"action": None, "reason": ""}
    if destination is None:
        return {"action": None, "reason": "The chosen disk is not connected."}
    if home is None or not isinstance(home.get("freeBytes"), int):
        return {"action": None, "reason": ""}
    if home["freeBytes"] >= config["floorBytes"]:
        return {"action": None, "reason": ""}
    return {"action": "move", "reason": "The system disk is below the free-space floor."}


def status(root, *, platform=None, env=None, inventory=None):
    """Folder location, saved config, offered destinations and the current suggestion."""
    platform = platform or paths.platform_id()
    env = os.environ if env is None else env
    if platform != "macos":
        return {"available": False, "reason": "iOS Simulator storage is macOS only"}
    snapshot = inventory if inventory is not None else volumes.inventory(platform, env)
    rows = snapshot.get("volumes", [])
    home = next((row for row in rows if row.get("isHome")), None)
    loaded = load(env, platform)
    config = loaded["config"]
    folder = _folder(root, platform, env)
    state, target, volume = location(folder, rows, home)
    offered = [row for row in rows if row.get("kind") in DESTINATION_KINDS and isinstance(row.get("freeBytes"), int)
               and (home is None or row["mountPoint"] != home["mountPoint"])]
    destination = next((row for row in offered if row["mountPoint"] == config["destination"]), None)
    return {
        "available": True, "reason": "", "entryId": ENTRY_ID,
        "folder": folder, "state": state, "target": target,
        "volume": volume and {"mountPoint": volume["mountPoint"], "name": volume.get("name"), "kind": volume.get("kind")},
        "home": home and {"mountPoint": home["mountPoint"], "freeBytes": home.get("freeBytes"), "totalBytes": home.get("totalBytes")},
        "config": config, "configError": loaded["configError"],
        "destinations": [{"mountPoint": row["mountPoint"], "name": row.get("name"), "kind": row["kind"],
                          "freeBytes": row["freeBytes"], "totalBytes": row.get("totalBytes")} for row in offered],
        "suggestion": suggestion(config, state, home, destination),
    }


def notification(report):
    """(title, message) for a monitor tick, or None. Only ``move`` and ``reconnect`` notify."""
    action = (report or {}).get("suggestion", {}).get("action")
    if action == "move":
        return ("Move iOS simulators off the system disk",
                "Simulators use the system disk. Open Cleanup Lab, Relocation, to move them to {0}.".format(
                    report["config"]["destination"]))
    if action == "reconnect":
        return ("Simulator disk is not connected",
                "Connect the disk that holds your iOS simulators before opening Simulator.")
    return None
