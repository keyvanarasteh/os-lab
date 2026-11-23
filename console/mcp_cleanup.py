"""Cleanup Lab tools for the os-lab MCP server (CUX-10).

Everything the dashboard's one-click surface can do is a tool here, on the same engine and the
same guards, so an agent and a person get identical behaviour:

* read-only: status, catalog, volumes, monitor, permissions, bookmarks, history, widget,
  preferences, job;
* one click: ``cleanup_review`` scans, suggests (catalog defaults, disk pressure, bookmarks and the
  saved preferences) and builds the Trash plan. It never cleans;
* ``cleanup_clean`` runs a plan, only with ``confirm: true`` (the dashboard's confirmation dialog),
  Trash only: this surface has no permanent-delete mode, no raw path and no command argument;
* settings: preferences, monitor config, bookmarks, reveal in the file manager.

Long work is a console job. Tools wait for it up to ``timeoutSeconds`` (default 60, max 300) and
return the job id when it is still running, so the agent can poll ``cleanup_job``.
"""
from __future__ import annotations

import json
import time

import cleanup_api
import oslab

MAX_WAIT = 300
DEFAULT_WAIT = 60
TOP_ENTRIES = 25

_API = None


def _api(root):
    global _API
    if _API is None or _API.root != root:
        _API = cleanup_api.CleanupAPI(root)
    return _API


def _obj(properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


WAIT = {"timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": MAX_WAIT, "default": DEFAULT_WAIT,
                           "description": "How long to wait for the job before returning its id"}}
IDS = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200,
       "description": "Catalog entry ids from cleanup_catalog; never paths"}

TOOLS = [
    {"name": "cleanup_status", "description": "Cleanup Lab readiness: ready / needs-setup / unavailable, with requirements and capabilities. Read-only.", "inputSchema": _obj()},
    {"name": "cleanup_catalog", "description": "The detector catalog for this OS: id, name, family, risk, defaultSelected, needsPrivilege, cleanable. Read-only; paths are not returned.", "inputSchema": _obj()},
    {"name": "cleanup_volumes", "description": "Every local volume with capacity, free space and pressure. Read-only.", "inputSchema": _obj()},
    {"name": "cleanup_monitor", "description": "The background monitor: config (thresholds, critical level, reminders, notifications), per-volume state, active warnings and recent events. Read-only.", "inputSchema": _obj()},
    {"name": "cleanup_permissions", "description": "Full Disk Access and folder grants the cleaner can use, with guidance. Read-only.", "inputSchema": _obj()},
    {"name": "cleanup_bookmarks", "description": "The user's cleanup bookmarks (quick clean, auto-clean hook, size alert). Read-only.", "inputSchema": _obj()},
    {"name": "cleanup_history", "description": "The verified audit history of cleanups on this computer. Read-only.", "inputSchema": _obj()},
    {"name": "cleanup_widget", "description": "The desktop-widget snapshot and whether it is published. Read-only.", "inputSchema": _obj()},
    {"name": "cleanup_preferences", "description": "The saved suggestion preferences: mode (auto, recommended, extended), always/never entries, smallest item, free-space target. Read-only.", "inputSchema": _obj()},
    {"name": "cleanup_job", "description": "Poll one console job by id (scan, plan, clean). Read-only.", "inputSchema": _obj({"jobId": {"type": "string"}}, ["jobId"])},
    {"name": "cleanup_scan", "description": "Measure catalog entries read-only (all of them when entryIds is omitted). Returns totals and the largest entries. Removes nothing.", "inputSchema": _obj({"entryIds": IDS, **WAIT})},
    {"name": "cleanup_suggest", "description": "What to clean from a finished scan job, under the disk pressure, quick-clean bookmarks and saved preferences. Read-only.", "inputSchema": _obj({"jobId": {"type": "string"}}, ["jobId"])},
    {"name": "cleanup_review", "description": "One click: scan, suggest and build the Trash plan. Returns the suggestion (with reasons and any shortfall) and the plan to confirm. Never cleans; show the plan to the user, then call cleanup_clean.", "inputSchema": _obj({"entryIds": {**IDS, "description": "Optional override of the suggested set; catalog ids, Trash only"}, **WAIT})},
    {"name": "cleanup_quick_clean_plan", "description": "Build the Trash plan for the user's quick-clean bookmarks, as the dashboard's Quick clean does. Never cleans.", "inputSchema": _obj(dict(WAIT))},
    {"name": "cleanup_clean", "description": "Run a plan from cleanup_review or cleanup_quick_clean_plan: moves its ready items to the Trash and audits the run. Requires confirm: true after the user approved the plan. Plans expire and are single-use.", "inputSchema": _obj({"planId": {"type": "string"}, "confirm": {"type": "boolean"}, **WAIT}, ["planId", "confirm"])},
    {"name": "cleanup_preferences_save", "description": "Save suggestion preferences (stored on this computer, kept across app updates). Ids that must never be suggested stay refused by the engine.", "inputSchema": _obj({"suggestion": {"type": "object", "properties": {
        "mode": {"enum": ["auto", "recommended", "extended"]}, "include": {"type": "array", "items": {"type": "string"}},
        "exclude": {"type": "array", "items": {"type": "string"}}, "minEntryBytes": {"type": "integer", "minimum": 0},
        "targetFreeBytes": {"type": ["integer", "null"], "minimum": 1}}, "additionalProperties": False}}, ["suggestion"])},
    {"name": "cleanup_monitor_config", "description": "Replace the monitor config (enabled, intervalSeconds, cooldownSeconds, reminderSeconds, notify, volumes with minFreeBytes, minFreePercent, criticalFreeBytes). Validated by the engine.", "inputSchema": _obj({"config": {"type": "object"}}, ["config"])},
    {"name": "cleanup_monitor_evaluate", "description": "Run one monitor check now and return its state.", "inputSchema": _obj()},
    {"name": "cleanup_bookmark_add", "description": "Bookmark a catalog entry.", "inputSchema": _obj({"entryId": {"type": "string"}}, ["entryId"])},
    {"name": "cleanup_bookmark_remove", "description": "Remove a bookmark.", "inputSchema": _obj({"entryId": {"type": "string"}}, ["entryId"])},
    {"name": "cleanup_reveal", "description": "Show a catalog entry's folder in the system file manager. Takes an entry id, never a path.", "inputSchema": _obj({"entryId": {"type": "string"}}, ["entryId"])},
]
NAMES = {tool["name"] for tool in TOOLS}


def _text(value):
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


def _plain(value):
    return value.to_dict() if hasattr(value, "to_dict") else value


def _wait(api, job, args):
    limit = args.get("timeoutSeconds", DEFAULT_WAIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_WAIT:
        raise oslab.PlanError("timeoutSeconds must be between 1 and {0}".format(MAX_WAIT), code="INVALID_ARGS")
    deadline = time.time() + limit
    while job.state == "running" and time.time() < deadline:
        time.sleep(0.1)
    return job


def _scan_summary(job):
    data = _plain(job)
    result = data.get("result")
    if data["state"] == "done" and isinstance(result, dict):
        entries = sorted(result.get("entries", []), key=lambda item: -(item.get("sizeBytes") or 0))
        data["result"] = {"cancelled": result.get("cancelled"), "totals": result.get("totals"),
                          "largest": [{"id": item["id"], "name": item["name"], "sizeBytes": item.get("sizeBytes"), "unreadable": len(item.get("unreadable", []))}
                                      for item in entries[:TOP_ENTRIES]]}
    return data


def _check(args, allowed):
    unknown = set(args) - set(allowed)
    if unknown:
        raise oslab.PlanError("Unexpected argument(s): {0}".format(", ".join(sorted(unknown))), code="INVALID_ARGS")


def call(name, args, root):
    """Run one cleanup tool. Raises oslab.PlanError with a code on every refusal."""
    api = _api(root)
    try:
        return _text(_dispatch(api, name, args if isinstance(args, dict) else {}))
    except cleanup_api.CleanupError as exc:
        raise oslab.PlanError(str(exc), code="CLEANUP_{0}".format(exc.status), retry="reobserve" if exc.status in (404, 409) else None) from exc


def _dispatch(api, name, args):
    if name in ("cleanup_status", "cleanup_volumes", "cleanup_monitor", "cleanup_permissions", "cleanup_bookmarks",
                "cleanup_history", "cleanup_widget", "cleanup_preferences"):
        _check(args, [])
        return api.get("/api/cleanup/" + name.split("_", 1)[1], {})
    if name == "cleanup_catalog":
        _check(args, [])
        report = api.get("/api/cleanup/catalog", {})
        keep = ("id", "name", "family", "category", "risk", "defaultSelected", "needsPrivilege", "cleanable", "hint")
        return {"platform": report["platform"], "entries": [{key: entry.get(key) for key in keep} for entry in report["entries"]]}
    if name == "cleanup_job":
        _check(args, ["jobId"])
        return api.get("/api/cleanup/jobs/{0}".format(args.get("jobId")), {})
    if name == "cleanup_scan":
        _check(args, ["entryIds", "timeoutSeconds"])
        body = {"entryIds": args["entryIds"]} if args.get("entryIds") else {"entryIds": [e["id"] for e in api.get("/api/cleanup/catalog", {})["entries"]]}
        return _scan_summary(_wait(api, api.post("/api/cleanup/scan", body), args))
    if name == "cleanup_suggest":
        _check(args, ["jobId"])
        return api.post("/api/cleanup/suggest", {"jobId": args.get("jobId")})
    if name == "cleanup_review":
        _check(args, ["entryIds", "timeoutSeconds"])
        scan = _wait(api, api.post("/api/cleanup/scan", {"entryIds": [e["id"] for e in api.get("/api/cleanup/catalog", {})["entries"]]}), args)
        if scan.state != "done":
            return {"stage": "scan", "scan": _scan_summary(scan), "note": "The scan is still running or failed; poll cleanup_job, then call cleanup_suggest."}
        suggestion = api.post("/api/cleanup/suggest", {"jobId": scan.id})
        ids = args.get("entryIds") or [item["id"] for item in suggestion["items"]]
        if not ids:
            return {"stage": "suggest", "scan": _scan_summary(scan), "suggestion": suggestion, "plan": None, "note": "Nothing to suggest."}
        plan = _wait(api, api.post("/api/cleanup/plan", {"entryIds": ids, "mode": "trash"}), args)
        return {"stage": "plan", "scan": _scan_summary(scan), "suggestion": suggestion, "plan": _plain(plan),
                "next": "Show the plan to the user; after approval call cleanup_clean with its planId and confirm: true."}
    if name == "cleanup_quick_clean_plan":
        _check(args, ["timeoutSeconds"])
        response = api.post("/api/cleanup/bookmarks/quick-clean", {})
        return {"plan": _plain(_wait(api, response["job"], args)), "refusals": response["refusals"]}
    if name == "cleanup_clean":
        _check(args, ["planId", "confirm", "timeoutSeconds"])
        if args.get("confirm") is not True:
            raise oslab.PlanError("cleanup_clean needs confirm: true after the user approved the plan", code="CONFIRM_REQUIRED")
        return _plain(_wait(api, api.post("/api/cleanup/clean", {"planId": args.get("planId")}), args))
    if name == "cleanup_preferences_save":
        _check(args, ["suggestion"])
        return api.post("/api/cleanup/preferences", {"suggestion": args.get("suggestion")})
    if name == "cleanup_monitor_config":
        _check(args, ["config"])
        return api.post("/api/cleanup/monitor/config", args.get("config"))
    if name == "cleanup_monitor_evaluate":
        _check(args, [])
        return api.post("/api/cleanup/monitor/evaluate", {})
    if name in ("cleanup_bookmark_add", "cleanup_bookmark_remove"):
        _check(args, ["entryId"])
        return api.post("/api/cleanup/bookmarks" + ("" if name.endswith("add") else "/remove"), {"entryId": args.get("entryId")})
    if name == "cleanup_reveal":
        _check(args, ["entryId"])
        return api.post("/api/cleanup/entries/reveal", {"entryId": args.get("entryId")})
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
