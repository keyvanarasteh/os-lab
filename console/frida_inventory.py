#!/usr/bin/env python3
"""Frida device and process inventory (PENT-09): read-only, JSON out.

Does what the two Frida listing commands taught in class do, `frida-ls-devices`
and `frida-ps`, and merges the result into one document the console and agents
can read: which devices Frida sees, over which transport (local / USB / TCP),
and which processes on them could be attached to. It asks the `frida` Python
module when that is installed and runs the two commands otherwise (`--backend`).

It only lists. It never attaches, spawns, injects or kills, and it starts no
frida-server. A TCP target must be a loopback or private (RFC 1918) lab
address; anything else is refused before a single packet is sent.

    python3 console/frida_inventory.py                    # devices + local/USB processes
    python3 console/frida_inventory.py --usb --apps       # apps on the USB device
    python3 console/frida_inventory.py --host 127.0.0.1:27042
    python3 console/frida_inventory.py --no-processes -o inventory.json

Exit codes: 0 inventory complete, 1 a tool is missing or a listing failed,
2 usage error or out-of-scope target. Standard library only.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone

SCHEMA = "oslab.frida-inventory/1"
TOOLS = ("frida-ls-devices", "frida-ps")
DEFAULT_TIMEOUT = 20
DEFAULT_PORT = 27042

# Frida's device "Type" column -> the transport a student would name it by.
TRANSPORTS = {"local": "local", "usb": "USB", "remote": "TCP"}

_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_RULE = re.compile(r"-+")


class ScopeError(ValueError):
    """The requested target is outside the lab scope (or malformed)."""


class ToolError(RuntimeError):
    """A Frida CLI tool is missing, timed out or exited with an error."""


# --- Scope guard -------------------------------------------------------------

def parse_lab_host(value):
    """Validate `HOST[:PORT]` and return it normalised, or raise ScopeError.

    Only literal loopback, private and link-local addresses (and `localhost`)
    pass. Hostnames are refused rather than resolved, so a DNS answer can never
    widen the scope.
    """
    text = (value or "").strip()
    host, port = text, DEFAULT_PORT
    if text.startswith("["):  # [::1]:27042
        end = text.find("]")
        if end < 0:
            raise ScopeError(f"malformed host: {value!r}")
        host, rest = text[1:end], text[end + 1:]
        if rest:
            if not rest.startswith(":"):
                raise ScopeError(f"malformed host: {value!r}")
            port = rest[1:]
    elif text.count(":") == 1:
        host, port = text.split(":")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ScopeError(f"malformed port in {value!r}") from None
    if not 1 <= port <= 65535:
        raise ScopeError(f"port out of range in {value!r}")
    if host.lower() == "localhost":
        return f"127.0.0.1:{port}"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ScopeError(
            f"{host!r} is not an IP address; use the lab device's loopback or private IP"
        ) from None
    if not (address.is_loopback or address.is_private or address.is_link_local):
        raise ScopeError(f"{address} is not a loopback or private lab address; refusing")
    return f"[{address}]:{port}" if address.version == 6 else f"{address}:{port}"


def check_device_id(value):
    """Return a device id that is safe to pass as one argv entry, or raise ScopeError."""
    if not _DEVICE_ID.match(value or ""):
        raise ScopeError(f"invalid device id: {value!r}")
    return value


# --- Running the Frida tools ---------------------------------------------------

def find_tool(name):
    """Locate a Frida CLI tool on PATH or next to the running interpreter."""
    found = shutil.which(name)
    if found:
        return found
    here = os.path.dirname(sys.executable)
    for candidate in (name, name + ".exe"):
        path = os.path.join(here, candidate)
        if os.path.isfile(path):
            return path
    return None


def run_tool(argv, timeout=DEFAULT_TIMEOUT):
    """Run one listing command (no shell) and return its stdout, or raise ToolError."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    name = os.path.basename(argv[0])
    # Own process group/session: a pip launcher runs the real tool as a child,
    # and that child must die with it on timeout or it keeps our pipes open.
    windows = os.name == "nt"
    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if windows else 0,
            start_new_session=not windows,
        )
    except OSError:
        raise ToolError(f"{name} not found") from None
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        raise ToolError(f"{name} timed out after {timeout}s") from None
    out = stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace").strip() or out.strip()
        last = err.splitlines()[-1] if err else f"exit code {proc.returncode}"
        raise ToolError(last)
    return out


def _kill_tree(proc):
    """Stop a timed-out listing command together with any child it started."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10, check=False)
        else:
            os.killpg(proc.pid, 9)
    except (OSError, subprocess.SubprocessError):
        proc.kill()
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass


# --- Parsing -------------------------------------------------------------------

def parse_table(text):
    """Parse Frida's fixed-width tables into dicts keyed by lower-cased header.

    Columns are taken from the `----  ----` rule line, so names containing
    spaces and right-aligned numeric columns both parse correctly. The last
    column runs to the end of the line.
    """
    lines = [line.rstrip("\r\n") for line in text.splitlines()]
    for index in range(1, len(lines)):
        rule = lines[index]
        if rule.strip() and not rule.replace("-", "").strip():
            spans = [match.span() for match in _RULE.finditer(rule)]
            header = lines[index - 1]
            break
    else:
        return []
    bounds = [(start, spans[i + 1][0] if i + 1 < len(spans) else None) for i, (start, _) in enumerate(spans)]
    # A right-aligned column's values may start before its rule does.
    bounds[0] = (0, bounds[0][1])
    keys = [header[start:end].strip().lower() for start, end in bounds]
    rows = []
    for line in lines[index + 1:]:
        if not line.strip():
            continue
        rows.append({key: line[start:end].strip() for key, (start, end) in zip(keys, bounds) if key})
    return rows


def parse_devices(text):
    """Turn `frida-ls-devices` output into device records with a transport."""
    devices = []
    for row in parse_table(text):
        if not row.get("id"):
            continue
        kind = row.get("type", "").lower()
        devices.append({
            "id": row["id"],
            "type": kind,
            "transport": TRANSPORTS.get(kind, kind or "unknown"),
            "name": row.get("name", ""),
            "os": row.get("os") or None,
        })
    return devices


def parse_processes(text):
    """Turn `frida-ps` output (JSON from `-j`, or the text table) into process records."""
    stripped = text.strip()
    rows = None
    if stripped.startswith("["):
        try:
            rows = json.loads(stripped)
        except ValueError:
            rows = None
    if rows is None:
        rows = parse_table(text)
    processes = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            pid = int(str(row.get("pid")))
        except ValueError:
            pid = None  # an installed-but-not-running app shows "-" for its PID
        entry = {"pid": pid, "name": name}
        identifier = row.get("identifier")
        if identifier:
            entry["identifier"] = str(identifier)
        processes.append(entry)
    return processes


# --- Inventory -----------------------------------------------------------------

class CliBackend:
    """Lists through the `frida-ls-devices` and `frida-ps` commands."""

    name = "cli"

    def __init__(self, runner=run_tool, timeout=DEFAULT_TIMEOUT):
        self.runner = runner
        self.timeout = timeout

    def devices(self):
        tool = find_tool("frida-ls-devices")
        if not tool:
            raise ToolError("frida-ls-devices not found (pip install frida-tools)")
        return parse_devices(self.runner([tool], self.timeout))

    def processes(self, device_id, host=None, apps=False):
        tool = find_tool("frida-ps")
        if not tool:
            raise ToolError("frida-ps not found (pip install frida-tools)")
        argv = [tool, *(["-H", host] if host else ["-D", device_id]), "-j", "-e"]
        if apps:
            argv.append("-a")
        return parse_processes(self.runner(argv, self.timeout))


class ApiBackend:
    """Lists through the `frida` Python module, the calls the two commands make themselves.

    Preferred when the module is importable: `frida-ls-devices` draws a live
    terminal UI that needs a console and waits on every device, so it cannot be
    relied on from a script or a service.
    """

    name = "api"

    def __init__(self, frida, timeout=DEFAULT_TIMEOUT):
        self.frida = frida
        self.timeout = timeout

    def _call(self, what, func):
        """Run one Frida call on a worker so a silent device cannot block the inventory."""
        box = {}

        def work():
            try:
                box["value"] = func()
            except Exception as exc:  # frida raises its own error types
                box["error"] = exc

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        worker.join(self.timeout)
        if worker.is_alive():
            raise ToolError(f"{what} timed out after {self.timeout}s")
        if "error" in box:
            raise ToolError(f"{what} failed: {box['error']}")
        return box["value"]

    def _os(self, device):
        try:
            info = self._call("os query", device.query_system_parameters).get("os", {})
        except ToolError:
            return None
        return " ".join(str(part) for part in (info.get("name"), info.get("version")) if part) or None

    def devices(self):
        found = []
        for device in self._call("device listing", self.frida.enumerate_devices):
            kind = str(device.type).lower()
            found.append({
                "id": str(device.id),
                "type": kind,
                "transport": TRANSPORTS.get(kind, kind or "unknown"),
                "name": str(device.name or ""),
                # Only devices that are really there: a `remote` stub has no server to ask.
                "os": self._os(device) if kind in ("local", "usb") else None,
            })
        return found

    def processes(self, device_id, host=None, apps=False):
        def work():
            if host:
                device = self.frida.get_device_manager().add_remote_device(host)
            else:
                device = self.frida.get_device(device_id, timeout=self.timeout)
            if apps:
                return [{"pid": app.pid or None, "name": app.name, "identifier": app.identifier}
                        for app in device.enumerate_applications() if app.pid]
            return [{"pid": proc.pid, "name": proc.name} for proc in device.enumerate_processes()]

        return parse_processes(json.dumps(self._call("process listing", work)))


def load_frida():
    """Return the `frida` module when it is installed for this interpreter, else None."""
    try:
        import frida
    except ImportError:
        return None
    return frida


def pick_backend(choice="auto", runner=run_tool, timeout=DEFAULT_TIMEOUT):
    frida = load_frida() if choice in ("auto", "api") else None
    if frida is not None:
        return ApiBackend(frida, timeout)
    if choice == "api":
        raise ToolError("the frida Python module is not installed (pip install frida-tools)")
    return CliBackend(runner, timeout)


def build_inventory(usb=False, device=None, host=None, apps=False, processes=True, name_filter=None,
                    backend="auto", runner=run_tool, timeout=DEFAULT_TIMEOUT, now=None):
    """Collect the inventory document. Raises ScopeError for an out-of-scope target.

    With no target chosen, processes are listed for local and USB devices only:
    Frida's built-in `remote` entries point at a frida-server that may not
    exist, and a TCP target has to be named (and pass the scope guard) first.
    """
    if sum(1 for chosen in (usb, device, host) if chosen) > 1:
        raise ScopeError("choose only one of --usb, --device and --host")
    if device:
        device = check_device_id(device)
    if host:
        host = parse_lab_host(host)

    errors = []
    tools = {name: {"found": bool(find_tool(name)), "path": find_tool(name)} for name in TOOLS}
    frida = load_frida()
    tools["frida-python"] = {"found": frida is not None, "version": getattr(frida, "__version__", None)}
    try:
        lister = pick_backend(backend, runner, timeout)
    except ToolError as exc:
        lister = None
        errors.append({"stage": "backend", "message": str(exc)})
    # A named TCP target is the whole inventory, so the device listing is skipped.
    try:
        devices = lister.devices() if lister and not host else []
    except ToolError as exc:
        devices = []
        errors.append({"stage": "devices", "message": str(exc)})

    if host:
        devices = [{"id": f"tcp@{host}", "type": "remote", "transport": "TCP", "name": host, "os": None}]
    elif device:
        devices = [d for d in devices if d["id"] == device]
        if not devices and not errors:
            errors.append({"stage": "devices", "message": f"device {device!r} is not attached"})
    elif usb:
        devices = [d for d in devices if d["type"] == "usb"]
        if not devices and not errors:
            errors.append({"stage": "devices", "message": "no USB device attached"})

    needle = name_filter.lower() if name_filter else None
    for entry in devices:
        entry["processes"] = None
        entry["processCount"] = None
        entry["error"] = None
        wanted = processes and lister and (host or device or entry["type"] in ("local", "usb"))
        if not wanted:
            continue
        try:
            found = lister.processes(entry["id"], host, apps)
        except ToolError as exc:
            entry["error"] = str(exc)
            errors.append({"stage": "processes", "device": entry["id"], "message": str(exc)})
            continue
        if needle:
            found = [p for p in found if needle in p["name"].lower() or needle in p.get("identifier", "").lower()]
        entry["processes"] = found
        entry["processCount"] = len(found)

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": SCHEMA,
        "generatedAt": stamp,
        "readOnly": True,
        "backend": lister.name if lister else None,
        "query": {"usb": bool(usb), "device": device, "host": host, "apps": bool(apps),
                  "processes": bool(processes), "filter": name_filter},
        "tools": tools,
        "devices": devices,
        "summary": {
            "devices": len(devices),
            "usb": sum(1 for d in devices if d["transport"] == "USB"),
            "tcp": sum(1 for d in devices if d["transport"] == "TCP"),
            "processes": sum(d["processCount"] or 0 for d in devices),
        },
        "errors": errors,
    }


# --- CLI -----------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="frida_inventory.py",
        description="Read-only inventory of Frida devices and attachable processes, as JSON.",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("-U", "--usb", action="store_true", help="only the USB device(s)")
    target.add_argument("-D", "--device", metavar="ID", help="only the device with this Frida id")
    target.add_argument("-H", "--host", metavar="HOST[:PORT]",
                        help="a lab frida-server over TCP (loopback or private address only)")
    parser.add_argument("-a", "--apps", action="store_true", help="list applications instead of all processes")
    parser.add_argument("--no-processes", action="store_true", help="list devices only")
    parser.add_argument("-f", "--filter", metavar="TEXT", help="keep processes whose name or identifier contains TEXT")
    parser.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT, metavar="SEC",
                        help=f"per-listing timeout (default {DEFAULT_TIMEOUT})")
    parser.add_argument("--backend", choices=("auto", "api", "cli"), default="auto",
                        help="api = frida Python module, cli = frida-ls-devices/frida-ps; auto prefers api")
    parser.add_argument("-o", "--out", metavar="FILE", help="also write the JSON to FILE")
    parser.add_argument("--compact", action="store_true", help="single-line JSON")
    return parser


def main(argv=None, runner=run_tool):
    args = build_parser().parse_args(argv)
    if args.timeout < 1:
        print("error: --timeout must be at least 1", file=sys.stderr)
        return 2
    try:
        inventory = build_inventory(
            usb=args.usb, device=args.device, host=args.host, apps=args.apps,
            processes=not args.no_processes, name_filter=args.filter, backend=args.backend,
            runner=runner, timeout=args.timeout,
        )
    except ScopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(inventory, ensure_ascii=False, indent=None if args.compact else 2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 1 if inventory["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
