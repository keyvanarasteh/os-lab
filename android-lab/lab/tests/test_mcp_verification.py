"""CI: mcp_verification.json tool keys match the server's defined tool set."""
import json
import os
import sys

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))

import mcp_server  # noqa: E402


def test_verification_registry_covers_every_defined_tool():
    registry = json.loads(open(os.path.join(REPO_ROOT, "console", "mcp_verification.json")).read())
    defined = {tool["name"] for tool in mcp_server.TOOLS + mcp_server.WIN_TOOLS}
    keys = set(registry["tools"])
    assert keys <= defined, sorted(keys - defined)
    assert defined <= keys, sorted(defined - keys)
    listed = {tool["name"] for tool in mcp_server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    # tools/list is platform-filtered; every listed tool must still be in the registry.
    assert listed <= keys


def test_macos_observe_extras_are_listed_and_callable():
    listed = {tool["name"] for tool in mcp_server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    for name in ("macos_focused", "macos_audit", "macos_sessions"):
        assert name in listed
    # audit/sessions are always callable; focused needs a pid and may fail without AX.
    reply = mcp_server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "macos_audit", "args": {}},
    })
    assert reply["result"]["isError"] is False
    payload = json.loads(reply["result"]["content"][0]["text"])
    assert "rows" in payload
    reply = mcp_server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "macos_sessions", "args": {}},
    })
    assert reply["result"]["isError"] is False
    payload = json.loads(reply["result"]["content"][0]["text"])
    assert "sessions" in payload and "appium" in payload
