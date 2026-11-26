"""Claude plugin tools for the os-lab MCP server: requirements, checks, install and setup."""
from __future__ import annotations

import claude_plugin as engine
import mcp_common as common
import mcp_ui
import oslab

W = mcp_ui.PLUGIN_WIDGET
RESOURCE_URI = "oslab://plugin/requirements"

_SCOPE = {"type": "string", "enum": list(engine.SCOPES), "description": "install scope; default user"}
_AREA = {"type": "string", "description": "one catalog area, for example manifest, mcp, skills or hooks"}

TOOLS = [
    mcp_ui.tool("plugin_requirements",
                "The Claude plugin requirement catalog: rule, severity, documentation URL and whether os-lab uses it. Read-only.",
                common.obj({"area": _AREA, "usage": {"type": "string", "enum": ["used", "n/a"]}}),
                read_only=True, idempotent=True),
    mcp_ui.tool("plugin_doctor",
                "Whether this computer can run the os-lab Claude plugin: Claude Code, Python and the checkout, each with a fix. Installs nothing. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("plugin_status",
                "The os-lab marketplace and plugin install state, plus hand-made MCP entries that duplicate it. Read-only.",
                common.obj(), read_only=True, idempotent=True, resource_uri=W["status"]),
    mcp_ui.tool("plugin_check",
                "Check this checkout's Claude plugin against every catalog rule, including claude plugin validate. Read-only.",
                common.obj({"area": _AREA, "useCli": {"type": "boolean", "description": "default true"}}),
                read_only=True, idempotent=True),
    mcp_ui.tool("plugin_plan",
                "Preview the exact claude commands to install, update, configure, enable, disable or uninstall the os-lab plugin, with a one-use token. Runs no change.",
                common.obj({
                    "action": {"type": "string", "enum": list(engine.ACTIONS)},
                    "scope": _SCOPE,
                    "name": {"type": "string", "enum": list(engine.DUPLICATE_NAMES),
                             "description": "remove-duplicate only"},
                }, ["action"]), read_only=True),
    mcp_ui.tool("plugin_apply",
                "Run a plan from plugin_plan after the user approved its commands: needs its token and confirm: true. Uninstall and remove-duplicate are refused here; the user runs them in a terminal.",
                common.obj({"token": {"type": "string"}, "confirm": {"type": "boolean"}}, ["token", "confirm"])),
    mcp_ui.tool("plugin_verify",
                "Start the installed plugin's server, list its tools and compare them with this checkout. Changes nothing.",
                common.obj(), read_only=True, idempotent=True),
]
NAMES = {tool["name"] for tool in TOOLS}
_UI_FOR = {tool["name"]: tool["_meta"]["ui"]["resourceUri"]
           for tool in TOOLS if tool.get("_meta", {}).get("ui", {}).get("resourceUri")}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    try:
        return mcp_ui.result(_dispatch(name, args, root), resource_uri=_UI_FOR.get(name))
    except engine.PluginError as exc:
        raise oslab.PlanError(str(exc), code=exc.code) from exc


def _dispatch(name, args, root):
    if name == "plugin_requirements":
        common.check(args, ["area", "usage"])
        return engine.requirements(args.get("area"), args.get("usage"))
    if name == "plugin_doctor":
        common.check(args, [])
        return engine.doctor(root)
    if name == "plugin_status":
        common.check(args, [])
        return engine.status(root)
    if name == "plugin_check":
        common.check(args, ["area", "useCli"])
        return engine.check(root, args.get("area"), use_cli=args.get("useCli") is not False)
    if name == "plugin_plan":
        common.check(args, ["action", "scope", "name"], ["action"])
        return engine.plan(root, args["action"], args.get("scope") or "user", args.get("name"))
    if name == "plugin_apply":
        common.check(args, ["token", "confirm"], ["token"])
        return engine.apply(root, args["token"], args.get("confirm") is True, audience="agent")
    if name == "plugin_verify":
        common.check(args, [])
        return engine.verify(root)
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
