"""Cleanup Lab auxiliary MCP tools (explorer, containers, sims, VMs, leftovers…).

Read/observe surfaces first; mutate paths follow preview → confirm: true, matching
the dashboard contracts in cleanup_api.
"""
from __future__ import annotations

import time

import cleanup_api
import mcp_ui
import oslab

MAX_WAIT = 300
DEFAULT_WAIT = 60

WAIT = {
    "timeoutSeconds": {
        "type": "integer", "minimum": 1, "maximum": MAX_WAIT, "default": DEFAULT_WAIT,
        "description": "How long to wait for the job before returning its id",
    }
}
CONFIRM = {"confirm": {"type": "boolean", "description": "Must be true after the user approved the preview"}}
PREVIEW_ID = {"previewId": {"type": "string", "description": "Id from the matching preview/plan tool"}}
ACTION_ID = {"actionId": {"type": "string", "description": "Action id from the matching inventory"}}
DEVICE_IDS = {
    "deviceIds": {
        "type": "array", "items": {"type": "string"},
        "description": "Optional device ids to scope the preview",
    }
}


def _obj(properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _tool(name, description, schema, **flags):
    return mcp_ui.tool(name, description, schema, **flags)


TOOLS = [
    _tool("cleanup_explorer_roots",
          "Space Explorer root folders the dashboard opens with. Read-only.",
          _obj(), read_only=True, idempotent=True),
    _tool("cleanup_explorer_scan",
          "Scan a Space Explorer root (or subtree). Read-only measurement job; removes nothing.",
          _obj({"rootId": {"type": "string"}, "relative": {"type": "string"}, **WAIT}, ["rootId"]),
          read_only=True),
    _tool("cleanup_deep_roots",
          "Deep-scan roots the Cleanup Lab can measure. Read-only.",
          _obj(), read_only=True, idempotent=True),
    _tool("cleanup_deep_scan",
          "Start a deep scan for configured root ids. Read-only measurement job; removes nothing.",
          _obj({"rootIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "minIdleDays": {"type": "integer", "minimum": 0},
                **WAIT}, ["rootIds"]), read_only=True),
    _tool("cleanup_containers",
          "Container engine capabilities and prune actions. Read-only inventory.",
          _obj(), read_only=True, idempotent=True),
    _tool("cleanup_containers_preview",
          "Preview a container prune action (candidates + command). Never prunes.",
          _obj({"actionId": ACTION_ID["actionId"]}, ["actionId"]), read_only=True),
    _tool("cleanup_containers_prune",
          "Run a container prune from cleanup_containers_preview. Requires confirm: true.",
          _obj({**PREVIEW_ID, **CONFIRM, **WAIT}, ["previewId", "confirm"]), destructive=True),
    _tool("cleanup_simulators",
          "iOS Simulator inventory, downloaded runtimes and clean actions. Read-only.",
          _obj(), read_only=True, idempotent=True),
    _tool("cleanup_simulators_preview",
          "Preview a simulator clean action. Never deletes.",
          _obj({"actionId": ACTION_ID["actionId"], **DEVICE_IDS}, ["actionId"]), read_only=True),
    _tool("cleanup_simulators_run",
          "Run a simulator clean from cleanup_simulators_preview. Requires confirm: true.",
          _obj({**PREVIEW_ID, **CONFIRM, **WAIT}, ["previewId", "confirm"]), destructive=True),
    _tool("cleanup_emulators",
          "Android emulator inventory and clean actions. Read-only.",
          _obj(), read_only=True, idempotent=True),
    _tool("cleanup_emulators_preview",
          "Preview an emulator clean action. Never deletes.",
          _obj({"actionId": ACTION_ID["actionId"], **DEVICE_IDS}, ["actionId"]), read_only=True),
    _tool("cleanup_emulators_run",
          "Run an emulator clean from cleanup_emulators_preview. Requires confirm: true.",
          _obj({**PREVIEW_ID, **CONFIRM, **WAIT}, ["previewId", "confirm"]), destructive=True),
    _tool("cleanup_vms_scan",
          "Scan virtual-machine disk usage. Read-only measurement job.",
          _obj(dict(WAIT)), read_only=True),
    _tool("cleanup_packages_scan",
          "Scan package-manager caches the Cleanup Lab knows about. Read-only measurement job.",
          _obj(dict(WAIT)), read_only=True),
    _tool("cleanup_leftovers_scan",
          "Scan leftover app support files. Read-only measurement job.",
          _obj({"macos": {"type": "boolean", "description": "Use the macOS-specific leftovers scanner"}, **WAIT}),
          read_only=True),
    _tool("cleanup_relocation",
          "Relocation status: eligible volumes and current links. Read-only.",
          _obj(), read_only=True, idempotent=True),
    _tool("cleanup_relocation_plan",
          "Build a relocation preview/plan job. Never moves data.",
          _obj({"action": {"enum": ["move", "restore", "relink", "resume"]},
                "entryId": {"type": "string"},
                "destination": {"type": "string", "description": "Volume mount point from cleanup_relocation"},
                **WAIT},
               ["action", "entryId", "destination"]),
          read_only=True),
    _tool("cleanup_relocation_run",
          "Run a relocation from cleanup_relocation_plan. Requires confirm: true.",
          _obj({**PREVIEW_ID, **CONFIRM, **WAIT}, ["previewId", "confirm"]), destructive=True),
    _tool("cleanup_privileged",
          "Privileged cleanup capabilities (elevation + available actions). Read-only.",
          _obj(), read_only=True, idempotent=True),
    _tool("cleanup_privileged_preview",
          "Preview a privileged cleanup action. Never runs elevation.",
          _obj({"actionId": ACTION_ID["actionId"]}, ["actionId"]), read_only=True),
    _tool("cleanup_privileged_run",
          "Run a privileged cleanup from cleanup_privileged_preview. Requires confirm: true.",
          _obj({**PREVIEW_ID, **CONFIRM, **WAIT}, ["previewId", "confirm"]), destructive=True),
    _tool("cleanup_simulator_storage",
          "Simulator storage relocation config and available destinations. Read-only.",
          _obj(), read_only=True, idempotent=True),
    _tool("cleanup_simulator_storage_save",
          "Save simulator storage relocation config (validated destinations only).",
          _obj({"config": {"type": "object", "description": "Body accepted by POST /api/cleanup/simulator-storage"}},
               ["config"]),
          idempotent=True),
    _tool("cleanup_custom_entries_add",
          "Add a custom catalog folder (path validated once; afterwards only custom.<slug> ids travel).",
          _obj({"name": {"type": "string"}, "path": {"type": "string"}}, ["name", "path"])),
    _tool("cleanup_custom_entries_remove",
          "Remove a custom.<slug> catalog entry. Requires confirm: true.",
          _obj({"entryId": {"type": "string"}, **CONFIRM}, ["entryId", "confirm"]),
          destructive=True, idempotent=True),
]
NAMES = {tool["name"] for tool in TOOLS}


def _plain(value):
    return value.to_dict() if hasattr(value, "to_dict") else value


def _wait(api, job, args):
    limit = args.get("timeoutSeconds", DEFAULT_WAIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_WAIT:
        raise oslab.PlanError("timeoutSeconds must be between 1 and {0}".format(MAX_WAIT), code="INVALID_ARGS")
    deadline = time.time() + limit
    while getattr(job, "state", None) == "running" and time.time() < deadline:
        time.sleep(0.1)
    return job


def _check(args, allowed):
    unknown = set(args) - set(allowed)
    if unknown:
        raise oslab.PlanError("Unexpected argument(s): {0}".format(", ".join(sorted(unknown))), code="INVALID_ARGS")


def _require_confirm(args):
    if args.get("confirm") is not True:
        raise oslab.PlanError("This tool needs confirm: true after the user approved the preview",
                              code="CONFIRM_REQUIRED")


def call(name, args, root):
    api = cleanup_api.CleanupAPI(root) if not hasattr(call, "_api") or call._api.root != root else call._api
    call._api = api
    try:
        return mcp_ui.result(_dispatch(api, name, args if isinstance(args, dict) else {}))
    except cleanup_api.CleanupError as exc:
        raise oslab.PlanError(str(exc), code="CLEANUP_{0}".format(exc.status),
                              retry="reobserve" if exc.status in (404, 409) else None) from exc


def _dispatch(api, name, args):
    if name == "cleanup_explorer_roots":
        _check(args, [])
        return api.get("/api/cleanup/explorer/roots", {})
    if name == "cleanup_explorer_scan":
        _check(args, ["rootId", "relative", "timeoutSeconds"])
        body = {"rootId": args["rootId"]}
        if args.get("relative"):
            body["relative"] = args["relative"]
            return _plain(_wait(api, api.post("/api/cleanup/explorer/subtree", body), args))
        return _plain(_wait(api, api.post("/api/cleanup/explorer/scan", body), args))
    if name == "cleanup_deep_roots":
        _check(args, [])
        return api.get("/api/cleanup/deep-roots", {})
    if name == "cleanup_deep_scan":
        _check(args, ["rootIds", "minIdleDays", "timeoutSeconds"])
        body = {"rootIds": args["rootIds"]}
        if args.get("minIdleDays") is not None:
            body["minIdleDays"] = args["minIdleDays"]
        return _plain(_wait(api, api.post("/api/cleanup/deep-scan", body), args))
    if name == "cleanup_containers":
        _check(args, [])
        return api.get("/api/cleanup/containers", {})
    if name == "cleanup_containers_preview":
        _check(args, ["actionId"])
        return api.post("/api/cleanup/containers/preview", {"actionId": args["actionId"]})
    if name == "cleanup_containers_prune":
        _check(args, ["previewId", "confirm", "timeoutSeconds"])
        _require_confirm(args)
        return _plain(_wait(api, api.post("/api/cleanup/containers/prune", {"previewId": args["previewId"]}), args))
    if name == "cleanup_simulators":
        _check(args, [])
        return api.get("/api/cleanup/simulators", {})
    if name == "cleanup_simulators_preview":
        _check(args, ["actionId", "deviceIds"])
        body = {"actionId": args["actionId"]}
        if args.get("deviceIds") is not None:
            body["deviceIds"] = args["deviceIds"]
        return api.post("/api/cleanup/simulators/preview", body)
    if name == "cleanup_simulators_run":
        _check(args, ["previewId", "confirm", "timeoutSeconds"])
        _require_confirm(args)
        return _plain(_wait(api, api.post("/api/cleanup/simulators/run", {"previewId": args["previewId"]}), args))
    if name == "cleanup_emulators":
        _check(args, [])
        return api.get("/api/cleanup/emulators", {})
    if name == "cleanup_emulators_preview":
        _check(args, ["actionId", "deviceIds"])
        body = {"actionId": args["actionId"]}
        if args.get("deviceIds") is not None:
            body["deviceIds"] = args["deviceIds"]
        return api.post("/api/cleanup/emulators/preview", body)
    if name == "cleanup_emulators_run":
        _check(args, ["previewId", "confirm", "timeoutSeconds"])
        _require_confirm(args)
        return _plain(_wait(api, api.post("/api/cleanup/emulators/run", {"previewId": args["previewId"]}), args))
    if name == "cleanup_vms_scan":
        _check(args, ["timeoutSeconds"])
        return _plain(_wait(api, api.post("/api/cleanup/vms/scan", {}), args))
    if name == "cleanup_packages_scan":
        _check(args, ["timeoutSeconds"])
        return _plain(_wait(api, api.post("/api/cleanup/packages/scan", {}), args))
    if name == "cleanup_leftovers_scan":
        _check(args, ["macos", "timeoutSeconds"])
        path = "/api/cleanup/leftovers/macos/scan" if args.get("macos") else "/api/cleanup/leftovers/scan"
        return _plain(_wait(api, api.post(path, {}), args))
    if name == "cleanup_relocation":
        _check(args, [])
        return api.get("/api/cleanup/relocation", {})
    if name == "cleanup_relocation_plan":
        _check(args, ["action", "entryId", "destination", "timeoutSeconds"])
        job = api.post("/api/cleanup/relocation/plan",
                       {"action": args["action"], "entryId": args["entryId"],
                        "destination": args["destination"]})
        return _plain(_wait(api, job, args))
    if name == "cleanup_relocation_run":
        _check(args, ["previewId", "confirm", "timeoutSeconds"])
        _require_confirm(args)
        return _plain(_wait(api, api.post("/api/cleanup/relocation/run", {"previewId": args["previewId"]}), args))
    if name == "cleanup_privileged":
        _check(args, [])
        return api.get("/api/cleanup/privileged", {})
    if name == "cleanup_privileged_preview":
        _check(args, ["actionId"])
        return api.post("/api/cleanup/privileged/preview", {"actionId": args["actionId"]})
    if name == "cleanup_privileged_run":
        _check(args, ["previewId", "confirm", "timeoutSeconds"])
        _require_confirm(args)
        return _plain(_wait(api, api.post("/api/cleanup/privileged/run", {"previewId": args["previewId"]}), args))
    if name == "cleanup_simulator_storage":
        _check(args, [])
        return api.get("/api/cleanup/simulator-storage", {})
    if name == "cleanup_simulator_storage_save":
        _check(args, ["config"])
        return api.post("/api/cleanup/simulator-storage", args["config"])
    if name == "cleanup_custom_entries_add":
        _check(args, ["name", "path"])
        return api.post("/api/cleanup/custom-entries", {"name": args["name"], "path": args["path"]})
    if name == "cleanup_custom_entries_remove":
        _check(args, ["entryId", "confirm"])
        _require_confirm(args)
        return api.post("/api/cleanup/custom-entries/remove", {"entryId": args["entryId"]})
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
