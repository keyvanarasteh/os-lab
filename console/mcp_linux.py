"""Linux Lab tools for the os-lab MCP server — readiness and plan preview first."""
from __future__ import annotations

import mcp_common as common
import mcp_ui
import oslab

TOOLS = common.annotate_ro([
    mcp_ui.tool("linux_status",
                "Linux Lab readiness: ready / needs-setup / unavailable, provider, KVM/WSL hints, reasons and actions. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("linux_plan",
                "Build a guarded labctl plan for a Linux Lab action without running it. Read-only preview.",
                common.obj({
                    "action": {"type": "string", "description": "Action id from linux_status.actions"},
                    "profile": {"type": "string"},
                    "wslDistro": {"type": "string"},
                }, ["action"]), read_only=True),
])
NAMES = {tool["name"] for tool in TOOLS}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    return common.result(_dispatch(name, args, root))


def _dispatch(name, args, root):
    if name == "linux_status":
        common.check(args, [])
        return common.lab_status(root, "linux")
    if name == "linux_plan":
        common.check(args, ["action", "profile", "wslDistro"], ["action"])
        request = {"lab": "linux", "action": args["action"]}
        if args.get("profile"):
            request["profile"] = args["profile"]
        if args.get("wslDistro"):
            request["wslDistro"] = args["wslDistro"]
        return oslab.plan(root, request)
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
