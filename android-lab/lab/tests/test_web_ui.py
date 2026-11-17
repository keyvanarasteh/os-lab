import os
import json
import threading
import time
import urllib.error
import urllib.request
import pytest
from http.server import HTTPServer
from web_ui import LabHttpHandler


@pytest.fixture(scope="module")
def web_server():
    server = HTTPServer(("127.0.0.1", 5059), LabHttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield "http://127.0.0.1:5059"
    server.shutdown()


def test_web_ui_health_endpoint(web_server):
    url = f"{web_server}/api/health"
    req = urllib.request.urlopen(url)
    assert req.status == 200
    data = json.loads(req.read().decode("utf-8"))
    assert data["status"] == "ok"
    assert data["app"] == "android-lab"


def test_web_ui_dashboard_page(web_server):
    url = f"{web_server}/"
    req = urllib.request.urlopen(url)
    assert req.status == 200
    body = req.read().decode("utf-8")
    assert "os-lab" in body


def test_web_ui_classic_console(web_server):
    body = urllib.request.urlopen(f"{web_server}/classic/").read().decode("utf-8")
    assert "android-lab" in body
    assert "Mobile Security Console" in body


def test_web_ui_logs_and_reports_endpoints(web_server):
    # Logs endpoint
    req_logs = urllib.request.urlopen(f"{web_server}/api/logs")
    assert req_logs.status == 200
    logs_data = json.loads(req_logs.read().decode("utf-8"))
    assert "logs" in logs_data

    # Reports endpoint
    req_reports = urllib.request.urlopen(f"{web_server}/api/reports")
    assert req_reports.status == 200
    reports_data = json.loads(req_reports.read().decode("utf-8"))
    assert "reports" in reports_data


def test_web_ui_upload_endpoint(web_server):
    boundary = "----TestBoundary12345"
    file_bytes = b"PK\x03\x04mock_apk_content"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="apk"; filename="uploaded-sample.apk"\r\n'
        f"Content-Type: application/vnd.android.package-archive\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{web_server}/api/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-OSLab": "1"}
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["filename"] == "uploaded-sample.apk"
        assert data["size"] == len(file_bytes)
        assert data["path"].endswith("uploaded-sample.apk")



def _post(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def test_post_requires_oslab_header(web_server):
    status, data = _post(f"{web_server}/api/run", {"action": "preflight"})
    assert status == 403
    assert "X-OSLab" in data["error"]


def test_foreign_host_header_is_refused(web_server):
    req = urllib.request.Request(f"{web_server}/api/health", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 403


def test_artifacts_cannot_escape_folder(web_server):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", 5059)
    conn.request("GET", "/artifacts/../web_ui.py")
    assert conn.getresponse().status == 404


def test_host_reports_every_lab(web_server):
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/host").read().decode("utf-8"))
    assert data["host"]["os"]
    assert [lab["id"] for lab in data["labs"]] == ["android", "windows", "winapps", "linux", "ios", "macos", "source", "web"]
    for lab in data["labs"]:
        assert lab["state"] in ("ready", "needs-setup", "unavailable")


def test_health_capabilities_are_served_by_console(web_server):
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/capabilities").read().decode("utf-8"))
    assert len(data["platforms"]) == 3
    assert any(item.get("lab") == "ios" for group in data["groups"] for item in group["items"])


def test_winapps_endpoint_serves_the_read_only_inventory(web_server, monkeypatch):
    import web_ui

    fixture = {"available": True, "windows": [], "reason": None}
    monkeypatch.setattr(web_ui.winapps, "winapps_windows", lambda: fixture)
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps").read().decode("utf-8"))
    assert data == fixture

    monkeypatch.setattr(web_ui, "winapps", None)
    try:
        status = urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps").status
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 501


def test_winapps_screenshot_serves_a_png_and_reports_stale_windows(web_server, monkeypatch):
    import web_ui

    png = b"\x89PNG\r\n\x1a\n"
    monkeypatch.setattr(web_ui.winapps, "winapps_window_screenshot", lambda window_id: png)
    reply = urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/screenshot")
    assert reply.status == 200 and reply.headers["Content-Type"] == "image/png"
    assert reply.headers["Cache-Control"] == "no-store" and reply.read() == png

    def stale(_window_id):
        raise web_ui.winapps.WinAppError("That window is not on screen anymore; refresh the mirror")

    monkeypatch.setattr(web_ui.winapps, "winapps_window_screenshot", stale)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/screenshot")
    assert caught.value.code == 400
    assert "not on screen" in json.loads(caught.value.read().decode("utf-8"))["error"]


def test_winapps_stream_serves_bounded_multipart_frames_without_caching(web_server, monkeypatch):
    import web_ui

    frames = []

    def stream(window_id, fps):
        frames.append((window_id, fps))
        return (b"\x89PNG first", b"\x89PNG second")

    monkeypatch.setattr(web_ui.winapps, "winapps_window_stream", stream)
    reply = urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/stream?fps=50")
    body = reply.read()
    assert reply.status == 200
    assert reply.headers["Content-Type"] == "multipart/x-mixed-replace; boundary=frame"
    assert reply.headers["Cache-Control"] == "no-store"
    assert reply.headers["X-Content-Type-Options"] == "nosniff"
    assert body.count(b"--frame\r\n") == 2
    assert b"Content-Type: image/png\r\n" in body
    assert b"\x89PNG first" in body and b"\x89PNG second" in body
    assert frames == [("7", web_ui.winapps.MAX_STREAM_FPS)]


def test_winapps_stream_reports_a_stale_window_before_streaming(web_server, monkeypatch):
    import web_ui

    def stale(_window_id, _fps):
        raise web_ui.winapps.WinAppError("That window is not on screen anymore; refresh the mirror")

    monkeypatch.setattr(web_ui.winapps, "winapps_window_stream", stale)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/stream")
    assert caught.value.code == 400
    assert "not on screen" in json.loads(caught.value.read().decode("utf-8"))["error"]


def test_winapps_stream_is_unavailable_without_the_native_module(web_server, monkeypatch):
    import web_ui

    monkeypatch.setattr(web_ui, "winapps", None)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/stream")
    assert caught.value.code == 501


def test_winapps_doctor_endpoint_serves_the_probe_and_is_501_without_the_module(web_server, monkeypatch):
    import web_ui

    probe = {"available": True, "desktop": True, "elevated": False, "capture": True, "windows": 1}
    monkeypatch.setattr(web_ui.winapps, "doctor", lambda: probe)
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/labs/winapps/doctor").read().decode("utf-8"))
    assert data == probe

    monkeypatch.setattr(web_ui, "winapps", None)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/doctor")
    assert caught.value.code == 501


def test_winapps_uia_routes_return_elements_search_and_explicit_errors(web_server, monkeypatch):
    import web_ui

    elements = {
        "windowId": 7, "app": "Example", "bounds": {"x": 1, "y": 2, "width": 3, "height": 4},
        "revision": "rev-1", "engine": "uia", "trimmed": False,
        "elements": [], "diff": {"added": [], "changed": [], "removed": []},
    }
    search = {"windowId": 7, "app": "Example", "revision": "rev-1", "query": "save", "count": 0, "hits": []}
    monkeypatch.setattr(web_ui.winapps, "winapps_window_elements", lambda hwnd, revision: {
        **elements, "windowId": int(hwnd), "requestedRevision": revision,
    })
    monkeypatch.setattr(web_ui.winapps, "winapps_search_elements", lambda hwnd, query: {
        **search, "windowId": int(hwnd), "query": query,
    })
    monkeypatch.setattr(web_ui.winapps, "winapps_control_state", lambda: {
        "armed": False, "owner": None, "expiresInSec": 0,
        "recentActions": [{"time": 1.0, "kind": "input", "action": "double_click", "ok": True}],
    })

    data = json.loads(urllib.request.urlopen(
        f"{web_server}/api/labs/winapps/apps/7/elements?revision=old"
    ).read().decode("utf-8"))
    assert data["requestedRevision"] == "old" and data["windowId"] == 7
    result = json.loads(urllib.request.urlopen(
        f"{web_server}/api/labs/winapps/apps/7/search?q=save"
    ).read().decode("utf-8"))
    assert result["query"] == "save"
    control = json.loads(urllib.request.urlopen(
        f"{web_server}/api/labs/winapps/control"
    ).read().decode("utf-8"))
    assert control["armed"] is False
    assert control["recentActions"][0]["action"] == "double_click"

    def unsupported(_hwnd, _revision):
        raise web_ui.winapps.WinAppError("UI Automation is unavailable", status=501, code="UIA_UNAVAILABLE")

    monkeypatch.setattr(web_ui.winapps, "winapps_window_elements", unsupported)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/elements")
    assert caught.value.code == 501
    assert json.loads(caught.value.read().decode("utf-8"))["code"] == "UIA_UNAVAILABLE"


def test_winapps_control_post_routes_require_header_and_dispatch_actions(web_server, monkeypatch):
    import web_ui

    calls = []

    def arm(armed, owner):
        calls.append(("arm", armed, owner))
        return {"armed": armed, "owner": owner, "expiresInSec": 600, "recentActions": []}

    def click(data):
        calls.append(("click", data))
        return {"ok": True, "actionSent": True}

    def input_action(data):
        calls.append(("input", data))
        return {"ok": True, "actionSent": True}

    def stop():
        calls.append(("stop",))
        return {"ok": True, "disarmed": True}

    monkeypatch.setattr(web_ui.winapps, "winapps_control_arm", arm)
    monkeypatch.setattr(web_ui.winapps, "winapps_control_click", click)
    monkeypatch.setattr(web_ui.winapps, "winapps_control_input", input_action)
    monkeypatch.setattr(web_ui.winapps, "winapps_panic_stop", stop)

    status, rejected = _post(f"{web_server}/api/labs/winapps/control", {"armed": True, "owner": "panel"})
    assert status == 403 and "X-OSLab" in rejected["error"]
    headers = {"X-OSLab": "1"}
    assert _post(f"{web_server}/api/labs/winapps/control", {"armed": True, "owner": "panel"}, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/click", {"x": 4, "y": 5}, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/input", {"kind": "key", "key": "tab"}, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/input",
                 {"kind": "double_click", "x": 4, "y": 5}, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/input",
                 {"kind": "scroll", "x": 4, "y": 5, "deltaX": 0, "deltaY": 120}, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/stop", {}, headers)[0] == 200
    assert [call[0] for call in calls] == ["arm", "click", "input", "input", "input", "stop"]
    assert calls[3][1]["kind"] == "double_click"
    assert calls[4][1]["deltaY"] == 120


def test_winapps_control_post_preserves_validation_status(web_server, monkeypatch):
    import web_ui

    def refused(_data):
        raise web_ui.winapps.WinAppError("Another dashboard holds the lock", status=409, code="INPUT_BUSY")

    monkeypatch.setattr(web_ui.winapps, "winapps_control_click", refused)
    status, data = _post(f"{web_server}/api/labs/winapps/click", {"confirm": True}, {"X-OSLab": "1"})
    assert status == 409 and data["code"] == "INPUT_BUSY"


def test_scope_endpoint_reports_the_declared_scope(web_server, tmp_path, monkeypatch):
    path = tmp_path / "scope.json"
    monkeypatch.setenv("OSLAB_SCOPE_FILE", str(path))
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/scope").read().decode("utf-8"))
    assert data["valid"] is False and data["declared"] is False and "No lab scope is declared" in data["error"]
    path.write_text(json.dumps({"version": 1, "name": "web test lab", "authorization": "Owned fixtures",
                                "hosts": ["127.0.0.1"], "devices": ["emulator-*"]}), encoding="utf-8")
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/scope").read().decode("utf-8"))
    assert data["valid"] is True and data["name"] == "web test lab"
    assert data["counts"] == {"hosts": 1, "packages": 0, "devices": 1, "paths": 0}


def test_lab_start_requires_a_previewed_plan(web_server, monkeypatch):
    # Test the preview-token guard independently of installed VM providers.
    # A host without KVM/runtime support cannot build a real Android plan.
    monkeypatch.setattr("web_ui.oslab.plan", lambda *args, **kwargs: {})
    status, data = _post(f"{web_server}/api/labs/start",
                         {"request": {"lab": "android", "action": "status"}, "token": "forged"},
                         {"X-OSLab": "1"})
    assert status == 409


def test_lab_plan_rejects_injection(web_server):
    status, data = _post(f"{web_server}/api/labs/plan",
                         {"request": {"lab": "android", "action": "start", "profile": "../../etc"}},
                         {"X-OSLab": "1"})
    assert status == 400


def _content_post(url, body=b"{}", headers=None):
    req = urllib.request.Request(url, data=body, method="POST", headers=headers or {})
    try:
        return urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        return e


def test_content_status_and_bundled_companies(web_server):
    status = json.load(urllib.request.urlopen(f"{web_server}/api/content/status"))
    assert status["installed"] is False and status["offline"] is True
    data = json.load(urllib.request.urlopen(f"{web_server}/api/content/companies"))
    assert data["source"] == "bundled" and len(data["companies"]) >= 1
    assert all(c["slug"] and isinstance(c["branches"], list) for c in data["companies"])


def test_content_file_is_limited_to_content_paths(web_server):
    ok = urllib.request.urlopen(f"{web_server}/api/content/file?path=docs/legal/PRIVACY.md")
    assert ok.status == 200 and b"Privacy" in ok.read()
    for bad in ("labctl", "../../etc/passwd", "android-lab/lab/web_ui.py", "docs/legal/../../labctl"):
        try:
            urllib.request.urlopen(f"{web_server}/api/content/file?path={bad}")
            raise AssertionError(f"{bad} was served")
        except urllib.error.HTTPError as e:
            assert e.code == 404


def test_content_posts_need_the_oslab_header_and_respect_the_offline_switch(web_server):
    assert _content_post(f"{web_server}/api/content/update").code == 403
    resp = _content_post(f"{web_server}/api/content/check", headers={"X-OSLab": "1"})
    assert resp.code == 400 and b"switched off" in resp.read()


def test_app_update_status_is_reported_without_network(web_server):
    data = json.load(urllib.request.urlopen(f"{web_server}/api/app/update"))
    assert "supported" in data and "updateAvailable" in data
    assert data["install"] is None

