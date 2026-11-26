"""Source Lab tools for the os-lab MCP server — readiness, detection, analyzer observe, plan preview."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import source_control as control
from source_artifacts import MAX_JSON, ArtifactError, SourceArtifacts
import mcp_common as common
import mcp_ui
import oslab

W = mcp_ui.SOURCE_WIDGET

TOOLS = common.annotate_ro([
    mcp_ui.tool("source_status",
                "Source Lab readiness: ready / needs-setup / unavailable, Python/storage requirements and actions. Read-only.",
                common.obj(), read_only=True, idempotent=True, resource_uri=W["status"]),
    mcp_ui.tool("source_readiness",
                "Raw engine readiness report from source-lab/run.py status --json. Read-only.",
                common.obj(), read_only=True, idempotent=True, resource_uri=W["status"]),
    mcp_ui.tool("source_candidates",
                "Detection candidate targets on this computer (no network). Read-only.",
                common.obj(), read_only=True, resource_uri=W["candidates"]),
    mcp_ui.tool("source_runtime",
                "Saved Source Lab runtime settings (canary URL, playwright flag). Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("source_analyzer",
                "Source analyzer observe: latest crawl/analyze job summary, report snippet and source file lists. Does not start analysis.",
                common.obj(), read_only=True, resource_uri=W["analyzer"]),
    mcp_ui.tool("source_jobs",
                "List Source Lab console jobs (observe only; start stays plan/dashboard unless confirm-gated).",
                common.obj({"action": {"type": "string", "description": "Optional action filter, e.g. crawl or detect"}}),
                read_only=True, idempotent=True, resource_uri=W["analyzer"]),
    mcp_ui.tool("source_job",
                "Poll one Source Lab console job by id (observe only).",
                common.obj({"jobId": {"type": "string"}}, ["jobId"]), read_only=True, idempotent=True, resource_uri=W["analyzer"]),
    mcp_ui.tool("source_plan",
                "Build a guarded Source Lab plan without running it. Read-only preview.",
                common.obj({
                    "action": {"type": "string", "description": "status | doctor | setup | detect | crawl | …"},
                    "target": {"type": "string"},
                    "glob": {"type": "string"},
                }, ["action"]), read_only=True, resource_uri=W["plan"]),
    mcp_ui.tool("source_app_overview",
                "Source Lab overview MCP App: readiness and available actions (dashboard Overview UX).",
                common.obj(), read_only=True, idempotent=True, resource_uri=mcp_ui.LAB_APP["source"]),
])
NAMES = {tool["name"] for tool in TOOLS}
_UI_FOR = {tool["name"]: tool["_meta"]["ui"]["resourceUri"]
           for tool in TOOLS if tool.get("_meta", {}).get("ui", {}).get("resourceUri")}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    try:
        return mcp_ui.result(_dispatch(name, args, root), resource_uri=_UI_FOR.get(name))
    except ArtifactError as exc:
        status = getattr(exc, "status", 400)
        raise oslab.PlanError(str(exc), code="SOURCE_{0}".format(status)) from exc


def _analyzer(root):
    reader = SourceArtifacts(root)
    report = reader._json(("analysis", "report.json"), optional=True)
    raw = reader._read(("analysis", "summary.csv"), MAX_JSON, optional=True)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8")))) if raw else []
    jobs = common.list_console_jobs(root, "source")
    crawl = [job for job in jobs.get("jobs", []) if job.get("action") == "crawl"]
    files, truncated = control.source_lists(root)
    return {
        "run": crawl[0] if crawl else None,
        "report": report,
        "summaryCount": len(rows),
        "summaryRows": rows[:50],
        "sourceFiles": files,
        "sourceFilesTruncated": truncated,
        "jobsSource": jobs.get("source"),
        "note": "Observe only. Start crawl/analyze from the dashboard confirm flow or source_plan.",
    }


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
    if name == "source_analyzer":
        common.check(args, [])
        return _analyzer(root)
    if name == "source_jobs":
        common.check(args, ["action"])
        payload = common.list_console_jobs(root, "source")
        action = args.get("action")
        if action:
            payload["jobs"] = [job for job in payload.get("jobs", []) if job.get("action") == action]
            payload["action"] = action
        return payload
    if name == "source_job":
        common.check(args, ["jobId"], ["jobId"])
        return common.get_console_job(root, args["jobId"], "source")
    if name == "source_plan":
        common.check(args, ["action", "target", "glob"], ["action"])
        request = {"lab": "source", "action": args["action"]}
        if args.get("target"):
            request["target"] = args["target"]
        if args.get("glob"):
            request["glob"] = args["glob"]
        return oslab.plan(root, request)
    if name == "source_app_overview":
        common.check(args, [])
        return {"status": common.lab_status(root, "source")}
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
