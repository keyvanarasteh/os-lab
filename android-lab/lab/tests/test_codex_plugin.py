"""Codex local plugin package and launcher proofs."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "console"))
import codex_plugin as engine  # noqa: E402


def launcher():
    path = os.path.join(engine.plugin_dir(ROOT), "launcher.py")
    spec = importlib.util.spec_from_file_location("oslab_codex_launcher_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checkout_copy(tmp_path):
    root = tmp_path / "repo"
    for rel in ("plugins/codex", "console/mcp_skills", ".agents/plugins"):
        shutil.copytree(os.path.join(ROOT, rel), root / rel)
    (root / "LICENSE").write_text("Apache-2.0\n")
    return root


def test_package_checks_and_generated_skills():
    assert engine.check(ROOT)["ok"]
    assert engine.skill_drift(ROOT) == []
    rows = engine.requirements()["requirements"]
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["source"].startswith("https://developers.openai.com/") for r in rows)


def test_broken_marketplace_and_skill_are_reported(tmp_path):
    root = checkout_copy(tmp_path)
    assert engine.check(str(root))["ok"]
    market_path = root / ".agents/plugins/marketplace.json"
    market = json.loads(market_path.read_text())
    market["plugins"][0]["source"]["path"] = "./../outside"
    market_path.write_text(json.dumps(market))
    assert any(row["id"] == "marketplace.entry" and row["result"] == "fail"
               for row in engine.check(str(root))["results"])
    (root / "plugins/codex/os-lab/skills/macos/SKILL.md").write_text("broken\n")
    assert any(row["id"] == "skills.generated" and row["result"] == "fail"
               for row in engine.check(str(root))["results"])


def test_checkout_resolution_and_setup_only_protocol(tmp_path):
    module = launcher()
    package = os.path.join(ROOT, engine.PLUGIN_REL, "launcher.py")
    assert module.find_checkout(env={}, here=package)[0] == ROOT
    assert module.find_checkout(env={"OSLAB_ROOT": str(tmp_path)}, here=package)[0] is None
    copied = tmp_path / "cache" / "launcher.py"
    copied.parent.mkdir()
    shutil.copy(package, copied)
    env = dict(os.environ, OSLAB_ROOT=str(tmp_path))
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "codex_plugin_doctor"}},
    ]
    done = subprocess.run([sys.executable, str(copied)], input="\n".join(json.dumps(m) for m in messages)+"\n",
                          capture_output=True, text=True, env=env, timeout=10)
    assert done.returncode == 0 and done.stderr == ""
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {
        "codex_plugin_doctor", "codex_plugin_status"}
    assert "OSLAB_ROOT" in replies[2]["result"]["content"][0]["text"]
    env["OSLAB_ROOT"] = ROOT
    healthy = subprocess.run([sys.executable, str(copied)], input=json.dumps({
        "jsonrpc": "2.0", "id": 4, "method": "tools/list"}) + "\n",
        capture_output=True, text=True, env=env, timeout=10)
    assert healthy.returncode == 0
    names = {row["name"] for row in json.loads(healthy.stdout)["result"]["tools"]}
    assert "macos_apps" in names and "codex_plugin_verify" in names


def test_isolated_cli_marketplace_round_trip(tmp_path, monkeypatch):
    if not shutil.which("codex"):
        pytest.skip("Codex CLI unavailable")
    home = tmp_path / "codex-home"
    home.mkdir()
    env = dict(os.environ, CODEX_HOME=str(home))
    monkeypatch.setenv("CODEX_HOME", str(home))
    add = subprocess.run(["codex", "plugin", "marketplace", "add", ROOT, "--json"],
                         capture_output=True, text=True, env=env, timeout=30)
    assert add.returncode == 0, add.stderr
    listing = subprocess.run(["codex", "plugin", "list", "--marketplace", "os-lab-local", "--available", "--json"],
                             capture_output=True, text=True, env=env, timeout=30)
    assert listing.returncode == 0, listing.stderr
    data = json.loads(listing.stdout)
    assert any(row["pluginId"] == engine.PLUGIN_ID for row in data["available"])
    preview = engine.plan(ROOT, "install")
    assert preview["terminalOnly"] and len(preview["commands"]) == 1
    with pytest.raises(engine.PluginError) as refusal:
        engine.apply(ROOT, preview["token"], True, audience="agent")
    assert refusal.value.code == "TERMINAL_ONLY"
    installed = subprocess.run(["codex", "plugin", "add", engine.PLUGIN_ID, "--json"],
                               capture_output=True, text=True, env=env, timeout=30)
    assert installed.returncode == 0, installed.stderr
    assert json.loads(installed.stdout)["pluginId"] == engine.PLUGIN_ID
    assert engine.verify(ROOT)["ok"]


def test_management_tools_are_read_only_or_refuse_agent_apply():
    import mcp_server
    listed = {tool["name"]: tool for tool in mcp_server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    assert listed["codex_plugin_requirements"]["annotations"]["readOnlyHint"]
    assert listed["codex_plugin_apply"]["annotations"]["readOnlyHint"] is False
    request = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "codex_plugin_apply", "arguments": {"token": "none", "confirm": True}}}
    refusal = mcp_server.handle(request)["result"]
    assert refusal["isError"] and "TERMINAL_ONLY" in refusal["content"][0]["text"]
    task = mcp_server.run_task({"steps": [{"tool": "codex_plugin_apply", "args": {}}]})
    assert task["failures"] == 1 and "not available" in task["transcript"][0]["error"]
    resources = mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})["result"]
    assert any(row["uri"] == "oslab://codex-plugin/requirements" for row in resources["resources"])
    prompts = mcp_server.handle({"jsonrpc": "2.0", "id": 4, "method": "prompts/list"})["result"]
    assert any(row["name"] == "codex_plugin_setup_flow" for row in prompts["prompts"])
