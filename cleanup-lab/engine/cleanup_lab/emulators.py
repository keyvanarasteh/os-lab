"""CLA-01/03 typed Android emulator cleanup on macOS, Linux and Windows.

Inventory reads ``*.ini`` under ``ANDROID_AVD_HOME`` or ``~/.android/avd``.
Delete runs ``avdmanager delete avd -n <name>`` (fixed argv, no shell). Wipe
removes regenerable images inside the AVD folder. Only shut-down AVDs can
change. The page sends names from the live inventory, never paths.

CLA-03 lists ``sdkmanager --list_installed`` system-image packages and
uninstalls only packages no AVD still references (``image.sysdir.1``). The
``system-images`` subfolder of the SDK is relocatable; the whole SDK is not.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from . import emulator_storage, paths
from .clean import fingerprint_path
from .devcache import valid_path
from .safety import is_contained, running_processes

NAME = re.compile(r"^[A-Za-z0-9._-]+$")
PACKAGE = re.compile(r"^system-images;(?:[A-Za-z0-9._-]+;){1,8}[A-Za-z0-9._-]+$")
MAX_AVDS = 100
MAX_IMAGES = 40
EXPIRY_SECONDS = 600
RUN_TIMEOUT = 300
LIST_TIMEOUT = 30
OWNING = ("emulator", "emulator.exe", "qemu-system-x86_64", "qemu-system-aarch64",
          "qemu-system-x86_64.exe", "qemu-system-aarch64.exe")
WIPE_FILES = ("cache.img", "cache.img.qcow2", "userdata-qemu.img", "userdata-qemu.img.qcow2")
WIPE_DIRS = ("snapshots",)
ACTIONS = {
    "emulators.delete-unavailable": {"risk": "low", "select": False, "op": "delete", "target": "devices"},
    "emulators.wipe-data": {"risk": "medium", "select": True, "op": "wipe", "target": "devices"},
    "emulators.delete-avds": {"risk": "high", "select": True, "op": "delete", "target": "devices"},
    "emulators.uninstall-images": {"risk": "medium", "select": True, "op": "uninstall", "target": "images"},
}


class EmulatorError(ValueError):
    """Unavailable tooling, invalid selection, stale preview, or failed command."""


@dataclass(frozen=True)
class Preview:
    action_id: str
    argv: tuple[str, ...]
    device_ids: tuple[str, ...]
    digest: str
    count: int
    bytes: int
    created_at: float
    risk: str
    devices: tuple[dict, ...] = ()
    op: str = "delete"


def actions():
    """The fixed action list the page offers, without argv choices."""
    def command(value):
        if value["op"] == "wipe":
            return ["wipe-avd-data", "<avd names>"]
        if value["op"] == "uninstall":
            return ["sdkmanager", "--uninstall", "<package>"]
        names = ["<avd names>"] if value["select"] else ["<unavailable>"]
        return ["avdmanager", "delete", "avd", "-n", *names]
    return [{"id": key, "risk": value["risk"], "needsSelection": value["select"], "defaultSelected": False,
             "target": value.get("target", "devices"), "command": command(value)} for key, value in ACTIONS.items()]


def avd_home(platform, env):
    """(folder, source) for the AVD directory; never guesses a relative path."""
    home = paths.home_dir(env)
    override = valid_path(env.get("ANDROID_AVD_HOME"), platform, home)
    if override:
        return override, "env:ANDROID_AVD_HOME"
    default = os.path.join(home, ".android", "avd")
    return default, "default"


def _ini_value(text, key):
    prefix = key + "="
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return ""


def _sysdir_to_package(sysdir):
    """``image.sysdir.1=system-images/android-34/google_apis/arm64-v8a/`` → package id."""
    if not isinstance(sysdir, str) or not sysdir:
        return None
    text = sysdir.strip().replace("\\", "/").strip("/")
    if not text.startswith("system-images/"):
        return None
    ident = text.replace("/", ";")
    return ident if PACKAGE.fullmatch(ident) else None


def _sdkmanager(env, sdk):
    path = env.get("PATH") if env is not None else None
    found = shutil.which("sdkmanager", path=path) or shutil.which("sdkmanager.bat", path=path)
    if found:
        return found
    if not sdk:
        return None
    names = ["sdkmanager", "sdkmanager.bat"]
    candidates = [
        os.path.join(sdk, "cmdline-tools", "latest", "bin"),
        os.path.join(sdk, "tools", "bin"),
    ]
    tools = os.path.join(sdk, "cmdline-tools")
    if os.path.isdir(tools):
        try:
            extra = sorted(os.listdir(tools))
        except OSError:
            extra = []
        for name in extra:
            if name == "latest":
                continue
            candidates.append(os.path.join(tools, name, "bin"))
    for folder in candidates:
        for name in names:
            tool = os.path.join(folder, name)
            if os.path.isfile(tool):
                return tool
    return None


def _parse_installed(text):
    """Rows from ``sdkmanager --list_installed`` whose id is a system-images package."""
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("path") or set(stripped) <= set("-| "):
            continue
        if "|" in stripped:
            parts = [item.strip() for item in stripped.split("|")]
            ident = parts[0]
            version = parts[1] if len(parts) > 1 else ""
            name = parts[2] if len(parts) > 2 else ident
            location = parts[3] if len(parts) > 3 else ""
        else:
            ident = stripped.split()[0]
            version, name, location = "", ident, ""
        if not PACKAGE.fullmatch(ident):
            continue
        rows.append({"id": ident, "name": name or ident, "version": version, "location": location})
        if len(rows) >= MAX_IMAGES:
            break
    return rows


def _image_folder(sdk, row):
    location = (row.get("location") or "").replace("\\", "/").strip().strip("/")
    if location and not os.path.isabs(location):
        path = os.path.normpath(os.path.join(sdk, *location.split("/")))
        if os.path.isdir(path):
            return path
    relative = row["id"].split(";")
    path = os.path.normpath(os.path.join(sdk, *relative))
    return path if os.path.isdir(path) else None


def _avd_image_refs(folder):
    """package id → AVD names from each AVD ``config.ini`` ``image.sysdir.1``."""
    refs = {}
    if not folder or not os.path.isdir(folder):
        return refs
    try:
        names = os.listdir(folder)
    except OSError:
        return refs
    for name in names:
        if not name.endswith(".ini") or os.path.islink(os.path.join(folder, name)):
            continue
        avd_name = name[:-4]
        if not NAME.fullmatch(avd_name):
            continue
        ini_path = os.path.join(folder, name)
        try:
            with open(ini_path, encoding="utf-8", errors="replace") as handle:
                pointer = handle.read(8192)
        except OSError:
            continue
        target = _ini_value(pointer, "path") or os.path.join(folder, avd_name + ".avd")
        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(folder, target))
        config = os.path.join(target, "config.ini")
        if not os.path.isfile(config) or os.path.islink(config):
            continue
        try:
            with open(config, encoding="utf-8", errors="replace") as handle:
                text = handle.read(8192)
        except OSError:
            continue
        package = _sysdir_to_package(_ini_value(text, "image.sysdir.1"))
        if package:
            refs.setdefault(package, []).append(avd_name)
    return refs


def images(*, platform=None, env=None, run=None):
    """Installed ``system-images;*`` packages from sdkmanager, with AVD usage."""
    platform = platform or paths.platform_id()
    env = os.environ if env is None else env
    run = run or subprocess.run
    if platform not in ("macos", "linux", "windows"):
        return {"available": False, "reason": "Android system images are desktop only",
                "sdkRoot": None, "images": []}
    sdk = emulator_storage.sdk_root(platform, env)
    manager = _sdkmanager(env, sdk)
    if not sdk:
        return {"available": False, "reason": "No Android SDK on this computer", "sdkRoot": None, "images": []}
    if not manager:
        return {"available": False, "reason": "sdkmanager is not on PATH", "sdkRoot": sdk, "images": []}
    argv = [manager, "--sdk_root=" + sdk, "--list_installed"]
    try:
        result = run(argv, shell=False, capture_output=True, text=True,
                     timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL, check=False, env=dict(env))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": str(exc), "sdkRoot": sdk, "images": []}
    if result.returncode != 0:
        return {"available": False, "reason": (result.stderr or "").strip()[:300] or "sdkmanager --list_installed failed",
                "sdkRoot": sdk, "images": []}
    folder, _ = avd_home(platform, env)
    refs = _avd_image_refs(folder)
    images_root = os.path.join(sdk, "system-images")
    rows = []
    for row in _parse_installed(result.stdout or ""):
        path = _image_folder(sdk, row)
        size = None
        if path and os.path.isdir(path) and not os.path.islink(path) and is_contained(path, images_root):
            measure = fingerprint_path(path)
            if measure and measure["kind"] == "dir":
                size = measure["bytes"]
        users = sorted(refs.get(row["id"], []))
        rows.append({
            "id": row["id"], "name": row["name"], "version": row["version"], "path": path,
            "sizeBytes": size, "avds": users, "unused": not users,
        })
    return {"available": True, "reason": "", "sdkRoot": sdk, "images": rows}


def _running(avd_path, busy_names):
    if avd_path and os.path.isdir(avd_path):
        try:
            names = os.listdir(avd_path)
        except OSError:
            names = []
        if any(name.endswith(".lock") for name in names):
            return True
    return bool(busy_names)


def _measure(path, root):
    if not path or not os.path.isdir(path) or os.path.islink(path):
        return None
    if root and not is_contained(path, root) and os.path.dirname(path) != root:
        # path= may live beside the ini folder (same parent) or inside it.
        parent = os.path.dirname(root)
        if parent and not is_contained(path, parent):
            return None
    measure = fingerprint_path(path)
    if measure and measure["kind"] == "dir":
        return measure["bytes"]
    return None


def inventory(*, platform=None, env=None, process_list=None):
    """Read-only AVD list from ini files. Works without avdmanager."""
    platform = platform or paths.platform_id()
    env = os.environ if env is None else env
    folder, source = avd_home(platform, env)
    if not os.path.isdir(folder):
        return {"available": False, "reason": "No Android AVD folder on this computer",
                "folder": folder, "source": source, "devices": []}
    busy = running_processes(OWNING, names=process_list, platform=platform)
    devices = []
    try:
        entries = os.listdir(folder)
    except OSError as exc:
        return {"available": False, "reason": str(exc), "folder": folder, "source": source, "devices": []}
    for name in sorted(entries):
        if not name.endswith(".ini"):
            continue
        avd_name = name[:-4]
        if not NAME.fullmatch(avd_name):
            continue
        ini_path = os.path.join(folder, name)
        if os.path.islink(ini_path):
            continue
        try:
            with open(ini_path, encoding="utf-8", errors="replace") as handle:
                text = handle.read(8192)
        except OSError:
            continue
        target = _ini_value(text, "path") or os.path.join(folder, avd_name + ".avd")
        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(folder, target))
        exists = os.path.isdir(target) and not os.path.islink(target)
        size = _measure(target, folder) if exists else None
        running = _running(target if exists else None, busy)
        devices.append({
            "id": avd_name, "name": avd_name, "runtime": _ini_value(text, "target") or "",
            "path": target, "state": "Running" if running else "Shutdown",
            "available": exists, "sizeBytes": size,
        })
        if len(devices) >= MAX_AVDS:
            break
    return {"available": True, "reason": "", "folder": folder, "source": source, "devices": devices}


def _digest(devices):
    rows = sorted((d.get("id") or "", d.get("state") or "", bool(d.get("available")),
                   d.get("runtime") or "", d.get("path") or "") for d in devices)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def _summary(device):
    return {"id": device.get("id"), "name": device.get("name"), "runtime": device.get("runtime"),
            "state": device.get("state"), "available": bool(device.get("available")),
            "sizeBytes": device.get("sizeBytes"), "path": device.get("path")}


def _avdmanager(env):
    path = env.get("PATH") if env is not None else None
    found = shutil.which("avdmanager", path=path) or shutil.which("avdmanager.bat", path=path)
    return found


def preview(root, action_id, device_ids=None, *, platform=None, env=None, process_list=None,
            run=None, clock=time.time):
    """Resolve one action against the live inventory and fingerprint its candidates."""
    del root  # catalog root unused; inventory is host AVD files
    action = ACTIONS.get(action_id)
    if action is None:
        raise EmulatorError("Unknown emulator action id")
    platform = platform or paths.platform_id()
    env = os.environ if env is None else env
    if action.get("target") == "images":
        return _preview_image(action_id, action, device_ids, platform=platform, env=env, run=run, clock=clock)
    listed = inventory(platform=platform, env=env, process_list=process_list)
    if not listed["available"]:
        raise EmulatorError(listed["reason"] or "Android emulator inventory is unavailable")
    devices = [d for d in listed["devices"] if isinstance(d.get("id"), str) and NAME.fullmatch(d["id"])]
    if action["select"]:
        if (not isinstance(device_ids, list) or not device_ids or len(device_ids) > MAX_AVDS or
                any(not isinstance(x, str) or not NAME.fullmatch(x) for x in device_ids) or
                len(set(device_ids)) != len(device_ids)):
            raise EmulatorError("deviceIds must list 1 to {0} unique AVD names".format(MAX_AVDS))
        by_id = {d["id"]: d for d in devices}
        missing = [x for x in device_ids if x not in by_id]
        if missing:
            raise EmulatorError("Unknown Android emulator: {0}".format(missing[0]))
        candidates = [by_id[x] for x in device_ids]
        running = [d for d in candidates if d.get("state") != "Shutdown"]
        if running:
            raise EmulatorError("Shut down {0} first; only shut-down emulators can be changed".format(
                running[0].get("name") or running[0]["id"]))
        if action["op"] == "wipe":
            gone = [d for d in candidates if not d.get("available")]
            if gone:
                raise EmulatorError("{0} has no AVD folder to wipe".format(gone[0]["id"]))
        argv = ("avdmanager", "delete", "avd", "-n", *(d["id"] for d in candidates)) if action["op"] == "delete" \
            else ("wipe-avd-data", *(d["id"] for d in candidates))
    else:
        if device_ids:
            raise EmulatorError("This action does not take deviceIds")
        candidates = [d for d in devices if not d.get("available")]
        argv = ("avdmanager", "delete", "avd", "-n", *(d["id"] for d in candidates))
    if action["op"] == "delete" and candidates and not _avdmanager(env):
        raise EmulatorError("avdmanager is not on PATH")
    total = sum(d["sizeBytes"] for d in candidates if isinstance(d.get("sizeBytes"), int))
    return Preview(action_id, argv, tuple(d["id"] for d in candidates), _digest(candidates), len(candidates),
                   total, clock(), action["risk"], tuple(_summary(d) for d in candidates), action["op"])


def _preview_image(action_id, action, package_ids, *, platform, env, run, clock):
    if (not isinstance(package_ids, list) or not package_ids or len(package_ids) > MAX_IMAGES or
            any(not isinstance(item, str) or not PACKAGE.fullmatch(item) for item in package_ids) or
            len(set(package_ids)) != len(package_ids)):
        raise EmulatorError("deviceIds must list 1 to {0} unique system-images packages".format(MAX_IMAGES))
    listed = images(platform=platform, env=env, run=run)
    if not listed["available"]:
        raise EmulatorError(listed["reason"] or "Android system images are unavailable")
    by_id = {item["id"]: item for item in listed["images"]}
    missing = [item for item in package_ids if item not in by_id]
    if missing:
        raise EmulatorError("Unknown system image: {0}".format(missing[0]))
    candidates = [by_id[item] for item in package_ids]
    used = [item for item in candidates if not item["unused"]]
    if used:
        avds = ", ".join(used[0]["avds"][:5]) or "an AVD"
        raise EmulatorError("{0} is still used by {1}".format(used[0]["id"], avds))
    sdk = listed["sdkRoot"]
    manager = _sdkmanager(env, sdk)
    if not manager:
        raise EmulatorError("sdkmanager is not on PATH")
    argv = (manager, "--sdk_root=" + sdk, "--uninstall", *package_ids)
    summaries = tuple({
        "id": item["id"], "name": item["name"], "runtime": item["id"], "path": item["path"],
        "state": "Unused", "available": True, "sizeBytes": item["sizeBytes"], "avds": item["avds"],
    } for item in candidates)
    digest = hashlib.sha256(json.dumps(
        sorted((item["id"], item["version"], item["sizeBytes"], item["unused"], tuple(item["avds"]))
               for item in candidates),
        separators=(",", ":")).encode("utf-8")).hexdigest()
    total = sum(item["sizeBytes"] for item in candidates if isinstance(item.get("sizeBytes"), int))
    return Preview(action_id, argv, tuple(item["id"] for item in candidates), digest, len(candidates),
                   total, clock(), action["risk"], summaries, action["op"])


def _wipe_one(device, folder):
    target = device.get("path") or ""
    if not target or os.path.islink(target) or not os.path.isdir(target):
        raise EmulatorError("Refusing to wipe {0}: folder missing or is a link".format(device["id"]))
    if not is_contained(target, folder) and os.path.dirname(target) != folder:
        parent = os.path.dirname(folder)
        if not parent or not is_contained(target, parent):
            raise EmulatorError("Refusing to wipe {0}: path is outside the AVD home".format(device["id"]))
    for name in WIPE_FILES:
        path = os.path.join(target, name)
        if os.path.isfile(path) and not os.path.islink(path) and is_contained(path, target):
            os.remove(path)
    for name in WIPE_DIRS:
        path = os.path.join(target, name)
        if os.path.isdir(path) and not os.path.islink(path) and is_contained(path, target):
            shutil.rmtree(path)


def execute(root, plan, *, platform=None, env=None, run=None, process_list=None, clock=time.time):
    """Re-preview, then run the stored delete argv or the contained wipe."""
    run = run or subprocess.run
    env = os.environ if env is None else env
    platform = platform or paths.platform_id()
    if clock() - plan.created_at > EXPIRY_SECONDS:
        raise EmulatorError("Emulator preview expired")
    select = ACTIONS[plan.action_id]["select"]
    fresh = preview(root, plan.action_id, list(plan.device_ids) if select else None,
                    platform=platform, env=env, process_list=process_list, run=run, clock=clock)
    if fresh.argv != plan.argv or fresh.digest != plan.digest:
        raise EmulatorError("Android emulators changed; preview again")
    if plan.count == 0:
        raise EmulatorError("There are no Android emulators to change")
    if plan.op == "uninstall":
        manager = plan.argv[0]
        sdk_flag = plan.argv[1] if len(plan.argv) > 1 else "--sdk_root="
        outputs = []
        for package in plan.device_ids:
            argv = [manager, sdk_flag, "--uninstall", package]
            try:
                result = run(argv, shell=False, capture_output=True, text=True,
                             timeout=RUN_TIMEOUT, stdin=subprocess.DEVNULL, check=False, env=dict(env))
            except (OSError, subprocess.SubprocessError) as exc:
                raise EmulatorError("sdkmanager failed: {0}".format(exc)) from exc
            if result.returncode != 0:
                raise EmulatorError((result.stderr or "").strip()[:500] or "sdkmanager returned an error")
            outputs.append((result.stdout or "").strip())
        return {"kind": "emulators", "actionId": plan.action_id, "status": "completed",
                "candidateCount": plan.count, "devices": list(plan.devices),
                "command": ["sdkmanager", "--uninstall", *plan.device_ids],
                "output": "\n".join(outputs)[:2000], "bytesFreed": plan.bytes}
    if plan.op == "wipe":
        folder, _ = avd_home(platform, env)
        for device in plan.devices:
            _wipe_one(device, folder)
        return {"kind": "emulators", "actionId": plan.action_id, "status": "completed",
                "candidateCount": plan.count, "devices": list(plan.devices), "command": list(plan.argv),
                "output": "", "bytesFreed": plan.bytes}
    manager = _avdmanager(env)
    if not manager:
        raise EmulatorError("avdmanager is not on PATH")
    outputs = []
    for name in plan.device_ids:
        argv = [manager, "delete", "avd", "-n", name]
        try:
            result = run(argv, shell=False, capture_output=True, text=True,
                         timeout=RUN_TIMEOUT, stdin=subprocess.DEVNULL, check=False, env=dict(env))
        except (OSError, subprocess.SubprocessError) as exc:
            raise EmulatorError("avdmanager failed: {0}".format(exc)) from exc
        if result.returncode != 0:
            raise EmulatorError((result.stderr or "").strip()[:500] or "avdmanager returned an error")
        outputs.append((result.stdout or "").strip())
    return {"kind": "emulators", "actionId": plan.action_id, "status": "completed",
            "candidateCount": plan.count, "devices": list(plan.devices),
            "command": ["avdmanager", "delete", "avd", "-n", *plan.device_ids],
            "output": "\n".join(outputs)[:2000], "bytesFreed": plan.bytes}
