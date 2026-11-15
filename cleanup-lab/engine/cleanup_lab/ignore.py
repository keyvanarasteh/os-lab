"""User ignore rules the engine enforces at scan and plan time (CLN-17).

Rules are typed data in the private state folder, held to the same discipline
as :mod:`cleanup_lab.settings`: a ``0700`` folder that may not be a symlink, a
``0600`` file that may not be a symlink, and an atomic write so a reader never
sees a half-written store. Three rule types:

* ``path`` — an absolute path. The rule matches the path itself and everything
  under it, so an ignored folder protects its whole subtree.
* ``glob`` — an ``fnmatch`` pattern. It is matched against the full path and
  against every suffix of the path after a separator, so a bare name such as
  ``node_modules*`` matches at any depth. There is no negation: a rule can
  only ever protect, never un-protect.
* ``extension`` — a bare filename suffix (``log``, ``tmp``), matched
  case-insensitively.

Enforcement is the point: the scan skips ignored paths, and a plan refuses an
ignored item. A candidate folder that *contains* an ignored path is refused
too (``contains-ignored``) — the user marked something inside it as
never-touch, so the folder must not be deleted because of what it holds.

The store fails closed: a file that cannot be read, parsed or trusted makes
:func:`load_rules` report a problem, and both the scan and the plan refuse to
run against rules they cannot see — never silently against empty rules.
"""
from __future__ import annotations

import functools
import json
import os
import re
import stat
import uuid

from .paths import home_dir, state_dir

#: The typed rule types, in the order the CLI and settings page list them.
RULE_TYPES = ("path", "glob", "extension")
#: Where the rules store lives inside the private state folder.
STORE_NAME = "ignore-rules.json"
#: An extension is a bare suffix: alphanumerics with a few safe punctuation
#: characters, no wildcard metacharacters, no leading dot (it is stripped).
_EXTENSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class RulesError(RuntimeError):
    """The rules store cannot be trusted; scans and plans fail closed."""


def _store_path(env, platform):
    """The rules file path; the folder is not created by reads."""
    return os.path.join(state_dir(env, platform), STORE_NAME)


def _normalize_path(value, env, platform):
    """Normalise an absolute path rule; ``None`` when it is not usable."""
    value = os.path.normpath(value)
    if not os.path.isabs(value):
        return None
    value = value.rstrip(os.sep)
    if not value or value == os.sep.rstrip(os.sep) or not os.path.isabs(value):
        return None
    if value == os.path.normpath(home_dir(env)):
        return None  # ignoring the home folder would ignore everything
    if value == "/" or value == os.sep:
        return None
    return value


def validate_rule(rule_type, value, *, env=None, platform=None):
    """Validate one rule value; returns the normalised value or raises ``ValueError``.

    ``path`` rules must be absolute, must not carry a trailing separator, and
    must not be the filesystem root or the home folder (either would ignore
    everything, which the guard refuses rather than honours). ``glob`` rules
    keep the pattern as written. ``extension`` rules lose any leading dot and
    are stored lowercase.
    """
    if rule_type not in RULE_TYPES:
        raise ValueError("Rule type must be one of: {0}.".format(", ".join(RULE_TYPES)))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("The rule value must be a non-empty string.")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("The rule value must not contain NUL or newline characters.")
    if rule_type == "path":
        normalized = _normalize_path(value.strip(), env, platform)
        if normalized is None:
            raise ValueError(
                "A path rule must be an absolute folder or file, not the filesystem "
                "root and not the home folder."
            )
        return normalized
    if rule_type == "extension":
        cleaned = value.strip().lower()
        while cleaned.startswith("."):
            cleaned = cleaned[1:]
        if not cleaned or not _EXTENSION_RE.match(cleaned):
            raise ValueError(
                "An extension rule is a bare suffix such as 'log'; wildcards and "
                "separators are not allowed."
            )
        return cleaned
    pattern = value.strip()
    while pattern.endswith("/"):
        pattern = pattern[:-1]
    if not pattern:
        raise ValueError("The rule value must be a non-empty string.")
    return pattern  # glob: the pattern as written, without a trailing separator


def _validate_stored(rule):
    """A stored rule must be the exact typed shape; anything else is corrupt."""
    if not isinstance(rule, dict):
        raise ValueError("A rule must be an object.")
    if set(rule) - {"id", "type", "value", "note"}:
        raise ValueError("A rule holds unknown keys.")
    if not isinstance(rule.get("id"), str) or not rule["id"]:
        raise ValueError("A rule needs an id.")
    if rule.get("type") not in RULE_TYPES:
        raise ValueError("A rule names an unknown type.")
    if not isinstance(rule.get("value"), str) or not rule["value"]:
        raise ValueError("A rule needs a value.")
    if rule.get("note") is not None and not isinstance(rule["note"], str):
        raise ValueError("A rule note must be a string.")


def _read_store(path):
    """Parse the store file with settings-store discipline; corrupt raises ``RulesError``."""
    if os.path.islink(path):
        raise RulesError("The ignore-rules file must not be a symlink.")
    if not os.path.exists(path):
        return {"version": 1, "rules": []}
    try:
        if os.name != "nt" and stat.S_IMODE(os.stat(path).st_mode) & 0o077:
            raise RulesError("The ignore-rules file must be private (mode 0600).")
        with open(path, "r", encoding="utf-8") as handle:
            body = json.load(handle)
    except RulesError:
        raise
    except (OSError, ValueError) as exc:
        raise RulesError("The ignore-rules file cannot be read: {0}".format(exc)) from exc
    if not isinstance(body, dict) or body.get("version") != 1 or not isinstance(body.get("rules"), list):
        raise RulesError("The ignore-rules file holds an unknown shape.")
    for rule in body["rules"]:
        try:
            _validate_stored(rule)
        except ValueError as exc:
            raise RulesError("The ignore-rules file holds an invalid rule: {0}".format(exc)) from exc
    return body


def load_rules(env=None, platform=None):
    """``(rules, problem)`` — never raises.

    ``rules`` is the stored list, empty when nothing was configured. ``problem``
    is ``None`` or ``{"code": "ignore-store-corrupt", "message": ...}``; the
    scan and the plan refuse to run against a store they cannot read.
    """
    path = _store_path(env, platform)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        return [], None
    try:
        body = _read_store(path)
    except RulesError as exc:
        return [], {"code": "ignore-store-corrupt", "message": str(exc)}
    return list(body["rules"]), None


def _write_store(rules, env, platform):
    """Atomically persist the rule list (temp file, fsync, ``os.replace``)."""
    folder = state_dir(env, platform)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    if not os.path.isdir(folder) or os.path.islink(folder):
        raise RulesError("The cleanup state folder is missing or is a symlink.")
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        raise RulesError("The cleanup state folder must be private (mode 0700).")
    path = os.path.join(folder, STORE_NAME)
    body = json.dumps({"version": 1, "rules": rules}, sort_keys=True, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path + ".tmp", flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(path + ".tmp", path)
    except OSError as exc:
        raise RulesError("The ignore-rules file cannot be written: {0}".format(exc)) from exc
    return rules


def add_rule(rule_type, value, note=None, *, env=None, platform=None):
    """Add one rule; returns it. Raises ``ValueError`` for an invalid or duplicate rule."""
    normalized = validate_rule(rule_type, value, env=env, platform=platform)
    rules, problem = load_rules(env, platform)
    if problem is not None:
        raise RulesError(problem["message"])
    for rule in rules:
        if rule["type"] == rule_type and rule["value"] == normalized:
            raise ValueError("This rule already exists.")
    rule = {"id": uuid.uuid4().hex[:12], "type": rule_type, "value": normalized}
    if note:
        rule["note"] = note
    rules.append(rule)
    _write_store(rules, env, platform)
    return rule


def remove_rule(rule_id, *, env=None, platform=None):
    """Remove the rule with this id; ``True`` when it existed."""
    if not isinstance(rule_id, str) or not rule_id:
        raise ValueError("A rule id is required.")
    rules, problem = load_rules(env, platform)
    if problem is not None:
        raise RulesError(problem["message"])
    kept = [rule for rule in rules if rule["id"] != rule_id]
    if len(kept) == len(rules):
        return False
    _write_store(kept, env, platform)
    return True


# ── matching ─────────────────────────────────────────────────────────────────


def _matchable(path):
    """The path in forward-slash form for pattern comparison."""
    return os.path.normpath(path).replace(os.sep, "/")


def _path_rule_matches(rule_value, path):
    """A ``path`` rule matches the path itself and everything under it."""
    rule_value = rule_value.replace(os.sep, "/")
    normalized = _matchable(path)
    rule_value = rule_value.rstrip("/")
    return normalized == rule_value or normalized.startswith(rule_value + "/")


@functools.lru_cache(maxsize=None)
def _glob_regex(pattern):
    """A glob pattern compiled so ``*`` and ``?`` never cross a separator.

    Standard wildcard matching for ignore rules: ``*`` matches any run of
    characters within one path segment, ``?`` matches one character, ``[...]``
    matches a character class (``[!...]`` negates). Everything else matches
    itself. Case handling follows the platform: case-insensitive where the
    filesystem is, case-sensitive where it is not.
    """
    out = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                out.append(re.escape("["))
                index += 1
                continue
            body = pattern[index + 1:end]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append("[" + body + "]")
            index = end + 1
            continue
        else:
            out.append(re.escape(char))
        index += 1
    return "".join(out)


def _glob_rule_matches(pattern, path):
    """A ``glob`` rule matches the full path or any suffix after a separator.

    A pattern that names a folder covers everything under it, exactly like a
    ``path`` rule: if the pattern matches any proper ancestor of the path, the
    path is ignored too. A pattern never matches across a separator unless the
    pattern itself carries one.
    """
    normalized = _matchable(path)
    flags = re.IGNORECASE if os.name == "nt" else 0
    regex = _glob_regex(pattern)
    parts = normalized.split("/")
    count = len(parts)
    for start in range(count):  # the path itself, anchored at any depth
        if re.fullmatch(regex, "/".join(parts[start:]), flags):
            return True
    for start in range(count):  # an ignored ancestor folder covers its subtree
        for end in range(start + 1, count):
            if re.fullmatch(regex, "/".join(parts[start:end]), flags):
                return True
    return False


def match(rules, path):
    """The first rule matching ``path`` directly, or ``None``."""
    if not path:
        return None
    for rule in rules:
        if rule["type"] == "path":
            if _path_rule_matches(rule["value"], path):
                return rule
        elif rule["type"] == "glob":
            if _glob_rule_matches(rule["value"], path):
                return rule
        elif rule["type"] == "extension":
            if path.lower().endswith("." + rule["value"]):
                return rule
    return None


def contains(rules, candidate):
    """A ``path`` rule strictly inside ``candidate`` — the folder holds ignored data."""
    if not candidate:
        return None
    normalized = _matchable(candidate).rstrip("/")
    for rule in rules:
        if rule["type"] != "path":
            continue
        rule_value = rule["value"].replace(os.sep, "/").rstrip("/")
        if rule_value.startswith(normalized + "/"):
            return rule
    return None
