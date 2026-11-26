#!/usr/bin/env python3
"""os-lab MCP server: the macOS Lab's guarded surface for computer-use agents (MIR-12).

A stdio MCP server (JSON-RPC 2.0, one message per line, standard library only) that
exposes the app mirror's observe → act → verify loop as tools an LLM client — ZCode,
Claude, ChatGPT — can drive. The division of labour is deliberate:

- The model is the decision loop; the console stays the guarded actuator.
- Read-only tools (apps, app state, screenshots, windows, menu bar, control state)
  always work, like the mirror panel's read-only endpoints.
- Every input tool rides the panel's armed control mode, risk classes and audit log:
  the human arms from the dashboard (or the preview flow), the agent acts, every step
  lands in artifacts/macos-audit-<date>.jsonl. There is deliberately no arm tool.
- Submit-class actions (Enter/Return keys, pastes) need confirm:true even while armed,
  and the panic stop tool ends everything at once.

On a Windows host the server also offers the Windows Apps Lab's read-only tools (winapps_*). They
sit behind console/winapps_guard.py: an agent sees only apps on the allowlist
(win-lab/winapps-policy.json, empty means none), restricted windows are never captured, and every
call and refusal lands in the guard's audit log. There is no arm tool and no input tool.

The plugin_* tools check and set up os-lab as a Claude plugin (console/claude_plugin.py): changes
are previewed, need a one-use token and confirm:true, and removals run only from a terminal. The
codex_plugin_* tools do the same for the Codex plugin (console/codex_plugin.py); install previews
are terminal-only and MCP apply refuses agent writes. cursor_plugin_*, zcode_plugin_* and
grok_plugin_* cover the Cursor, ZCode and Grok Build packages the same way (console/host_plugin.py).

Run: python3 console/mcp_server.py   (or `make -C ios-lab mac-mcp`)
"""

from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oslab  # noqa: E402
import mcp_cleanup  # noqa: E402
import mcp_websec  # noqa: E402
import mcp_android  # noqa: E402
import mcp_ios  # noqa: E402
import mcp_linux  # noqa: E402
import mcp_web  # noqa: E402
import mcp_source  # noqa: E402
import mcp_firewall  # noqa: E402
import mcp_plugin  # noqa: E402
import mcp_ui  # noqa: E402
import mcp_prompts  # noqa: E402
import mcp_codex_plugin  # noqa: E402
import mcp_host_plugins  # noqa: E402
import winapps  # noqa: E402
import winapps_guard  # noqa: E402

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROTOCOL_VERSION = "2024-11-05"
MAX_TASK_STEPS = 25
# Sent on initialize. Clients cut it at 4096 characters.
INSTRUCTIONS = (
    "os-lab: guarded tools for the security labs on this computer. Use them only on systems and apps "
    "the user owns or is authorized to test.\n"
    "- Names are grouped by lab: macos_, winapps_, cleanup_, websec_, android_, ios_, linux_, web_, "
    "source_, firewall_. plugin_ manages the os-lab Claude plugin itself.\n"
    "- Read-only tools are safe to call. Observe, act, then observe again to verify.\n"
    "- Writes need the lab's own gate: a human arms macOS control from the dashboard (there is no arm "
    "tool), and tools with a confirm argument need the user's approval first. Never set confirm: true "
    "without it.\n"
    "- Web Sec scans outside the declared scope are refused.\n"
    "- For Claude plugin setup call plugin_doctor, then plugin_status. To change that installation "
    "call plugin_plan, show its commands, and only after approval plugin_apply.\n"
    "- For Codex plugin setup call codex_plugin_doctor and codex_plugin_status, preview with "
    "codex_plugin_plan, then run the shown installation in an interactive terminal. "
    "codex_plugin_apply refuses agent writes.\n"
    "- For Cursor plugin setup call cursor_plugin_doctor and cursor_plugin_status, preview with "
    "cursor_plugin_plan, then run python3 scripts/cursor-plugin.py install in a terminal; "
    "cursor_plugin_apply refuses agent writes.\n"
    "- For ZCode plugin setup call zcode_plugin_doctor and zcode_plugin_status, preview with "
    "zcode_plugin_plan, then run python3 scripts/zcode-plugin.py install in a terminal; "
    "zcode_plugin_apply refuses agent writes.\n"
    "- For Grok Build plugin setup call grok_plugin_doctor and grok_plugin_status, preview with "
    "grok_plugin_plan, then run python3 scripts/grok-plugin.py install in a terminal; "
    "grok_plugin_apply refuses agent writes."
)
# Tools whose JSON can pass the 50,000 characters after which Claude Code saves results to a file.
LARGE_RESULTS = ("macos_get_app_state", "macos_menubar", "websec_report", "cleanup_catalog")

TOOLS = [
    {
        "name": "macos_apps",
        "description": "List the visible app windows on this Mac: id, pid, app, title, rect and the display scale of each (read-only).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "_meta": mcp_ui.ui_meta(mcp_ui.MACOS_WIDGET["apps"]),
    },
    {
        "name": "macos_get_app_state",
        "description": "The accessibility tree of one window as element hotspots: role, label, value, enabled, focus, advertised AX actions and a stable path per element, plus a diff against the previous revision when one is passed (read-only). Set screenshot:true to include a PNG.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "windowId": {"type": "integer"},
                "revision": {"type": "string", "description": "the previous revision token for a diff"},
                "screenshot": {"type": "boolean", "description": "include a base64 PNG of the window"},
            },
            "required": ["windowId"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_screenshot",
        "description": "A PNG of one visible window (read-only; needs Screen Recording permission on the console).",
        "inputSchema": {
            "type": "object",
            "properties": {"windowId": {"type": "integer"}},
            "required": ["windowId"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_click",
        "description": "One click at a window point, or on an element path from the last tree read (armed control mode required; the human arms it from the dashboard).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "windowId": {"type": "integer"},
                "x": {"type": "integer", "description": "window-relative x (with y)"},
                "y": {"type": "integer", "description": "window-relative y (with x)"},
                "path": {"type": "string", "description": "element path from macos_get_app_state; clicks its centre"},
                "identity": {"type": "string", "description": "the element's identity hash from the tree read"},
            },
            "required": ["windowId"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_type",
        "description": "Type text into the focused element (armed; click the target first). Newlines are refused — Return is never sent by type; use macos_key with confirm for Enter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "windowId": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "text": {"type": "string", "maxLength": 200},
            },
            "required": ["windowId", "text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_key",
        "description": "One allowlisted key press (armed). Enter/Return are submit-class: they need confirm:true and always land in the audit log.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "windowId": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "key": {"type": "string", "enum": list(oslab._MACOS_INPUT_KEYS)},
                "confirm": {"type": "boolean", "description": "required for enter/return"},
            },
            "required": ["windowId", "key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_paste",
        "description": "Paste text through the clipboard (armed; replaces the clipboard). Submit-class: needs confirm:true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "windowId": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "text": {"type": "string", "maxLength": 2000},
                "confirm": {"type": "boolean"},
            },
            "required": ["windowId", "text", "confirm"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_scroll",
        "description": "Scroll the window vertically at a point, direction up|down and 1-10 pages (armed; horizontal is not supported).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "windowId": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "direction": {"type": "string", "enum": ["up", "down"]},
                "pages": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["windowId", "x", "y", "direction", "pages"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_set_value",
        "description": "Write a value straight into one settable accessibility element via the native AX helper (armed; fails closed when the tree moved).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "windowId": {"type": "integer"},
                "path": {"type": "string"},
                "identity": {"type": "string"},
                "value": {"type": "string", "maxLength": 2000},
            },
            "required": ["pid", "path", "identity", "value", "windowId"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_perform",
        "description": "Run one action the element advertises (e.g. AXPress, AXShowMenu) via the native AX helper (armed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "windowId": {"type": "integer"},
                "path": {"type": "string"},
                "identity": {"type": "string"},
                "action": {"type": "string"},
            },
            "required": ["pid", "path", "identity", "action", "windowId"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_windows",
        "description": "The AX window list of one app: rects, titles, subroles, sheets and alerts flagged (read-only).",
        "inputSchema": {
            "type": "object",
            "properties": {"pid": {"type": "integer"}},
            "required": ["pid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_menubar",
        "description": "The menu-bar tree of one app: menus and items with enabled state and advertised actions (read-only).",
        "inputSchema": {
            "type": "object",
            "properties": {"pid": {"type": "integer"}},
            "required": ["pid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_search",
        "description": "Find elements of one window by label, value or placeholder substring (max 50 hits), with the same paths and revision as macos_get_app_state, so an element can be acted on without reading the whole tree (read-only).",
        "inputSchema": {
            "type": "object",
            "properties": {"windowId": {"type": "integer"}, "query": {"type": "string"}},
            "required": ["windowId", "query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_displays",
        "description": "Active displays with origin, size and backing scale, so window coordinates can be reasoned about (read-only).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "macos_capabilities",
        "description": "What this console can observe and do right now: engine, input kinds, keys, safety limits and control state in one read-only answer.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "macos_permissions",
        "description": "Accessibility and Screen Recording state and the app each grant belongs to (read-only).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "macos_request_access",
        "description": "Ask macOS for Accessibility or Screen Recording: open the privacy pane and, when possible, fire the consent prompt (write counterpart to macos_permissions). The human still grants in System Settings; there is no silent grant.",
        "inputSchema": {
            "type": "object",
            "properties": {"pane": {"type": "string", "enum": ["accessibility", "screen-recording"]}},
            "required": ["pane"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "macos_focused",
        "description": "The focused accessibility element of one app (pid), with attributes (read-only observe; MIR-08).",
        "inputSchema": {
            "type": "object",
            "properties": {"pid": {"type": "integer"}},
            "required": ["pid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_audit",
        "description": "Recent macOS Lab audit rows for this process (agent calls, refusals, panic stop). Read-only; thumbnails omitted.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "macos_sessions",
        "description": "Open deep-inspect (Appium mac2) sessions and whether Appium answers. Read-only; opening a session stays on the armed dashboard.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "macos_control_state",
        "description": "Whether armed control mode is active, its owner and remaining seconds (read-only). Input tools refuse while it is off; there is no arm tool — the human arms from the dashboard.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "_meta": mcp_ui.ui_meta(mcp_ui.MACOS_WIDGET["control"]),
    },
    {
        "name": "macos_stop",
        "description": "The panic stop: disarm control, close every deep-inspect session, end every stream, record one audit row. Always safe to call.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "macos_task",
        "description": "Run a scripted sequence of the tools above with a step budget, one audit row per step, and return the transcript. A deterministic, auditable sequence — no model runs inside the lab.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "maxItems": MAX_TASK_STEPS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                        },
                        "required": ["tool"],
                        "additionalProperties": False,
                    },
                },
                "stopOnError": {"type": "boolean", "default": True},
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "macos_app_overview",
        "description": "macOS Lab MCP App: visible windows, control/arm state and permission hints (dashboard Overview UX). Observe only — there is no arm tool.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "_meta": mcp_ui.ui_meta(mcp_ui.MACOS_APP["overview"]),
        "annotations": mcp_ui.annotations(read_only=True, idempotent=True),
    },
]


TOOLS += mcp_cleanup.TOOLS  # CUX-10: the Cleanup Lab tools share this server and its error shape
TOOLS += mcp_websec.TOOLS  # the Web Sec Lab workbench, on the same console API and scope guard
TOOLS += mcp_android.TOOLS
TOOLS += mcp_ios.TOOLS
TOOLS += mcp_linux.TOOLS
TOOLS += mcp_web.TOOLS
TOOLS += mcp_source.TOOLS
TOOLS += mcp_firewall.TOOLS
TOOLS += mcp_plugin.TOOLS
TOOLS += mcp_codex_plugin.TOOLS
TOOLS += mcp_host_plugins.TOOLS
for _tool in TOOLS:
    if _tool["name"] in LARGE_RESULTS:
        _tool["_meta"] = {**_tool.get("_meta", {}), "anthropic/maxResultSizeChars": 200000}


def _window_point(window_id: int, args: dict) -> tuple[int, int, dict]:
    """The screen point for a click/type/scroll: element centre when a path is given,
    otherwise the given window-relative point, resolved through the mirror's bounds."""
    window = next((w for w in oslab.macos_windows()["windows"] if w["windowId"] == int(window_id)), None)
    if window is None:
        raise oslab.PlanError("That window is not on screen anymore; read macos_apps again",
                              code="APP_QUIT", retry="reobserve")
    if args.get("path"):
        elements = oslab.macos_window_elements(REPO_ROOT, window_id).get("elements", [])
        element = next((e for e in elements if e.get("path") == args["path"]), None)
        if element is None:
            raise oslab.PlanError(f"path {args['path']} is not in the current tree; read macos_get_app_state again",
                                  code="STALE_PATH", retry="reobserve")
        if args.get("identity") and element.get("identity") and args["identity"] != element["identity"]:
            raise oslab.PlanError("That element changed since the tree read; observe again",
                                  code="STALE_PATH", retry="reobserve")
        return window["pid"], window["x"] + element["x"] + element["w"] // 2, \
            window["y"] + element["y"] + element["h"] // 2, window
    try:
        return window["pid"], window["x"] + int(args.get("x", 0)), window["y"] + int(args.get("y", 0)), window
    except (TypeError, ValueError):
        raise oslab.PlanError("x and y must be integers", code="INVALID_ARGS") from None


WIN_TOOLS = [
    {
        "name": "winapps_apps",
        "description": "The on-screen Windows desktop windows this agent may see: only apps on the policy "
                       "allowlist, never restricted windows. `withheld` counts the rest (read-only).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "winapps_screenshot",
        "description": "A PNG of one allowlisted, unrestricted Windows window from winapps_apps (read-only).",
        "inputSchema": {
            "type": "object",
            "properties": {"windowId": {"type": "integer"}},
            "required": ["windowId"],
            "additionalProperties": False,
        },
    },
    {
        "name": "winapps_capabilities",
        "description": "Why you see what you see: allowlist and restriction counts, policy errors, and "
                       "that this lab supports no input (read-only).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "winapps_doctor",
        "description": "Desktop session, this console's elevation and one capture probe (read-only).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "winapps_audit",
        "description": "The newest audit rows for this lab: agent calls and refusals, without titles (read-only).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]




# Annotate core macos / winapps tools that were declared without annotations above.
_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_WR = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
_WR_OPEN = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
_STOP = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_RO_NAMES = {
    "macos_apps", "macos_get_app_state", "macos_screenshot", "macos_windows", "macos_menubar",
    "macos_search", "macos_displays", "macos_capabilities", "macos_control_state",
    "macos_focused", "macos_audit", "macos_sessions", "macos_permissions", "macos_app_overview",
    "winapps_apps", "winapps_screenshot", "winapps_capabilities", "winapps_doctor", "winapps_audit",
}
_WR_NAMES = {
    "macos_click", "macos_type", "macos_key", "macos_paste", "macos_scroll",
    "macos_set_value", "macos_perform", "macos_task",
}
for _tool in TOOLS + WIN_TOOLS:
    if "annotations" in _tool:
        continue
    name = _tool["name"]
    if name in _RO_NAMES:
        _tool["annotations"] = dict(_RO)
    elif name == "macos_stop":
        _tool["annotations"] = dict(_STOP)
    elif name in _WR_NAMES:
        _tool["annotations"] = dict(_WR)


def _text(value: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


def win_tool_call(name: str, args: dict) -> dict:
    """The Windows Apps Lab tools: every one is read-only and goes through the guard as the agent."""
    if sys.platform != "win32":
        raise winapps_guard.GuardError("The Windows Apps Lab needs a Windows host", "NOT_SUPPORTED")
    if not isinstance(args, dict):
        winapps_guard.audit(REPO_ROOT, "refused", audience="agent", code="INVALID_ARGS", tool=name)
        raise winapps_guard.GuardError("Tool arguments must be a JSON object", "INVALID_ARGS")
    if name == "winapps_apps":
        return _text(winapps_guard.list_windows(REPO_ROOT, "agent", tool=name))
    if name == "winapps_screenshot":
        png = winapps_guard.screenshot(REPO_ROOT, args.get("windowId"), "agent", tool=name)
        return {"content": [{"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}]}
    if name == "winapps_capabilities":
        summary = winapps_guard.policy_summary(REPO_ROOT)
        winapps_guard.audit(REPO_ROOT, "capabilities", audience="agent", tool=name)
        return _text({"allowedApps": summary["allowedApps"], "restrictedApps": summary["restrictedApps"],
                      "restrictedTitles": summary["restrictedTitles"], "policyError": summary["policyError"],
                      "exists": summary["exists"], "audience": "agent", "inputSupported": False,
                      # The arm state lives in the HTTP console's process; this one would only see its
                      # own (always disarmed) copy, so only the fixed rules are reported, never an owner.
                      "inputGate": {"armedIn": "console", "allowlistRequired": True,
                                    "confirmForSubmit": True, "agentCanArm": False}})
    if name == "winapps_doctor":
        return _text(winapps_guard.doctor(REPO_ROOT, "agent", tool=name))
    if name == "winapps_audit":
        winapps_guard.audit(REPO_ROOT, "audit", audience="agent", tool=name)
        return _text(winapps_guard.audit_rows(200, audience="agent"))
    raise winapps_guard.GuardError(f"Unknown tool {name}", "UNKNOWN_TOOL")


def tool_call(name: str, args: dict) -> dict:
    """One tool invocation against the same surface the panel drives. Returns MCP content."""
    if name.startswith("winapps_"):
        return win_tool_call(name, args)
    if name in mcp_codex_plugin.NAMES:
        return mcp_codex_plugin.call(name, args, REPO_ROOT)
    if name in mcp_host_plugins.NAMES:
        return mcp_host_plugins.call(name, args, REPO_ROOT)
    if name in mcp_cleanup.NAMES:
        return mcp_cleanup.call(name, args, REPO_ROOT)
    if name in mcp_websec.NAMES:
        return mcp_websec.call(name, args, REPO_ROOT)
    if name in mcp_android.NAMES:
        return mcp_android.call(name, args, REPO_ROOT)
    if name in mcp_ios.NAMES:
        return mcp_ios.call(name, args, REPO_ROOT)
    if name in mcp_linux.NAMES:
        return mcp_linux.call(name, args, REPO_ROOT)
    if name in mcp_web.NAMES:
        return mcp_web.call(name, args, REPO_ROOT)
    if name in mcp_source.NAMES:
        return mcp_source.call(name, args, REPO_ROOT)
    if name in mcp_firewall.NAMES:
        return mcp_firewall.call(name, args, REPO_ROOT)
    if name in mcp_plugin.NAMES:
        return mcp_plugin.call(name, args, REPO_ROOT)
    if name == "macos_app_overview":
        if args:
            raise oslab.PlanError("Unexpected argument(s): {0}".format(", ".join(sorted(args))),
                                  code="INVALID_ARGS")
        return mcp_ui.result({
            "apps": oslab.macos_windows(),
            "control": oslab.macos_control_state(),
            "permissions": oslab.macos_permissions(REPO_ROOT),
            "note": "Arm from the dashboard; there is no macos_arm MCP tool.",
        }, resource_uri=mcp_ui.MACOS_APP["overview"])
    if name == "macos_apps":
        return mcp_ui.result(oslab.macos_windows(), resource_uri=mcp_ui.MACOS_WIDGET["apps"])
    if name == "macos_get_app_state":
        state = oslab.macos_window_elements(REPO_ROOT, args.get("windowId"), args.get("revision"))
        content: list[dict] = [{"type": "text", "text": json.dumps(state)}]
        if args.get("screenshot") is True:
            png = oslab.macos_window_screenshot(args.get("windowId"))
            content.append({"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"})
        return {"content": content}
    if name == "macos_screenshot":
        png = oslab.macos_window_screenshot(args.get("windowId"))
        return {"content": [{"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}]}
    if name == "macos_click":
        pid, x, y, window = _window_point(args.get("windowId"), args)
        return {"content": [{"type": "text", "text": json.dumps(
            oslab.macos_control_click(REPO_ROOT, {"pid": pid, "x": x, "y": y, "owner": args.get("owner")}))}]}
    if name in ("macos_type", "macos_key", "macos_paste", "macos_scroll"):
        kind = {"macos_type": "type", "macos_key": "key", "macos_paste": "paste", "macos_scroll": "scroll"}[name]
        pid, x, y, window = _window_point(args.get("windowId"), args)
        payload = {"pid": pid, "x": x, "y": y, "kind": kind, "owner": args.get("owner"),
                   "confirm": args.get("confirm") is True}
        if kind in ("type", "paste"):
            payload["text"] = args.get("text")
        elif kind == "key":
            payload["key"] = args.get("key")
        else:
            payload["direction"], payload["pages"] = args.get("direction"), args.get("pages")
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_control_input(REPO_ROOT, payload))}]}
    if name == "macos_set_value":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_ax_set(REPO_ROOT, args))}]}
    if name == "macos_perform":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_ax_perform(REPO_ROOT, args))}]}
    if name == "macos_windows":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_ax_windows(REPO_ROOT, args))}]}
    if name == "macos_menubar":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_ax_menubar(REPO_ROOT, args))}]}
    if name == "macos_search":
        return {"content": [{"type": "text", "text": json.dumps(
            oslab.macos_search_elements(REPO_ROOT, args.get("windowId"), args.get("query")))}]}
    if name == "macos_displays":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_displays())}]}
    if name == "macos_capabilities":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_capabilities(REPO_ROOT))}]}
    if name == "macos_permissions":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_permissions(REPO_ROOT))}]}
    if name == "macos_request_access":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_request_access(REPO_ROOT, args))}]}
    if name == "macos_focused":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_ax_focused(REPO_ROOT, args))}]}
    if name == "macos_audit":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_audit_rows())}]}
    if name == "macos_sessions":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_session_state(REPO_ROOT))}]}
    if name == "macos_control_state":
        return mcp_ui.result(oslab.macos_control_state(), resource_uri=mcp_ui.MACOS_WIDGET["control"])
    if name == "macos_stop":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_panic_stop(REPO_ROOT))}]}
    if name == "macos_task":
        return {"content": [{"type": "text", "text": json.dumps(run_task(args))}]}
    raise oslab.PlanError(f"Unknown tool {name}", code="INVALID_ARGS")


def run_task(args: dict) -> dict:
    """The task runner (MIR-12): a scripted, auditable sequence with a step budget."""
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        raise oslab.PlanError("steps must be a non-empty list", code="INVALID_ARGS")
    if len(steps) > MAX_TASK_STEPS:
        raise oslab.PlanError(f"a task runs at most {MAX_TASK_STEPS} steps", code="INVALID_ARGS")
    stop_on_error = args.get("stopOnError", True) is not False
    transcript, failures = [], 0
    for number, step in enumerate(steps, start=1):
        tool = step.get("tool") if isinstance(step, dict) else None
        step_args = step.get("args") if isinstance(step, dict) else None
        row: dict = {"step": number, "tool": tool}
        try:
            if tool == "macos_task":
                raise oslab.PlanError("macos_task cannot nest", code="INVALID_ARGS")
            if str(tool) in mcp_cleanup.NAMES:
                raise oslab.PlanError("cleanup tools are not available inside macos_task", code="INVALID_ARGS")
            if str(tool) in mcp_websec.NAMES:
                raise oslab.PlanError("web sec tools are not available inside macos_task", code="INVALID_ARGS")
            for _mod, _label in (
                (mcp_android, "android"), (mcp_ios, "ios"), (mcp_linux, "linux"),
                (mcp_web, "web"), (mcp_source, "source"), (mcp_firewall, "firewall"),
                (mcp_plugin, "plugin"),
                (mcp_codex_plugin, "Codex plugin"),
                (mcp_host_plugins, "host plugin"),
            ):
                if str(tool) in _mod.NAMES:
                    raise oslab.PlanError(f"{_label} tools are not available inside macos_task", code="INVALID_ARGS")
            result = tool_call(str(tool), step_args if isinstance(step_args, dict) else {})
            row["ok"] = True
            row["result"] = result["content"][0]["text"][:2000]
        except oslab.PlanError as e:
            row.update({"ok": False, "error": str(e), "code": e.code, "retry": e.retry})
            failures += 1
        oslab._macos_audit(REPO_ROOT, "task-step", detail=row)
        transcript.append(row)
        if not row["ok"] and stop_on_error:
            break
    return {"steps": len(transcript), "failures": failures, "transcript": transcript}


def listed_tools() -> list[dict]:
    """The tools this host offers: the Windows Apps tools exist only on Windows."""
    return TOOLS + WIN_TOOLS if sys.platform == "win32" else TOOLS


def handle(message: dict) -> dict | None:
    """One JSON-RPC message; notifications return None."""
    method = message.get("method")
    message_id = message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": message_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
                "prompts": {"listChanged": False},
                "extensions": {"io.modelcontextprotocol/ui": {"mimeTypes": [mcp_ui.RESOURCE_MIME]}},
            },
            "serverInfo": {"name": "os-lab-windows" if sys.platform == "win32" else "os-lab-macos",
                           "version": "0.7.0"},
            "instructions": INSTRUCTIONS}}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": message_id, "result": {"tools": listed_tools()}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": message_id, "result": {"resources": mcp_ui.list_resources() + [
            {"uri": mcp_plugin.RESOURCE_URI, "name": "Claude plugin requirements",
             "description": "Every Claude plugin requirement os-lab checks, with sources.",
             "mimeType": "application/json"},
            {"uri": mcp_codex_plugin.RESOURCE_URI, "name": "Codex plugin requirements",
             "description": "Every Codex plugin requirement os-lab checks, with sources.",
             "mimeType": "application/json"},
        ] + [
            {"uri": uri, "name": "{0} plugin requirements".format(host.title()),
             "description": "Every {0} plugin requirement os-lab checks, with sources.".format(host),
             "mimeType": "application/json"}
            for host, uri in mcp_host_plugins.RESOURCES.items()
        ]}}
    if method == "resources/templates/list":
        return {"jsonrpc": "2.0", "id": message_id, "result": {"resourceTemplates": []}}
    if method == "resources/read":
        params = message.get("params") or {}
        uri = params.get("uri")
        if uri == mcp_plugin.RESOURCE_URI:
            return {"jsonrpc": "2.0", "id": message_id, "result": {"contents": [{
                "uri": uri, "mimeType": "application/json",
                "text": json.dumps(mcp_plugin.engine.requirements())}]}}
        try:
            if uri == mcp_codex_plugin.RESOURCE_URI:
                return {"jsonrpc": "2.0", "id": message_id, "result": {"contents": [{
                    "uri": uri, "mimeType": "application/json",
                    "text": json.dumps(mcp_codex_plugin.engine.requirements())}]}}
            for host, resource_uri in mcp_host_plugins.RESOURCES.items():
                if uri == resource_uri:
                    return {"jsonrpc": "2.0", "id": message_id, "result": {"contents": [{
                        "uri": uri, "mimeType": "application/json",
                        "text": json.dumps(mcp_host_plugins.engine.requirements(host))}]}}
            return {"jsonrpc": "2.0", "id": message_id, "result": mcp_ui.read_resource(str(uri))}
        except KeyError:
            return {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32002, "message": f"Resource not found: {uri}"}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": message_id, "result": {"prompts": mcp_prompts.list_prompts()}}
    if method == "prompts/get":
        params = message.get("params") or {}
        try:
            return {"jsonrpc": "2.0", "id": message_id, "result": mcp_prompts.get_prompt(str(params.get("name")), params.get("arguments") or {})}
        except KeyError:
            return {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32602, "message": f"Unknown prompt {params.get('name')}"}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            # MCP clients send the tool arguments as `arguments`; `args` is kept for older callers.
            raw_args = params["arguments"] if "arguments" in params else params.get("args")
            if str(params.get("name")).startswith("winapps_"):
                # The Windows tools validate their arguments themselves, so a falsey non-object such
                # as [] or 0 is refused instead of silently becoming {}; only a missing value means none.
                args = {} if raw_args is None else raw_args
            else:
                args = raw_args if isinstance(raw_args, dict) else {}
            result = tool_call(str(params.get("name")), args)
            return {"jsonrpc": "2.0", "id": message_id, "result": {**result, "isError": False}}
        except (oslab.PlanError, winapps_guard.GuardError, winapps.WinAppError) as e:
            payload: dict = {"error": str(e)}
            if getattr(e, "code", None):
                payload["code"] = e.code
            if getattr(e, "retry", None):
                payload["retry"] = e.retry
            return {"jsonrpc": "2.0", "id": message_id, "result": {
                "content": [{"type": "text", "text": json.dumps(payload)}], "isError": True}}
    if message_id is not None:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32601, "message": f"Unknown method {method}"}}
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
