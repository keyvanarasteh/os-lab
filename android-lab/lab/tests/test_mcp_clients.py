"""MCP-01: connecting os-lab's MCP servers to an MCP client (console/mcp_clients.py)."""
import json
import os
import stat
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "console"))
import mcp_clients  # noqa: E402


@pytest.fixture(autouse=True)
def _no_system_clis(monkeypatch):
    """Only the fake home's folders: a CLI installed on this machine must not leak in."""
    monkeypatch.setattr(mcp_clients, "EXTRA_BIN_DIRS", ("~/.local/bin",))


def env_for(home: Path, path: str = "") -> dict:
    return {"HOME": str(home), "PATH": path}


def fake_cli(folder: Path, name: str, registered: bool = False) -> Path:
    """A CLI that logs its argv and answers `mcp get` like the real one."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / name
    log = folder / f"{name}.log"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        f'if [ "$2" = get ]; then exit {0 if registered else 1}; fi\n'
        "exit 0\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return log


def test_unknown_servers_and_clients_are_refused(tmp_path):
    for server, client in [("rm", "cursor"), ("macos", "evil"), (None, "cursor"), ("macos", ["cursor"])]:
        with pytest.raises(mcp_clients.McpError) as err:
            mcp_clients.preview(server, client, env_for(tmp_path))
        assert err.value.status == 400


def test_server_command_is_this_console_python_and_the_fixed_script():
    command = mcp_clients.server_command("macos")
    assert command[0] == sys.executable
    assert command[1] == str(REPO_ROOT / "console" / "mcp_server.py")


def test_json_client_preview_touches_nothing_and_connect_merges(tmp_path):
    env = env_for(tmp_path)
    config = tmp_path / ".cursor" / "mcp.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "keep": 1}))
    before = config.read_text()

    plan = mcp_clients.preview("macos", "cursor", env)
    assert plan["file"] == str(config)
    assert plan["replaces"] is False
    assert plan["entry"]["args"] == [str(REPO_ROOT / "console" / "mcp_server.py")]
    assert config.read_text() == before

    assert mcp_clients.connect(plan, env)["ok"] is True
    data = json.loads(config.read_text())
    assert data["keep"] == 1 and "other" in data["mcpServers"]
    assert data["mcpServers"]["os-lab-macos"] == plan["entry"]
    assert (config.parent / "mcp.json.oslab.bak").read_text() == before
    # A second preview now reports the existing entry.
    assert mcp_clients.preview("macos", "cursor", env)["replaces"] is True


def test_a_broken_config_file_is_refused_not_overwritten(tmp_path):
    env = env_for(tmp_path)
    config = tmp_path / ".cursor" / "mcp.json"
    config.parent.mkdir()
    config.write_text("{not json")
    with pytest.raises(mcp_clients.McpError) as err:
        mcp_clients.preview("macos", "cursor", env)
    assert err.value.status == 409
    assert config.read_text() == "{not json"


def test_claude_desktop_path_per_platform(tmp_path):
    env = env_for(tmp_path)
    mac = mcp_clients.config_path("claude-desktop", env, "darwin")
    assert mac == tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    assert mcp_clients.config_path("claude-desktop", env, "linux") == tmp_path / ".config" / "Claude" / "claude_desktop_config.json"


def test_cli_client_runs_its_own_mcp_add(tmp_path):
    bin_dir = tmp_path / "bin"
    log = fake_cli(bin_dir, "claude")
    env = env_for(tmp_path, str(bin_dir))
    plan = mcp_clients.preview("macos", "claude-code", env)
    assert plan["argv"][1:7] == ["mcp", "add", "--scope", "user", "os-lab-macos", "--"]
    assert plan["replaces"] is False
    assert "add" not in log.read_text()  # preview only asked `mcp get`
    assert mcp_clients.connect(plan, env)["ok"] is True
    assert "mcp add --scope user os-lab-macos --" in log.read_text()


def test_cli_client_missing_is_reported(tmp_path):
    with pytest.raises(mcp_clients.McpError) as err:
        mcp_clients.preview("macos", "codex", env_for(tmp_path))
    assert err.value.status == 409 and "not installed" in str(err.value)


def test_status_lists_servers_and_clients(tmp_path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"os-lab-macos": {}}}))
    result = mcp_clients.status(env_for(tmp_path))
    assert [s["id"] for s in result["servers"]] == ["macos"]
    cursor = next(c for c in result["clients"] if c["id"] == "cursor")
    assert cursor["installed"] is True and cursor["registered"] == {"macos": True}
    codex = next(c for c in result["clients"] if c["id"] == "codex")
    assert codex["installed"] is False and codex["registered"] == {"macos": False}


@pytest.fixture
def console(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    from web_ui import LabHttpHandler

    server = HTTPServer(("127.0.0.1", 0), LabHttpHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    server.shutdown()


def post(url: str, body: dict, header: bool = True):
    headers = {"Content-Type": "application/json", **({"X-OSLab": "1"} if header else {})}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_console_connect_needs_the_preview_token(console):
    base, home = console
    (home / ".cursor").mkdir()
    status, _ = post(f"{base}/api/mcp/preview", {"server": "macos", "client": "cursor"}, header=False)
    assert status == 403
    status, preview = post(f"{base}/api/mcp/preview", {"server": "macos", "client": "cursor"})
    assert status == 200 and preview["plan"]["client"] == "cursor"
    status, _ = post(f"{base}/api/mcp/connect", {"server": "macos", "client": "cursor", "token": "0" * 64})
    assert status == 409
    assert not (home / ".cursor" / "mcp.json").exists()
    status, result = post(f"{base}/api/mcp/connect", {"server": "macos", "client": "cursor", "token": preview["token"]})
    assert status == 200 and result["ok"] is True
    assert "os-lab-macos" in json.loads((home / ".cursor" / "mcp.json").read_text())["mcpServers"]
    # The same token no longer matches: the file now has the entry, so the plan changed.
    status, _ = post(f"{base}/api/mcp/connect", {"server": "macos", "client": "cursor", "token": preview["token"]})
    assert status == 409
    with urllib.request.urlopen(f"{base}/api/mcp") as res:
        assert json.loads(res.read())["servers"][0]["name"] == "os-lab-macos"
