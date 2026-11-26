"""Android Lab tools for the os-lab MCP server (read-only observe + Frida inventory).

Mirrors the dashboard's readiness and the PENT-09 Frida inventory. Lab jobs still
run through the console plan/start surface; this module does not arm or inject.
"""
from __future__ import annotations

import frida_inventory
import mcp_common as common
import mcp_ui
import oslab

TOOLS = common.annotate_ro([
    mcp_ui.tool("android_status",
                "Android Lab readiness: ready / needs-setup / unavailable, provider, reasons and available actions. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("android_frida_inventory",
                "Read-only Frida device and process inventory (PENT-09). Lists only; never attaches or injects. TCP hosts must be loopback or private.",
                common.obj({
                    "usb": {"type": "boolean", "default": False},
                    "host": {"type": "string", "description": "HOST[:PORT] loopback or RFC1918 only"},
                    "apps": {"type": "boolean", "default": False, "description": "List applications instead of all processes"},
                    "processes": {"type": "boolean", "default": True},
                    "filter": {"type": "string", "description": "Keep processes whose name/identifier contains this text"},
                }), read_only=True),
    mcp_ui.tool("android_plan",
                "Build a guarded labctl plan for an Android Lab action (status, start, stop, …) without running it. Read-only preview.",
                common.obj({
                    "action": {"type": "string", "description": "Action id from android_status.actions"},
                    "profile": {"type": "string"},
                    "device": {"type": "string", "description": "Emulator device for resize/start when applicable"},
                }, ["action"]), read_only=True),
    mcp_ui.tool("android_app_overview",
                "Android Lab overview MCP App: readiness, provider and available actions (dashboard Overview UX).",
                common.obj(), read_only=True, idempotent=True, resource_uri=mcp_ui.LAB_APP["android"]),
])
NAMES = {tool["name"] for tool in TOOLS}
_UI_FOR = {tool["name"]: tool["_meta"]["ui"]["resourceUri"]
           for tool in TOOLS if tool.get("_meta", {}).get("ui", {}).get("resourceUri")}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    try:
        return mcp_ui.result(_dispatch(name, args, root), resource_uri=_UI_FOR.get(name))
    except frida_inventory.ScopeError as exc:
        raise oslab.PlanError(str(exc), code="ANDROID_SCOPE") from exc
    except frida_inventory.ToolError as exc:
        raise oslab.PlanError(str(exc), code="ANDROID_TOOL") from exc


def _dispatch(name, args, root):
    if name == "android_status":
        common.check(args, [])
        return common.lab_status(root, "android")
    if name == "android_frida_inventory":
        common.check(args, ["usb", "host", "apps", "processes", "filter"])
        return frida_inventory.build_inventory(
            usb=bool(args.get("usb")),
            host=args.get("host") or None,
            apps=bool(args.get("apps")),
            processes=args.get("processes", True) is not False,
            name_filter=args.get("filter") or None,
        )
    if name == "android_plan":
        common.check(args, ["action", "profile", "device"], ["action"])
        request = {"lab": "android", "action": args["action"]}
        if args.get("profile"):
            request["profile"] = args["profile"]
        if args.get("device"):
            request["device"] = args["device"]
        return oslab.plan(root, request)
    if name == "android_app_overview":
        common.check(args, [])
        return {"status": common.lab_status(root, "android")}
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
