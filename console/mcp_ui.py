"""MCP Apps / widget helpers for the os-lab stdio MCP server.

Hosts that speak the MCP Apps extension (SEP-1865 / ChatGPT Apps) render a
``ui://`` HTML resource next to a tool result. This module keeps that surface
stdlib-only: annotations, resource discovery, structured tool payloads, and a
tiny HTML bridge so widgets stay useful when the host has no UI.
"""
from __future__ import annotations

import json
import os
from typing import Any

# MCP Apps resource profile (text/html+mcp) and the ChatGPT Apps alias.
RESOURCE_MIME = "text/html;profile=mcp-app"
RESOURCE_MIME_ALIASES = (RESOURCE_MIME, "text/html+mcp", "text/html")

WIDGET_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_widgets")
APP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_apps")
BRIDGE_PATH = os.path.join(WIDGET_ROOT, "_bridge.js")


def annotations(*, read_only: bool = False, destructive: bool = False,
                idempotent: bool = False, open_world: bool = False) -> dict:
    """Tool annotations hosts use to gate write / destructive calls."""
    return {
        "readOnlyHint": bool(read_only),
        "destructiveHint": bool(destructive),
        "idempotentHint": bool(idempotent),
        "openWorldHint": bool(open_world),
    }


def ui_meta(resource_uri: str) -> dict:
    """Link a tool to a predeclared UI resource (MCP Apps + ChatGPT alias)."""
    return {
        "ui": {"resourceUri": resource_uri},
        "ui/resourceUri": resource_uri,
        "openai/outputTemplate": resource_uri,
    }


def tool(name: str, description: str, input_schema: dict, *,
         read_only: bool = False, destructive: bool = False,
         idempotent: bool = False, open_world: bool = False,
         resource_uri: str | None = None) -> dict:
    """One tools/list entry with annotations and optional UI resource link."""
    entry = {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "annotations": annotations(
            read_only=read_only, destructive=destructive,
            idempotent=idempotent, open_world=open_world,
        ),
    }
    if resource_uri:
        entry["_meta"] = ui_meta(resource_uri)
    return entry


def result(value: Any, *, resource_uri: str | None = None) -> dict:
    """Text fallback for every client plus structuredContent for UI hosts."""
    payload = {
        "content": [{"type": "text", "text": json.dumps(value)}],
        "structuredContent": value if isinstance(value, dict) else {"value": value},
    }
    if resource_uri:
        payload["_meta"] = ui_meta(resource_uri)
    return payload


def _inject_bridge(html: str) -> str:
    """Replace the ``<!-- MCP_BRIDGE -->`` marker with the shared host bridge."""
    if "<!-- MCP_BRIDGE -->" not in html:
        return html
    try:
        with open(BRIDGE_PATH, encoding="utf-8") as handle:
            bridge = handle.read()
    except OSError:
        bridge = "/* mcp bridge missing */"
    return html.replace("<!-- MCP_BRIDGE -->", "<script>\n{0}\n</script>".format(bridge), 1)


def _walk_html(root: str, uri_prefix: str) -> list[dict]:
    resources = []
    if not os.path.isdir(root):
        return resources
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if not name.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
            uri = "{0}/{1}".format(uri_prefix.rstrip("/"), rel)
            title = name[:-5].replace("-", " ").replace("_", " ").title()
            resources.append({
                "uri": uri,
                "name": title,
                "description": "os-lab MCP UI: {0}".format(rel),
                "mimeType": RESOURCE_MIME,
            })
    return resources


_UI_SECTIONS = (
    ("cleanup", "widgets", WIDGET_ROOT),
    ("cleanup", "apps", APP_ROOT),
    ("websec", "widgets", WIDGET_ROOT),
    ("macos", "widgets", WIDGET_ROOT),
    ("android", "apps", APP_ROOT),
    ("ios", "apps", APP_ROOT),
    ("web", "apps", APP_ROOT),
    ("source", "apps", APP_ROOT),
)


def list_resources() -> list[dict]:
    """Every predeclared widget and app HTML resource."""
    resources = []
    for section, kind, base in _UI_SECTIONS:
        resources.extend(_walk_html(os.path.join(base, section),
                                    "ui://os-lab/{0}/{1}".format(section, kind)))
    return resources


def _path_for_uri(uri: str) -> str | None:
    prefixes = []
    for section, kind, base in _UI_SECTIONS:
        prefixes.append(("ui://os-lab/{0}/{1}/".format(section, kind), os.path.join(base, section)))
    for prefix, root in prefixes:
        if not uri.startswith(prefix):
            continue
        rel = uri[len(prefix):]
        if not rel or ".." in rel.split("/") or rel.startswith("/"):
            return None
        path = os.path.realpath(os.path.join(root, *rel.split("/")))
        root_real = os.path.realpath(root)
        if path == root_real or path.startswith(root_real + os.sep):
            return path if os.path.isfile(path) else None
    return None


def read_resource(uri: str) -> dict:
    """Return one UI resource contents block, or raise KeyError."""
    path = _path_for_uri(uri)
    if path is None:
        raise KeyError(uri)
    with open(path, encoding="utf-8") as handle:
        text = _inject_bridge(handle.read())
    return {
        "contents": [{
            "uri": uri,
            "mimeType": RESOURCE_MIME,
            "text": text,
            "_meta": {"ui": {"csp": {"resourceDomains": [], "connectDomains": [], "frameDomains": []}}},
        }]
    }


# Cleanup Lab resource URIs used by tools and apps.
CLEANUP_WIDGET = {
    "status": "ui://os-lab/cleanup/widgets/status.html",
    "volumes": "ui://os-lab/cleanup/widgets/volumes.html",
    "catalog": "ui://os-lab/cleanup/widgets/catalog.html",
    "monitor": "ui://os-lab/cleanup/widgets/monitor.html",
    "permissions": "ui://os-lab/cleanup/widgets/permissions.html",
    "bookmarks": "ui://os-lab/cleanup/widgets/bookmarks.html",
    "history": "ui://os-lab/cleanup/widgets/history.html",
    "widget": "ui://os-lab/cleanup/widgets/widget.html",
    "preferences": "ui://os-lab/cleanup/widgets/preferences.html",
    "suggest": "ui://os-lab/cleanup/widgets/suggest.html",
    "review": "ui://os-lab/cleanup/widgets/review.html",
    "job": "ui://os-lab/cleanup/widgets/job.html",
}
CLEANUP_APP = {
    "overview": "ui://os-lab/cleanup/apps/overview.html",
    "review": "ui://os-lab/cleanup/apps/review.html",
    "settings": "ui://os-lab/cleanup/apps/settings.html",
}
WEBSEC_WIDGET = {
    "status": "ui://os-lab/websec/widgets/status.html",
    "review": "ui://os-lab/websec/widgets/review.html",
    "report": "ui://os-lab/websec/widgets/report.html",
}
MACOS_WIDGET = {
    "apps": "ui://os-lab/macos/widgets/apps.html",
    "control": "ui://os-lab/macos/widgets/control.html",
}
LAB_APP = {
    "android": "ui://os-lab/android/apps/overview.html",
    "ios": "ui://os-lab/ios/apps/overview.html",
    "web": "ui://os-lab/web/apps/overview.html",
    "source": "ui://os-lab/source/apps/overview.html",
}
