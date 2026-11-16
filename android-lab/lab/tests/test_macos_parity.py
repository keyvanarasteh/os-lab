"""macOS Lab engine parity with QcU: config precedence, arm owner, capabilities, displays,
element search, permissions, the live audit feed, the allowlist, preview stamps and the
native REPL. A fake AX helper stands in for the Mac, so these run on Linux CI (OSLAB_AX_HELPER)."""
import functools
import http.client
import io
import os
import sys
import threading
import time
from http.server import HTTPServer

import pytest

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))

import oslab  # noqa: E402

FAKE_HELPER = os.path.join(REPO_ROOT, "ios-lab", "mac", "fake-ax-helper.py")
WINDOW = {"windowId": 7, "pid": 1, "app": "Demo", "title": "Demo", "x": 100, "y": 100, "width": 800, "height": 600}


@pytest.fixture
def mac(monkeypatch):
    """A Mac as far as oslab can tell: the host check, the window list and the helper are faked."""
    monkeypatch.setenv("OSLAB_AX_HELPER", FAKE_HELPER)
    monkeypatch.setattr(oslab, "host_os", lambda: "macos")
    monkeypatch.setattr(oslab, "macos_windows",
                        lambda: {"available": True, "reason": None, "screenRecording": True, "windows": [dict(WINDOW)]})
    oslab._MACOS_ELEMENTS.clear()
    with oslab._MACOS_CONTROL_LOCK:
        oslab._MACOS_CONTROL.update({"armed": False, "owner": None})
    yield
    with oslab._MACOS_CONTROL_LOCK:
        oslab._MACOS_CONTROL.update({"armed": False, "owner": None})


def test_config_env_beats_defaults_and_is_clamped(monkeypatch):
    monkeypatch.setenv("OSLAB_MAC_CONTROL_TIMEOUT", "120")
    monkeypatch.setenv("OSLAB_MAC_AUDIT_MAX", "1")  # below the floor: a typo cannot shrink the log to nothing
    monkeypatch.setenv("OSLAB_MAC_STREAM_CAP", "nonsense")
    config = oslab._load_macos_config()
    assert config["controlTimeout"] == 120
    assert config["auditMax"] == 50
    assert config["streamCap"] == 600


def _allowlist_root(tmp_path, content=None):
    """A fake repo root whose ios-lab/mac/agent-apps.json holds the given text."""
    folder = tmp_path / "ios-lab" / "mac"
    folder.mkdir(parents=True)
    entry = folder / "agent-apps.json"
    if content is not None:
        entry.write_text(content, encoding="utf-8")
    return str(tmp_path)


def test_allowlist_missing_file_and_empty_list_allow_every_app(tmp_path):
    root = _allowlist_root(tmp_path)
    oslab._macos_allowlist(root, app="Anything", bundle="com.any.app")  # no file: no restriction
    root = _allowlist_root(tmp_path / "b", content="[]")
    oslab._macos_allowlist(root, app="Anything", bundle="com.any.app")  # empty list: explicit no restriction


def test_allowlist_admits_members_and_refuses_strangers(tmp_path):
    root = _allowlist_root(tmp_path, content='["Finder", "com.example.app"]')
    oslab._macos_allowlist(root, app="Finder")              # by name
    oslab._macos_allowlist(root, bundle="com.example.APP")   # by bundle id, case-insensitive
    with pytest.raises(oslab.PlanError) as refused:
        oslab._macos_allowlist(root, bundle="com.stranger.app")
    assert refused.value.code == "APP_NOT_ALLOWED"


def test_allowlist_fails_closed_on_a_broken_file(tmp_path):
    root = _allowlist_root(tmp_path, content='{"Finder": true}')  # a dict, not a list
    with pytest.raises(oslab.PlanError) as refused:
        oslab._macos_allowlist(root, app="Finder")
    assert refused.value.code == "ALLOWLIST_INVALID"
    assert "agent-apps.json" in str(refused.value)
    entry = tmp_path / "ios-lab" / "mac" / "agent-apps.json"
    entry.write_text('["Finder", 7]', encoding="utf-8")  # not a list of strings
    with pytest.raises(oslab.PlanError) as refused:
        oslab._macos_allowlist(root, app="Finder")
    assert refused.value.code == "ALLOWLIST_INVALID"
    entry.write_text('["Finder",', encoding="utf-8")  # malformed JSON
    with pytest.raises(oslab.PlanError) as refused:
        oslab._macos_allowlist(root, app="Finder")
    assert refused.value.code == "ALLOWLIST_INVALID"
    entry.unlink()
    entry.mkdir()  # present but unreadable: a directory where the file should be
    with pytest.raises(oslab.PlanError) as refused:
        oslab._macos_allowlist(root, app="Finder")
    assert refused.value.code == "ALLOWLIST_INVALID"


def test_second_owner_cannot_arm_and_is_named(mac):
    oslab.macos_control_arm(None, True, "console")
    with pytest.raises(oslab.PlanError) as refused:
        oslab.macos_control_arm(None, True, "agent")
    assert refused.value.code == "ARMED_BY_OTHER"
    assert "console" in str(refused.value)
    assert oslab.macos_control_state()["owner"] == "console"


def test_element_search_finds_by_label_value_and_placeholder(mac):
    by_label = oslab.macos_search_elements(REPO_ROOT, 7, "save")
    assert by_label["count"] == 1 and by_label["hits"][0]["label"] == "Save"
    assert by_label["hits"][0]["path"] == "1"  # the same path macos_get_app_state reports
    assert oslab.macos_search_elements(REPO_ROOT, 7, "ada")["hits"][0]["role"] == "TextField"
    assert oslab.macos_search_elements(REPO_ROOT, 7, "your name")["count"] == 1
    assert oslab.macos_search_elements(REPO_ROOT, 7, "nothing like this")["count"] == 0


def test_element_search_rejects_an_empty_query(mac):
    with pytest.raises(oslab.PlanError) as refused:
        oslab.macos_search_elements(REPO_ROOT, 7, "   ")
    assert refused.value.code == "INVALID_ARGS"


def test_capabilities_report_engine_and_safety(mac):
    caps = oslab.macos_capabilities(REPO_ROOT)
    assert caps["available"] and caps["engine"] == "ax-helper" and caps["helperBuilt"]
    assert caps["canAct"]["setValue"] and "type" in caps["canAct"]["input"]
    assert caps["safety"]["singleOwner"] and caps["safety"]["panicStop"]
    assert "paste" in caps["safety"]["submitKinds"]


def test_capabilities_off_a_mac_are_empty(monkeypatch):
    monkeypatch.delenv("OSLAB_AX_HELPER", raising=False)
    monkeypatch.setattr(oslab, "host_os", lambda: "linux")
    caps = oslab.macos_capabilities(REPO_ROOT)
    assert caps["available"] is False and caps["canObserve"] == [] and caps["canAct"]["input"] == []


def test_displays_are_json_on_a_mac_and_refused_elsewhere(mac, monkeypatch):
    class Cg:
        def screens(self):
            return [{"x": 0, "y": 0, "width": 1512, "height": 982, "scale": 2.0}]
    monkeypatch.setattr(oslab, "_macos_cg", lambda: Cg())
    assert oslab.macos_displays()["displays"][0]["scale"] == 2.0
    monkeypatch.setattr(oslab, "host_os", lambda: "linux")
    assert oslab.macos_displays() == {"available": False, "reason": "The app mirror needs a Mac.", "displays": []}


def test_new_navigation_keys_are_allowlisted_and_unknown_keys_refused():
    for key in ("home", "end", "pageup", "pagedown"):
        values = oslab._validated_input({"pid": 1, "x": 0, "y": 0, "kind": "key", "key": key})
        assert values["key"] == key
    with pytest.raises(oslab.PlanError) as refused:
        oslab._validated_input({"pid": 1, "x": 0, "y": 0, "kind": "key", "key": "f13"})
    assert refused.value.code == "INVALID_ARGS"


def test_type_paste_and_tree_limits_are_configurable_and_honored(monkeypatch):
    monkeypatch.setenv("OSLAB_MAC_TYPE_MAX", "300")
    monkeypatch.setenv("OSLAB_MAC_PASTE_MAX", "1500")
    monkeypatch.setenv("OSLAB_MAC_TREE_SIZE", "250")
    config = oslab._load_macos_config()
    assert (config["typeMax"], config["pasteMax"], config["treeSize"]) == (300, 1500, 250)
    monkeypatch.setenv("OSLAB_MAC_TYPE_MAX", "nonsense")
    assert oslab._load_macos_config()["typeMax"] == 200  # a typo keeps the default
    ok = oslab._validated_input({"pid": 1, "x": 0, "y": 0, "kind": "type", "text": "a" * 200})
    assert len(ok["text"]) == 200  # the default limit still gates the input family
    with pytest.raises(oslab.PlanError) as refused:
        oslab._validated_input({"pid": 1, "x": 0, "y": 0, "kind": "type", "text": "a" * 201})
    assert refused.value.code == "INVALID_ARGS"


def test_permissions_name_the_app_that_needs_the_grant(mac, monkeypatch):
    monkeypatch.setattr(oslab, "macos_responsible_app", lambda: "Terminal.app")
    permissions = oslab.macos_permissions(REPO_ROOT)
    assert permissions["accessibility"]["granted"] is True
    assert permissions["responsibleApp"] == "Terminal.app"
    monkeypatch.setattr(oslab, "_ax_helper", lambda root: None)
    assert "Terminal.app" in oslab.macos_permissions(REPO_ROOT)["accessibility"]["hint"]


def test_responsible_app_walks_up_to_the_app_bundle(mac, monkeypatch):
    chain = iter([(0, "100 /bin/zsh"), (0, "200 /Applications/Terminal.app/Contents/MacOS/Terminal")])
    monkeypatch.setattr(oslab, "_capture", lambda args, timeout=5.0, decode="utf-8": next(chain))
    assert oslab.macos_responsible_app() == "Terminal.app"


def test_request_access_validates_the_pane_and_audits(mac, monkeypatch):
    opened = []
    monkeypatch.setattr(oslab, "_capture", lambda args, timeout=5.0, decode="utf-8": (opened.append(args) or (0, '{"trusted": true}')))
    monkeypatch.setattr(oslab, "macos_responsible_app", lambda: "Terminal.app")
    with pytest.raises(oslab.PlanError):
        oslab.macos_request_access(None, {"pane": "camera"})
    result = oslab.macos_request_access(None, {"pane": "accessibility"})
    assert result["ok"] and result["trusted"] is True and result["grantTo"] == "Terminal.app"
    assert any(call[0] == "open" and "Privacy_Accessibility" in call[1] for call in opened)
    assert oslab.macos_audit_rows()["rows"][-1]["kind"] == "permission-request"


def test_request_access_refuses_off_a_mac(monkeypatch):
    monkeypatch.setattr(oslab, "host_os", lambda: "linux")
    with pytest.raises(oslab.PlanError) as refused:
        oslab.macos_request_access(None, {"pane": "accessibility"})
    assert refused.value.code == "UNSUPPORTED_PLATFORM"


def test_audit_rows_carry_a_sequence_for_the_live_feed():
    _, start = oslab.macos_audit_since(10 ** 12)
    oslab._macos_audit(None, "test-a")
    oslab._macos_audit(None, "test-b")
    rows, latest = oslab.macos_audit_since(start)
    assert [r["kind"] for r in rows] == ["test-a", "test-b"]
    assert latest == start + 2 and all(r["thumbnail"] is None for r in rows)


@pytest.fixture
def events_server():
    from web_ui import LabHttpHandler
    server = HTTPServer(("127.0.0.1", 5061), LabHttpHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)
    yield 5061
    server.shutdown()


def test_events_stream_delivers_rows_and_ends_on_panic_stop(events_server):
    connection = http.client.HTTPConnection("127.0.0.1", events_server, timeout=10)
    connection.request("GET", "/api/labs/macos/events")
    response = connection.getresponse()
    assert response.status == 200 and response.getheader("Content-Type") == "text/event-stream"
    assert response.readline() == b"retry: 3000\n"
    response.readline()
    response.readline()  # the opening heartbeat comment and its blank line
    oslab._macos_audit(None, "live-row")
    line = b""
    while not line.startswith(b"data:"):
        line = response.readline()
    assert b'"kind": "live-row"' in line
    oslab.macos_panic_stop(None)  # bumps the stream epoch: the handler must end, not dangle
    deadline = time.time() + 5
    while time.time() < deadline:
        chunk = response.read(1) if not response.isclosed() else b""
        if chunk == b"" and response.isclosed():
            break
    assert response.isclosed() or response.read() == b""

def make_repl_host(root):
    """A fake macOS host for oslab.plan: the mirror actions are available on this lab."""
    return {"os": "macos", "arch": "arm64", "root": root,
            "kvm": {"present": True, "usable": True},
            "wsl": {"guest": False, "distributions": []},
            "runtime": None,
            "xcode": {"installed": True, "iosRuntime": True, "iosDevice": True},
            "tools": [{"id": tool, "label": label, "found": tool in ("xcrun", "brew", "node"), "path": None}
                      for tool, label in oslab.TOOLS]}


def _repl(monkeypatch, input_lines=""):
    """A REPL session over the fake helper; the plan executor is stubbed, so confirmed plans never run."""
    import macos_repl
    monkeypatch.setattr(oslab, "host_info", lambda root: make_repl_host(root))
    repl = macos_repl.MacRepl(REPO_ROOT, input=io.StringIO(input_lines), output=io.StringIO())
    repl.runs = []
    repl._execute = lambda plan: (repl.runs.append(plan) or (0, "stubbed output"))
    return repl


def _stamp_of(out):
    for line in out.splitlines():
        if line.strip().startswith("stamp: "):
            return line.strip().split()[1]
    return None


def _save_index(repl):
    repl.handle("tree")
    return next(i for i, entry in enumerate(repl.numbered, 1)
                if entry["element"].get("label") == "Save")


def test_repl_previews_then_confirms_once_and_refuses_replay(mac, monkeypatch):
    repl = _repl(monkeypatch)
    index = _save_index(repl)
    repl.handle(f"click {index}")
    assert repl.runs == []  # a preview never executes
    stamp = _stamp_of(repl.output.getvalue())
    assert stamp and stamp.startswith("v1.")
    repl.handle("confirm not-the-stamp")
    assert repl.runs == []
    repl.handle(f"confirm {stamp}")
    assert len(repl.runs) == 1 and repl.runs[0]["action"] == "macos-click"
    kinds = [row["kind"] for row in oslab.macos_audit_rows()["rows"]]
    assert "preview" in kinds and "preview-confirmed" in kinds
    repl.handle(f"confirm {stamp}")  # replay: the first confirm consumed the stamp
    assert len(repl.runs) == 1
    assert "nothing to confirm" in repl.output.getvalue()


def test_repl_expired_stamp_refused(mac, monkeypatch):
    monkeypatch.setattr(oslab, "PlanSigner", functools.partial(oslab.PlanSigner, ttl=1))
    repl = _repl(monkeypatch)
    index = _save_index(repl)
    repl.handle(f"click {index}")
    stamp = _stamp_of(repl.output.getvalue())
    time.sleep(1.1)
    repl.handle(f"confirm {stamp}")
    assert repl.runs == [] and "no longer valid" in repl.output.getvalue()


def test_repl_arm_persists_across_commands_and_refuses_a_second_owner(mac, monkeypatch):
    repl = _repl(monkeypatch)
    index = _save_index(repl)  # tree reads before the _capture stub: the fake helper answers it
    captured = []
    monkeypatch.setattr(oslab, "_capture",
                        lambda args, timeout=5.0, decode="utf-8": captured.append(args) or (0, "ok"))
    repl.handle("arm")
    assert oslab.macos_control_state()["owner"] == "repl"
    repl.handle(f"click {index}")  # armed: runs now, no preview
    assert "executed" in repl.output.getvalue() and repl.runs == []
    repl.handle("apps")  # a read-only command between actions: the session keeps the arm
    repl.handle(f"click {index}")
    clicks = [args for args in captured if args[0] == "bash"]
    assert len(clicks) == 2 and clicks[0][2] == "click"
    with pytest.raises(oslab.PlanError) as refused:
        oslab.macos_control_arm(REPO_ROOT, True, "dashboard")
    assert refused.value.code == "ARMED_BY_OTHER"
    repl.handle("disarm")
    assert oslab.macos_control_state()["armed"] is False


def test_repl_paste_needs_explicit_confirm_even_while_armed(mac, monkeypatch):
    repl = _repl(monkeypatch, input_lines="n\ny\n")
    _save_index(repl)  # tree reads before the _capture stub: the fake helper answers it
    captured = []
    monkeypatch.setattr(oslab, "_capture",
                        lambda args, timeout=5.0, decode="utf-8": captured.append(args) or (0, "ok"))
    repl.handle("arm")
    repl.handle("paste hello")
    assert "cancelled" in repl.output.getvalue()
    repl.handle("paste hello")
    pastes = [args for args in captured if args[0] == "bash" and "paste" in args]
    assert pastes and "hello" in pastes[-1]


def test_repl_key_scroll_set_value_and_perform_preview_through_the_plan(mac, monkeypatch):
    repl = _repl(monkeypatch)
    index = _save_index(repl)
    repl.handle("key enter")
    assert "key enter" in repl.output.getvalue().replace('"', "")
    repl.handle("scroll down 5")
    assert "down:5" in repl.output.getvalue()
    repl.handle(f"set-value {index} Ada Lovelace")
    assert "axset" in repl.output.getvalue()
    repl.handle(f"perform {index} AXPress")
    assert "axperform" in repl.output.getvalue()
    assert repl.runs == []  # everything stays a preview while disarmed


def test_repl_stop_disarms_and_audits(mac, monkeypatch):
    repl = _repl(monkeypatch)
    oslab.macos_control_arm(REPO_ROOT, True, "repl")
    repl.handle("stop")
    assert oslab.macos_control_state()["armed"] is False
    assert oslab.macos_audit_rows()["rows"][-1]["kind"] == "panic-stop"
