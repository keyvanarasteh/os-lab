"""Codex plugin management tools on the guarded os-lab MCP server."""
from __future__ import annotations

import codex_plugin as engine
import mcp_common as common
import mcp_ui
import oslab

RESOURCE_URI = "oslab://codex-plugin/requirements"

TOOLS = [
    mcp_ui.tool("codex_plugin_requirements", "Codex plugin requirements with current official sources. Read-only.",
                common.obj({"area": {"type": "string"}, "usage": {"type": "string", "enum": ["used", "n/a"]}}),
                read_only=True, idempotent=True),
    mcp_ui.tool("codex_plugin_doctor", "Check Python, checkout discovery and package readiness. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("codex_plugin_status", "Codex plugin install state and duplicate manual MCP names, without secrets. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("codex_plugin_check", "Check the Codex plugin package against its requirement catalog. Read-only.",
                common.obj({"area": {"type": "string"}}), read_only=True, idempotent=True),
    mcp_ui.tool("codex_plugin_plan", "Preview the exact local Codex plugin installation commands; changes nothing.",
                common.obj({"action": {"type": "string", "enum": ["install"]}}, ["action"]),
                read_only=True),
    mcp_ui.tool("codex_plugin_apply", "Installation is terminal-only; this tool refuses MCP-initiated writes.",
                common.obj({"token": {"type": "string"}, "confirm": {"type": "boolean"}}, ["token", "confirm"])),
    mcp_ui.tool("codex_plugin_verify", "Start this checkout's installed launcher and compare discovered MCP tools. Read-only.",
                common.obj(), read_only=True, idempotent=True),
]
NAMES = {entry["name"] for entry in TOOLS}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    try:
        if name == "codex_plugin_requirements":
            common.check(args, ["area", "usage"])
            value = engine.requirements(args.get("area"), args.get("usage"))
        elif name == "codex_plugin_doctor":
            common.check(args, [])
            value = engine.doctor(root)
        elif name == "codex_plugin_status":
            common.check(args, [])
            value = engine.status(root)
        elif name == "codex_plugin_check":
            common.check(args, ["area"])
            value = engine.check(root, args.get("area"))
        elif name == "codex_plugin_plan":
            common.check(args, ["action"], ["action"])
            value = engine.plan(root, args["action"])
        elif name == "codex_plugin_apply":
            common.check(args, ["token", "confirm"], ["token", "confirm"])
            value = engine.apply(root, args["token"], args["confirm"], audience="agent")
        elif name == "codex_plugin_verify":
            common.check(args, [])
            value = engine.verify(root)
        else:
            raise engine.PluginError("Unknown Codex tool: " + name)
        return mcp_ui.result(value)
    except engine.PluginError as exc:
        raise oslab.PlanError(str(exc), code=exc.code) from exc
