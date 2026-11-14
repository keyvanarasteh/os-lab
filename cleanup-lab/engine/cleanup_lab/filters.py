"""Age and size filters for scan and plan requests (CLN-32).

A filter narrows a planned list by age ("only items older than 7 days") and
size — but a filter must never quietly change what gets deleted. The
filtered-in-flux guard is the point: while a filter hides planned items,
plan building refuses to run, because the confirmation page would show the
filtered list while the unfiltered list would be removed. :func:`blocked`
is true whenever anything was excluded, and the caller turns it into a
refusal that carries the exclusion reasons.

The helpers here are pure. :func:`parse_duration` turns a duration string
(``7d``, ``2h30m``, ``1y2mo``) into seconds, :func:`parse_filters` picks the
typed filter fields out of a request, :func:`age_bucket` and
:func:`apply_filters` decide per item, and :func:`blocked` reports whether
the plan must refuse. Nothing is written; the filesystem is only ever read
with ``lstat`` on the paths the caller hands over, so symlinks are never
followed.
"""
from __future__ import annotations

import math
import os
import re

#: Duration units, largest first, with their fixed length in seconds. ``mo``
#: is a 30-day month and ``y`` a 365-day year: an age filter needs a fixed
#: length, not a calendar answer that changes with the date.
UNITS = (
    ("y", 31536000),  # 365 days
    ("mo", 2592000),  # 30 days
    ("w", 604800),
    ("d", 86400),
    ("h", 3600),
    ("m", 60),
    ("s", 1),
)
_SECONDS_PER_UNIT = dict(UNITS)
#: Position of each unit in the descending order. A multi-token duration
#: walks this order from largest to smallest, each unit at most once.
_UNIT_RANK = {unit: rank for rank, (unit, _seconds) in enumerate(UNITS)}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_UNIT_RE = re.compile(r"[A-Za-z]+")
_SPACE_RE = re.compile(r"\s*")

#: The request fields :func:`parse_filters` reads, in validation order.
AGE_KEYS = ("minAgeSeconds", "maxAgeSeconds")
SIZE_KEYS = ("minSizeBytes", "maxSizeBytes")
FILTER_KEYS = AGE_KEYS + SIZE_KEYS

#: The exclusion reasons :func:`apply_filters` reports, in check order.
REASON_YOUNGER = "younger than the minimum age"
REASON_OLDER = "older than the maximum age"
REASON_SMALLER = "below the minimum size"
REASON_LARGER = "above the maximum size"
REASON_MISSING = "the item no longer exists"


class FilterError(ValueError):
    """A filter value cannot be used as given; the caller reports it verbatim."""


def parse_duration(text):
    """Parse a duration into seconds (``float``).

    A bare number is seconds (``"90"``); otherwise each token is a whole
    number with a unit — ``s``, ``m``, ``h``, ``d``, ``w``, ``mo`` (30 days)
    or ``y`` (365 days) — case-insensitive, and multiple tokens must appear
    in descending unit order with each unit at most once (``"2h30m"``,
    ``"1y2mo"``). Whitespace is allowed between tokens, and a bare fractional
    number is a fractional number of seconds (``"1.5"``); a unit token never
    takes a fraction (``"1.5h"`` is refused — write ``"90m"``).

    Raises :class:`FilterError` (a ``ValueError``) for an empty, negative,
    non-numeric or badly shaped value.
    """
    if not isinstance(text, str):
        raise FilterError("A duration must be a string like '7d' or '2h30m'.")
    stripped = text.strip()
    if not stripped:
        raise FilterError("A duration is required.")
    if stripped.startswith("-"):
        raise FilterError("A duration must not be negative: '{0}'.".format(text))
    tokens = []
    position = 0
    length = len(stripped)
    while position < length:
        position = _SPACE_RE.match(stripped, position).end()
        if position >= length:
            break  # trailing whitespace
        number = _NUMBER_RE.match(stripped, position)
        if number is None:
            raise FilterError(
                "'{0}' is not a duration: expected a number where '{1}' appears.".format(
                    text, stripped[position]
                )
            )
        number_text = number.group(0)
        position = number.end()
        unit_match = _UNIT_RE.match(stripped, position)
        if unit_match is None:
            unit = ""  # a bare number: seconds, and only standing alone
        else:
            unit = unit_match.group(0).lower()
            position = unit_match.end()
        tokens.append((number_text, unit))
    if len(tokens) > 1 and any(unit == "" for _number, unit in tokens):
        raise FilterError(
            "A bare number of seconds must stand alone in '{0}'.".format(text)
        )
    total = 0
    previous_rank = None
    seen = set()
    for number_text, unit in tokens:
        if unit == "":
            total += float(number_text)
            continue
        if unit not in _SECONDS_PER_UNIT:
            raise FilterError(
                "Unknown duration unit '{0}' in '{1}': units are {2}.".format(
                    unit, text, ", ".join(name for name, _seconds in UNITS)
                )
            )
        if "." in number_text:
            raise FilterError(
                "A duration unit takes a whole number: '{0}{1}' in '{2}' is not valid.".format(
                    number_text, unit, text
                )
            )
        if unit in seen:
            raise FilterError(
                "The duration unit '{0}' appears more than once in '{1}'.".format(unit, text)
            )
        rank = _UNIT_RANK[unit]
        if previous_rank is not None and rank < previous_rank:
            raise FilterError(
                "Duration units must appear in descending order "
                "(y, mo, w, d, h, m, s) in '{0}'.".format(text)
            )
        seen.add(unit)
        previous_rank = rank
        total += int(number_text) * _SECONDS_PER_UNIT[unit]
    try:
        seconds = float(total)
    except OverflowError:
        raise FilterError("The duration '{0}' is too large.".format(text)) from None
    if not math.isfinite(seconds):
        raise FilterError("The duration '{0}' is too large.".format(text))
    return seconds


def _parse_age(key, value):
    """One age field: a number of seconds or a duration string, never negative."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise FilterError("{0} must be a number of seconds or a duration string.".format(key))
    if isinstance(value, str):
        try:
            seconds = parse_duration(value)
        except FilterError as exc:
            raise FilterError("{0}: {1}".format(key, exc)) from exc
    else:
        try:
            seconds = float(value)
        except OverflowError:
            raise FilterError("{0} is too large to be a number of seconds.".format(key)) from None
    if not math.isfinite(seconds):
        raise FilterError("{0} must be a finite number of seconds.".format(key))
    if seconds < 0:
        raise FilterError("{0} must not be negative.".format(key))
    return seconds


def _parse_size(key, value):
    """One size field: a whole, non-negative number of bytes."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FilterError("{0} must be a number of bytes.".format(key))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FilterError("{0} must be a finite number of bytes.".format(key))
        if value < 0:
            raise FilterError("{0} must not be negative.".format(key))
        if value != int(value):
            raise FilterError("{0} must be a whole number of bytes.".format(key))
    elif value < 0:
        raise FilterError("{0} must not be negative.".format(key))
    return int(value)


def parse_filters(request):
    """Pick the typed filter fields out of a request; ``None`` means no filters.

    Reads ``minAgeSeconds`` and ``maxAgeSeconds`` (a number of seconds or a
    duration string) and ``minSizeBytes`` and ``maxSizeBytes`` (a whole
    number of bytes). Unknown keys are the caller's business and are left
    alone. Returns ``{"minAgeSeconds": float|None, "maxAgeSeconds":
    float|None, "minSizeBytes": int|None, "maxSizeBytes": int|None,
    "active": bool}`` where ``active`` is true when any field is set.
    Raises :class:`FilterError` for a negative value, an inverted range
    (``min`` greater than ``max``) or an unparseable duration.
    """
    if request is None:
        request = {}
    if not isinstance(request, dict):
        raise FilterError("The filter request must be an object.")
    filters = {
        "minAgeSeconds": None,
        "maxAgeSeconds": None,
        "minSizeBytes": None,
        "maxSizeBytes": None,
        "active": False,
    }
    for key in AGE_KEYS:
        filters[key] = _parse_age(key, request.get(key))
    for key in SIZE_KEYS:
        filters[key] = _parse_size(key, request.get(key))
    if (
        filters["minAgeSeconds"] is not None
        and filters["maxAgeSeconds"] is not None
        and filters["minAgeSeconds"] > filters["maxAgeSeconds"]
    ):
        raise FilterError("minAgeSeconds must not be greater than maxAgeSeconds.")
    if (
        filters["minSizeBytes"] is not None
        and filters["maxSizeBytes"] is not None
        and filters["minSizeBytes"] > filters["maxSizeBytes"]
    ):
        raise FilterError("minSizeBytes must not be greater than maxSizeBytes.")
    filters["active"] = any(filters[key] is not None for key in FILTER_KEYS)
    return filters


def _age_decision(path, *, filters, now, lstat):
    """``(bucket, reason)``: the reason names the bound that excluded the item.

    An item exactly at either bound is included; the bounds exclude strictly
    (``age < min`` is too fresh, ``age > max`` is too old). A path that
    cannot be ``lstat``ed is ``missing`` — a vanished item cannot be
    filtered in, so it never counts as included.
    """
    if filters.get("minAgeSeconds") is None and filters.get("maxAgeSeconds") is None:
        return "include", None
    try:
        st = lstat(path)
    except OSError:
        return "missing", None
    age = now - st.st_mtime
    minimum = filters.get("minAgeSeconds")
    maximum = filters.get("maxAgeSeconds")
    if minimum is not None and age < minimum:
        return "exclude", REASON_YOUNGER
    if maximum is not None and age > maximum:
        return "exclude", REASON_OLDER
    return "include", None


def age_bucket(path, *, filters, now, lstat=os.lstat):
    """``"include"`` / ``"exclude"`` / ``"missing"`` for the age dimension.

    With no active age filters everything is included and the path is never
    touched. Otherwise the item's age (``now - st_mtime``, read with
    ``lstat`` so a symlink is never followed) decides: younger than
    ``minAgeSeconds`` or older than ``maxAgeSeconds`` is excluded, exactly at
    a bound is included, and an ``lstat`` failure is ``missing``.
    """
    bucket, _reason = _age_decision(path, filters=filters, now=now, lstat=lstat)
    return bucket


def apply_filters(items, *, filters, now, lstat=os.lstat):
    """Split plan items into ``{"included": [...], "excluded": [{"item", "reason"}]}``.

    Items are dicts carrying ``path`` and ``sizeBytes``. With no active
    filter, every item is included untouched and nothing is stat'ed. With
    age filters active, each path is ``lstat``ed (a failure excludes the
    item as gone — a vanished item cannot be filtered in); size filters
    compare the item's own measured ``sizeBytes`` directly and never stat:
    a ``None`` size is included rather than guessed. Age is checked before
    size, and the first failing check's reason is the one reported. Each
    excluded entry carries the very item dict it excludes, in input order.
    """
    if not filters.get("active"):
        return {"included": list(items), "excluded": []}
    has_age = (
        filters.get("minAgeSeconds") is not None or filters.get("maxAgeSeconds") is not None
    )
    included = []
    excluded = []
    for item in items:
        reason = None
        if has_age:
            bucket, age_reason = _age_decision(
                item["path"], filters=filters, now=now, lstat=lstat
            )
            if bucket == "missing":
                reason = REASON_MISSING
            elif bucket == "exclude":
                reason = age_reason
        if reason is None:
            size = item.get("sizeBytes")
            if size is not None:
                minimum = filters.get("minSizeBytes")
                maximum = filters.get("maxSizeBytes")
                if minimum is not None and size < minimum:
                    reason = REASON_SMALLER
                elif maximum is not None and size > maximum:
                    reason = REASON_LARGER
        if reason is None:
            included.append(item)
        else:
            excluded.append({"item": item, "reason": reason})
    return {"included": included, "excluded": excluded}


def blocked(items_excluded):
    """True while anything was filtered out: the plan refuses to build.

    Pass the ``excluded`` list :func:`apply_filters` returned, or the whole
    result dict. The caller turns a ``True`` into a refusal that carries the
    exclusion reasons — the confirmation must never show a filtered list
    while the run would remove the unfiltered one.
    """
    if isinstance(items_excluded, dict):
        items_excluded = items_excluded.get("excluded", [])
    return bool(items_excluded)
