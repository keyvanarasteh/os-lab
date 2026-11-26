"""os-lab as a Claude plugin: requirement checks, status, previewed changes and verification.

Used by console/mcp_plugin.py (the plugin_* tools) and scripts/claude-plugin.py. Standard
library only. Every command run here is a fixed argument list built in this module: callers
choose an action and a scope, never a command, a path or a marketplace source.
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import zipfile

MARKETPLACE = "os-lab"
PLUGIN = "os-lab"
PLUGIN_ID = PLUGIN + "@" + MARKETPLACE
PLUGIN_REL = os.path.join("plugins", "claude", "os-lab")
SKILL_SOURCE_REL = os.path.join("console", "mcp_skills")
CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_requirements.json")
OWN_SKILLS = ("doctor", "setup")
MIN_CLI = (2, 1, 285)
SCOPES = ("user", "project", "local")
ACTIONS = ("install", "update", "configure", "enable", "disable", "uninstall", "remove-duplicate",
           "extension-install")
TERMINAL_ONLY = ("uninstall", "remove-duplicate")
DUPLICATE_NAMES = ("os-lab", "os-lab-macos", "os-lab-windows")
PLAN_SECONDS = 600
RUN_SECONDS = 120
TOOL_PREFIX = "mcp__plugin_{0}_{0}__".format(PLUGIN)

_PLANS: dict[str, dict] = {}
_LOCK = threading.Lock()


class PluginError(Exception):
    def __init__(self, message: str, code: str = "INVALID_ARGS"):
        super().__init__(message)
        self.code = code


def _read_json(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def plugin_dir(root: str) -> str:
    return os.path.join(root, PLUGIN_REL)


# --- Claude Code CLI ------------------------------------------------------------

def claude_binary() -> str | None:
    """OSLAB_CLAUDE_BIN (tests, unusual installs), then PATH, then the running session's binary."""
    override = os.environ.get("OSLAB_CLAUDE_BIN")
    if override is not None:
        return override if os.path.isfile(override) else None
    found = shutil.which("claude")
    if found:
        return found
    session = os.environ.get("CLAUDE_CODE_EXECPATH")
    return session if session and os.path.isfile(session) else None


def _run(argv: list[str], cwd: str, timeout: int = RUN_SECONDS, stdin: str | None = None) -> dict:
    try:
        done = subprocess.run(argv, cwd=cwd, input=stdin or "", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PluginError("claude did not answer within {0} seconds".format(timeout), "TIMEOUT") from None
    except OSError as exc:
        raise PluginError("claude could not be started: {0}".format(exc), "CLI_MISSING") from None
    return {"code": done.returncode, "stdout": done.stdout, "stderr": done.stderr}


def _parse_json(text: str):
    """The whole output, or its last JSON line (--json results follow human messages)."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    raise PluginError("claude returned output that is not JSON", "CLI_OUTPUT")


def _need_cli() -> str:
    binary = claude_binary()
    if not binary:
        raise PluginError("Claude Code is not installed or not on PATH", "CLI_MISSING")
    return binary


def _query(root: str, *args: str):
    reply = _run([_need_cli(), "plugin", *args], root, timeout=30)
    if reply["code"] != 0:
        raise PluginError("claude plugin {0} failed: {1}".format(
            " ".join(args), (reply["stderr"] or reply["stdout"]).strip()[:500]), "CLI_FAILED")
    return _parse_json(reply["stdout"])


def cli_version(root: str) -> tuple[int, int, int] | None:
    binary = claude_binary()
    if not binary:
        return None
    try:
        reply = _run([binary, "--version"], root, timeout=15)
    except PluginError:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", reply["stdout"])
    return tuple(int(part) for part in match.groups()) if match else None


def _dotted(version) -> str | None:
    return ".".join(str(part) for part in version) if version else None


# --- Doctor and status ------------------------------------------------------------

def doctor(root: str) -> dict:
    """What this computer needs before the plugin can work. Installs nothing."""
    version = cli_version(root)
    checks = []

    def add(name, ok, detail, fix=None):
        row = {"name": name, "ok": bool(ok), "detail": detail}
        if not ok and fix:
            row["fix"] = fix
        checks.append(row)

    add("claude", version is not None,
        "Claude Code {0}".format(_dotted(version)) if version else "Claude Code was not found",
        "Install Claude Code: https://code.claude.com/docs/en/setup")
    if version:
        add("claude-version", version >= MIN_CLI,
            "{0}; needs {1} or newer".format(_dotted(version), _dotted(MIN_CLI)), "Run: claude update")
    add("python", sys.version_info >= (3, 8), "Python {0}.{1}".format(*sys.version_info[:2]),
        "Install Python 3.8 or newer")
    add("python-command", bool(shutil.which("python3") or shutil.which("python")),
        "python3 or python on PATH" if shutil.which("python3") or shutil.which("python") else "neither found",
        "Put Python on PATH, or set the python_command plugin option")
    add("checkout", os.path.isfile(os.path.join(root, "console", "mcp_server.py")), root)
    add("plugin-files", os.path.isfile(os.path.join(plugin_dir(root), ".claude-plugin", "plugin.json")),
        PLUGIN_REL, "Update the checkout; it has no Claude plugin")
    return {"ready": all(row["ok"] for row in checks), "platform": sys.platform, "checks": checks}


def _config_dir() -> str | None:
    return os.environ.get("CLAUDE_CONFIG_DIR") or None


def duplicates(root: str) -> list[dict]:
    """Hand-made MCP entries that would run this server next to the plugin's copy.

    Reads names and arguments only; env values and headers are never returned.
    """
    base = _config_dir()
    user_file = os.path.join(base, ".claude.json") if base else os.path.expanduser("~/.claude.json")
    found = []

    def scan(servers, scope, path):
        if not isinstance(servers, dict):
            return
        for name, entry in servers.items():
            args = entry.get("args") if isinstance(entry, dict) else None
            runs_server = any(str(arg).replace("\\", "/").endswith("console/mcp_server.py")
                              for arg in (args if isinstance(args, list) else []))
            if name in DUPLICATE_NAMES or runs_server:
                found.append({"name": name, "scope": scope, "file": path})

    for path, scope in ((user_file, "user"), (os.path.join(root, ".mcp.json"), "project")):
        try:
            data = _read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        scan(data.get("mcpServers"), scope, path)
        if scope == "user":
            projects = data.get("projects")
            project = projects.get(root) if isinstance(projects, dict) else None
            if isinstance(project, dict):
                scan(project.get("mcpServers"), "local", path)
    return found


def _marketplace_entry(root: str) -> dict | None:
    rows = _query(root, "marketplace", "list", "--json")
    if not isinstance(rows, list):
        raise PluginError("Unexpected marketplace list output", "CLI_OUTPUT")
    return next((row for row in rows if isinstance(row, dict) and row.get("name") == MARKETPLACE), None)


def _is_this_checkout(root: str, entry: dict) -> bool:
    path = entry.get("path") or entry.get("installLocation")
    return bool(path) and entry.get("source") == "directory" and \
        os.path.realpath(path) == os.path.realpath(root)


def _installed(root: str) -> list[dict]:
    rows = _query(root, "list", "--json")
    if not isinstance(rows, list):
        raise PluginError("Unexpected plugin list output", "CLI_OUTPUT")
    keep = ("id", "version", "scope", "enabled", "installPath", "readFromFolder", "errors", "projectPath")
    return [{key: row[key] for key in keep if key in row}
            for row in rows if isinstance(row, dict) and row.get("id") == PLUGIN_ID]


def status(root: str) -> dict:
    version = cli_version(root)
    result = {"cli": _dotted(version), "pluginId": PLUGIN_ID, "duplicates": duplicates(root)}
    if not version:
        result.update({"installed": [], "marketplace": None,
                       "note": "Claude Code was not found, so install state is unknown."})
        return result
    entry = _marketplace_entry(root)
    result["marketplace"] = None if entry is None else {
        "source": entry.get("source"), "path": entry.get("path"), "repo": entry.get("repo"),
        "thisCheckout": _is_this_checkout(root, entry)}
    result["installed"] = _installed(root)
    return result


# --- Skills build -----------------------------------------------------------------

def generated_skills(root: str) -> dict[str, str]:
    """Plugin copies of the lab skills; the name becomes the lab so it reads /os-lab:<lab>."""
    source = os.path.join(root, SKILL_SOURCE_REL)
    skills = {}
    for lab in sorted(os.listdir(source)):
        path = os.path.join(source, lab, "SKILL.md")
        if os.path.isfile(path):
            skills[lab] = re.sub(r"(?m)^name:.*$", "name: " + lab, _read_text(path), count=1)
    return skills


def skill_drift(root: str) -> list[str]:
    target = os.path.join(plugin_dir(root), "skills")
    expected = generated_skills(root)
    problems = []
    for lab, text in expected.items():
        path = os.path.join(target, lab, "SKILL.md")
        if not os.path.isfile(path):
            problems.append("missing skills/{0}/SKILL.md".format(lab))
        elif _read_text(path) != text:
            problems.append("out of date skills/{0}/SKILL.md".format(lab))
    if os.path.isdir(target):
        for name in sorted(os.listdir(target)):
            if name not in expected and name not in OWN_SKILLS and os.path.isdir(os.path.join(target, name)):
                problems.append("unexpected skills/{0}".format(name))
    return problems


def build_skills(root: str) -> list[str]:
    target = os.path.join(plugin_dir(root), "skills")
    expected = generated_skills(root)
    changed = skill_drift(root)
    for lab, text in expected.items():
        folder = os.path.join(target, lab)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    for name in os.listdir(target):
        if name not in expected and name not in OWN_SKILLS:
            shutil.rmtree(os.path.join(target, name))
    return changed


# --- Claude Desktop bundle ---------------------------------------------------------

def mcpb_manifest(root: str) -> dict:
    plugin = _read_json(os.path.join(plugin_dir(root), ".claude-plugin", "plugin.json"))
    options = plugin.get("userConfig", {})
    python = "${user_config.python_command}"
    # The update check belongs to Claude Code's session start hook; a bundle has no hooks.
    options = {key: value for key, value in options.items() if key != "update_check"}
    return {
        "manifest_version": "0.3",
        "name": PLUGIN,
        "display_name": plugin.get("displayName", PLUGIN),
        "version": plugin.get("version"),
        "description": plugin.get("description"),
        "author": plugin.get("author"),
        "repository": {"type": "git", "url": plugin.get("repository")},
        "license": plugin.get("license"),
        "server": {
            "type": "python",
            "entry_point": "server/launcher.py",
            "mcp_config": {
                "command": python,
                "args": ["${__dirname}/server/launcher.py"],
                "env": {"OSLAB_PLUGIN_REPO": "${user_config.repo_path}",
                        "OSLAB_CONSOLE_PORT": "${user_config.console_port}"},
            },
        },
        "compatibility": {"platforms": ["darwin", "win32", "linux"], "runtimes": {"python": ">=3.8"}},
        # A bundle has no folder to walk up from, so the checkout is required here.
        "user_config": {key: dict(value, required=True) if key == "repo_path" else dict(value)
                        for key, value in options.items()},
    }


def build_mcpb(root: str) -> bytes:
    """A reproducible .mcpb archive: manifest.json and the launcher."""
    members = (
        ("manifest.json", json.dumps(mcpb_manifest(root), indent=2) + "\n"),
        ("server/launcher.py", _read_text(os.path.join(plugin_dir(root), "launcher.py"))),
    )
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, text in members:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, text)
    return data.getvalue()


# --- Requirement catalog and checks ------------------------------------------------

def catalog() -> dict:
    return _read_json(CATALOG_PATH)


def requirements(area: str | None = None, usage: str | None = None) -> dict:
    data = catalog()
    rows = data["requirements"]
    areas = sorted({row["area"] for row in rows})
    if area and area not in areas:
        raise PluginError("area must be one of: {0}".format(", ".join(areas)))
    if usage and usage not in ("used", "n/a"):
        raise PluginError("usage must be used or n/a")
    rows = [dict(row, url=data["sources"][row["source"]]) for row in rows
            if (not area or row["area"] == area) and (not usage or row["usage"] == usage)]
    return {"reviewedOn": data["reviewedOn"], "areas": areas, "count": len(rows), "requirements": rows}


def frontmatter(text: str) -> tuple[dict, list[str]] | None:
    """(fields, body lines) of a SKILL.md, or None without frontmatter on line 1."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            fields = {}
            for line in lines[1:end]:
                match = re.match(r"([A-Za-z_-]+):\s*(.*)$", line)
                if match:
                    fields[match.group(1)] = match.group(2)
            return fields, lines[end + 1:]
    return None


class _Context:
    def __init__(self, root: str, use_cli: bool):
        self.root = root
        self.plugin = plugin_dir(root)
        self.use_cli = use_cli
        self._version = False

    def json(self, *parts):
        return _read_json(os.path.join(self.plugin, *parts))

    @property
    def manifest(self):
        return self.json(".claude-plugin", "plugin.json")

    @property
    def market(self):
        return _read_json(os.path.join(self.root, ".claude-plugin", "marketplace.json"))

    @property
    def version(self):
        if self._version is False:
            self._version = cli_version(self.root) if self.use_cli else None
        return self._version

    def skills(self):
        folder = os.path.join(self.plugin, "skills")
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            path = os.path.join(folder, name, "SKILL.md")
            if os.path.isfile(path):
                yield name, _read_text(path)

    def server(self):
        import mcp_server  # imported late: the server imports this module through mcp_plugin
        return mcp_server

    def tools(self):
        server = self.server()
        return server.TOOLS + server.WIN_TOOLS


# A check returns (result, detail): result is pass, fail, warn or skipped. "fail" is turned
# into "warn" for rules whose severity is warning.

def _verdict(problems: list[str], good: str = "ok"):
    if problems:
        return "fail", "; ".join(problems[:8]) + (" (+{0} more)".format(len(problems) - 8) if len(problems) > 8 else "")
    return "pass", good


def _check_manifest_name(ctx):
    name = ctx.manifest.get("name")
    ok = isinstance(name, str) and name and not re.search(r"[\s@:/\\]", name)
    return _verdict([] if ok else ["name is missing or has forbidden characters"], str(name))


def _check_manifest_reserved(ctx):
    name = str(ctx.manifest.get("name", ""))
    bad = name.startswith(("claude-", "anthropic-", "anthropics-", "cc-plugin-")) or \
        name in ("claude", "anthropic", "anthropics", "claude-code", "claude-mods")
    return _verdict(["{0} is reserved".format(name)] if bad else [], name)


def _check_manifest_metadata(ctx):
    manifest = ctx.manifest
    missing = [key for key in ("description", "version", "license") if not manifest.get(key)]
    if not (manifest.get("author") or {}).get("name"):
        missing.append("author.name")
    return _verdict(["missing " + ", ".join(missing)] if missing else [])


_PATH_KEYS = ("skills", "commands", "agents", "hooks", "mcpServers", "lspServers", "outputStyles", "workflows")
_KNOWN_KEYS = _PATH_KEYS + (
    "$schema", "name", "displayName", "version", "description", "author", "homepage", "repository", "license",
    "keywords", "metadata", "icon", "documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl",
    "defaultEnabled", "engines", "dependencies", "network", "userConfig", "types", "channels", "experimental")


def _check_manifest_paths(ctx):
    problems = []
    for key in _PATH_KEYS:
        value = ctx.manifest.get(key)
        for item in value if isinstance(value, list) else [value]:
            if not isinstance(item, str) or item.startswith("https://") or (key == "skills" and item == "."):
                continue
            if not item.startswith("./") or ".." in item.split("/") or "\\" in item:
                problems.append("{0}: {1} must start with ./ and stay inside the plugin".format(key, item))
            elif not os.path.exists(os.path.join(ctx.plugin, item)):
                problems.append("{0}: {1} does not exist".format(key, item))
    return _verdict(problems)


def _check_manifest_keys(ctx):
    unknown = sorted(set(ctx.manifest) - set(_KNOWN_KEYS))
    return _verdict(["unknown: " + ", ".join(unknown)] if unknown else [])


def _check_config_options(ctx):
    problems = []
    for key, option in (ctx.manifest.get("userConfig") or {}).items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            problems.append("{0}: invalid key".format(key))
        if option.get("type") not in ("string", "number", "boolean", "directory", "file"):
            problems.append("{0}: invalid type".format(key))
        if not option.get("title") or not option.get("description"):
            problems.append("{0}: needs title and description".format(key))
    return _verdict(problems)


def _check_config_references(ctx):
    declared = set(ctx.manifest.get("userConfig") or {})
    allowed = {"CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "CLAUDE_PROJECT_DIR"}
    problems = []
    for parts in ((".mcp.json",), ("hooks", "hooks.json")):
        path = os.path.join(ctx.plugin, *parts)
        if not os.path.isfile(path):
            continue
        for name in re.findall(r"\$\{([^}]+)\}", _read_text(path)):
            if name.startswith("user_config."):
                if name.split(".", 1)[1] not in declared:
                    problems.append("{0}: undeclared ${{{1}}}".format(parts[-1], name))
            elif name not in allowed and ":-" not in name:
                problems.append("{0}: ${{{1}}} is not provided by Claude Code".format(parts[-1], name))
    return _verdict(problems)


def _check_market_required(ctx):
    data = ctx.market
    problems = []
    if not data.get("name"):
        problems.append("name is missing")
    if not (data.get("owner") or {}).get("name"):
        problems.append("owner.name is missing")
    if not isinstance(data.get("plugins"), list) or not data.get("plugins"):
        problems.append("plugins is empty")
    return _verdict(problems)


_RESERVED_MARKETS = (
    "claude-code-marketplace", "claude-code-plugins", "claude-plugins-official", "anthropic-marketplace",
    "anthropic-plugins", "agent-skills", "anthropic-agent-skills", "life-sciences", "knowledge-work-plugins",
    "claude-community", "claude-plugins-community", "healthcare", "inline", "builtin", "skills-dir", "synced")


def _check_market_reserved(ctx):
    name = str(ctx.market.get("name", ""))
    bad = name in _RESERVED_MARKETS or name.startswith("claudeai-") or not name.isascii()
    return _verdict(["{0} is reserved".format(name)] if bad else [], name)


def _entry(ctx):
    return next((row for row in ctx.market.get("plugins", []) if row.get("name") == ctx.manifest.get("name")), None)


def _check_market_entry(ctx):
    entry = _entry(ctx)
    if entry is None:
        return "fail", "no entry named like the manifest"
    source = entry.get("source")
    if isinstance(source, str):
        if not source.startswith("./") or ".." in source.split("/"):
            return "fail", "source must start with ./ and contain no .."
        if os.path.realpath(os.path.join(ctx.root, source)) != os.path.realpath(ctx.plugin):
            return "fail", "source does not point at the plugin folder"
    return "pass", str(source)


def _check_market_version(ctx):
    entry = _entry(ctx) or {}
    both = "version" in entry and "version" in ctx.manifest
    return _verdict(["set in both the manifest and the entry"] if both else [])


def _check_mcp_config(ctx):
    servers = ctx.json(".mcp.json").get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        return "fail", ".mcp.json declares no servers"
    problems = []
    for name, server in servers.items():
        if not server.get("command"):
            problems.append("{0}: no command".format(name))
        for arg in server.get("args", []):
            if str(arg).endswith(".py") and not str(arg).startswith("${CLAUDE_PLUGIN_ROOT}/"):
                problems.append("{0}: {1} should use ${{CLAUDE_PLUGIN_ROOT}}".format(name, arg))
    return _verdict(problems, ", ".join(servers))


def _check_mcp_tool_names(ctx):
    names = [tool["name"] for tool in ctx.tools()]
    long = [name for name in names if len(TOOL_PREFIX + name) > 128]
    longest = max(len(TOOL_PREFIX + name) for name in names)
    return _verdict(long, "{0} tools, longest full name {1}".format(len(names), longest))


def _check_mcp_schema_names(ctx):
    problems = ["{0}.{1}".format(tool["name"], key) for tool in ctx.tools()
                for key in tool.get("inputSchema", {}).get("properties", {})
                if not re.match(r"^[A-Za-z0-9_.-]{1,64}$", key)]
    return _verdict(problems)


def _check_mcp_descriptions(ctx):
    problems = [tool["name"] for tool in ctx.tools() if len(tool.get("description", "")) > 4096]
    if len(ctx.server().INSTRUCTIONS) > 4096:
        problems.append("server instructions")
    return _verdict(problems)


def _check_mcp_instructions(ctx):
    reply = ctx.server().handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    return _verdict([] if reply["result"].get("instructions") else ["initialize returns no instructions"])


def _check_mcp_result_size(ctx):
    hinted = [(tool["name"], tool.get("_meta", {}).get("anthropic/maxResultSizeChars")) for tool in ctx.tools()]
    over = [name for name, size in hinted if size is not None and not 0 < size <= 500000]
    return _verdict(over, "{0} tools raise the limit".format(sum(1 for _n, size in hinted if size)))


def _check_mcp_annotations(ctx):
    return _verdict([tool["name"] for tool in ctx.tools()
                     if "readOnlyHint" not in tool.get("annotations", {})])


def _check_skills_frontmatter(ctx):
    skills = list(ctx.skills())
    problems = [name for name, text in skills if frontmatter(text) is None]
    if not skills:
        problems.append("no skills found")
    return _verdict(problems, "{0} skills".format(len(skills)))


_SKILL_FIELDS = {
    "name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
    "user-invocable", "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent", "background",
    "hooks", "paths", "shell", "metadata", "license", "compatibility"}


def _check_skills_fields(ctx):
    return _verdict(["{0}: {1}".format(name, ", ".join(sorted(set(parsed[0]) - _SKILL_FIELDS)))
                     for name, text in ctx.skills()
                     for parsed in [frontmatter(text)] if parsed and set(parsed[0]) - _SKILL_FIELDS])


def _check_skills_description(ctx):
    problems = []
    for name, text in ctx.skills():
        fields = (frontmatter(text) or ({}, []))[0]
        length = len(fields.get("description", "")) + len(fields.get("when_to_use", ""))
        if not fields.get("description"):
            problems.append("{0}: no description".format(name))
        elif length > 1536:
            problems.append("{0}: {1} characters".format(name, length))
    return _verdict(problems)


def _check_skills_length(ctx):
    return _verdict([name for name, text in ctx.skills() if len(text.splitlines()) >= 500])


def _check_skills_generated(ctx):
    return _verdict(skill_drift(ctx.root))


_HOOK_EVENTS = {
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion", "PreSkillShellCommand", "PreToolUse",
    "PermissionRequest", "PermissionDenied", "PostToolUse", "PostToolUseFailure", "PostToolBatch",
    "Notification", "MessageDisplay", "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "Stop",
    "StopFailure", "TeammateIdle", "InstructionsLoaded", "ConfigChange", "CwdChanged", "DirectoryAdded",
    "FileChanged", "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact", "PreModelSwitch",
    "PostModelSwitch", "Elicitation", "ElicitationResult", "SessionEnd"}


def _hooks(ctx):
    for event, groups in ctx.json("hooks", "hooks.json").get("hooks", {}).items():
        for group in groups if isinstance(groups, list) else [None]:
            entries = group.get("hooks") if isinstance(group, dict) else None
            for hook in entries if isinstance(entries, list) else [None]:
                yield event, hook


def _check_hooks_shape(ctx):
    problems = []
    for event, hook in _hooks(ctx):
        if event not in _HOOK_EVENTS:
            problems.append("unknown event {0}".format(event))
        if not isinstance(hook, dict) or hook.get("type") not in ("command", "http", "mcp_tool", "prompt", "agent"):
            problems.append("{0}: a hook has no valid type".format(event))
        elif hook["type"] == "command" and not hook.get("command"):
            problems.append("{0}: command hook without a command".format(event))
        elif event == "SessionStart" and hook["type"] not in ("command", "mcp_tool"):
            problems.append("SessionStart supports command and mcp_tool hooks only")
    return _verdict(problems)


def _check_hooks_timeout(ctx):
    return _verdict(["{0}: no timeout".format(event) for event, hook in _hooks(ctx)
                     if isinstance(hook, dict) and hook.get("type") == "command"
                     and not 0 < hook.get("timeout", 0) <= 60])


def _check_cache_contained(ctx):
    real = os.path.realpath(ctx.plugin)
    problems = []
    for folder, folders, files in os.walk(ctx.plugin):
        for name in folders + files:
            path = os.path.join(folder, name)
            if os.path.islink(path) and not os.path.realpath(path).startswith(real + os.sep):
                problems.append(os.path.relpath(path, ctx.plugin))
    return _verdict(problems)


def _check_cli_available(ctx):
    if not ctx.use_cli:
        return "skipped", "CLI checks were not requested"
    if not ctx.version:
        return "fail", "Claude Code was not found"
    return _verdict([] if ctx.version >= MIN_CLI else ["{0} is older than {1}".format(
        _dotted(ctx.version), _dotted(MIN_CLI))], _dotted(ctx.version))


def _check_cli_validate(ctx):
    if not ctx.version:
        return "skipped", "needs Claude Code"
    problems = []
    for target in (ctx.root, ctx.plugin):
        reply = _run([_need_cli(), "plugin", "validate", target, "--strict", "--json"], ctx.root, timeout=60)
        if reply["code"] != 0:
            detail = (reply["stdout"] or reply["stderr"]).strip()[:400]
            problems.append("{0}: {1}".format(os.path.relpath(target, ctx.root), detail))
    return _verdict(problems, "claude plugin validate --strict passed")


def _check_readme(ctx):
    path = os.path.join(ctx.plugin, "README.md")
    words = len(_read_text(path).split()) if os.path.isfile(path) else 0
    return _verdict([] if words >= 40 else ["README.md has {0} words".format(words)], "{0} words".format(words))


def _check_mcpb_manifest(ctx):
    manifest = mcpb_manifest(ctx.root)
    missing = [key for key in ("manifest_version", "name", "version", "description", "author", "server")
               if not manifest.get(key)]
    if not re.match(r"^\d+\.\d+\.\d+", str(manifest.get("version", ""))):
        missing.append("semver version")
    if not (manifest.get("author") or {}).get("name"):
        missing.append("author.name")
    return _verdict(["missing " + ", ".join(missing)] if missing else [])


def _check_no_bin(ctx):
    present = os.path.isdir(os.path.join(ctx.plugin, "bin"))
    return _verdict(["bin/ exists"] if present else [], "no bin/")


def check(root: str, area: str | None = None, use_cli: bool = True) -> dict:
    """Every catalog rule against this checkout. Reads only."""
    ctx = _Context(root, use_cli)
    results = []
    for rule in requirements(area)["requirements"]:
        name = rule["check"]
        if name == "manual":
            result, detail = ("n/a" if rule["usage"] == "n/a" else "manual"), rule["rule"]
        elif rule.get("minVersion") and ctx.version and \
                ctx.version < tuple(int(p) for p in rule["minVersion"].split(".")):
            result, detail = "skipped", "needs Claude Code " + rule["minVersion"]
        else:
            try:
                result, detail = globals()["_check_" + name](ctx)
            except PluginError as exc:
                result, detail = "fail", str(exc)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                result, detail = "fail", "could not read: {0}: {1}".format(type(exc).__name__, exc)
        if result == "fail" and rule["severity"] == "warning":
            result = "warn"
        row = {"id": rule["id"], "area": rule["area"], "result": result, "detail": detail, "source": rule["url"]}
        if result in ("fail", "warn"):
            row["fix"] = rule["rule"]
        results.append(row)
    summary: dict[str, int] = {}
    for row in results:
        summary[row["result"]] = summary.get(row["result"], 0) + 1
    return {"ok": not summary.get("fail"), "summary": summary, "results": results}


# --- Plan, apply, verify -----------------------------------------------------------

def _python_command() -> str:
    for name in ("python3", "python"):
        if shutil.which(name):
            return name
    return sys.executable


def _configuration(root: str) -> list[str]:
    values = {"repo_path": os.path.realpath(root), "python_command": _python_command()}
    port = os.environ.get("OSLAB_CONSOLE_PORT", "")
    if port.isdigit() and 0 < int(port) < 65536:
        values["console_port"] = port
    check = os.environ.get("OSLAB_UPDATE_CHECK", "")
    if check in ("true", "false"):
        values["update_check"] = check
    return [part for key, value in values.items() for part in ("--config", "{0}={1}".format(key, value))]


def _build_plan(root: str, action: str, scope: str, name: str | None) -> dict:
    if action not in ACTIONS:
        raise PluginError("action must be one of: {0}".format(", ".join(ACTIONS)))
    if scope not in SCOPES:
        raise PluginError("scope must be one of: {0}".format(", ".join(SCOPES)))
    if (action == "remove-duplicate") != bool(name):
        raise PluginError("name is required for remove-duplicate and refused for other actions")
    if action == "extension-install":
        if scope != "user":
            raise PluginError("The Claude Desktop extension has no scope; leave it as user")
        import claude_desktop  # imported late: it imports this module
        return claude_desktop.build_plan(root)
    version = cli_version(root)
    if not version:
        raise PluginError("Claude Code is not installed or not on PATH", "CLI_MISSING")
    if version < MIN_CLI:
        raise PluginError("Claude Code {0} or newer is needed; run: claude update".format(_dotted(MIN_CLI)),
                          "CLI_OLD")
    found = duplicates(root)
    market = _marketplace_entry(root)
    installed = _installed(root)
    here = [row for row in installed if row.get("scope") == scope]
    warnings = []
    commands: list[list[str]] = []
    if action == "remove-duplicate":
        if not any(row["name"] == name and row["scope"] == scope for row in found):
            raise PluginError("No duplicate entry {0} in {1} scope".format(name, scope), "NOT_FOUND")
        commands.append(["mcp", "remove", name, "--scope", scope])
    else:
        if market is not None and not _is_this_checkout(root, market):
            raise PluginError(
                "A marketplace named {0} already points somewhere else ({1}); remove it yourself first".format(
                    MARKETPLACE, market.get("path") or market.get("repo") or market.get("source")), "CONFLICT")
        if action in ("install", "configure"):
            if action == "configure" and not here:
                raise PluginError("The plugin is not installed in {0} scope".format(scope), "NOT_INSTALLED")
            if market is None:
                commands.append(["plugin", "marketplace", "add", os.path.realpath(root), "--scope", scope, "--json"])
            # Installing an installed plugin only saves the options, so configure is the same call.
            commands.append(["plugin", "install", PLUGIN_ID, "--scope", scope, *_configuration(root), "--json"])
        else:
            if not here:
                raise PluginError("The plugin is not installed in {0} scope".format(scope), "NOT_INSTALLED")
            if action == "update":
                commands.append(["plugin", "marketplace", "update", MARKETPLACE, "--json"])
            commands.append(["plugin", action, PLUGIN_ID, "--scope", scope, "--json"])
        for row in found:
            warnings.append("MCP entry '{0}' ({1} scope) also runs this server; remove it with "
                            "scripts/claude-plugin.py remove-duplicate --name {0} --scope {1}".format(
                                row["name"], row["scope"]))
    if scope == "project":
        warnings.append("project scope writes .claude/settings.json in the checkout, which git can pick up")
    return {"action": action, "scope": scope, "name": name, "commands": commands, "warnings": warnings,
            "manual": [], "program": "claude", "state": {"cli": _dotted(version), "marketplace": market, "installed": installed, "duplicates": found}}


def _shown(built: dict, command: list[str]) -> str:
    return subprocess.list2cmdline(([built["program"]] if built["program"] else []) + command)


def plan(root: str, action: str, scope: str = "user", name: str | None = None) -> dict:
    """Preview one change and hand out a token that runs exactly it, once."""
    built = _build_plan(root, action, scope, name)
    token = secrets.token_urlsafe(24)
    with _LOCK:
        now = time.time()
        for old in [key for key, value in _PLANS.items() if value["expires"] < now]:
            del _PLANS[old]
        _PLANS[token] = {"plan": built, "root": os.path.realpath(root), "expires": now + PLAN_SECONDS}
    terminal = "python3 scripts/claude-plugin.py {0} --scope {1}{2}".format(
        action, scope, " --name " + name if name else "")
    return {"token": token, "expiresInSeconds": PLAN_SECONDS, "action": action, "scope": scope,
            "commands": [_shown(built, c) for c in built["commands"]], "manual": built["manual"],
            "warnings": built["warnings"], "terminalOnly": action in TERMINAL_ONLY, "terminalCommand": terminal}


def audit(root: str, event: str, detail: dict) -> None:
    folder = os.path.join(root, "artifacts")
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "claude-plugin-audit-{0}.jsonl".format(time.strftime("%Y-%m-%d")))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **detail}) + "\n")
    except OSError:
        pass


def apply(root: str, token: str, confirm: bool, audience: str = "agent") -> dict:
    """Run a previewed plan. Needs the token, confirm:true and an unchanged state."""
    def refuse(message, code):
        audit(root, "refused", {"audience": audience, "code": code, "reason": message})
        raise PluginError(message, code)

    if confirm is not True:
        refuse("confirm must be true after the user approved the plan", "CONFIRM_REQUIRED")
    with _LOCK:
        held = _PLANS.pop(token, None) if isinstance(token, str) else None
    if held is None or held["root"] != os.path.realpath(root):
        refuse("Unknown or already used token; call plugin_plan again", "STALE_PLAN")
    if held["expires"] < time.time():
        refuse("The plan expired; call plugin_plan again", "STALE_PLAN")
    wanted = held["plan"]
    if audience != "terminal" and wanted["action"] in TERMINAL_ONLY:
        refuse("{0} runs only from a terminal: python3 scripts/claude-plugin.py {0} --scope {1}{2}".format(
            wanted["action"], wanted["scope"],
            " --name " + wanted["name"] if wanted["name"] else ""), "TERMINAL_ONLY")
    current = _build_plan(root, wanted["action"], wanted["scope"], wanted["name"])
    if current != wanted:
        refuse("The installation changed since the preview; call plugin_plan again", "STALE_PLAN")
    desktop = wanted["action"] == "extension-install"
    program = [_need_cli()] if wanted["program"] else []
    if desktop and wanted["commands"]:
        import claude_desktop
        path = claude_desktop.bundle_path(root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(build_mcpb(root))
    elif desktop:
        refuse("Do this by hand: " + " ".join(wanted["manual"]), "MANUAL")
    steps = []
    for command in wanted["commands"]:
        shown = _shown(wanted, command)
        try:
            reply = _run([*program, *command], root)
        except PluginError as exc:
            steps.append({"command": shown, "ok": False, "message": str(exc)})
            break
        message = (reply["stdout"] or reply["stderr"]).strip()
        ok = reply["code"] == 0
        if "--json" in command:
            try:
                parsed = _parse_json(reply["stdout"])
                message = parsed.get("message", message)
                ok = ok and parsed.get("outcome") == "ok"
            except (PluginError, AttributeError):
                ok = False
        steps.append({"command": shown, "ok": ok, "message": message[:1000]})
        if not ok:
            break
    done = len(steps) == len(wanted["commands"]) and all(step["ok"] for step in steps)
    audit(root, "applied" if done else "failed",
          {"audience": audience, "action": wanted["action"], "scope": wanted["scope"], "steps": steps})
    return {"ok": done, "action": wanted["action"], "scope": wanted["scope"], "steps": steps,
            "notRun": len(wanted["commands"]) - len(steps),
            "next": ("Confirm the install in Claude Desktop, then check again with plugin_updates."
                     if desktop else "Restart Claude Code or run /reload-plugins, then verify.") if done else
                    "Fix the failed step, then preview again."}


def _handshake(launcher: str, repo_path: str) -> list[str]:
    """Start a launcher, run initialize and tools/list, return the tool names."""
    lines = "".join(json.dumps(message) + "\n" for message in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    # The saved option, so a wrong repo_path fails here as it would in Claude Code.
    env = dict(os.environ, OSLAB_PLUGIN_REPO=repo_path)
    env.pop("OSLAB_ROOT", None)
    try:
        done = subprocess.run([sys.executable, launcher], input=lines, capture_output=True, text=True,
                              encoding="utf-8", timeout=30, env=env)
    except subprocess.TimeoutExpired:
        raise PluginError("The installed server did not answer within 30 seconds", "TIMEOUT") from None
    for line in done.stdout.splitlines():
        try:
            reply = json.loads(line)
        except ValueError:
            continue
        if reply.get("id") == 2 and "result" in reply:
            return [tool["name"] for tool in reply["result"]["tools"]]
    raise PluginError("The installed server did not list its tools: {0}".format(done.stderr.strip()[-400:]),
                      "VERIFY_FAILED")


def verify(root: str) -> dict:
    """Start the installed plugin's launcher and compare its tools with this checkout."""
    market = _marketplace_entry(root)
    installed = _installed(root)
    if not installed:
        return {"ok": False, "reason": "The plugin is not installed."}
    if market is None or not _is_this_checkout(root, market):
        # Only code that came from this checkout's marketplace is started.
        return {"ok": False, "reason": "The installed marketplace is not this checkout, so nothing was started."}
    row = next((item for item in installed if item.get("enabled")), None)
    if row is None:
        return {"ok": False, "reason": "The plugin is installed but disabled."}
    folder = row.get("readFromFolder") or row.get("installPath") or ""
    launcher = os.path.join(folder, "launcher.py")
    if not os.path.isfile(launcher):
        return {"ok": False, "reason": "launcher.py is missing from the installed plugin."}
    options = _query(root, "configure", PLUGIN_ID, "--json")
    inputs = options.get("inputs") if isinstance(options, dict) else None
    repo_path = str((inputs or {}).get("repo_path") or "")
    listed = set(_handshake(launcher, repo_path))
    import mcp_server
    expected = {tool["name"] for tool in mcp_server.listed_tools()}
    missing, extra = sorted(expected - listed), sorted(listed - expected)
    return {"ok": not missing and not extra, "scope": row.get("scope"), "version": row.get("version"),
            "repoPath": repo_path,
            "tools": len(listed), "missing": missing, "extra": extra}
