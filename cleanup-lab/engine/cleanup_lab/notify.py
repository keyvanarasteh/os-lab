"""CUX-07: desktop notifications for monitor events.

The monitor used to record a warning and show it only inside the dashboard, so a
disk that filled while the window was closed produced no signal at all. This
module turns the events a tick produced into one native notification each, with
fixed argv and the text passed as arguments (never spliced into a script), so a
volume name can not inject anything.

Delivery is best effort and reports what happened: ``sent``, ``skipped`` with a
reason, or ``failed`` with the error. Nothing here blocks the runner for long.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

LEVELS = ("warning", "critical", "reminder")
TIMEOUT = 5
_MAC_SCRIPT = ["-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)", "-e", "end run"]


def _gib(value):
    return "{0:.1f} GB".format(value / (1024 ** 3)) if isinstance(value, (int, float)) else "unknown"


def describe(event):
    """(title, message) for one monitor event, or None when it is not notifiable."""
    kind = event.get("kind")
    if kind not in LEVELS:
        return None
    mount = event.get("volume") or "your disk"
    title = {"warning": "Low disk space", "critical": "Disk almost full", "reminder": "Disk space is still low"}[kind]
    return title, "{0} has {1} free. Open Cleanup Lab and run Scan & review.".format(mount, _gib(event.get("freeBytes")))


def command(title, message, platform=None, which=shutil.which):
    """The fixed argv for this platform, or None when there is no notifier."""
    platform = platform or sys.platform
    if platform == "darwin":
        return ["osascript", *_MAC_SCRIPT, message, title]
    if platform.startswith("linux") and which("notify-send"):
        return ["notify-send", "--app-name=os-lab", "--", title, message]
    return None


def send(event, *, platform=None, run=subprocess.run, which=shutil.which):
    described = describe(event)
    if described is None:
        return {"status": "skipped", "reason": "not a warning event"}
    argv = command(*described, platform=platform, which=which)
    if argv is None:
        return {"status": "skipped", "reason": "no notifier on this system"}
    try:
        result = run(argv, capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "reason": str(exc)}
    if result.returncode != 0:
        return {"status": "failed", "reason": "the notifier exited with {0}".format(result.returncode)}
    return {"status": "sent", "reason": ""}


def send_all(events, *, enabled=True, **kwargs):
    """Notify once per warning-level event; the cleanup hook and the banner are unaffected."""
    if not enabled:
        return []
    return [send(event, **kwargs) for event in events if event.get("kind") in LEVELS]
