"""Cleanup Lab auxiliary MCP tools: inventory, confirm gates, listing."""
import json
import os
import sys

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))

import mcp_server  # noqa: E402


def rpc(name, args=None):
    reply = mcp_server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "args": args or {}},
    })
    result = reply["result"]
    text = next(item["text"] for item in result["content"] if item.get("type") == "text")
    return result["isError"], json.loads(text)


def test_aux_tools_are_listed():
    listed = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    names = {tool["name"] for tool in listed}
    for expected in (
        "cleanup_explorer_roots", "cleanup_explorer_scan",
        "cleanup_deep_roots", "cleanup_deep_scan",
        "cleanup_containers", "cleanup_containers_preview", "cleanup_containers_prune",
        "cleanup_simulators", "cleanup_simulators_preview", "cleanup_simulators_run",
        "cleanup_emulators", "cleanup_emulators_preview", "cleanup_emulators_run",
        "cleanup_vms_scan", "cleanup_packages_scan", "cleanup_leftovers_scan",
        "cleanup_relocation", "cleanup_relocation_plan", "cleanup_relocation_run",
        "cleanup_privileged", "cleanup_privileged_preview", "cleanup_privileged_run",
        "cleanup_simulator_storage", "cleanup_simulator_storage_save",
        "cleanup_custom_entries_add", "cleanup_custom_entries_remove",
    ):
        assert expected in names, expected


def test_aux_inventory_tools_return_payloads():
    for name in (
        "cleanup_explorer_roots", "cleanup_deep_roots", "cleanup_containers",
        "cleanup_simulators", "cleanup_emulators", "cleanup_relocation",
        "cleanup_privileged", "cleanup_simulator_storage",
    ):
        failed, payload = rpc(name)
        assert not failed, (name, payload)
        assert isinstance(payload, dict)


def test_destructive_aux_tools_require_confirm():
    cases = [
        ("cleanup_containers_prune", {"previewId": "x"}),
        ("cleanup_simulators_run", {"previewId": "x"}),
        ("cleanup_emulators_run", {"previewId": "x"}),
        ("cleanup_relocation_run", {"previewId": "x"}),
        ("cleanup_privileged_run", {"previewId": "x"}),
        ("cleanup_custom_entries_remove", {"entryId": "custom.demo"}),
    ]
    for name, args in cases:
        failed, payload = rpc(name, args)
        assert failed, name
        message = payload.get("error") or payload.get("message") or json.dumps(payload)
        assert "confirm" in message.lower() or payload.get("code") == "CONFIRM_REQUIRED"
