"""Cleanup Lab tools for the os-lab MCP server (CUX-10 + write/UI extensions).

Everything the dashboard's one-click surface can do is a tool here, on the same engine and the
same guards, so an agent and a person get identical behaviour:

* read-only: status, catalog, volumes, monitor, permissions, bookmarks, history, widget,
  preferences, job;
* write counterparts for every mutatable surface: preferences save, monitor config/evaluate,
  bookmark add/update/remove, reveal, permissions open/reveal-app/reset, job cancel,
  widget refresh, explicit Trash plan;
* one click: ``cleanup_review`` scans, suggests and builds the Trash plan. It never cleans;
* ``cleanup_clean`` runs a plan only with ``confirm: true`` (Trash only);
* MCP Apps widgets (first batch) on the tools that benefit from UX; three lab apps
  (overview / review / settings) built from the dashboard Cleanup Lab UX parts.

Long work is a console job. Tools wait for it up to ``timeoutSeconds`` (default 60, max 300) and
return the job id when it is still running, so the agent can poll ``cleanup_job``.
"""
from __future__ import annotations

import time

import cleanup_api
import mcp_cleanup_aux
import mcp_ui
import oslab

MAX_WAIT = 300
DEFAULT_WAIT = 60
TOP_ENTRIES = 25
W = mcp_ui.CLEANUP_WIDGET
A = mcp_ui.CLEANUP_APP

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
    mcp_ui.tool("cleanup_status",
                "Cleanup Lab readiness: ready / needs-setup / unavailable, with requirements and capabilities. Read-only.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["status"]),
    mcp_ui.tool("cleanup_catalog",
                "The detector catalog for this OS: id, name, family, risk, defaultSelected, needsPrivilege, cleanable. Read-only; paths are not returned.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["catalog"]),
    mcp_ui.tool("cleanup_volumes",
                "Every local volume with capacity, free space and pressure. Read-only.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["volumes"]),
    mcp_ui.tool("cleanup_monitor",
                "The background monitor: config, per-volume state, active warnings and recent events. Read-only.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["monitor"]),
    mcp_ui.tool("cleanup_permissions",
                "Full Disk Access and folder grants the cleaner can use, with guidance. Read-only.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["permissions"]),
    mcp_ui.tool("cleanup_bookmarks",
                "The user's cleanup bookmarks (quick clean, auto-clean hook, size alert). Read-only.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["bookmarks"]),
    mcp_ui.tool("cleanup_history",
                "The verified audit history of cleanups on this computer. Read-only.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["history"]),
    mcp_ui.tool("cleanup_widget",
                "The desktop-widget snapshot and whether it is published. Read-only.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["widget"]),
    mcp_ui.tool("cleanup_preferences",
                "The saved suggestion preferences: mode, always/never entries, smallest item, free-space target. Read-only.",
                _obj(), read_only=True, idempotent=True, resource_uri=W["preferences"]),
    mcp_ui.tool("cleanup_job",
                "Poll one console job by id (scan, plan, clean). Read-only.",
                _obj({"jobId": {"type": "string"}}, ["jobId"]), read_only=True, idempotent=True, resource_uri=W["job"]),
    mcp_ui.tool("cleanup_scan",
                "Measure catalog entries read-only (all of them when entryIds is omitted). Returns totals and the largest entries. Removes nothing.",
                _obj({"entryIds": IDS, **WAIT}), read_only=True),
    mcp_ui.tool("cleanup_suggest",
                "What to clean from a finished scan job, under disk pressure, quick-clean bookmarks and saved preferences. Read-only.",
                _obj({"jobId": {"type": "string"}}, ["jobId"]), read_only=True, idempotent=True, resource_uri=W["suggest"]),
    mcp_ui.tool("cleanup_review",
                "One click: scan, suggest and build the Trash plan. Never cleans; show the plan, then call cleanup_clean.",
                _obj({"entryIds": {**IDS, "description": "Optional override of the suggested set; catalog ids, Trash only"}, **WAIT}),
                read_only=True, resource_uri=W["review"]),
    mcp_ui.tool("cleanup_quick_clean_plan",
                "Build the Trash plan for the user's quick-clean bookmarks, as the dashboard's Quick clean does. Never cleans.",
                _obj(dict(WAIT)), read_only=True, resource_uri=W["review"]),
    mcp_ui.tool("cleanup_plan",
                "Build a Trash-only plan for catalog entry ids (never paths). Never cleans; show the plan, then call cleanup_clean with confirm: true.",
                _obj({"entryIds": IDS, **WAIT}, ["entryIds"]), read_only=True, resource_uri=W["review"]),
    mcp_ui.tool("cleanup_clean",
                "Run a plan from cleanup_review / cleanup_plan / cleanup_quick_clean_plan: moves ready items to the Trash and audits the run. Requires confirm: true. Plans expire and are single-use.",
                _obj({"planId": {"type": "string"}, "confirm": {"type": "boolean"}, **WAIT}, ["planId", "confirm"]),
                destructive=True),
    mcp_ui.tool("cleanup_job_cancel",
                "Cancel a running cleanup console job (scan, plan or clean).",
                _obj({"jobId": {"type": "string"}}, ["jobId"]), destructive=True, idempotent=True),
    mcp_ui.tool("cleanup_preferences_save",
                "Save suggestion preferences (stored on this computer, kept across app updates).",
                _obj({"suggestion": {"type": "object", "properties": {
                    "mode": {"enum": ["auto", "recommended", "extended"]},
                    "include": {"type": "array", "items": {"type": "string"}},
                    "exclude": {"type": "array", "items": {"type": "string"}},
                    "minEntryBytes": {"type": "integer", "minimum": 0},
                    "targetFreeBytes": {"type": ["integer", "null"], "minimum": 1}},
                    "additionalProperties": False}}, ["suggestion"]),
                idempotent=True, resource_uri=W["preferences"]),
    mcp_ui.tool("cleanup_monitor_config",
                "Replace the monitor config (enabled, intervalSeconds, cooldownSeconds, reminderSeconds, notify, volumes…). Validated by the engine.",
                _obj({"config": {"type": "object"}}, ["config"]), idempotent=True, resource_uri=W["monitor"]),
    mcp_ui.tool("cleanup_monitor_evaluate",
                "Run one monitor check now and return its state.",
                _obj(), resource_uri=W["monitor"]),
    mcp_ui.tool("cleanup_bookmark_add",
                "Bookmark a catalog entry.",
                _obj({"entryId": {"type": "string"}}, ["entryId"]), idempotent=True, resource_uri=W["bookmarks"]),
    mcp_ui.tool("cleanup_bookmark_update",
                "Update a bookmark's priority, quickClean, autoCleanHook and/or sizeAlert flags.",
                _obj({"entryId": {"type": "string"},
                      "priority": {"type": "integer", "minimum": 0, "maximum": 100},
                      "quickClean": {"type": "boolean"},
                      "autoCleanHook": {"type": "boolean"},
                      "sizeAlert": {"type": "object"}}, ["entryId"]),
                idempotent=True, resource_uri=W["bookmarks"]),
    mcp_ui.tool("cleanup_bookmark_remove",
                "Remove a bookmark.",
                _obj({"entryId": {"type": "string"}}, ["entryId"]), destructive=True, idempotent=True, resource_uri=W["bookmarks"]),
    mcp_ui.tool("cleanup_reveal",
                "Show a catalog entry's folder in the system file manager. Takes an entry id, never a path.",
                _obj({"entryId": {"type": "string"}}, ["entryId"]), open_world=True),
    mcp_ui.tool("cleanup_permissions_open",
                "Open the system settings pane for one Cleanup Lab permission id (write counterpart to cleanup_permissions).",
                _obj({"permissionId": {"type": "string"}}, ["permissionId"]), open_world=True, resource_uri=W["permissions"]),
    mcp_ui.tool("cleanup_permissions_reveal_app",
                "Reveal the running host app in the file manager so the user can drag it into Full Disk Access.",
                _obj(), open_world=True, resource_uri=W["permissions"]),
    mcp_ui.tool("cleanup_permissions_reset",
                "Reset this host app's Full Disk Access record via tccutil. Requires confirm: true; the user must re-grant afterwards.",
                _obj({"confirm": {"type": "boolean"}}, ["confirm"]), destructive=True, open_world=True, resource_uri=W["permissions"]),
    mcp_ui.tool("cleanup_widget_refresh",
                "Rebuild and publish the desktop-widget snapshot (write counterpart to cleanup_widget).",
                _obj(), idempotent=True, resource_uri=W["widget"]),
    # MCP Apps built from the Cleanup Lab dashboard UX parts.
    mcp_ui.tool("cleanup_app_overview",
                "Cleanup Lab overview app: storage hero, readiness and links into review/settings (dashboard Overview UX).",
                _obj(), read_only=True, idempotent=True, resource_uri=A["overview"]),
    mcp_ui.tool("cleanup_app_review",
                "Cleanup Lab review app: one-click scan → suggest → Trash plan, with confirm affordance (dashboard Clean UX).",
                _obj({"entryIds": {**IDS, "description": "Optional override of the suggested set"}, **WAIT}),
                read_only=True, resource_uri=A["review"]),
    mcp_ui.tool("cleanup_app_settings",
                "Cleanup Lab settings app: permissions, bookmarks, monitor and suggestion preferences (dashboard Settings UX).",
                _obj(), read_only=True, idempotent=True, resource_uri=A["settings"]),
]
TOOLS += mcp_cleanup_aux.TOOLS
NAMES = {tool["name"] for tool in TOOLS}

# Tools that attach a UI resource — call() adds structuredContent + _meta.
_UI_FOR = {tool["name"]: tool["_meta"]["ui"]["resourceUri"] for tool in TOOLS if tool.get("_meta", {}).get("ui", {}).get("resourceUri")}


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
                          "largest": [{"id": item["id"], "name": item["name"], "sizeBytes": item.get("sizeBytes"),
                                       "unreadable": len(item.get("unreadable", []))}
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
        value = _dispatch(api, name, args if isinstance(args, dict) else {})
        return mcp_ui.result(value, resource_uri=_UI_FOR.get(name))
    except cleanup_api.CleanupError as exc:
        raise oslab.PlanError(str(exc), code="CLEANUP_{0}".format(exc.status),
                              retry="reobserve" if exc.status in (404, 409) else None) from exc


def _review(api, args):
    scan = _wait(api, api.post("/api/cleanup/scan", {"entryIds": [e["id"] for e in api.get("/api/cleanup/catalog", {})["entries"]]}), args)
    if scan.state != "done":
        return {"stage": "scan", "scan": _scan_summary(scan),
                "note": "The scan is still running or failed; poll cleanup_job, then call cleanup_suggest."}
    suggestion = api.post("/api/cleanup/suggest", {"jobId": scan.id})
    ids = args.get("entryIds") or [item["id"] for item in suggestion["items"]]
    if not ids:
        return {"stage": "suggest", "scan": _scan_summary(scan), "suggestion": suggestion, "plan": None, "note": "Nothing to suggest."}
    plan = _wait(api, api.post("/api/cleanup/plan", {"entryIds": ids, "mode": "trash"}), args)
    return {"stage": "plan", "scan": _scan_summary(scan), "suggestion": suggestion, "plan": _plain(plan),
            "next": "Show the plan to the user; after approval call cleanup_clean with its planId and confirm: true."}


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
    if name == "cleanup_job_cancel":
        _check(args, ["jobId"])
        return api.post("/api/cleanup/jobs/{0}/cancel".format(args.get("jobId")), {})
    if name == "cleanup_scan":
        _check(args, ["entryIds", "timeoutSeconds"])
        body = {"entryIds": args["entryIds"]} if args.get("entryIds") else {
            "entryIds": [e["id"] for e in api.get("/api/cleanup/catalog", {})["entries"]]}
        return _scan_summary(_wait(api, api.post("/api/cleanup/scan", body), args))
    if name == "cleanup_suggest":
        _check(args, ["jobId"])
        return api.post("/api/cleanup/suggest", {"jobId": args.get("jobId")})
    if name in ("cleanup_review", "cleanup_app_review"):
        _check(args, ["entryIds", "timeoutSeconds"])
        return _review(api, args)
    if name == "cleanup_quick_clean_plan":
        _check(args, ["timeoutSeconds"])
        response = api.post("/api/cleanup/bookmarks/quick-clean", {})
        return {"plan": _plain(_wait(api, response["job"], args)), "refusals": response["refusals"]}
    if name == "cleanup_plan":
        _check(args, ["entryIds", "timeoutSeconds"])
        plan = _wait(api, api.post("/api/cleanup/plan", {"entryIds": args["entryIds"], "mode": "trash"}), args)
        return {"stage": "plan", "plan": _plain(plan),
                "next": "Show the plan to the user; after approval call cleanup_clean with its planId and confirm: true."}
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
    if name == "cleanup_bookmark_add":
        _check(args, ["entryId"])
        return api.post("/api/cleanup/bookmarks", {"entryId": args.get("entryId")})
    if name == "cleanup_bookmark_update":
        _check(args, ["entryId", "priority", "quickClean", "autoCleanHook", "sizeAlert"])
        body = {key: args[key] for key in ("entryId", "priority", "quickClean", "autoCleanHook", "sizeAlert") if key in args}
        return api.post("/api/cleanup/bookmarks/update", body)
    if name == "cleanup_bookmark_remove":
        _check(args, ["entryId"])
        return api.post("/api/cleanup/bookmarks/remove", {"entryId": args.get("entryId")})
    if name == "cleanup_reveal":
        _check(args, ["entryId"])
        return api.post("/api/cleanup/entries/reveal", {"entryId": args.get("entryId")})
    if name == "cleanup_permissions_open":
        _check(args, ["permissionId"])
        return api.post("/api/cleanup/permissions/open-settings", {"permissionId": args.get("permissionId")})
    if name == "cleanup_permissions_reveal_app":
        _check(args, [])
        return api.post("/api/cleanup/permissions/reveal-app", {})
    if name == "cleanup_permissions_reset":
        _check(args, ["confirm"])
        if args.get("confirm") is not True:
            raise oslab.PlanError("cleanup_permissions_reset needs confirm: true", code="CONFIRM_REQUIRED")
        return api.post("/api/cleanup/permissions/reset", {})
    if name == "cleanup_widget_refresh":
        _check(args, [])
        cleanup_api.publish_widget(api.root)
        return api.get("/api/cleanup/widget", {})
    if name == "cleanup_app_overview":
        _check(args, [])
        volumes = api.get("/api/cleanup/volumes", {})
        if isinstance(volumes, dict) and "volumes" in volumes:
            volumes = volumes["volumes"]
        return {"status": api.get("/api/cleanup/status", {}), "volumes": volumes}
    if name == "cleanup_app_settings":
        _check(args, [])
        return {
            "permissions": api.get("/api/cleanup/permissions", {}),
            "bookmarks": api.get("/api/cleanup/bookmarks", {}),
            "monitor": api.get("/api/cleanup/monitor", {}),
            "preferences": api.get("/api/cleanup/preferences", {}),
            "widget": api.get("/api/cleanup/widget", {}),
        }
    if name in mcp_cleanup_aux.NAMES:
        return mcp_cleanup_aux._dispatch(api, name, args)
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
