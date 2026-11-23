"""macOS Lab engine parity with QcU: config precedence, arm owner, capabilities, displays,
element search, permissions, the live audit feed. A fake AX helper stands in for the Mac, so
these run on Linux CI (OSLAB_AX_HELPER)."""
import http.client
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
