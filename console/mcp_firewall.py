"""Firewall Lab tools for the os-lab MCP server — content browse only, no network mutate."""
from __future__ import annotations

import json
import os
import re

import mcp_common as common
import mcp_ui
import oslab

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")
MAX_DOC = 200_000

TOOLS = common.annotate_ro([
    mcp_ui.tool("firewall_status",
                "Firewall Lab presence: catalog summary and company count. Content-only; no live firewall control. Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("firewall_catalog",
                "The Firewall Lab catalog (companies/firewalls list). Read-only.",
                common.obj(), read_only=True, idempotent=True),
    mcp_ui.tool("firewall_company",
                "One company pack by slug: README excerpt and listed files (no path traversal). Read-only.",
                common.obj({"slug": {"type": "string"}}, ["slug"]), read_only=True, idempotent=True),
    mcp_ui.tool("firewall_guides",
                "Knowledge guide filenames under firewall-lab/knowledge/. Read-only.",
                common.obj(), read_only=True, idempotent=True),
])
NAMES = {tool["name"] for tool in TOOLS}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    return common.result(_dispatch(name, args, root))


def _lab(root):
    return os.path.join(root, "firewall-lab")


def _dispatch(name, args, root):
    lab = _lab(root)
    if name == "firewall_status":
        common.check(args, [])
        catalog_path = os.path.join(lab, "catalog.json")
        if not os.path.isfile(catalog_path):
            return {"available": False, "reason": "firewall-lab/catalog.json is missing"}
        with open(catalog_path, encoding="utf-8") as handle:
            catalog = json.load(handle)
        firewalls = catalog.get("firewalls") or []
        return {
            "available": True,
            "generatedBy": catalog.get("generatedBy"),
            "summary": catalog.get("summary"),
            "companies": len(firewalls),
            "contributors": len(catalog.get("contributors") or []),
        }
    if name == "firewall_catalog":
        common.check(args, [])
        with open(os.path.join(lab, "catalog.json"), encoding="utf-8") as handle:
            return json.load(handle)
    if name == "firewall_company":
        common.check(args, ["slug"], ["slug"])
        slug = args["slug"]
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise oslab.PlanError("slug must be a safe company folder name", code="INVALID_ARGS")
        folder = os.path.realpath(os.path.join(lab, "companies", slug))
        base = os.path.realpath(os.path.join(lab, "companies"))
        if not folder.startswith(base + os.sep) or not os.path.isdir(folder):
            raise oslab.PlanError("Unknown company slug", code="FIREWALL_404", retry="reobserve")
        files = sorted(name for name in os.listdir(folder) if not name.startswith("."))
        readme = None
        for candidate in ("README.md", "readme.md"):
            path = os.path.join(folder, candidate)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    text = handle.read(MAX_DOC + 1)
                readme = {"name": candidate, "text": text[:MAX_DOC], "truncated": len(text) > MAX_DOC}
                break
        return {"slug": slug, "files": files, "readme": readme}
    if name == "firewall_guides":
        common.check(args, [])
        knowledge = os.path.join(lab, "knowledge")
        if not os.path.isdir(knowledge):
            return {"guides": []}
        guides = sorted(name for name in os.listdir(knowledge)
                        if name.endswith((".md", ".txt", ".yml", ".yaml", ".json")) and not name.startswith("."))
        return {"guides": guides}
    raise oslab.PlanError("Unknown tool {0}".format(name), code="INVALID_ARGS")
