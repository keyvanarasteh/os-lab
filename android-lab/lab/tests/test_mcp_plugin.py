"""The Claude plugin: package, launcher, requirement checks, previewed changes and the MCP tools.

A fake `claude` command stands in for Claude Code, so nothing here touches a real configuration.
"""
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import zipfile

import pytest

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PLUGIN = os.path.join(REPO_ROOT, "plugins", "claude", "os-lab")
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))
sys.path.insert(0, PLUGIN)
sys.path.insert(0, os.path.join(PLUGIN, "hooks"))

import claude_desktop as desktop  # noqa: E402
import claude_plugin as engine  # noqa: E402
import launcher  # noqa: E402
import mcp_server  # noqa: E402
import session_check  # noqa: E402

FAKE = r'''#!{python}
import json, os, sys
state_path = os.environ["FAKE_STATE"]
state = json.load(open(state_path))
argv = sys.argv[1:]
state["calls"].append(argv)
def done(value=None, code=0):
    json.dump(state, open(state_path, "w"))
    if value is not None:
        print(value if isinstance(value, str) else json.dumps(value))
    sys.exit(code)
if argv == ["--version"]:
    done(state["version"] + " (Claude Code)")
if state.get("garbage"):
    done("not json")
if argv[:3] == ["plugin", "marketplace", "list"]:
    done(state["markets"])
if argv[:2] == ["plugin", "configure"]:
    done({{"inputs": {{"repo_path": state.get("repo_path", "")}}}})
if argv[:2] == ["plugin", "list"]:
    done(state["installed"])
if argv[:2] == ["plugin", "validate"]:
    done({{"success": True}})
verb = argv[2] if argv[1] == "marketplace" else argv[1]
if state.get("fail") == verb:
    done({{"outcome": "failed", "message": "boom"}}, 1)
if argv[:3] == ["plugin", "marketplace", "add"]:
    state["markets"] = [{{"name": "os-lab", "source": "directory", "path": argv[3]}}]
elif argv[:2] == ["plugin", "install"]:
    state["installed"] = [{{"id": "os-lab@os-lab", "version": "0.1.0", "scope": "user", "enabled": True,
                           "readFromFolder": state["folder"], "mcpServers": {{"secret": 1}}}}]
elif argv[:2] == ["plugin", "uninstall"]:
    state["installed"] = []
elif argv[:2] in (["plugin", "disable"], ["plugin", "enable"]):
    state["installed"][0]["enabled"] = argv[1] == "enable"
done({{"outcome": "ok", "message": "done " + verb}})
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("the fake CLI is a shebang script")
    binary = tmp_path / "claude"
    binary.write_text(FAKE.format(python=sys.executable))
    binary.chmod(0o755)
    state_path = tmp_path / "state.json"

    class Fake:
        def write(self, **changes):
            state = self.read() if state_path.exists() else {
                "version": "2.1.332", "markets": [], "installed": [], "calls": [], "folder": PLUGIN}
            state.update(changes)
            state_path.write_text(json.dumps(state))

        def read(self):
            return json.loads(state_path.read_text())

        def changes(self):
            return [call for call in self.read()["calls"]
                    if call[-1:] == ["--json"] and not {"list", "validate", "configure"} & set(call)]

    instance = Fake()
    instance.write()
    monkeypatch.setenv("OSLAB_CLAUDE_BIN", str(binary))
    monkeypatch.setenv("FAKE_STATE", str(state_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(engine, "audit", lambda *args: None)
    monkeypatch.setenv("OSLAB_CLAUDE_DESKTOP_DIR", str(tmp_path / "desktop"))
    return instance


def _code(call):
    with pytest.raises(engine.PluginError) as caught:
        call()
    return caught.value.code


def _copy_checkout(tmp_path):
    """The parts of the checkout the checks read, so a test can break them."""
    root = tmp_path / "checkout"
    for part in (".claude-plugin", os.path.join("plugins", "claude"), os.path.join("console", "mcp_skills")):
        shutil.copytree(os.path.join(REPO_ROOT, part), str(root / part))
    return str(root)


def _result(report, rule):
    return next(row for row in report["results"] if row["id"] == rule)["result"]


# --- Package ----------------------------------------------------------------

def test_shipped_plugin_passes_every_rule_without_the_cli():
    report = engine.check(REPO_ROOT, use_cli=False)
    assert report["ok"], [row for row in report["results"] if row["result"] == "fail"]
    assert "warn" not in report["summary"], report["results"]


def test_generated_skills_match_their_source():
    assert engine.skill_drift(REPO_ROOT) == []


def test_every_catalog_rule_has_a_check_and_a_source():
    data = engine.catalog()
    ids = [row["id"] for row in data["requirements"]]
    assert len(ids) == len(set(ids))
    for row in data["requirements"]:
        assert row["source"] in data["sources"], row["id"]
        assert row["check"] == "manual" or hasattr(engine, "_check_" + row["check"]), row["id"]


def _edit_json(path, change):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    change(data)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


MANIFEST = ("plugins", "claude", "os-lab", ".claude-plugin", "plugin.json")
MARKET = (".claude-plugin", "marketplace.json")
MCP = ("plugins", "claude", "os-lab", ".mcp.json")
HOOKS = ("plugins", "claude", "os-lab", "hooks", "hooks.json")


@pytest.mark.parametrize("rule, parts, change", [
    ("manifest.name", MANIFEST, lambda d: d.update(name="os lab")),
    ("manifest.reserved-name", MANIFEST, lambda d: d.update(name="claude-os-lab")),
    ("manifest.metadata", MANIFEST, lambda d: d.pop("license")),
    ("manifest.paths", MANIFEST, lambda d: d.update(skills="../skills")),
    ("manifest.keys", MANIFEST, lambda d: d.update(surprise=1)),
    ("config.options", MANIFEST, lambda d: d["userConfig"]["repo_path"].pop("title")),
    ("config.references", MCP, lambda d: d["mcpServers"]["os-lab"]["env"].update(X="${user_config.nope}")),
    ("marketplace.required", MARKET, lambda d: d.pop("owner")),
    ("marketplace.reserved-name", MARKET, lambda d: d.update(name="claude-plugins-official")),
    ("marketplace.entry", MARKET, lambda d: d["plugins"][0].update(source="./../x")),
    ("marketplace.version", MARKET, lambda d: d["plugins"][0].update(version="9.0.0")),
    ("mcp.config", MCP, lambda d: d["mcpServers"]["os-lab"].update(args=["launcher.py"])),
    ("hooks.shape", HOOKS, lambda d: d["hooks"].update(Nope=[{"hooks": [{"type": "command", "command": "x"}]}])),
    ("hooks.timeout", HOOKS, lambda d: d["hooks"]["SessionStart"][0]["hooks"][0].pop("timeout")),
])
def test_a_broken_package_is_reported(tmp_path, rule, parts, change):
    root = _copy_checkout(tmp_path)
    assert _result(engine.check(root, use_cli=False), rule) == "pass"
    _edit_json(os.path.join(root, *parts), change)
    broken = engine.check(root, use_cli=False)
    row = next(row for row in broken["results"] if row["id"] == rule)
    assert row["result"] in ("fail", "warn"), row
    assert row["fix"]


@pytest.mark.parametrize("rule, relative, text", [
    ("skills.frontmatter", "skills/setup/SKILL.md", "# no frontmatter\n"),
    ("skills.fields", "skills/setup/SKILL.md", "---\nname: setup\ndescription: d\nsurprise: 1\n---\n"),
    ("skills.description", "skills/setup/SKILL.md", "---\nname: setup\n---\n"),
    ("skills.length", "skills/setup/SKILL.md", "---\nname: setup\ndescription: d\n---\n" + "x\n" * 600),
    ("skills.generated", "skills/macos/SKILL.md", "---\nname: macos\ndescription: edited\n---\n"),
    ("distribution.readme", "README.md", "short\n"),
    ("component.bin", "bin/tool", "x\n"),
])
def test_a_broken_file_is_reported(tmp_path, rule, relative, text):
    root = _copy_checkout(tmp_path)
    _write(os.path.join(root, "plugins", "claude", "os-lab", relative), text)
    assert _result(engine.check(root, use_cli=False), rule) in ("fail", "warn")


def test_a_symlink_out_of_the_plugin_is_reported(tmp_path):
    if os.name == "nt":
        pytest.skip("symlinks need extra rights on Windows")
    root = _copy_checkout(tmp_path)
    os.symlink(str(tmp_path), os.path.join(engine.plugin_dir(root), "outside"))
    assert _result(engine.check(root, use_cli=False), "cache.contained") == "fail"


@pytest.mark.parametrize("rule, tool", [
    ("mcp.tool-name", {"name": "x" * 120, "description": "d", "annotations": {"readOnlyHint": True}}),
    ("mcp.schema-names", {"name": "a", "inputSchema": {"properties": {"bad name": {}}}}),
    ("mcp.description-length", {"name": "a", "description": "d" * 5000}),
    ("mcp.result-size", {"name": "a", "_meta": {"anthropic/maxResultSizeChars": 600000}}),
    ("mcp.annotations", {"name": "a", "annotations": {}}),
])
def test_a_broken_tool_is_reported(monkeypatch, rule, tool):
    monkeypatch.setattr(mcp_server, "TOOLS", mcp_server.TOOLS + [tool])
    assert _result(engine.check(REPO_ROOT, area="mcp", use_cli=False), rule) in ("fail", "warn")


def test_requirements_filter_and_refuse_unknown_values():
    rows = engine.requirements(area="mcp")["requirements"]
    assert rows and all(row["area"] == "mcp" and row["url"].startswith("https://") for row in rows)
    assert _code(lambda: engine.requirements(area="nope")) == "INVALID_ARGS"


def test_desktop_bundle_is_reproducible_and_requires_the_checkout():
    data = engine.build_mcpb(REPO_ROOT)
    assert data == engine.build_mcpb(REPO_ROOT)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == ["manifest.json", "server/launcher.py"]
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["user_config"]["repo_path"]["required"] is True
    assert manifest["server"]["entry_point"] == "server/launcher.py"


# --- Launcher and session check ---------------------------------------------

def test_launcher_resolution_order(tmp_path):
    here = os.path.join(PLUGIN, "launcher.py")
    assert launcher.find_checkout({"OSLAB_PLUGIN_REPO": REPO_ROOT}, here)[:2] == (REPO_ROOT, "repo_path")
    assert launcher.find_checkout({"OSLAB_ROOT": REPO_ROOT}, here)[1] == "OSLAB_ROOT"
    assert launcher.find_checkout({"OSLAB_PLUGIN_REPO": ""}, here)[:2] == (REPO_ROOT, "marketplace folder")
    # A configured but wrong path is not replaced by another checkout.
    root, source, problem = launcher.find_checkout({"OSLAB_PLUGIN_REPO": str(tmp_path)}, here)
    assert root is None and source == "repo_path" and str(tmp_path) in problem


def test_launcher_ignores_a_server_file_outside_a_marketplace(tmp_path):
    _write(str(tmp_path / "console" / "mcp_server.py"), "raise SystemExit(9)\n")
    assert launcher.find_checkout({}, str(tmp_path / "cache" / "launcher.py"))[0] is None


def _speak(env, *messages):
    lines = "".join(json.dumps(message) + "\n" for message in messages)
    done = subprocess.run([sys.executable, os.path.join(PLUGIN, "launcher.py")], input=lines,
                          capture_output=True, text=True, timeout=60, env=dict(os.environ, **env))
    return [json.loads(line) for line in done.stdout.splitlines()]


def test_launcher_runs_the_server_and_explains_a_missing_checkout(tmp_path):
    hello = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    replies = _speak({"OSLAB_PLUGIN_REPO": REPO_ROOT}, hello, listing)
    assert replies[0]["result"]["instructions"]
    assert "plugin_apply" in {tool["name"] for tool in replies[1]["result"]["tools"]}
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "plugin_doctor"}}
    replies = _speak({"OSLAB_PLUGIN_REPO": str(tmp_path)}, hello, {"method": "notifications/initialized"},
                     listing, call)
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert [tool["name"] for tool in replies[1]["result"]["tools"]] == ["plugin_doctor", "plugin_status"]
    assert "repo_path" in json.loads(replies[2]["result"]["content"][0]["text"])["fix"]


def test_session_check_is_silent_when_healthy(tmp_path, monkeypatch):
    monkeypatch.setenv("OSLAB_CLAUDE_DESKTOP_DIR", str(tmp_path / "desktop"))
    assert session_check.message({"OSLAB_PLUGIN_REPO": REPO_ROOT}) == ""
    assert "/os-lab:doctor" in session_check.message({"CLAUDE_PLUGIN_OPTION_REPO_PATH": str(tmp_path)})


# --- Status, plan, apply, verify ----------------------------------------------

def test_without_claude_code_status_says_so_and_plans_refuse(monkeypatch, tmp_path):
    monkeypatch.setenv("OSLAB_CLAUDE_BIN", str(tmp_path / "absent"))
    assert engine.status(REPO_ROOT)["cli"] is None
    assert engine.doctor(REPO_ROOT)["ready"] is False
    assert _code(lambda: engine.plan(REPO_ROOT, "install")) == "CLI_MISSING"


def test_an_old_cli_and_unreadable_output_are_refused(fake):
    fake.write(version="2.1.200")
    assert _code(lambda: engine.plan(REPO_ROOT, "install")) == "CLI_OLD"
    fake.write(version="2.1.332", garbage=True)
    assert _code(lambda: engine.status(REPO_ROOT)) == "CLI_OUTPUT"


def test_preview_changes_nothing_then_install_verify_uninstall(fake):
    preview = engine.plan(REPO_ROOT, "install")
    assert fake.changes() == []
    assert any("marketplace add" in command for command in preview["commands"])
    result = engine.apply(REPO_ROOT, preview["token"], True)
    assert result["ok"], result
    assert [call[1] for call in fake.changes()] == ["marketplace", "install"]
    status = engine.status(REPO_ROOT)
    assert status["marketplace"]["thisCheckout"] and "mcpServers" not in status["installed"][0]
    assert engine.verify(REPO_ROOT)["ok"] is True
    removal = engine.plan(REPO_ROOT, "uninstall")
    assert removal["terminalOnly"]
    assert _code(lambda: engine.apply(REPO_ROOT, removal["token"], True)) == "TERMINAL_ONLY"
    removal = engine.plan(REPO_ROOT, "uninstall")
    assert engine.apply(REPO_ROOT, removal["token"], True, audience="terminal")["ok"]
    assert engine.verify(REPO_ROOT)["ok"] is False


def test_verify_fails_for_a_wrong_saved_checkout(fake, tmp_path):
    assert engine.apply(REPO_ROOT, engine.plan(REPO_ROOT, "install")["token"], True)["ok"]
    fake.write(repo_path=str(tmp_path))
    report = engine.verify(REPO_ROOT)
    assert report["ok"] is False and "plugin_apply" in report["missing"]


def test_tokens_need_confirmation_and_work_once(fake):
    token = engine.plan(REPO_ROOT, "install")["token"]
    assert _code(lambda: engine.apply(REPO_ROOT, token, False)) == "CONFIRM_REQUIRED"
    assert engine.apply(REPO_ROOT, token, True)["ok"]
    assert _code(lambda: engine.apply(REPO_ROOT, token, True)) == "STALE_PLAN"
    assert _code(lambda: engine.apply(REPO_ROOT, "made-up", True)) == "STALE_PLAN"


def test_a_changed_state_or_expired_plan_is_refused(fake, monkeypatch):
    token = engine.plan(REPO_ROOT, "install")["token"]
    fake.write(markets=[{"name": "os-lab", "source": "directory", "path": REPO_ROOT}])
    assert _code(lambda: engine.apply(REPO_ROOT, token, True)) == "STALE_PLAN"
    token = engine.plan(REPO_ROOT, "install")["token"]
    later = engine.time.time() + engine.PLAN_SECONDS + 1
    monkeypatch.setattr(engine.time, "time", lambda: later)
    assert _code(lambda: engine.apply(REPO_ROOT, token, True)) == "STALE_PLAN"
    assert fake.changes() == []


def test_a_failed_step_stops_the_plan(fake):
    fake.write(fail="add")
    result = engine.apply(REPO_ROOT, engine.plan(REPO_ROOT, "install")["token"], True)
    assert result["ok"] is False and result["notRun"] == 1
    assert result["steps"][0]["message"] == "boom"


def test_another_marketplace_with_the_name_is_a_conflict_and_is_never_started(fake, tmp_path):
    fake.write(markets=[{"name": "os-lab", "source": "github", "repo": "someone/else"}],
               installed=[{"id": "os-lab@os-lab", "scope": "user", "enabled": True, "installPath": str(tmp_path)}])
    assert _code(lambda: engine.plan(REPO_ROOT, "install")) == "CONFLICT"
    assert "not this checkout" in engine.verify(REPO_ROOT)["reason"]


@pytest.mark.parametrize("action, scope, name", [
    ("nope", "user", None), ("install", "managed", None),
    ("remove-duplicate", "user", None), ("install", "user", "os-lab"),
])
def test_plan_arguments_are_checked(fake, action, scope, name):
    assert _code(lambda: engine.plan(REPO_ROOT, action, scope, name)) == "INVALID_ARGS"


def test_changes_need_an_installed_plugin(fake):
    for action in ("update", "configure", "enable", "disable", "uninstall"):
        assert _code(lambda: engine.plan(REPO_ROOT, action)) == "NOT_INSTALLED"


def test_duplicates_are_reported_without_secrets(fake, tmp_path):
    entry = {"command": "python3", "args": ["/x/console/mcp_server.py"], "env": {"TOKEN": "s3cret"}}
    _write(str(tmp_path / "config" / ".claude.json"),
           json.dumps({"mcpServers": {"mine": entry, "os-lab-macos": {}, "other": {"args": ["x"]}}}))
    found = engine.duplicates(REPO_ROOT)
    assert {row["name"] for row in found if row["scope"] == "user"} == {"mine", "os-lab-macos"}
    assert "s3cret" not in json.dumps(found)
    preview = engine.plan(REPO_ROOT, "install")
    assert any("os-lab-macos" in warning for warning in preview["warnings"])
    removal = engine.plan(REPO_ROOT, "remove-duplicate", "user", "os-lab-macos")
    assert removal["commands"] == ["claude mcp remove os-lab-macos --scope user"]
    assert _code(lambda: engine.apply(REPO_ROOT, removal["token"], True)) == "TERMINAL_ONLY"


# --- MCP surface -------------------------------------------------------------

def _rpc(method, params=None):
    return mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def _tool(name, arguments=None):
    result = _rpc("tools/call", {"name": name, "arguments": arguments or {}})["result"]
    return result["isError"], json.loads(result["content"][0]["text"])


def test_tools_run_through_the_server(fake):
    assert _tool("plugin_requirements", {"area": "skills"})[1]["count"] >= 4
    error, preview = _tool("plugin_plan", {"action": "install"})
    assert not error
    error, refused = _tool("plugin_apply", {"token": preview["token"], "confirm": False})
    assert error and refused["code"] == "CONFIRM_REQUIRED"
    error, applied = _tool("plugin_apply", {"token": preview["token"], "confirm": True})
    assert not error and applied["ok"]
    assert _tool("plugin_status")[1]["installed"]
    error, refused = _tool("plugin_plan", {"action": "install", "command": "rm"})
    assert error and refused["code"] == "INVALID_ARGS"


def test_plugin_tools_are_refused_inside_macos_task():
    result = mcp_server.run_task({"steps": [{"tool": "plugin_apply", "args": {}}]})
    assert result["failures"] == 1 and "not available" in result["transcript"][0]["error"]


def test_resource_prompt_instructions_and_annotations():
    assert any(r["uri"] == "oslab://plugin/requirements" for r in _rpc("resources/list")["result"]["resources"])
    body = _rpc("resources/read", {"uri": "oslab://plugin/requirements"})["result"]["contents"][0]
    assert json.loads(body["text"])["requirements"]
    prompt = _rpc("prompts/get", {"name": "claude_plugin_setup_flow", "arguments": {"action": "update"}})
    assert "plugin_plan" in prompt["result"]["messages"][0]["content"]["text"]
    assert 0 < len(_rpc("initialize")["result"]["instructions"]) <= 4096
    tools = {tool["name"]: tool for tool in _rpc("tools/list")["result"]["tools"]}
    assert tools["plugin_apply"]["annotations"]["readOnlyHint"] is False
    assert tools["cleanup_catalog"]["_meta"]["anthropic/maxResultSizeChars"] == 200000
    assert tools["cleanup_catalog"]["_meta"]["ui"]


# --- Claude Desktop and updates ------------------------------------------------

@pytest.fixture
def mac(tmp_path, monkeypatch):
    """A fake macOS with Claude Desktop and an empty settings folder."""
    app = tmp_path / "Claude.app" / "Contents"
    app.mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps(
        {"CFBundleIdentifier": desktop.DESKTOP_ID, "CFBundleShortVersionString": "1.2.3"}))
    monkeypatch.setattr(desktop, "_platform", lambda: "darwin")
    monkeypatch.setenv("OSLAB_CLAUDE_APP", str(tmp_path / "Claude.app"))
    monkeypatch.setenv("OSLAB_CLAUDE_DESKTOP_DIR", str(tmp_path / "desktop"))
    monkeypatch.setattr(desktop, "published_version", lambda timeout=5: pytest.fail("network used"))
    return tmp_path / "desktop"


def _extension(base, version):
    _write(str(base / "Claude Extensions" / "local.mcpb.os-lab" / "manifest.json"),
           json.dumps({"name": "os-lab", "version": version}))


def test_desktop_extension_state_and_duplicates(mac):
    assert desktop.status(REPO_ROOT)["app"]["version"] == "1.2.3"
    assert desktop.extension_info(REPO_ROOT)["installed"] is False
    _extension(mac, "0.0.9")
    _write(str(mac / "claude_desktop_config.json"),
           json.dumps({"mcpServers": {"os-lab-macos": {"env": {"T": "s3cret"}}, "other": {}}}))
    info = desktop.extension_info(REPO_ROOT)
    assert info["version"] == "0.0.9" and info["updateAvailable"]
    assert info["duplicates"] == ["os-lab-macos"] and "s3cret" not in json.dumps(info)
    _extension(mac, "99.0.0")
    assert desktop.extension_info(REPO_ROOT)["updateAvailable"] is False


def test_extension_install_builds_the_bundle_and_opens_it(mac, monkeypatch, tmp_path):
    target = tmp_path / "out" / "os-lab.mcpb"
    ran = []
    monkeypatch.setattr(desktop, "bundle_path", lambda root: str(target))
    monkeypatch.setattr(engine, "_run", lambda argv, cwd, **kw: ran.append(argv) or
                        {"code": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(engine, "audit", lambda *args: None)
    preview = engine.plan(REPO_ROOT, "extension-install")
    assert not target.exists() and not ran
    assert preview["commands"][0].startswith("open -a ")
    result = engine.apply(REPO_ROOT, preview["token"], True)
    assert result["ok"] and "Confirm the install" in result["next"]
    assert target.read_bytes() == engine.build_mcpb(REPO_ROOT)
    assert ran == [["open", "-a", str(tmp_path / "Claude.app"), str(target)]]


def test_extension_install_without_desktop_or_without_a_command(mac, monkeypatch):
    monkeypatch.setenv("OSLAB_CLAUDE_APP", "")
    assert _code(lambda: engine.plan(REPO_ROOT, "extension-install")) == "NOT_INSTALLED"
    assert _code(lambda: engine.plan(REPO_ROOT, "extension-install", "project")) == "INVALID_ARGS"
    monkeypatch.setattr(desktop, "_platform", lambda: "linux")
    monkeypatch.setattr(engine, "audit", lambda *args: None)
    preview = engine.plan(REPO_ROOT, "extension-install")
    assert preview["commands"] == [] and preview["manual"]
    assert _code(lambda: engine.apply(REPO_ROOT, preview["token"], True)) == "MANUAL"


def test_updates_compare_both_apps_and_the_published_version(fake, mac, monkeypatch):
    fake.write(installed=[{"id": "os-lab@os-lab", "version": "0.0.1", "scope": "user", "enabled": True}])
    _extension(mac, "0.0.9")
    offline = desktop.updates(REPO_ROOT)
    assert offline["updatesAvailable"] == ["claude-code", "claude-desktop"] and "published" not in offline
    monkeypatch.setattr(desktop, "published_version", lambda timeout=5: ("99.0.0", None))
    assert desktop.updates(REPO_ROOT, online=True)["updatesAvailable"][0] == "checkout"
    monkeypatch.setattr(desktop, "published_version", lambda timeout=5: (None, "offline"))
    report = desktop.updates(REPO_ROOT, online=True)
    assert report["published"] == {"version": None, "updateAvailable": None, "note": "offline"}


def test_session_check_asks_once_a_day_and_only_when_switched_on(mac, monkeypatch, tmp_path):
    env = {"OSLAB_PLUGIN_REPO": REPO_ROOT, "CLAUDE_PLUGIN_DATA": str(tmp_path / "data")}
    assert session_check.message(env) == ""  # off: the network guard in `mac` would fail
    asked = []
    monkeypatch.setattr(desktop, "published_version",
                        lambda timeout=5: asked.append(1) or ("99.0.0", None))
    env["CLAUDE_PLUGIN_OPTION_UPDATE_CHECK"] = "true"
    assert "99.0.0 is published" in session_check.message(env)
    assert "99.0.0" in session_check.message(env) and len(asked) == 1
    _extension(mac, "0.0.9")
    assert "extension-install" in session_check.message(env)
