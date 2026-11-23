"""CUX-08: what to clean, chosen from a finished scan, the disk's pressure and the user's preferences.

A pure function. The old dashboard suggested ``defaultSelected`` entries only, so a Mac
with 4 GB free of 245 GB was offered the same 3 GB whether the disk was healthy or nearly
full, and the user's choices had nowhere to live. Here:

* ``recommended`` is the catalog's own default set;
* ``extended`` is every safe measured entry;
* ``auto`` (the default) is ``recommended`` on a healthy disk and, while free space is below
  the warning level, adds the safest largest entries until the shortfall is covered;
* the user's ``include`` list adds entries, the ``exclude`` list removes them, ``minEntryBytes``
  hides entries too small to matter.

Safety is not negotiable: high, privacy and credentials entries, entries that need
administrator rights and entries the catalog marks ``cleanable: false`` are never suggested,
even when the user lists them under ``include`` (they come back in ``skipped`` with the reason).
"""
from __future__ import annotations

UNSAFE_RISKS = ("high", "privacy", "credentials")
RISK_ORDER = {"low": 0, "medium": 1}


def unsafe_reason(entry):
    if entry.get("risk") in UNSAFE_RISKS:
        return "{0} risk entries are never suggested".format(entry.get("risk"))
    if entry.get("needsPrivilege"):
        return "needs administrator rights"
    if entry.get("cleanable") is False:
        return "measured only, the catalog never cleans it"
    return None


def suggest(catalog, scan_entries, preferences, *, free_bytes=None, threshold_bytes=None):
    """Build the suggestion. ``catalog`` and ``scan_entries`` are the API payload lists."""
    by_id = {entry["id"]: entry for entry in catalog}
    measured = {item["id"]: item.get("sizeBytes") or 0 for item in scan_entries if item.get("id") in by_id}
    mode = preferences["mode"]
    exclude = set(preferences["exclude"])
    include = [item for item in preferences["include"] if item in by_id]
    unknown = [item for item in preferences["include"] + preferences["exclude"] if item not in by_id]
    minimum = preferences["minEntryBytes"]
    target = preferences.get("targetFreeBytes") or threshold_bytes
    pressure = free_bytes is not None and target is not None and free_bytes < target
    need = max(0, target - free_bytes) if pressure else 0

    skipped, picked, reasons = [], [], {}

    def take(entry_id, reason):
        if entry_id not in reasons:
            reasons[entry_id] = reason
            picked.append(entry_id)

    candidates = []
    for entry_id, size in measured.items():
        entry = by_id[entry_id]
        if entry_id in exclude or size <= 0 or size < minimum:
            continue
        if unsafe_reason(entry):
            continue
        candidates.append(entry)

    defaults = sorted((e for e in candidates if e.get("defaultSelected")), key=lambda e: -measured[e["id"]])
    others = sorted((e for e in candidates if not e.get("defaultSelected")),
                    key=lambda e: (RISK_ORDER.get(e.get("risk"), 2), -measured[e["id"]]))
    if mode in ("recommended", "auto"):
        for entry in defaults:
            take(entry["id"], "recommended")
    if mode == "extended":
        for entry in defaults:
            take(entry["id"], "recommended")
        for entry in others:
            take(entry["id"], "safe")
    if mode == "auto" and pressure:
        total = sum(measured[item] for item in picked)
        for entry in others:
            if total >= need:
                break
            take(entry["id"], "extra for space")
            total += measured[entry["id"]]
    for entry_id in include:
        entry = by_id[entry_id]
        reason = unsafe_reason(entry)
        if reason:
            skipped.append({"id": entry_id, "reason": reason})
        elif entry_id in exclude:
            continue
        elif measured.get(entry_id, 0) > 0:
            take(entry_id, "included by you")
        else:
            skipped.append({"id": entry_id, "reason": "nothing measured to clean"})

    items = [{"id": item, "name": by_id[item]["name"], "bytes": measured[item], "risk": by_id[item]["risk"], "reason": reasons[item]}
             for item in picked]
    total_bytes = sum(item["bytes"] for item in items)
    return {
        "mode": mode,
        "items": items,
        "totalBytes": total_bytes,
        "pressure": {
            "underPressure": bool(pressure), "freeBytes": free_bytes, "targetFreeBytes": target,
            "shortfallBytes": need, "covers": (not pressure) or total_bytes >= need,
            "remainingBytes": max(0, need - total_bytes) if pressure else 0,
        },
        "skipped": skipped,
        "ignoredIds": sorted(set(unknown)),
    }


__all__ = ["suggest", "unsafe_reason"]
