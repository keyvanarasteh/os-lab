"""Source Lab tools for the os-lab MCP server — readiness, detection targets, plan preview."""
from __future__ import annotations

import source_control as control
from source_artifacts import ArtifactError
import mcp_common as common
import mcp_ui
import oslab

TOOLS = common.annotate_ro([
    mcp_ui.tool("source_status",
                "Source Lab readiness: ready / needs-setup / unavailable, Python/storage requirements and actions. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("source_readiness",
                "Raw engine readiness report from source-lab/run.py status --json. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("source_candidates",
                "Detection candidate targets on this computer (no network). Read-only.",
                common.obj(), read_only=True),
    mcp_ui.tool("source_runtime",
                "Saved Source Lab runtime settings (canary URL, playwright flag). Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("source_plan",
                "Build a guarded Source Lab plan without running it. Read-only preview.",
                common.obj({
                    "action": {"type": "string", "description": "status | doctor | setup | detect | crawl | …"},
                    "target": {"type": "string"},
                    "glob": {"type": "string"},
                }, ["action"]), read_only=True),
])
NAMES = {tool["name"] for tool in TOOLS}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    try:
        return common.result(_dispatch(name, args, root))
    except ArtifactError as exc:
        status = getattr(exc, "status", 400)
        raise oslab.PlanError(str(exc), code="SOURCE_{0}".format(status)) from exc


def _dispatch(name, args, root):
    if name == "source_status":
        common.check(args, [])
        return common.lab_status(root, "source")
    if name == "source_readiness":
        common.check(args, [])
        return control.readiness(root)
    if name == "source_candidates":
        common.check(args, [])
        return {"targets": control.candidates(root)}
    if name == "source_runtime":
        common.check(args, [])
        return control.runtime(root)
    if name == "source_plan":
        common.check(args, ["action", "target", "glob"], ["action"])
        request = {"lab": "source", "action": args["action"]}
        if args.get("target"):
            request["target"] = args["target"]
        if args.get("glob"):
            request["glob"] = args["glob"]
        return oslab.plan(root, request)
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
