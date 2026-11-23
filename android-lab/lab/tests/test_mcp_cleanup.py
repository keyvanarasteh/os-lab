"""CUX-10: the Cleanup Lab MCP tools run the same engine and guards as the dashboard."""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))
sys.path.insert(0, os.path.join(REPO_ROOT, "cleanup-lab", "engine"))
sys.path.insert(0, os.path.dirname(__file__))

import mcp_server  # noqa: E402
from test_cleanup_console import catalog_cache_target, clean_jobs  # noqa: E402,F401


def rpc(name, args=None):
    reply = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "args": args or {}}})
    payload = json.loads(reply["result"]["content"][0]["text"])
    return reply["result"]["isError"], payload


def test_every_cleanup_tool_is_listed_with_a_schema():
    listed = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    names = {tool["name"] for tool in listed}
    expected = {"cleanup_status", "cleanup_catalog", "cleanup_volumes", "cleanup_monitor", "cleanup_permissions", "cleanup_bookmarks",
                "cleanup_history", "cleanup_widget", "cleanup_preferences", "cleanup_job", "cleanup_scan", "cleanup_suggest",
                "cleanup_review", "cleanup_quick_clean_plan", "cleanup_clean", "cleanup_preferences_save", "cleanup_monitor_config",
                "cleanup_monitor_evaluate", "cleanup_bookmark_add", "cleanup_bookmark_remove", "cleanup_reveal"}
    assert expected <= names
    assert "macos_stop" in names  # the macOS tools are still there
    assert all(tool["inputSchema"]["type"] == "object" for tool in listed)


def test_review_scans_suggests_and_plans_but_never_cleans(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    with open(os.path.join(target, "big.bin"), "wb") as handle:
        handle.write(b"x" * (2 * 1024 * 1024))
    failed, review = rpc("cleanup_review", {"entryIds": ["system.user-caches"], "timeoutSeconds": 120})  # the plan is limited to the temp tree
    assert not failed
    assert review["stage"] == "plan"
    assert "system.user-caches" in [item["id"] for item in review["suggestion"]["items"]]
    assert [row["entryId"] for row in review["plan"]["result"]["items"]] == ["system.user-caches"]
    assert review["plan"]["state"] == "done" and review["plan"]["result"]["totals"]["ready"] >= 1
    assert os.path.exists(os.path.join(target, "big.bin")), "review must not remove anything"
    # Cleaning needs an explicit confirmation, and refuses without it.
    failed, refusal = rpc("cleanup_clean", {"planId": review["plan"]["result"]["planId"], "confirm": False})
    assert failed and refusal["code"] == "CONFIRM_REQUIRED"
    assert os.path.exists(os.path.join(target, "big.bin"))
    failed, result = rpc("cleanup_clean", {"planId": review["plan"]["result"]["planId"], "confirm": True, "timeoutSeconds": 120})
    assert not failed and result["state"] == "done", result["error"]
    assert result["result"]["mode"] == "trash"
    assert not os.path.exists(os.path.join(target, "big.bin"))


def test_tools_refuse_paths_unknown_arguments_and_unknown_ids(tmp_path, monkeypatch):
    catalog_cache_target(tmp_path, monkeypatch)
    for name, args in (("cleanup_scan", {"entryIds": ["no.such-entry"]}), ("cleanup_reveal", {"entryId": "/etc"}),
                       ("cleanup_status", {"path": "/"}), ("cleanup_clean", {"planId": "x", "confirm": True, "mode": "delete"}),
                       ("cleanup_suggest", {"jobId": "nope"})):
        failed, payload = rpc(name, args)
        assert failed and payload["error"], name


def test_preferences_and_monitor_settings_round_trip_through_the_tools(tmp_path, monkeypatch):
    catalog_cache_target(tmp_path, monkeypatch)
    failed, saved = rpc("cleanup_preferences_save", {"suggestion": {"mode": "extended", "exclude": ["developers.npm"]}})
    assert not failed and saved["suggestion"]["mode"] == "extended"
    assert rpc("cleanup_preferences")[1]["suggestion"]["exclude"] == ["developers.npm"]
    failed, bad = rpc("cleanup_preferences_save", {"suggestion": {"mode": "wild"}})
    assert failed
    config = {"enabled": False, "intervalSeconds": 300, "cooldownSeconds": 3600, "reminderSeconds": 3600, "notify": False,
              "volumes": [{"mountPoint": "", "minFreeBytes": 1, "minFreePercent": 5, "criticalFreeBytes": 1, "enabled": True}]}
    failed, monitor = rpc("cleanup_monitor_config", {"config": config})
    assert not failed and monitor["reminderSeconds"] == 3600 and monitor["notify"] is False


def test_cleanup_tools_do_not_run_inside_a_macos_task():
    result = mcp_server.run_task({"steps": [{"tool": "cleanup_clean", "args": {"planId": "x", "confirm": True}}]})
    assert result["failures"] == 1
    assert "not available inside macos_task" in result["transcript"][0]["error"]
