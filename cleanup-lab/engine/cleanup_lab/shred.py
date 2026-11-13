"""Best-effort overwriting of regular files before removal (CLN-14).

Overwriting does not guarantee erasure on SSD, APFS or other copy-on-write,
wear-levelled, snapshotted or backed-up storage. Failures are returned per path.
"""
from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass, field

CHUNK = 1024 * 1024
LIMITATION = "Overwriting cannot guarantee erasure on SSD, APFS, copy-on-write, snapshotted or backed-up storage."


@dataclass
class Outcome:
    bytes_removed: int = 0
    files_removed: int = 0
    folders_removed: int = 0
    errors: list[str] = field(default_factory=list)


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        count = os.write(fd, view)
        if count is None or count <= 0:
            raise OSError("Short write while overwriting")
        view = view[count:]


def _overwrite(path, passes, *, random_bytes=os.urandom, cancel=None):
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink > 1:
        raise OSError("Only regular files with one link can be shredded")
    flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OSError("File changed before overwrite")
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink > 1:
            raise OSError("File is no longer a single-link regular file")
        size = opened.st_size
        for pattern in passes:
            os.lseek(fd, 0, os.SEEK_SET)
            remaining = size
            while remaining:
                if cancel is not None and cancel.is_set():
                    raise OSError("Cancelled during overwrite")
                length = min(CHUNK, remaining)
                data = random_bytes(length) if pattern == "random" else bytes([pattern]) * length
                _write_all(fd, data)
                remaining -= length
            os.fsync(fd)
            after = os.fstat(fd)
            if (after.st_dev, after.st_ino, after.st_size) != (opened.st_dev, opened.st_ino, size):
                raise OSError("File changed during overwrite")
    finally:
        os.close(fd)
    return size


def _rename_unlink(path):
    parent = os.path.dirname(path)
    renamed = os.path.join(parent, "." + secrets.token_hex(16))
    if os.path.lexists(renamed):
        raise OSError("Random rename target already exists")
    os.rename(path, renamed)
    try:
        os.unlink(renamed)
    except OSError:
        # The original name is gone; report the remaining random-name path.
        raise OSError("Could not unlink renamed file {0}".format(renamed))


def shred_tree(path, policy, *, cancel=None):
    """Overwrite and remove each regular file, returning all failures and removed bytes."""
    if policy not in ("one-pass", "three-pass"):
        raise ValueError("Shred policy must be one-pass or three-pass")
    passes = ("random",) if policy == "one-pass" else (0, 255, "random")
    outcome = Outcome()
    stack = [(path, False)]
    while stack:
        current, post = stack.pop()
        if cancel is not None and cancel.is_set():
            outcome.errors.append("Cancelled before {0}".format(current))
            break
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            outcome.errors.append("{0}: {1}".format(current, exc))
            continue
        if stat.S_ISLNK(mode):
            outcome.errors.append("{0}: symlink refused".format(current))
            continue
        if stat.S_ISREG(mode):
            try:
                size = _overwrite(current, passes, cancel=cancel)
                _rename_unlink(current)
                outcome.bytes_removed += size
                outcome.files_removed += 1
            except OSError as exc:
                outcome.errors.append("{0}: {1}".format(current, exc))
            continue
        if not stat.S_ISDIR(mode):
            outcome.errors.append("{0}: special file refused".format(current))
            continue
        if post:
            try:
                os.rmdir(current)
                outcome.folders_removed += 1
            except OSError as exc:
                outcome.errors.append("{0}: {1}".format(current, exc))
            continue
        stack.append((current, True))
        try:
            with os.scandir(current) as iterator:
                children = list(iterator)
        except OSError as exc:
            outcome.errors.append("{0}: {1}".format(current, exc))
            continue
        stack.extend((child.path, False) for child in children)
    return outcome
