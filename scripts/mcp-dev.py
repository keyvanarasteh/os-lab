#!/usr/bin/env python3
"""Dev mode for the os-lab MCP server (console/mcp_server.py), a stdio server that clients launch themselves.

  scripts/mcp-dev.py smoke [--call NAME [--args JSON]]   start the server in dev mode, run the handshake,
                                                         tools/list, ping and an error probe, print the result,
                                                         exit non-zero if any step fails
  scripts/mcp-dev.py proxy                               stand in for the server in a client's config; run the real
                                                         server with --dev and restart it when console/*.py changes,
                                                         replaying the client's handshake so the session survives
  scripts/mcp-dev.py config [--proxy] [--client NAME]    print the registration for claude, codex, agy, opencode, zcode

Only the server runs here. Input tools still need the human to arm control mode from the dashboard, and a
`--call` of an input tool is refused by the console unless it is armed. Requests in flight when the proxy
restarts the server are lost (logged), which is acceptable for dev.

Logs and the JSONL trace of every message go to test-results/mcp-dev/ (git-ignored); stdout of the server
stays pure JSON-RPC.
# @lat: [[ios-lab#Native macOS path#MCP dev mode]]
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import time

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SERVER = os.path.join(REPO, "console", "mcp_server.py")
WATCH_DIR = os.path.join(REPO, "console")


def server_cmd() -> list[str]:
    return [sys.executable, SERVER, "--dev"]


class Client:
    """A line-delimited JSON-RPC client over the server's stdio."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(server_cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO)
        self._id = 0
        self.stderr_lines: list[str] = []
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr
        for line in self.proc.stderr:
            self.stderr_lines.append(line.rstrip())

    def send(self, payload: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        self._id += 1
        message: dict = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        assert self.proc.stdout
        result: dict = {}

        def read() -> None:
            nonlocal result
            line = self.proc.stdout.readline()  # type: ignore[union-attr]
            result = json.loads(line) if line else {"error": {"message": "server closed stdout"}}

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(timeout)
        if reader.is_alive():
            return {"error": {"message": f"no reply to {method} within {timeout:.0f}s"}}
        return result

    def close(self) -> None:
        try:
            assert self.proc.stdin
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - best effort on shutdown
            self.proc.kill()


def cmd_smoke(args: argparse.Namespace) -> int:
    client = Client()
    failed = 0

    def check(name: str, ok: bool, info: str = "") -> None:
        nonlocal failed
        print(f"{'ok  ' if ok else 'FAIL'} {name}{(' - ' + info) if info else ''}")
        failed += 0 if ok else 1

    try:
        init = client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "mcp-dev-smoke", "version": "0"}})
        info = (init.get("result") or {}).get("serverInfo") or {}
        check("initialize", bool(info), f"{info.get('name')} {info.get('version')}")
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = (client.request("tools/list").get("result") or {}).get("tools") or []
        check("tools/list", len(tools) > 0, f"{len(tools)} tools: " + ", ".join(t["name"] for t in tools[:6]) + (" ..." if len(tools) > 6 else ""))
        check("ping", client.request("ping").get("result") == {})
        probe = client.request("tools/call", {"name": "__dev_probe__", "arguments": {}})
        check("unknown tool is an isError result, not a crash", bool((probe.get("result") or {}).get("isError")))
        if args.call:
            payload = json.loads(args.args or "{}")
            reply = client.request("tools/call", {"name": args.call, "arguments": payload}, timeout=60)
            result = reply.get("result") or {}
            text = " ".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")
            image = any(part.get("type") == "image" for part in result.get("content", []))
            check(f"tools/call {args.call}", "result" in reply and not result.get("isError"), (text[:300] + (" [+image]" if image else "")) or json.dumps(reply)[:300])
    finally:
        client.close()
    trace = next((line.split("trace ", 1)[1] for line in client.stderr_lines if "trace " in line), "")
    if trace:
        print(f"trace: {trace}")
    print("smoke passed" if not failed else f"smoke FAILED ({failed})")
    return 1 if failed else 0


def snapshot() -> dict[str, float]:
    out: dict[str, float] = {}
    for name in os.listdir(WATCH_DIR):
        if name.endswith((".py", ".json")):
            try:
                out[name] = os.stat(os.path.join(WATCH_DIR, name)).st_mtime
            except OSError:
                pass
    return out


def cmd_proxy(_: argparse.Namespace) -> int:
    """Forward the client's stdio to a dev-mode server and restart it when its files change."""
    lock = threading.Lock()
    state: dict = {"proc": None, "init": None, "initialized": False, "swallow": 0}

    def log(message: str) -> None:
        sys.stderr.write(f"[mcp-dev proxy] {message}\n")
        sys.stderr.flush()

    def start() -> None:
        proc = subprocess.Popen(server_cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=REPO)
        state["proc"] = proc
        threading.Thread(target=pump_out, args=(proc,), daemon=True).start()

    def pump_out(proc: subprocess.Popen) -> None:
        assert proc.stdout
        for line in proc.stdout:
            with lock:
                if state["proc"] is not proc:
                    return
                if state["swallow"] > 0:  # the reply to the handshake we replayed on restart
                    state["swallow"] -= 1
                    continue
            sys.stdout.write(line)
            sys.stdout.flush()

    def write_child(text: str) -> None:
        proc = state["proc"]
        try:
            proc.stdin.write(text)
            proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            log("server pipe closed; waiting for the next restart")

    def restart(reason: str) -> None:
        with lock:
            old = state["proc"]
            log(f"restarting server: {reason}")
            try:
                old.stdin.close()
            except OSError:
                pass
            try:
                old.wait(timeout=3)
            except subprocess.TimeoutExpired:
                old.kill()
            start()
            if state["init"] is not None:
                write_child(state["init"] + "\n")
                state["swallow"] = 1
                if state["initialized"]:
                    write_child(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            log("server restarted; the client session continues (requests in flight were lost)")

    def watch() -> None:
        seen = snapshot()
        while True:
            time.sleep(0.5)
            now = snapshot()
            changed = [n for n in now if seen.get(n) != now[n]] + [n for n in seen if n not in now]
            if changed:
                time.sleep(0.3)  # let an editor finish writing
                seen = snapshot()
                restart("changed: " + ", ".join(sorted(set(changed))[:4]))
            else:
                seen = now

    start()
    threading.Thread(target=watch, daemon=True).start()
    log(f"watching {WATCH_DIR} (*.py, *.json); server runs with --dev")
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            message = {}
        with lock:
            if message.get("method") == "initialize":
                state["init"] = line.strip()
            elif message.get("method") == "notifications/initialized":
                state["initialized"] = True
            write_child(line if line.endswith("\n") else line + "\n")
    with lock:
        try:
            state["proc"].stdin.close()
        except OSError:
            pass
    return 0


CLIENTS = ("claude", "codex", "agy", "opencode", "zcode")
NAME = "os-lab-macos"


def client_entries(command: list[str]) -> dict[str, list[str]]:
    """Per client: how to register the server, as printable lines. Verified against each CLI's `mcp add --help`
    and the config files on this machine; ZCode's location is not verified."""
    quoted = shlex.join(command)
    json_entry = json.dumps({"mcpServers": {NAME: {"command": command[0], "args": command[1:]}}}, indent=2)
    return {
        "claude": [
            "Claude Code (local scope, this project):",
            f"  claude mcp add {NAME} -- {quoted}",
            "  Add `--scope user` after `add` for every project, or `--scope project` to write .mcp.json.",
        ],
        "codex": [
            "Codex CLI (writes ~/.codex/config.toml):",
            f"  codex mcp add {NAME} -- {quoted}",
            "  or by hand:",
            f"  [mcp_servers.{NAME}]",
            f"  command = {json.dumps(command[0])}",
            f"  args = {json.dumps(command[1:])}",
        ],
        "agy": [
            "Antigravity CLI, agy (writes ~/.gemini/config/mcp_config.json):",
            f"  agy mcp add {NAME} {quoted}",
        ],
        "opencode": [
            "OpenCode (merge into ~/.config/opencode/opencode.json, or opencode.json in a project; `opencode mcp add` is interactive):",
            json.dumps({"mcp": {NAME: {"type": "local", "command": command, "enabled": True}}}, indent=2),
        ],
        "zcode": [
            "ZCode (add in its MCP settings; I could not find a config file for it to verify, so this is the common mcpServers shape):",
            json_entry,
        ],
    }


def cmd_config(args: argparse.Namespace) -> int:
    script = os.path.join(REPO, "scripts", "mcp-dev.py") if args.proxy else SERVER
    command = [sys.executable, script] + (["proxy"] if args.proxy else [])
    entries = client_entries(command)
    chosen = CLIENTS if args.client == "all" else (args.client,)
    for client in chosen:
        print("\n".join(entries[client]) + "\n")
    print("Nothing is written for you. The human arms control mode from the dashboard; there is deliberately no arm tool.")
    if args.proxy:
        print(f"The proxy path points at this checkout ({REPO}); register again from your main checkout after it merges.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    smoke = sub.add_parser("smoke", help="handshake, tools/list, ping and an error probe against a dev-mode server")
    smoke.add_argument("--call", help="also call this tool")
    smoke.add_argument("--args", help="JSON arguments for --call")
    smoke.set_defaults(fn=cmd_smoke)
    sub.add_parser("proxy", help="restart-on-change stdio proxy for a client config").set_defaults(fn=cmd_proxy)
    config = sub.add_parser("config", help="print the client config for this checkout")
    config.add_argument("--proxy", action="store_true", help="point the client at the restart-on-change proxy")
    config.add_argument("--client", choices=("all",) + CLIENTS, default="all", help="print one client's entry (default all)")
    config.set_defaults(fn=cmd_config)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
