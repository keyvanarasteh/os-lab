#!/usr/bin/env python3
"""A stand-in for ios-lab/mac/build/ax-helper: canned JSON for the same commands, so the act and
verify paths (and CI on Linux) run without a Mac. Select it with OSLAB_AX_HELPER=<this file>.
Never used unless that variable is set."""
import json
import sys

RECT_WINDOW = {"x": 100, "y": 100, "w": 800, "h": 600}


def node(path, role, label, x, y, w, h, **extra):
    base = {"path": path, "identity": f"{abs(hash(path + role)) % 0xFFFFFFFF:08x}", "role": role, "label": label,
            "rect": {"x": 100 + x, "y": 100 + y, "w": w, "h": h}, "enabled": True, "focused": False,
            "actions": [], "children": []}
    base.update(extra)
    return base


TREE = node("", "AXWindow", "Demo", 0, 0, 800, 600, children=[
    node("0", "AXTextField", "Name", 20, 20, 300, 30, value="Ada", placeholder="Your name", focused=True),
    node("1", "AXButton", "Save", 20, 70, 100, 30, actions=["AXPress"]),
    node("2", "AXButton", "Cancel", 140, 70, 100, 30, actions=["AXPress"]),
    node("3", "AXStaticText", "Status: idle", 20, 120, 200, 20),
])


def arg(name):
    args = sys.argv
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def emit(payload):
    print(json.dumps(payload))
    sys.exit(0)


command = sys.argv[1] if len(sys.argv) > 1 else ""
if command == "trusted":
    emit({"trusted": True})
if command == "request-access":
    emit({"trusted": True})
if command == "windows":
    emit({"pid": 1, "windows": [{"index": 0, "title": "Demo", "rect": RECT_WINDOW}]})
if command == "tree":
    emit({"pid": 1, "window": 1, "tree": TREE})
if command == "focused":
    emit({"pid": 1, "focused": TREE["children"][0]})
if command == "read":
    emit({"pid": 1, "path": arg("--path"), "value": "Ada"})
if command in ("set", "perform"):
    emit({"pid": 1, "ok": True, "path": arg("--path")})
if command == "menubar":
    emit({"pid": 1, "menubar": {"role": "AXMenuBar", "children": []}})
print(json.dumps({"error": f"unknown command {command}", "code": "INVALID_ARGS"}))
sys.exit(1)
