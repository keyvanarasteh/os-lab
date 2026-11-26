"""Host plugin HTTP contracts for Cursor, Zcode and Grok (``/api/<host>-plugin``).

GET  /api/<host>-plugin           doctor and install state (no network)
POST /api/<host>-plugin/check     {online} versions; online also asks GitHub
POST /api/<host>-plugin/preview   {action} commands and a one-use token
POST /api/<host>-plugin/apply     refused — install runs only from a terminal

The engine is console/host_plugin.py. Standard library only.
"""
from __future__ import annotations

import host_plugin

HOSTS = ("cursor", "zcode", "grok")
STATUS = {"CONFIRM_REQUIRED": 400, "INVALID_ARGS": 400, "TERMINAL_ONLY": 403, "STALE_PLAN": 409,
          "CONFLICT": 409, "ALREADY_INSTALLED": 409, "NOT_INSTALLED": 409, "CLI_MISSING": 409,
          "UNSUPPORTED": 409, "PACKAGE_MISSING": 409}


def prefix_for(host: str) -> str:
    return "/api/{0}-plugin".format(host)


def state(root: str, host: str) -> dict:
    result = {"host": host, "doctor": host_plugin.doctor(root, host),
              "checkoutVersion": host_plugin.checkout_version(root, host),
              "terminalCommand": "python3 scripts/{0}-plugin.py install".format(host)}
    try:
        result["install"] = host_plugin.status(root, host)
    except host_plugin.PluginError as exc:
        result["install"] = {"cli": None, "installed": False, "duplicates": [], "error": str(exc)}
    return result


def _only(data: dict, *allowed: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise host_plugin.PluginError("Unexpected field(s): " + ", ".join(unknown))


def handle(root: str, host: str, method: str, path: str, data: dict | None = None) -> tuple[int, dict]:
    if host not in HOSTS:
        return 404, {"error": "Unknown host"}
    data = data or {}
    prefix = prefix_for(host)
    try:
        if method == "GET" and path == prefix:
            return 200, state(root, host)
        if method == "POST" and path == prefix + "/check":
            _only(data, "online")
            return 200, host_plugin.updates(root, host, online=data.get("online") is True)
        if method == "POST" and path == prefix + "/preview":
            _only(data, "action")
            action = data.get("action")
            if not isinstance(action, str):
                raise host_plugin.PluginError("action is text")
            return 200, host_plugin.plan(root, host, action)
        if method == "POST" and path == prefix + "/apply":
            _only(data, "token", "confirm")
            raise host_plugin.PluginError(
                "Run this in a terminal: python3 scripts/{0}-plugin.py install".format(host),
                "TERMINAL_ONLY")
    except host_plugin.PluginError as exc:
        return STATUS.get(exc.code, 502), {"error": str(exc), "code": exc.code}
    return 404, {"error": "Not found"}
