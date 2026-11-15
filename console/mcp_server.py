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

Run: python3 console/mcp_server.py   (or `make -C ios-lab mac-mcp`)
"""

from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oslab  # noqa: E402

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROTOCOL_VERSION = "2024-11-05"
MAX_TASK_STEPS = 25

TOOLS = [
    {
        "name": "macos_apps",
        "description": "List the visible app windows on this Mac: id, pid, app, title, rect and the display scale of each (read-only).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
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
        "name": "macos_control_state",
        "description": "Whether armed control mode is active, its owner and remaining seconds (read-only). Input tools refuse while it is off; there is no arm tool — the human arms from the dashboard.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
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
]


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


def tool_call(name: str, args: dict) -> dict:
    """One tool invocation against the same surface the panel drives. Returns MCP content."""
    if name == "macos_apps":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_windows())}]}
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
    if name == "macos_control_state":
        return {"content": [{"type": "text", "text": json.dumps(oslab.macos_control_state())}]}
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


def handle(message: dict) -> dict | None:
    """One JSON-RPC message; notifications return None."""
    method = message.get("method")
    message_id = message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": message_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "os-lab-macos", "version": "0.1.0"}}}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": message_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = tool_call(str(params.get("name")), params.get("args") or {})
            return {"jsonrpc": "2.0", "id": message_id, "result": {**result, "isError": False}}
        except oslab.PlanError as e:
            payload: dict = {"error": str(e)}
            if e.code:
                payload["code"] = e.code
            if e.retry:
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
