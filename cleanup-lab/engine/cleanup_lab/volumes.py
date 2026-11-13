"""Read-only local mounted-volume inventory (CLN-28)."""
from __future__ import annotations

import ctypes
import ntpath
import os
import plistlib
import re
import shutil
import subprocess

from .paths import home_dir, platform_id

PRESSURE_PERCENT = 85
NETWORK_FS = {"nfs", "nfs4", "cifs", "smbfs", "afpfs", "sshfs", "fuse.sshfs", "davfs", "9p"}
PSEUDO_FS = {"proc", "sysfs", "tmpfs", "devtmpfs", "devfs", "overlay", "squashfs",
             "cgroup", "cgroup2", "securityfs", "debugfs", "tracefs", "pstore",
             "mqueue", "hugetlbfs", "fusectl", "configfs", "autofs", "ramfs"}
MOUNT_LINE = re.compile(r"^.+ on (.+) \(([^,]+)(?:,\s*(.*))?\)$")


def _unescape(value):
    return re.sub(r"\\([0-7]{3})", lambda found: chr(int(found.group(1), 8)), value)


def linux_mounts(text):
    """Parse kernel mountinfo; return (mount, filesystem, source) tuples."""
    mounts = []
    for line in text.splitlines():
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        head, tail = left.split(), right.split()
        if len(head) < 5 or len(tail) < 2:
            continue
        mount, fs, source = _unescape(head[4]), tail[0], _unescape(tail[1])
        if fs in NETWORK_FS or fs in PSEUDO_FS or fs.startswith(("fuse.", "nfs")):
            continue
        if source.startswith("//") or ":" in source:
            continue
        mounts.append((mount, fs, source))
    return mounts


def macos_mounts(text):
    mounts = []
    for line in text.splitlines():
        found = MOUNT_LINE.match(line)
        if not found:
            continue
        mount, fs, options = found.groups()
        if fs in NETWORK_FS or fs in PSEUDO_FS or "local" not in (options or "").split(", "):
            continue
        if mount.startswith("/System/Volumes/") and mount != "/System/Volumes/Data":
            continue
        mounts.append((_unescape(mount), fs, line.split(" on ", 1)[0]))
    return mounts


def windows_mounts(*, drives=None, drive_type=None):
    kernel = ctypes.windll.kernel32 if drives is None or drive_type is None else None
    mask = kernel.GetLogicalDrives() if drives is None else drives
    kind = kernel.GetDriveTypeW if drive_type is None else drive_type
    return [("{0}:\\".format(chr(65 + index)), "windows", "")
            for index in range(26) if mask & (1 << index) and kind("{0}:\\".format(chr(65 + index))) in (2, 3)]


def _disk(mount, *, usage=shutil.disk_usage):
    try:
        data = usage(mount)
    except OSError:
        return None
    total, free = int(data.total), int(data.free)
    if total <= 0:
        return None
    return total, free


def _linux_removable(source, *, reader=None):
    if not source.startswith("/dev/"):
        return None
    candidate = "/sys/class/block/{0}/removable".format(os.path.basename(source))
    try:
        if reader:
            value = reader(candidate).strip()
        else:
            with open(candidate, encoding="ascii") as handle:
                value = handle.read().strip()
        return value == "1" if value in ("0", "1") else None
    except OSError:
        return None


def _mac_flags(mount, *, runner=subprocess.run):
    try:
        result = runner(["diskutil", "info", "-plist", mount], capture_output=True, timeout=5)
        if result.returncode:
            return None, None
        data = plistlib.loads(result.stdout)
        internal = data.get("Internal")
        removable = data.get("RemovableMedia")
        return (internal if isinstance(internal, bool) else None,
                removable if isinstance(removable, bool) else None)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, None


def report(*, platform=None, env=None, mountinfo=None, mount_output=None,
           usage=shutil.disk_usage, runner=subprocess.run, removable_reader=None,
           drives=None, drive_type=None, stat_fn=os.stat, threshold=PRESSURE_PERCENT):
    """List local disks only; unknown internal/removable flags stay null."""
    target = platform or platform_id()
    env = os.environ if env is None else env
    if target == "linux":
        if mountinfo is None:
            with open("/proc/self/mountinfo", encoding="utf-8") as handle:
                mountinfo = handle.read()
        found = linux_mounts(mountinfo)
    elif target == "macos":
        if mount_output is None:
            mount_output = runner(["mount"], capture_output=True, text=True, timeout=5).stdout
        found = macos_mounts(mount_output)
    elif target == "windows":
        found = windows_mounts(drives=drives, drive_type=drive_type)
    else:
        found = []
    home = (ntpath.normcase(ntpath.normpath(env.get("USERPROFILE", ""))) if target == "windows"
            else os.path.normpath(home_dir(env)))
    root = ((env.get("SystemDrive") or "C:").upper() + "\\" if target == "windows"
            else os.path.abspath(os.sep))
    rows = []
    seen = set()
    for mount, fs, source in found:
        mount = os.path.normpath(mount)
        if mount in seen:
            continue
        seen.add(mount)
        space = _disk(mount, usage=usage)
        if space is None:
            continue
        total, free = space
        internal = removable = None
        if target == "linux":
            removable = _linux_removable(source, reader=removable_reader)
            internal = None if removable is None else not removable
        elif target == "macos":
            internal, removable = _mac_flags(mount, runner=runner)
        elif target == "windows":
            removable = drive_type(mount) == 2 if drive_type else ctypes.windll.kernel32.GetDriveTypeW(mount) == 2
            internal = not removable
        used = round((total - free) * 100 / total, 1)
        rows.append({"name": os.path.basename(mount.rstrip(os.sep)) or mount,
                     "mountPoint": mount, "filesystem": fs, "source": source,
                     "totalBytes": total, "freeBytes": free, "usedPercent": used,
                     "pressure": used >= threshold, "root": mount.upper() == root.upper(),
                     "removable": removable, "internal": internal, "home": False})
    if target == "windows":
        home_rows = [row for row in rows if home.startswith(ntpath.normcase(row["mountPoint"]))]
    else:
        home_rows = [row for row in rows if home == row["mountPoint"] or
                     home.startswith(row["mountPoint"].rstrip(os.sep) + os.sep)]
    if target != "windows":
        try:
            home_dev = stat_fn(home).st_dev
            same_device = [row for row in rows if stat_fn(row["mountPoint"]).st_dev == home_dev]
        except OSError:
            same_device = []
        if same_device:
            home_rows = same_device
    if home_rows:
        max(home_rows, key=lambda row: len(row["mountPoint"]))["home"] = True
    return {"platform": target, "thresholdPercent": threshold,
            "volumes": rows, "homeVolume": next((row["mountPoint"] for row in rows if row["home"]), None)}
