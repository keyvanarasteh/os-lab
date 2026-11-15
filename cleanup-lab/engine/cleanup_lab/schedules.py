"""Scan schedules: a cron-validating store in private state (CLN-18).

The user's dry-run scan schedules are typed records in the private state
folder, held to the same discipline as :mod:`cleanup_lab.settings` and
:mod:`cleanup_lab.ignore`: a ``0700`` folder that may not be a symlink, a
``0600`` file that may not be a symlink, and an atomic write (temporary file,
``fsync``, ``os.replace``, directory fsync) so a reader never sees a
half-written store. One record:

    {"id": <hex12>, "cron": <expression>, "enabled": <bool>,
     "createdAt": <float>, "lastRunAt": <float | None>}

The store fails closed: a file that cannot be read, parsed or trusted makes
:func:`list_schedules` report ``{"code": "schedules-corrupt", "message": ...}``
and every mutator raise :class:`SchedulesError` — schedules that cannot be
seen are never silently dropped, and nothing is written on top of a store
that cannot be trusted. The runner that polls :func:`due` and starts the
scan jobs is the console's part; this module is the pure store plus the cron
evaluation it needs.

Cron dialect (integers only — no month/day names, no ``@`` shortcuts): five
whitespace-separated fields, minute (0-59), hour (0-23), day of month (1-31),
month (1-12) and day of week (0-7, where 7 is also Sunday), each supporting
``*``, single values, ranges ``a-b``, lists ``a,b,c`` and steps ``*/n`` and
``a-b/n``. A step needs ``*`` or a range behind it; a range runs low to high.
When both day-of-month and day-of-week are restricted, a day matches when
*either* does — the semantics every classic cron implements.

Evaluation uses naive local wall-clock minutes (plain ``datetime``, no
timezone gymnastics): :func:`next_run` returns the first fire strictly after
the base timestamp, iterating candidate minutes within the ``limit_hours``
window, and :func:`due` reports whether a record's next fire (from
``lastRunAt``, or ``createdAt`` before the first run) has arrived. A schedule
whose next fire lies beyond the window is not reported due until its base
moves — the runner marks every run with :func:`mark_run`, so the window
always starts at the last run.
"""
from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from datetime import datetime, timedelta

from .paths import state_dir

#: Where the schedules store lives inside the private state folder.
STORE_NAME = "schedules.json"
#: The store format version.
VERSION = 1
#: The exact keys of one stored record.
RECORD_KEYS = ("id", "cron", "enabled", "createdAt", "lastRunAt")
#: The five cron fields with their inclusive bounds, in order.
FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 7),
)
#: A cron value is a plain run of ASCII digits — no names, signs or decimals.
_INTEGER_RE = re.compile(r"^[0-9]+$")


class SchedulesError(RuntimeError):
    """The schedules store cannot be trusted; readers report it, writers refuse it."""


# ── the cron dialect ─────────────────────────────────────────────────────────


def _to_int(text, name, element):
    """One field value as an integer; anything else is refused with the field named."""
    if not _INTEGER_RE.match(text):
        raise ValueError(
            "The {0} field has a value that is not an integer: {1}.".format(name, element)
        )
    return int(text)


def _parse_field(name, low, high, token):
    """The set of values one field allows; ``ValueError`` says exactly what is wrong.

    ``*`` is the full range, ``a-b`` a range (low to high, inside the bounds),
    ``n`` a single value, and ``/n`` a step over ``*`` or a range — a step on a
    bare value is refused, and a comma list may mix any of these.
    """
    values = set()
    for element in token.split(","):
        if not element:
            raise ValueError("The {0} field has an empty list element.".format(name))
        body = element
        step = 1
        if "/" in element:
            body, _, step_text = element.partition("/")
            if not _INTEGER_RE.match(step_text) or int(step_text) < 1:
                raise ValueError(
                    "The {0} field step must be a whole number of at least 1: {1}.".format(
                        name, element
                    )
                )
            step = int(step_text)
            if body != "*" and "-" not in body:
                raise ValueError(
                    "The {0} field does not allow a step on a single value: {1}.".format(
                        name, element
                    )
                )
        if body == "*":
            first, last = low, high
        elif "-" in body:
            left, _, right = body.partition("-")
            first = _to_int(left, name, element)
            last = _to_int(right, name, element)
            if first < low or last > high:
                raise ValueError(
                    "The {0} field has a value out of range {1}-{2}: {3}.".format(
                        name, low, high, element
                    )
                )
            if first > last:
                raise ValueError(
                    "The {0} field range must go from low to high: {1}.".format(name, element)
                )
        else:
            first = last = _to_int(body, name, element)
            if first < low or last > high:
                raise ValueError(
                    "The {0} field has a value out of range {1}-{2}: {3}.".format(
                        name, low, high, element
                    )
                )
        values.update(range(first, last + 1, step))
    return values


def validate_cron(expr):
    """The normalized expression (whitespace collapsed), or ``ValueError``.

    Exactly five fields — minute 0-59, hour 0-23, day of month 1-31, month
    1-12, day of week 0-7 (7 is Sunday too) — each an integer-only ``*``,
    value, range, list or step as documented in the module docstring.
    """
    if not isinstance(expr, str):
        raise ValueError("The cron expression must be a string.")
    tokens = expr.split()
    if len(tokens) != len(FIELDS):
        raise ValueError(
            "A cron expression must have 5 fields (minute hour day-of-month month "
            "day-of-week); got {0}.".format(len(tokens))
        )
    for (name, low, high), token in zip(FIELDS, tokens):
        _parse_field(name, low, high, token)
    return " ".join(tokens)


def _parse_fields(expr):
    """The validated expression as candidate sets plus the dom/dow wild flags."""
    tokens = expr.split()
    minute, hour, dom, month, dow = (
        _parse_field(name, low, high, token)
        for (name, low, high), token in zip(FIELDS, tokens)
    )
    return {
        "minutes": tuple(sorted(minute)),
        "hours": tuple(sorted(hour)),
        "doms": dom,
        "months": month,
        "dows": {value % 7 for value in dow},  # 7 is Sunday, the same day as 0
        "dom_wild": tokens[2] == "*",
        "dow_wild": tokens[4] == "*",
    }


def _day_matches(day, parsed):
    """Vixie day semantics: a restricted day-of-month and day-of-week match on either."""
    if parsed["dom_wild"] and parsed["dow_wild"]:
        return True
    dom_hit = day.day in parsed["doms"]
    dow_hit = (day.weekday() + 1) % 7 in parsed["dows"]  # Monday=0 cron: Sunday=0
    if parsed["dom_wild"]:
        return dow_hit
    if parsed["dow_wild"]:
        return dom_hit
    return dom_hit or dow_hit


def next_run(expr, after_ts, *, limit_hours=48):
    """The next fire time strictly after ``after_ts``, or ``None`` within ``limit_hours``.

    Fire times are naive local wall-clock minutes: the expression is matched
    against local ``datetime`` values and converted with ``timestamp()``, so a
    schedule fires at the wall time it names. A fire exactly at ``after_ts``
    does not count (strictly after). The scan iterates candidate minutes —
    only the expression's own hours and minutes on matching days inside the
    window — so an expression that never fires (or fires only beyond the
    window) returns ``None`` quickly.
    """
    parsed = _parse_fields(validate_cron(expr))
    start = datetime.fromtimestamp(after_ts).replace(second=0, microsecond=0)
    start += timedelta(minutes=1)  # a fire at the base minute itself is not strictly after
    limit_ts = after_ts + limit_hours * 3600.0
    day = start.date()
    last_day = datetime.fromtimestamp(limit_ts).date()
    while day <= last_day:
        if day.month in parsed["months"] and _day_matches(day, parsed):
            for hour in parsed["hours"]:
                for minute in parsed["minutes"]:
                    candidate = datetime(day.year, day.month, day.day, hour, minute)
                    if candidate < start:
                        continue
                    fire = candidate.timestamp()
                    if fire <= limit_ts:
                        return fire
                    return None  # every later candidate on this and later days is later still
        day += timedelta(days=1)
    return None


def due(schedule, now):
    """Whether ``schedule`` should fire now: enabled, and its next fire has arrived.

    The base is ``lastRunAt`` once a run has been marked, ``createdAt`` before
    that. A record that cannot be evaluated — disabled, no base, an unparsable
    cron — is not due: fail closed, never fire on a guess.
    """
    if not isinstance(schedule, dict) or schedule.get("enabled") is not True:
        return False
    cron = schedule.get("cron")
    base = schedule.get("lastRunAt")
    if base is None:
        base = schedule.get("createdAt")
    if not isinstance(cron, str) or isinstance(base, bool) or not isinstance(base, (int, float)):
        return False
    try:
        fire = next_run(cron, float(base))
    except ValueError:
        return False
    return fire is not None and fire <= now


# ── the store ────────────────────────────────────────────────────────────────


def _store_path(env, platform):
    """The schedules file path; the folder is not created by reads."""
    return os.path.join(state_dir(env, platform), STORE_NAME)


def _validate_stored(record):
    """A stored record must be the exact typed shape with a parsable cron."""
    if not isinstance(record, dict):
        raise ValueError("A schedule must be an object.")
    if set(record) - set(RECORD_KEYS):
        raise ValueError("A schedule holds unknown keys.")
    if not isinstance(record.get("id"), str) or not record["id"]:
        raise ValueError("A schedule needs an id.")
    cron = record.get("cron")
    if not isinstance(cron, str) or not cron:
        raise ValueError("A schedule needs a cron expression.")
    try:
        validate_cron(cron)
    except ValueError as exc:
        raise ValueError("A schedule holds an invalid cron: {0}".format(exc)) from exc
    if not isinstance(record.get("enabled"), bool):
        raise ValueError("A schedule's enabled flag must be true or false.")
    for key in ("createdAt", "lastRunAt"):
        value = record.get(key)
        if value is None and key == "lastRunAt":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("A schedule's {0} must be a number.".format(key))


def _read_store(path):
    """Parse the store file with settings-store discipline; corrupt raises ``SchedulesError``."""
    if os.path.islink(path):
        raise SchedulesError("The schedules file must not be a symlink.")
    if not os.path.exists(path):
        return {"version": VERSION, "schedules": []}
    try:
        if os.name != "nt" and stat.S_IMODE(os.stat(path).st_mode) & 0o077:
            raise SchedulesError("The schedules file must be private (mode 0600).")
        with open(path, "r", encoding="utf-8") as handle:
            body = json.load(handle)
    except SchedulesError:
        raise
    except (OSError, ValueError) as exc:
        raise SchedulesError("The schedules file cannot be read: {0}".format(exc)) from exc
    if (
        not isinstance(body, dict)
        or body.get("version") != VERSION
        or not isinstance(body.get("schedules"), list)
    ):
        raise SchedulesError("The schedules file holds an unknown shape.")
    for record in body["schedules"]:
        try:
            _validate_stored(record)
        except ValueError as exc:
            raise SchedulesError(
                "The schedules file holds an invalid schedule: {0}".format(exc)
            ) from exc
    return body


def list_schedules(env=None, platform=None):
    """``(schedules, problem)`` — never raises.

    ``schedules`` is the stored list, empty when nothing was configured.
    ``problem`` is ``None`` or ``{"code": "schedules-corrupt", "message": ...}``;
    the runner refuses to act against a store it cannot read.
    """
    path = _store_path(env, platform)
    if not os.path.isdir(os.path.dirname(path)):
        return [], None
    try:
        body = _read_store(path)
    except SchedulesError as exc:
        return [], {"code": "schedules-corrupt", "message": str(exc)}
    return list(body["schedules"]), None


def _write_store(records, env, platform):
    """Atomically persist the schedule list (temp file, fsync, ``os.replace``)."""
    folder = state_dir(env, platform)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    if not os.path.isdir(folder) or os.path.islink(folder):
        raise SchedulesError("The cleanup state folder is missing or is a symlink.")
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        raise SchedulesError("The cleanup state folder must be private (mode 0700).")
    path = os.path.join(folder, STORE_NAME)
    body = json.dumps({"version": VERSION, "schedules": records}, sort_keys=True, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path + ".tmp", flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise SchedulesError("The schedules file cannot be written: {0}".format(exc)) from exc
    try:
        os.replace(path + ".tmp", path)
    except OSError as exc:
        raise SchedulesError("The schedules file cannot be replaced: {0}".format(exc)) from exc
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
    return records


def _load_records(env, platform):
    """The stored records; a store that cannot be trusted raises ``SchedulesError``."""
    return list(_read_store(_store_path(env, platform))["schedules"])


def _update(schedule_id, change, env, platform):
    """Apply ``change`` to one stored record and persist it; ``ValueError`` when unknown."""
    records = _load_records(env, platform)
    for index, record in enumerate(records):
        if record["id"] == schedule_id:
            updated = dict(record)
            change(updated)
            records[index] = updated
            _write_store(records, env, platform)
            return updated
    raise ValueError("Unknown schedule: {0}".format(schedule_id))


def add(cron, *, enabled=True, env=None, platform=None, clock=time.time):
    """Add one schedule; returns it.

    The cron expression is validated (and whitespace-normalized) first, so a
    ``ValueError`` for a bad expression leaves the store untouched; an exact
    duplicate of an already-stored expression is refused the same way. The
    clock is injectable so tests can pin ``createdAt``.
    """
    normalized = validate_cron(cron)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false.")
    records = _load_records(env, platform)
    for record in records:
        if record["cron"] == normalized:
            raise ValueError("This schedule already exists.")
    record = {
        "id": uuid.uuid4().hex[:12],
        "cron": normalized,
        "enabled": enabled,
        "createdAt": float(clock()),
        "lastRunAt": None,
    }
    records.append(record)
    _write_store(records, env, platform)
    return record


def remove(schedule_id, *, env=None, platform=None):
    """Remove the schedule with this id; ``True`` when it existed."""
    if not isinstance(schedule_id, str) or not schedule_id:
        raise ValueError("A schedule id is required.")
    records = _load_records(env, platform)
    kept = [record for record in records if record["id"] != schedule_id]
    if len(kept) == len(records):
        return False
    _write_store(kept, env, platform)
    return True


def set_enabled(schedule_id, enabled, *, env=None, platform=None):
    """Enable or disable one schedule; returns the updated record."""
    if not isinstance(schedule_id, str) or not schedule_id:
        raise ValueError("A schedule id is required.")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false.")

    def change(record):
        record["enabled"] = enabled

    return _update(schedule_id, change, env, platform)


def mark_run(schedule_id, timestamp, *, env=None, platform=None):
    """Record that the schedule ran at ``timestamp``; returns the updated record."""
    if not isinstance(schedule_id, str) or not schedule_id:
        raise ValueError("A schedule id is required.")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValueError("The run timestamp must be a number.")

    def change(record):
        record["lastRunAt"] = float(timestamp)

    return _update(schedule_id, change, env, platform)
