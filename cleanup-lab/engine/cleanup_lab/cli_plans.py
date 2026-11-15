"""Single-use, signed plan handoff between headless CLI invocations."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import tempfile

from . import history
from .clean import Plan, PlanError


def _path(folder, plan_id):
    if not isinstance(plan_id, str) or not re.fullmatch(r"[0-9a-f]{12}", plan_id):
        raise PlanError("Invalid plan id.", "plan-invalid")
    return os.path.join(folder, "cli-plan-" + plan_id + ".json")


def _signature(key, payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(key, encoded.encode("utf-8"), hashlib.sha256).hexdigest()


def save(plan):
    history.prepare()
    folder = history._private_state()
    key = history._key(folder)
    if plan.payload is None:
        raise PlanError("A cancelled plan cannot be saved.")
    payload = {"plan": plan.payload, "fingerprints": plan.fingerprints,
               "progress": plan.progress}
    record = {"payload": payload, "hmac": _signature(key, payload)}
    target = _path(folder, plan.id)
    fd, temporary = tempfile.mkstemp(prefix=".cli-plan-", dir=folder)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def claim(plan_id):
    """Atomic rename consumes the token even when the run later fails."""
    folder = history._private_state()
    key = history._key(folder)
    target = _path(folder, plan_id)
    claimed = target + ".claimed-" + str(os.getpid())
    try:
        mode = os.lstat(target).st_mode
        if not stat.S_ISREG(mode) or (os.name != "nt" and stat.S_IMODE(mode) & 0o077):
            raise PlanError("Plan file must be private.", "plan-invalid")
        os.rename(target, claimed)
    except FileNotFoundError as exc:
        raise PlanError("Unknown or already used plan id.", "unknown-plan") from exc
    try:
        with open(claimed, encoding="utf-8") as handle:
            record = json.load(handle)
        payload = record["payload"]
        if not hmac.compare_digest(record["hmac"], _signature(key, payload)):
            raise PlanError("Plan signature is invalid.", "plan-invalid")
        data = payload["plan"]
        if data["planId"] != plan_id:
            raise PlanError("Plan id does not match the signed file.", "plan-invalid")
        return Plan(id=plan_id, mode=data["mode"], created_at=data["createdAt"],
                    expires_at=data["expiresAt"], payload=data,
                    fingerprints={path: tuple(value) for path, value in payload["fingerprints"].items()},
                    progress=payload["progress"])
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, PlanError):
            raise
        raise PlanError("Plan file is invalid.", "plan-invalid") from exc
    finally:
        os.unlink(claimed)
