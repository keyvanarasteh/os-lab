"""Shared helpers for lab MCP modules (status, schemas, result shape)."""
from __future__ import annotations

import mcp_ui
import oslab


def obj(properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def check(args, allowed, required=()):
    unknown = set(args) - set(allowed)
    if unknown:
        raise oslab.PlanError("Unexpected argument(s): {0}".format(", ".join(sorted(unknown))), code="INVALID_ARGS")
    missing = [key for key in required if args.get(key) in (None, "")]
    if missing:
        raise oslab.PlanError("Missing argument(s): {0}".format(", ".join(missing)), code="INVALID_ARGS")


def lab_status(root: str, lab: str) -> dict:
    host = oslab.host_info(root)
    host = {**host, "root": root}
    return oslab.lab_status(lab, host)


def result(value):
    return mcp_ui.result(value)


def annotate_ro(tools):
    for tool in tools:
        if "annotations" not in tool:
            tool["annotations"] = mcp_ui.annotations(read_only=True, idempotent=True)
    return tools
