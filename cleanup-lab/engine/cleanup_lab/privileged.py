"""Fixed privileged maintenance actions with explicit preview and confirmation."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import threading
import time
import uuid

from .paths import platform_id
from . import safety

TTL = 600
LOCK = threading.Lock()
PLANS = {}
TRUSTED_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
ACTIONS = safety.PRIVILEGED_ACTIONS


class PrivilegedError(ValueError):
    def __init__(self, message, code="invalid"):
        super().__init__(message)
        self.code = code


def _trusted_binary(name, *, which=shutil.which, lstat=os.stat, trusted_dirs=TRUSTED_DIRS):
    found = which(name)
    if not found:
        raise PrivilegedError("Required tool is unavailable: " + name, "unavailable")
    real = os.path.realpath(found)
    if os.path.dirname(real) not in trusted_dirs:
        raise PrivilegedError("Tool is outside a trusted system directory: " + name, "unavailable")
    mode = lstat(real)
    if not stat.S_ISREG(mode.st_mode) or mode.st_mode & 0o022 or mode.st_uid != 0:
        raise PrivilegedError("Tool is not a root-owned, protected executable: " + name, "unavailable")
    return real


def preview(action_ids, *, platform=None, which=shutil.which, lstat=os.stat, clock=time.time):
    target = platform or platform_id()
    if (not isinstance(action_ids, list) or not action_ids or len(set(action_ids)) != len(action_ids)
            or any(not isinstance(value, str) or value not in ACTIONS for value in action_ids)):
        raise PrivilegedError("Choose unique, known privileged action ids")
    items = []
    for action_id in action_ids:
        os_name, description, argv = ACTIONS[action_id]
        if os_name != target:
            raise PrivilegedError("Action is unavailable on this operating system: " + action_id, "unavailable")
        safety.assert_privileged_action(action_id, target, argv)
        binary = _trusted_binary(argv[0], which=which, lstat=lstat)
        items.append({"id": action_id, "description": description,
                      "argv": [binary, *argv[1:]], "platform": target})
    escalator = "pkexec" if target == "linux" and which("pkexec") else "sudo"
    escalator_path = _trusted_binary(escalator, which=which, lstat=lstat)
    now = clock()
    plan = {"planId": uuid.uuid4().hex[:12], "createdAt": now,
            "expiresAt": now + TTL, "platform": target,
            "authorization": escalator, "actions": items}
    with LOCK:
        PLANS[plan["planId"]] = (plan, escalator_path)
        if len(PLANS) > 50:
            oldest = min(PLANS, key=lambda key: PLANS[key][0]["createdAt"])
            PLANS.pop(oldest, None)
    return plan


def run(plan_id, *, platform=None, which=shutil.which, lstat=os.stat,
        runner=subprocess.run, clock=time.time):
    if not isinstance(plan_id, str):
        raise PrivilegedError("planId is required")
    with LOCK:
        stored = PLANS.pop(plan_id, None)
    if stored is None:
        raise PrivilegedError("Unknown or already used privileged plan", "unknown-plan")
    plan, escalator_path = stored
    if clock() > plan["expiresAt"]:
        raise PrivilegedError("Privileged plan expired", "expired")
    if (platform or platform_id()) != plan["platform"]:
        raise PrivilegedError("Platform changed since preview", "stale")
    if _trusted_binary(plan["authorization"], which=which, lstat=lstat) != escalator_path:
        raise PrivilegedError("Authorization tool changed since preview", "stale")
    results = []
    for item in plan["actions"]:
        safety.assert_privileged_action(item["id"], plan["platform"],
                                        (os.path.basename(item["argv"][0]), *item["argv"][1:]))
        if _trusted_binary(os.path.basename(item["argv"][0]), which=which, lstat=lstat) != item["argv"][0]:
            results.append({"id": item["id"], "status": "failed", "error": "Tool changed since preview"})
            continue
        command = ([escalator_path] if plan["authorization"] == "pkexec" else [escalator_path, "-n", "--"])
        command += item["argv"]
        try:
            completed = runner(command, shell=False, capture_output=True, text=True, timeout=120)
            results.append({"id": item["id"], "status": "done" if completed.returncode == 0 else "failed",
                            "exitCode": completed.returncode,
                            "output": (completed.stdout or "")[:4000],
                            "error": (completed.stderr or "")[:4000] or None})
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append({"id": item["id"], "status": "failed", "error": str(exc)})
    return {"planId": plan_id, "mode": "privileged", "platform": plan["platform"],
            "results": results, "totals": {"items": len(results),
            "failed": sum(item["status"] == "failed" for item in results), "bytes": 0},
            "cancelled": False, "finishedAt": clock()}
