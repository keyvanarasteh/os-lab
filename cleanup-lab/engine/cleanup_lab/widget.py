"""CLW-01: the macOS widget snapshot — one read-only fold of the lab's state.

The desktop app's WidgetKit extension renders whatever this module publishes,
so the snapshot is a plain typed dict of counts, byte totals and statuses:
never paths beyond the home volume's mount point, never a plan or command.
``build`` folds the existing engine modules (volumes, history, monitor,
bookmarks, permissions) plus the console's view of the current job; ``publish``
writes it into the macOS App Group container the widget extension reads.
Both sides agree on the constant names here — the Swift mirror
(``app/widget``) re-declares the group id and file names, because the
extension is a separate module that cannot import Python.
"""
import json
import os
import time

from . import paths as _paths

GROUP_ID = "group.com.keyvanarasteh.oslab"
SNAPSHOT_FILE_NAME = "widget-snapshot.json"
PENDING_QUICK_CLEAN_NAME = "widget-pending-quick-clean.txt"
SCHEMA_VERSION = 1

# Job kinds that change disk contents (everything else is a measurement).
_CLEAN_KINDS = frozenset({"clean", "container-prune", "privileged-run"})


def container_dir(env=None, platform=None):
    """The App Group container directory, when it exists on this machine.

    Never created here: the system makes it for the signed, entitled app, and
    a stray directory on a machine without the widget would be misleading. The
    ``OSLAB_WIDGET_GROUP_DIR`` override exists for tests and for pointing a
    dev console at a fixture directory.
    """
    platform = platform or os.environ.get("OSLAB_PLATFORM") or _paths.platform_id()
    env = os.environ if env is None else env
    override = env.get("OSLAB_WIDGET_GROUP_DIR")
    if override:
        # The explicit override wins on every platform: it is the test and
        # dev seam, and it must exist (never created implicitly).
        path = os.path.realpath(override)
        return path if os.path.isdir(path) else None
    if platform != "macos":
        return None
    home = env.get("HOME") or os.path.expanduser("~")
    path = os.path.join(home, "Library", "Group Containers", GROUP_ID)
    return path if os.path.isdir(path) else None


def status_label(activity=None, found_bytes=0):
    """The widget's one-word state, mirroring the reference app's derivation."""
    if activity is not None:
        return "cleaning" if activity in _CLEAN_KINDS else "scanning"
    return "ready-to-clean" if found_bytes > 0 else "up-to-date"


def pick_latest_scan(jobs):
    for job in jobs:
        result = job.get("result")
        if job.get("kind") == "scan" and job.get("state") == "done" and isinstance(result, dict):
            return job
    return None


def pick_running_job(jobs):
    running = [job for job in jobs if job.get("state") == "running"]
    if not running:
        return None
    return max(running, key=lambda job: job.get("startedAt") or 0)


def _derive_last_scan(job):
    """Only finished scans report numbers; failed or cancelled runs report none."""
    if job is None or job.get("state") != "done":
        return None
    result = job.get("result") or {}
    totals = result.get("totals") or {}
    return {
        "finishedAt": job.get("finishedAt"),
        "foundItems": totals.get("paths", 0),
        "foundBytes": totals.get("sizeBytes", 0),
        "unreadable": totals.get("unreadable", 0),
    }


def _derive_progress(job):
    """Live n/m counters from the running job, in whatever units it uses."""
    if job is None:
        return None
    progress = job.get("progress") or {}
    done = progress.get("pathsDone", progress.get("itemsDone", 0))
    total = progress.get("pathsTotal", progress.get("itemsTotal", 0))
    return {"done": done, "total": total}


def _warning_events(events):
    return [event for event in events if event.get("kind") == "warning"]


def build(latest_scan=None, running_job=None, *, env=None, platform=None, clock=time.time,
          volumes_fn=None, history_fn=None, monitor_fn=None, bookmarks_fn=None, fda_fn=None):
    """The typed widget snapshot. Every input is optional and read-only.

    ``latest_scan`` is the console's most recent finished scan job (or the
    whole job list — the pickers run here); ``running_job`` is the currently
    running job of any kind (same: one job or the list). The ``*_fn`` arguments
    are the test seams — each defaults to the real engine module call.
    """
    platform = platform or os.environ.get("OSLAB_PLATFORM") or _paths.platform_id()
    env = os.environ if env is None else env
    now = clock()

    if volumes_fn is None:
        from . import volumes as _volumes
        volumes_fn = lambda **kw: _volumes.inventory(platform, env, clock=clock, **kw)  # noqa: E731
    report = volumes_fn()
    home = next((v for v in report.get("volumes", []) if v.get("isHome")), None)
    disk = {
        "mountPoint": home.get("mountPoint") if home else None,
        "totalBytes": home.get("totalBytes") if home else None,
        "freeBytes": home.get("freeBytes") if home else None,
        "usedPercent": round(home["usage"] * 100, 1) if home and home.get("usage") is not None else None,
    }

    if history_fn is None:
        from . import history as _history
        history_fn = lambda **kw: _history.read(env=env, platform=platform, **kw)  # noqa: E731
    total_reclaimed = 0
    last_run_at = None
    try:
        entries = history_fn().get("entries", [])
        reclaimed = []
        for entry in entries:
            totals = ((entry.get("result") or {}).get("totals") or {})
            if isinstance(totals.get("bytes"), int):
                reclaimed.append((totals["bytes"], entry["result"].get("finishedAt")))
        total_reclaimed = sum(item[0] for item in reclaimed)
        last_run_at = max((item[1] for item in reclaimed if item[1]), default=None)
    except Exception:
        pass  # a missing or unreadable history never breaks the snapshot
    cleanup = {"totalReclaimedBytes": total_reclaimed, "lastRunAt": last_run_at}

    if monitor_fn is None:
        from . import monitor as _monitor
        monitor_fn = lambda **kw: _monitor.status(env=env, platform=platform)  # noqa: E731
    monitor_payload = monitor_fn()
    state = monitor_payload.get("state") or {}
    interval = monitor_payload.get("intervalSeconds")
    last_evaluation = state.get("lastEvaluationAt")
    warnings = _warning_events(state.get("events") or [])
    monitor = {
        "enabled": bool(monitor_payload.get("enabled")),
        "intervalSeconds": interval if isinstance(interval, int) else None,
        "nextCheckAt": (last_evaluation + interval) if monitor_payload.get("enabled")
                       and isinstance(last_evaluation, (int, float)) and isinstance(interval, int) else None,
        "lastWarningAt": warnings[-1]["at"] if warnings else None,
        "warningCount": len(warnings),
    }

    if bookmarks_fn is None:
        from . import bookmarks as _bookmarks
        bookmarks_fn = lambda **kw: _bookmarks.load(env=env, platform=platform)  # noqa: E731
    records = bookmarks_fn().get("bookmarks", [])
    bookmarks = {
        "count": len(records),
        "quickCleanCount": sum(1 for item in records if item.get("quickClean")),
        "hookCount": sum(1 for item in records if (item.get("autoCleanHook") or {}).get("enabled")),
        "alertCount": sum(1 for item in records if (item.get("sizeAlert") or {}).get("enabled")),
    }

    if fda_fn is None:
        from . import permissions as _permissions
        fda_fn = lambda **kw: _permissions.fda(platform, env)  # noqa: E731
    granted = None
    try:
        granted = fda_fn().get("granted")
    except Exception:
        pass  # an unusable probe renders as "unknown" in the widget
    permissions = {"fullDiskAccess": granted}

    last_scan = _derive_last_scan(pick_latest_scan(latest_scan) if isinstance(latest_scan, list) else latest_scan)
    progress = _derive_progress(pick_running_job(running_job) if isinstance(running_job, list) else running_job)
    running = pick_running_job(running_job) if isinstance(running_job, list) else running_job
    activity = running.get("kind") if running else None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "capturedAt": now,
        "platform": platform,
        "capable": container_dir(env, platform) is not None,
        "disk": disk,
        "lastScan": last_scan,
        "progress": progress,
        "cleanup": cleanup,
        "monitor": monitor,
        "bookmarks": bookmarks,
        "permissions": permissions,
        "status": status_label(activity, last_scan["foundBytes"] if last_scan else 0),
    }


def publish(payload, *, env=None, platform=None, group_dir=None, write_fn=None):
    """Write the snapshot into the App Group container, atomically.

    Best-effort by contract: without the container (no signed app installed,
    not macOS) nothing is written and the reason says so — never an error.
    The widget re-reads the file per timeline build, so a corrupt write must
    never leave a partial JSON behind (os.replace gives that).
    """
    env = os.environ if env is None else env
    directory = group_dir if group_dir is not None else container_dir(env, platform)
    if directory is None:
        return {"published": False, "path": None, "reason": "The widget container is not available here."}
    path = os.path.join(directory, SNAPSHOT_FILE_NAME)
    blob = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if write_fn is not None:
        write_fn(path, blob)
        return {"published": True, "path": path, "reason": None}
    tmp = path + ".tmp"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(tmp, "wb") as handle:
            handle.write(blob)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        return {"published": False, "path": path, "reason": str(exc)}
    return {"published": True, "path": path, "reason": None}


__all__ = [
    "GROUP_ID", "PENDING_QUICK_CLEAN_NAME", "SCHEMA_VERSION", "SNAPSHOT_FILE_NAME",
    "build", "container_dir", "pick_latest_scan", "pick_running_job", "publish", "status_label",
]
