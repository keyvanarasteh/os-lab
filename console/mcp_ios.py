"""iOS Lab observe tools for the os-lab MCP server (MIR companions).

Device/simulator listing and screenshots only. Driving a device still needs
Developer Mode and a signed WebDriverAgent from the dashboard — there is no
agent arm or automation-start tool here.
"""
from __future__ import annotations

import base64

import mcp_common as common
import mcp_ui
import oslab

TOOLS = common.annotate_ro([
    mcp_ui.tool("ios_status",
                "iOS Lab readiness: ready / needs-setup / unavailable, provider, reasons and actions. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("ios_simulator",
                "Installed iOS Simulator devices, runtimes and which are booted. Read-only; needs Xcode on macOS.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("ios_devices",
                "Real (paired or connected) iOS devices via xcrun devicectl. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("ios_device_check",
                "Reachability probe for one real-device UDID. Read-only.",
                common.obj({"udid": {"type": "string"}}, ["udid"]), read_only=True),
    mcp_ui.tool("ios_resources",
                "iOS Lab resource tips and tooling hints for this Mac. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("ios_screenshot",
                "PNG of a booted simulator (udid optional) or a real device (set real:true). Read-only capture.",
                common.obj({
                    "udid": {"type": "string"},
                    "real": {"type": "boolean", "default": False, "description": "Capture a physical device instead of a simulator"},
                }), read_only=True),
    mcp_ui.tool("ios_plan",
                "Build a guarded labctl plan for an iOS Lab action without running it. Read-only preview.",
                common.obj({
                    "action": {"type": "string"},
                    "device": {"type": "string", "description": "Simulator name or UDID for start"},
                }, ["action"]), read_only=True),
])
NAMES = {tool["name"] for tool in TOOLS}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    if name == "ios_screenshot":
        common.check(args, ["udid", "real"])
        if args.get("real") is True:
            if not args.get("udid"):
                raise oslab.PlanError("ios_screenshot with real:true needs udid", code="INVALID_ARGS")
            png = oslab.ios_real_device_screenshot(args["udid"])
        else:
            png = oslab.ios_screenshot(args.get("udid") or None)
        return {
            "content": [
                {"type": "text", "text": '{"ok": true, "bytes": %d}' % len(png)},
                {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"},
            ],
            "structuredContent": {"ok": True, "bytes": len(png)},
        }
    return common.result(_dispatch(name, args, root))


def _dispatch(name, args, root):
    if name == "ios_status":
        common.check(args, [])
        return common.lab_status(root, "ios")
    if name == "ios_simulator":
        common.check(args, [])
        return oslab.ios_simulator(root)
    if name == "ios_devices":
        common.check(args, [])
        return oslab.ios_devices()
    if name == "ios_device_check":
        common.check(args, ["udid"], ["udid"])
        return oslab.ios_device_check(args["udid"])
    if name == "ios_resources":
        common.check(args, [])
        return oslab.ios_resources()
    if name == "ios_plan":
        common.check(args, ["action", "device"], ["action"])
        request = {"lab": "ios", "action": args["action"]}
        if args.get("device"):
            request["device"] = args["device"]
        return oslab.plan(root, request)
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
