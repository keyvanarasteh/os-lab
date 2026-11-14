"""CLN-29 report-only inventory of simulator and emulator runtimes.

Xcode simulator runtimes (``xcrun simctl runtime list -j``) and Android AVDs
plus SDK system images (``avdmanager list avd`` and the SDK's
``system-images`` tree), each with its size and in-use state. Everything here
is report-only: there is no deletion API in this module — the typed preview
and removal land separately.

All external probes are injectable through a ``run`` callable shaped like
``subprocess.run`` (fixed argv, ``capture_output=True``, ``text=True``,
``timeout=5``, ``check=False``), defaulting to ``subprocess.run``; the tests
pass fakes and never launch a real probe (rule 8). Sizes come from a small
local read-only directory walk (``os.scandir`` + ``lstat``): symlinks are
never followed, a hard link is counted once per walk by ``(device, inode)``,
sockets and device nodes are not measured, and an unreadable path is counted
in the item's ``unreadable`` instead of failing the walk. Apparent size
(``st_size``) and on-disk size (``st_blocks * 512``) are reported separately;
on-disk is ``None`` where the OS exposes no block count.
"""
from __future__ import annotations

import json
import os
import stat
import re
import subprocess

from .readiness import repo_root
from .paths import home_dir, platform_id

#: The fixed probe arguments; no shell, no interpolation, five-second timeout.
XCODE_RUNTIMES_ARGV = ["xcrun", "simctl", "runtime", "list", "-j"]
AVDMANAGER_ARGV = ["avdmanager", "list", "avd"]


def _text(value):
    """A non-empty string or ``None`` — the defensive read of a probe field."""
    return value if isinstance(value, str) and value else None


def _walk_size(path):
    """Read-only size walk: ``{"sizeBytes", "sizeOnDiskBytes", "unreadable"}``.

    ``lstat`` only: symlinks are never followed or counted, sockets, FIFOs and
    device nodes are not measured, a hard link is counted once per walk by
    ``(device, inode)`` and an unreadable entry is counted in ``unreadable``
    rather than failing the walk. ``None`` when ``path`` is missing, is a
    symlink or is not a walkable node — nothing is guessed about what it would
    contain.
    """
    try:
        root_stat = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(root_stat.st_mode):
        return None
    if not stat.S_ISDIR(root_stat.st_mode):
        if not stat.S_ISREG(root_stat.st_mode):
            return None
        blocks = getattr(root_stat, "st_blocks", None)
        return {"sizeBytes": root_stat.st_size,
                "sizeOnDiskBytes": blocks * 512 if blocks is not None else None,
                "unreadable": 0}
    seen, size, on_disk, has_blocks, unreadable = set(), 0, 0, True, 0
    stack = [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as iterator:
                entries = list(iterator)
        except OSError:
            unreadable += 1
            continue
        for entry in entries:
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                unreadable += 1
                continue
            mode = entry_stat.st_mode
            if stat.S_ISLNK(mode):
                continue  # a link is never followed and never counted
            if stat.S_ISDIR(mode):
                stack.append(entry.path)
                continue
            if not stat.S_ISREG(mode):
                continue  # sockets, FIFOs and device nodes are not measured
            key = (entry_stat.st_dev, entry_stat.st_ino)
            if key in seen:
                continue  # a hard link is counted once per walk
            seen.add(key)
            size += entry_stat.st_size
            blocks = getattr(entry_stat, "st_blocks", None)
            if blocks is None:
                has_blocks = False
            else:
                on_disk += blocks * 512
    return {"sizeBytes": size,
            "sizeOnDiskBytes": on_disk if has_blocks else None,
            "unreadable": unreadable}


def _expand_home(template, env):
    """The ``~`` templates the simulator roots file uses, against ``env``."""
    if template == "~":
        return home_dir(env)
    if template.startswith("~/") or template.startswith("~\\"):
        return os.path.join(home_dir(env), template[2:])
    return template


def _simulator_root(root, env):
    """The allowed simulator root from ``cleanup-lab/simulator-roots.json``.

    ``None`` when the file is missing, unreadable or malformed: no path is
    then verifiable as inside the configured root, so no size is walked.
    """
    path = os.path.join(root, "cleanup-lab", "simulator-roots.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        template = data["macos"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(template, str) or not template:
        return None
    return _expand_home(template, env)


def _inside(path, base):
    """Whether the resolved ``path`` stays inside the resolved ``base``."""
    try:
        resolved = os.path.realpath(path)
        root = os.path.realpath(base)
    except (OSError, ValueError):
        return False
    try:
        return os.path.commonpath([resolved, root]) == root
    except ValueError:
        return False


def xcode_runtimes(root, *, platform=None, env=None, run=subprocess.run):
    """The Xcode simulator runtimes as a report-only inventory.

    ``platform != "macos"`` refuses honestly. The fixed ``xcrun simctl
    runtime list -j`` probe is injectable through ``run``; a missing binary,
    a non-zero exit or JSON that cannot be trusted is an honest
    ``{"available": False, "reason": ..., "items": []}``. The JSON may be the
    wrapper ``{"runtimes": {...}}`` or a bare map keyed by runtime identifier;
    entries that are not objects are skipped.

    A runtime bundle path is measured only when it stays inside the configured
    simulator root (``cleanup-lab/simulator-roots.json``, ``~`` expanded
    against ``env``): a path outside it, or a roots file that cannot be read,
    keeps ``sizeBytes: None`` and carries a ``note`` saying why. Items are
    ``{"kind": "xcode-runtime", "id", "name", "build", "platform", "path",
    "sizeBytes", "sizeOnDiskBytes", "unreadable", "inUse": False,
    "deletable": True}``; ``inUse`` is always False here (simctl is the
    authority on runtime state and is not a lock this module can read).
    """
    if (platform or platform_id()) != "macos":
        return {"available": False, "reason": "Xcode simulator runtimes require macOS", "items": []}
    try:
        result = run(XCODE_RUNTIMES_ARGV, shell=False, capture_output=True, text=True,
                     timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": str(exc), "items": []}
    if result.returncode != 0:
        return {"available": False,
                "reason": (result.stderr or "").strip() or "simctl failed",
                "items": []}
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return {"available": False, "reason": "simctl returned invalid JSON", "items": []}
    if not isinstance(data, dict):
        return {"available": False, "reason": "simctl returned an unexpected JSON shape",
                "items": []}
    entries = data.get("runtimes")
    if entries is None:
        entries = data  # a bare map keyed by runtime identifier
    elif not isinstance(entries, dict):
        return {"available": False, "reason": "simctl returned an unexpected JSON shape",
                "items": []}
    env = os.environ if env is None else env
    allowed = _simulator_root(root, env)
    items = []
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue  # a malformed entry is skipped, never fatal
        path = _text(entry.get("runtimeBundlePath")) or _text(entry.get("path"))
        item = {"kind": "xcode-runtime",
                "id": _text(entry.get("runtimeIdentifier"))
                or _text(entry.get("bundleIdentifier")) or key,
                "name": _text(entry.get("name")) or key,
                "build": _text(entry.get("build")),
                "platform": _text(entry.get("platform")),
                "path": path,
                "sizeBytes": None, "sizeOnDiskBytes": None, "unreadable": 0,
                "inUse": False, "deletable": True}
        if path is not None:
            if allowed is None:
                item["note"] = "the configured simulator roots cannot be read"
            elif not _inside(path, allowed):
                item["note"] = "outside the configured simulator roots"
            else:
                walked = _walk_size(path)
                if walked is not None:
                    item["sizeBytes"] = walked["sizeBytes"]
                    item["sizeOnDiskBytes"] = walked["sizeOnDiskBytes"]
                    item["unreadable"] = walked["unreadable"]
        items.append(item)
    return {"available": True, "reason": None, "items": items}


def _parse_avds(text):
    """The per-AVD blocks of ``avdmanager list avd`` text, defensively.

    ``Name:`` opens a block, ``Path:`` and ``Based on:`` fill it; anything
    else (separators, preambles, the "could not be loaded" section) is
    ignored. A block with an empty name is dropped.
    """
    avds, current = [], None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key == "Name":
            current = {"name": value, "path": None, "basedOn": None}
            if current["name"]:
                avds.append(current)
            else:
                current = None
        elif current is not None and key == "Path":
            current["path"] = value or None
        elif current is not None and key == "Based on":
            current["basedOn"] = value or None
    return avds


def _avd_home(env):
    """``ANDROID_AVD_HOME`` when absolute, else ``<home>/.android/avd``.

    A relative override is refused the way :mod:`cleanup_lab.paths` refuses
    relative XDG values — it would resolve against the working directory.
    """
    override = env.get("ANDROID_AVD_HOME")
    if override and os.path.isabs(override):
        return override
    return os.path.join(home_dir(env), ".android", "avd")


def _sdk_root(env, platform):
    """``ANDROID_SDK_ROOT`` when absolute, else the per-OS default location."""
    override = env.get("ANDROID_SDK_ROOT")
    if override and os.path.isabs(override):
        return override
    if platform == "macos":
        return os.path.join(home_dir(env), "Library", "Android", "sdk")
    return os.path.join(home_dir(env), "Android", "Sdk")


def _avd_in_use(path):
    """The in-use heuristic: emulator ``*.lock`` files; presence, never proof.

    The emulator holds ``*.lock`` files beside the AVD folder
    (``<name>.avd.lock``) and inside it while an instance runs, and an
    unclean shutdown can leave one behind — a lock marks ``inUse`` without
    proving a live process. A folder that cannot be listed cannot prove
    in-use either.
    """
    if not path:
        return False
    try:
        if os.path.lexists(path + ".lock"):
            return True
        if os.path.isdir(path) and not os.path.islink(path):
            with os.scandir(path) as iterator:
                return any(entry.name.endswith(".lock") for entry in iterator)
    except OSError:
        return False
    return False


def _avd_items(parsed, env):
    """AVD records to items; a missing ``Path:`` is filled from the AVD home.

    When ``avdmanager`` does not name a path, the AVD folder is looked up as
    ``<avd home>/<name>.avd`` and only reported when it exists — nothing is
    guessed beyond that.
    """
    avd_home = _avd_home(env)
    items = []
    for avd in parsed:
        path = avd["path"]
        if path is None:
            candidate = os.path.join(avd_home, avd["name"] + ".avd")
            if os.path.isdir(candidate) and not os.path.islink(candidate):
                path = candidate
        walked = _walk_size(path) if path is not None else None
        items.append({"kind": "avd", "id": avd["name"], "name": avd["name"],
                      "path": path, "basedOn": avd["basedOn"],
                      "sizeBytes": walked["sizeBytes"] if walked else None,
                      "sizeOnDiskBytes": walked["sizeOnDiskBytes"] if walked else None,
                      "unreadable": walked["unreadable"] if walked else 0,
                      "inUse": _avd_in_use(path), "deletable": True})
    return items


def _system_images(images_root):
    """One item per leaf variant directory under ``system-images``.

    The tree is ``<api>/<tag>/<abi>/``; a directory that still holds
    directories is a branch, a directory whose children are all files is a
    variant. Unreadable branches are skipped, links are never descended into,
    and the root itself is never reported as a variant.
    """
    items = []
    stack = [(images_root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except OSError:
            continue  # an unreadable branch is skipped, never fatal
        children = []
        for entry in entries:
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(entry_stat.st_mode):
                children.append(entry.path)
        if children:
            stack.extend((child, depth + 1) for child in children)
            continue
        if depth == 0:
            continue
        walked = _walk_size(current)
        # the id is sdkmanager's package form — the same string its uninstall
        # command consumes — so the inventory id and the delete id match
        items.append({"kind": "system-image",
                      "id": "system-images;" + os.path.relpath(current, images_root).replace(os.sep, ";"),
                      "path": current,
                      "sizeBytes": walked["sizeBytes"] if walked else None,
                      "sizeOnDiskBytes": walked["sizeOnDiskBytes"] if walked else None,
                      "unreadable": walked["unreadable"] if walked else 0,
                      "inUse": False, "deletable": True})
    items.sort(key=lambda item: item["id"])
    return items


def android_avds(root, *, platform=None, env=None, run=subprocess.run):
    """Android AVDs and SDK system images as a report-only inventory.

    Two probes: the fixed ``avdmanager list avd`` text listing (injectable
    through ``run``) and the SDK's ``system-images`` tree under
    ``ANDROID_SDK_ROOT`` or the per-OS default (``<home>/Library/Android/sdk``
    on macOS, ``<home>/Android/Sdk`` elsewhere). ``avdmanager`` missing or
    failing is not fatal — the system-image probe can still answer, and
    ``available`` is true when at least one probe answered; what did not
    answer is named in ``reason`` (``None`` when every probe answered).

    ``inUse`` is the ``*.lock`` heuristic (:func:`_avd_in_use`); system
    images are immutable payloads and are never marked in use. ``root`` is
    accepted for interface symmetry with :func:`xcode_runtimes`; every
    Android location comes from the environment.
    """
    del root  # interface symmetry; Android locations come from the environment
    env = os.environ if env is None else env
    platform = platform or platform_id()
    problems = []
    avds, answered = [], False
    try:
        result = run(AVDMANAGER_ARGV, shell=False, capture_output=True, text=True,
                     timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append("avdmanager could not be run: {0}".format(exc))
    else:
        if result.returncode != 0:
            problems.append((result.stderr or "").strip() or "avdmanager failed")
        else:
            answered = True
            avds = _avd_items(_parse_avds(result.stdout), env)
    sdk_root = _sdk_root(env, platform)
    images, sdk_answered = [], False
    if not os.path.isdir(sdk_root):
        problems.append("the Android SDK root {0} was not found".format(sdk_root))
    else:
        sdk_answered = True
        images_root = os.path.join(sdk_root, "system-images")
        if not os.path.isdir(images_root):
            pass  # an SDK without system-images answered with none
        elif os.path.islink(images_root):
            problems.append("the SDK's system-images directory is a symlink; "
                            "it was not followed")
        else:
            images = _system_images(images_root)
    return {"available": answered or sdk_answered,
            "reason": "; ".join(problems) if problems else None,
            "items": avds + images}


# ── typed delete actions (CLN-29): fixed argv, fresh-candidate check ─────────


#: Fixed argv prefixes for the typed delete actions. The id is the only
#: variable part, validated per kind before it joins the argv — the page sends
#: kind and id, never a command. System images go through sdkmanager's
#: uninstall path, whose id is the ; -separated package path.
_DELETE_PREFIXES = {
    "xcode-runtime": ["xcrun", "simctl", "runtime", "delete"],
    "avd": ["avdmanager", "delete", "avd", "-n"],
    "system-image": ["sdkmanager", "uninstall"],
}
_ID_PATTERNS = {
    "xcode-runtime": re.compile(r"^[A-Za-z0-9._-]{6,128}$"),
    "avd": re.compile(r"^[A-Za-z0-9._-]{1,128}$"),
    "system-image": re.compile(r"^[A-Za-z0-9._+-]+(;[A-Za-z0-9._+-]+){2,}$"),
}


def delete_argv(kind, identifier, *, platform=None, env=None, run=subprocess.run):
    """The fixed argv for one typed delete action, with the fresh-candidate check.

    Refuses an unknown kind, an id that fails its kind's shape, and — the
    CLN-08 fresh-candidate check — an id that no longer appears in a fresh
    inventory: the page confirms what the scan saw, and the run re-checks it
    before anything executes. Returns the argv for the preview to show.
    """
    if kind not in _DELETE_PREFIXES:
        raise ValueError("kind must be one of: {0}".format(", ".join(_DELETE_PREFIXES)))
    if not isinstance(identifier, str) or not _ID_PATTERNS[kind].match(identifier):
        raise ValueError("The id does not match the shape for {0}.".format(kind))
    root = repo_root()
    if kind == "xcode-runtime":
        items = xcode_runtimes(root, platform=platform, env=env, run=run)["items"]
    else:
        items = android_avds(root, platform=platform, env=env, run=run)["items"]
    if not any(item["kind"] == kind and item["id"] == identifier for item in items):
        raise ValueError(
            "The {0} {1} is no longer in the inventory; refresh and try again.".format(kind, identifier)
        )
    return [*_DELETE_PREFIXES[kind], identifier]


def run_delete(argv, *, run=subprocess.run):
    """Execute one delete argv exactly as previewed; reports the honest outcome."""
    try:
        completed = run(argv, capture_output=True, text=True, check=False, timeout=3600)
    except subprocess.TimeoutExpired as exc:
        return {"status": "failed", "argv": argv,
                "error": "The delete timed out: {0}".format(exc)}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "argv": argv,
                "error": "{0}: {1}".format(type(exc).__name__, exc)}
    tail = (completed.stdout or "")[-2000:]
    errors = (completed.stderr or "")[-2000:]
    return {
        "status": "completed" if completed.returncode == 0 else "failed",
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": tail,
        "stderr": errors,
        **({} if completed.returncode == 0 else {"error": errors.strip() or "The tool refused the delete."}),
    }
