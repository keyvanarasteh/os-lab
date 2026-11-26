#!/usr/bin/env python3
"""Start os-lab from a checkout, or serve read-only setup help over MCP."""
from __future__ import annotations

import json
import os
import runpy
import sys

SERVER = os.path.join("console", "mcp_server.py")
MARKETPLACE = os.path.join(".agents", "plugins", "marketplace.json")
FIX = "Set OSLAB_ROOT to the absolute path of an os-lab checkout, then restart Codex."


def _checkout(path):
    return os.path.isfile(os.path.join(path, SERVER)) and os.path.isfile(os.path.join(path, "labctl"))


def _local_marketplace(path):
    try:
        with open(os.path.join(path, MARKETPLACE), encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("name") == "os-lab-local" and any(
            row.get("name") == "os-lab" and
            (row.get("source") or {}).get("path") == "./plugins/codex/os-lab"
            for row in data.get("plugins", []) if isinstance(row, dict))
    except (OSError, ValueError, AttributeError):
        return False


def find_checkout(env=None, here=None):
    """Return (root, source, problem); a bad explicit root never falls through."""
    env = os.environ if env is None else env
    value = (env.get("OSLAB_ROOT") or "").strip()
    if value:
        root = os.path.realpath(os.path.expanduser(value))
        if _checkout(root):
            return root, "OSLAB_ROOT", None
        return None, "OSLAB_ROOT", "OSLAB_ROOT does not name an os-lab checkout."
    folder = os.path.dirname(os.path.realpath(here or __file__))
    while True:
        if _checkout(folder) and _local_marketplace(folder):
            return folder, "local marketplace", None
        parent = os.path.dirname(folder)
        if parent == folder:
            return None, None, "No os-lab checkout was found."
        folder = parent


def setup_reply(message, problem):
    if not isinstance(message, dict) or "id" not in message:
        return None
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "os-lab-setup", "version": "0.1.0"},
                  "instructions": problem + " " + FIX}
    elif method == "tools/list":
        result = {"tools": [{"name": name, "description": "Explain why os-lab cannot start and how to fix it.",
                             "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                             "annotations": {"readOnlyHint": True}}
                            for name in ("codex_plugin_doctor", "codex_plugin_status")]}
    elif method == "tools/call":
        name = (message.get("params") or {}).get("name")
        if name not in ("codex_plugin_doctor", "codex_plugin_status"):
            return {"jsonrpc": "2.0", "id": message["id"],
                    "error": {"code": -32602, "message": "Unknown setup tool"}}
        result = {"content": [{"type": "text", "text": json.dumps({"ready": False,
                   "problem": problem, "fix": FIX})}], "isError": False}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": message["id"],
                "error": {"code": -32601, "message": "Unknown method"}}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def main():
    root, _source, problem = find_checkout()
    if root:
        server = os.path.join(root, SERVER)
        sys.path.insert(0, os.path.dirname(server))
        sys.argv[0] = server
        runpy.run_path(server, run_name="__main__")
        return
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = setup_reply(message, problem)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
