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

PLUGIN_REL = os.path.join("plugins", "codex", "os-lab")
MARKET_REL = os.path.join(".agents", "plugins", "marketplace.json")
SOURCE_REL = os.path.join("console", "mcp_skills")
LABS = ("android", "cleanup", "firewall", "ios", "linux", "macos", "source", "web", "websec", "winapps")
OWN_SKILLS = ("setup", "doctor")
PLUGIN_ID = "os-lab@os-lab-local"
PLAN_SECONDS = 600
_PLANS = {}
_LOCK = threading.Lock()
DOCS = {
    "package": "https://developers.openai.com/plugins/build/plugins",
    "skills": "https://developers.openai.com/plugins/build/skills",
    "desktop": "https://developers.openai.com/plugins/deploy/desktop-only",
}


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


def requirements(area=None, usage=None):
    rows = [
        ("manifest.identity", "manifest", "used", "package", "Root plugin.json has a stable name, version and description."),
        ("manifest.extension", "manifest", "used", "package", "OpenAI metadata and onboarding path are valid."),
        ("marketplace.entry", "marketplace", "used", "package", "Repo marketplace has a contained local source and install policy."),
        ("mcp.stdio", "mcp", "used", "desktop", "mcp.json declares one stdio server with a package-local launcher."),
        ("skills.frontmatter", "skills", "used", "skills", "Every skill has a name and description on its first frontmatter block."),
        ("skills.generated", "skills", "used", "skills", "The ten packaged lab skills match their sources."),
        ("cache.contained", "cache", "used", "package", "No packaged symlink escapes the plugin root."),
        ("distribution.readme", "distribution", "used", "package", "The package has a README and license."),
        ("desktop.local", "desktop", "used", "desktop", "Local stdio plugin is tested in a desktop client."),
        ("desktop.mcpb", "desktop", "n/a", "desktop", "Claude Desktop .mcpb is not a Codex package format."),
    ]
    areas = sorted({row[1] for row in rows})
    if area and area not in areas:
        raise PluginError("Unknown area: " + area)
    if usage and usage not in ("used", "n/a"):
        raise PluginError("usage must be used or n/a")
    selected = [{"id": ident, "area": section, "usage": use, "severity": "error" if use == "used" else "info",
                 "rule": rule, "source": DOCS[source], "reviewedOn": "2026-11-26"}
                for ident, section, use, source, rule in rows if
                (not area or section == area) and (not usage or use == usage)]
    return {"areas": areas, "count": len(selected), "requirements": selected}


def _path_inside(path, root):
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
    except ValueError:  # paths on different Windows drives
        return False


def _checks(root):
    package = plugin_dir(root)
    errors = {}
    try:
        manifest = _json(os.path.join(package, "plugin.json"))
        if manifest.get("name") != "os-lab" or not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
            errors["manifest.identity"] = "Plugin name or version is invalid"
        extension = manifest.get("extensions", {}).get("com.openai", {})
        onboard = extension.get("onboardingSkill", "")
        if not onboard.startswith("./") or ".." in onboard.split("/") or not os.path.isfile(os.path.join(package, onboard)):
            errors["manifest.extension"] = "onboardingSkill is missing or escapes the package"
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        errors["manifest.identity"] = str(exc)
        errors["manifest.extension"] = "Cannot check without a valid manifest"
    try:
        market = _json(os.path.join(root, MARKET_REL))
        entries = market.get("plugins", [])
        valid = market.get("name") == "os-lab-local" and len(entries) == 1
        entry = entries[0] if valid else {}
        source = entry.get("source", {})
        valid = valid and entry.get("name") == "os-lab" and source.get("source") == "local" and source.get("path") == "./plugins/codex/os-lab"
        valid = valid and entry.get("policy", {}).get("installation") == "AVAILABLE" and bool(entry.get("policy", {}).get("authentication"))
        if not valid:
            errors["marketplace.entry"] = "Marketplace source or policy is invalid"
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        errors["marketplace.entry"] = str(exc)
    try:
        mcp = _json(os.path.join(package, "mcp.json"))
        server = mcp.get("mcpServers", {}).get("os-lab", {})
        if server.get("type") != "stdio" or server.get("command") != "python3" or server.get("args") != ["${PLUGIN_ROOT}/launcher.py"]:
            errors["mcp.stdio"] = "Local stdio launcher declaration is invalid"
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        errors["mcp.stdio"] = str(exc)
    for name in LABS + OWN_SKILLS:
        path = os.path.join(package, "skills", name, "SKILL.md")
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            header = text.split("---", 2)[1] if text.startswith("---\n") else ""
            if not re.search(r"(?m)^name: .+$", header) or not re.search(r"(?m)^description: .+$", header):
                errors["skills.frontmatter"] = "Invalid frontmatter in " + name
        except OSError:
            errors["skills.frontmatter"] = "Missing skill " + name
    drift = skill_drift(root)
    if drift:
        errors["skills.generated"] = "; ".join(drift)
    for base, dirs, files in os.walk(package, followlinks=False):
        for name in dirs + files:
            path = os.path.join(base, name)
            if os.path.islink(path) and not _path_inside(path, package):
                errors["cache.contained"] = "Symlink escapes package: " + os.path.relpath(path, package)
    if not os.path.isfile(os.path.join(package, "README.md")) or not os.path.isfile(os.path.join(package, "LICENSE")):
        errors["distribution.readme"] = "Packaged README or license is missing"
    return errors


def check(root, area=None):
    errors = _checks(root)
    rows = []
    for rule in requirements(area)["requirements"]:
        ident = rule["id"]
        if rule["usage"] == "n/a":
            result, detail = "n/a", rule["rule"]
        elif ident == "desktop.local":
            result, detail = "manual", "Requires an isolated Codex desktop installation"
        elif ident in errors:
            result, detail = "fail", errors[ident]
        else:
            result, detail = "pass", "ok"
        entry = {"id": ident, "area": rule["area"], "result": result, "detail": detail, "source": rule["source"]}
        if result == "fail":
            entry["fix"] = rule["rule"]
        rows.append(entry)
    return {"ok": all(row["result"] != "fail" for row in rows), "results": rows,
            "summary": {state: sum(row["result"] == state for row in rows) for state in ("pass", "fail", "manual", "n/a")}}


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


def status(root):
    """Read-only Codex installation state; never reads secret-bearing config values."""
    found = {"pluginId": PLUGIN_ID, "checkout": os.path.realpath(root), "installed": False,
             "marketplace": False, "duplicates": []}
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
    return found


def doctor(root):
    from importlib.util import spec_from_file_location, module_from_spec
    path = os.path.join(plugin_dir(root), "launcher.py")
    spec = spec_from_file_location("os_lab_codex_launcher", path)
    if not os.path.isfile(path) or not spec or not spec.loader:
        raise PluginError("The plugin launcher is missing", "PACKAGE_MISSING")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout, source, problem = module.find_checkout(here=path)
    checks = [
        {"name": "python", "ok": sys.version_info >= (3, 8), "detail": sys.version.split()[0]},
        {"name": "checkout", "ok": bool(checkout), "detail": checkout or problem, "source": source},
        {"name": "package", "ok": check(root)["ok"], "detail": "package checks"},
    ]
    return {"ready": all(row["ok"] for row in checks), "platform": sys.platform, "checks": checks}


def _install_steps(root, action):
    if action != "install":
        raise PluginError("Codex CLI 0.167.0 has no tested {0} operation here; use the Codex plugin browser".format(action),
                          "UNSUPPORTED")
    state = status(root)
    if state["marketplace"] and not state.get("thisCheckout"):
        raise PluginError("A marketplace entry named os-lab points to another source", "CONFLICT")
    if state["installed"]:
        raise PluginError("The plugin is already installed; inspect it in the plugin browser", "ALREADY_INSTALLED")
    steps = []
    if not state["marketplace"]:
        steps.append(["plugin", "marketplace", "add", os.path.realpath(root), "--json"])
    steps.append(["plugin", "add", PLUGIN_ID, "--json"])
    return state, steps


def plan(root, action):
    """Preview a fixed local CLI install. The MCP tool cannot apply it."""
    state, steps = _install_steps(root, action)
    token = secrets.token_urlsafe(24)
    with _LOCK:
        _PLANS[token] = {"root": os.path.realpath(root), "state": state, "steps": steps,
                         "expires": time.time() + PLAN_SECONDS}
    return {"action": action, "token": token, "expiresInSeconds": PLAN_SECONDS,
            "commands": ["codex " + " ".join(subprocess.list2cmdline([word]) for word in step) for step in steps],
            "terminalOnly": True, "note": "Run python3 scripts/codex-plugin.py install in an interactive terminal."}


def apply(root, token, confirm, audience="agent"):
    """Only an interactive terminal may apply a preview, after state recheck."""
    if not confirm:
        raise PluginError("The preview needs explicit approval", "CONFIRM_REQUIRED")
    if audience != "terminal" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise PluginError("Installation runs only in an interactive terminal", "TERMINAL_ONLY")
    with _LOCK:
        held = _PLANS.pop(token, None)
    if not held or held["root"] != os.path.realpath(root) or held["expires"] < time.time():
        raise PluginError("The preview expired or was already used", "STALE_PLAN")
    current, steps = _install_steps(root, "install")
    if current != held["state"] or steps != held["steps"]:
        raise PluginError("Codex installation state changed since the preview", "STALE_PLAN")
    results = []
    for step in steps:
        try:
            output = _codex(*step)
            results.append({"command": "codex " + " ".join(step), "ok": True,
                            "message": json.loads(output).get("pluginId", "ok")})
        except (PluginError, ValueError) as exc:
            results.append({"command": "codex " + " ".join(step), "ok": False, "message": str(exc)[:500]})
            break
    return {"ok": len(results) == len(steps) and all(row["ok"] for row in results),
            "steps": results, "notRun": len(steps) - len(results)}


def verify(root):
    """Start only this checkout's installed plugin launcher and compare tool discovery."""
    state = status(root)
    if not state["installed"] or not state.get("enabled"):
        return {"ok": False, "reason": "os-lab is not installed and enabled in Codex"}
    if not state.get("thisCheckout"):
        return {"ok": False, "reason": "The installed plugin is not from this checkout; nothing was started"}
    launcher = os.path.join(plugin_dir(root), "launcher.py")
    messages = (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"},
    )
    env = dict(os.environ, OSLAB_ROOT=os.path.realpath(root))
    try:
        done = subprocess.run([sys.executable, launcher], input="".join(json.dumps(m)+"\n" for m in messages),
                              capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": str(exc)}
    try:
        replies = {row["id"]: row for line in done.stdout.splitlines()
                   if (row := json.loads(line)).get("id") is not None}
        listed = {tool["name"] for tool in replies[2]["result"]["tools"]}
        import mcp_server
        expected = {tool["name"] for tool in mcp_server.TOOLS}
        missing, extra = sorted(expected - listed), sorted(listed - expected)
        return {"ok": done.returncode == 0 and not missing and not extra,
                "tools": len(listed), "resources": len(replies[3]["result"]["resources"]),
                "prompts": len(replies[4]["result"]["prompts"]),
                "missing": missing, "extra": extra}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"ok": False, "reason": "The installed server did not complete MCP discovery: " + str(exc)}
