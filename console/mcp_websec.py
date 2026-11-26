"""Web Sec Lab tools for the os-lab MCP server.

Everything the workbench can do is a tool here, on the same console API, engine and
scope guard, so an agent and a person get identical behaviour (the pattern is
``mcp_cleanup.py``):

* read-only: status, catalogue, guides, preferences, history, reports, one report,
  compare, job;
* review: ``websec_review`` normalizes the target, asks the scope guard and lists
  the checks a scan would run. It never touches the target;
* ``websec_scan`` runs a scope-checked scan as a console job. Intrusive checks need
  ``active: true`` *and* ``confirm: true`` (the workbench's confirmation dialog);
  a passive scan, like the workbench's one-click Scan, needs neither;
* ``websec_bulk`` validates up to 20 targets, passive only; ``websec_scan_cancel``
  stops a job; ``websec_preferences_save`` stores the workbench choices;
* the monitor: ``websec_monitor`` (read-only), ``websec_monitor_config`` and
  ``websec_monitor_run`` (always passive, scope-checked).

There is no raw command, path or URL argument: targets are host names the console
validates, reports are names it validates, and every network call still goes
through the scope guard. Long work waits up to ``timeoutSeconds`` (default 60,
max 300) and otherwise returns the job id for ``websec_job``.
"""
from __future__ import annotations

import json
import time

import mcp_ui
import oslab
import websec_api

MAX_WAIT = 300
DEFAULT_WAIT = 60
TOP_FINDINGS = 25
MAX_REPORT_CHARS = 200_000


def _obj(properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


WAIT = {"timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": MAX_WAIT, "default": DEFAULT_WAIT,
                           "description": "How long to wait for the job before returning its id"}}
TARGET = {"type": "string", "description": "A host name or address listed in the declared scope (scope.json)"}
REPORT = {"type": "string", "description": "A stored report name from websec_reports, such as 20261124T000000Z-95.json"}
SCAN = {
    "target": TARGET,
    "preset": {"enum": ["quick", "standard", "full"], "default": "standard"},
    "scheme": {"enum": ["http", "https"], "default": "https"},
    "modules": {"type": "array", "items": {"type": "string"}, "maxItems": 40,
                "description": "Check ids from websec_catalogue; replaces the preset when given"},
    "active": {"type": "boolean", "default": False,
               "description": "Include the intrusive checks; needs written authorization and confirm: true"},
}

TOOLS = [
    {"name": "websec_status", "description": "Web Sec Lab readiness: ready / needs-setup / unavailable, requirements, scope summary and storage. Read-only.", "inputSchema": _obj()},
    {"name": "websec_catalogue", "description": "Every registered check: id, label, group, weight, whether it is intrusive (active), its upstream module and its SecOps guide id. Read-only.", "inputSchema": _obj()},
    {"name": "websec_guides", "description": "The SecOps guides: short defensive how-tos and the check ids each one explains. Read-only.", "inputSchema": _obj()},
    {"name": "websec_preferences", "description": "The saved workbench choices (last target, preset, protocol, check selection, pacing, bulk preset). Intrusive mode is never saved. Read-only.", "inputSchema": _obj()},
    {"name": "websec_history", "description": "Recent scans, newest first: target, time, grade, score, finding counts and the stored report name. Read-only.", "inputSchema": _obj({"target": TARGET, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}})},
    {"name": "websec_reports", "description": "Stored report names for one target, newest first. Read-only.", "inputSchema": _obj({"target": TARGET}, ["target"])},
    {"name": "websec_report", "description": "One stored report rendered as markdown (default), json, sarif, text or html. Read-only.", "inputSchema": _obj({"target": TARGET, "name": REPORT, "format": {"enum": ["markdown", "json", "sarif", "text", "html"], "default": "markdown"}}, ["target", "name"])},
    {"name": "websec_compare", "description": "What changed between two stored runs of one target: grade and score delta, new and resolved findings, check status changes. Defaults to the latest two runs. Read-only.", "inputSchema": _obj({"target": TARGET, "old": REPORT, "new": REPORT}, ["target"])},
    {"name": "websec_job", "description": "Poll one scan or bulk job by id; a finished scan returns its graded summary. Read-only.", "inputSchema": _obj({"jobId": {"type": "string"}}, ["jobId"])},
    {"name": "websec_review", "description": "The review step: normalizes the target, asks the scope guard and lists every check a scan would run (intrusive ones held back unless active). Sends nothing to the target. Show it to the user, then call websec_scan.", "inputSchema": _obj(dict(SCAN), ["target"])},
    {"name": "websec_scan", "description": "Run a scope-checked scan as a job and return its graded summary. A passive scan needs no confirmation; active: true runs the intrusive checks and requires confirm: true after the user approved them with written authorization.", "inputSchema": _obj({**SCAN, "confirm": {"type": "boolean"}, **WAIT}, ["target"])},
    {"name": "websec_scan_cancel", "description": "Stop a running scan or bulk job.", "inputSchema": _obj({"jobId": {"type": "string"}}, ["jobId"])},
    {"name": "websec_bulk", "description": "Validate up to 20 targets passively, one job; targets outside the scope come back as refusal rows.", "inputSchema": _obj({"targets": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}, "preset": {"enum": ["quick", "standard", "full"], "default": "quick"}, **WAIT}, ["targets"])},
    {"name": "websec_monitor", "description": "The opt-in passive monitor: config (targets, interval, preset, alert threshold, notifications, reminders, scope warning), per-target state, active warnings and recent events. Read-only.", "inputSchema": _obj()},
    {"name": "websec_monitor_config", "description": "Replace the monitor config: enabled, targets (host names in scope, at most 10), intervalMinutes (60, 360, 1440, 10080), preset (quick or standard), alertOn (critical, high, medium, low), notify, reminderHours (0-168), scopeWarnDays (1-60). Monitor scans are always passive.", "inputSchema": _obj({"config": {"type": "object"}}, ["config"])},
    {"name": "websec_monitor_run", "description": "Run one monitor check now over every configured target (passive, scope-checked). Refused while a scan is running.", "inputSchema": _obj()},
    {"name": "websec_stats", "description": "Totals over every stored run: targets, runs, reports and bytes, favourites, the grade of each target's latest run and its finding counts. Read-only.", "inputSchema": _obj()},
    {"name": "websec_favourite", "description": "Mark (on: true) or unmark a stored run as a favourite; favourites survive history pruning (at most 10 per target).", "inputSchema": _obj({"target": TARGET, "name": REPORT, "on": {"type": "boolean", "default": True}}, ["target", "name"])},
    {"name": "websec_delete_runs", "description": "Delete stored runs of one target by report name. Irreversible: requires confirm: true after the user approved the list.", "inputSchema": _obj({"target": TARGET, "names": {"type": "array", "items": REPORT, "minItems": 1, "maxItems": 50}, "confirm": {"type": "boolean"}}, ["target", "names", "confirm"])},
    {"name": "websec_clear_history", "description": "Delete every stored run of one target, or of all targets with all: true. Irreversible: requires confirm: true after the user approved it.", "inputSchema": _obj({"target": TARGET, "all": {"type": "boolean"}, "confirm": {"type": "boolean"}}, ["confirm"])},
    {"name": "websec_preferences_save", "description": "Save the workbench choices on this computer (kept across restarts and app updates). Takes scan {target, preset, scheme, modules, timeout, deadline} and bulk {preset}; there is no intrusive setting.", "inputSchema": _obj({"preferences": {"type": "object", "properties": {"scan": {"type": "object"}, "bulk": {"type": "object"}}, "additionalProperties": False}}, ["preferences"])},
]
NAMES = {tool["name"] for tool in TOOLS}

# Annotate every websec tool so hosts can gate write / destructive calls.
_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_RW = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
_DEST = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}
_RO_SET = {
    "websec_status", "websec_catalogue", "websec_guides", "websec_preferences", "websec_history",
    "websec_reports", "websec_report", "websec_compare", "websec_job", "websec_review",
    "websec_monitor", "websec_stats",
}
_DEST_SET = {"websec_delete_runs", "websec_clear_history", "websec_scan_cancel"}
for _tool in TOOLS:
    name = _tool["name"]
    if name in _RO_SET:
        _tool["annotations"] = dict(_RO)
    elif name in _DEST_SET:
        _tool["annotations"] = dict(_DEST)
    else:
        _tool["annotations"] = dict(_RW)



def _text(value):
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


def _check(args, allowed, required=()):
    unknown = set(args) - set(allowed)
    if unknown:
        raise oslab.PlanError("Unexpected argument(s): {0}".format(", ".join(sorted(unknown))), code="INVALID_ARGS")
    missing = [key for key in required if args.get(key) in (None, "")]
    if missing:
        raise oslab.PlanError("Missing argument(s): {0}".format(", ".join(missing)), code="INVALID_ARGS")


def _limit(args):
    limit = args.get("timeoutSeconds", DEFAULT_WAIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_WAIT:
        raise oslab.PlanError("timeoutSeconds must be between 1 and {0}".format(MAX_WAIT), code="INVALID_ARGS")
    return limit


def _wait(api, view, limit):
    deadline = time.time() + limit
    while view["state"] == "running" and time.time() < deadline:
        time.sleep(0.25)
        view = api.job(view["id"])
    return view


def _brief(view):
    """A job view an agent can read: the report becomes its grade and top findings."""
    data = {key: view.get(key) for key in ("id", "kind", "state", "target", "preset", "active", "error") if key in view}
    if view.get("progress"):
        data["progress"] = view["progress"]
    report = view.get("report")
    if isinstance(report, dict):
        findings = report.get("findings") or []
        data["report"] = {
            "target": report.get("target"), "grade": report.get("grade"), "score": report.get("score"),
            "summary": report.get("summary"), "refused": report.get("refused"), "refusal": report.get("refusal"),
            "modules": [{"id": m.get("id"), "status": m.get("status"), "findings": m.get("findings")}
                        for m in report.get("modules") or []],
            "findings": [{key: f.get(key) for key in ("severity", "module", "title", "remediation", "cwe", "owasp")
                          if f.get(key) is not None}
                         for f in findings[:TOP_FINDINGS]],
            "omittedFindings": max(0, len(findings) - TOP_FINDINGS),
        }
        data["next"] = "Read the full report with websec_report, or compare runs with websec_compare."
    if view.get("results") is not None:
        data["results"] = view["results"]
    if view["state"] == "running":
        data["next"] = "Still running; poll websec_job with this id."
    return data


def _scan_payload(args):
    payload = {key: args[key] for key in ("target", "preset", "scheme", "modules", "active") if key in args}
    payload["active"] = bool(args.get("active"))
    return payload


def call(name, args, root):
    """Run one Web Sec Lab tool. Raises oslab.PlanError with a code on every refusal."""
    api = websec_api.api_for(root)
    try:
        return _text(_dispatch(api, name, args if isinstance(args, dict) else {}))
    except websec_api.WebSecError as exc:
        raise oslab.PlanError(str(exc), code="WEBSEC_{0}".format(exc.status),
                              retry="reobserve" if exc.status in (404, 409) else None) from exc


def _dispatch(api, name, args):
    if name == "websec_status":
        _check(args, [])
        return api.status()
    if name == "websec_catalogue":
        _check(args, [])
        by_check = api.guides().get("byCheck", {})
        modules = api.modules().get("modules", [])
        return {"modules": [{**module, "guide": by_check.get(module.get("id"), "")} for module in modules]}
    if name == "websec_guides":
        _check(args, [])
        return api.guides()
    if name == "websec_preferences":
        _check(args, [])
        return api.preferences()
    if name == "websec_history":
        _check(args, ["target", "limit"])
        limit = args.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise oslab.PlanError("limit must be between 1 and 100", code="INVALID_ARGS")
        return api.history(args.get("target") or None, limit)
    if name == "websec_reports":
        _check(args, ["target"], ["target"])
        return api.reports(args["target"])
    if name == "websec_report":
        _check(args, ["target", "name", "format"], ["target", "name"])
        content = api.report(args["target"], args["name"], args.get("format", "markdown"))
        return {"name": args["name"], "format": args.get("format", "markdown"),
                "content": content[:MAX_REPORT_CHARS], "truncated": len(content) > MAX_REPORT_CHARS}
    if name == "websec_compare":
        _check(args, ["target", "old", "new"], ["target"])
        old, new = args.get("old"), args.get("new")
        if not (old and new):
            names = [entry["name"] for entry in api.reports(args["target"]).get("reports", [])]
            if len(names) < 2:
                raise oslab.PlanError("Compare needs two stored runs of this target", code="WEBSEC_404", retry="reobserve")
            # reports are listed newest first
            new, old = new or names[0], old or names[1]
        return api.compare(args["target"], old, new)
    if name == "websec_job":
        _check(args, ["jobId"], ["jobId"])
        return _brief(api.job(str(args["jobId"])))
    if name == "websec_review":
        _check(args, list(SCAN), ["target"])
        plan = api.plan(_scan_payload(args))
        plan["next"] = ("Show this plan to the user. Run it with websec_scan"
                        + (" (intrusive checks need confirm: true)." if plan.get("intrusive") else "."))
        return plan
    if name == "websec_scan":
        _check(args, [*SCAN, "confirm", "timeoutSeconds"], ["target"])
        limit = _limit(args)
        if args.get("active") and args.get("confirm") is not True:
            raise oslab.PlanError("An active scan needs confirm: true after the user approved the intrusive checks "
                                  "with written authorization; review it with websec_review first",
                                  code="CONFIRM_REQUIRED")
        return _brief(_wait(api, api.start_scan(_scan_payload(args)), limit))
    if name == "websec_scan_cancel":
        _check(args, ["jobId"], ["jobId"])
        return _brief(api.cancel(str(args["jobId"])))
    if name == "websec_bulk":
        _check(args, ["targets", "preset", "timeoutSeconds"], ["targets"])
        limit = _limit(args)
        payload = {"targets": args["targets"], "preset": args.get("preset", "quick")}
        return _brief(_wait(api, api.start_bulk(payload), limit))
    if name == "websec_monitor":
        _check(args, [])
        return api.monitor_status()
    if name == "websec_monitor_config":
        _check(args, ["config"], ["config"])
        return api.save_monitor({"config": args["config"]})
    if name == "websec_monitor_run":
        _check(args, [])
        return api.run_monitor()
    if name == "websec_stats":
        _check(args, [])
        return api.run_stats()
    if name == "websec_favourite":
        _check(args, ["target", "name", "on"], ["target", "name"])
        return api.manage_runs("favourite", {"target": args["target"], "name": args["name"], "on": args.get("on", True) is not False})
    if name in ("websec_delete_runs", "websec_clear_history"):
        _check(args, ["target", "names", "confirm"] if name == "websec_delete_runs" else ["target", "all", "confirm"])
        if args.get("confirm") is not True:
            raise oslab.PlanError(f"{name} deletes stored reports; it needs confirm: true after the user approved it",
                                  code="CONFIRM_REQUIRED")
        body = {key: args[key] for key in ("target", "names", "all") if key in args}
        return api.manage_runs("delete" if name == "websec_delete_runs" else "clear", body)
    if name == "websec_preferences_save":
        _check(args, ["preferences"], ["preferences"])
        return api.save_preferences(args["preferences"])
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
