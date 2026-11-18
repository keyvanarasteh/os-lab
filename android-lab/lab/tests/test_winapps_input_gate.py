"""Contracts for the Windows Apps Lab input gate (console/winapps_input_gate.py).

The gate decides whether an input action MAY run; it never sends input itself. Every refusal code
below is part of its public contract, and the order of the checks is asserted where it matters.
"""

import json
import os
import sys
import threading

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
    """A fake unlocked desktop where only Notepad (and 1Password, which is restricted) is allowlisted."""
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"allowedApps": ["Notepad", "1Password"]}))
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(policy))
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(tmp_path / "audit"))
    clock = [1000.0]
    state = {"windows": {k: dict(v) for k, v in WINDOWS.items()}, "locked": False, "root": str(tmp_path)}
    monkeypatch.setattr(gate.time, "time", lambda: clock[0])
    monkeypatch.setattr(winapps.sys, "platform", "win32")
    monkeypatch.setattr(winapps, "window_info", lambda hwnd: state["windows"].get(hwnd), raising=False)
    monkeypatch.setattr(winapps, "desktop_locked", lambda: state["locked"], raising=False)
    guard._reset_audit()
    gate._reset()
    state["clock"] = clock
    yield state
    gate._reset()
    guard._reset_audit()


def armed(desk, owner="panel-1", ttl=None):
    return gate.arm(desk["root"], owner, ttl) if ttl else gate.arm(desk["root"], owner)


def refused_code(call):
    with pytest.raises(guard.GuardError) as refused:
        call()
    return refused.value.code


def audit_kinds():
    return [(row["kind"], row["code"]) for row in guard.audit_rows(500)["rows"]]


# ── arming ────────────────────────────────────────────────────────────────────

def test_the_gate_starts_disarmed(desk):
    assert gate.state() == {"armed": False, "owner": None, "expiresInSec": 0, "epoch": 0}


def test_arm_sets_one_owner_with_a_default_ttl_and_is_audited(desk):
    result = armed(desk)
    assert result["armed"] is True and result["owner"] == "panel-1" and result["expiresInSec"] == 60
    assert ("arm", None) in audit_kinds()


@pytest.mark.parametrize("ttl,expected", [(5, 5), (120, 120), (9999, 300), (0.4, 5)])
def test_ttl_is_clamped_to_five_seconds_and_five_minutes(desk, ttl, expected):
    assert gate.arm(desk["root"], "panel-1", ttl)["expiresInSec"] == expected


@pytest.mark.parametrize("ttl", [0, -5, "x", None, True, float("nan"), float("inf")])
def test_a_non_positive_or_non_numeric_ttl_is_refused(desk, ttl):
    assert refused_code(lambda: gate.arm(desk["root"], "panel-1", ttl)) == "INVALID_ARGS"


@pytest.mark.parametrize("owner", ["", "  ", "a b", "x" * 65, "pa/th", "line\nbreak", None, 7, ["a"]])
def test_owner_must_be_a_short_plain_identifier(desk, owner):
    assert refused_code(lambda: gate.arm(desk["root"], owner)) == "INVALID_ARGS"


def test_a_second_owner_cannot_arm_while_armed_but_the_same_owner_extends(desk):
    armed(desk, "panel-1")
    assert refused_code(lambda: armed(desk, "agent-9")) == "INPUT_BUSY"
    desk["clock"][0] += 30
    assert armed(desk, "panel-1")["expiresInSec"] == 60


def test_arming_expires_and_the_next_owner_can_take_over(desk):
    armed(desk, "panel-1", 5)
    desk["clock"][0] += 6
    assert gate.state()["armed"] is False
    assert armed(desk, "agent-9")["owner"] == "agent-9"


def test_exactly_one_of_many_concurrent_owners_wins(desk):
    results = []

    def attempt(n):
        try:
            gate.arm(desk["root"], f"client-{n}")
            results.append("ok")
        except guard.GuardError as error:
            results.append(error.code)

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("INPUT_BUSY") == 9


# ── disarming and the panic stop ──────────────────────────────────────────────

def test_disarm_needs_the_owner_but_the_panic_stop_does_not(desk):
    armed(desk, "panel-1")
    assert refused_code(lambda: gate.disarm(desk["root"], "agent-9")) == "INPUT_BUSY"
    assert gate.state()["armed"] is True
    result = gate.panic_stop(desk["root"])
    assert result["armed"] is False and result["epoch"] == 1 and gate.state()["epoch"] == 1
    assert ("panic-stop", None) in audit_kinds()


def test_the_owner_can_disarm_and_it_is_audited(desk):
    armed(desk, "panel-1")
    assert gate.disarm(desk["root"], "panel-1")["armed"] is False
    assert ("disarm", None) in audit_kinds()


def test_the_owner_name_is_never_written_to_the_audit(desk):
    armed(desk, "secret-owner-name")
    gate.panic_stop(desk["root"])
    assert "secret-owner-name" not in json.dumps(guard.audit_rows(500))


# ── authorizing one input action ──────────────────────────────────────────────

def test_an_allowed_action_returns_the_fresh_window_and_is_audited_without_the_title(desk):
    armed(desk)
    window = gate.authorize(desk["root"], 1, "click", owner="panel-1")
    assert window["windowId"] == 1 and window["app"] == "Notepad"
    assert ("input-authorized", "click") in audit_kinds()
    assert "notes.txt" not in json.dumps(guard.audit_rows(500))


def test_nothing_is_authorized_while_disarmed_or_after_expiry(desk):
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1")) == "NOT_ARMED"
    armed(desk, "panel-1", 5)
    desk["clock"][0] += 6
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1")) == "NOT_ARMED"


def test_another_owner_is_refused(desk):
    armed(desk, "panel-1")
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="agent-9")) == "INPUT_BUSY"


def test_a_locked_desktop_refuses_input(desk):
    armed(desk)
    desk["locked"] = True
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1")) == "SCREEN_LOCKED"


def test_input_is_default_deny_even_for_a_person(desk, monkeypatch, tmp_path):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 2, "click", owner="panel-1")) == "APP_NOT_ALLOWED"
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(tmp_path / "absent.json"))
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1")) == "APP_NOT_ALLOWED"


def test_a_restricted_window_is_refused_even_when_its_app_is_allowlisted(desk):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 3, "click", owner="panel-1")) == "RESTRICTED_WINDOW"


def test_the_window_is_read_again_at_the_moment_of_the_action(desk):
    armed(desk)
    desk["windows"][1]["title"] = "notes [InPrivate]"
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1")) == "RESTRICTED_WINDOW"
    del desk["windows"][1]
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1")) == "WINDOW_GONE"


@pytest.mark.parametrize("kind,key", [("paste", None), ("key", "Enter"), ("key", " return ")])
def test_submit_class_input_needs_an_explicit_true_confirm(desk, kind, key):
    armed(desk)
    call = lambda confirm: gate.authorize(desk["root"], 1, kind, owner="panel-1", key=key, confirm=confirm)
    assert refused_code(lambda: call(False)) == "CONFIRM_REQUIRED"
    assert refused_code(lambda: call("yes")) == "CONFIRM_REQUIRED"
    assert call(True)["windowId"] == 1


@pytest.mark.parametrize("kind,key", [("click", None), ("double-click", None), ("right-click", None),
                                      ("type", None), ("scroll", None), ("key", "Tab")])
def test_ordinary_input_needs_no_confirm(desk, kind, key):
    armed(desk)
    assert gate.authorize(desk["root"], 1, kind, owner="panel-1", key=key)["windowId"] == 1


@pytest.mark.parametrize("kind,key", [("drag", None), ("", None), (None, None), ("key", None), ("key", "")])
def test_unknown_kinds_and_a_key_action_without_a_key_are_invalid(desk, kind, key):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 1, kind, owner="panel-1", key=key)) == "INVALID_INPUT"


@pytest.mark.parametrize("bad", [True, 1.5, -3, "12abc", 10 ** 30, None, 0])
def test_a_bad_window_id_is_refused_before_anything_else(desk, bad):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], bad, "click", owner="panel-1")) == "INVALID_WINDOW"


def test_the_checks_run_in_order_so_an_unarmed_locked_restricted_request_says_not_armed(desk):
    desk["locked"] = True
    assert refused_code(lambda: gate.authorize(desk["root"], 3, "paste", owner="x1")) == "NOT_ARMED"


def test_every_refusal_is_audited_with_its_code(desk):
    refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1"))
    armed(desk)
    refused_code(lambda: gate.authorize(desk["root"], 3, "click", owner="panel-1"))
    kinds = audit_kinds()
    assert ("refused", "NOT_ARMED") in kinds and ("refused", "RESTRICTED_WINDOW") in kinds


def test_a_panic_stop_ends_an_armed_session_for_authorize_too(desk):
    armed(desk)
    gate.panic_stop(desk["root"])
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1")) == "NOT_ARMED"


def test_an_unknown_audience_is_refused(desk):
    armed(desk)
    assert refused_code(lambda: gate.authorize(desk["root"], 1, "click", owner="panel-1", audience="Agent")) == "INVALID_AUDIENCE"
