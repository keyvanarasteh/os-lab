"""Private, scan-only cron schedules (CLN-18). Times use the host's local clock."""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from datetime import datetime

from .paths import state_dir

LOCK = threading.RLock()
FILE = "schedules.json"
FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


class ScheduleError(ValueError):
    pass


def _field(source, low, high):
    values = set()
    for part in source.split(","):
        match = re.fullmatch(r"(\*|\d+)(?:-(\d+))?(?:/(\d+))?", part)
        if not match:
            raise ScheduleError("Invalid cron field")
        first, end, step = match.groups()
        start = low if first == "*" else int(first)
        stop = high if first == "*" and end is None else (int(end) if end else start)
        stride = int(step) if step else 1
        if first != "*" and end is None and step:
            stop = high
        if not (low <= start <= stop <= high) or stride < 1:
            raise ScheduleError("Cron field is out of range")
        values.update(range(start, stop + 1, stride))
    return values


def parse_cron(expression):
    if not isinstance(expression, str) or len(expression) > 100:
        raise ScheduleError("Cron must have five fields")
    parts = expression.split()
    if len(parts) != 5:
        raise ScheduleError("Cron must have five fields")
    return tuple(_field(part, *bounds) for part, bounds in zip(parts, FIELDS))


def matches(expression, when):
    minute, hour, day, month, weekday = parse_cron(expression)
    # Python Monday=0; cron Sunday=0.
    cron_weekday = (when.weekday() + 1) % 7
    day_match = when.day in day
    weekday_match = cron_weekday in weekday
    day_restricted = expression.split()[2] != "*"
    weekday_restricted = expression.split()[4] != "*"
    calendar_match = (day_match or weekday_match) if day_restricted and weekday_restricted else (day_match and weekday_match)
    return when.minute in minute and when.hour in hour and when.month in month and calendar_match


def _folder(env=None, platform=None, *, create=False):
    folder = state_dir(env, platform)
    if create:
        os.makedirs(folder, mode=0o700, exist_ok=True)
    if not os.path.exists(folder):
        return None
    if os.path.islink(folder) or not os.path.isdir(folder):
        raise ScheduleError("Schedules folder must be a real directory")
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        raise ScheduleError("Schedules folder must be private")
    return folder


def read(*, env=None, platform=None):
    with LOCK:
        folder = _folder(env, platform)
        if folder is None:
            return {"version": 1, "schedules": []}
        target = os.path.join(folder, FILE)
        if not os.path.lexists(target):
            return {"version": 1, "schedules": []}
        mode = os.lstat(target).st_mode
        if not stat.S_ISREG(mode) or (os.name != "nt" and stat.S_IMODE(mode) & 0o077):
            raise ScheduleError("Schedules file must be private")
        try:
            with open(target, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleError("Schedules file cannot be read") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("schedules"), list):
            raise ScheduleError("Schedules file is invalid")
        seen = set()
        for row in data["schedules"]:
            if (not isinstance(row, dict) or set(row) != {"id", "cron", "entryIds", "enabled", "createdAt", "lastSlot", "lastRun"}
                    or not isinstance(row["id"], str) or not re.fullmatch(r"[0-9a-f]{24}", row["id"])
                    or row["id"] in seen or not isinstance(row["enabled"], bool)
                    or not isinstance(row["entryIds"], list) or not row["entryIds"]
                    or any(not isinstance(item, str) for item in row["entryIds"])
                    or not isinstance(row["createdAt"], (int, float))
                    or row["lastSlot"] is not None and not isinstance(row["lastSlot"], int)
                    or row["lastRun"] is not None and not isinstance(row["lastRun"], dict)):
                raise ScheduleError("Schedule is invalid")
            parse_cron(row["cron"])
            seen.add(row["id"])
        if len(seen) > 100:
            raise ScheduleError("Too many schedules")
        return data


def _write(data, *, env=None, platform=None):
    folder = _folder(env, platform, create=True)
    fd, temporary = tempfile.mkstemp(prefix=".schedules-", dir=folder)
    try:
        os.fchmod(fd, 0o600) if hasattr(os, "fchmod") else os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, os.path.join(folder, FILE))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def add(cron, entry_ids, *, enabled=True, env=None, platform=None):
    parse_cron(cron)
    if not isinstance(enabled, bool) or not isinstance(entry_ids, list) or not entry_ids:
        raise ScheduleError("Schedule needs detector ids and a boolean enabled value")
    with LOCK:
        data = read(env=env, platform=platform)
        if len(data["schedules"]) >= 100:
            raise ScheduleError("Too many schedules")
        row = {"id": uuid.uuid4().hex[:24], "cron": cron, "entryIds": entry_ids,
               "enabled": enabled, "createdAt": time.time(), "lastSlot": None, "lastRun": None}
        data["schedules"].append(row)
        _write(data, env=env, platform=platform)
        return row


def toggle(schedule_id, enabled, *, env=None, platform=None):
    if not isinstance(enabled, bool):
        raise ScheduleError("enabled must be a boolean")
    with LOCK:
        data = read(env=env, platform=platform)
        row = next((item for item in data["schedules"] if item["id"] == schedule_id), None)
        if row is None:
            raise ScheduleError("Schedule not found")
        row["enabled"] = enabled
        _write(data, env=env, platform=platform)
        return row


def delete(schedule_id, *, env=None, platform=None):
    with LOCK:
        data = read(env=env, platform=platform)
        before = len(data["schedules"])
        data["schedules"] = [item for item in data["schedules"] if item["id"] != schedule_id]
        if len(data["schedules"]) == before:
            raise ScheduleError("Schedule not found")
        _write(data, env=env, platform=platform)
        return {"deleted": schedule_id}


def claim_due(now=None, *, env=None, platform=None):
    """Atomically reserve this local minute before launching any scans."""
    now = time.time() if now is None else now
    slot = int(now // 60)
    when = datetime.fromtimestamp(now)
    with LOCK:
        data = read(env=env, platform=platform)
        due = []
        for row in data["schedules"]:
            if row["enabled"] and row["lastSlot"] != slot and matches(row["cron"], when):
                row["lastSlot"] = slot
                due.append(dict(row))
        if due:
            _write(data, env=env, platform=platform)
        return due


def record(schedule_id, report, *, env=None, platform=None):
    with LOCK:
        data = read(env=env, platform=platform)
        row = next((item for item in data["schedules"] if item["id"] == schedule_id), None)
        if row is None:
            return
        row["lastRun"] = report
        _write(data, env=env, platform=platform)
