#!/usr/bin/env python3
"""Start the os-lab MCP server from a checkout.

Claude Code copies only the plugin folder into its cache, so the server is found in a
checkout: the repo_path option, then OSLAB_ROOT, then the folders above this file (a
marketplace added from a local path). Without a checkout this still answers MCP with two
tools that say how to set one. Standard library only; Python 3.8+.
"""
from __future__ import annotations

import json
import os
import runpy
import sys

SERVER = os.path.join("console", "mcp_server.py")
FIX = ("Set the plugin option repo_path to your os-lab checkout (/plugin configure os-lab@os-lab), "
       "then restart Claude Code or run /reload-plugins.")


def _is_checkout(path):
    return os.path.isfile(os.path.join(path, SERVER))


def _is_marketplace_root(path):
    try:
        with open(os.path.join(path, ".claude-plugin", "marketplace.json"), encoding="utf-8") as handle:
            return json.load(handle).get("name") == "os-lab"
    except (OSError, ValueError, AttributeError):
        return False


def find_checkout(env=None, here=None):
    """(root, source, problem). A configured but wrong path is never silently replaced."""
    env = os.environ if env is None else env
    for variable, source in (("OSLAB_PLUGIN_REPO", "repo_path"), ("OSLAB_ROOT", "OSLAB_ROOT")):
        value = (env.get(variable) or "").strip()
        if not value or value.startswith("${"):
            continue
        root = os.path.realpath(os.path.expanduser(value))
        if _is_checkout(root):
            return root, source, None
        return None, source, "{0} is {1}, which has no {2}.".format(source, value, SERVER)
    folder = os.path.dirname(os.path.realpath(here or __file__))
    while True:
        # Only a folder that is itself the os-lab marketplace counts, so a stray
        # console/mcp_server.py above the plugin cache is never run.
        if _is_checkout(folder) and _is_marketplace_root(folder):
            return folder, "marketplace folder", None
        parent = os.path.dirname(folder)
        if parent == folder:
            return None, None, "No os-lab checkout was found."
        folder = parent


def setup_reply(message, problem):
    """One JSON-RPC reply in setup-only mode; notifications return None."""
    if not isinstance(message, dict) or "id" not in message:
        return None
    method = message.get("method")
    if method == "initialize":
        params = message.get("params") or {}
        result = {"protocolVersion": params.get("protocolVersion") or "2024-11-05",
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "os-lab-setup", "version": "0.1.0"},
                  "instructions": "os-lab is not set up. " + problem + " " + FIX}
    elif method == "tools/list":
        result = {"tools": [{
            "name": name,
            "description": "os-lab is not set up yet: explain why and how to fix it. Read-only.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        } for name in ("plugin_doctor", "plugin_status")]}
    elif method == "tools/call":
        report = {"ready": False, "problem": problem, "fix": FIX}
        result = {"content": [{"type": "text", "text": json.dumps(report)}], "isError": False}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": message["id"],
                "error": {"code": -32601, "message": "Unknown method {0}".format(method)}}
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
