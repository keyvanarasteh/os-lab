"""Contracts for the Windows Apps Lab input gate (console/winapps_input_gate.py).

The gate decides whether an input action MAY run; it never sends input itself. It has no arm state
of its own: arming, the owner and the timeout are the single control lock in console/winapps.py,
and the gate's arm/disarm/panic are audited doors to that lock. Every refusal code below is part of
its public contract, and the order of the checks is asserted where it matters.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "console")))

import winapps
import winapps_guard as guard
import winapps_input_gate as gate

WINDOWS = {
    1: {"windowId": 1, "app": "Notepad", "title": "notes.txt", "width": 10, "height": 10},
    2: {"windowId": 2, "app": "Calc", "title": "Calculator", "width": 10, "height": 10},
    3: {"windowId": 3, "app": "1Password", "title": "Vault", "width": 10, "height": 10},
}


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A fake unlocked Windows desktop where only Notepad (and 1Password, which is restricted) is allowlisted."""
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"allowedApps": ["Notepad", "1Password"]}))
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(policy))
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(tmp_path / "audit"))
    clock = [1000.0]
    state = {"windows": {k: dict(v) for k, v in WINDOWS.items()}, "locked": False, "root": str(tmp_path),
             "clock": clock}
    monkeypatch.setattr(winapps.sys, "platform", "win32")
    monkeypatch.setattr(winapps, "_user32", object())  # arming only checks that the native layer exists
    monkeypatch.setattr(winapps.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(winapps, "_CONTROL_STATE", {"armed": False, "armedAt": 0.0, "owner": None})
    monkeypatch.setattr(winapps, "_WINAPPS_STREAM_EPOCH", 0)
    monkeypatch.setattr(winapps, "window_info", lambda hwnd: state["windows"].get(hwnd))
    monkeypatch.setattr(winapps, "desktop_locked", lambda: state["locked"])
    guard._reset_audit()
    yield state
    guard._reset_audit()


def armed(desk, owner="panel-1"):
    return gate.arm(desk["root"], owner)


def refused_code(call):
    with pytest.raises(guard.GuardError) as refused:
        call()
    return refused.value.code


def audit_kinds():
    return [(row["kind"], row["code"]) for row in guard.audit_rows(500)["rows"]]


# ── arming: one lock, shared with console/winapps.py ──────────────────────────

def test_the_gate_starts_disarmed_and_never_reports_the_owner(desk):
    assert gate.state() == {"armed": False, "expiresInSec": 0, "epoch": 0, "allowlistRequired": True,
                            "desktopLocked": False}


def test_arm_is_the_control_lock_and_is_audited(desk):
    result = armed(desk)
    assert result["armed"] is True and result["owner"] == "panel-1"
    assert result["expiresInSec"] == winapps.CONTROL_TIMEOUT_SECONDS
    assert result["gate"]["armed"] is True and "owner" not in result["gate"]
    assert winapps.winapps_control_state()["armed"] is True  # the same state the send path checks
    assert ("arm", None) in audit_kinds()


@pytest.mark.parametrize("owner", ["", "a b", "x" * 65, "pa/th", "line\nbreak", None, 7, ["a"]])
def test_owner_must_be_a_short_plain_identifier(desk, owner):
    assert refused_code(lambda: gate.arm(desk["root"], owner)) == "WINAPP_ERROR"
    assert winapps.winapps_control_state()["armed"] is False


def test_a_second_owner_cannot_arm_while_armed_but_the_same_owner_extends(desk):
    armed(desk, "panel-1")
    assert refused_code(lambda: armed(desk, "agent-9")) == "INPUT_BUSY"
    desk["clock"][0] += 30
    assert armed(desk, "panel-1")["expiresInSec"] == winapps.CONTROL_TIMEOUT_SECONDS


def test_arming_expires_and_the_next_owner_can_take_over(desk):
    armed(desk, "panel-1")
    desk["clock"][0] += winapps.CONTROL_TIMEOUT_SECONDS + 1
    assert gate.state()["armed"] is False
    assert armed(desk, "agent-9")["owner"] == "agent-9"


def test_arming_off_windows_is_refused(desk, monkeypatch):
    monkeypatch.setattr(winapps.sys, "platform", "linux")
    assert refused_code(lambda: armed(desk)) == "WINAPP_ERROR"


# ── disarming and the panic stop ──────────────────────────────────────────────

def test_disarm_needs_the_owner_but_the_panic_stop_does_not(desk):
    armed(desk, "panel-1")
    assert refused_code(lambda: gate.disarm(desk["root"], "agent-9")) == "INPUT_BUSY"
    assert gate.state()["armed"] is True
    result = gate.panic_stop(desk["root"])
    assert result["disarmed"] is True and result["gate"]["armed"] is False and result["gate"]["epoch"] == 1
    assert ("panic-stop", None) in audit_kinds()


def test_the_owner_can_disarm_and_it_is_audited(desk):
    armed(desk, "panel-1")
    assert gate.disarm(desk["root"], "panel-1")["armed"] is False
    assert ("disarm", None) in audit_kinds()


def test_the_owner_name_is_never_written_to_the_gate_audit(desk):
    armed(desk, "secret-owner-name")
    gate.panic_stop(desk["root"])
    assert "secret-owner-name" not in json.dumps(guard.audit_rows(500))


# ── authorizing one input action ──────────────────────────────────────────────

def test_an_allowed_action_returns_the_fresh_window_and_is_audited_without_the_title(desk):
    armed(desk)
    window = gate.authorize(desk["root"], 1, "click")
    assert window["windowId"] == 1 and window["app"] == "Notepad"
    assert ("input-authorized", "click") in audit_kinds()
    assert "notes.txt" not in json.dumps(guard.audit_rows(500))


def test_nothing_is_authorized_while_disarmed_or_after_expiry(desk):
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "NOT_ARMED"
    armed(desk)
    desk["clock"][0] += winapps.CONTROL_TIMEOUT_SECONDS + 1
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "NOT_ARMED"


def test_a_disarm_through_the_console_lock_also_stops_the_gate(desk):
    armed(desk, "panel-1")
    winapps.winapps_control_arm(False, "panel-1")  # the dashboard's /control route
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "NOT_ARMED"


def test_a_locked_desktop_refuses_input(desk):
    armed(desk)
    desk["locked"] = True
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "SCREEN_LOCKED"


def test_input_is_default_deny_even_for_a_person(desk, monkeypatch, tmp_path):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 2, "click")) == "APP_NOT_ALLOWED"
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(tmp_path / "absent.json"))
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "APP_NOT_ALLOWED"


def test_a_restricted_window_is_refused_even_when_its_app_is_allowlisted(desk):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 3, "click")) == "RESTRICTED_WINDOW"


def test_the_window_is_read_again_at_the_moment_of_the_action(desk):
    armed(desk)
    desk["windows"][1]["title"] = "notes [InPrivate]"
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "RESTRICTED_WINDOW"
    del desk["windows"][1]
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "WINDOW_GONE"


@pytest.mark.parametrize("kind,key", [("paste", None), ("key", "Enter"), ("key", " return ")])
def test_submit_class_input_needs_an_explicit_true_confirm(desk, kind, key):
    armed(desk)
    call = lambda confirm: gate.authorize(desk["root"], 1, kind, key=key, confirm=confirm)
    assert refused_code(lambda: call(False)) == "CONFIRM_REQUIRED"
    assert refused_code(lambda: call("yes")) == "CONFIRM_REQUIRED"
    assert call(True)["windowId"] == 1


@pytest.mark.parametrize("kind,key", [("click", None), ("double_click", None), ("right_click", None),
                                      ("double-click", None), ("type", None), ("scroll", None), ("key", "Tab")])
def test_ordinary_input_needs_no_confirm_from_the_gate(desk, kind, key):
    armed(desk)
    assert gate.authorize(desk["root"], 1, kind, key=key)["windowId"] == 1


@pytest.mark.parametrize("kind,key", [("drag", None), ("", None), (None, None), ("key", None), ("key", "")])
def test_unknown_kinds_and_a_key_action_without_a_key_are_invalid(desk, kind, key):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 1, kind, key=key)) == "INVALID_INPUT"


@pytest.mark.parametrize("bad", [True, 1.5, -3, "12abc", 10 ** 30, None, 0])
def test_a_bad_window_id_is_refused_before_anything_else(desk, bad):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], bad, "click")) == "INVALID_WINDOW"


def test_the_checks_run_in_order_so_an_unarmed_locked_restricted_request_says_not_armed(desk):
    desk["locked"] = True
    assert refused_code(lambda: gate.authorize(desk["root"], 3, "paste")) == "NOT_ARMED"


def test_every_refusal_is_audited_with_its_code(desk):
    refused_code(lambda: gate.authorize(desk["root"], 1, "click"))
    armed(desk)
    refused_code(lambda: gate.authorize(desk["root"], 3, "click"))
    kinds = audit_kinds()
    assert ("refused", "NOT_ARMED") in kinds and ("refused", "RESTRICTED_WINDOW") in kinds


def test_a_panic_stop_ends_an_armed_session_for_authorize_too(desk):
    armed(desk)
    gate.panic_stop(desk["root"])
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "NOT_ARMED"


def test_an_unknown_audience_is_refused(desk):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", audience="Agent")) == "INVALID_AUDIENCE"


def test_off_windows_authorize_says_not_supported_and_is_audited(desk, monkeypatch):
    monkeypatch.setattr(winapps.sys, "platform", "linux")
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click")) == "NOT_SUPPORTED"
    assert ("refused", "NOT_SUPPORTED") in audit_kinds()


@pytest.mark.parametrize("kind", [["click"], {"k": 1}, 7, b"click"])
def test_a_non_string_kind_is_refused_and_audited_not_a_crash(desk, kind):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 1, kind)) == "INVALID_INPUT"
    assert ("refused", "INVALID_INPUT") in audit_kinds()


@pytest.mark.parametrize("owner", [None, "agent-9"])
def test_a_disarm_without_the_owner_cannot_stop_another_session(desk, owner):
    armed(desk, "panel-1")
    assert refused_code(lambda: gate.disarm(desk["root"], owner)) == "INPUT_BUSY"
    assert winapps.winapps_control_state()["armed"] is True
