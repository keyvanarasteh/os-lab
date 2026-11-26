"""Linux Lab tools for the os-lab MCP server — readiness, doctor depth, plan preview."""
from __future__ import annotations

import mcp_common as common
import mcp_ui
import oslab

W = mcp_ui.LINUX_WIDGET

TOOLS = common.annotate_ro([
    mcp_ui.tool("linux_status",
                "Linux Lab readiness: ready / needs-setup / unavailable, provider, KVM/WSL hints, reasons and actions. Read-only.",
                common.obj(), read_only=True, idempotent=True, resource_uri=W["status"]),
    mcp_ui.tool("linux_doctor",
                "Linux Lab doctor depth without running the script: host OS/arch, virtualization, KVM/WSL signals, lab status and a doctor plan preview. Read-only.",
                common.obj(), read_only=True, idempotent=True, resource_uri=W["doctor"]),
    mcp_ui.tool("linux_plan",
                "Build a guarded labctl plan for a Linux Lab action without running it. Read-only preview.",
                common.obj({
                    "action": {"type": "string", "description": "Action id from linux_status.actions"},
                    "profile": {"type": "string"},
                    "wslDistro": {"type": "string"},
                }, ["action"]), read_only=True),
])
NAMES = {tool["name"] for tool in TOOLS}
_UI_FOR = {tool["name"]: tool["_meta"]["ui"]["resourceUri"]
           for tool in TOOLS if tool.get("_meta", {}).get("ui", {}).get("resourceUri")}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    return mcp_ui.result(_dispatch(name, args, root), resource_uri=_UI_FOR.get(name))


def _dispatch(name, args, root):
    if name == "linux_status":
        common.check(args, [])
        return common.lab_status(root, "linux")
    if name == "linux_doctor":
        common.check(args, [])
        host = oslab.host_info(root)
        host = {**host, "root": root}
        status = oslab.lab_status("linux", host)
        plan = None
        try:
            plan = oslab.plan(root, {"lab": "linux", "action": "doctor"})
        except oslab.PlanError as exc:
            plan = {"error": str(exc), "code": getattr(exc, "code", None)}
        return {
            "host": {
                "os": host.get("os"),
                "arch": host.get("arch"),
                "virt": host.get("virt") or host.get("virtualization"),
                "kvm": host.get("kvm"),
                "wsl": host.get("wsl") or host.get("inWsl"),
                "docker": host.get("docker"),
                "disk": host.get("disk") or host.get("storage"),
            },
            "status": status,
            "doctorPlan": plan,
            "note": "Observe-only doctor depth. Run the real doctor via the dashboard confirm flow or linux_plan + console start.",
        }
    if name == "linux_plan":
        common.check(args, ["action", "profile", "wslDistro"], ["action"])
        request = {"lab": "linux", "action": args["action"]}
        if args.get("profile"):
            request["profile"] = args["profile"]
        if args.get("wslDistro"):
            request["wslDistro"] = args["wslDistro"]
        return oslab.plan(root, request)
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
