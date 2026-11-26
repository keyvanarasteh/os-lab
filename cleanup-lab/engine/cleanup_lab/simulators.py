"""CLS-01 typed Xcode simulator device cleanup through ``xcrun simctl``.

The page previews one fixed action against the live device inventory, the
console keeps that preview single-use, and the run re-previews and refuses if
the candidates changed. Commands are argv tuples; there is no shell string and
no path the caller can choose. Only shut-down devices can be erased or deleted.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass

from . import deep

#: The only simctl actions the engine runs. ``select`` actions take device ids.
ACTIONS = {
    "simulators.delete-unavailable": {"argv": ("simctl", "delete", "unavailable"), "risk": "low", "select": False},
    "simulators.erase-devices": {"argv": ("simctl", "erase"), "risk": "medium", "select": True},
    "simulators.delete-devices": {"argv": ("simctl", "delete"), "risk": "high", "select": True},
}
UDID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
MAX_DEVICES = 100
EXPIRY_SECONDS = 600
RUN_TIMEOUT = 300


class SimulatorError(ValueError):
    """Unavailable tooling, invalid selection, stale preview, or failed command."""


@dataclass(frozen=True)
class Preview:
    action_id: str
    argv: tuple[str, ...]
    device_ids: tuple[str, ...]
    digest: str
    count: int
    bytes: int
    created_at: float
    risk: str
    devices: tuple[dict, ...] = ()


def actions():
    """The fixed action list the page offers, without argv choices."""
    return [{"id": key, "risk": value["risk"], "needsSelection": value["select"], "defaultSelected": False,
             "command": ["xcrun", *value["argv"], *(["<device ids>"] if value["select"] else [])]}
            for key, value in ACTIONS.items()]


def _digest(devices):
    rows = sorted((d.get("id") or "", d.get("state") or "", bool(d.get("available")), d.get("runtime") or "")
                  for d in devices)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def _summary(device):
    return {"id": device.get("id"), "name": device.get("name"), "runtime": device.get("runtime"),
            "state": device.get("state"), "available": bool(device.get("available")),
            "sizeBytes": device.get("sizeBytes")}


def preview(root, action_id, device_ids=None, *, platform=None, env=None, run=None, clock=time.time):
    """Resolve one action against the live inventory and fingerprint its candidates."""
    action = ACTIONS.get(action_id)
    if action is None:
        raise SimulatorError("Unknown simulator action id")
    inventory = deep.simulators(root, platform=platform, env=env, run=run)
    if not inventory["available"]:
        raise SimulatorError(inventory["reason"] or "Simulator tooling is unavailable")
    devices = [d for d in inventory["devices"] if isinstance(d.get("id"), str) and UDID.fullmatch(d["id"])]
    if action["select"]:
        if (not isinstance(device_ids, list) or not device_ids or len(device_ids) > MAX_DEVICES or
                any(not isinstance(x, str) or not UDID.fullmatch(x) for x in device_ids) or
                len({x.upper() for x in device_ids}) != len(device_ids)):
            raise SimulatorError("deviceIds must list 1 to {0} unique simulator UDIDs".format(MAX_DEVICES))
        by_id = {d["id"].upper(): d for d in devices}
        missing = [x for x in device_ids if x.upper() not in by_id]
        if missing:
            raise SimulatorError("Unknown simulator device: {0}".format(missing[0]))
        candidates = [by_id[x.upper()] for x in device_ids]
        running = [d for d in candidates if d.get("state") != "Shutdown"]
        if running:
            raise SimulatorError("Shut down {0} first; only shut-down simulators can be changed".format(
                running[0].get("name") or running[0]["id"]))
        argv = ("xcrun", *action["argv"], *(d["id"] for d in candidates))
    else:
        if device_ids:
            raise SimulatorError("This action does not take deviceIds")
        candidates = [d for d in devices if not d.get("available")]
        argv = ("xcrun", *action["argv"])
    total = sum(d["sizeBytes"] for d in candidates if isinstance(d.get("sizeBytes"), int))
    return Preview(action_id, argv, tuple(d["id"] for d in candidates), _digest(candidates), len(candidates),
                   total, clock(), action["risk"], tuple(_summary(d) for d in candidates))


def execute(root, plan, *, platform=None, env=None, run=None, clock=time.time):
    """Re-preview, then run exactly the stored argv when nothing changed."""
    run = run or subprocess.run
    if clock() - plan.created_at > EXPIRY_SECONDS:
        raise SimulatorError("Simulator preview expired")
    select = ACTIONS[plan.action_id]["select"]
    fresh = preview(root, plan.action_id, list(plan.device_ids) if select else None,
                    platform=platform, env=env, run=run, clock=clock)
    if fresh.argv != plan.argv or fresh.digest != plan.digest:
        raise SimulatorError("Simulator devices changed; preview again")
    if plan.count == 0:
        raise SimulatorError("There are no simulators to change")
    try:
        result = run(list(plan.argv), shell=False, capture_output=True, text=True,
                     timeout=RUN_TIMEOUT, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SimulatorError("simctl failed: {0}".format(exc)) from exc
    if result.returncode != 0:
        raise SimulatorError((result.stderr or "").strip()[:500] or "simctl returned an error")
    return {"kind": "simulators", "actionId": plan.action_id, "status": "completed",
            "candidateCount": plan.count, "devices": list(plan.devices), "command": list(plan.argv),
            "output": (result.stdout or "").strip()[:2000], "bytesFreed": plan.bytes}
