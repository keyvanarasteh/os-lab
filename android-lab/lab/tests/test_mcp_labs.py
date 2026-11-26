"""Missing-lab MCP modules: status/observe tools are listed and callable."""
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


def test_new_lab_tools_are_listed():
    listed = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    names = {tool["name"] for tool in listed}
    for expected in (
        "android_status", "android_frida_inventory", "android_plan",
        "ios_status", "ios_simulator", "ios_devices", "ios_resources", "ios_plan",
        "linux_status", "linux_plan",
        "web_status", "web_engine_start", "web_engine_stop",
        "source_status", "source_candidates", "source_plan",
        "firewall_status", "firewall_catalog", "firewall_company", "firewall_guides",
    ):
        assert expected in names, expected
    assert all("annotations" in tool for tool in listed if tool["name"].startswith(
        ("android_", "ios_", "linux_", "web_", "source_", "firewall_")))


def test_status_tools_return_lab_payloads():
    for name in ("android_status", "ios_status", "linux_status", "web_status", "source_status", "firewall_status"):
        failed, payload = rpc(name)
        assert not failed, (name, payload)
        assert isinstance(payload, dict)


def test_firewall_catalog_and_company_round_trip():
    failed, catalog = rpc("firewall_catalog")
    assert not failed and "firewalls" in catalog
    slug = catalog["firewalls"][0]["companySlug"]
    failed, company = rpc("firewall_company", {"slug": slug})
    assert not failed and company["slug"] == slug and "files" in company
    failed, bad = rpc("firewall_company", {"slug": "../etc"})
    assert failed


def test_lab_tools_refused_inside_macos_task():
    result = mcp_server.run_task({"steps": [{"tool": "android_status", "args": {}}]})
    assert result["failures"] == 1
    assert "not available inside macos_task" in result["transcript"][0]["error"]
