"""Policy gate for the Windows Apps Lab.

Decides which desktop windows a person or an agent may see, records what agents did and what was
refused, and is the only door the web endpoints and the MCP server use to reach the native
collector in winapps.py. It has no Win32 dependency, so it is testable on any host.

The filter reads process names and window titles only. It is a heuristic, not a guarantee.
"""

from __future__ import annotations

import json
import os
import threading
import time
import unicodedata
from dataclasses import dataclass

import winapps

POLICY_ENV = "OSLAB_WINAPPS_POLICY"
POLICY_KEYS = ("allowedApps", "restrictedApps", "restrictedTitles")

# Built-in restrictions can be extended by the policy file but never removed.
BUILTIN_RESTRICTED_APPS = frozenset({
    "1password", "bitwarden", "keepass", "keepassxc", "dashlane", "lastpass", "nordpass",
    "enpass", "roboform", "proton pass", "protonpass",
})
BUILTIN_PRIVATE_TITLES = ("inprivate", "incognito", "private browsing", "private window")
BUILTIN_BANKING_TITLES = ("online banking", "internet banking")


class GuardError(Exception):
    """A refusal the caller can show: what failed, a stable code and whether retrying can help."""

    def __init__(self, message: str, code: str, retry: str = "never") -> None:
        super().__init__(message)
        self.code = code
        self.retry = retry


@dataclass(frozen=True)
class Policy:
    allowed: frozenset[str]
    restricted_apps: frozenset[str]
    restricted_titles: tuple[str, ...]
    error: str | None
    path: str
    exists: bool


@dataclass(frozen=True)
class Verdict:
    restricted: bool
    allowed: bool
    reason: str | None


def _norm(value: object) -> str:
    """Case, accent and Turkish dotted/dotless i insensitive form used for every comparison."""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold().replace("ı", "i").strip()


def _norm_app(value: object) -> str:
    name = _norm(value)
    return name[:-4].strip() if name.endswith(".exe") else name


def _policy_path(root: str) -> str:
    return os.environ.get(POLICY_ENV) or os.path.join(root, "win-lab", "winapps-policy.json")


_POLICY_CACHE: dict[str, tuple[bytes, Policy]] = {}  # keyed by the file contents, not size or mtime


def _broken(path: str, message: str) -> Policy:
    return Policy(frozenset(), frozenset(), (), message, path, True)


def _parse(path: str, raw: bytes) -> Policy:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return _broken(path, "The policy file is not valid JSON")
    if not isinstance(data, dict):
        return _broken(path, "The policy file must be a JSON object")
    errors: list[str] = []
    unknown = sorted(str(key) for key in data if key not in POLICY_KEYS)
    if unknown:
        errors.append("Unknown policy key(s): " + ", ".join(unknown))  # a typo must not drop a restriction
    lists: dict[str, list[str]] = {}
    for key in POLICY_KEYS:
        value = data.get(key, [])
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            lists[key] = value
        else:
            lists[key] = []
            errors.append(f"{key} must be a list of strings")
    restricted_apps = frozenset(name for name in map(_norm_app, lists["restrictedApps"]) if name)
    restricted_titles = tuple(hint for hint in map(_norm, lists["restrictedTitles"]) if hint)
    if errors:
        # Fail closed for the allowlist, but keep every restriction that did parse.
        return Policy(frozenset(), restricted_apps, restricted_titles, "; ".join(errors), path, True)
    allowed = frozenset(name for name in map(_norm_app, lists["allowedApps"]) if name)
    return Policy(allowed, restricted_apps, restricted_titles, None, path, True)


def load_policy(root: str) -> Policy:
    """The current policy; a missing file allows nothing and a broken one fails closed."""
    path = _policy_path(root)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return Policy(frozenset(), frozenset(), (), None, path, False)
    except OSError:
        return _broken(path, "The policy file could not be read")
    cached = _POLICY_CACHE.get(path)
    if cached and cached[0] == raw:
        return cached[1]
    policy = _parse(path, raw)
    _POLICY_CACHE[path] = (raw, policy)
    return policy


def classify(window: dict, policy: Policy) -> Verdict:
    """Restricted wins over the allowlist; an app off the allowlist is simply not allowed."""
    app = _norm_app(window.get("app") or "")
    title = _norm(window.get("title") or "")
    if app in BUILTIN_RESTRICTED_APPS:
        return Verdict(True, False, "password-manager")
    if app and app in policy.restricted_apps:
        return Verdict(True, False, "policy-app")
    if any(hint in title for hint in BUILTIN_PRIVATE_TITLES):
        return Verdict(True, False, "private-window")
    if any(hint in title for hint in BUILTIN_BANKING_TITLES):
        return Verdict(True, False, "banking-hint")
    if any(hint in title for hint in policy.restricted_titles):
        return Verdict(True, False, "policy-title")
    if app and app in policy.allowed:
        return Verdict(False, True, None)
    return Verdict(False, False, "not-allowlisted")


def policy_summary(root: str) -> dict:
    """Counts only: the app names stay in the policy file."""
    policy = load_policy(root)
    return {"allowedApps": len(policy.allowed), "restrictedApps": len(policy.restricted_apps),
            "restrictedTitles": len(policy.restricted_titles), "policyError": policy.error,
            "path": policy.path, "exists": policy.exists}


# ── Audit ────────────────────────────────────────────────────────────────────

AUDIT_DIR_ENV = "OSLAB_WINAPPS_AUDIT_DIR"
_AUDIT_MAX = 500
_COALESCE_SECONDS = 60
_AUDIT: list[dict] = []
_AUDIT_SEQ = 0
_AUDIT_LOCK = threading.Lock()
_AUDIT_FILE_MAX_ROWS = 10_000  # per process and day: a flood of distinct rows must not fill the disk
_AUDIT_FILE_ROWS = 0
_AUDIT_PERSISTENT = True


def _reset_audit() -> None:
    global _AUDIT_SEQ, _AUDIT_FILE_ROWS, _AUDIT_PERSISTENT
    with _AUDIT_LOCK:
        _AUDIT.clear()
        _AUDIT_SEQ = 0
        _AUDIT_FILE_ROWS = 0
        _AUDIT_PERSISTENT = True


def audit(root: str | None, kind: str, *, audience: str, app: str | None = None,
          window_id: int | None = None, code: str | None = None, tool: str | None = None) -> None:
    """Record one row. Never raises: auditing must not break the action it describes.

    Titles and pixels cannot be passed in. An identical row (same audience, kind, app, window and
    code) within 60 seconds of the previous one only raises its count, so a panel retrying a
    restricted window every few seconds writes one row a minute.
    """
    global _AUDIT_SEQ, _AUDIT_FILE_ROWS, _AUDIT_PERSISTENT
    try:
        now = time.time()
        with _AUDIT_LOCK:
            last = _AUDIT[-1] if _AUDIT else None
            if (last and now - last["time"] <= _COALESCE_SECONDS and last["audience"] == audience
                    and last["kind"] == kind and last["app"] == app and last["windowId"] == window_id
                    and last["code"] == code):
                last["count"] += 1
                return
            _AUDIT_SEQ += 1
            row = {"seq": _AUDIT_SEQ, "time": now, "audience": audience, "kind": kind, "app": app,
                   "windowId": window_id, "code": code, "tool": tool, "count": 1}
            _AUDIT.append(row)
            del _AUDIT[:-_AUDIT_MAX]
            folder = os.environ.get(AUDIT_DIR_ENV) or (os.path.join(root, "win-lab", "artifacts") if root else None)
            if folder:
                # Under the lock so rows reach the file in seq order; a failure or the cap only
                # flips `persistent`, the in-memory trail keeps working.
                if _AUDIT_FILE_ROWS >= _AUDIT_FILE_MAX_ROWS:
                    _AUDIT_PERSISTENT = False
                else:
                    try:
                        os.makedirs(folder, exist_ok=True)
                        with open(os.path.join(folder, "winapps-audit-%s.jsonl" % time.strftime("%Y%m%d")),
                                  "a", encoding="utf-8") as f:
                            f.write(json.dumps(row) + "\n")
                        _AUDIT_FILE_ROWS += 1
                    except OSError:
                        _AUDIT_PERSISTENT = False
    except Exception:  # noqa: BLE001 - the audit trail is best effort by design
        pass


_AGENT_HIDDEN_CODES = ("RESTRICTED_WINDOW", "APP_NOT_ALLOWED")


def audit_rows(limit: int = 200, *, audience: str | None = None) -> dict:
    """The newest rows for the panel and the MCP audit tool.

    For the agent view only the agent's own rows are returned, and the app name of a refusal for a
    restricted or non-allowlisted window is dropped, so the audit cannot reveal what the agent was
    never allowed to see. `persistent` is False when rows are no longer reaching the daily file.
    """
    with _AUDIT_LOCK:
        selected = [dict(row) for row in _AUDIT if audience != "agent" or row["audience"] == "agent"]
        persistent = _AUDIT_PERSISTENT
    if audience == "agent":
        for row in selected:
            if row["code"] in _AGENT_HIDDEN_CODES:
                row["app"] = None
    return {"recording": True, "persistent": persistent, "rows": selected[-max(0, limit):]}


# ── Guarded facade: the only way web_ui and the MCP server reach the collector ─────────────────

_MAX_HWND = 0xFFFFFFFF
AUDIENCES = ("human", "agent")
AGENT_MAX_PIXELS = 3840 * 2160  # an agent capture is base64'd into one JSON line; people keep the 8K ceiling
_CAPTURE_TIMEOUT = 15.0


def _capture(hwnd: int) -> bytes:
    """The raw capture with a deadline: a window that stops responding must not block the caller."""
    box: dict = {}

    def run() -> None:
        try:
            box["png"] = winapps.winapps_window_screenshot(hwnd)
        except BaseException as error:  # noqa: BLE001 - re-raised on the caller's thread
            box["error"] = error

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(_CAPTURE_TIMEOUT)
    if worker.is_alive():
        raise winapps.WinAppError("That window did not respond in time; try again later", "CAPTURE_TIMEOUT")
    if "error" in box:
        raise box["error"]
    return box["png"]


def _audience(value: object) -> None:
    """Fail closed: an unknown audience must never fall through to the more permissive human view."""
    if value not in AUDIENCES:
        raise GuardError("Unknown audience", "INVALID_AUDIENCE")


def require_audience(value: object) -> None:
    """Public form of the audience check for sibling modules such as the input gate."""
    _audience(value)


def parse_window_id(value: object) -> int:
    """Public form of the window id check: a GuardError(INVALID_WINDOW) unless it is a plausible HWND."""
    return _window_id(value)


def _window_id(value: object) -> int:
    """A usable window id, or INVALID_WINDOW. Only real integers and ASCII digit strings qualify."""
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        number = int(value)
    else:
        number = None
    if number is None or not 0 < number <= _MAX_HWND:
        raise GuardError("Invalid window id", "INVALID_WINDOW")
    return number


def _refuse(root: str, audience: str, tool: str | None, window: dict | None, window_id: int | None,
            code: str, message: str, retry: str = "never") -> GuardError:
    audit(root, "refused", audience=audience, app=(window or {}).get("app"), window_id=window_id,
          code=code, tool=tool)
    return GuardError(message, code, retry)


def _check(root: str, audience: str, tool: str | None, window: dict, window_id: int, policy: Policy) -> None:
    verdict = classify(window, policy)
    if verdict.restricted:
        raise _refuse(root, audience, tool, window, window_id, "RESTRICTED_WINDOW",
                      "That window is restricted and cannot be mirrored")
    if audience == "agent" and not verdict.allowed:
        raise _refuse(root, audience, tool, window, window_id, "APP_NOT_ALLOWED",
                      "That app is not on this lab's agent allowlist (win-lab/winapps-policy.json)")


def list_windows(root: str, audience: str, *, tool: str | None = None) -> dict:
    """The window inventory as `audience` ("human" or "agent") may see it.

    An agent gets only allowlisted, unrestricted windows and a count of how many were withheld. A
    person gets every window, with restricted ones flagged and their titles replaced.
    """
    _audience(audience)
    result = winapps.winapps_windows()
    if audience == "agent":
        audit(root, "list", audience=audience, tool=tool)
    if not result.get("available"):
        return {**result, "withheld": 0} if audience == "agent" else result
    policy = load_policy(root)
    shown: list[dict] = []
    withheld = 0
    for window in result["windows"]:
        verdict = classify(window, policy)
        if audience == "agent":
            if verdict.allowed:
                shown.append(window)
            else:
                withheld += 1
        elif verdict.restricted:
            shown.append({**window, "title": "(restricted)", "restricted": True, "reason": verdict.reason})
        else:
            shown.append({**window, "restricted": False, "reason": None})
    reply = {**result, "windows": shown}
    if audience == "agent":
        reply["withheld"] = withheld
    return reply


def screenshot(root: str, window_id: object, audience: str, *, tool: str | None = None,
               _audit_success: bool = True) -> bytes:
    """A PNG of one window, only if it passes the policy before and after the capture."""
    _audience(audience)
    if winapps.sys.platform != "win32":
        raise GuardError("The Windows app mirror needs a Windows host", "NOT_SUPPORTED")
    try:
        hwnd = _window_id(window_id)
    except GuardError as error:
        raise _refuse(root, audience, tool, None, None, error.code, str(error)) from None
    policy = load_policy(root)
    window = winapps.window_info(hwnd)
    if window is None:
        raise _refuse(root, audience, tool, None, hwnd, "WINDOW_GONE",
                      "That window is not on screen anymore; refresh the mirror", "retry")
    _check(root, audience, tool, window, hwnd, policy)
    if audience == "agent" and window.get("width", 0) * window.get("height", 0) > AGENT_MAX_PIXELS:
        raise _refuse(root, audience, tool, window, hwnd, "CAPTURE_TOO_LARGE",
                      "That window is too large for an agent capture")
    try:
        png = _capture(hwnd)
    except winapps.WinAppError as error:
        retry = "never" if error.code == "INVALID_WINDOW" else "retry"
        raise _refuse(root, audience, tool, window, hwnd, error.code, str(error), retry) from None
    # A title can change while the capture runs; the pixels are discarded if it became restricted.
    after = winapps.window_info(hwnd)
    if after is None:
        raise _refuse(root, audience, tool, window, hwnd, "WINDOW_GONE",
                      "That window is not on screen anymore; refresh the mirror", "retry")
    # Reload: the policy file may have changed while the capture ran.
    _check(root, audience, tool, after, hwnd, load_policy(root))
    if audience == "agent" and _audit_success:
        audit(root, "screenshot", audience=audience, app=window.get("app"), window_id=hwnd, tool=tool)
    return png


def doctor(root: str, audience: str = "agent", *, tool: str | None = None) -> dict:
    """The collector's doctor probe, which never captures a window this audience may not see."""
    _audience(audience)
    policy = load_policy(root)

    def can_probe(window: dict) -> bool:
        verdict = classify(window, policy)
        return not verdict.restricted and (audience != "agent" or verdict.allowed)

    def capture(hwnd: int) -> bytes:
        # Every probe capture re-checks the current window and policy, like any other capture.
        try:
            return screenshot(root, hwnd, audience, tool=tool, _audit_success=False)
        except GuardError as error:
            raise winapps.WinAppError(str(error), error.code) from None

    result = winapps.doctor(can_probe=can_probe, capture=capture)
    if audience == "agent":
        audit(root, "doctor", audience=audience, tool=tool)
    return result
