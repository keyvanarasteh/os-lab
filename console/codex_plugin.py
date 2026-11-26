"""Codex plugin package checks, status and generated skills. Standard library only."""
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

PLUGIN_REL = os.path.join("plugins", "codex", "os-lab")
MARKET_REL = os.path.join(".agents", "plugins", "marketplace.json")
SOURCE_REL = os.path.join("console", "mcp_skills")
CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codex_requirements.json")
LABS = ("android", "cleanup", "firewall", "ios", "linux", "macos", "source", "web", "websec", "winapps")
OWN_SKILLS = ("setup", "doctor")
PLUGIN_ID = "os-lab@os-lab-local"
ACTIONS = ("install", "update", "uninstall")
TERMINAL_ONLY = ACTIONS
PLAN_SECONDS = 600
PUBLISHED_URL = ("https://raw.githubusercontent.com/keyvanarasteh/os-lab/master/"
                 "plugins/codex/os-lab/plugin.json")
_PLANS = {}
_LOCK = threading.Lock()


class PluginError(Exception):
    def __init__(self, message, code="INVALID_ARGS"):
        super().__init__(message)
        self.code = code


def _json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def plugin_dir(root):
    return os.path.join(root, PLUGIN_REL)


def generated_skills(root):
    """Package all lab workflows with names that cannot collide with loose MCP skills."""
    result = {}
    for lab in LABS:
        source = os.path.join(root, SOURCE_REL, lab, "SKILL.md")
        with open(source, encoding="utf-8") as handle:
            body = handle.read()
        if not body.startswith("---\n") or not re.search(r"(?m)^name: .+$", body):
            raise PluginError("Invalid source skill: " + source, "SKILL_INVALID")
        result[lab] = re.sub(r"(?m)^name: .+$", "name: os-lab-" + lab, body, count=1)
    return result


def skill_drift(root):
    target = os.path.join(plugin_dir(root), "skills")
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
            problems.append("missing" if actual is None else "out of date")
            problems[-1] += " skills/{0}/SKILL.md".format(lab)
    if os.path.isdir(target):
        for name in os.listdir(target):
            if name not in expected and name not in OWN_SKILLS:
                problems.append("unexpected skills/" + name)
    return sorted(problems)


def build_skills(root):
    changed = skill_drift(root)
    for lab, body in generated_skills(root).items():
        folder = os.path.join(plugin_dir(root), "skills", lab)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    return changed


def catalog() -> dict:
    return _json(CATALOG_PATH)


def checkout_version(root: str) -> str:
    return str(_json(os.path.join(plugin_dir(root), "plugin.json"))["version"])


def requirements(area=None, usage=None):
    data = catalog()
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
    except ValueError:  # paths on different Windows drives
        return False


def _readme_words(package: str) -> int:
    try:
        with open(os.path.join(package, "README.md"), encoding="utf-8") as handle:
            return len(re.findall(r"\w+", handle.read()))
    except OSError:
        return 0


def _run_check(name: str, root: str) -> tuple[str, str]:
    package = plugin_dir(root)
    if name == "n/a":
        return "n/a", "Not applicable for Codex"
    if name == "manual":
        return "manual", "Requires an isolated Codex desktop installation"
    if name == "manifest_identity":
        try:
            manifest = _json(os.path.join(package, "plugin.json"))
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
    if name == "manifest_extension":
        try:
            manifest = _json(os.path.join(package, "plugin.json"))
            extension = manifest.get("extensions", {}).get("com.openai", {})
            onboard = extension.get("onboardingSkill", "")
            iface = extension.get("interface") or {}
            if not onboard.startswith("./") or ".." in onboard.split("/") or not os.path.isfile(os.path.join(package, onboard)):
                return "fail", "onboardingSkill is missing or escapes the package"
            if not iface.get("displayName") or not iface.get("shortDescription"):
                return "fail", "OpenAI interface display fields are missing"
            return "pass", "ok"
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            return "fail", str(exc)
    if name == "market_name":
        try:
            market = _json(os.path.join(root, MARKET_REL))
            return ("pass", "ok") if market.get("name") == "os-lab-local" else ("fail", "Marketplace name is not os-lab-local")
        except (OSError, ValueError, TypeError) as exc:
            return "fail", str(exc)
    if name == "market_entry":
        try:
            market = _json(os.path.join(root, MARKET_REL))
            entries = market.get("plugins", [])
            valid = market.get("name") == "os-lab-local" and len(entries) == 1
            entry = entries[0] if valid else {}
            source = entry.get("source", {})
            valid = valid and entry.get("name") == "os-lab" and source.get("source") == "local"
            valid = valid and source.get("path") == "./plugins/codex/os-lab"
            valid = valid and entry.get("policy", {}).get("installation") == "AVAILABLE"
            valid = valid and bool(entry.get("policy", {}).get("authentication"))
            return ("pass", "ok") if valid else ("fail", "Marketplace source or policy is invalid")
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            return "fail", str(exc)
    if name == "mcp_stdio":
        try:
            mcp = _json(os.path.join(package, "mcp.json"))
            server = mcp.get("mcpServers", {}).get("os-lab", {})
            ok = (server.get("type") == "stdio" and server.get("command") == "python3"
                  and server.get("args") == ["${PLUGIN_ROOT}/launcher.py"])
            return ("pass", "ok") if ok else ("fail", "Local stdio launcher declaration is invalid")
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            return "fail", str(exc)
    if name == "mcp_annotations":
        import mcp_codex_plugin
        missing = [tool["name"] for tool in mcp_codex_plugin.TOOLS
                   if "readOnlyHint" not in (tool.get("annotations") or {})]
        return ("fail", "Missing readOnlyHint: " + ", ".join(missing)) if missing else ("pass", "ok")
    if name == "mcp_instructions":
        import mcp_server
        text = mcp_server.INSTRUCTIONS
        ok = "codex_plugin_doctor" in text and "codex_plugin_plan" in text
        return ("pass", "ok") if ok else ("fail", "Initialize instructions omit Codex plugin tools")
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
        drift = skill_drift(root)
        return ("fail", "; ".join(drift)) if drift else ("pass", "ok")
    if name == "cache_contained":
        for base, dirs, files in os.walk(package, followlinks=False):
            for entry in dirs + files:
                path = os.path.join(base, entry)
                if os.path.islink(path) and not _path_inside(path, package):
                    return "fail", "Symlink escapes package: " + os.path.relpath(path, package)
        return "pass", "ok"
    if name == "cli_available":
        binary = shutil.which("codex")
        # Missing CLI is skipped so package checks stay useful before Codex is installed.
        return ("pass", binary) if binary else ("skipped", "Codex CLI is not on PATH")
    if name == "readme":
        if not os.path.isfile(os.path.join(package, "LICENSE")):
            return "fail", "Packaged license is missing"
        words = _readme_words(package)
        return ("pass", "{0} words".format(words)) if words >= 40 else ("fail", "README is under 40 words")
    return "fail", "Unknown check: " + name


def check(root, area=None):
    rows = []
    for rule in requirements(area)["requirements"]:
        result, detail = _run_check(rule["check"], root)
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


def _codex(*args):
    binary = shutil.which("codex")
    if not binary:
        raise PluginError("Codex CLI is not on PATH", "CLI_MISSING")
    try:
        run = subprocess.run([binary, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PluginError(str(exc), "CLI_FAILED") from exc
    if run.returncode:
        raise PluginError((run.stderr or run.stdout).strip()[-500:], "CLI_FAILED")
    return run.stdout


def _version_key(version) -> tuple:
    try:
        return tuple(int(part) for part in str(version).split("."))
    except (TypeError, ValueError):
        return (0,)


def status(root):
    """Read-only Codex installation state; never reads secret-bearing config values."""
    found = {"pluginId": PLUGIN_ID, "checkout": os.path.realpath(root), "cli": shutil.which("codex"),
             "installed": False, "marketplace": False, "duplicates": [], "checkoutVersion": None,
             "manualConfig": None}
    try:
        found["checkoutVersion"] = checkout_version(root)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        data = json.loads(_codex("plugin", "list", "--available", "--json"))
        rows = data.get("installed", []) + data.get("available", [])
        for row in rows:
            if row.get("pluginId") == PLUGIN_ID:
                found["installed"] = bool(row.get("installed"))
                found["enabled"] = bool(row.get("enabled"))
                found["marketplace"] = True
                found["version"] = row.get("version")
                source = row.get("source") or {}
                found["thisCheckout"] = (source.get("source") == "local" and
                    os.path.realpath(source.get("path") or "") == os.path.realpath(plugin_dir(root)))
                break
    except (PluginError, ValueError, AttributeError) as exc:
        found["note"] = "Codex state unavailable: " + str(exc)
    # Report only names. Never return env, headers, or arbitrary config values.
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    paths = [os.path.join(root, ".codex", "config.toml"), os.path.join(codex_home, "config.toml")]
    if sys.version_info >= (3, 11):
        import tomllib
        for path in paths:
            try:
                with open(path, "rb") as handle:
                    data = tomllib.load(handle)
                for name in data.get("mcp_servers", {}):
                    if name in ("os-lab", "os-lab-macos", "os-lab-windows"):
                        found["duplicates"].append({"name": name, "scope": "project" if path.startswith(root) else "user"})
            except (OSError, ValueError, TypeError):
                continue
    if found["duplicates"]:
        found["manualConfig"] = ("Remove the manual plugins/mcp/codex/config.toml MCP entries named "
                                 + ", ".join(sorted({row["name"] for row in found["duplicates"]}))
                                 + " so only the plugin connection remains.")
    return found


def doctor(root):
    from importlib.util import spec_from_file_location, module_from_spec
    path = os.path.join(plugin_dir(root), "launcher.py")
    spec = spec_from_file_location("os_lab_codex_launcher", path)
    cli = shutil.which("codex")
    checks = [
        {"name": "python", "ok": sys.version_info >= (3, 8), "detail": sys.version.split()[0],
         "fix": None if sys.version_info >= (3, 8) else "Install Python 3.8 or newer"},
        {"name": "cli", "ok": bool(cli), "detail": cli or "missing",
         "fix": None if cli else "Install the Codex CLI and put it on PATH"},
    ]
    if not os.path.isfile(path) or not spec or not spec.loader:
        checks.append({
            "name": "package", "ok": False, "detail": path,
            "fix": "Rebuild or reinstall the app so plugins/codex/os-lab/launcher.py ships with the runtime",
        })
        return {"ready": False, "platform": sys.platform, "checks": checks}
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout, source, problem = module.find_checkout(here=path)
    package_ok = check(root)["ok"]
    checks.extend([
        {"name": "checkout", "ok": bool(checkout), "detail": checkout or problem, "source": source,
         "fix": None if checkout else "Set OSLAB_ROOT to this repository"},
        {"name": "package", "ok": package_ok, "detail": "package checks",
         "fix": None if package_ok else "Run python3 scripts/codex-plugin.py check"},
    ])
    return {"ready": all(row["ok"] for row in checks), "platform": sys.platform, "checks": checks}


def published_version(timeout: float = 5) -> tuple[str | None, str | None]:
    request = urllib.request.Request(PUBLISHED_URL, headers={"User-Agent": "os-lab"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            version = str(json.loads(reply.read(200_000).decode("utf-8"))["version"])
        if not re.match(r"^\d+(\.\d+)+$", version):
            raise ValueError("unexpected version")
        return version, None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, "could not read the published version: {0}".format(type(exc).__name__)


def updates(root, online: bool = False, timeout: float = 5) -> dict:
    """Compare the checkout with the installed Codex plugin; online also asks GitHub."""
    wanted = checkout_version(root)
    result: dict = {"online": online, "checkoutVersion": wanted, "updatesAvailable": []}
    if online:
        latest, problem = published_version(timeout)
        newer = bool(latest) and _version_key(wanted) < _version_key(latest)
        result["published"] = {"version": latest, "updateAvailable": newer if latest else None}
        if problem:
            result["published"]["note"] = problem
        if newer:
            result["updatesAvailable"].append("checkout")
            result["published"]["next"] = "Update the checkout (git pull), then reinstall the plugin."
    state = status(root)
    result["codex"] = {
        "cli": state.get("cli"),
        "installed": state.get("installed"),
        "version": state.get("version"),
        "updateAvailable": bool(state.get("installed") and state.get("version")
                                and _version_key(state.get("version")) < _version_key(wanted)),
    }
    if result["codex"]["updateAvailable"]:
        result["updatesAvailable"].append("codex")
        result["codex"]["next"] = "codex_plugin_plan with action update"
    return result


def _install_steps(root, action):
    if action not in ACTIONS:
        raise PluginError("action must be one of: {0}".format(", ".join(ACTIONS)), "UNSUPPORTED")
    state = status(root)
    if state["marketplace"] and state.get("thisCheckout") is False:
        raise PluginError("A marketplace entry named os-lab points to another source", "CONFLICT")
    steps = []
    if action == "install":
        if state["installed"]:
            raise PluginError("The plugin is already installed; use update or the plugin browser",
                              "ALREADY_INSTALLED")
        if not state["marketplace"]:
            steps.append(["plugin", "marketplace", "add", os.path.realpath(root), "--json"])
        steps.append(["plugin", "add", PLUGIN_ID, "--json"])
    elif action == "update":
        if not state["installed"]:
            raise PluginError("The plugin is not installed", "NOT_INSTALLED")
        steps.append(["plugin", "remove", PLUGIN_ID, "--json"])
        if not state["marketplace"]:
            steps.append(["plugin", "marketplace", "add", os.path.realpath(root), "--json"])
        steps.append(["plugin", "add", PLUGIN_ID, "--json"])
    else:  # uninstall
        if not state["installed"]:
            raise PluginError("The plugin is not installed", "NOT_INSTALLED")
        steps.append(["plugin", "remove", PLUGIN_ID, "--json"])
    return state, steps


def audit(root, event, detail):
    """Record lifecycle outcomes without tokens, CLI output or config values."""
    path = os.path.join(root, "artifacts", "codex-plugin-audit-" + time.strftime("%Y-%m-%d") + ".jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                     "event": event, **detail}) + "\n")
    except OSError:
        pass


def plan(root, action):
    """Preview a fixed local CLI change. The MCP tool cannot apply it."""
    state, steps = _install_steps(root, action)
    token = secrets.token_urlsafe(24)
    with _LOCK:
        _PLANS[token] = {"root": os.path.realpath(root), "action": action, "state": state, "steps": steps,
                         "expires": time.time() + PLAN_SECONDS}
    warnings = []
    if state.get("manualConfig"):
        warnings.append(state["manualConfig"])
    audit(root, "planned", {"action": action, "steps": len(steps)})
    return {"action": action, "token": token, "expiresInSeconds": PLAN_SECONDS,
            "commands": ["codex " + " ".join(subprocess.list2cmdline([word]) for word in step) for step in steps],
            "manual": [], "warnings": warnings, "terminalOnly": True,
            "terminalCommand": "python3 scripts/codex-plugin.py " + action,
            "note": "Run python3 scripts/codex-plugin.py {0} in an interactive terminal.".format(action)}


def _interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def apply(root, token, confirm, audience="agent"):
    """Only an interactive terminal may apply a preview, after state recheck."""
    def refuse(message, code):
        audit(root, "refused", {"code": code, "audience": audience})
        raise PluginError(message, code)

    if not confirm:
        refuse("The preview needs explicit approval", "CONFIRM_REQUIRED")
    if audience != "terminal" or not _interactive():
        refuse("Codex plugin changes run only in an interactive terminal", "TERMINAL_ONLY")
    with _LOCK:
        held = _PLANS.pop(token, None)
    if not held or held["root"] != os.path.realpath(root) or held["expires"] < time.time():
        refuse("The preview expired or was already used", "STALE_PLAN")
    action = held.get("action", "install")
    current, steps = _install_steps(root, action)
    if current != held["state"] or steps != held["steps"]:
        refuse("Codex installation state changed since the preview", "STALE_PLAN")
    results = []
    for step in steps:
        try:
            output = _codex(*step)
            try:
                message = json.loads(output).get("pluginId") or json.loads(output).get("status") or "ok"
            except ValueError:
                message = "ok"
            results.append({"command": "codex " + " ".join(step), "ok": True, "message": message})
        except (PluginError, ValueError) as exc:
            results.append({"command": "codex " + " ".join(step), "ok": False, "message": str(exc)[:500]})
            break
    done = len(results) == len(steps) and all(row["ok"] for row in results)
    audit(root, "applied" if done else "failed", {"action": action, "completed": len(results),
          "notRun": len(steps) - len(results)})
    return {"ok": done, "steps": results, "notRun": len(steps) - len(results),
            "next": "Restart Codex or reopen the plugin browser, then verify."}


def verify(root):
    """Start only this checkout's installed plugin launcher and compare tool discovery."""
    state = status(root)
    if not state["installed"] or not state.get("enabled"):
        return {"ok": False, "reason": "os-lab is not installed and enabled in Codex"}
    if not state.get("thisCheckout"):
        return {"ok": False, "reason": "The installed plugin is not from this checkout; nothing was started"}
    package = plugin_dir(root)
    try:
        configured = _json(os.path.join(package, "mcp.json"))["mcpServers"]["os-lab"]
        if configured["type"] != "stdio" or configured["args"] != ["${PLUGIN_ROOT}/launcher.py"]:
            return {"ok": False, "reason": "The installed MCP launch declaration changed"}
        command = shutil.which(configured["command"])
        if not command:
            return {"ok": False, "reason": "The configured Python command is missing: " + configured["command"]}
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
                              input="".join(json.dumps(m)+"\n" for m in messages),
                              capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": str(exc)}
    try:
        replies = {row["id"]: row for line in done.stdout.splitlines()
                   if (row := json.loads(line)).get("id") is not None}
        listed_tools = {tool["name"]: tool for tool in replies[2]["result"]["tools"]}
        listed = set(listed_tools)
        import mcp_server
        expected_tools = {tool["name"]: tool for tool in mcp_server.TOOLS}
        expected = set(expected_tools)
        missing, extra = sorted(expected - listed), sorted(listed - expected)
        annotations_changed = sorted(name for name in listed & expected
                                     if listed_tools[name].get("annotations") != expected_tools[name].get("annotations"))
        resource_uris = {row["uri"] for row in replies[3]["result"]["resources"]}
        prompt_names = {row["name"] for row in replies[4]["result"]["prompts"]}
        instructions = replies[1]["result"].get("instructions") or ""
        return {"ok": done.returncode == 0 and not missing and not extra and
                not annotations_changed and bool(instructions) and
                "oslab://codex-plugin/requirements" in resource_uris and
                "codex_plugin_setup_flow" in prompt_names,
                "tools": len(listed), "resources": len(replies[3]["result"]["resources"]),
                "prompts": len(replies[4]["result"]["prompts"]),
                "missing": missing, "extra": extra, "annotationsChanged": annotations_changed,
                "instructions": bool(instructions)}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"ok": False, "reason": "The installed server did not complete MCP discovery: " + str(exc)}
