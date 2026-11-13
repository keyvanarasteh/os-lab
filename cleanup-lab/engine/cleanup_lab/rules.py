"""Private ignore rules enforced by scans and cleaning plans (CLN-17)."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass

from .paths import state_dir
from .safety import validate_managed_path, PathPolicyError

FILE = "ignore-rules.json"
LOCK = threading.RLock()
KINDS = ("path", "extension", "glob")
EXTENSION = re.compile(r"^\.[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_RULES = 200


class RulesError(ValueError):
    """Invalid rule or private rules store."""


@dataclass(frozen=True)
class Matcher:
    rules: tuple[dict, ...]

    def matches(self, path):
        if not self.rules:
            return None
        full = os.path.realpath(os.fspath(path))
        basename = os.path.basename(full)
        for rule in self.rules:
            value = rule["value"]
            if rule["kind"] == "path":
                try:
                    if os.path.commonpath([full, value]) == value:
                        return rule
                except ValueError:
                    pass
            elif rule["kind"] == "extension" and basename.casefold().endswith(value.casefold()):
                return rule
            elif rule["kind"] == "glob" and (
                fnmatch.fnmatchcase(full, value) or fnmatch.fnmatchcase(basename, value)
            ):
                return rule
        return None


def _folder(env=None, platform=None, *, create=False):
    folder = state_dir(env, platform)
    if create:
        os.makedirs(folder, mode=0o700, exist_ok=True)
    if not os.path.exists(folder):
        return None
    if os.path.islink(folder) or not os.path.isdir(folder):
        raise RulesError("Ignore rules folder must be a real directory")
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        raise RulesError("Ignore rules folder must be private")
    return folder


def _validate(kind, value, *, home=None):
    if kind not in KINDS or not isinstance(value, str) or not value or len(value) > 256 or "\x00" in value or "\n" in value:
        raise RulesError("Rule must have a path, extension or glob value (max 256 characters)")
    if kind == "path":
        try:
            return validate_managed_path(value, home=home)
        except PathPolicyError as exc:
            raise RulesError(str(exc)) from exc
    if kind == "extension" and not EXTENSION.fullmatch(value):
        raise RulesError("Extension must start with a dot and contain no path separators")
    if kind == "glob" and value.strip() != value:
        raise RulesError("Glob cannot have surrounding whitespace")
    return value


def read(*, env=None, platform=None):
    with LOCK:
        folder = _folder(env, platform)
        if folder is None:
            return {"version": 1, "rules": []}
        path = os.path.join(folder, FILE)
        if not os.path.lexists(path):
            return {"version": 1, "rules": []}
        file_mode = os.lstat(path).st_mode
        if not stat.S_ISREG(file_mode) or (os.name != "nt" and stat.S_IMODE(file_mode) & 0o077):
            raise RulesError("Ignore rules file must be private and not a symlink")
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RulesError("Ignore rules file cannot be read") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("rules"), list):
            raise RulesError("Ignore rules file is invalid")
        seen = set()
        for rule in data["rules"]:
            if (not isinstance(rule, dict) or set(rule) != {"id", "kind", "value", "enabled", "createdAt"} or
                not isinstance(rule["id"], str) or not re.fullmatch(r"[0-9a-f]{24}", rule["id"]) or
                rule["id"] in seen or not isinstance(rule["enabled"], bool) or
                not isinstance(rule["createdAt"], (int, float))):
                raise RulesError("Ignore rule is invalid")
            _validate(rule["kind"], rule["value"], home=(env or os.environ).get("HOME"))
            seen.add(rule["id"])
        if len(data["rules"]) > MAX_RULES:
            raise RulesError("Too many ignore rules")
        return data


def _write(data, *, env=None, platform=None):
    folder = _folder(env, platform, create=True)
    target = os.path.join(folder, FILE)
    fd, temporary = tempfile.mkstemp(prefix=".rules-", dir=folder)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def add(kind, value, *, enabled=True, env=None, platform=None):
    if not isinstance(enabled, bool):
        raise RulesError("enabled must be a boolean")
    value = _validate(kind, value, home=(env or os.environ).get("HOME"))
    with LOCK:
        data = read(env=env, platform=platform)
        if len(data["rules"]) >= MAX_RULES:
            raise RulesError("Too many ignore rules")
        rule = {"id": uuid.uuid4().hex[:24], "kind": kind, "value": value,
                "enabled": enabled, "createdAt": time.time()}
        data["rules"].append(rule)
        _write(data, env=env, platform=platform)
        return rule


def update(rule_id, *, kind=None, value=None, enabled=None, env=None, platform=None):
    with LOCK:
        data = read(env=env, platform=platform)
        rule = next((item for item in data["rules"] if item["id"] == rule_id), None)
        if rule is None:
            raise RulesError("Ignore rule not found")
        new_kind = kind if kind is not None else rule["kind"]
        new_value = value if value is not None else rule["value"]
        rule["value"] = _validate(new_kind, new_value, home=(env or os.environ).get("HOME"))
        rule["kind"] = new_kind
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise RulesError("enabled must be a boolean")
            rule["enabled"] = enabled
        _write(data, env=env, platform=platform)
        return rule


def delete(rule_id, *, env=None, platform=None):
    with LOCK:
        data = read(env=env, platform=platform)
        remaining = [item for item in data["rules"] if item["id"] != rule_id]
        if len(remaining) == len(data["rules"]):
            raise RulesError("Ignore rule not found")
        data["rules"] = remaining
        _write(data, env=env, platform=platform)
        return {"deleted": rule_id}


def matcher(data):
    return Matcher(tuple(rule for rule in data["rules"] if rule["enabled"]))


def digest(data):
    encoded = json.dumps(data["rules"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def first_ignored(path, match, *, limit=100000):
    """First ignored descendant, or None. Failure to inspect stops the plan."""
    if not match.rules:
        return None
    stack = [path]
    visited = 0
    while stack:
        current = stack.pop()
        visited += 1
        if visited > limit:
            raise RulesError("Ignore-rule check reached its directory limit")
        if match.matches(current):
            return current
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            raise RulesError("Cannot verify ignore rules under {0}: {1}".format(current, exc)) from exc
        if not stat.S_ISDIR(mode):
            continue
        try:
            with os.scandir(current) as iterator:
                stack.extend(child.path for child in iterator)
        except OSError as exc:
            raise RulesError("Cannot verify ignore rules under {0}: {1}".format(current, exc)) from exc
    return None
