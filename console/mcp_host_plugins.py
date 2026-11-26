"""Zcode / Grok / Cursor plugin management tools on the guarded os-lab MCP server."""
from __future__ import annotations

import host_plugin as engine
import mcp_common as common
import mcp_ui
import oslab

HOSTS = ("cursor", "zcode", "grok")
TOOLS = []
NAMES = set()
_UI_FOR = {}
_ENGINES = {host: engine for host in HOSTS}  # shared module; host passed per call


def _resource(host):
    return "oslab://{0}-plugin/requirements".format(host)


def tools_for(host):
    return [tool for tool in TOOLS if tool["name"].startswith(host + "_plugin_")]


def _register(host):
    prefix = host + "_plugin_"
    title = engine.HOSTS[host]["title"]
    widget = mcp_ui.HOST_PLUGIN_WIDGET[host]
    uri = _resource(host)
    rows = [
        mcp_ui.tool(prefix + "requirements",
                    "{0} plugin requirements with current official sources. Read-only.".format(title),
                    common.obj({"area": {"type": "string"}, "usage": {"type": "string", "enum": ["used", "n/a"]}}),
                    read_only=True, idempotent=True),
        mcp_ui.tool(prefix + "doctor",
                    "Check Python, checkout discovery and {0} package readiness. Read-only.".format(title),
                    common.obj(), read_only=True, idempotent=True),
        mcp_ui.tool(prefix + "status",
                    "{0} plugin install state and duplicate MCP names, without secrets. Read-only.".format(title),
                    common.obj(), read_only=True, idempotent=True, resource_uri=widget["status"]),
        mcp_ui.tool(prefix + "updates",
                    "Whether the os-lab {0} plugin is current. online: true also asks GitHub. Read-only.".format(title),
                    common.obj({"online": {"type": "boolean", "description": "default false"}}),
                    read_only=True, idempotent=True, open_world=True),
        mcp_ui.tool(prefix + "check",
                    "Check the {0} plugin package against its requirement catalog. Read-only.".format(title),
                    common.obj({"area": {"type": "string"}}), read_only=True, idempotent=True),
        mcp_ui.tool(prefix + "plan",
                    "Preview the exact local {0} plugin install, update or uninstall; changes nothing.".format(title),
                    common.obj({"action": {"type": "string", "enum": list(engine.ACTIONS)}}, ["action"]),
                    read_only=True),
        mcp_ui.tool(prefix + "apply",
                    "Installation is terminal-only; this tool refuses MCP-initiated writes.",
                    common.obj({"token": {"type": "string"}, "confirm": {"type": "boolean"}}, ["token", "confirm"])),
        mcp_ui.tool(prefix + "verify",
                    "Start this checkout's {0} launcher and compare discovered MCP tools. Read-only.".format(title),
                    common.obj(), read_only=True, idempotent=True),
    ]
    for tool in rows:
        TOOLS.append(tool)
        NAMES.add(tool["name"])
        meta = tool.get("_meta", {}).get("ui", {}).get("resourceUri")
        if meta:
            _UI_FOR[tool["name"]] = meta
    return uri


RESOURCES = {host: _register(host) for host in HOSTS}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    host = None
    for candidate in HOSTS:
        if name.startswith(candidate + "_plugin_"):
            host = candidate
            break
    if not host:
        raise engine.PluginError("Unknown host plugin tool: " + name)
    prefix = host + "_plugin_"
    action = name[len(prefix):]
    try:
        if action == "requirements":
            common.check(args, ["area", "usage"])
            value = engine.requirements(host, args.get("area"), args.get("usage"))
        elif action == "doctor":
            common.check(args, [])
            value = engine.doctor(root, host)
        elif action == "status":
            common.check(args, [])
            value = engine.status(root, host)
        elif action == "updates":
            common.check(args, ["online"])
            value = engine.updates(root, host, online=args.get("online") is True)
        elif action == "check":
            common.check(args, ["area"])
            value = engine.check(root, host, args.get("area"))
        elif action == "plan":
            common.check(args, ["action"], ["action"])
            value = engine.plan(root, host, args["action"])
        elif action == "apply":
            common.check(args, ["token", "confirm"], ["token", "confirm"])
            value = engine.apply(root, host, args["token"], args.get("confirm") is True, audience="agent")
        elif action == "verify":
            common.check(args, [])
            value = engine.verify(root, host)
        else:
            raise engine.PluginError("Unknown {0} tool: {1}".format(host, name))
        return mcp_ui.result(value, resource_uri=_UI_FOR.get(name))
    except engine.PluginError as exc:
        raise oslab.PlanError(str(exc), code=exc.code) from exc
