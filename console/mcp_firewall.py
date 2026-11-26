"""Firewall Lab tools for the os-lab MCP server: browse, search, compare and recommend.

Content only. Nothing here touches a live firewall or the network. The same tools are served by
console/mcp_server.py and, on their own, by console/mcp_firewall_server.py.
"""
from __future__ import annotations

import json
import math
import os
import re

import firewall_catalog as catalog_engine
import mcp_common as common
import mcp_ui
import oslab

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")
MAX_DOC = 200_000
MAX_TEXT = 200
ROLES = ["headquarters", "branch", "campus", "datacenter", "remote"]
CATEGORIES = ["firewall", "waf"]


def _text(description):
    return {"type": "string", "maxLength": MAX_TEXT, "description": description}


def _number(description, **limits):
    return {"type": "number", "description": description, **limits}


def _flag(description):
    return {"type": "boolean", "description": description}


def _integer(description, minimum, maximum):
    return {"type": "integer", "minimum": minimum, "maximum": maximum, "description": description}


def _choice(values, description):
    return {"type": "string", "enum": values, "description": description}


def _names(description, maximum=20):
    return {"type": "array", "items": {"type": "string", "maxLength": MAX_TEXT}, "maxItems": maximum,
            "description": description}


_FILTERS = {
    "query": _text("Words that must all appear (product, vendor, company, branch, location, segment)."),
    "vendor": _text("Exact vendor name, case-insensitive, e.g. Fortinet. See facets in firewall_products."),
    "category": _choice(CATEGORIES, "Network firewall or web application firewall (WAF)."),
    "segment": _text("Substring of the segment, e.g. perimeter, dmz, students."),
    "role": _choice(ROLES, "Branch role."),
    "openSource": _flag("Only open-source based products (true) or only commercial ones (false)."),
    "minThroughputGbps": _number("Minimum quoted throughput in Gbps. Drops items with none.", minimum=0),
    "maxPriceUsd": _number("Maximum quoted price in USD. Drops items with none.", minimum=0),
}
_PAGE = {
    "limit": _integer("Rows to return (default 20).", 1, 100),
    "offset": _integer("Rows to skip.", 0, 100000),
}
SCHEMAS = {
    "firewall_devices": common.obj({
        **_FILTERS,
        "company": _text("Company slug."),
        "ha": _flag("Only high-availability deployments (true) or only single units (false)."),
        "includeAlternatives": _flag("Let query also match the alternatives compared for a device."),
        "sort": _choice(["company", "vendor", "product", "price", "throughput"], "Sort field."),
        "order": _choice(["asc", "desc"], "Sort order (default asc)."),
        **_PAGE,
    }),
    "firewall_device": common.obj({"deviceId": _text("deviceId from firewall_devices.")}, ["deviceId"]),
    "firewall_products": common.obj({
        **_FILTERS,
        "chosenOnly": _flag("Only products at least one design actually chose."),
        "sort": _choice(["popularity", "vendor", "price", "throughput"], "Sort field (default popularity)."),
        "order": _choice(["asc", "desc"], "Sort order (default asc; popularity is always most chosen first)."),
        **_PAGE,
    }),
    "firewall_compare": common.obj({
        "productKeys": {**_names("1 to 5 productKey values from firewall_products or firewall_recommend.", 5),
                        "minItems": 1},
    }, ["productKeys"]),
    "firewall_recommend": common.obj({
        "linkMbps": _number("The internet link or traffic to inspect, in Mbps.", exclusiveMinimum=0,
                            maximum=10_000_000),
        "headroom": _number("Multiplier over linkMbps for peaks and growth (default 1.5).",
                            minimum=1, maximum=10),
        "requiredThroughputGbps": _number("Required throughput in Gbps; replaces linkMbps x headroom.",
                                          exclusiveMinimum=0, maximum=100_000),
        "budgetUsd": _number("Most to spend in USD (the pair when haRequired).", minimum=0, maximum=1e12),
        "category": _choice(CATEGORIES, "firewall (default) or waf."),
        "role": _FILTERS["role"],
        "segment": _FILTERS["segment"],
        "haRequired": _flag("Price a high-availability pair."),
        "openSourceOnly": _flag("Only open-source based products."),
        "vendors": _names("Only these vendors."),
        "excludeVendors": _names("Never these vendors."),
        "includeUnknownSpecs": _flag("Keep products with no quoted throughput or price when a limit needs it."),
        "priority": _choice(list(catalog_engine.PRIORITIES), "What to favour (default balanced)."),
        "limit": _integer("Recommendations to return (default 5).", 1, 10),
    }),
}


def _tool(name, description, schema=None):
    return mcp_ui.tool(name, description, schema or common.obj(), read_only=True, idempotent=True)


TOOLS = common.annotate_ro([
    _tool("firewall_status",
          "Firewall Lab presence: catalog summary and company count. Content-only; no live firewall control. "
          "Read-only."),
    _tool("firewall_catalog",
          "The raw Firewall Lab catalog file (every deployed firewall; large). Prefer firewall_devices for "
          "searching. Read-only."),
    _tool("firewall_company",
          "One company pack by slug: README excerpt and listed files (no path traversal). Read-only.",
          common.obj({"slug": {"type": "string"}}, ["slug"])),
    _tool("firewall_guides",
          "Knowledge guide filenames under firewall-lab/knowledge/; pass name to read one. Read-only.",
          common.obj({"name": _text("A filename from the guide list.")})),
    _tool("firewall_devices",
          "Search the deployed firewalls (one per branch segment across all student company designs) by text, "
          "vendor, segment, role, throughput or price. Returns deviceId rows. Read-only.",
          SCHEMAS["firewall_devices"]),
    _tool("firewall_device",
          "Everything about one deployed firewall: quoted specs, why it was chosen, alternatives, rule set, "
          "branch bandwidth and segmentation, and other deployments of the same model. Read-only.",
          SCHEMAS["firewall_device"]),
    _tool("firewall_products",
          "Search distinct firewall products, including those only compared as alternatives, with throughput "
          "and price ranges across all quotes. Also returns facets (vendors, segments, roles). Read-only.",
          SCHEMAS["firewall_products"]),
    _tool("firewall_compare",
          "Compare 1-5 products side by side with the reasons designs chose or passed over each. Read-only.",
          SCHEMAS["firewall_compare"]),
    _tool("firewall_recommend",
          "Suggest the best firewalls for a context. Turn the user's need into linkMbps or "
          "requiredThroughputGbps, budgetUsd, role, segment, haRequired and priority (ask for what is "
          "missing and matters). Returns ranked products with score parts, reasons, warnings, evidence and "
          "similar deployments. Figures are student-quoted: pass the warnings on. Read-only.",
          SCHEMAS["firewall_recommend"]),
])
NAMES = {tool["name"] for tool in TOOLS}


def call(name, args, root):
    args = args if isinstance(args, dict) else {}
    return common.result(_dispatch(name, args, root))


def _lab(root):
    return os.path.join(root, "firewall-lab")


def _invalid(message):
    return oslab.PlanError(message, code="INVALID_ARGS")


def _validate(args, schema):
    """Check args against the tool's schema; clients are not required to do it. Returns args without nulls."""
    args = {key: value for key, value in args.items() if value is not None and value != ""}
    common.check(args, list(schema["properties"]), schema.get("required", ()))
    for key, value in args.items():
        rule = schema["properties"][key]
        kind = rule["type"]
        if kind == "string":
            if not isinstance(value, str) or len(value) > rule.get("maxLength", MAX_TEXT):
                raise _invalid("{0} must be a short string".format(key))
            if "enum" in rule and value not in rule["enum"]:
                raise _invalid("{0} must be one of: {1}".format(key, ", ".join(rule["enum"])))
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise _invalid("{0} must be true or false".format(key))
        elif kind in ("number", "integer"):
            wanted = int if kind == "integer" else (int, float)
            if isinstance(value, bool) or not isinstance(value, wanted) or not math.isfinite(value):
                raise _invalid("{0} must be a finite {1}".format(key, kind))
            if (("minimum" in rule and value < rule["minimum"])
                    or ("maximum" in rule and value > rule["maximum"])
                    or ("exclusiveMinimum" in rule and value <= rule["exclusiveMinimum"])):
                raise _invalid("{0} is out of range".format(key))
        elif kind == "array":
            if (not isinstance(value, list) or len(value) > rule["maxItems"]
                    or len(value) < rule.get("minItems", 0)
                    or not all(isinstance(item, str) and 0 < len(item) <= MAX_TEXT for item in value)):
                raise _invalid("{0} must be a list of {1} to {2} short strings".format(
                    key, rule.get("minItems", 0), rule["maxItems"]))
    return args


def _page(rows, args):
    offset, limit = args.get("offset", 0), args.get("limit", 20)
    shown = rows[offset:offset + limit]
    following = offset + len(shown)
    return shown, {"total": len(rows), "offset": offset, "returned": len(shown),
                   "nextOffset": following if following < len(rows) else None}


def _sorted(rows, value, descending):
    """Sort by value(row); rows without one come last in either direction."""
    known = sorted((r for r in rows if value(r) is not None), key=value, reverse=descending)
    return known + [r for r in rows if value(r) is None]


def _load(root):
    try:
        return catalog_engine.Catalog.load(root)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise oslab.PlanError("Firewall Lab companies could not be read: {0}".format(exc),
                              code="FIREWALL_DATA") from exc


def _query(name, args, root):
    data = _load(root)
    meta = {"dataSource": data.source, "dataVersion": data.version}
    if name == "firewall_devices":
        field = args.get("sort", "company")
        keys = {
            "company": lambda d: str(d["company"]).casefold(),
            "vendor": lambda d: d["vendor"].casefold(),
            "product": lambda d: d["model"].casefold(),
            "price": lambda d: d["priceUsd"],
            "throughput": lambda d: d["throughputGbps"],
        }
        rows = _sorted(data.search_devices(args), keys[field], args.get("order") == "desc")
        shown, page = _page(rows, args)
        return {**meta, **page, "devices": [data.device_row(d) for d in shown],
                "provenance": catalog_engine.PROVENANCE}
    if name == "firewall_device":
        device = data.device(args["deviceId"])
        if device is None:
            raise oslab.PlanError("Unknown deviceId; search with firewall_devices", code="FIREWALL_404",
                                  retry="reobserve")
        return {**meta, "device": data.device_detail(device), "provenance": catalog_engine.PROVENANCE}
    if name == "firewall_products":
        field = args.get("sort", "popularity")
        found = sorted(data.search_products(args), key=lambda p: p["key"])
        if field == "popularity":
            rows = sorted(found, key=lambda p: (-p["timesChosen"], -p["timesQuoted"]))
        else:
            keys = {
                "vendor": lambda p: (p["vendor"].casefold(), p["model"].casefold()),
                "price": lambda p: (catalog_engine.price_for(p, False) or {}).get("usd"),
                "throughput": lambda p: (p["throughputGbps"] or {}).get("median"),
            }
            rows = _sorted(found, keys[field], args.get("order") == "desc")
        shown, page = _page(rows, args)
        return {**meta, **page, "products": shown, "facets": data.facets(),
                "provenance": catalog_engine.PROVENANCE}
    if name == "firewall_compare":
        keys = list(dict.fromkeys(args["productKeys"]))
        unknown = [key for key in keys if key not in data.products]
        if unknown:
            raise oslab.PlanError("Unknown productKey(s): {0}; search with firewall_products".format(
                ", ".join(unknown)), code="FIREWALL_404", retry="reobserve")
        return {**meta, "products": [{**data.products[key], "evidence": data.evidence(key)} for key in keys],
                "provenance": catalog_engine.PROVENANCE}
    return {**meta, **data.recommend(args)}


def _guides(root):
    knowledge = os.path.join(_lab(root), "knowledge")
    if not os.path.isdir(knowledge):
        return []
    return sorted(name for name in os.listdir(knowledge)
                  if name.endswith((".md", ".txt", ".yml", ".yaml", ".json")) and not name.startswith("."))


def _dispatch(name, args, root):
    lab = _lab(root)
    if name == "firewall_status":
        common.check(args, [])
        catalog_path = os.path.join(lab, "catalog.json")
        if not os.path.isfile(catalog_path):
            return {"available": False, "reason": "firewall-lab/catalog.json is missing"}
        with open(catalog_path, encoding="utf-8") as handle:
            catalog = json.load(handle)
        summary = catalog.get("summary") or {}
        return {
            "available": True,
            "generatedBy": catalog.get("generatedBy"),
            "summary": summary,
            "companies": summary.get("companies"),
            "firewalls": len(catalog.get("firewalls") or []),
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
            raise _invalid("slug must be a safe company folder name")
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
        common.check(args, ["name"])
        guides = _guides(root)
        wanted = args.get("name")
        if wanted in (None, ""):
            return {"guides": guides}
        if wanted not in guides:
            raise oslab.PlanError("Unknown guide name", code="FIREWALL_404", retry="reobserve")
        with open(os.path.join(lab, "knowledge", wanted), encoding="utf-8") as handle:
            text = handle.read(MAX_DOC + 1)
        return {"name": wanted, "text": text[:MAX_DOC], "truncated": len(text) > MAX_DOC}
    if name in SCHEMAS:
        return _query(name, _validate(args, SCHEMAS[name]), root)
    raise _invalid("Unknown tool {0}".format(name))
