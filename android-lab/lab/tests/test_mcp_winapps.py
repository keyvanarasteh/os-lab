"""Contracts for the read-only Windows Apps Lab tools on the stdio MCP server."""

import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "console")))

import mcp_server
import winapps
import winapps_guard

WIN_TOOL_NAMES = {"winapps_apps", "winapps_screenshot", "winapps_capabilities", "winapps_doctor", "winapps_audit"}


def rpc(method, params=None):
    return mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})["result"]


def call(name, args=None):
    return rpc("tools/call", {"name": name, "args": args or {}})


def payload(result):
    return json.loads(result["content"][0]["text"])


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")


def test_win_tools_are_listed_only_on_windows(monkeypatch):
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    assert WIN_TOOL_NAMES <= {tool["name"] for tool in rpc("tools/list")["tools"]}
    monkeypatch.setattr(mcp_server.sys, "platform", "linux")
    listed = rpc("tools/list")["tools"]
    assert not any(tool["name"].startswith("winapps_") for tool in listed)
    assert listed == mcp_server.TOOLS


def test_there_is_no_arm_or_input_tool(on_windows):
    names = {tool["name"] for tool in rpc("tools/list")["tools"] if tool["name"].startswith("winapps_")}
    assert names == WIN_TOOL_NAMES
    for name in names:
        assert not any(word in name for word in ("arm", "click", "type", "key", "paste", "scroll", "set", "perform"))


def test_winapps_apps_is_agent_filtered(on_windows, monkeypatch):
    seen = {}

    def fake(root, audience, *, tool=None):
        seen.update(audience=audience, tool=tool)
        return {"available": True, "reason": None, "windows": [], "withheld": 2}

    monkeypatch.setattr(winapps_guard, "list_windows", fake)
    result = call("winapps_apps")
    assert result["isError"] is False and payload(result)["withheld"] == 2
    assert seen == {"audience": "agent", "tool": "winapps_apps"}


def test_winapps_screenshot_returns_image_content(on_windows, monkeypatch):
    png = b"\x89PNG\r\n\x1a\nxx"
    seen = {}

    def fake(root, window_id, audience, *, tool=None):
        seen.update(window_id=window_id, audience=audience, tool=tool)
        return png

    monkeypatch.setattr(winapps_guard, "screenshot", fake)
    result = call("winapps_screenshot", {"windowId": 12})
    assert result["isError"] is False
    assert result["content"] == [{"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}]
    assert seen == {"window_id": 12, "audience": "agent", "tool": "winapps_screenshot"}


def test_guard_and_collector_errors_become_is_error_with_code(on_windows, monkeypatch):
    def refuse(root, window_id, audience, *, tool=None):
        raise winapps_guard.GuardError("restricted", "RESTRICTED_WINDOW")

    monkeypatch.setattr(winapps_guard, "screenshot", refuse)
    refused = call("winapps_screenshot", {"windowId": 3})
    assert refused["isError"] is True
    assert payload(refused) == {"error": "restricted", "code": "RESTRICTED_WINDOW", "retry": "never"}

    def broken(root, audience, *, tool=None):
        raise winapps.WinAppError("enumeration failed")

    monkeypatch.setattr(winapps_guard, "list_windows", broken)
    failed = call("winapps_apps")
    assert failed["isError"] is True and payload(failed) == {"error": "enumeration failed", "code": "CAPTURE_FAILED"}


def test_winapps_capabilities_reports_policy_summary_and_input_unsupported(on_windows, monkeypatch, tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"allowedApps": ["Notepad", "Calc"], "restrictedApps": ["Vault"]}))
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(policy))
    result = call("winapps_capabilities")
    assert payload(result) == {"allowedApps": 2, "restrictedApps": 1, "restrictedTitles": 0, "policyError": None,
                               "exists": True, "audience": "agent", "inputSupported": False}
    assert "Notepad" not in result["content"][0]["text"]


def test_winapps_doctor_and_audit_use_the_agent_audience(on_windows, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(winapps_guard, "doctor", lambda root, audience="agent", *, tool=None:
                        seen.update(audience=audience, tool=tool) or {"capture": True})
    assert payload(call("winapps_doctor")) == {"capture": True}
    assert seen == {"audience": "agent", "tool": "winapps_doctor"}
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(tmp_path / "audit"))
    winapps_guard._reset_audit()
    winapps_guard.audit(None, "list", audience="agent", tool="winapps_apps")
    # The audit tool is itself an agent call, so it appears in what it returns.
    assert [row["kind"] for row in payload(call("winapps_audit"))["rows"]] == ["list", "audit"]
    winapps_guard._reset_audit()


def test_winapps_tool_on_a_non_windows_host_is_a_clean_error(monkeypatch):
    monkeypatch.setattr(mcp_server.sys, "platform", "linux")
    result = call("winapps_apps")
    assert result["isError"] is True and payload(result)["code"] == "NOT_SUPPORTED"


@pytest.mark.parametrize("platform,name", [("win32", "os-lab-windows"), ("linux", "os-lab-macos"),
                                           ("darwin", "os-lab-macos")])
def test_server_name_depends_on_platform(monkeypatch, platform, name):
    monkeypatch.setattr(mcp_server.sys, "platform", platform)
    assert rpc("initialize")["serverInfo"]["name"] == name


@pytest.mark.parametrize("args", ["x", 5, [1]])
def test_non_object_arguments_are_a_clean_error_not_a_crash(on_windows, args):
    result = rpc("tools/call", {"name": "winapps_screenshot", "args": args})
    assert result["isError"] is True and payload(result)["code"] == "INVALID_ARGS"


# ── Sourcery review findings ──────────────────────────────────────────────────

@pytest.mark.parametrize("args", [[], 0, "", False])
def test_falsey_non_object_arguments_are_refused_too(on_windows, args):
    result = rpc("tools/call", {"name": "winapps_screenshot", "args": args})
    assert result["isError"] is True and payload(result)["code"] == "INVALID_ARGS"


def test_every_agent_tool_call_is_audited_including_argument_refusals(on_windows, monkeypatch, tmp_path):
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("OSLAB_WINAPPS_POLICY", str(tmp_path / "absent.json"))
    winapps_guard._reset_audit()
    call("winapps_capabilities")
    call("winapps_audit")
    rpc("tools/call", {"name": "winapps_screenshot", "args": "x"})
    seen = [(row["kind"], row["code"], row["tool"]) for row in winapps_guard.audit_rows(200)["rows"]]
    assert seen == [("capabilities", None, "winapps_capabilities"), ("audit", None, "winapps_audit"),
                    ("refused", "INVALID_ARGS", "winapps_screenshot")]
    winapps_guard._reset_audit()


def test_winapps_audit_tool_shows_agent_rows_without_restricted_identities(on_windows, monkeypatch, tmp_path):
    monkeypatch.setenv("OSLAB_WINAPPS_AUDIT_DIR", str(tmp_path / "audit"))
    winapps_guard._reset_audit()
    winapps_guard.audit(None, "refused", audience="agent", app="1Password", window_id=3, code="RESTRICTED_WINDOW")
    winapps_guard.audit(None, "refused", audience="human", app="msedge", window_id=4, code="RESTRICTED_WINDOW")
    rows = payload(call("winapps_audit"))["rows"]
    assert [(row["audience"], row["app"]) for row in rows][:1] == [("agent", None)]
    assert "msedge" not in json.dumps(rows) and "1Password" not in json.dumps(rows)
    winapps_guard._reset_audit()


# ── MCP spec: tool arguments travel as `arguments` ────────────────────────────

def test_the_spec_key_arguments_reaches_the_tool(on_windows, monkeypatch):
    seen = {}

    def fake(root, window_id, audience, *, tool=None):
        seen["window_id"] = window_id
        return b"\x89PNG\r\n\x1a\nxx"

    monkeypatch.setattr(winapps_guard, "screenshot", fake)
    result = rpc("tools/call", {"name": "winapps_screenshot", "arguments": {"windowId": 21}})
    assert result["isError"] is False and seen == {"window_id": 21}


def test_arguments_wins_over_the_legacy_args_key(on_windows, monkeypatch):
    seen = {}
    monkeypatch.setattr(winapps_guard, "screenshot",
                        lambda root, window_id, audience, *, tool=None: seen.update(id=window_id) or b"\x89PNG\r\n\x1a\nxx")
    rpc("tools/call", {"name": "winapps_screenshot", "arguments": {"windowId": 5}, "args": {"windowId": 9}})
    assert seen == {"id": 5}


@pytest.mark.parametrize("arguments", ["x", 5, [1], [], 0])
def test_non_object_arguments_key_is_refused_for_windows_tools(on_windows, arguments):
    result = rpc("tools/call", {"name": "winapps_screenshot", "arguments": arguments})
    assert result["isError"] is True and payload(result)["code"] == "INVALID_ARGS"


def test_macos_tools_also_read_the_spec_key(monkeypatch):
    seen = {}
    monkeypatch.setattr(mcp_server.oslab, "macos_search_elements",
                        lambda root, window_id, query: seen.update(w=window_id, q=query) or {"count": 0, "hits": []})
    result = rpc("tools/call", {"name": "macos_search", "arguments": {"windowId": 3, "query": "Save"}})
    assert result["isError"] is False and seen == {"w": 3, "q": "Save"}
