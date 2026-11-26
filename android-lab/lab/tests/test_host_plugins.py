"""Cursor / ZCode / Grok Build local plugin package and launcher proofs."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "console"))
import host_plugin as engine  # noqa: E402

HOSTS = ("cursor", "zcode", "grok")


def launcher(host):
    path = os.path.join(engine.plugin_dir(ROOT, host), "launcher.py")
    spec = importlib.util.spec_from_file_location("oslab_{0}_launcher_test".format(host), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("host", HOSTS)
def test_package_checks_and_generated_skills(host):
    assert engine.check(ROOT, host)["ok"]
    assert engine.skill_drift(ROOT, host) == []
    rows = engine.requirements(host)["requirements"]
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["source"].startswith("https://") for r in rows)
    assert engine.checkout_version(ROOT, host) == "0.1.0"


@pytest.mark.parametrize("host", HOSTS)
def test_checkout_resolution_and_setup_only_protocol(host, tmp_path):
    module = launcher(host)
    package = os.path.join(engine.plugin_dir(ROOT, host), "launcher.py")
    assert module.find_checkout(env={}, here=package)[0] == ROOT
    assert module.find_checkout(env={"OSLAB_ROOT": str(tmp_path)}, here=package)[0] is None
    copied = tmp_path / "cache" / "launcher.py"
    copied.parent.mkdir()
    shutil.copy(package, copied)
    env = dict(os.environ, OSLAB_ROOT=str(tmp_path))
    doctor = host + "_plugin_doctor"
    status = host + "_plugin_status"
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": doctor}},
    ]
    done = subprocess.run([sys.executable, str(copied)], input="\n".join(json.dumps(m) for m in messages) + "\n",
                          capture_output=True, text=True, env=env, timeout=10)
    assert done.returncode == 0 and done.stderr == ""
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {doctor, status}
    assert "OSLAB_ROOT" in replies[2]["result"]["content"][0]["text"]


@pytest.mark.parametrize("host", HOSTS)
def test_plan_apply_refuses_agent_and_config_round_trip(host, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for rel in (
        "plugins/{0}".format(host),
        "console/mcp_skills",
        "plugins/mcp/{0}".format(host),
    ):
        src = os.path.join(ROOT, rel)
        if os.path.isdir(src):
            shutil.copytree(src, root / rel)
    if host == "grok":
        shutil.copytree(os.path.join(ROOT, ".grok-plugin"), root / ".grok-plugin")
    for name in ("labctl", "console/mcp_server.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# stub\n")
    # Copy catalogs and engine pieces needed by check annotations
    for name in ("host_plugin.py", "mcp_host_plugins.py", "mcp_common.py", "mcp_ui.py",
                 "oslab.py", "{0}_requirements.json".format(host)):
        src = os.path.join(ROOT, "console", name)
        if os.path.isfile(src):
            shutil.copy(src, root / "console" / name)

    preview = engine.plan(str(root), host, "install")
    assert preview["terminalOnly"] is True
    with pytest.raises(engine.PluginError) as refused:
        engine.apply(str(root), host, preview["token"], True, audience="agent")
    assert refused.value.code == "TERMINAL_ONLY"

    # Fresh plan for terminal apply with fake TTY
    preview = engine.plan(str(root), host, "install")
    monkeypatch.setattr(engine, "_interactive", lambda: True)
    result = engine.apply(str(root), host, preview["token"], True, audience="terminal")
    assert result["ok"] is True
    state = engine.status(str(root), host)
    assert state["installed"] is True
    assert os.path.isfile(engine.config_path(str(root), host))


def test_mcp_tools_registered():
    import mcp_host_plugins
    names = {tool["name"] for tool in mcp_host_plugins.TOOLS}
    for host in HOSTS:
        for action in ("requirements", "doctor", "status", "updates", "check", "plan", "apply", "verify"):
            assert "{0}_plugin_{1}".format(host, action) in names
