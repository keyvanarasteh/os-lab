"""Codex plugin HTTP contracts (``/api/codex-plugin``), behind the MCP page's cards.

GET  /api/codex-plugin           doctor and Codex install state (no network)
POST /api/codex-plugin/check     {online} versions; online also asks GitHub
POST /api/codex-plugin/preview   {action} commands and a one-use token
POST /api/codex-plugin/apply     refused — install runs only from a terminal

The engine is console/codex_plugin.py, the same one the MCP tools use. Standard library only.
"""
from __future__ import annotations

import codex_plugin

PREFIX = "/api/codex-plugin"
STATUS = {"CONFIRM_REQUIRED": 400, "INVALID_ARGS": 400, "TERMINAL_ONLY": 403, "STALE_PLAN": 409,
          "CONFLICT": 409, "ALREADY_INSTALLED": 409, "NOT_INSTALLED": 409, "CLI_MISSING": 409,
          "UNSUPPORTED": 409, "PACKAGE_MISSING": 409}


def state(root: str) -> dict:
    result = {"doctor": codex_plugin.doctor(root),
              "checkoutVersion": codex_plugin.checkout_version(root),
              "terminalCommand": "python3 scripts/codex-plugin.py install"}
    try:
        result["codex"] = codex_plugin.status(root)
    except codex_plugin.PluginError as exc:
        result["codex"] = {"cli": None, "installed": False, "duplicates": [], "error": str(exc)}
    return result


def _only(data: dict, *allowed: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise codex_plugin.PluginError("Unexpected field(s): " + ", ".join(unknown))


def handle(root: str, method: str, path: str, data: dict | None = None) -> tuple[int, dict]:
    data = data or {}
    try:
        if method == "GET" and path == PREFIX:
            return 200, state(root)
        if method == "POST" and path == PREFIX + "/check":
            _only(data, "online")
            return 200, codex_plugin.updates(root, online=data.get("online") is True)
        if method == "POST" and path == PREFIX + "/preview":
            _only(data, "action")
            action = data.get("action")
            if not isinstance(action, str):
                raise codex_plugin.PluginError("action is text")
            # Preview is allowed from the console; apply still refuses and shows the terminal command.
            return 200, codex_plugin.plan(root, action)
        if method == "POST" and path == PREFIX + "/apply":
            _only(data, "token", "confirm")
            raise codex_plugin.PluginError(
                "Run this in a terminal: python3 scripts/codex-plugin.py install", "TERMINAL_ONLY")
    except codex_plugin.PluginError as exc:
        return STATUS.get(exc.code, 502), {"error": str(exc), "code": exc.code}
    return 404, {"error": "Not found"}
