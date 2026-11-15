"""The content-hash duplicate finder (CLN-30): report-only, honest, cancellable.

Finds files with byte-identical content across one or more roots and reports
them as groups with a *keeper* — the one file to keep. This slice only finds
and reports; nothing is deleted, moved or written here. The integrator wires
the removal into the Trash-only plan flow later; :func:`select_for_removal`
provides the keeper vocabulary that flow will use.

The pipeline, in order:

1. **Walk.** Every root is walked with an iterative stack and ``lstat``.
   Symlinks are reported as skipped and never followed (safety rule 1), so a
   link loop cannot recurse by construction. Sockets, FIFOs and device nodes
   are skipped (``not-regular``); an unstatable path or an unlistable
   directory is skipped (``unreadable``) and never fails the run.
2. **Hard-link filter.** A file whose ``(device, inode)`` was already seen is
   skipped (``hard-link-duplicate``): two links to one file are one file.
   Filesystems without inode numbers (``st_ino == 0``) cannot be de-duplicated
   this way, so there every file counts.
3. **Size filter and grouping.** Files below ``min_size`` are skipped
   (``below-min-size``) — empty files would all be "duplicates" of each other.
   The rest group by size; only groups with more than one file can hold
   duplicates.
4. **Prehash.** Each surviving group is dissolved cheaply: a sha256
   fingerprint over the first and last ``prehash_bytes`` of the file (files no
   longer than both windows together: the whole content, read once). The
   prehash never invokes the injectable ``hasher``.
5. **Full hash.** Sub-groups that survive prehashing are read whole and hashed
   with ``hasher`` (default sha256) — the only stage that calls it — and the
   files group by digest. A digest group with a single file is dropped.

Honesty: every file is re-stat'ed right before it is hashed, and a size or
``mtime_ns`` drift against the walk stat skips it (``changed-during-scan``)
instead of hashing a moving target; a read that returns other bytes than the
walk stat promised is skipped the same way. An open or read failure is an
``unreadable`` skip. Nothing is guessed.

Cancellation: ``cancel`` is ``None`` or a callable (an object with ``is_set``,
like a :class:`threading.Event`, works too). It is polled between files; a
cancelled run returns promptly with ``"cancelled": true`` and its partial
result — only digest groups fully verified before the cancel are reported,
because an unverified group would be an invented one.

Progress: ``progress(payload)`` receives ``{"phase": "walking" | "prehash" |
"hashing", "filesDone", "filesTotal", "currentPath"}`` — once per directory
while walking (``filesTotal`` is 0 there: still unknown), once per file while
prehashing and hashing (while hashing, ``filesTotal`` counts the files queued
so far, because prehash outcomes arrive as the run proceeds). Throttling is
the caller's job.

``lstat``, ``open_func`` and ``hasher`` are injectable for tests. Everything
runs on caller-provided roots; the tests use generated temp trees and never a
real user folder (rule 8). The result is plain dicts, JSON-ready for a
console job.
"""
from __future__ import annotations

import hashlib
import os
import stat as stat_mod

#: The keeper vocabulary: which file of a group survives and which are
#: candidates for removal. :func:`select_for_removal` refuses anything else.
KEEPER_METHODS = ("newest", "oldest", "biggest", "smallest", "first-path")

#: Default floor for candidate files (an empty file is never a duplicate worth
#: reporting); files below it are skipped as ``below-min-size``.
DEFAULT_MIN_SIZE = 1

#: Default prehash window: the bytes read from each end of a file before the
#: full hash is spent.
DEFAULT_PREHASH_BYTES = 4096

_CHUNK = 1 << 20  # 1 MiB reads for the full hash

# Skip reasons — stable codes, like the plan's verdict codes.
SYMLINK = "symlink"
NOT_REGULAR = "not-regular"
UNREADABLE = "unreadable"
HARD_LINK_DUPLICATE = "hard-link-duplicate"
BELOW_MIN_SIZE = "below-min-size"
CHANGED_DURING_SCAN = "changed-during-scan"


class _Drifted(Exception):
    """The file no longer matches its walk stat; it is skipped, never hashed."""


def _cancelled(cancel):
    """True when the caller asked to stop (a callable, or an Event-like)."""
    if cancel is None:
        return False
    checker = getattr(cancel, "is_set", None)
    if checker is not None:
        return bool(checker())
    if callable(cancel):
        return bool(cancel())
    return False


def reclaimable(group):
    """Bytes recovered by removing every file of the group but the keeper."""
    return group["sizeBytes"] * (len(group["files"]) - 1)


def select_for_removal(group, method="newest"):
    """The paths of one duplicate group to remove: every file but the keeper.

    ``method`` is one of :data:`KEEPER_METHODS`: the keeper is the file with
    the newest ``mtimeNs``, the oldest one, the biggest ``sizeBytes``, the
    smallest, or the lexicographically first path. Ties break to the
    lexicographically first path, so the choice is deterministic. The keeper
    is never included: a group with two or more files yields at least one
    path, and a one-file group (no duplicates) yields ``[]``. An unknown
    method is a ``ValueError`` — removal never guesses.
    """
    if method not in KEEPER_METHODS:
        raise ValueError(
            "The keeper method must be one of: {0}.".format(", ".join(KEEPER_METHODS))
        )
    files = sorted(group["files"], key=lambda item: item["path"])
    if len(files) < 2:
        return []
    if method == "newest":
        keeper = max(files, key=lambda item: item["mtimeNs"])
    elif method == "oldest":
        keeper = min(files, key=lambda item: item["mtimeNs"])
    elif method == "biggest":
        keeper = max(files, key=lambda item: item["sizeBytes"])
    elif method == "smallest":
        keeper = min(files, key=lambda item: item["sizeBytes"])
    else:  # first-path
        keeper = files[0]
    return [item["path"] for item in files if item is not keeper]


def _prehash_digest(path, size, window, open_func):
    """sha256 over the first and last ``window`` bytes; small files whole, once.

    Raises ``OSError`` when the file cannot be read and :class:`_Drifted` when
    the bytes read disagree with the walk stat.
    """
    digest = hashlib.sha256()
    with open_func(path, "rb") as handle:
        if size <= 2 * window:
            body = handle.read()
            if len(body) != size:
                raise _Drifted()
            digest.update(body)
        else:
            head = handle.read(window)
            if len(head) != window:
                raise _Drifted()
            handle.seek(size - window, os.SEEK_SET)
            tail = handle.read(window)
            if len(tail) != window:
                raise _Drifted()
            digest.update(head)
            digest.update(tail)
    return digest.hexdigest()


def _full_digest(path, size, open_func, hasher):
    """The whole-file digest; a read that disagrees with the walk size is drift."""
    digest = hasher()
    seen = 0
    with open_func(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            seen += len(chunk)
            if seen > size:
                raise _Drifted()  # grew past the promised size; stop reading
            digest.update(chunk)
    if seen != size:
        raise _Drifted()
    return digest.hexdigest()


def _recheck(path, size, mtime_ns, lstat):
    """``None`` when the file still matches its walk stat, else the skip reason."""
    try:
        fresh = lstat(path)
    except OSError:
        return UNREADABLE
    if fresh.st_size != size or fresh.st_mtime_ns != mtime_ns:
        return CHANGED_DURING_SCAN
    return None


def _group_record(digest, bucket):
    """One reported group; the keeper is the newest file (ties: first path)."""
    files = sorted(bucket, key=lambda item: item["path"])
    keeper = max(files, key=lambda item: item["mtimeNs"])["path"]
    return {
        "digest": digest,
        "sizeBytes": files[0]["sizeBytes"],
        "files": files,
        "keeper": keeper,
    }


def _result(groups, skipped, cancelled):
    return {
        "cancelled": cancelled,
        "groups": groups,
        "skipped": skipped,
        "totals": {
            "groups": len(groups),
            "duplicateFiles": sum(len(group["files"]) - 1 for group in groups),
            "reclaimableBytes": sum(reclaimable(group) for group in groups),
        },
    }


def find_duplicates(
    root_paths,
    *,
    min_size=DEFAULT_MIN_SIZE,
    prehash_bytes=DEFAULT_PREHASH_BYTES,
    cancel=None,
    progress=None,
    follow_symlinks=False,
    lstat=os.lstat,
    open_func=open,
    hasher=hashlib.sha256,
):
    """Find byte-identical files under ``root_paths`` and report them.

    Returns a JSON-ready dict::

        {"cancelled": bool,
         "groups": [{"digest", "sizeBytes",
                     "files": [{"path", "sizeBytes", "dev", "ino", "mtimeNs"}, ...],
                     "keeper": <the newest file's path>}, ...],
         "skipped": [{"path", "reason"}, ...],
         "totals": {"groups", "duplicateFiles", "reclaimableBytes"}}

    Groups are sorted largest-first (then by digest); a group's files are
    sorted by path and its keeper is the newest ``mtimeNs`` (ties break to the
    first path) — the same file :func:`select_for_removal` keeps for
    ``method="newest"``. ``reclaimableBytes`` is what removing every file but
    its keeper would free (:func:`reclaimable` per group). Skips are in scan
    order with a stable ``reason`` (see the module docstring); a missing or
    unlistable root is a skip, never an error. A bare string is accepted as a
    one-root list.

    ``follow_symlinks=True`` is refused with ``ValueError``: symlinks are
    reported and never followed, so a link loop cannot recurse.
    """
    if follow_symlinks:
        raise ValueError(
            "Symlinks are never followed (safety rule 1); follow_symlinks must stay False."
        )
    if isinstance(root_paths, (str, bytes)):
        roots = [root_paths]
    else:
        roots = list(root_paths)
    min_size = max(0, int(min_size))
    window = max(0, int(prehash_bytes))

    skipped = []
    candidates = []
    seen_inodes = set()
    cancelled = False

    def emit(phase, files_done, files_total, current):
        if progress is not None:
            progress({
                "phase": phase,
                "filesDone": files_done,
                "filesTotal": files_total,
                "currentPath": current,
            })

    def consider(path, info):
        """Hard-link filter, size filter and the candidate record."""
        if info.st_ino != 0:
            key = (info.st_dev, info.st_ino)
            if key in seen_inodes:
                skipped.append({"path": path, "reason": HARD_LINK_DUPLICATE})
                return
            seen_inodes.add(key)
        if info.st_size < min_size:
            skipped.append({"path": path, "reason": BELOW_MIN_SIZE})
            return
        candidates.append({
            "path": path,
            "sizeBytes": info.st_size,
            "dev": info.st_dev,
            "ino": info.st_ino,
            "mtimeNs": info.st_mtime_ns,
        })

    # ── walk: iterative stack, links and special nodes never touched ─────────
    stack = []
    for root in roots:
        if _cancelled(cancel):
            cancelled = True
            break
        try:
            info = lstat(root)
        except OSError:
            skipped.append({"path": root, "reason": UNREADABLE})
            continue
        mode = info.st_mode
        if stat_mod.S_ISLNK(mode):
            skipped.append({"path": root, "reason": SYMLINK})
        elif stat_mod.S_ISDIR(mode):
            stack.append(root)
        elif stat_mod.S_ISREG(mode):
            consider(root, info)
        else:
            skipped.append({"path": root, "reason": NOT_REGULAR})

    while stack:
        if _cancelled(cancel):
            cancelled = True
            break
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                names = sorted(entry.name for entry in iterator)
        except OSError:
            skipped.append({"path": directory, "reason": UNREADABLE})
            continue
        child_dirs = []
        for name in names:
            if _cancelled(cancel):
                cancelled = True
                break
            path = os.path.join(directory, name)
            try:
                info = lstat(path)
            except OSError:
                skipped.append({"path": path, "reason": UNREADABLE})
                continue
            mode = info.st_mode
            if stat_mod.S_ISLNK(mode):
                skipped.append({"path": path, "reason": SYMLINK})
            elif stat_mod.S_ISDIR(mode):
                child_dirs.append(path)
            elif stat_mod.S_ISREG(mode):
                consider(path, info)
            else:
                skipped.append({"path": path, "reason": NOT_REGULAR})
        if not cancelled:
            emit("walking", len(candidates), 0, directory)
            stack.extend(reversed(child_dirs))

    if cancelled:
        # Nothing is verified yet: an unhashed "group" would be an invented one.
        return _result([], skipped, True)

    # ── size grouping ────────────────────────────────────────────────────────
    by_size = {}
    for candidate in candidates:
        by_size.setdefault(candidate["sizeBytes"], []).append(candidate)
    size_groups = []
    for size in sorted(by_size, reverse=True):
        members = sorted(by_size[size], key=lambda item: item["path"])
        if len(members) > 1:
            size_groups.append(members)

    total_prehash = sum(len(members) for members in size_groups)
    pre_done = 0
    hash_queued = 0
    hash_done = 0
    groups = []

    for members in size_groups:
        if _cancelled(cancel):
            cancelled = True
            break
        size = members[0]["sizeBytes"]
        # ── prehash: the cheap fingerprint dissolves most false groups ───────
        buckets = {}
        for candidate in members:
            if _cancelled(cancel):
                cancelled = True
                break
            reason = _recheck(
                candidate["path"], candidate["sizeBytes"], candidate["mtimeNs"], lstat
            )
            fingerprint = None
            if reason is None:
                try:
                    fingerprint = _prehash_digest(candidate["path"], size, window, open_func)
                except OSError:
                    reason = UNREADABLE
                except _Drifted:
                    reason = CHANGED_DURING_SCAN
            if reason is not None:
                skipped.append({"path": candidate["path"], "reason": reason})
            else:
                buckets.setdefault(fingerprint, []).append(candidate)
            pre_done += 1
            emit("prehash", pre_done, total_prehash, candidate["path"])
        if cancelled:
            break
        # ── full hash: only the survivors are read whole ─────────────────────
        for fingerprint in sorted(buckets):
            survivors = buckets[fingerprint]
            if len(survivors) < 2:
                continue
            hash_queued += len(survivors)
            digests = {}
            for candidate in survivors:
                if _cancelled(cancel):
                    cancelled = True
                    break
                reason = _recheck(
                    candidate["path"], candidate["sizeBytes"], candidate["mtimeNs"], lstat
                )
                digest = None
                if reason is None:
                    try:
                        digest = _full_digest(
                            candidate["path"], candidate["sizeBytes"], open_func, hasher
                        )
                    except OSError:
                        reason = UNREADABLE
                    except _Drifted:
                        reason = CHANGED_DURING_SCAN
                if reason is not None:
                    skipped.append({"path": candidate["path"], "reason": reason})
                else:
                    digests.setdefault(digest, []).append(candidate)
                hash_done += 1
                emit("hashing", hash_done, hash_queued, candidate["path"])
            if cancelled:
                break
            for digest in sorted(digests):
                bucket = digests[digest]
                if len(bucket) > 1:
                    groups.append(_group_record(digest, bucket))
        if cancelled:
            break

    return _result(groups, skipped, cancelled)
