"""The cleaned-items ledger and learned pre-selection (CLN-26).

Every clean result the user confirmed is recorded here, keyed by catalog
entry id: only rows whose status is ``trashed``, ``deleted`` or ``shredded``
and that carry bytes actually freed. Repeated cleans of the same entry build
a pattern, and :func:`suggest` turns patterns into soft pre-selection advice
for the next scan. The advice only ever *ticks a box* — the plan → confirm →
clean flow (CLN-13) still lists, confirms and runs every row — and cleaning
never depends on this store: a ledger that cannot be read degrades to "no
suggestions", never to a blocked clean.

The store is one JSON file (``ledger.json``) in the private state folder,
held to the same discipline as :mod:`cleanup_lab.settings`: a ``0700`` folder
that may not be a symlink, a ``0600`` file that may not be a symlink, and an
atomic write (temporary file, fsync, ``os.replace``) so a reader never sees a
half-written ledger. Runs are capped at :data:`MAX_RUNS`; the oldest run is
evicted as a new one arrives.

A file that cannot be read, parsed or trusted is *moved aside* to
``ledger.corrupt-<epoch>.json`` — never overwritten and never deleted, so
lifetime totals cannot vanish silently — and the module starts empty,
reporting the problem through its ``(value, problem)`` returns. A symlinked
store, or one with loose permissions, is refused outright: the store is never
written through or over a link, and a link is never moved aside to hide it.
"""
from __future__ import annotations

import json
import os
import stat
import time

from .paths import state_dir

#: Where the ledger lives inside the private state folder.
LEDGER_NAME = "ledger.json"
#: The store shape version; a different version is a wrong-shaped store.
STORE_VERSION = 1
#: The hard cap on stored runs; the oldest run is evicted on insert.
MAX_RUNS = 1000
#: The clean-result statuses that count as "the user really cleaned this".
RECORDED_STATUSES = ("trashed", "deleted", "shredded")
#: Rule 5: these risk classes are never suggested, however often they were cleaned.
EXCLUDED_RISKS = ("high", "credentials", "privacy")
#: The exact keys of one stored run; anything else is a wrong-shaped store.
_RUN_KEYS = {"at", "entryId", "path", "bytes"}


class LedgerError(RuntimeError):
    """The ledger store cannot be touched at all (a symlinked or loose store)."""


def _problem(message):
    """The typed problem payload for an untrustworthy store, or ``None``."""
    if message is None:
        return None
    return {"code": "ledger-corrupt", "message": message}


def _folder_problem(folder):
    """Why the private state folder cannot be trusted, or ``None`` when absent."""
    if not os.path.isdir(folder):
        return None  # no folder yet: reads see an empty store, writes create it 0700
    if os.path.islink(folder):
        return "The cleanup state folder must not be a symlink."
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        return "The cleanup state folder must be private (mode 0700)."
    return None


def _check_shape(body):
    """A problem message when the parsed body is not the typed store shape."""
    if (
        not isinstance(body, dict)
        or body.get("version") != STORE_VERSION
        or not isinstance(body.get("runs"), list)
    ):
        return "The ledger file holds an unknown shape."
    for run in body["runs"]:
        if not isinstance(run, dict) or set(run) != _RUN_KEYS:
            return "The ledger file holds an invalid run."
        if isinstance(run["at"], bool) or not isinstance(run["at"], (int, float)):
            return "The ledger file holds an invalid run."
        if not isinstance(run["entryId"], str) or not run["entryId"]:
            return "The ledger file holds an invalid run."
        if not isinstance(run["path"], str) or not run["path"]:
            return "The ledger file holds an invalid run."
        bytes_value = run["bytes"]
        if isinstance(bytes_value, bool) or not isinstance(bytes_value, int) or bytes_value < 0:
            return "The ledger file holds an invalid run."
    return None


def _aside_names(folder, stamp):
    """Candidate ``ledger.corrupt-<epoch>.json`` names; the first free one wins."""
    yield os.path.join(folder, "ledger.corrupt-{0}.json".format(stamp))
    for index in range(2, 100):
        yield os.path.join(folder, "ledger.corrupt-{0}-{1}.json".format(stamp, index))


def _recover(path, message, clock):
    """Move an untrustworthy ledger aside and start empty; ``(runs, problem, refused)``.

    The aside name is never overwritten: the first free
    ``ledger.corrupt-<epoch>`` name wins, and the move is a hard link plus
    unlink where the filesystem offers one, so an existing aside cannot be
    replaced by accident. When even the move fails, the corrupt file stays
    where it is and the store refuses writes rather than risk clobbering it.
    """
    stamp = int((clock or time.time)())
    folder = os.path.dirname(path)
    aside = None
    linked = False
    for candidate in _aside_names(folder, stamp):
        try:
            os.link(path, candidate)
        except FileExistsError:
            continue
        except OSError:
            break  # no hard links on this filesystem; fall back to a checked rename
        aside, linked = candidate, True
        break
    if aside is None:
        for candidate in _aside_names(folder, stamp):
            if os.path.lexists(candidate):
                continue
            try:
                os.rename(path, candidate)
            except OSError:
                break
            aside = candidate
            break
    if aside is None:
        refused = "{0} It could not be moved aside, so the store refuses writes until the file is resolved.".format(message)
        return [], refused, True
    if linked:
        try:
            os.unlink(path)
        except OSError as exc:
            refused = (
                "{0} A copy was preserved at {1} but the original could not be removed ({2}); "
                "the store refuses writes until it is resolved.".format(message, os.path.basename(aside), exc)
            )
            return [], refused, True
    moved = "{0} It was moved aside to {1}; the store starts empty.".format(message, os.path.basename(aside))
    return [], moved, False


def _load(path, *, clock=None):
    """``(runs, problem, refused)`` read from the store file.

    A missing file is an empty store. A symlinked or loose-permission file is
    refused in place (``refused`` — never read, never moved, never written
    through). A file that cannot be read or parsed, or that holds a wrong
    shape, is moved aside (data preserved) and the store starts empty.
    """
    if os.path.islink(path):
        return [], "The ledger file must not be a symlink.", True
    if not os.path.exists(path):
        return [], None, False
    try:
        if os.name != "nt" and stat.S_IMODE(os.stat(path).st_mode) & 0o077:
            return [], "The ledger file must be private (mode 0600).", True
        with open(path, "r", encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, ValueError) as exc:
        return _recover(path, "The ledger file cannot be read: {0}.".format(exc), clock)
    problem = _check_shape(body)
    if problem is not None:
        return _recover(path, problem, clock)
    return list(body["runs"]), None, False


def _runs(env, platform):
    """``(runs, problem)`` read from the store; reads never create anything."""
    folder = state_dir(env, platform)
    problem = _folder_problem(folder)
    if problem is not None:
        return [], problem
    runs, problem, _ = _load(os.path.join(folder, LEDGER_NAME))
    return runs, problem


def _write(runs, env, platform):
    """Atomically persist the run list (temp file, fsync, ``os.replace``)."""
    folder = state_dir(env, platform)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    if not os.path.isdir(folder) or os.path.islink(folder):
        raise LedgerError("The cleanup state folder is missing or is a symlink.")
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        raise LedgerError("The cleanup state folder must be private (mode 0700).")
    path = os.path.join(folder, LEDGER_NAME)
    if os.path.islink(path):
        raise LedgerError("The ledger file must not be a symlink.")
    body = json.dumps({"version": STORE_VERSION, "runs": runs}, sort_keys=True, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    tmp = path + ".tmp"
    try:
        fd = os.open(tmp, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.unlink(tmp)  # never leave a .tmp behind
        except OSError:
            pass
        raise LedgerError("The ledger file cannot be written: {0}".format(exc)) from exc
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
    return runs


def _row(row, clock):
    """One ledger entry from a clean-plan result row, or ``None`` when it does not qualify."""
    if not isinstance(row, dict):
        return None
    if row.get("status") not in RECORDED_STATUSES:
        return None
    bytes_value = row.get("bytes")
    if isinstance(bytes_value, bool) or not isinstance(bytes_value, int) or bytes_value <= 0:
        return None
    entry_id = row.get("entryId")
    path = row.get("path")
    if not isinstance(entry_id, str) or not entry_id or not isinstance(path, str) or not path:
        return None
    return {"at": clock(), "entryId": entry_id, "path": path, "bytes": bytes_value}


def _check_min_runs(min_runs):
    if isinstance(min_runs, bool) or not isinstance(min_runs, int) or min_runs < 1:
        raise ValueError("min_runs must be a whole number of at least 1.")


def _record(rows, env, platform, clock):
    folder = state_dir(env, platform)
    path = os.path.join(folder, LEDGER_NAME)
    problem = _folder_problem(folder)
    refused = problem is not None
    runs = []
    if problem is None:
        runs, problem, refused = _load(path, clock=clock)
    if refused:
        return 0, _problem(problem)
    recorded = []
    for row in rows:
        entry = _row(row, clock)
        if entry is not None:
            recorded.append(entry)
    runs.extend(recorded)
    runs.sort(key=lambda run: run["at"])  # the oldest run really is the oldest
    del runs[:-MAX_RUNS]
    _write(runs, env, platform)
    return len(recorded), _problem(problem)


def record(rows, *, env=None, platform=None, clock=time.time):
    """Record qualifying clean-plan result rows; ``(count, problem)``.

    Only rows whose status is ``trashed``, ``deleted`` or ``shredded`` and
    that carry a positive byte count are recorded; skipped, failed and
    zero-byte rows are ignored. Each recorded run is
    ``{"at": clock(), "entryId", "path", "bytes"}``. A store that cannot be
    trusted is recovered (corrupt data moved aside and reported) or refused
    (symlink, loose permissions) with a count of 0; a store that cannot be
    written reports the failure the same way, because a finished clean is
    never failed by its ledger. ``rows`` must be a list or tuple.
    """
    if not isinstance(rows, (list, tuple)):
        raise ValueError("rows must be a list of clean-plan result rows.")
    try:
        return _record(rows, env, platform, clock)
    except LedgerError as exc:
        return 0, _problem(str(exc))


def learned(*, env=None, platform=None, min_runs=2):
    """``(patterns, problem)`` — runs aggregated by entry id, bytes descending.

    Each pattern is ``{"entryId", "runs", "bytes"}`` for an entry id cleaned
    at least ``min_runs`` times; ties on bytes are broken alphabetically. A
    store that cannot be trusted is recovered or refused exactly like
    :func:`record` and reported here; an empty or missing store is simply no
    patterns and no problem.
    """
    _check_min_runs(min_runs)
    runs, problem = _runs(env, platform)
    totals = {}
    for run in runs:
        pattern = totals.setdefault(run["entryId"], {"entryId": run["entryId"], "runs": 0, "bytes": 0})
        pattern["runs"] += 1
        pattern["bytes"] += run["bytes"]
    patterns = [pattern for pattern in totals.values() if pattern["runs"] >= min_runs]
    patterns.sort(key=lambda pattern: (-pattern["bytes"], pattern["entryId"]))
    return patterns, _problem(problem)


def suggest(entries, *, env=None, platform=None, min_runs=2):
    """``(suggestions, problem)`` — soft pre-selection advice for catalog entries.

    ``entries`` are catalog entry dicts (``id``, ``risk``, ...). An entry
    whose id was learned gets ``{"entryId", "reason"}``, where the reason
    names how often it was cleaned and how much that reclaimed. Entries with
    the ``high``, ``credentials`` or ``privacy`` risk classes are never
    suggested (rule 5). A suggestion is only ever a ticked box for the caller
    to show: the plan flow still lists, confirms and runs every row.
    """
    if not isinstance(entries, (list, tuple)):
        raise ValueError("entries must be a list of catalog entry objects.")
    _check_min_runs(min_runs)
    patterns, problem = learned(env=env, platform=platform, min_runs=min_runs)
    if problem is not None:
        return [], problem
    by_id = {pattern["entryId"]: pattern for pattern in patterns}
    suggestions = []
    for entry_value in entries:
        if not isinstance(entry_value, dict):
            raise ValueError("entries must be a list of catalog entry objects.")
        risk = entry_value.get("risk")
        if isinstance(risk, str) and risk.lower() in EXCLUDED_RISKS:
            continue
        pattern = by_id.get(entry_value.get("id"))
        if pattern is None:
            continue
        suggestions.append({
            "entryId": pattern["entryId"],
            "reason": "You have cleaned this {0} ({1} total)".format(
                _cleaned_phrase(pattern["runs"]), _format_bytes(pattern["bytes"])
            ),
        })
    return suggestions, None


def clear(*, env=None, platform=None):
    """Empty the store; ``True`` when a store file existed.

    The file is reset to the empty store atomically. A corrupt file is moved
    aside first (its data preserved), so clearing never destroys it. A
    symlinked store, a loose-permission file or an unwritable folder raises
    :class:`LedgerError` — clearing never writes through or over a link.
    """
    folder = state_dir(env, platform)
    problem = _folder_problem(folder)
    if problem is not None:
        raise LedgerError(problem)
    path = os.path.join(folder, LEDGER_NAME)
    if not os.path.lexists(path):
        return False
    _, problem, refused = _load(path)
    if refused:
        raise LedgerError(problem)
    _write([], env, platform)
    return True


def stats(*, env=None, platform=None):
    """``({"runs", "entries", "bytes"}, problem)`` for the settings page."""
    runs, problem = _runs(env, platform)
    return {
        "runs": len(runs),
        "entries": len({run["entryId"] for run in runs}),
        "bytes": sum(run["bytes"] for run in runs),
    }, _problem(problem)


def _cleaned_phrase(count):
    """``"2 times"`` (or ``"1 time"``) for the suggestion reason."""
    if count == 1:
        return "1 time"
    return "{0} times".format(count)


def _format_bytes(value):
    """A short human-readable byte count for the suggestion reason."""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return "{0:.0f} {1}".format(size, unit) if unit == "B" else "{0:.1f} {1}".format(size, unit)
        size /= 1024
    return "{0:.1f} PB".format(size)
