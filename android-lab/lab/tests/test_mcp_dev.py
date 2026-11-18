"""os-lab MCP server dev mode: the `arguments` field, ping, the dev trace and parse errors, and the
smoke client end to end. The server runs as a real subprocess over stdio; nothing here touches the Mac
(only tools/list, ping and an unknown tool are called)."""
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SERVER = os.path.join(REPO_ROOT, "console", "mcp_server.py")
DEV = os.path.join(REPO_ROOT, "scripts", "mcp-dev.py")
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))

import mcp_server  # noqa: E402


def test_tool_call_reads_arguments_and_still_accepts_args(monkeypatch):
    seen = []
    monkeypatch.setattr(mcp_server, "tool_call", lambda name, args: seen.append((name, args)) or {"content": []})
    mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "t", "arguments": {"windowId": 7}}})
    mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "t", "args": {"windowId": 8}}})
    mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "t"}})
    assert seen == [("t", {"windowId": 7}), ("t", {"windowId": 8}), ("t", {})]


def test_ping_answers_an_empty_result():
    assert mcp_server.handle({"jsonrpc": "2.0", "id": 9, "method": "ping"}) == {"jsonrpc": "2.0", "id": 9, "result": {}}


def run_server(lines, *flags, env=None):
    proc = subprocess.run([sys.executable, SERVER, *flags], input="\n".join(lines) + "\n", capture_output=True, text=True,
                          cwd=REPO_ROOT, timeout=60, env={**os.environ, **(env or {})})
    return proc


def test_dev_mode_keeps_stdout_pure_and_writes_a_trace():
    proc = run_server(
        [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), "not json at all"],
        "--dev",
    )
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    assert rows[0] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert rows[1]["error"]["code"] == -32700  # malformed line answered in dev mode
    assert "[mcp-dev] in ping" in proc.stderr and "[mcp-dev] out reply" in proc.stderr
    assert "trace " in proc.stderr
    trace = proc.stderr.split("trace ", 1)[1].splitlines()[0]
    assert os.path.exists(trace)
    assert any(json.loads(line)["dir"] == "out" for line in open(trace, encoding="utf-8"))


def test_without_dev_mode_malformed_lines_are_still_dropped_and_nothing_is_logged():
    proc = run_server(["not json", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})])
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    assert rows == [{"jsonrpc": "2.0", "id": 1, "result": {}}]
    assert proc.stderr == ""


def test_env_var_turns_dev_mode_on():
    proc = run_server([json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})], env={"OSLAB_MCP_DEV": "1"})
    assert "[mcp-dev]" in proc.stderr


def test_smoke_client_passes_against_the_dev_server():
    proc = subprocess.run([sys.executable, DEV, "smoke"], capture_output=True, text=True, cwd=REPO_ROOT, timeout=90)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "smoke passed" in proc.stdout
    assert "tools/list" in proc.stdout


def config(*extra):
    return subprocess.run([sys.executable, DEV, "config", *extra], capture_output=True, text=True, cwd=REPO_ROOT, timeout=30)


def test_config_prints_an_entry_for_every_agent_client():
    proc = config("--proxy")
    assert proc.returncode == 0
    out = proc.stdout
    assert "claude mcp add os-lab-macos --" in out
    assert "codex mcp add os-lab-macos --" in out and "[mcp_servers.os-lab-macos]" in out
    assert "agy mcp add os-lab-macos " in out
    assert '"type": "local"' in out and '"enabled": true' in out  # OpenCode
    assert '"mcpServers"' in out  # ZCode
    assert out.count("mcp-dev.py") >= 5 and "proxy" in out


def test_config_can_print_one_client_and_without_proxy_points_at_the_server():
    proc = config("--client", "codex")
    assert proc.returncode == 0
    assert "console/mcp_server.py" in proc.stdout and "mcp-dev.py" not in proc.stdout
    assert "claude mcp add" not in proc.stdout and "agy mcp add" not in proc.stdout


def test_malformed_arguments_are_a_tool_error_and_the_server_keeps_running():
    """A null or string windowId used to raise TypeError out of handle() and end the process, so the
    client lost its whole session. No Mac access: the id check fails before any window is read."""
    calls = [
        {"name": "macos_click", "arguments": {"windowId": None, "x": 5, "y": 5}},
        {"name": "macos_click", "arguments": {"windowId": "abc"}},
        {"name": "macos_click", "arguments": {"windowId": True}},
        {"name": "macos_apps", "arguments": [1]},
    ]
    lines = [json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": p}) for i, p in enumerate(calls, 1)]
    lines.append(json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping"}))
    proc = run_server(lines)
    assert proc.returncode == 0, proc.stderr
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3, 4, 99]
    for reply in replies[:4]:
        assert reply["result"]["isError"] is True
        assert json.loads(reply["result"]["content"][0]["text"])["code"] == "INVALID_ARGS"
    assert replies[-1]["result"] == {}


def test_an_unexpected_exception_answers_internal_error_instead_of_exiting(monkeypatch):
    monkeypatch.setattr(mcp_server, "tool_call", lambda name, args: (_ for _ in ()).throw(KeyError("x")))
    reply = mcp_server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "t", "arguments": {}}})
    assert reply["result"]["isError"] is True
    assert json.loads(reply["result"]["content"][0]["text"])["code"] == "INVALID_ARGS"
