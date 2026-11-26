"""Claude plugin HTTP contracts (``/api/claude-plugin``), behind the MCP page's cards.

GET  /api/claude-plugin           doctor, Claude Code and Claude Desktop state (no network)
POST /api/claude-plugin/check     {online} versions; online also asks GitHub
POST /api/claude-plugin/preview   {action, scope?, updateCheck?} commands and a one-use token
POST /api/claude-plugin/apply     {token, confirm}

The engine is console/claude_plugin.py, the same one the MCP tools use: fixed commands, a token
bound to the previewed state, and removals only from a terminal. Standard library only.
"""
from __future__ import annotations

import claude_desktop
import claude_plugin

PREFIX = "/api/claude-plugin"
STATUS = {"CONFIRM_REQUIRED": 400, "INVALID_ARGS": 400, "TERMINAL_ONLY": 403, "STALE_PLAN": 409,
          "CONFLICT": 409, "NOT_INSTALLED": 409, "CLI_MISSING": 409, "CLI_OLD": 409, "MANUAL": 409}


def state(root: str) -> dict:
    result = {"doctor": claude_plugin.doctor(root), "desktop": claude_desktop.status(root),
              "checkoutVersion": claude_plugin.mcpb_manifest(root)["version"]}
    try:
        result["code"] = claude_plugin.status(root)
    except claude_plugin.PluginError as exc:
        result["code"] = {"cli": None, "installed": [], "duplicates": [], "marketplace": None,
                          "error": str(exc)}
    return result


def _only(data: dict, *allowed: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise claude_plugin.PluginError("Unexpected field(s): " + ", ".join(unknown))


def handle(root: str, method: str, path: str, data: dict | None = None) -> tuple[int, dict]:
    data = data or {}
    try:
        if method == "GET" and path == PREFIX:
            return 200, state(root)
        if method == "POST" and path == PREFIX + "/check":
            _only(data, "online")
            return 200, claude_desktop.updates(root, online=data.get("online") is True)
        if method == "POST" and path == PREFIX + "/preview":
            _only(data, "action", "scope", "updateCheck")
            action, scope = data.get("action"), data.get("scope", "user")
            check = data.get("updateCheck")
            if not isinstance(action, str) or not isinstance(scope, str) or \
                    not (check is None or isinstance(check, bool)):
                raise claude_plugin.PluginError("action and scope are text; updateCheck is true or false")
            if action in claude_plugin.TERMINAL_ONLY:
                raise claude_plugin.PluginError(
                    "Run this in a terminal: python3 scripts/claude-plugin.py " + action, "TERMINAL_ONLY")
            return 200, claude_plugin.plan(root, action, scope, update_check=check)
        if method == "POST" and path == PREFIX + "/apply":
            _only(data, "token", "confirm")
            return 200, claude_plugin.apply(root, data.get("token"), data.get("confirm") is True,
                                            audience="console")
    except claude_plugin.PluginError as exc:
        return STATUS.get(exc.code, 502), {"error": str(exc), "code": exc.code}
    return 404, {"error": "Not found"}
