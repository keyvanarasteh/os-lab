"""MCP client registration (MCP-01): connect os-lab's MCP servers to an MCP client.

os-lab ships stdio MCP servers (today the macOS Lab's guarded surface,
``console/mcp_server.py``). A client — Claude Code, Codex, Claude Desktop,
Cursor — launches such a server itself, so "connecting" one means adding an
entry to that client's own configuration. This module is the only place that
does it, and it follows the console's preview → token → run rule:

- ``status`` is read-only: which servers exist, which clients are installed,
  and whether each already has the entry.
- ``preview`` computes the exact change — the CLI argv it would run, or the JSON
  file and entry it would write — without touching anything.
- ``connect`` recomputes that preview and runs it only when the signed token
  from the preview still matches, so the user confirms exactly what happens.

Servers and clients are fixed tables. Nothing a page or an ``oslab://`` URL sends
becomes a command, an argument or a path: requests name a server id and a
client id, and both are looked up here.

Connecting gives an agent no control. The macOS server's input tools still need
the human to arm control mode in the dashboard, and the panic stop still ends
everything.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Servers os-lab offers, by id. ``name`` is the entry name a client lists.
SERVERS: dict[str, dict] = {
    "macos": {
        "name": "os-lab-macos",
        "label": "macOS Lab",
        "description": "Observe, act, verify and stop on this Mac's app windows. Input tools need armed control mode.",
        "script": "console/mcp_server.py",
    },
}

#: Clients this module can register a server with, by id.
#: ``cli`` clients run their own ``mcp add``; ``json`` clients get an entry merged
#: into their config file under ``mcpServers``.
CLIENTS: dict[str, dict] = {
    "claude-code": {"label": "Claude Code", "kind": "cli", "binary": "claude"},
    "codex": {"label": "Codex CLI", "kind": "cli", "binary": "codex"},
    "claude-desktop": {"label": "Claude Desktop", "kind": "json"},
    "cursor": {"label": "Cursor", "kind": "json"},
}

#: Where GUI-started consoles often miss a CLI on PATH.
EXTRA_BIN_DIRS = ("~/.local/bin", "~/.claude/local", "~/.npm-global/bin", "/opt/homebrew/bin", "/usr/local/bin")
CLI_TIMEOUT = 20


class McpError(Exception):
    """A refused or failed request, with the HTTP status the console answers."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _home(env: dict | None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("HOME") or env.get("USERPROFILE") or str(Path.home()))


def server_command(server_id: str, python: str | None = None) -> list[str]:
    """The argv a client runs to start one server: this console's Python and the script."""
    server = _server(server_id)
    return [python or sys.executable, str(REPO_ROOT / server["script"])]


def config_path(client_id: str, env: dict | None = None, platform: str | None = None) -> Path | None:
    """The config file a ``json`` client reads; None for ``cli`` clients."""
    platform = platform or sys.platform
    home = _home(env)
    env = os.environ if env is None else env
    if client_id == "claude-desktop":
        if platform == "darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if platform.startswith("win"):
            return Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "Claude" / "claude_desktop_config.json"
        return home / ".config" / "Claude" / "claude_desktop_config.json"
    if client_id == "cursor":
        return home / ".cursor" / "mcp.json"
    return None


def find_cli(binary: str, env: dict | None = None) -> str | None:
    """The CLI on PATH, or in a common install folder a GUI-started console may not have on PATH."""
    env = os.environ if env is None else env
    found = shutil.which(binary, path=env.get("PATH"))
    if found:
        return found
    home = _home(env)
    for folder in EXTRA_BIN_DIRS:
        candidate = Path(folder.replace("~", str(home), 1)) / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _server(server_id: object) -> dict:
    if not isinstance(server_id, str) or server_id not in SERVERS:
        raise McpError(400, "Unknown MCP server")
    return SERVERS[server_id]


def _client(client_id: object) -> dict:
    if not isinstance(client_id, str) or client_id not in CLIENTS:
        raise McpError(400, "Unknown MCP client")
    return CLIENTS[client_id]


def _read_config(path: Path) -> dict:
    """A client's JSON config; an empty one when it does not exist yet. Never guesses at a broken file."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        raise McpError(409, f"{path.name} is not valid JSON; fix or move it before connecting ({exc})") from exc
    if not isinstance(data, dict):
        raise McpError(409, f"{path.name} does not hold a JSON object")
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise McpError(409, f"{path.name} has an mcpServers value that is not an object")
    return data


def _cli_registered(binary_path: str, name: str, client_id: str, env: dict | None) -> bool | None:
    """Whether a CLI client already lists the entry; None when it cannot tell."""
    if client_id == "codex":
        config = _home(env) / ".codex" / "config.toml"
        try:
            text = config.read_text(encoding="utf-8")
        except OSError:
            return False
        return f"[mcp_servers.{name}]" in text or f'[mcp_servers."{name}"]' in text
    try:
        result = subprocess.run([binary_path, "mcp", "get", name], capture_output=True, text=True, timeout=CLI_TIMEOUT, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def status(env: dict | None = None) -> dict:
    """Read-only: every server, and for each client whether it is installed and already has each server."""
    clients = []
    for client_id, client in CLIENTS.items():
        row = {"id": client_id, "label": client["label"], "kind": client["kind"], "installed": False, "registered": {}}
        if client["kind"] == "cli":
            binary = find_cli(client["binary"], env)
            row["installed"] = binary is not None
            row["binary"] = binary
            for server_id, server in SERVERS.items():
                row["registered"][server_id] = _cli_registered(binary, server["name"], client_id, env) if binary else False
        else:
            path = config_path(client_id, env)
            row["installed"] = bool(path and path.parent.is_dir())
            row["config"] = str(path) if path else None
            try:
                entries = _read_config(path).get("mcpServers", {}) if path else {}
            except McpError:
                entries = {}
                row["error"] = "The config file is not valid JSON"
            for server_id, server in SERVERS.items():
                row["registered"][server_id] = server["name"] in entries
        clients.append(row)
    servers = [
        {"id": server_id, "name": s["name"], "label": s["label"], "description": s["description"], "command": server_command(server_id)}
        for server_id, s in SERVERS.items()
    ]
    return {"servers": servers, "clients": clients}


def preview(server_id: object, client_id: object, env: dict | None = None) -> dict:
    """The exact change ``connect`` would make. Touches nothing."""
    server = _server(server_id)
    client = _client(client_id)
    command = server_command(server_id)  # type: ignore[arg-type]
    plan: dict = {"server": server_id, "client": client_id, "name": server["name"], "kind": client["kind"]}
    if client["kind"] == "cli":
        binary = find_cli(client["binary"], env)
        if not binary:
            raise McpError(409, f"{client['label']} is not installed (no `{client['binary']}` command found)")
        if client_id == "claude-code":
            argv = [binary, "mcp", "add", "--scope", "user", server["name"], "--", *command]
        else:
            argv = [binary, "mcp", "add", server["name"], "--", *command]
        plan["argv"] = argv
        plan["replaces"] = bool(_cli_registered(binary, server["name"], client_id, env))  # type: ignore[arg-type]
    else:
        path = config_path(client_id, env)  # type: ignore[arg-type]
        assert path is not None
        existing = _read_config(path).get("mcpServers", {}).get(server["name"])
        entry = {"type": "stdio", "command": command[0], "args": command[1:]}
        if client_id == "claude-desktop":
            entry = {"command": command[0], "args": command[1:]}
        plan["file"] = str(path)
        plan["entry"] = entry
        plan["replaces"] = existing is not None
        plan["existing"] = existing
    return plan


def _write_json(path: Path, data: dict) -> None:
    """Atomic write that keeps a one-step backup of the file it replaces."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".oslab.bak"))
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _check_command(plan: dict) -> None:
    """The server command must exist before anything is touched: a replace removes the old entry first."""
    command = plan["argv"][plan["argv"].index("--") + 1:] if plan["kind"] == "cli" else [plan["entry"]["command"], *plan["entry"]["args"]]
    for part in command[:2]:
        if not Path(part).is_file():
            raise McpError(409, f"The server command is missing ({part}); nothing was changed")


def connect(plan: dict, env: dict | None = None) -> dict:
    """Apply a plan that ``preview`` returned and the caller has verified against its token."""
    _check_command(plan)
    if plan["kind"] == "cli":
        argv = list(plan["argv"])
        if plan.get("replaces"):
            # The CLIs refuse to add a name that exists; remove the old entry first,
            # which the preview showed as "replaces".
            remove = [argv[0], "mcp", "remove", *(["--scope", "user"] if plan["client"] == "claude-code" else []), plan["name"]]
            subprocess.run(remove, capture_output=True, text=True, timeout=CLI_TIMEOUT, env=env)
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=CLI_TIMEOUT, env=env)
        except subprocess.TimeoutExpired as exc:
            raise McpError(504, f"{CLIENTS[plan['client']]['label']} did not answer in {CLI_TIMEOUT}s") from exc
        except OSError as exc:
            raise McpError(500, f"Could not run {argv[0]}: {exc}") from exc
        if result.returncode != 0:
            raise McpError(400, (result.stderr or result.stdout).strip() or f"{argv[0]} exited {result.returncode}")
        return {"ok": True, "server": plan["server"], "client": plan["client"], "output": result.stdout.strip()}
    path = Path(plan["file"])
    data = _read_config(path)
    servers = data.setdefault("mcpServers", {})
    servers[plan["name"]] = plan["entry"]
    try:
        _write_json(path, data)
    except OSError as exc:
        raise McpError(500, f"Could not write {path}: {exc}") from exc
    return {"ok": True, "server": plan["server"], "client": plan["client"], "file": str(path)}
