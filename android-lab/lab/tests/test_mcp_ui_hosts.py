"""Host-style proofs: every declared UI resource reads, tools attach structuredContent."""
import json
import os
import sys

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))

import mcp_server  # noqa: E402
import mcp_ui  # noqa: E402


def test_all_ui_resources_list_and_read_with_bridge():
    resources = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})["result"]["resources"]
    uris = {item["uri"] for item in resources}
    expected = set(mcp_ui.CLEANUP_WIDGET.values()) | set(mcp_ui.CLEANUP_APP.values())
    expected |= set(mcp_ui.WEBSEC_WIDGET.values()) | set(mcp_ui.MACOS_WIDGET.values())
    expected |= set(mcp_ui.LAB_APP.values())
    assert expected <= uris, sorted(expected - uris)
    for uri in sorted(expected):
        body = mcp_server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": uri},
        })
        content = body["result"]["contents"][0]
        assert "html" in content["mimeType"]
        assert "__oslabUi" in content["text"], uri
        assert "<!-- MCP_BRIDGE -->" not in content["text"], uri


def test_cleanup_widget_tools_return_structured_ui_meta():
    reply = mcp_server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "cleanup_status", "args": {}},
    })
    result = reply["result"]
    assert result["isError"] is False
    assert isinstance(result.get("structuredContent"), dict)
    assert result["_meta"]["ui"]["resourceUri"] == mcp_ui.CLEANUP_WIDGET["status"]


def test_cleanup_apps_return_structured_ui_meta():
    for name, uri in (
        ("cleanup_app_overview", mcp_ui.CLEANUP_APP["overview"]),
        ("cleanup_app_settings", mcp_ui.CLEANUP_APP["settings"]),
    ):
        reply = mcp_server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "args": {}},
        })
        result = reply["result"]
        assert result["isError"] is False, name
        assert result["_meta"]["ui"]["resourceUri"] == uri


def test_websec_and_macos_widgets_are_linked():
    listed = {t["name"]: t for t in mcp_server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    assert listed["websec_status"]["_meta"]["ui"]["resourceUri"] == mcp_ui.WEBSEC_WIDGET["status"]
    assert listed["websec_review"]["_meta"]["ui"]["resourceUri"] == mcp_ui.WEBSEC_WIDGET["review"]
    assert listed["websec_report"]["_meta"]["ui"]["resourceUri"] == mcp_ui.WEBSEC_WIDGET["report"]
    assert listed["macos_apps"]["_meta"]["ui"]["resourceUri"] == mcp_ui.MACOS_WIDGET["apps"]
    assert listed["macos_control_state"]["_meta"]["ui"]["resourceUri"] == mcp_ui.MACOS_WIDGET["control"]
    reply = mcp_server.handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "websec_status", "args": {}},
    })
    assert reply["result"]["isError"] is False
    assert reply["result"]["_meta"]["ui"]["resourceUri"] == mcp_ui.WEBSEC_WIDGET["status"]
    reply = mcp_server.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "macos_control_state", "args": {}},
    })
    assert reply["result"]["isError"] is False
    assert reply["result"]["_meta"]["ui"]["resourceUri"] == mcp_ui.MACOS_WIDGET["control"]


def test_lab_overview_apps_are_callable():
    for name, uri in (
        ("android_app_overview", mcp_ui.LAB_APP["android"]),
        ("ios_app_overview", mcp_ui.LAB_APP["ios"]),
        ("web_app_overview", mcp_ui.LAB_APP["web"]),
        ("source_app_overview", mcp_ui.LAB_APP["source"]),
    ):
        reply = mcp_server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "args": {}},
        })
        result = reply["result"]
        assert result["isError"] is False, (name, result)
        assert result["_meta"]["ui"]["resourceUri"] == uri
        payload = json.loads(result["content"][0]["text"])
        assert isinstance(payload, dict)
