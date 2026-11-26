"""Web Lab tools for the os-lab MCP server — status, engine lifecycle, and observe proxies."""
from __future__ import annotations

import mcp_common as common
import mcp_ui
import oslab
import web_api

_API = None
W = mcp_ui.WEB_WIDGET


def _api(root):
    global _API
    if _API is None or _API.root != root:
        _API = web_api.WebLabAPI(root)
    return _API


TOOLS = [
    mcp_ui.tool("web_status",
                "Web Lab readiness and engine health (ready / stopped / needs-setup / unavailable). Read-only.",
                common.obj(), read_only=True, idempotent=True, resource_uri=W["status"]),
    mcp_ui.tool("web_overview",
                "Engine overview when running (windows, injections). Read-only.",
                common.obj(), read_only=True, resource_uri=W["engine"]),
    mcp_ui.tool("web_windows",
                "Open Web Lab browser windows. Read-only list.",
                common.obj(), read_only=True, resource_uri=W["windows"]),
    mcp_ui.tool("web_injections",
                "Active Web Lab JavaScript injections (mirrors GET /api/web/injections). Read-only observe.",
                common.obj(), read_only=True, resource_uri=W["injections"]),
    mcp_ui.tool("web_profiles",
                "Saved Web Lab profiles (mirrors GET /api/web/profiles). Read-only observe.",
                common.obj(), read_only=True, resource_uri=W["profiles"]),
    mcp_ui.tool("web_engine_start",
                "Start the local Web Lab engine on loopback (builds must already exist via labctl web setup).",
                common.obj(), open_world=False, resource_uri=W["engine"]),
    mcp_ui.tool("web_engine_stop",
                "Stop the local Web Lab engine.",
                common.obj(), idempotent=True, resource_uri=W["engine"]),
    mcp_ui.tool("web_app_overview",
                "Web Lab overview MCP App: readiness and engine health (dashboard Overview UX).",
                common.obj(), read_only=True, idempotent=True, resource_uri=mcp_ui.LAB_APP["web"]),
]
NAMES = {tool["name"] for tool in TOOLS}
_UI_FOR = {tool["name"]: tool["_meta"]["ui"]["resourceUri"]
           for tool in TOOLS if tool.get("_meta", {}).get("ui", {}).get("resourceUri")}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    api = _api(root)
    try:
        return mcp_ui.result(_dispatch(api, name, args, root), resource_uri=_UI_FOR.get(name))
    except web_api.WebLabError as exc:
        raise oslab.PlanError(str(exc), code="WEB_{0}".format(exc.status),
                              retry="reobserve" if exc.status in (404, 503, 409) else None) from exc


def _dispatch(api, name, args, root):
    if name == "web_status":
        common.check(args, [])
        return {"lab": common.lab_status(root, "web"), "engine": api.status()}
    if name == "web_overview":
        common.check(args, [])
        return api.get("/api/web/overview", {})
    if name == "web_windows":
        common.check(args, [])
        return api.get("/api/web/windows", {})
    if name == "web_injections":
        common.check(args, [])
        return api.get("/api/web/injections", {})
    if name == "web_profiles":
        common.check(args, [])
        return api.get("/api/web/profiles", {})
    if name == "web_engine_start":
        common.check(args, [])
        return api.start_engine()
    if name == "web_engine_stop":
        common.check(args, [])
        return api.stop_engine()
    if name == "web_app_overview":
        common.check(args, [])
        return {"status": common.lab_status(root, "web"), "engine": api.status()}
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
