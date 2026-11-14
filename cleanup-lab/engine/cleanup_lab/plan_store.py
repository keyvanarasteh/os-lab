"""The headless plan store (CLN-19): plans built by `labctl` persist here.

The console keeps its plans in one process's memory; the CLI builds a plan in
one invocation and cleans it in another, so the plan lives in a small file
store inside the private state folder (`plans/<planId>.json`). The discipline
matches the other stores: a `0700` folder, `0600` files, no symlinks.

A plan is single-use because **claiming renames the file away** — the second
`clean --plan <id>` finds nothing, a crash mid-clean leaves the claimed file
behind so nothing can ever run twice, and the audit history carries the
outcome. The ten-minute TTL is enforced again at claim time, on top of
:func:`cleanup_lab.clean.verify_plan`'s own expiry check, so an old plan
cannot survive in the store past its lifetime.
"""
from __future__ import annotations

import json
import os
import stat
import uuid

from .paths import state_dir

#: Where the plan store lives inside the private state folder.
STORE_DIR = "plans"


class PlanStoreError(RuntimeError):
    """The plan store cannot be used; the message is the honest reason."""


def _store_dir(env, platform):
    """The store folder, created with private mode on first use."""
    folder = os.path.join(state_dir(env, platform), STORE_DIR)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    if not os.path.isdir(folder) or os.path.islink(folder):
        raise PlanStoreError("The plan store folder is missing or is a symlink.")
    if os.name != "nt" and stat.S_IMODE(os.stat(folder).st_mode) & 0o077:
        raise PlanStoreError("The plan store folder must be private (mode 0700).")
    return folder


def save(plan, *, env=None, platform=None):
    """Persist one built plan atomically; returns the store path."""
    folder = _store_dir(env, platform)
    body = json.dumps({
        "id": plan.id,
        "mode": plan.mode,
        "createdAt": plan.created_at,
        "expiresAt": plan.expires_at,
        "payload": plan.payload,
        "fingerprints": plan.fingerprints,
        "progress": plan.progress,
    }, sort_keys=True) + "\n"
    path = os.path.join(folder, plan.id + ".json")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path + ".tmp", flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(path + ".tmp", path)
    except OSError as exc:
        raise PlanStoreError("The plan store cannot be written: {0}".format(exc)) from exc
    return path


def claim(plan_id, *, env=None, platform=None):
    """Atomically claim one stored plan; returns ``(plan_path, record)``.

    Raises :class:`PlanStoreError` for an unknown id. The record carries the
    ``expiresAt`` clock the caller compares against its own TTL decision, plus
    everything :meth:`cleanup_lab.clean.Plan` needs to be rebuilt. After the
    claim the stored file is gone — the caller removes the claimed copy when
    the run ends, whatever its outcome.
    """
    if not isinstance(plan_id, str) or not plan_id or "/" in plan_id or "\\" in plan_id or plan_id.startswith("."):
        raise PlanStoreError("A plan id is required.")
    folder = os.path.join(state_dir(env, platform), STORE_DIR)
    path = os.path.join(folder, plan_id + ".json")
    if os.path.islink(path):
        raise PlanStoreError("The plan file must not be a symlink.")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except FileNotFoundError:
        raise PlanStoreError("No plan with id {0} in the store; build one with "
                             "`labctl cleanup plan`.".format(plan_id)) from None
    except (OSError, ValueError) as exc:
        raise PlanStoreError("The plan file cannot be read: {0}".format(exc)) from exc
    if not isinstance(record, dict) or record.get("id") != plan_id \
            or not isinstance(record.get("payload"), dict) \
            or not isinstance(record.get("fingerprints"), dict):
        raise PlanStoreError("The plan file holds an unknown shape.")
    claimed = os.path.join(folder, "{0}.claimed-{1}.json".format(plan_id, uuid.uuid4().hex[:8]))
    try:
        os.rename(path, claimed)
    except FileNotFoundError:
        raise PlanStoreError("No plan with id {0} in the store; build one with "
                             "`labctl cleanup plan`.".format(plan_id)) from None
    except OSError as exc:
        raise PlanStoreError("The plan cannot be claimed: {0}".format(exc)) from exc
    return claimed, record


def discard(claimed_path):
    """Remove a claimed plan file; the run ended, whatever its outcome."""
    try:
        os.unlink(claimed_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise PlanStoreError("The claimed plan cannot be removed: {0}".format(exc)) from exc
