"""The os-lab plugin in Claude Desktop, and update checks for it and for Claude Code.

In Claude Desktop the plugin is the os-lab .mcpb extension. This module detects it, compares
versions and builds the install plan; console/claude_plugin.py previews and runs it. It never
installs or updates Claude Desktop or Claude Code themselves. Standard library only. The network
is used only when a caller asks (online=True): one public HTTPS GET that sends nothing about
this computer.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import sys
import time
import urllib.request

import claude_plugin as engine

DESKTOP_ID = "com.anthropic.claudefordesktop"
PUBLISHED_URL = ("https://raw.githubusercontent.com/keyvanarasteh/os-lab/master/"
                 "plugins/claude/os-lab/.claude-plugin/plugin.json")
CACHE_SECONDS = 86400
ACTION = "extension-install"


def _platform() -> str:
    return sys.platform


def version_key(text) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(text or ""))[:4])


def _app_paths() -> list[str]:
    override = os.environ.get("OSLAB_CLAUDE_APP")
    if override is not None:
        return [override] if override else []
    if _platform() == "darwin":
        return ["/Applications/Claude.app", os.path.expanduser("~/Applications/Claude.app")]
    return []


def config_dir() -> str:
    override = os.environ.get("OSLAB_CLAUDE_DESKTOP_DIR")
    if override:
        return override
    if _platform() == "darwin":
        return os.path.expanduser("~/Library/Application Support/Claude")
    if _platform() == "win32":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Claude")
    return os.path.expanduser("~/.config/Claude")


def app_info() -> dict:
    """Whether Claude Desktop is here. installed is None where it cannot be told for sure."""
    if _platform() == "darwin":
        for path in _app_paths():
            try:
                with open(os.path.join(path, "Contents", "Info.plist"), "rb") as handle:
                    plist = plistlib.load(handle)
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            if plist.get("CFBundleIdentifier") == DESKTOP_ID:
                return {"installed": True, "version": plist.get("CFBundleShortVersionString"), "path": path}
        return {"installed": False}
    return {"installed": True if os.path.isdir(config_dir()) else None,
            "note": "Detected from its settings folder; not verified on this system."}


def extension_info(root: str) -> dict:
    """The installed os-lab extension and hand-made config entries that duplicate it."""
    wanted = engine.mcpb_manifest(root)["version"]
    base = config_dir()
    versions = []
    folder = os.path.join(base, "Claude Extensions")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        try:
            manifest = engine._read_json(os.path.join(folder, name, "manifest.json"))
        except (OSError, ValueError):
            continue
        if isinstance(manifest, dict) and manifest.get("name") == engine.PLUGIN:
            versions.append(str(manifest.get("version")))
    duplicates = []
    try:
        servers = engine._read_json(os.path.join(base, "claude_desktop_config.json")).get("mcpServers", {})
        for name, entry in servers.items():
            args = entry.get("args") if isinstance(entry, dict) else None
            runs = any(str(arg).replace("\\", "/").endswith("console/mcp_server.py")
                       for arg in (args if isinstance(args, list) else []))
            if name in engine.DUPLICATE_NAMES or runs:
                duplicates.append(name)
    except (OSError, ValueError, AttributeError):
        pass
    current = max(versions, key=version_key) if versions else None
    return {"installed": bool(versions), "version": current, "checkoutVersion": wanted,
            "updateAvailable": bool(current) and version_key(current) < version_key(wanted),
            "duplicates": duplicates}


def status(root: str) -> dict:
    return {"app": app_info(), "extension": extension_info(root)}


def published_version(timeout: float = 5) -> tuple[str | None, str | None]:
    """(version on the master branch, problem)."""
    request = urllib.request.Request(PUBLISHED_URL, headers={"User-Agent": "os-lab"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            version = str(json.loads(reply.read(200_000).decode("utf-8"))["version"])
        if not re.match(r"^\d+(\.\d+)+$", version):
            raise ValueError("unexpected version")
        return version, None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, "could not read the published version: {0}".format(type(exc).__name__)


def updates(root: str, online: bool = False, timeout: float = 5) -> dict:
    """Is the plugin current in Claude Code and Claude Desktop, and is the checkout current?"""
    wanted = engine.mcpb_manifest(root)["version"]
    result: dict = {"online": online, "checkoutVersion": wanted}
    available = []
    if online:
        latest, problem = published_version(timeout)
        newer = bool(latest) and version_key(wanted) < version_key(latest)
        result["published"] = {"version": latest, "updateAvailable": newer if latest else None}
        if problem:
            result["published"]["note"] = problem
        if newer:
            available.append("checkout")
            result["published"]["next"] = "Update the checkout (git pull), then update the plugin."
    try:
        installed = engine.status(root)["installed"]
        rows = [{"scope": row.get("scope"), "version": row.get("version"),
                 "updateAvailable": version_key(row.get("version")) < version_key(wanted)}
                for row in installed]
        result["claudeCode"] = {"installed": bool(rows), "installs": rows}
        if any(row["updateAvailable"] for row in rows):
            available.append("claude-code")
            result["claudeCode"]["next"] = "plugin_plan with action update"
    except engine.PluginError as exc:
        result["claudeCode"] = {"installed": None, "note": str(exc)}
    result["claudeDesktop"] = status(root)
    if result["claudeDesktop"]["extension"]["updateAvailable"]:
        available.append("claude-desktop")
        result["claudeDesktop"]["next"] = "plugin_plan with action " + ACTION
    result["updatesAvailable"] = available
    return result


def session_notes(root: str, online: bool, data_dir: str = "") -> list[str]:
    """Lines for the session start check. Local files only, unless online is switched on; the
    published version is then asked for at most once a day. Starts no process."""
    notes = []
    extension = extension_info(root)
    if extension["updateAvailable"]:
        notes.append("os-lab Claude Desktop extension {0} is older than {1}. Run /os-lab:setup "
                     "extension-install.".format(extension["version"], extension["checkoutVersion"]))
    if not online or not data_dir:
        return notes
    path = os.path.join(data_dir, "update-check.json")
    latest = None
    try:
        saved = engine._read_json(path)
        fresh = 0 <= time.time() - saved["at"] < CACHE_SECONDS
        latest = saved["version"] if fresh else None
    except (OSError, ValueError, KeyError, TypeError):
        fresh = False
    if not fresh:
        latest = published_version(timeout=3)[0]
        try:
            # A failed request is remembered too, so an offline machine waits once a day.
            os.makedirs(data_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"at": time.time(), "version": latest}, handle)
        except OSError:
            pass
    if latest and version_key(extension["checkoutVersion"]) < version_key(latest):
        notes.append("os-lab plugin {0} is published; this checkout has {1}. Update the checkout, "
                     "then run /os-lab:setup update.".format(latest, extension["checkoutVersion"]))
    return notes


def bundle_path(root: str) -> str:
    return os.path.join(root, "build", "os-lab.mcpb")


def build_plan(root: str) -> dict:
    """Install or update the extension: build the bundle and open it in Claude Desktop, which
    asks the user to confirm. Where it cannot be opened for them, the manual step is given."""
    app, extension = app_info(), extension_info(root)
    if app["installed"] is False:
        raise engine.PluginError("Claude Desktop was not found on this computer", "NOT_INSTALLED")
    bundle = bundle_path(root)
    commands, manual = [], []
    if _platform() == "darwin":
        commands.append(["open", "-a", app["path"], bundle])
    else:
        manual.append("In Claude Desktop open Settings > Extensions and install " + bundle)
    warnings = ["Claude Desktop shows its own install dialog: confirm there and set the checkout folder."]
    warnings += ["claude_desktop_config.json entry '{0}' also runs this server; remove it".format(name)
                 for name in extension["duplicates"]]
    return {"action": ACTION, "scope": "user", "name": None, "commands": commands, "manual": manual,
            "warnings": warnings, "program": None, "state": {"app": app, "extension": extension}}
