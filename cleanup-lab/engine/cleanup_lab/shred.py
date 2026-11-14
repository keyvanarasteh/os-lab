"""Secure shred: overwrite in place, random rename, unlink — honestly (CLN-14).

The *technique* is the classic one (and what bleachbit's ``Wipe.py`` does): a
regular file is overwritten in place pass by pass, renamed to a random name to
obscure what it was, and only then unlinked. A folder is shredded bottom-up:
every regular file inside first, then the folders are removed deepest-first,
the planned root last. What this module refuses to inherit from Qleaner's
shredder is its core bug — ignoring write and remove errors and still reporting
success. Here every failure (overwrite, rename, unlink, folder removal) is a
reported failure, and bytes are counted only for files verifiably gone from
their original path.

Deterministic pass order: ``1-pass`` writes zeros once; ``3-pass`` writes
zeros, then ones (``0xFF``), then random bytes from the OS. Every pass is
flushed and ``fsync``ed before the next pattern overwrites it.

Honest limits (the dashboard confirm dialog says the same): overwriting is not
a guarantee on SSD, APFS or copy-on-write filesystems — wear levelling,
over-provisioning and copy-on-write can leave the original blocks elsewhere on
the device. Shred is a best-effort technique, not a promise.

Symlinks are never followed (rule 1). A symlink planned as the target is
refused; a symlink inside a shredded folder is unlinked as the bare link (the
referent outside the folder is untouched). Sockets, FIFOs and device nodes are
refused everywhere: shred only ever destroys the contents of regular files, so
a refused node stays in place and its containing folder's removal fails
honestly with ``ENOTEMPTY``.
"""
from __future__ import annotations

import errno
import os
import stat as stat_mod
import uuid

#: Overwrite chunk size: 1 MiB, so a pass streams instead of buffering the file.
CHUNK = 1024 * 1024
#: Overwrite passes per settings policy (``cleanup_lab.settings``).
PASSES = {"1-pass": 1, "3-pass": 3}
#: Prefix for the random renamed file, inside the file's own folder.
RENAME_PREFIX = ".oslab-shred-"
#: Attempts to find a free random name before giving up with an honest error.
RENAME_ATTEMPTS = 5


class ShredError(ValueError):
    """One item could not be shredded; ``str`` is the per-item error."""


def passes_for(policy):
    """The overwrite pass count for a policy value, or ``None`` when off/unknown."""
    return PASSES.get(policy)


def _open_no_follow(path):
    """Open ``path`` read-write without following a final symlink (rule 1).

    ``O_NOFOLLOW`` closes the swap-the-link race between the caller's ``lstat``
    and this open, on platforms that have it. ``O_BINARY`` keeps Windows from
    translating newline bytes during the overwrite.
    """
    flags = os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    return os.open(path, flags)


def _check_target_file(path, lstat):
    """``(size, info)`` for a regular file; a symlink or special node is refused."""
    try:
        info = lstat(path)
    except OSError as exc:
        raise ShredError("The item cannot be read: {0}".format(exc)) from exc
    if stat_mod.S_ISLNK(info.st_mode):
        raise ShredError("This is a symlink; shred never follows links.")
    if not stat_mod.S_ISREG(info.st_mode):
        raise ShredError("Not a regular file; sockets, FIFOs and device nodes are refused.")
    return info.st_size, info


def _overwrite_pass(fd, size, index, *, write, urandom, fsync):
    """Write one full pass over ``fd``: pass 0 zeros, pass 1 ones, later random.

    Seeks to the start, writes exactly ``size`` bytes (a short write raises
    instead of being ignored), then ``fsync``s — the pattern must reach the
    device before the next pass overwrites it.
    """
    fill = {0: b"\x00", 1: b"\xff"}.get(index)
    os.lseek(fd, 0, os.SEEK_SET)
    remaining = size
    while remaining > 0:
        chunk = min(CHUNK, remaining)
        data = urandom(chunk) if fill is None else fill * chunk
        written = write(fd, data)
        if written != chunk:
            raise OSError(errno.EIO, "short write during overwrite pass {0}".format(index + 1))
        remaining -= written
    fsync(fd)


def shred_file(
    path,
    passes,
    *,
    open=_open_no_follow,
    write=os.write,
    rename=os.rename,
    unlink=os.unlink,
    lstat=os.lstat,
    lexists=os.path.lexists,
    fsync=os.fsync,
    urandom=os.urandom,
):
    """Shred one regular file in place: overwrite passes, random rename, unlink.

    Every step is verified; the first failure raises :class:`ShredError` saying
    how far it got (contents overwritten under the old name, or contents
    overwritten and renamed but not removed). No retries: a transient failure
    is reported like any other — honesty over optimism. Returns the file size
    the overwrite covered, for the caller's honest byte count.
    """
    if not isinstance(passes, int) or isinstance(passes, bool) or passes < 1:
        raise ShredError("The overwrite pass count must be a whole number of at least 1.")
    size, info = _check_target_file(path, lstat)
    try:
        fd = open(path)
    except OSError as exc:
        raise ShredError("The file cannot be opened for overwriting: {0}".format(exc)) from exc
    try:
        for index in range(passes):
            _overwrite_pass(fd, size, index, write=write, urandom=urandom, fsync=fsync)
    except OSError as exc:
        raise ShredError(
            "Overwrite failed; the file was left in place with its old name: {0}".format(exc)
        ) from exc
    finally:
        os.close(fd)
    try:
        fresh = lstat(path)
    except OSError as exc:
        raise ShredError("The file cannot be re-read after overwriting: {0}".format(exc)) from exc
    if fresh.st_dev != info.st_dev or fresh.st_ino != info.st_ino:
        raise ShredError("The file was replaced while it was being overwritten; it was left in place.")
    if fresh.st_size != size:
        raise ShredError("The file changed size while it was being overwritten; it was left in place.")
    folder = os.path.dirname(os.path.abspath(path))
    renamed = None
    for _ in range(RENAME_ATTEMPTS):
        candidate = os.path.join(folder, "{0}{1}".format(RENAME_PREFIX, uuid.uuid4().hex[:16]))
        if not lexists(candidate):
            renamed = candidate
            break
    if renamed is None:
        raise ShredError("The contents are overwritten but no free name was found to rename the file.")
    try:
        rename(path, renamed)
    except OSError as exc:
        raise ShredError(
            "The contents are overwritten but the file could not be renamed: {0}".format(exc)
        ) from exc
    try:
        unlink(renamed)
    except OSError as exc:
        raise ShredError(
            "The contents are overwritten but the renamed file {0} could not be removed: {1}".format(
                renamed, exc
            )
        ) from exc
    if lexists(path) or lexists(renamed):
        raise ShredError("The file is still present after shredding; nothing would be counted.")
    return size


def shred_path(
    path,
    passes,
    *,
    open=_open_no_follow,
    write=os.write,
    rename=os.rename,
    unlink=os.unlink,
    rmdir=os.rmdir,
    lstat=os.lstat,
    lexists=os.path.lexists,
    fsync=os.fsync,
    urandom=os.urandom,
    scandir=os.scandir,
):
    """Shred one planned item and return ``(summary, entries)`` — never raises.

    A regular file is shredded in place (:func:`shred_file`). A folder is
    shredded bottom-up: every regular file inside first, then the folders
    removed deepest-first, the planned root last; the walk never follows
    symlinks, and a folder whose listing fails is refused and left in place.
    Each entry reports ``shredded`` (a regular file overwritten,
    renamed and unlinked — ``bytes`` is the size the overwrite covered),
    ``unlinked`` (a bare symlink removed; the link only, never its referent),
    ``removed`` (a folder taken out) or ``failed`` with the error string. The
    summary counts only verified destruction; ``errors`` is the failure count.
    """
    entries = []

    def failed(target, error):
        entries.append({"path": target, "status": "failed", "bytes": 0, "error": error})

    try:
        info = lstat(path)
    except OSError as exc:
        failed(path, "The item cannot be read: {0}".format(exc))
        return _summary(entries), entries
    if stat_mod.S_ISLNK(info.st_mode):
        failed(path, "This is a symlink; shred never follows links and refuses it.")
        return _summary(entries), entries
    if stat_mod.S_ISREG(info.st_mode):
        try:
            size = shred_file(
                path, passes, open=open, write=write, rename=rename, unlink=unlink,
                lstat=lstat, lexists=lexists, fsync=fsync, urandom=urandom,
            )
        except ShredError as exc:
            failed(path, str(exc))
        else:
            entries.append({"path": path, "status": "shredded", "bytes": size, "error": None})
        return _summary(entries), entries
    if not stat_mod.S_ISDIR(info.st_mode):
        failed(path, "Not a regular file or folder; sockets, FIFOs and device nodes are refused.")
        return _summary(entries), entries

    directories = []
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with scandir(current) as iterator:
                listing = list(iterator)
        except OSError as exc:
            # A folder whose contents cannot be inspected is left in place:
            # shred refuses to remove what it cannot verify. Its parent's
            # removal then fails honestly with ENOTEMPTY.
            failed(current, "The folder cannot be read: {0}".format(exc))
            continue
        directories.append(current)
        for child in listing:
            try:
                mode = child.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                failed(child.path, "The item cannot be read: {0}".format(exc))
                continue
            if stat_mod.S_ISDIR(mode):
                stack.append(child.path)
                continue
            if stat_mod.S_ISLNK(mode):
                try:
                    unlink(child.path)
                except OSError as exc:
                    failed(child.path, "The symlink could not be removed: {0}".format(exc))
                else:
                    entries.append({"path": child.path, "status": "unlinked", "bytes": 0, "error": None})
                continue
            if stat_mod.S_ISREG(mode):
                try:
                    size = shred_file(
                        child.path, passes, open=open, write=write, rename=rename,
                        unlink=unlink, lstat=lstat, lexists=lexists, fsync=fsync,
                        urandom=urandom,
                    )
                except ShredError as exc:
                    failed(child.path, str(exc))
                else:
                    entries.append({"path": child.path, "status": "shredded", "bytes": size, "error": None})
                continue
            failed(
                child.path,
                "Not a regular file; sockets, FIFOs and device nodes are refused and were left in place.",
            )
    for directory in reversed(directories):
        try:
            rmdir(directory)
        except OSError as exc:
            failed(directory, "The folder could not be removed: {0}".format(exc))
        else:
            entries.append({"path": directory, "status": "removed", "bytes": 0, "error": None})
    return _summary(entries), entries


def _summary(entries):
    """Only verified destruction counts: overwritten files and removed folders."""
    return {
        "bytes": sum(entry["bytes"] for entry in entries if entry["status"] == "shredded"),
        "files": sum(1 for entry in entries if entry["status"] == "shredded"),
        "folders": sum(1 for entry in entries if entry["status"] == "removed"),
        "entries": len(entries),
        "errors": sum(1 for entry in entries if entry["status"] == "failed"),
    }
