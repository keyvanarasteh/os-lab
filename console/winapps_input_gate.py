"""Input gate for the Windows Apps Lab (WINMIR-11a, 11b, 11c, 11d, 11e).

This module decides whether ONE input action may run. It never sends input itself: the console's
click and input routes call `authorize()` before `winapps.winapps_control_click` /
`winapps_control_input`, and stop on a `GuardError`.

There is exactly one arm state: the single-owner, expiring control lock in `console/winapps.py`
(#316/#318). `arm`, `disarm` and `panic_stop` here are thin, audited doors to it, and the send path
re-checks that lock and the explicit confirmation under its own mutex immediately before
`SendInput`, so a disarm or panic stop that lands while `authorize()` runs still stops the action.

`authorize()` adds what the control lock does not know about, in this order so the cheapest and
most fundamental reason is reported:

1. the audience, input kind and window id are well formed        (INVALID_AUDIENCE / INVALID_INPUT / INVALID_WINDOW)
2. the control lock is armed                                     (NOT_ARMED; the owner is checked again at send time)
3. the desktop is not locked or showing a secure prompt          (SCREEN_LOCKED)
4. the window is on screen right now                             (WINDOW_GONE)
5. the window is not restricted and its app is allowlisted       (RESTRICTED_WINDOW / APP_NOT_ALLOWED)
6. submit-class input carries an explicit `confirm is True`      (CONFIRM_REQUIRED)

The allowlist is default-deny for input even for a person (#288, 11d): an empty or missing policy
refuses every action until the app is listed in `win-lab/winapps-policy.json`.

Honest limit: the gate is a guard against mistakes, not against a hostile local user. Whoever can
reach the local HTTP address with the X-OSLab header can arm it.
"""

from __future__ import annotations

import threading

import winapps
import winapps_guard as guard

# Accepted kinds: the console's own (master) names and the hyphenated names of the first draft.
INPUT_KINDS = frozenset({"click", "double_click", "right_click", "scroll", "type", "key", "paste",
                         "double-click", "right-click"})
_SUBMIT_KEYS = frozenset({"enter", "return"})  # a paste or Enter can submit or overwrite
# One transition at a time, each with its audit row, so the audit order is the transition order.
_TRANSITION = threading.Lock()


def _refuse(root: str, audience: str, code: str, message: str, *, window: dict | None = None,
            window_id: int | None = None, retry: str = "never") -> guard.GuardError:
    guard.audit(root, "refused", audience=audience, app=(window or {}).get("app"), window_id=window_id, code=code)
    return guard.GuardError(message, code, retry)


def state() -> dict:
    """The control lock as the gate reports it: armed, seconds left, the panic-stop epoch. No owner."""
    control = winapps.winapps_control_state()
    return {"armed": bool(control.get("armed")), "expiresInSec": int(control.get("expiresInSec") or 0),
            "epoch": int(getattr(winapps, "_WINAPPS_STREAM_EPOCH", 0)), "allowlistRequired": True,
            "desktopLocked": winapps.desktop_locked()}


def _control_error(root: str, error: "winapps.WinAppError") -> guard.GuardError:
    code = "INPUT_BUSY" if error.code in ("ARMED_BY_OTHER", "INPUT_BUSY") else error.code
    return _refuse(root, "human", code, str(error))


def arm(root: str, owner: object) -> dict:
    """Arm the control lock for one owner; the lock's own timeout applies. Returns the control state."""
    with _TRANSITION:
        try:
            result = winapps.winapps_control_arm(True, owner if isinstance(owner, str) else None)
        except winapps.WinAppError as error:
            raise _control_error(root, error) from None
        guard.audit(root, "arm", audience="human")  # the owner name is deliberately not recorded
    return {**result, "gate": state()}


def disarm(root: str, owner: object = None) -> dict:
    """Disarm; only the current owner may: a missing or other owner gets INPUT_BUSY while armed
    (the panic stop is the only ownerless way to stop)."""
    with _TRANSITION:
        try:
            result = winapps.winapps_control_arm(False, owner if isinstance(owner, str) else None)
        except winapps.WinAppError as error:
            raise _control_error(root, error) from None
        guard.audit(root, "disarm", audience="human")
    return {**result, "gate": state()}


def panic_stop(root: str) -> dict:
    """Disarm whoever holds control and end every running mirror stream at once."""
    with _TRANSITION:
        result = winapps.winapps_panic_stop()
        guard.audit(root, "panic-stop", audience="human")
    return {**result, "gate": state()}


def authorize(root: str, window_id: object, kind: object, *, confirm: object = False,
              key: object = None, audience: str = "human") -> dict:
    """The window (read fresh) when this input action may run; raises GuardError otherwise."""
    guard.require_audience(audience)  # a programming error (callers pass a constant), like the guard's
    if winapps.sys.platform != "win32":
        raise _refuse(root, audience, "NOT_SUPPORTED", "The Windows app mirror needs a Windows host")
    if not isinstance(kind, str) or kind not in INPUT_KINDS or (kind == "key" and not (isinstance(key, str) and key.strip())):
        raise _refuse(root, audience, "INVALID_INPUT", "Unknown input kind, or a key action without a key")
    try:
        hwnd = guard.parse_window_id(window_id)
    except guard.GuardError as error:
        raise _refuse(root, audience, error.code, str(error)) from None
    if not winapps.winapps_control_state().get("armed"):
        raise _refuse(root, audience, "NOT_ARMED", "Input control is not armed", window_id=hwnd, retry="retry")
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
