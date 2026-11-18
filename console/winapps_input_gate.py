"""Input gate for the Windows Apps Lab (WINMIR-11a, 11b, 11c, 11d, 11e).

This module decides whether ONE input action may run. It never sends input itself: whatever code
later calls `SendInput` must first call `authorize()` and must stop on a `GuardError`.

An action is authorized only when all of these hold, checked in this order so the cheapest and most
fundamental reason is the one reported:

1. the audience, input kind and window id are well formed        (INVALID_AUDIENCE / INVALID_INPUT / INVALID_WINDOW)
2. the gate is armed, and it is armed for this owner             (NOT_ARMED / INPUT_BUSY)
3. the desktop is not locked or showing a secure prompt          (SCREEN_LOCKED)
4. the window is on screen right now                             (WINDOW_GONE)
5. the window is not restricted and its app is allowlisted       (RESTRICTED_WINDOW / APP_NOT_ALLOWED)
6. submit-class input carries an explicit `confirm is True`      (CONFIRM_REQUIRED)

The allowlist is default-deny for input even for a person: an empty or missing policy refuses every
action. Arming expires on its own, has exactly one owner, and the panic stop ends it at once.

Honest limit: the gate is a guard against mistakes, not against a hostile local user. Whoever can
reach the local HTTP address with the X-OSLab header can arm it.
"""

from __future__ import annotations

import math
import re
import threading
import time

import winapps
import winapps_guard as guard

DEFAULT_TTL_SECONDS = 60
MIN_TTL_SECONDS = 5
MAX_TTL_SECONDS = 300
INPUT_KINDS = frozenset({"click", "double-click", "right-click", "type", "key", "paste", "scroll"})
_SUBMIT_KEYS = frozenset({"enter", "return"})  # a paste or Enter can submit or overwrite
_OWNER = re.compile(r"[A-Za-z0-9._-]{1,64}")

_LOCK = threading.Lock()
_STATE: dict = {"owner": None, "expires_at": 0.0, "epoch": 0}


def _reset() -> None:
    """Back to a fresh, disarmed gate (tests)."""
    with _LOCK:
        _STATE.update(owner=None, expires_at=0.0, epoch=0)


def _live_owner(now: float) -> str | None:
    """The current owner, or None once arming has expired. Call with the lock held."""
    return _STATE["owner"] if _STATE["owner"] and now < _STATE["expires_at"] else None


def _snapshot(now: float) -> dict:
    owner = _live_owner(now)
    return {"armed": owner is not None, "owner": owner,
            "expiresInSec": max(0, math.ceil(_STATE["expires_at"] - now)) if owner else 0,
            "epoch": _STATE["epoch"]}


def state() -> dict:
    """Armed or not, who owns it, seconds left, and the panic-stop epoch (streams watch it)."""
    with _LOCK:
        return _snapshot(time.time())


def _refuse(root: str, audience: str, code: str, message: str, *, window: dict | None = None,
            window_id: int | None = None, retry: str = "never") -> guard.GuardError:
    guard.audit(root, "refused", audience=audience, app=(window or {}).get("app"), window_id=window_id, code=code)
    return guard.GuardError(message, code, retry)


def _owner(root: str, value: object) -> str:
    if not isinstance(value, str) or not _OWNER.fullmatch(value):
        raise _refuse(root, "human", "INVALID_ARGS", "owner must be 1-64 letters, digits, dots, dashes or underscores")
    return value


def _ttl(root: str, value: object) -> float:
    if (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
            or value <= 0):
        raise _refuse(root, "human", "INVALID_ARGS", "ttl must be a positive number of seconds")
    return float(min(MAX_TTL_SECONDS, max(MIN_TTL_SECONDS, value)))


def arm(root: str, owner: object, ttl: object = DEFAULT_TTL_SECONDS) -> dict:
    """Arm for one owner. The same owner extends; another owner is refused until it expires or is stopped."""
    name = _owner(root, owner)
    seconds = _ttl(root, ttl)
    with _LOCK:
        now = time.time()
        live = _live_owner(now)
        busy = live is not None and live != name
        if not busy:
            _STATE.update(owner=name, expires_at=now + seconds)
        result = _snapshot(now)
    if busy:
        raise _refuse(root, "human", "INPUT_BUSY", "Another client holds input control; wait for it to "
                      "expire or use the panic stop")
    guard.audit(root, "arm", audience="human")  # the owner name is deliberately not recorded
    return result


def disarm(root: str, owner: object = None) -> dict:
    """End arming. When an owner is given it must be the current one; the panic stop needs none."""
    name = None if owner is None else _owner(root, owner)
    with _LOCK:
        now = time.time()
        live = _live_owner(now)
        busy = name is not None and live is not None and name != live
        if not busy:
            _STATE.update(owner=None, expires_at=0.0)
        result = _snapshot(now)
    if busy:
        raise _refuse(root, "human", "INPUT_BUSY", "Input control is held by another client")
    guard.audit(root, "disarm", audience="human")
    return result


def panic_stop(root: str) -> dict:
    """Disarm whoever holds control and bump the epoch so every running stream can end itself."""
    with _LOCK:
        _STATE.update(owner=None, expires_at=0.0, epoch=_STATE["epoch"] + 1)
        result = _snapshot(time.time())
    guard.audit(root, "panic-stop", audience="human")
    return result


def authorize(root: str, window_id: object, kind: object, *, owner: object, confirm: object = False,
              key: object = None, audience: str = "human") -> dict:
    """The window (read fresh) when this input action may run; raises GuardError otherwise."""
    guard.require_audience(audience)
    if winapps.sys.platform != "win32":
        raise guard.GuardError("The Windows app mirror needs a Windows host", "NOT_SUPPORTED")
    if kind not in INPUT_KINDS or (kind == "key" and not (isinstance(key, str) and key.strip())):
        raise _refuse(root, audience, "INVALID_INPUT", "Unknown input kind, or a key action without a key")
    try:
        hwnd = guard.parse_window_id(window_id)
    except guard.GuardError as error:
        raise _refuse(root, audience, error.code, str(error)) from None
    if not isinstance(owner, str):
        raise _refuse(root, audience, "INVALID_ARGS", "owner must be a string", window_id=hwnd)
    with _LOCK:
        live = _live_owner(time.time())
    if live is None:
        raise _refuse(root, audience, "NOT_ARMED", "Input control is not armed", window_id=hwnd, retry="retry")
    if owner != live:
        raise _refuse(root, audience, "INPUT_BUSY", "Another client holds input control", window_id=hwnd)
    if winapps.desktop_locked() is True:
        raise _refuse(root, audience, "SCREEN_LOCKED", "The screen is locked or showing a secure prompt",
                      window_id=hwnd, retry="retry")
    window = winapps.window_info(hwnd)
    if window is None:
        raise _refuse(root, audience, "WINDOW_GONE", "That window is not on screen anymore; refresh the mirror",
                      window_id=hwnd, retry="retry")
    verdict = guard.classify(window, guard.load_policy(root))
    if verdict.restricted:
        raise _refuse(root, audience, "RESTRICTED_WINDOW", "That window is restricted and cannot be driven",
                      window=window, window_id=hwnd)
    if not verdict.allowed:
        raise _refuse(root, audience, "APP_NOT_ALLOWED", "That app is not on the allowlist, and input is "
                      "refused unless it is (win-lab/winapps-policy.json)", window=window, window_id=hwnd)
    key_name = key.strip().casefold() if isinstance(key, str) else ""
    submits = kind == "paste" or (kind == "key" and key_name in _SUBMIT_KEYS)
    if submits and confirm is not True:
        raise _refuse(root, audience, "CONFIRM_REQUIRED", "This can submit or overwrite: send confirm:true "
                      "from an explicit dialog, even while armed", window=window, window_id=hwnd)
    guard.audit(root, "input-authorized", audience=audience, app=window.get("app"), window_id=hwnd, code=str(kind))
    return window
