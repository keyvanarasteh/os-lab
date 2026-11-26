"""Shared Zcode / Grok / Cursor plugin package checks, status and config installs.

File-based MCP config install (no host CLI required). Standard library only.
Terminal-only apply; MCP apply refuses agent writes — same gate as Codex.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

LABS = ("android", "cleanup", "firewall", "ios", "linux", "macos", "source", "web", "websec", "winapps")
OWN_SKILLS = ("setup", "doctor")
ACTIONS = ("install", "update", "uninstall")
PLAN_SECONDS = 600
SOURCE_REL = os.path.join("console", "mcp_skills")
_PLANS: dict = {}
_LOCK = threading.Lock()

# Per-host layout. Install writes a project MCP config pointing at the package launcher.
HOSTS = {
    "cursor": {
        "title": "Cursor",
        "prefix": "cursor",
        "plugin_rel": os.path.join("plugins", "cursor", "os-lab"),
        "manifest": os.path.join(".cursor-plugin", "plugin.json"),
        "mcp_file": "mcp.json",
        "config_rel": os.path.join(".cursor", "mcp.json"),
        "config_key": "mcpServers",
        "market_rel": None,
        "cli_names": ("cursor",),
        "catalog": "cursor_requirements.json",
        "published": ("https://raw.githubusercontent.com/keyvanarasteh/os-lab/master/"
                      "plugins/cursor/os-lab/plugin.json"),
        "scaffold_rel": os.path.join("plugins", "mcp", "cursor", "mcp.json"),
    },
    "zcode": {
        "title": "ZCode",
        "prefix": "zcode",
        "plugin_rel": os.path.join("plugins", "zcode", "os-lab"),
        "manifest": "plugin.json",
        "mcp_file": ".mcp.json",
        "config_rel": os.path.join(".zcode", "mcp.json"),
        "config_key": "servers",
        "market_rel": None,
        "cli_names": ("zcode",),
        "catalog": "zcode_requirements.json",
        "published": ("https://raw.githubusercontent.com/keyvanarasteh/os-lab/master/"
                      "plugins/zcode/os-lab/plugin.json"),
        "scaffold_rel": os.path.join("plugins", "mcp", "zcode", "mcp.json"),
    },
    "grok": {
        "title": "Grok Build",
        "prefix": "grok",
        "plugin_rel": os.path.join("plugins", "grok", "os-lab"),
        "manifest": "plugin.json",
        "mcp_file": ".mcp.json",
        "config_rel": os.path.join(".grok", "mcp.json"),
        "config_key": "mcpServers",
        "market_rel": os.path.join(".grok-plugin", "marketplace.json"),
        "cli_names": ("grok",),
        "catalog": "grok_requirements.json",
        "published": ("https://raw.githubusercontent.com/keyvanarasteh/os-lab/master/"
                      "plugins/grok/os-lab/plugin.json"),
        "scaffold_rel": os.path.join("plugins", "mcp", "grok", "mcp.json"),
    },
}


class PluginError(Exception):
    def __init__(self, message, code="INVALID_ARGS"):
        super().__init__(message)
        self.code = code


def _json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _spec(host: str) -> dict:
    if host not in HOSTS:
        raise PluginError("Unknown host: " + host)
    return HOSTS[host]


def plugin_dir(root, host):
    return os.path.join(root, _spec(host)["plugin_rel"])


def config_path(root, host):
    return os.path.join(root, _spec(host)["config_rel"])


def catalog_path(host):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _spec(host)["catalog"])


def generated_skills(root):
    result = {}
    for lab in LABS:
        source = os.path.join(root, SOURCE_REL, lab, "SKILL.md")
        with open(source, encoding="utf-8") as handle:
            body = handle.read()
        if not body.startswith("---\n") or not re.search(r"(?m)^name: .+$", body):
            raise PluginError("Invalid source skill: " + source, "SKILL_INVALID")
        result[lab] = re.sub(r"(?m)^name: .+$", "name: os-lab-" + lab, body, count=1)
    return result


def skill_drift(root, host):
    target = os.path.join(plugin_dir(root, host), "skills")
    expected = generated_skills(root)
    problems = []
    for lab, body in expected.items():
        path = os.path.join(target, lab, "SKILL.md")
        try:
            with open(path, encoding="utf-8") as handle:
                actual = handle.read()
        except OSError:
            actual = None
        if actual != body:
            problems.append(("missing" if actual is None else "out of date") +
                            " skills/{0}/SKILL.md".format(lab))
    if os.path.isdir(target):
        for name in os.listdir(target):
            if name not in expected and name not in OWN_SKILLS:
                problems.append("unexpected skills/" + name)
    return sorted(problems)


def build_skills(root, host):
    changed = skill_drift(root, host)
    for lab, body in generated_skills(root).items():
        folder = os.path.join(plugin_dir(root, host), "skills", lab)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    return changed


def catalog(host) -> dict:
    return _json(catalog_path(host))


def checkout_version(root: str, host: str) -> str:
    return str(_json(os.path.join(plugin_dir(root, host), "plugin.json"))["version"])


def requirements(host, area=None, usage=None):
    data = catalog(host)
    sources = data["sources"]
    rows = data["requirements"]
    areas = sorted({row["area"] for row in rows})
    if area and area not in areas:
        raise PluginError("Unknown area: " + area)
    if usage and usage not in ("used", "n/a"):
        raise PluginError("usage must be used or n/a")
    selected = []
    for row in rows:
        if area and row["area"] != area:
            continue
        if usage and row["usage"] != usage:
            continue
        selected.append({
            "id": row["id"], "area": row["area"], "usage": row["usage"], "severity": row["severity"],
            "rule": row["rule"], "check": row["check"], "source": sources[row["source"]],
            "reviewedOn": data["reviewedOn"],
        })
    return {"areas": areas, "count": len(selected), "requirements": selected}


def _path_inside(path, root):
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
    except ValueError:
        return False


def _readme_words(package: str) -> int:
    try:
        with open(os.path.join(package, "README.md"), encoding="utf-8") as handle:
            return len(re.findall(r"\w+", handle.read()))
    except OSError:
        return 0


def _which_cli(host):
    for name in _spec(host)["cli_names"]:
        found = shutil.which(name)
        if found:
            return found
    return None


def _server_entry(root, host):
    """Project MCP entry that starts this checkout's host package launcher."""
    launcher = os.path.join(plugin_dir(root, host), "launcher.py")
    base = {
        "command": "python3",
        "args": [launcher],
        "env": {"OSLAB_ROOT": os.path.realpath(root)},
    }
    if _spec(host)["config_key"] == "servers":
        return {"transport": "stdio", **base}
    return {"type": "stdio", **base}


def _read_config(root, host):
    path = config_path(root, host)
    if not os.path.isfile(path):
        return {}, path
    try:
        data = _json(path)
    except (OSError, ValueError):
        return {}, path
    if not isinstance(data, dict):
        return {}, path
    return data, path


def _servers(data, host):
    key = _spec(host)["config_key"]
    block = data.get(key)
    return block if isinstance(block, dict) else {}


def _entry_points_here(entry, root, host) -> bool:
    if not isinstance(entry, dict):
        return False
    args = entry.get("args") or []
    launcher = os.path.realpath(os.path.join(plugin_dir(root, host), "launcher.py"))
    for arg in args:
        try:
            if os.path.realpath(str(arg)) == launcher:
                return True
        except OSError:
            continue
    env = entry.get("env") or {}
    if isinstance(env, dict) and os.path.realpath(str(env.get("OSLAB_ROOT") or "")) == os.path.realpath(root):
        command = entry.get("command")
        if command and "mcp_server" in " ".join(str(a) for a in args):
            return True
    return False


def _run_check(host: str, name: str, root: str) -> tuple[str, str]:
    package = plugin_dir(root, host)
    spec = _spec(host)
    if name == "n/a":
        return "n/a", "Not applicable for " + spec["title"]
    if name == "manual":
        return "manual", "Requires an isolated " + spec["title"] + " desktop installation"
    if name == "manifest_identity":
        try:
            path = os.path.join(package, "plugin.json")
            if spec["manifest"] != "plugin.json":
                path = os.path.join(package, spec["manifest"])
                if not os.path.isfile(path):
                    path = os.path.join(package, "plugin.json")
            manifest = _json(path)
            if manifest.get("name") != "os-lab" or not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
                return "fail", "Plugin name or version is invalid"
            return "pass", "ok"
        except (OSError, ValueError, TypeError) as exc:
            return "fail", str(exc)
    if name == "manifest_metadata":
        try:
            manifest = _json(os.path.join(package, "plugin.json"))
            author = manifest.get("author") or {}
            missing = [key for key in ("description", "homepage", "repository", "license") if not manifest.get(key)]
            if not author.get("name"):
                missing.append("author.name")
            return ("fail", "Missing " + ", ".join(missing)) if missing else ("pass", "ok")
        except (OSError, ValueError, TypeError) as exc:
            return "fail", str(exc)
    if name == "cursor_manifest_dir":
        path = os.path.join(package, ".cursor-plugin", "plugin.json")
        return ("pass", "ok") if os.path.isfile(path) else ("fail", ".cursor-plugin/plugin.json is missing")
    if name == "market_name":
        rel = spec["market_rel"]
        if not rel:
            return "n/a", "No marketplace for " + host
        try:
            market = _json(os.path.join(root, rel))
            return ("pass", "ok") if market.get("name") == "os-lab-local" else ("fail", "Marketplace name is not os-lab-local")
        except (OSError, ValueError, TypeError) as exc:
            return "fail", str(exc)
    if name == "market_entry":
        rel = spec["market_rel"]
        if not rel:
            return "n/a", "No marketplace for " + host
        try:
            market = _json(os.path.join(root, rel))
            entries = market.get("plugins", [])
            valid = market.get("name") == "os-lab-local" and len(entries) == 1
            entry = entries[0] if valid else {}
            source = entry.get("source", {})
            wanted = "./" + spec["plugin_rel"].replace(os.sep, "/")
            valid = valid and entry.get("name") == "os-lab" and source.get("source") == "local"
            valid = valid and source.get("path") == wanted
            valid = valid and entry.get("policy", {}).get("installation") == "AVAILABLE"
            return ("pass", "ok") if valid else ("fail", "Marketplace source or policy is invalid")
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            return "fail", str(exc)
    if name == "mcp_stdio":
        try:
            mcp = _json(os.path.join(package, spec["mcp_file"]))
            if "mcpServers" not in mcp and os.path.isfile(os.path.join(package, "mcp.json")):
                mcp = _json(os.path.join(package, "mcp.json"))
            server = mcp.get("mcpServers", {}).get("os-lab", {})
            ok = (server.get("type") == "stdio" and server.get("command") == "python3"
                  and server.get("args") == ["${PLUGIN_ROOT}/launcher.py"])
            return ("pass", "ok") if ok else ("fail", "Local stdio launcher declaration is invalid")
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            return "fail", str(exc)
    if name == "mcp_annotations":
        import mcp_host_plugins
        tools = mcp_host_plugins.tools_for(host)
        missing = [tool["name"] for tool in tools
                   if "readOnlyHint" not in (tool.get("annotations") or {})]
        return ("fail", "Missing readOnlyHint: " + ", ".join(missing)) if missing else ("pass", "ok")
    if name == "mcp_instructions":
        import mcp_server
        text = mcp_server.INSTRUCTIONS
        prefix = spec["prefix"] + "_plugin_"
        ok = prefix + "doctor" in text and prefix + "plan" in text
        return ("pass", "ok") if ok else ("fail", "Initialize instructions omit " + host + " plugin tools")
    if name == "skills_frontmatter":
        for skill in LABS + OWN_SKILLS:
            path = os.path.join(package, "skills", skill, "SKILL.md")
            try:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                header = text.split("---", 2)[1] if text.startswith("---\n") else ""
                if not re.search(r"(?m)^name: .+$", header) or not re.search(r"(?m)^description: .+$", header):
                    return "fail", "Invalid frontmatter in " + skill
            except OSError:
                return "fail", "Missing skill " + skill
        return "pass", "ok"
    if name == "skills_length":
        long = []
        for skill in LABS + OWN_SKILLS:
            path = os.path.join(package, "skills", skill, "SKILL.md")
            try:
                with open(path, encoding="utf-8") as handle:
                    if sum(1 for _ in handle) > 500:
                        long.append(skill)
            except OSError:
                return "fail", "Missing skill " + skill
        return ("fail", "Over 500 lines: " + ", ".join(long)) if long else ("pass", "ok")
    if name == "skills_generated":
        drift = skill_drift(root, host)
        return ("fail", "; ".join(drift)) if drift else ("pass", "ok")
    if name == "cache_contained":
        for base, dirs, files in os.walk(package, followlinks=False):
            for entry in dirs + files:
                path = os.path.join(base, entry)
                if os.path.islink(path) and not _path_inside(path, package):
                    return "fail", "Symlink escapes package: " + os.path.relpath(path, package)
        return "pass", "ok"
    if name == "cli_available":
        binary = _which_cli(host)
        return ("pass", binary) if binary else ("skipped", spec["title"] + " CLI is not on PATH")
    if name == "readme":
        if not os.path.isfile(os.path.join(package, "LICENSE")):
            return "fail", "Packaged license is missing"
        words = _readme_words(package)
        return ("pass", "{0} words".format(words)) if words >= 40 else ("fail", "README is under 40 words")
    if name == "scaffold_present":
        path = os.path.join(root, spec["scaffold_rel"])
        return ("pass", "ok") if os.path.isfile(path) else ("fail", "MCP scaffold missing: " + spec["scaffold_rel"])
    return "fail", "Unknown check: " + name


def check(root, host, area=None):
    rows = []
    for rule in requirements(host, area)["requirements"]:
        result, detail = _run_check(host, rule["check"], root)
        if rule["usage"] == "n/a" and result != "n/a":
            result, detail = "n/a", rule["rule"]
        entry = {"id": rule["id"], "area": rule["area"], "result": result, "detail": detail,
                 "source": rule["source"]}
        if result == "fail":
            entry["fix"] = rule["rule"]
        rows.append(entry)
    return {"ok": all(row["result"] != "fail" for row in rows), "results": rows,
            "summary": {state: sum(row["result"] == state for row in rows)
                        for state in ("pass", "fail", "manual", "n/a", "skipped")}}


def _version_key(version) -> tuple:
    try:
        return tuple(int(part) for part in str(version).split("."))
    except (TypeError, ValueError):
        return (0,)


def status(root, host):
    """Read-only install state from the project MCP config; never returns secrets."""
    spec = _spec(host)
    data, path = _read_config(root, host)
    servers = _servers(data, host)
    entry = servers.get("os-lab")
    installed = _entry_points_here(entry, root, host) if entry else False
    duplicates = []
    for name, row in servers.items():
        if name == "os-lab":
            continue
        if name in ("os-lab-macos", "os-lab-windows") or (
                isinstance(row, dict) and "mcp_server" in " ".join(str(a) for a in (row.get("args") or []))):
            duplicates.append({"name": name, "scope": "project"})
    found = {
        "host": host,
        "title": spec["title"],
        "checkout": os.path.realpath(root),
        "cli": _which_cli(host),
        "installed": installed,
        "configPath": path if os.path.isfile(path) else None,
        "duplicates": duplicates,
        "checkoutVersion": None,
        "thisCheckout": installed,
        "manualConfig": None,
    }
    try:
        found["checkoutVersion"] = checkout_version(root, host)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if duplicates:
        found["manualConfig"] = (
            "Remove duplicate MCP entries named "
            + ", ".join(sorted({row["name"] for row in duplicates}))
            + " so only the os-lab plugin connection remains.")
    return found


def doctor(root, host):
    from importlib.util import spec_from_file_location, module_from_spec
    path = os.path.join(plugin_dir(root, host), "launcher.py")
    spec = spec_from_file_location("os_lab_{0}_launcher".format(host), path)
    checks = [
        {"name": "python", "ok": sys.version_info >= (3, 8), "detail": sys.version.split()[0],
         "fix": None if sys.version_info >= (3, 8) else "Install Python 3.8 or newer"},
        {"name": "cli", "ok": True, "detail": _which_cli(host) or "optional (file-based install)",
         "fix": None},
    ]
    if not os.path.isfile(path) or not spec or not spec.loader:
        checks.append({
            "name": "package", "ok": False, "detail": path,
            "fix": "Rebuild or reinstall the app so plugins/{0}/os-lab/launcher.py ships with the runtime"
            .format(host),
        })
        return {"ready": False, "platform": sys.platform, "host": host, "checks": checks}
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout, source, problem = module.find_checkout(here=path)
    package_ok = check(root, host)["ok"]
    checks.extend([
        {"name": "checkout", "ok": bool(checkout), "detail": checkout or problem, "source": source,
         "fix": None if checkout else "Set OSLAB_ROOT to this repository"},
        {"name": "package", "ok": package_ok, "detail": "package checks",
         "fix": None if package_ok else "Run python3 scripts/{0}-plugin.py check".format(host)},
    ])
    return {"ready": all(row["ok"] for row in checks), "platform": sys.platform, "host": host, "checks": checks}


def published_version(host: str, timeout: float = 5) -> tuple[str | None, str | None]:
    request = urllib.request.Request(_spec(host)["published"], headers={"User-Agent": "os-lab"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            version = str(json.loads(reply.read(200_000).decode("utf-8"))["version"])
        if not re.match(r"^\d+(\.\d+)+$", version):
            raise ValueError("unexpected version")
        return version, None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, "could not read the published version: {0}".format(type(exc).__name__)


def updates(root, host, online: bool = False, timeout: float = 5) -> dict:
    wanted = checkout_version(root, host)
    result: dict = {"host": host, "online": online, "checkoutVersion": wanted, "updatesAvailable": []}
    if online:
        latest, problem = published_version(host, timeout)
        newer = bool(latest) and _version_key(wanted) < _version_key(latest)
        result["published"] = {"version": latest, "updateAvailable": newer if latest else None}
        if problem:
            result["published"]["note"] = problem
        if newer:
            result["updatesAvailable"].append("checkout")
            result["published"]["next"] = "Update the checkout (git pull), then reinstall the plugin."
    state = status(root, host)
    result["install"] = {
        "cli": state.get("cli"),
        "installed": state.get("installed"),
        "updateAvailable": False,
    }
    return result


def _install_steps(root, host, action):
    if action not in ACTIONS:
        raise PluginError("action must be one of: {0}".format(", ".join(ACTIONS)), "UNSUPPORTED")
    state = status(root, host)
    path = config_path(root, host)
    entry = _server_entry(root, host)
    steps = []
    if action == "install":
        if state["installed"]:
            raise PluginError("The plugin is already installed; use update", "ALREADY_INSTALLED")
        steps.append({"op": "write_mcp", "path": path, "entry": entry, "mode": "add"})
    elif action == "update":
        if not state["installed"] and not os.path.isfile(path):
            raise PluginError("The plugin is not installed", "NOT_INSTALLED")
        steps.append({"op": "write_mcp", "path": path, "entry": entry, "mode": "set"})
    else:
        if not state["installed"] and "os-lab" not in _servers(_read_config(root, host)[0], host):
            raise PluginError("The plugin is not installed", "NOT_INSTALLED")
        steps.append({"op": "write_mcp", "path": path, "entry": None, "mode": "remove"})
    return state, steps


def audit(root, host, event, detail):
    path = os.path.join(root, "artifacts",
                        "{0}-plugin-audit-{1}.jsonl".format(host, time.strftime("%Y-%m-%d")))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                     "host": host, "event": event, **detail}) + "\n")
    except OSError:
        pass


def plan(root, host, action):
    state, steps = _install_steps(root, host, action)
    token = secrets.token_urlsafe(24)
    with _LOCK:
        _PLANS[token] = {"root": os.path.realpath(root), "host": host, "action": action,
                         "state": state, "steps": steps, "expires": time.time() + PLAN_SECONDS}
    warnings = []
    if state.get("manualConfig"):
        warnings.append(state["manualConfig"])
    audit(root, host, "planned", {"action": action, "steps": len(steps)})
    commands = []
    for step in steps:
        if step["op"] == "write_mcp":
            commands.append("python3 scripts/{0}-plugin.py {1}  # writes {2}".format(
                host, action, step["path"]))
    return {"host": host, "action": action, "token": token, "expiresInSeconds": PLAN_SECONDS,
            "commands": commands, "manual": [], "warnings": warnings, "terminalOnly": True,
            "terminalCommand": "python3 scripts/{0}-plugin.py {1}".format(host, action),
            "note": "Run python3 scripts/{0}-plugin.py {1} in an interactive terminal.".format(host, action)}


def _interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def _apply_write_mcp(root, host, step):
    path = step["path"]
    data, _ = _read_config(root, host)
    key = _spec(host)["config_key"]
    block = dict(_servers(data, host))
    if step["mode"] == "remove":
        block.pop("os-lab", None)
    else:
        block["os-lab"] = step["entry"]
    data[key] = block
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    return "wrote " + path


def apply(root, host, token, confirm, audience="agent"):
    def refuse(message, code):
        audit(root, host, "refused", {"code": code, "audience": audience})
        raise PluginError(message, code)

    if not confirm:
        refuse("The preview needs explicit approval", "CONFIRM_REQUIRED")
    if audience != "terminal" or not _interactive():
        refuse(_spec(host)["title"] + " plugin changes run only in an interactive terminal", "TERMINAL_ONLY")
    with _LOCK:
        held = _PLANS.pop(token, None)
    if not held or held["root"] != os.path.realpath(root) or held["host"] != host or held["expires"] < time.time():
        refuse("The preview expired or was already used", "STALE_PLAN")
    action = held.get("action", "install")
    current, steps = _install_steps(root, host, action)
    # Compare structural fields only (state may include nondeterministic paths).
    if current.get("installed") != held["state"].get("installed") or steps != held["steps"]:
        refuse("Installation state changed since the preview", "STALE_PLAN")
    results = []
    for step in steps:
        try:
            message = _apply_write_mcp(root, host, step)
            results.append({"command": step["op"], "ok": True, "message": message})
        except (OSError, PluginError, ValueError) as exc:
            results.append({"command": step["op"], "ok": False, "message": str(exc)[:500]})
            break
    done = len(results) == len(steps) and all(row["ok"] for row in results)
    audit(root, host, "applied" if done else "failed", {"action": action, "completed": len(results),
          "notRun": len(steps) - len(results)})
    return {"ok": done, "host": host, "steps": results, "notRun": len(steps) - len(results),
            "next": "Restart {0}, then verify.".format(_spec(host)["title"])}


def verify(root, host):
    """Start this checkout's package launcher and compare tool discovery."""
    state = status(root, host)
    if not state["installed"]:
        return {"ok": False, "reason": "os-lab is not installed in the {0} project MCP config".format(host)}
    package = plugin_dir(root, host)
    try:
        mcp_name = _spec(host)["mcp_file"]
        configured = _json(os.path.join(package, mcp_name if os.path.isfile(os.path.join(package, mcp_name)) else "mcp.json"))
        server = configured.get("mcpServers", {}).get("os-lab", {})
        if server.get("type") != "stdio" or server.get("args") != ["${PLUGIN_ROOT}/launcher.py"]:
            return {"ok": False, "reason": "The packaged MCP launch declaration changed"}
        command = shutil.which("python3") or sys.executable
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "reason": "Cannot read MCP launch configuration: " + str(exc)}
    launcher = os.path.join(package, "launcher.py")
    messages = (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"},
    )
    env = dict(os.environ, OSLAB_ROOT=os.path.realpath(root))
    try:
        done = subprocess.run([command, launcher], cwd=package,
                              input="".join(json.dumps(m) + "\n" for m in messages),
                              capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": str(exc)}
    prefix = _spec(host)["prefix"]
    resource = "oslab://{0}-plugin/requirements".format(host)
    prompt = prefix + "_plugin_setup_flow"
    try:
        replies = {row["id"]: row for line in done.stdout.splitlines()
                   if (row := json.loads(line)).get("id") is not None}
        listed_tools = {tool["name"]: tool for tool in replies[2]["result"]["tools"]}
        listed = set(listed_tools)
        import mcp_server
        expected_tools = {tool["name"]: tool for tool in mcp_server.TOOLS}
        expected = set(expected_tools)
        missing, extra = sorted(expected - listed), sorted(listed - expected)
        resource_uris = {row["uri"] for row in replies[3]["result"]["resources"]}
        prompt_names = {row["name"] for row in replies[4]["result"]["prompts"]}
        instructions = replies[1]["result"].get("instructions") or ""
        return {"ok": done.returncode == 0 and not missing and not extra and bool(instructions) and
                resource in resource_uris and prompt in prompt_names,
                "host": host, "tools": len(listed), "resources": len(replies[3]["result"]["resources"]),
                "prompts": len(replies[4]["result"]["prompts"]),
                "missing": missing, "extra": extra, "instructions": bool(instructions)}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"ok": False, "reason": "The installed server did not complete MCP discovery: " + str(exc)}
