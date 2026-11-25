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
    assert [lab["id"] for lab in data["labs"]] == ["android", "windows", "winapps", "linux", "ios", "macos", "source", "websec", "web"]
    for lab in data["labs"]:
        assert lab["state"] in ("ready", "needs-setup", "unavailable")


def test_health_capabilities_are_served_by_console(web_server):
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/capabilities").read().decode("utf-8"))
    assert len(data["platforms"]) == 3
    assert any(item.get("lab") == "ios" for group in data["groups"] for item in group["items"])


def _no_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(tmp_path / "absent-policy.json"))


def _http_error(url):
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(url)
    return caught.value.code, json.loads(caught.value.read().decode("utf-8"))


def test_winapps_endpoint_serves_the_read_only_inventory(web_server, monkeypatch, tmp_path):
    import web_ui

    _no_policy(monkeypatch, tmp_path)
    fixture = {"available": True, "reason": None, "windows": [
        {"windowId": 1, "app": "Notepad", "title": "notes.txt", "width": 10, "height": 10},
        {"windowId": 3, "app": "1Password", "title": "Vault: bank", "width": 10, "height": 10}]}
    monkeypatch.setattr(web_ui.winapps_guard.winapps, "winapps_windows", lambda: fixture)
    raw = urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps").read().decode("utf-8")
    data = json.loads(raw)
    by_id = {window["windowId"]: window for window in data["windows"]}
    # Served through the guard: the restricted window is flagged and its title never leaves.
    assert by_id[1]["restricted"] is False and by_id[1]["title"] == "notes.txt"
    assert by_id[3]["restricted"] is True and by_id[3]["title"] == "(restricted)"
    assert "Vault: bank" not in raw


def test_winapps_endpoints_are_501_without_the_guard_module(web_server, monkeypatch):
    import web_ui

    monkeypatch.setattr(web_ui, "winapps_guard", None)
    for path in ("apps", "apps/7/screenshot", "doctor", "policy", "audit"):
        code, body = _http_error(f"{web_server}/api/labs/winapps/{path}")
        assert code == 501 and "not installed" in body["error"]


def test_winapps_screenshot_serves_a_png_and_maps_guard_errors(web_server, monkeypatch):
    import web_ui

    png = b"\x89PNG\r\n\x1a\n"
    seen = {}

    def fake(root, window_id, audience, **kwargs):
        seen.update(window_id=window_id, audience=audience, expected_token=kwargs.get("expected_token"))
        return png

    monkeypatch.setattr(web_ui.winapps_guard, "screenshot", fake)
    reply = urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/screenshot?windowToken=token-a")
    assert reply.status == 200 and reply.headers["Content-Type"] == "image/png"
    assert reply.headers["Cache-Control"] == "no-store" and reply.read() == png
    assert seen == {"window_id": "7", "audience": "human", "expected_token": "token-a"}

    def changed(root, window_id, audience, **kwargs):
        raise web_ui.winapps.WinAppError("The selected window changed; refresh the mirror",
                                         status=409, code="WINDOW_CHANGED")

    monkeypatch.setattr(web_ui.winapps_guard, "screenshot", changed)
    got, body = _http_error(f"{web_server}/api/labs/winapps/apps/7/screenshot?windowToken=old")
    assert got == 409 and body["code"] == "WINDOW_CHANGED"

    for code, status in (("WINDOW_GONE", 400), ("INVALID_WINDOW", 400), ("RESTRICTED_WINDOW", 403)):
        def refuse(root, window_id, audience, _code=code, **kwargs):
            raise web_ui.winapps_guard.GuardError("refused", _code)

        monkeypatch.setattr(web_ui.winapps_guard, "screenshot", refuse)
        got, body = _http_error(f"{web_server}/api/labs/winapps/apps/7/screenshot")
        assert got == status and body == {"error": "refused", "code": code}


def test_winapps_stream_serves_bounded_multipart_frames_without_caching(web_server, monkeypatch):
    import web_ui

    frames = []
    png = web_ui.winapps._png(1, 1, bytes(4))

    def stream(window_id, fps, expected_token=None):
        frames.append((window_id, fps, expected_token))
        return (png, png)

    monkeypatch.setattr(web_ui.winapps, "winapps_window_stream", stream)
    reply = urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/stream?fps=50&windowToken=token-a")
    body = reply.read()
    assert reply.status == 200
    assert reply.headers["Content-Type"] == "multipart/x-mixed-replace; boundary=frame"
    assert reply.headers["Cache-Control"] == "no-store"
    assert reply.headers["X-Content-Type-Options"] == "nosniff"
    assert body.count(b"--frame\r\n") == 2
    assert b"Content-Type: image/png\r\n" in body
    parts = body.split(b"--frame\r\n")[1:]
    assert len(parts) == 2
    for part in parts:
        headers, payload = part.split(b"\r\n\r\n", 1)
        content_length = int(next(line.split(b": ", 1)[1] for line in headers.split(b"\r\n")
                                  if line.startswith(b"Content-Length: ")))
        assert payload == png + b"\r\n"
        assert content_length == len(png)
    assert frames == [("7", web_ui.winapps.MAX_STREAM_FPS, "token-a")]


def test_winapps_stream_reports_a_stale_window_before_streaming(web_server, monkeypatch):
    import web_ui

    def stale(_window_id, _fps, _expected_token=None):
        if False:
            yield b""
        raise web_ui.winapps.WinAppError("That window is not on screen anymore; refresh the mirror")

    monkeypatch.setattr(web_ui.winapps, "winapps_window_stream", stale)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/stream")
    assert caught.value.code == 400
    assert "not on screen" in json.loads(caught.value.read().decode("utf-8"))["error"]


def test_winapps_stream_rejects_an_invalid_first_frame_before_headers(web_server, monkeypatch):
    import web_ui

    monkeypatch.setattr(web_ui.winapps, "winapps_window_stream",
                        lambda _window_id, _fps, _token=None: iter([b"not a PNG"]))
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/stream")
    assert caught.value.code == 502
    assert "invalid PNG" in json.loads(caught.value.read().decode("utf-8"))["error"]


def test_winapps_stream_is_unavailable_without_the_native_module(web_server, monkeypatch):
    import web_ui

    monkeypatch.setattr(web_ui, "winapps", None)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/apps/7/stream")
    assert caught.value.code == 501


def test_winapps_doctor_endpoint_serves_the_probe(web_server, monkeypatch):
    import web_ui

    probe = {"available": True, "desktop": True, "elevated": False, "capture": True, "windows": 1}
    monkeypatch.setattr(web_ui.winapps_guard, "doctor", lambda root, audience="agent", **kw: probe)
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/labs/winapps/doctor").read().decode("utf-8"))
    assert data == probe


def test_winapps_policy_endpoint_serves_counts_only(web_server, monkeypatch, tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"allowedApps": ["Notepad"], "restrictedTitles": ["a", "b"]}))
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(policy))
    text = urllib.request.urlopen(f"{web_server}/api/labs/winapps/policy").read().decode("utf-8")
    data = json.loads(text)
    assert (data["allowedApps"], data["restrictedTitles"], data["exists"]) == (1, 2, True)
    assert "Notepad" not in text


def test_winapps_audit_endpoint_serves_rows(web_server, monkeypatch, tmp_path):
    import web_ui

    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(tmp_path / "audit"))
    web_ui.winapps_guard._reset_audit()
    web_ui.winapps_guard.audit(None, "list", audience="agent", tool="winapps_apps")
    data = json.loads(urllib.request.urlopen(f"{web_server}/api/labs/winapps/audit").read().decode("utf-8"))
    assert [row["kind"] for row in data["rows"]] == ["list"] and data["recording"] is True
    web_ui.winapps_guard._reset_audit()


def test_winapps_uia_routes_return_elements_search_and_explicit_errors(web_server, monkeypatch):
    import web_ui

    elements = {
        "windowId": 7, "app": "Example", "bounds": {"x": 1, "y": 2, "width": 3, "height": 4},
        "revision": "rev-1", "engine": "uia", "trimmed": False,
        "elements": [], "diff": {"added": [], "changed": [], "removed": []},
    }
    search = {"windowId": 7, "app": "Example", "revision": "rev-1", "query": "save", "count": 0, "hits": []}
    monkeypatch.setattr(web_ui.winapps, "winapps_window_elements", lambda hwnd, revision, token: {
        **elements, "windowId": int(hwnd), "requestedRevision": revision, "requestedToken": token,
    })
    monkeypatch.setattr(web_ui.winapps, "winapps_search_elements", lambda hwnd, query, token: {
        **search, "windowId": int(hwnd), "query": query, "requestedToken": token,
    })
    monkeypatch.setattr(web_ui.winapps, "winapps_control_state", lambda: {
        "armed": False, "owner": None, "expiresInSec": 0,
        "recentActions": [{"time": 1.0, "kind": "input", "action": "double_click", "ok": True}],
    })

    data = json.loads(urllib.request.urlopen(
        f"{web_server}/api/labs/winapps/apps/7/elements?revision=old&windowToken=token-a"
    ).read().decode("utf-8"))
    assert data["requestedRevision"] == "old" and data["windowId"] == 7
    assert data["requestedToken"] == "token-a"
    result = json.loads(urllib.request.urlopen(
        f"{web_server}/api/labs/winapps/apps/7/search?q=save&windowToken=token-a"
    ).read().decode("utf-8"))
    assert result["query"] == "save" and result["requestedToken"] == "token-a"
    control = json.loads(urllib.request.urlopen(
        f"{web_server}/api/labs/winapps/control"
    ).read().decode("utf-8"))
    assert control["armed"] is False
    assert control["recentActions"][0]["action"] == "double_click"

    def unsupported(_hwnd, _revision, _token=None):
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
    monkeypatch.setattr(web_ui.winapps_input_gate, "authorize", lambda *a, **k: {"windowId": 7})

    arm_payload = {"armed": True, "owner": "panel"}
    binding = {
        "windowId": 7, "windowToken": "a" * 24, "revision": "b" * 16,
        "elementId": "c" * 16, "elementBounds": {"x": 40, "y": 20, "w": 80, "h": 24},
        "owner": "panel", "confirm": True,
    }
    click_payload = {
        **binding, "x": 80, "y": 32, "action": "click", "deltaX": 0, "deltaY": 0,
        "actionId": "action-1",
    }
    input_payload = {**binding, "kind": "key", "key": "tab", "actionId": "action-2"}
    status, rejected = _post(f"{web_server}/api/labs/winapps/control", arm_payload)
    assert status == 403 and "X-OSLab" in rejected["error"]
    headers = {"X-OSLab": "1"}
    input_double_click_payload = {**binding, "kind": "double_click", "x": 4, "y": 5, "actionId": "action-3"}
    input_scroll_payload = {**binding, "kind": "scroll", "x": 4, "y": 5, "deltaX": 0, "deltaY": 120, "actionId": "action-4"}
    assert _post(f"{web_server}/api/labs/winapps/control", arm_payload, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/click", click_payload, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/input", input_payload, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/input", input_double_click_payload, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/input", input_scroll_payload, headers)[0] == 200
    assert _post(f"{web_server}/api/labs/winapps/stop", {}, headers)[0] == 200
    assert [call[0] for call in calls] == ["arm", "click", "input", "input", "input", "stop"]
    assert calls == [
        ("arm", True, "panel"),
        ("click", click_payload),
        ("input", input_payload),
        ("input", input_double_click_payload),
        ("input", input_scroll_payload),
        ("stop",),
    ]
    assert calls[3][1]["kind"] == "double_click"
    assert calls[4][1]["deltaY"] == 120


def test_winapps_control_post_preserves_validation_status(web_server, monkeypatch):
    import web_ui

    def refused(_data):
        raise web_ui.winapps.WinAppError("Another dashboard holds the lock", status=409, code="INPUT_BUSY")

    monkeypatch.setattr(web_ui.winapps, "winapps_control_click", refused)
    monkeypatch.setattr(web_ui.winapps_input_gate, "authorize", lambda *a, **k: {"windowId": 7})
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


def test_winapps_input_gate_endpoints_need_the_header_and_share_the_control_lock(web_server, monkeypatch, tmp_path):
    import web_ui

    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(tmp_path / "audit"))

    winapps = web_ui.winapps
    monkeypatch.setattr(winapps.sys, "platform", "win32")
    monkeypatch.setattr(winapps, "_user32", object())
    monkeypatch.setattr(winapps, "_CONTROL_STATE", {"armed": False, "armedAt": 0.0, "owner": None})
    monkeypatch.setattr(winapps, "_WINAPPS_STREAM_EPOCH", 0)
    monkeypatch.setattr(winapps, "desktop_locked", lambda: False)
    state = json.loads(urllib.request.urlopen(f"{web_server}/api/labs/winapps/input").read().decode("utf-8"))
    assert state["armed"] is False and "owner" not in state
    arm = f"{web_server}/api/labs/winapps/input/arm"
    assert _post(arm, {"owner": "panel-1"}, {})[0] == 403
    status, data = _post(arm, {"owner": "panel-1"}, {"X-OSLab": "1"})
    assert status == 200 and data["armed"] is True and data["owner"] == "panel-1"
    status, data = _post(f"{web_server}/api/labs/winapps/control", {"armed": True, "owner": "agent-9"},
                         {"X-OSLab": "1"})
    assert (status, data["code"]) == (409, "INPUT_BUSY")  # one lock behind both doors
    status, data = _post(f"{web_server}/api/labs/winapps/input/disarm", {"owner": "agent-9"}, {"X-OSLab": "1"})
    assert (status, data["code"]) == (409, "INPUT_BUSY")
    status, data = _post(f"{web_server}/api/labs/winapps/stop", {}, {"X-OSLab": "1"})
    assert status == 200 and data["disarmed"] is True and data["gate"]["epoch"] == 1
    assert winapps.winapps_control_state()["armed"] is False

    monkeypatch.setattr(web_ui, "winapps_input_gate", None)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{web_server}/api/labs/winapps/input")
    assert caught.value.code == 501


@pytest.mark.parametrize("code,status", [("NOT_ARMED", 409), ("SCREEN_LOCKED", 409), ("APP_NOT_ALLOWED", 403),
                                         ("RESTRICTED_WINDOW", 403), ("CONFIRM_REQUIRED", 400)])
def test_winapps_click_and_input_stop_at_the_gate(web_server, monkeypatch, code, status):
    import web_ui

    sent = []
    seen = []
    monkeypatch.setattr(web_ui.winapps, "winapps_control_click", lambda data: sent.append("click") or {})
    monkeypatch.setattr(web_ui.winapps, "winapps_control_input", lambda data: sent.append("input") or {})

    def refuse(root, window_id, kind, **kwargs):
        seen.append((window_id, kind, kwargs.get("confirm"), kwargs.get("key")))
        raise web_ui.winapps_guard.GuardError("refused", code)

    monkeypatch.setattr(web_ui.winapps_input_gate, "authorize", refuse)
    for path, body in (("click", {"windowId": 7, "confirm": True}),
                       ("input", {"windowId": 7, "kind": "key", "key": "Enter", "confirm": True})):
        got, data = _post(f"{web_server}/api/labs/winapps/{path}", body, {"X-OSLab": "1"})
        assert (got, data["code"]) == (status, code)
    assert seen == [(7, "click", True, None), (7, "key", True, "Enter")]
    assert sent == []


def test_winapps_input_reaches_the_mirror_only_after_the_gate_allows_it(web_server, monkeypatch):
    import web_ui

    sent = []
    monkeypatch.setattr(web_ui.winapps_input_gate, "authorize", lambda *a, **k: {"windowId": 7})
    monkeypatch.setattr(web_ui.winapps, "winapps_control_input", lambda data: sent.append(data) or {"ok": True})
    status, data = _post(f"{web_server}/api/labs/winapps/input", {"windowId": 7, "kind": "type", "text": "hi",
                                                                   "confirm": True}, {"X-OSLab": "1"})
    assert status == 200 and data == {"ok": True} and sent[0]["text"] == "hi"


class _FakeFrida:
    name = "api"

    def __init__(self):
        self.calls = []

    def devices(self):
        self.calls.append("devices")
        return [{"id": "local", "type": "local", "transport": "local", "name": "Local System", "os": None},
                {"id": "socket", "type": "remote", "transport": "TCP", "name": "Local Socket", "os": None}]

    def processes(self, device_id, host, apps):
        self.calls.append(("processes", device_id, host))
        return [{"pid": 10, "name": "sleep"}]


def test_frida_inventory_lists_attachable_targets(web_server, monkeypatch):
    import web_ui
    fake = _FakeFrida()
    monkeypatch.setattr(web_ui.frida_inventory, "pick_backend", lambda *args, **kwargs: fake)
    data = json.load(urllib.request.urlopen(f"{web_server}/api/frida/inventory"))
    assert data["schema"] == "oslab.frida-inventory/1" and data["readOnly"] is True
    assert [d["id"] for d in data["devices"]] == ["local", "socket"]
    assert data["devices"][0]["processes"] == [{"pid": 10, "name": "sleep"}]
    assert data["devices"][1]["processes"] is None  # an unnamed remote entry is never probed

    data = json.load(urllib.request.urlopen(f"{web_server}/api/frida/inventory?host=127.0.0.1:27042"))
    assert [d["id"] for d in data["devices"]] == ["tcp@127.0.0.1:27042"]
    assert fake.calls[-1] == ("processes", "tcp@127.0.0.1:27042", "127.0.0.1:27042")


def test_frida_inventory_refuses_targets_outside_the_lab(web_server, monkeypatch):
    import web_ui
    fake = _FakeFrida()
    monkeypatch.setattr(web_ui.frida_inventory, "pick_backend", lambda *args, **kwargs: fake)
    for host in ("8.8.8.8", "example.com"):
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(f"{web_server}/api/frida/inventory?host={host}")
        assert refused.value.code == 400
        assert "error" in json.load(refused.value)
    assert fake.calls == []


def test_winapps_restricted_windows_are_refused_on_uia_and_stream_routes(web_server, monkeypatch):
    """The policy gate also stands in front of the UIA, search, and stream routes from #316/#318."""
    import web_ui

    called = []
    monkeypatch.setattr(web_ui.winapps, "winapps_window_elements", lambda *a, **k: called.append("elements") or {})
    monkeypatch.setattr(web_ui.winapps, "winapps_search_elements", lambda *a, **k: called.append("search") or {})
    monkeypatch.setattr(web_ui.winapps, "winapps_window_stream", lambda *a, **k: called.append("stream") or iter(()))

    def restricted(root, window_id, audience, **kwargs):
        raise web_ui.winapps_guard.GuardError("That window is restricted and cannot be mirrored", "RESTRICTED_WINDOW")

    monkeypatch.setattr(web_ui.winapps_guard, "require_window", restricted)
    for path in ("apps/7/elements", "apps/7/search?q=save", "apps/7/stream"):
        code, body = _http_error(f"{web_server}/api/labs/winapps/{path}")
        assert code == 403 and body["code"] == "RESTRICTED_WINDOW"
    assert called == []  # click and input stop at the input gate: test_winapps_click_and_input_stop_at_the_gate
