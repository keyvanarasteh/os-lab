"""Web Lab tools for the os-lab MCP server — status, engine lifecycle, and observe proxies."""
from __future__ import annotations

import mcp_common as common
import mcp_ui
import oslab
import web_api

_API = None


def _api(root):
    global _API
    if _API is None or _API.root != root:
        _API = web_api.WebLabAPI(root)
    return _API


TOOLS = [
    mcp_ui.tool("web_status",
                "Web Lab readiness and engine health (ready / stopped / needs-setup / unavailable). Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("web_overview",
                "Engine overview when running (windows, injections). Read-only.",
                common.obj(), read_only=True),
    mcp_ui.tool("web_windows",
                "Open Web Lab browser windows. Read-only list.",
                common.obj(), read_only=True),
    mcp_ui.tool("web_engine_start",
                "Start the local Web Lab engine on loopback (builds must already exist via labctl web setup).",
                common.obj(), open_world=False),
    mcp_ui.tool("web_engine_stop",
                "Stop the local Web Lab engine.",
                common.obj(), idempotent=True),
]
NAMES = {tool["name"] for tool in TOOLS}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    api = _api(root)
    try:
        return common.result(_dispatch(api, name, args, root))
    except web_api.WebLabError as exc:
        raise oslab.PlanError(str(exc), code="WEB_{0}".format(exc.status),
                              retry="reobserve" if exc.status in (404, 503, 409) else None) from exc


def _dispatch(api, name, args, root):
    if name == "web_status":
        common.check(args, [])
        # Prefer lab_status (dashboard chip) plus engine detail.
        return {"lab": common.lab_status(root, "web"), "engine": api.status()}
    if name == "web_overview":
        common.check(args, [])
        return api.get("/api/web/overview", {})
    if name == "web_windows":
        common.check(args, [])
        return api.get("/api/web/windows", {})
    if name == "web_engine_start":
        common.check(args, [])
        return api.start_engine()
    if name == "web_engine_stop":
        common.check(args, [])
        return api.stop_engine()
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
