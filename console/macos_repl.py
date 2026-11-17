#!/usr/bin/env python3
"""Interactive REPL for the macOS Lab: one long-lived console session over the native AX
helper path — the same oslab functions, preview → confirm stamps, armed gates and audit log
the dashboard and the MCP server use.

This replaces the Appium mac2 REPL (ios-lab/mac/macos-repl.mjs): element reads go through
the native AX helper (ios-lab/mac/ax-helper.swift, or the fake helper via OSLAB_AX_HELPER),
there is no Appium session to start, and the arm state persists for the whole session.

QcU's own CLI builds a new engine per command, so its `arm` is lost between commands; this
REPL deliberately holds one session instead: one oslab module state, one preview stamp
signer, one numbered element cache — arm, pending previews and the signer's consumed set all
live as long as the process does.

Every state-changing command goes through the same gates as the API:
- while disarmed, it prints a preview and a one-use expiring stamp; `confirm <stamp>` runs
  exactly that preview (the same plan the dashboard's Run button would start);
- while armed, it runs immediately through the armed functions — single owner, unlock and
  allowlist checks included — and submit-class actions (Enter/Return keys, pastes) still
  ask for an explicit confirmation;
- nothing here bypasses a gate: no direct CGEvent posting, no unvalidated coordinates.

Run: python3 console/macos_repl.py [--app APP] [--artifacts DIR]
     (or `make -C ios-lab mac-app-repl APP=…`)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oslab  # noqa: E402

PROMPT = "macos> "

HELP = """commands:
  apps                     list visible app windows (id, pid, app, title, rect)
  tree [windowId]          element tree of the target window, numbered
  find <text>              search elements by label/value/placeholder (numbered hits)
  click <n> [double|right] click element n (its rect centre)
  type <n> <text>          type at element n (click <n> first to focus the field)
  key <k>                  press an allowlisted key in the target app (e.g. key enter)
  scroll <up|down> [pages] scroll the target window (1-10 pages, default 3)
  paste <text>             paste through the clipboard (replaces it; submit-class)
  set-value <n> <value>    write a value into settable element n
  perform <n> <action>     run one advertised AX action (e.g. AXPress)
  shot [name]              save a PNG of the target window into the artifacts folder
  displays                 list displays (id, origin, size, scale)
  arm | disarm             armed control mode (single owner; it disarms itself after idle)
  confirm <stamp>          confirm the pending preview (one use; it expires)
  stop                     panic stop: disarm, close sessions, end streams
  status                   control state and engine capabilities
  clear                    forget the numbered elements
  help                     show this list
  quit                     leave the REPL

State-changing commands run immediately while armed; otherwise they print a preview and a
stamp that `confirm` consumes. Submit-class actions (enter/return, paste) always ask."""


def _refused(error: oslab.PlanError) -> str:
    text = f"refused {error.code or 'ERROR'}: {error}"
    return text + (f" ({error.retry})" if error.retry else "")


class MacRepl:
    """One REPL session over one oslab state: arm owner, element numbers and the pending
    preview survive between commands; the preview signer is shared for the session too."""

    def __init__(self, root: str, app: str | None = None, artifacts: str | None = None,
                 owner: str = "repl", input=None, output=None) -> None:
        self.root = root
        self.app = app
        self.owner = owner
        self.artifacts = artifacts or os.path.join(root, "ios-lab", "artifacts")
        self.input = input or sys.stdin
        self.output = output or sys.stdout
        self.signer = oslab.PlanSigner()
        self.numbered: list[dict] = []      # tree/find hits: {"window": row, "element": node}
        self.pending: dict | None = None    # {"request": …, "plan": …, "stamp": …}
        self._host = None                   # resolved once; oslab keeps the session state
        self._execute = _execute_plan       # replaced in tests

    # ── output ─────────────────────────────────────────────────────────────

    def print(self, text: str = "") -> None:
        self.output.write(text + "\n")
        try:
            self.output.flush()
        except (OSError, ValueError):
            pass

    def _fail(self, error: oslab.PlanError) -> None:
        self.print(_refused(error))

    # ── scope ──────────────────────────────────────────────────────────────

    def _scope(self) -> list[dict]:
        windows = oslab.macos_windows().get("windows", [])
        if not self.app:
            return windows
        wanted = self.app.lower()
        exact = [w for w in windows if (w.get("app") or "").lower() == wanted]
        return exact or [w for w in windows
                         if wanted in (w.get("app") or "").lower() or wanted in (w.get("title") or "").lower()]

    def _target(self, window_id: int | None = None) -> dict | None:
        windows = self._scope()
        if window_id is not None:
            return next((w for w in windows if w["windowId"] == window_id), None)
        return windows[0] if windows else None

    def _point(self, window: dict) -> tuple[int, int]:
        return window["x"] + window["width"] // 2, window["y"] + window["height"] // 2

    def _pick(self, raw: str) -> dict | None:
        try:
            index = int(raw)
        except (TypeError, ValueError):
            self.print(f"no element {raw!r} — run tree or find first (1..{len(self.numbered)})")
            return None
        if not 1 <= index <= len(self.numbered):
            self.print(f"no element {index} — run tree or find first (1..{len(self.numbered)})")
            return None
        return self.numbered[index - 1]

    def _host_info(self) -> dict:
        if self._host is None:
            self._host = oslab.host_info(self.root)
        return self._host

    # ── state-changing commands ────────────────────────────────────────────

    def _act(self, request: dict) -> None:
        """One state-changing command: armed means immediate (through the armed gates);
        disarmed prints the preview and a one-use stamp for `confirm`."""
        if oslab.macos_control_state()["armed"]:
            submit = request.get("inputKind") == "paste" or request.get("inputKey") in ("enter", "return")
            confirm = False
            if submit and not self._ask("this action can submit or overwrite — type y to confirm"):
                self.print("cancelled")
                return
            if submit:
                confirm = True
            self._run_armed(request, confirm)
            return
        try:
            plan = oslab.plan(self.root, request, self._host_info())
        except oslab.PlanError as error:
            self._fail(error)
            return
        stamp = self.signer.sign(request)
        self.pending = {"request": request, "plan": plan, "stamp": stamp}
        oslab.macos_audit_preview(self.root, request, "preview", stamp)
        self.print(f"preview (not executed): {plan.get('display')}")
        for effect in plan.get("effects") or []:
            self.print(f"  effect: {effect}")
        self.print(f"  stamp: {stamp} (expires in {self.signer.ttl}s)")
        self.print('  -> run "confirm <stamp>", or "arm" to execute directly')

    def _ask(self, question: str) -> bool:
        self.print(question + " [y/N]")
        line = self.input.readline()
        return line.strip().lower() in ("y", "yes")

    def _run_armed(self, request: dict, confirm: bool) -> None:
        """The armed halves, exactly the functions the API's armed routes call."""
        action = request["action"]
        try:
            if action == "macos-click":
                result = oslab.macos_control_click(self.root, {
                    "pid": request["clickPid"], "x": request["clickX"], "y": request["clickY"],
                    "owner": self.owner})
            elif action in ("macos-input", "macos-scroll"):
                payload = {"pid": request["clickPid"], "x": request["clickX"], "y": request["clickY"],
                           "kind": request["inputKind"], "owner": self.owner, "confirm": confirm}
                if request.get("inputText") is not None:
                    payload["text"] = request["inputText"]
                if request.get("inputKey") is not None:
                    payload["key"] = request["inputKey"]
                if request.get("scrollDirection") is not None:
                    payload["direction"], payload["pages"] = request["scrollDirection"], request["scrollPages"]
                result = oslab.macos_control_input(self.root, payload)
            elif action == "macos-set-value":
                result = oslab.macos_ax_set(self.root, {
                    "pid": request["elementPid"], "path": request["elementPath"],
                    "identity": request["elementIdentity"], "windowId": request["elementWindowId"],
                    "value": request["elementValue"], "owner": self.owner, "confirm": confirm})
            else:  # macos-perform
                result = oslab.macos_ax_perform(self.root, {
                    "pid": request["elementPid"], "path": request["elementPath"],
                    "identity": request["elementIdentity"], "windowId": request["elementWindowId"],
                    "action": request["axAction"], "owner": self.owner, "confirm": confirm})
        except oslab.PlanError as error:
            self._fail(error)
            return
        self.print("executed: " + json.dumps(result, default=str)[:600])

    def _confirm(self, stamp: str) -> None:
        if not self.pending:
            self.print("nothing to confirm — run an action first (unarmed actions print a stamp)")
            return
        if stamp != self.pending["stamp"]:
            self.print("that is not the pending preview's stamp; run the action again")
            return
        request, plan, known = self.pending["request"], self.pending["plan"], self.pending["stamp"]
        if not self.signer.verify(request, known):
            self.pending = None
            self.print("the preview is no longer valid (expired, already used or a different "
                       "request); preview the action again")
            return
        self.pending = None
        oslab.macos_audit_preview(self.root, request, "preview-confirmed", known)
        if not plan.get("runnable"):
            self.print("this action must be run in a terminal: " + (plan.get("manualCommand") or ""))
            return
        self.print(f"running: {plan.get('display')}")
        code, output = self._execute(plan)
        text = (output or "").strip()
        if text:
            self.print("\n".join(text.splitlines()[-12:]))
        self.print(f"exit {code}")

    # ── read-only commands ─────────────────────────────────────────────────

    def _tree(self, window_id: str) -> None:
        try:
            target = self._target(int(window_id) if window_id else None)
        except ValueError:
            self.print("windowId must be an integer")
            return
        if target is None:
            self.print("no window in scope" + (f" for {self.app}" if self.app else ""))
            return
        try:
            state = oslab.macos_window_elements(self.root, target["windowId"])
        except oslab.PlanError as error:
            self._fail(error)
            return
        elements = state.get("elements") or []
        self.numbered = [{"window": target, "element": element} for element in elements]
        self.print(f"tree of {target['app']} window {target['windowId']} "
                   f"(revision {state.get('revision')}, {len(elements)} elements):")
        for index, element in enumerate(elements, start=1):
            label = element.get("label") or element.get("title") or ""
            value = element.get("value")
            actions = element.get("actions") or []
            rect = f" ({element['x']},{element['y']} {element['w']}x{element['h']})"
            self.print(f"{index:3} {element.get('role')}"
                       + (f' "{label}"' if label else "")
                       + (f' = "{value}"' if value else "")
                       + rect + (f" [{','.join(actions)}]" if actions else ""))

    def _find(self, query: str) -> None:
        if not query:
            self.print("usage: find <text>")
            return
        target = self._target()
        if target is None:
            self.print("no window in scope" + (f" for {self.app}" if self.app else ""))
            return
        try:
            result = oslab.macos_search_elements(self.root, target["windowId"], query)
        except oslab.PlanError as error:
            self._fail(error)
            return
        hits = result.get("hits") or []
        self.numbered = [{"window": target, "element": hit} for hit in hits]
        if not hits:
            self.print(f'no hits for "{query}"')
            return
        self.print(f'{len(hits)} hit(s) for "{query}":')
        for index, hit in enumerate(hits, start=1):
            self.print(f"{index:3} {hit.get('role')}"
                       + (f' "{hit.get("label")}"' if hit.get("label") else "")
                       + (f' = "{hit.get("value")}"' if hit.get("value") else ""))

    def _shot(self, name: str) -> None:
        target = self._target()
        if target is None:
            self.print("no window in scope")
            return
        try:
            png = oslab.macos_window_screenshot(target["windowId"])
        except oslab.PlanError as error:
            self._fail(error)
            return
        os.makedirs(self.artifacts, exist_ok=True)
        file = os.path.join(self.artifacts, f"macos-repl-{name or int(time.time())}.png")
        with open(file, "wb") as f:
            f.write(png)
        self.print(file)

    # ── dispatch ───────────────────────────────────────────────────────────

    def handle(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        command, _, rest = stripped.partition(" ")
        command, rest = command.lower(), rest.strip()
        try:
            if command in ("quit", "exit", "q"):
                raise SystemExit(0)
            if command == "help":
                self.print(HELP)
            elif command == "apps":
                data = oslab.macos_windows()
                if not data.get("available", True):
                    self.print(data.get("reason") or "The app mirror is not available here.")
                    return
                for window in data.get("windows", []):
                    self.print(f"{window['windowId']:>8} {window['pid']:>7}  {window['app']}"
                               f" — {(window.get('title') or '')[:60]} "
                               f"({window['x']},{window['y']} {window['width']}x{window['height']})")
            elif command == "tree":
                self._tree(rest)
            elif command == "find":
                self._find(rest)
            elif command == "displays":
                data = oslab.macos_displays()
                if not data.get("available"):
                    self.print(data.get("reason") or "No display information.")
                    return
                for display in data.get("displays", []):
                    self.print(f"display {display.get('id')}: origin ({display['x']},{display['y']}) "
                               f"{display['width']}x{display['height']} @ {display.get('scale')}x")
            elif command == "shot" or command == "screenshot":
                self._shot(rest)
            elif command == "status":
                self.print(json.dumps({"control": oslab.macos_control_state(),
                                       "capabilities": oslab.macos_capabilities(self.root)},
                                      indent=2, default=str)[:2000])
            elif command == "clear":
                self.numbered = []
                self.print("element numbers cleared")
            elif command in ("arm", "disarm"):
                state = oslab.macos_control_arm(self.root, command == "arm", self.owner)
                self.print(f"armed by {state['owner']} (expires in {state['expiresInSec']}s)"
                           if state["armed"] else "disarmed")
            elif command == "confirm":
                self._confirm(rest)
            elif command == "stop":
                self.print(json.dumps(oslab.macos_panic_stop(self.root)))
            elif command == "click":
                self._click(rest)
            elif command == "type":
                self._typed(rest)
            elif command == "key":
                self._key(rest)
            elif command == "scroll":
                self._scroll(rest)
            elif command == "paste":
                self._paste(rest)
            elif command in ("set-value", "set"):
                self._set_value(rest)
            elif command == "perform":
                self._perform(rest)
            else:
                self.print(f'unknown command "{command}" — type "help"')
        except SystemExit:
            raise
        except oslab.PlanError as error:
            self._fail(error)
        except (OSError, ValueError) as error:
            self.print(f"error: {error}")

    # ── state-changing command parsers ─────────────────────────────────────

    def _window_or_none(self) -> dict | None:
        target = self._target()
        if target is None:
            self.print("no window in scope" + (f" for {self.app}" if self.app else ""))
        return target

    def _click(self, rest: str) -> None:
        parts = rest.split()
        if not parts:
            self.print("usage: click <n> [double|right]")
            return
        kind = parts[1].lower() if len(parts) > 1 else "single"
        if kind not in ("single", "double", "right"):
            self.print("usage: click <n> [double|right]")
            return
        picked = self._pick(parts[0])
        if picked is None:
            return
        window, element = picked["window"], picked["element"]
        x = window["x"] + element["x"] + element["w"] // 2
        y = window["y"] + element["y"] + element["h"] // 2
        request = {"lab": "macos", "clickPid": window["pid"], "clickX": x, "clickY": y}
        if kind == "single":
            self._act({**request, "action": "macos-click"})
        else:
            self._act({**request, "action": "macos-input", "inputKind": kind})

    def _typed(self, rest: str) -> None:
        number, _, text = rest.partition(" ")
        if not number or not text:
            self.print("usage: type <n> <text>")
            return
        picked = self._pick(number)
        if picked is None:
            return
        window, element = picked["window"], picked["element"]
        self._act({"lab": "macos", "action": "macos-input",
                   "clickPid": window["pid"], "clickX": window["x"] + element["x"] + element["w"] // 2,
                   "clickY": window["y"] + element["y"] + element["h"] // 2,
                   "inputKind": "type", "inputText": text})

    def _key(self, rest: str) -> None:
        key = rest.strip().lower()
        if not key:
            self.print("usage: key <k>  (e.g. key enter)")
            return
        window = self._window_or_none()
        if window is None:
            return
        x, y = self._point(window)
        self._act({"lab": "macos", "action": "macos-input", "clickPid": window["pid"],
                   "clickX": x, "clickY": y, "inputKind": "key", "inputKey": key})

    def _scroll(self, rest: str) -> None:
        parts = rest.split()
        if not parts or parts[0].lower() not in ("up", "down"):
            self.print("usage: scroll <up|down> [pages]")
            return
        pages = parts[1] if len(parts) > 1 else "3"
        window = self._window_or_none()
        if window is None:
            return
        x, y = self._point(window)
        self._act({"lab": "macos", "action": "macos-scroll", "clickPid": window["pid"],
                   "clickX": x, "clickY": y, "scrollDirection": parts[0].lower(), "scrollPages": pages})

    def _paste(self, rest: str) -> None:
        if not rest:
            self.print("usage: paste <text>")
            return
        window = self._window_or_none()
        if window is None:
            return
        x, y = self._point(window)
        self._act({"lab": "macos", "action": "macos-input", "clickPid": window["pid"],
                   "clickX": x, "clickY": y, "inputKind": "paste", "inputText": rest})

    def _set_value(self, rest: str) -> None:
        number, _, value = rest.partition(" ")
        if not number or not value:
            self.print("usage: set-value <n> <value>")
            return
        picked = self._pick(number)
        if picked is None:
            return
        window, element = picked["window"], picked["element"]
        self._act({"lab": "macos", "action": "macos-set-value",
                   "elementPid": window["pid"], "elementWindowId": window["windowId"],
                   "elementPath": element.get("path", ""), "elementIdentity": element.get("identity", ""),
                   "elementValue": value})

    def _perform(self, rest: str) -> None:
        number, _, action = rest.partition(" ")
        if not number or not action:
            self.print("usage: perform <n> <action>  (e.g. perform 2 AXPress)")
            return
        picked = self._pick(number)
        if picked is None:
            return
        window, element = picked["window"], picked["element"]
        self._act({"lab": "macos", "action": "macos-perform",
                   "elementPid": window["pid"], "elementWindowId": window["windowId"],
                   "elementPath": element.get("path", ""), "elementIdentity": element.get("identity", ""),
                   "axAction": action})

    # ── loop ───────────────────────────────────────────────────────────────

    def run(self) -> None:
        capabilities = oslab.macos_capabilities(self.root)
        if not capabilities.get("available"):
            self.print("The macOS Lab needs a Mac; the app mirror has nothing to drive here.")
        self.print('macOS Lab REPL — the native AX helper path, one session. Type "help" for commands.')
        if self.app:
            self.print(f"scope: {self.app}")
        while True:
            self.print(PROMPT)
            line = self.input.readline()
            if not line:
                break
            try:
                self.handle(line)
            except SystemExit:
                self.print("bye")
                return


def _execute_plan(plan: dict) -> tuple[int, str]:
    """Run one confirmed plan exactly as the job worker would: program + args, bounded."""
    try:
        completed = subprocess.run([plan["program"]] + list(plan["args"]), capture_output=True,
                                   text=True, timeout=plan.get("timeoutSec") or 120,
                                   env=dict(os.environ, NO_COLOR="1", TERM="dumb"))
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")
    except (OSError, subprocess.SubprocessError) as error:
        return 1, str(error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive macOS Lab REPL (native AX path).")
    parser.add_argument("--app", default=os.environ.get("MACOS_APP") or None,
                        help="only drive windows of this app (name or bundle id)")
    parser.add_argument("--artifacts", default=None, help="folder for screenshots")
    parser.add_argument("--root", default=oslab.REPO_ROOT if hasattr(oslab, "REPO_ROOT") else None,
                        help="repository root (defaults to this checkout)")
    options = parser.parse_args(argv)
    root = options.root or os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    try:
        MacRepl(root, app=options.app, artifacts=options.artifacts).run()
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
