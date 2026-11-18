"""Contracts for the Windows Apps Lab policy gate (console/winapps_guard.py).

The guard has no Win32 dependency, so these run the same on any host.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "console")))

import winapps_guard as guard


def write_policy(tmp_path, monkeypatch, data=None, raw=None):
    path = tmp_path / "policy.json"
    path.write_bytes(raw if raw is not None else json.dumps(data).encode("utf-8"))
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(path))
    return path


def win(app, title="Untitled"):
    return {"windowId": 7, "app": app, "title": title}


def verdict(tmp_path, monkeypatch, window, **policy):
    write_policy(tmp_path, monkeypatch, policy)
    return guard.classify(window, guard.load_policy(str(tmp_path)))


# ── Task 1: policy and classification ────────────────────────────────────────

def test_missing_policy_means_nothing_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(tmp_path / "absent.json"))
    policy = guard.load_policy(str(tmp_path))
    assert policy.exists is False and policy.error is None
    assert policy.allowed == frozenset()


def test_allowlist_matches_case_insensitively_and_ignores_exe_and_spaces(tmp_path, monkeypatch):
    v = verdict(tmp_path, monkeypatch, win(" notepad.EXE "), allowedApps=["Notepad"])
    assert v.allowed is True and v.restricted is False and v.reason is None


def test_unlisted_app_is_not_allowlisted(tmp_path, monkeypatch):
    v = verdict(tmp_path, monkeypatch, win("Calc"), allowedApps=["Notepad"])
    assert (v.restricted, v.allowed, v.reason) == (False, False, "not-allowlisted")


def test_blank_entries_never_match_blank_apps(tmp_path, monkeypatch):
    v = verdict(tmp_path, monkeypatch, win(""), allowedApps=["", "  ", ".exe"])
    assert v.allowed is False


def test_builtin_password_managers_are_restricted_even_if_allowlisted(tmp_path, monkeypatch):
    v = verdict(tmp_path, monkeypatch, win("1Password"), allowedApps=["1Password"])
    assert (v.restricted, v.allowed, v.reason) == (True, False, "password-manager")


@pytest.mark.parametrize("title,reason", [
    ("New tab - [InPrivate] - Edge", "private-window"),
    ("New Incognito tab - Chrome", "private-window"),
    ("Mozilla Firefox Private Browsing", "private-window"),
    ("Brave Private Window", "private-window"),
    ("My Online Banking", "banking-hint"),
    ("Internet Banking login", "banking-hint"),
])
def test_builtin_sensitive_titles_are_restricted(tmp_path, monkeypatch, title, reason):
    v = verdict(tmp_path, monkeypatch, win("msedge", title), allowedApps=["msedge"])
    assert (v.restricted, v.allowed, v.reason) == (True, False, reason)


def test_policy_can_add_restrictions_but_not_remove_defaults(tmp_path, monkeypatch):
    policy = dict(allowedApps=["MyVault", "msedge", "1Password"], restrictedApps=["MyVault"],
                  restrictedTitles=["secret"])
    assert verdict(tmp_path, monkeypatch, win("MyVault"), **policy).reason == "policy-app"
    assert verdict(tmp_path, monkeypatch, win("msedge", "my SECRET plan"), **policy).reason == "policy-title"
    assert verdict(tmp_path, monkeypatch, win("1Password"), **policy).reason == "password-manager"


@pytest.mark.parametrize("title", ["İNTERNET BANKACILIĞI", "Internet Bankacılığı", "internet bankaciligi"])
def test_turkish_dotted_capital_i_matches_title_hints(tmp_path, monkeypatch, title):
    v = verdict(tmp_path, monkeypatch, win("msedge", title), restrictedTitles=["internet bankacılığı"])
    assert v.restricted is True and v.reason == "policy-title"


@pytest.mark.parametrize("raw", [
    b"not json",
    json.dumps({"allowedApps": "Notepad"}).encode(),
    json.dumps({"allowedApps": [1, None, ["x"]]}).encode(),
    json.dumps({"restrictedTitles": {"a": 1}}).encode(),
    json.dumps([]).encode(),
])
def test_malformed_policy_fails_closed_with_policy_error(tmp_path, monkeypatch, raw):
    write_policy(tmp_path, monkeypatch, raw=raw)
    policy = guard.load_policy(str(tmp_path))
    assert policy.allowed == frozenset() and policy.error
    assert guard.classify(win("Notepad"), policy).allowed is False


def test_a_utf8_bom_policy_still_loads(tmp_path, monkeypatch):
    write_policy(tmp_path, monkeypatch, raw=b"\xef\xbb\xbf" + json.dumps({"allowedApps": ["Notepad"]}).encode())
    policy = guard.load_policy(str(tmp_path))
    assert policy.error is None and policy.allowed == frozenset({"notepad"})


def test_ten_thousand_allowlist_entries_load(tmp_path, monkeypatch):
    write_policy(tmp_path, monkeypatch, {"allowedApps": [f"app{i}" for i in range(10_000)]})
    policy = guard.load_policy(str(tmp_path))
    assert policy.error is None and len(policy.allowed) == 10_000


def test_policy_is_reloaded_when_the_file_changes(tmp_path, monkeypatch):
    path = write_policy(tmp_path, monkeypatch, {"allowedApps": ["a"]})
    assert guard.load_policy(str(tmp_path)).allowed == frozenset({"a"})
    path.write_text(json.dumps({"allowedApps": ["b"]}))
    later = path.stat().st_mtime + 10
    os.utime(path, (later, later))
    assert guard.load_policy(str(tmp_path)).allowed == frozenset({"b"})


def test_policy_summary_reports_counts_without_names(tmp_path, monkeypatch):
    path = write_policy(tmp_path, monkeypatch, {"allowedApps": ["Notepad", "Calc"], "restrictedApps": ["V"],
                                                "restrictedTitles": ["x", "y", "z"]})
    summary = guard.policy_summary(str(tmp_path))
    assert summary == {"allowedApps": 2, "restrictedApps": 1, "restrictedTitles": 3,
                       "policyError": None, "path": str(path), "exists": True}
    assert "Notepad" not in json.dumps(summary)


# ── Task 2: audit ─────────────────────────────────────────────────────────────

import threading


@pytest.fixture
def audit_dir(tmp_path, monkeypatch):
    folder = tmp_path / "audit"
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(folder))
    guard._reset_audit()
    yield folder
    guard._reset_audit()


def rows(limit=500):
    return guard.audit_rows(limit)["rows"]


def test_audit_row_has_seq_time_and_no_title_or_pixels(audit_dir):
    guard.audit(None, "list", audience="agent", app="Notepad", window_id=1, tool="winapps_apps")
    row = rows()[-1]
    assert set(row) == {"seq", "time", "audience", "kind", "app", "windowId", "code", "tool", "count"}
    assert row["seq"] == 1 and row["count"] == 1 and row["windowId"] == 1
    with pytest.raises(TypeError):
        guard.audit(None, "list", audience="agent", title="secret")  # titles cannot be passed at all


def test_identical_rows_within_60_seconds_coalesce_with_count(audit_dir, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    for _ in range(20):
        guard.audit(None, "refused", audience="human", app="1Password", window_id=5, code="RESTRICTED_WINDOW")
        now[0] += 1
    assert len(rows()) == 1 and rows()[0]["count"] == 20
    now[0] = 1061.5
    guard.audit(None, "refused", audience="human", app="1Password", window_id=5, code="RESTRICTED_WINDOW")
    assert len(rows()) == 2


def test_ring_never_exceeds_500_rows(audit_dir):
    for i in range(650):
        guard.audit(None, "list", audience="agent", window_id=i)
    assert len(rows(10_000)) == 500 and rows(10_000)[-1]["windowId"] == 649


def test_audit_writes_one_jsonl_line_per_new_row_under_the_audit_dir(audit_dir, tmp_path):
    guard.audit(str(tmp_path), "list", audience="agent", window_id=1)
    guard.audit(str(tmp_path), "screenshot", audience="agent", window_id=1)
    files = list(audit_dir.glob("winapps-audit-*.jsonl"))
    assert len(files) == 1
    lines = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    assert [line["kind"] for line in lines] == ["list", "screenshot"]


def test_audit_never_raises_when_the_directory_is_unwritable(tmp_path, monkeypatch):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(blocker))
    guard._reset_audit()
    guard.audit(str(tmp_path), "list", audience="agent", window_id=1)
    assert len(rows()) == 1


def test_concurrent_audit_keeps_unique_consecutive_seq(audit_dir):
    def work(base):
        for i in range(50):
            guard.audit(None, "list", audience="agent", window_id=base * 1000 + i)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(row["seq"] for row in rows()) == list(range(1, 401))


# ── Task 3: guarded facade ────────────────────────────────────────────────────

import winapps

PNG = b"\x89PNG\r\n\x1a\nfake"
WINDOWS = [
    {"windowId": 1, "app": "Notepad", "title": "notes.txt", "width": 10, "height": 10},
    {"windowId": 2, "app": "Calc", "title": "Calculator", "width": 10, "height": 10},
    {"windowId": 3, "app": "1Password", "title": "Vault", "width": 10, "height": 10},
    {"windowId": 4, "app": "msedge", "title": "News [InPrivate]", "width": 10, "height": 10},
]


@pytest.fixture
def world(tmp_path, monkeypatch, audit_dir):
    """A fake desktop: Notepad and 1Password are allowlisted, 1Password and the InPrivate tab restricted."""
    write_policy(tmp_path, monkeypatch, {"allowedApps": ["Notepad", "1Password"]})
    state = {"captures": [], "info": lambda hwnd: next((dict(w) for w in WINDOWS if w["windowId"] == hwnd), None)}
    monkeypatch.setattr(winapps, "winapps_windows",
                        lambda: {"available": True, "reason": None, "windows": [dict(w) for w in WINDOWS]})
    monkeypatch.setattr(winapps, "window_info", lambda hwnd: state["info"](hwnd), raising=False)
    monkeypatch.setattr(winapps, "winapps_window_screenshot", lambda hwnd: state["captures"].append(hwnd) or PNG)
    monkeypatch.setattr(winapps.sys, "platform", "win32")
    state["root"] = str(tmp_path)
    return state


def test_agent_list_returns_only_allowlisted_unrestricted_windows_and_a_withheld_count(world):
    result = guard.list_windows(world["root"], "agent", tool="winapps_apps")
    assert [w["windowId"] for w in result["windows"]] == [1]
    assert result["withheld"] == 3 and result["available"] is True


def test_agent_list_with_empty_policy_returns_nothing_and_counts_all_as_withheld(world, monkeypatch, tmp_path):
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(tmp_path / "absent.json"))
    result = guard.list_windows(world["root"], "agent")
    assert result["windows"] == [] and result["withheld"] == 4


def test_human_list_keeps_restricted_windows_but_redacts_title_and_flags_them(world):
    result = guard.list_windows(world["root"], "human")
    by_id = {w["windowId"]: w for w in result["windows"]}
    assert set(by_id) == {1, 2, 3, 4}
    assert by_id[3]["restricted"] is True and by_id[3]["reason"] == "password-manager"
    assert by_id[3]["title"] == "(restricted)" and by_id[3]["app"] == "1Password"
    assert by_id[4]["reason"] == "private-window" and by_id[4]["title"] == "(restricted)"
    assert by_id[1]["restricted"] is False and by_id[1]["title"] == "notes.txt"
    assert "withheld" not in result


@pytest.mark.parametrize("audience", ["human", "agent"])
@pytest.mark.parametrize("window_id", [3, 4])
def test_screenshot_refuses_restricted_windows_for_everyone(world, audience, window_id):
    with pytest.raises(guard.GuardError) as refused:
        guard.screenshot(world["root"], window_id, audience)
    assert refused.value.code == "RESTRICTED_WINDOW" and world["captures"] == []


def test_screenshot_refuses_non_allowlisted_apps_for_agents_only(world):
    with pytest.raises(guard.GuardError) as refused:
        guard.screenshot(world["root"], 2, "agent")
    assert refused.value.code == "APP_NOT_ALLOWED"
    assert guard.screenshot(world["root"], 2, "human") == PNG
    assert guard.screenshot(world["root"], 1, "agent") == PNG


def test_screenshot_discards_pixels_if_the_title_turns_restricted_during_capture(world):
    calls = []

    def flipping(hwnd):
        calls.append(hwnd)
        window = dict(WINDOWS[0])
        if len(calls) > 1:
            window["title"] = "notes [InPrivate]"
        return window

    world["info"] = flipping
    with pytest.raises(guard.GuardError) as refused:
        guard.screenshot(world["root"], 1, "agent")
    assert refused.value.code == "RESTRICTED_WINDOW" and world["captures"] == [1]
    assert rows()[-1]["kind"] == "refused" and rows()[-1]["code"] == "RESTRICTED_WINDOW"


@pytest.mark.parametrize("bad", [True, 1.5, -3, "12abc", 10 ** 30, None, "٣", 0])
def test_screenshot_rejects_bad_window_ids(world, bad):
    with pytest.raises(guard.GuardError) as refused:
        guard.screenshot(world["root"], bad, "agent")
    assert refused.value.code == "INVALID_WINDOW" and world["captures"] == []


def test_gone_window_and_capture_failures_map_to_codes(world, monkeypatch):
    with pytest.raises(guard.GuardError) as gone:
        guard.screenshot(world["root"], 99, "human")
    assert gone.value.code == "WINDOW_GONE" and gone.value.retry == "retry"

    def failing(hwnd):
        raise winapps.WinAppError("Could not capture that window", "CAPTURE_FAILED")

    monkeypatch.setattr(winapps, "winapps_window_screenshot", failing)
    with pytest.raises(guard.GuardError) as failed:
        guard.screenshot(world["root"], 1, "human")
    assert failed.value.code == "CAPTURE_FAILED"


def test_screenshot_on_a_non_windows_host_is_not_supported(world, monkeypatch):
    monkeypatch.setattr(winapps.sys, "platform", "linux")
    with pytest.raises(guard.GuardError) as refused:
        guard.screenshot(world["root"], 1, "human")
    assert refused.value.code == "NOT_SUPPORTED"


def test_doctor_probe_skips_restricted_windows(world, monkeypatch):
    seen = {}
    monkeypatch.setattr(winapps, "doctor", lambda can_probe=None, capture=None: seen.update(probe=can_probe) or {"capture": True},
                        raising=False)
    guard.doctor(world["root"], "agent", tool="winapps_doctor")
    assert [seen["probe"](w) for w in WINDOWS] == [True, False, False, False]
    guard.doctor(world["root"], "human")
    assert [seen["probe"](w) for w in WINDOWS] == [True, True, False, False]


def test_every_refusal_and_every_agent_call_is_audited_but_human_success_is_not(world):
    guard.list_windows(world["root"], "human")
    guard.screenshot(world["root"], 1, "human")
    assert rows() == []
    guard.list_windows(world["root"], "agent", tool="winapps_apps")
    guard.screenshot(world["root"], 1, "agent", tool="winapps_screenshot")
    with pytest.raises(guard.GuardError):
        guard.screenshot(world["root"], 3, "human")
    assert [(r["kind"], r["audience"]) for r in rows()] == [("list", "agent"), ("screenshot", "agent"),
                                                            ("refused", "human")]
    refusal = rows()[-1]
    assert (refusal["app"], refusal["windowId"], refusal["code"]) == ("1Password", 3, "RESTRICTED_WINDOW")
    assert "Vault" not in json.dumps(rows())


def test_web_ui_and_mcp_never_call_the_raw_screenshot_directly():
    """Every caller goes through the guard, so a new endpoint cannot bypass the policy by accident."""
    console = os.path.join(os.path.dirname(__file__), "..", "..", "..", "console")
    sources = [os.path.join(os.path.dirname(__file__), "..", "web_ui.py"), os.path.join(console, "mcp_server.py")]
    for path in sources:
        with open(path, encoding="utf-8") as f:
            assert "winapps.winapps_window_screenshot" not in f.read(), path


# ── Final review fixes ────────────────────────────────────────────────────────

@pytest.mark.parametrize("call", [
    lambda root: guard.list_windows(root, "admin"),
    lambda root: guard.screenshot(root, 1, "Agent"),
    lambda root: guard.doctor(root, ""),
])
def test_unknown_audience_is_refused_instead_of_treated_as_human(world, call):
    with pytest.raises(guard.GuardError) as refused:
        call(world["root"])
    assert refused.value.code == "INVALID_AUDIENCE" and world["captures"] == []


def test_example_policy_is_valid_and_grants_no_terminal(monkeypatch):
    repo = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", os.path.join(repo, "win-lab", "winapps-policy.example.json"))
    policy = guard.load_policy(repo)
    assert policy.error is None and policy.allowed
    assert not policy.allowed & {"windowsterminal", "wt", "cmd", "powershell", "pwsh", "conhost"}


# ── Sourcery review findings ──────────────────────────────────────────────────

def test_post_capture_check_uses_the_policy_as_it_is_after_the_capture(world, monkeypatch, tmp_path):
    policy_path = tmp_path / "policy.json"

    def capture(hwnd):
        policy_path.write_text(json.dumps({"allowedApps": ["Notepad"], "restrictedApps": ["Notepad"]}))
        return PNG

    monkeypatch.setattr(winapps, "winapps_window_screenshot", capture)
    with pytest.raises(guard.GuardError) as refused:
        guard.screenshot(world["root"], 1, "agent")
    assert refused.value.code == "RESTRICTED_WINDOW"


def test_doctor_captures_only_after_rechecking_the_current_window(world, monkeypatch):
    seen = {}

    def fake_doctor(can_probe=None, capture=None):
        seen["ok"] = capture(1)
        with pytest.raises(winapps.WinAppError) as refused:
            capture(3)
        seen["code"] = refused.value.code
        return {"capture": True}

    monkeypatch.setattr(winapps, "doctor", fake_doctor, raising=False)
    guard.doctor(world["root"], "agent")
    assert seen == {"ok": PNG, "code": "RESTRICTED_WINDOW"} and world["captures"] == [1]
    assert not any(row["kind"] == "screenshot" for row in rows())


def test_agent_audit_view_hides_human_rows_and_restricted_identities(audit_dir):
    guard.audit(None, "refused", audience="agent", app="1Password", window_id=3, code="RESTRICTED_WINDOW")
    guard.audit(None, "refused", audience="agent", app="Calc", window_id=2, code="APP_NOT_ALLOWED")
    guard.audit(None, "refused", audience="human", app="msedge", window_id=4, code="RESTRICTED_WINDOW")
    guard.audit(None, "list", audience="agent", tool="winapps_apps")
    agent_rows = guard.audit_rows(200, audience="agent")["rows"]
    assert [row["audience"] for row in agent_rows] == ["agent", "agent", "agent"]
    assert [row["app"] for row in agent_rows] == [None, None, None]
    assert [row["windowId"] for row in agent_rows][:2] == [3, 2]
    assert [row["app"] for row in guard.audit_rows(200)["rows"]][:3] == ["1Password", "Calc", "msedge"]


def test_unknown_policy_keys_are_a_policy_error(tmp_path, monkeypatch):
    write_policy(tmp_path, monkeypatch, {"allowedApps": ["a"], "restrictedApp": ["b"]})
    policy = guard.load_policy(str(tmp_path))
    assert policy.allowed == frozenset() and "restrictedApp" in policy.error


def test_valid_restrictions_survive_an_invalid_allowlist(tmp_path, monkeypatch):
    write_policy(tmp_path, monkeypatch, {"allowedApps": "nope", "restrictedTitles": ["secret"]})
    policy = guard.load_policy(str(tmp_path))
    assert policy.error and policy.allowed == frozenset()
    assert guard.classify(win("msedge", "my SECRET plan"), policy).reason == "policy-title"


def test_policy_change_with_the_same_size_and_mtime_is_seen(tmp_path, monkeypatch):
    path = write_policy(tmp_path, monkeypatch, {"allowedApps": ["a"]})
    stamp = path.stat().st_mtime_ns
    assert guard.load_policy(str(tmp_path)).allowed == frozenset({"a"})
    path.write_text(json.dumps({"allowedApps": ["b"]}))
    os.utime(path, ns=(stamp, stamp))
    assert guard.load_policy(str(tmp_path)).allowed == frozenset({"b"})


def test_concurrent_audit_rows_reach_the_file_in_seq_order(audit_dir, tmp_path):
    def work(base):
        for i in range(40):
            guard.audit(str(tmp_path), "list", audience="agent", window_id=base * 1000 + i + 1)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    file = next(audit_dir.glob("winapps-audit-*.jsonl"))
    seqs = [json.loads(line)["seq"] for line in file.read_text(encoding="utf-8").splitlines()]
    assert seqs == sorted(seqs) and len(seqs) == 240


def test_audit_rows_report_when_persistence_is_failing(tmp_path, monkeypatch):
    guard._reset_audit()
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(tmp_path / "ok"))
    guard.audit(str(tmp_path), "list", audience="agent", window_id=1)
    assert guard.audit_rows()["persistent"] is True
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(blocker))
    guard.audit(str(tmp_path), "list", audience="agent", window_id=2)
    assert guard.audit_rows()["persistent"] is False
    guard._reset_audit()


def test_the_audit_file_stops_growing_at_its_row_cap(audit_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "_AUDIT_FILE_MAX_ROWS", 5)
    for i in range(8):
        guard.audit(str(tmp_path), "list", audience="agent", window_id=i + 1)
    file = next(audit_dir.glob("winapps-audit-*.jsonl"))
    assert len(file.read_text(encoding="utf-8").splitlines()) == 5
    assert len(rows()) == 8 and guard.audit_rows()["persistent"] is False


def test_a_hung_capture_times_out_instead_of_blocking(world, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(guard, "_CAPTURE_TIMEOUT", 0.2)
    monkeypatch.setattr(winapps, "winapps_window_screenshot", lambda hwnd: release.wait(5) and PNG)
    try:
        with pytest.raises(guard.GuardError) as refused:
            guard.screenshot(world["root"], 1, "human")
    finally:
        release.set()
    assert refused.value.code == "CAPTURE_TIMEOUT" and refused.value.retry == "retry"


def test_agents_get_a_smaller_capture_ceiling_than_people(world):
    world["info"] = lambda hwnd: {**WINDOWS[0], "width": 5000, "height": 3000}
    with pytest.raises(guard.GuardError) as refused:
        guard.screenshot(world["root"], 1, "agent")
    assert refused.value.code == "CAPTURE_TOO_LARGE"
    assert guard.screenshot(world["root"], 1, "human") == PNG
