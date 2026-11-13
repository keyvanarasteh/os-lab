"""Unit and integration tests for PENT-06: frida-trace Auto-Tracer & Call-Map Builder."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.join(REPO_ROOT, "console") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "console"))

import oslab  # noqa: E402
from hooks import trace_runner as hooks_trace_runner  # noqa: E402
from scripts import trace_runner  # noqa: E402


def test_hooks_and_scripts_entry_points_expose_same_api():
    for attr in trace_runner.__all__ if hasattr(trace_runner, "__all__") else hooks_trace_runner.__all__:
        assert hasattr(trace_runner, attr)
        assert hasattr(hooks_trace_runner, attr)
        assert getattr(trace_runner, attr) is getattr(hooks_trace_runner, attr)


def test_validate_target_accepts_lab_targets_and_rejects_unsafe_inputs():
    assert trace_runner.validate_target("com.testlab.vulnerable") == "com.testlab.vulnerable"
    assert trace_runner.validate_target("hedef") == "hedef"
    assert trace_runner.validate_target("4242") == "4242"

    for forbidden in ("", "   ", "-f", "--help", "init", "systemd", "sshd", "launchd", "lsass.exe", "0", "1", "../hedef", "app;id", "app|cat"):
        with pytest.raises(trace_runner.TraceScopeError):
            trace_runner.validate_target(forbidden)


def test_validate_symbol_glob_accepts_valid_globs_and_rejects_injection():
    assert trace_runner.validate_symbol_glob("*auth*") == "*auth*"
    assert trace_runner.validate_symbol_glob("libnative.so!check_*") == "libnative.so!check_*"
    assert trace_runner.validate_symbol_glob("-[NSURLSession *]") == "-[NSURLSession *]"
    assert trace_runner.validate_symbol_glob("+[CryptoUtils *]") == "+[CryptoUtils *]"

    for bad in ("", "  ", "-i", "--version", "*auth*;rm -rf /", "foo`id`", "../secret", "a\\b"):
        with pytest.raises(trace_runner.TraceScopeError):
            trace_runner.validate_symbol_glob(bad)


def test_build_frida_trace_cmd_constructs_typed_argument_list():
    cmd = trace_runner.build_frida_trace_cmd(
        target="com.testlab.fixture",
        include_globs=["*auth*", "check_*"],
        exclude_globs=["*log*"],
        module_globs=["libnative.so"],
        java_globs=["com.testlab.*!*"],
        objc_globs=["-[NSURLSession *]"],
        transport="usb",
        device_id="emulator-5554",
        spawn=True,
        frida_trace_bin="/usr/bin/frida-trace",
    )
    assert cmd == [
        "/usr/bin/frida-trace",
        "-U",
        "-D",
        "emulator-5554",
        "-i",
        "*auth*",
        "-i",
        "check_*",
        "-I",
        "libnative.so",
        "-j",
        "com.testlab.*!*",
        "-m",
        "-[NSURLSession *]",
        "-x",
        "*log*",
        "-f",
        "com.testlab.fixture",
    ]

    pid_cmd = trace_runner.build_frida_trace_cmd(
        target="31337",
        include_globs=["open*"],
        transport="remote",
        host="127.0.0.1:27042",
        spawn=False,
        frida_trace_bin="frida-trace",
    )
    assert pid_cmd == ["frida-trace", "-H", "127.0.0.1:27042", "-i", "open*", "-p", "31337"]


def test_parse_args_string_snapshots_diverse_argument_types():
    raw = 'user="student_lab", ptr=0x7ff90100 ("Bearer xyz"), count=0x10, retries=3, active=true, meta={"role": "lab", "tags": [1, 2]}, empty=null'
    snaps = trace_runner.parse_args_string(raw)
    assert len(snaps) == 7

    assert snaps[0] == {
        "index": 0,
        "name": "user",
        "value": "student_lab",
        "type": "string",
        "raw": 'user="student_lab"',
    }
    assert snaps[1] == {
        "index": 1,
        "name": "ptr",
        "value": "0x7ff90100",
        "type": "pointer",
        "raw": 'ptr=0x7ff90100 ("Bearer xyz")',
        "annotation": "Bearer xyz",
    }
    assert snaps[2]["name"] == "count" and snaps[2]["value"] == "0x10" and snaps[2]["type"] == "int"
    assert snaps[3]["name"] == "retries" and snaps[3]["value"] == 3 and snaps[3]["type"] == "int"
    assert snaps[4]["name"] == "active" and snaps[4]["value"] is True and snaps[4]["type"] == "bool"
    assert snaps[5]["name"] == "meta" and snaps[5]["value"] == {"role": "lab", "tags": [1, 2]} and snaps[5]["type"] == "json"
    assert snaps[6]["name"] == "empty" and snaps[6]["value"] is None and snaps[6]["type"] == "null"


def test_generate_and_instrument_handlers_dir(tmp_path: Path):
    handlers = tmp_path / "__handlers__"
    (handlers / "libauth.so").mkdir(parents=True)
    stub_file = handlers / "libauth.so" / "check_password.js"
    stub_file.write_text("defineHandler({ onEnter(log, args, state) {} });\n", encoding="utf-8")

    updated = trace_runner.instrument_handlers_dir(handlers, arg_count=3)
    assert len(updated) == 1
    content = stub_file.read_text(encoding="utf-8")
    assert "defineHandler" in content
    assert "[OSLAB_TRACE]" in content
    assert '"libauth.so!check_password"' in content
    assert "for (let i = 0; i < 3; i++)" in content


def test_build_call_map_from_standard_frida_trace_fixture():
    extra_log = (
        trace_runner.SAMPLE_LAB_TRACE_LOG
        + '\nunused_helper: Auto-generated handler at "/tmp/__handlers__/libauth.so/unused_helper.js"\n'
    )
    cmap = trace_runner.build_call_map(
        target="com.testlab.vulnerable",
        patterns=["*verify*", "check_*", "strcmp", "derive_*"],
        raw_output=extra_log,
        action="login_flow",
        transport="usb",
        timestamp="2026-11-12T20:00:00+00:00",
    )

    assert cmap["schema_version"] == 1
    assert cmap["task_id"] == "PENT-06"
    assert cmap["target"] == "com.testlab.vulnerable"
    assert cmap["action"] == "login_flow"
    assert cmap["summary"]["total_discovered"] == 5
    assert cmap["summary"]["total_calls"] == 7
    assert cmap["summary"]["unique_functions_called"] == 4
    assert cmap["summary"]["uncalled_functions"] == ["libauth.so!unused_helper"]
    assert cmap["summary"]["max_depth"] == 2
    assert cmap["summary"]["threads_observed"] == ["0x1a2b"]
    assert cmap["summary"]["entry_points"] == ["libauth.so!Java_com_testlab_AuthBridge_verifyCredentials"]

    funcs = cmap["functions"]
    verify_fn = funcs["libauth.so!Java_com_testlab_AuthBridge_verifyCredentials"]
    assert verify_fn["call_count"] == 2
    assert verify_fn["callees"] == ["libauth.so!check_password", "libcrypto.so!derive_session_token"]
    assert verify_fn["return_values"] == ["0x0 (0)", "0x1 (1)"]

    check_fn = funcs["libauth.so!check_password"]
    assert check_fn["call_count"] == 2
    assert check_fn["callers"] == ["libauth.so!Java_com_testlab_AuthBridge_verifyCredentials"]
    assert check_fn["callees"] == ["libc.so!strcmp"]
    assert check_fn["argument_snapshots"][0]["args"][0]["value"] == "deneme123"
    assert check_fn["argument_snapshots"][1]["args"][0]["value"] == "gizli_parola"

    edges = {(e["caller"], e["callee"]): e["count"] for e in cmap["call_graph"]}
    assert edges[("libauth.so!Java_com_testlab_AuthBridge_verifyCredentials", "libauth.so!check_password")] == 2
    assert edges[("libauth.so!check_password", "libc.so!strcmp")] == 2
    assert edges[("libauth.so!Java_com_testlab_AuthBridge_verifyCredentials", "libcrypto.so!derive_session_token")] == 1

    # Verify parent/child links and durations on calls
    first_root = cmap["calls"][0]
    assert first_root["call_id"] == 1
    assert first_root["depth"] == 0
    assert first_root["parent_call_id"] is None
    assert first_root["children_call_ids"] == [2]
    assert first_root["duration_ms"] == 10


def test_parse_oslab_structured_json_and_objc_trace_lines():
    structured_log = """
   10 ms [OSLAB_TRACE] {"event": "enter", "module": "hedef", "symbol": "main_loop", "qualified_name": "hedef!main_loop", "thread_id": "0x99", "depth": 0, "args": [{"index": 0, "name": "arg0", "value": "start", "type": "string"}]}
   12 ms [OSLAB_TRACE] {"event": "enter", "module": "hedef", "symbol": "check_pin", "qualified_name": "hedef!check_pin", "thread_id": "0x99", "depth": 1, "args": [{"index": 0, "name": "pin", "value": 1234, "type": "int"}]}
   15 ms [OSLAB_TRACE] {"event": "leave", "module": "hedef", "symbol": "check_pin", "qualified_name": "hedef!check_pin", "thread_id": "0x99", "depth": 1, "retval": "0x1"}
   18 ms [OSLAB_TRACE] {"event": "leave", "module": "hedef", "symbol": "main_loop", "qualified_name": "hedef!main_loop", "thread_id": "0x99", "depth": 0, "retval": "0x0"}
   25 ms [0x99]  -[NSURLSession dataTaskWithRequest:0x600001 completionHandler:0x700002] => 0x800003
"""
    cmap = trace_runner.build_call_map("hedef", ["*"], structured_log, transport="local")
    assert cmap["summary"]["total_calls"] == 3
    assert cmap["calls"][0]["children_call_ids"] == [2]
    assert cmap["calls"][1]["caller"] == "hedef!main_loop"
    assert cmap["calls"][1]["retval"] == "0x1"
    assert cmap["calls"][1]["duration_ms"] == 3
    assert cmap["calls"][2]["symbol"] == "-[NSURLSession dataTaskWithRequest:completionHandler:]"
    assert cmap["calls"][2]["retval"] == "0x800003"


def test_run_trace_session_writes_json_and_annotated_session_log(tmp_path: Path):
    out_json = tmp_path / "artifacts" / "call-map.json"
    session_md = tmp_path / "artifacts" / "trace-session.md"

    cmap = trace_runner.run_trace_session(
        target="com.testlab.vulnerable",
        include_globs=["*auth*", "check_*"],
        simulate=True,
        action="verify_credentials",
        out_json=out_json,
        session_log=session_md,
        timestamp="2026-11-12T20:00:00+00:00",
    )

    assert out_json.is_file()
    assert session_md.is_file()

    loaded = json.loads(out_json.read_text(encoding="utf-8"))
    assert loaded["task_id"] == "PENT-06"
    assert loaded["summary"]["total_calls"] == cmap["summary"]["total_calls"] == 7

    md_text = session_md.read_text(encoding="utf-8")
    assert "os-lab frida-trace Annotated Session Log (PENT-06)" in md_text
    assert "libauth.so!check_password" in md_text
    assert "Caller -> Callee Graph Edges" in md_text


def test_run_trace_session_with_mocked_frida_trace_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    handlers_dir = tmp_path / "__handlers__"
    lib_dir = handlers_dir / "libauth.so"
    lib_dir.mkdir(parents=True)
    handler_js = lib_dir / "check_password.js"
    handler_js.write_text("// initial stub\n", encoding="utf-8")

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.args = cmd
            self.returncode = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def poll(self):
            return self.returncode

        def communicate(self, input=None, timeout=None):
            return (trace_runner.SAMPLE_LAB_TRACE_LOG, "")

        def kill(self):
            pass

    monkeypatch.setattr(trace_runner, "find_frida_trace", lambda: "/usr/local/bin/frida-trace")
    monkeypatch.setattr(subprocess, "Popen", FakeProc)

    cmap = trace_runner.run_trace_session(
        target="com.testlab.vulnerable",
        include_globs=["*auth*"],
        handlers_dir=handlers_dir,
        simulate=False,
    )
    assert cmap["mode"] == "live"
    assert cmap["summary"]["total_calls"] == 7
    assert "defineHandler" in handler_js.read_text(encoding="utf-8")


def test_cli_simulate_and_scope_guard_exit_codes(tmp_path: Path):
    out_json = tmp_path / "cli-map.json"
    rc = hooks_trace_runner.main([
        "--target",
        "com.testlab.vulnerable",
        "-i",
        "check_*",
        "--simulate",
        "--out",
        str(out_json),
    ])
    assert rc == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["target"] == "com.testlab.vulnerable"

    # Protected system target returns exit code 2
    rc_bad = hooks_trace_runner.main(["--target", "sshd", "--simulate"])
    assert rc_bad == 2

    # Subprocess invocation of hooks/trace_runner.py --emit-handler
    hook_script = Path(REPO_ROOT) / "android-lab" / "lab" / "hooks" / "trace_runner.py"
    proc = subprocess.run(
        [sys.executable, str(hook_script), "--emit-handler", "libauth.so!check_password"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "defineHandler" in proc.stdout
    assert "libauth.so!check_password" in proc.stdout


def test_oslab_console_plan_supports_android_trace_action():
    host = {
        "os": "linux",
        "arch": "x86_64",
        "root": REPO_ROOT,
        "kvm": {"present": True, "usable": True},
        "wsl": {"guest": False, "distributions": []},
        "runtime": "docker",
        "xcode": None,
        "tools": [{"id": t, "label": label, "found": True, "path": f"/usr/bin/{t}"} for t, label in oslab.TOOLS],
    }
    status = oslab.lab_status("android", host)
    assert any(a["id"] == "trace" for a in status["actions"])

    plan = oslab.plan(
        REPO_ROOT,
        {"lab": "android", "action": "trace", "target": "com.testlab.vulnerable", "glob": "*auth*"},
        host,
    )
    assert plan["program"] == "bash"
    assert plan["args"][1:] == ["android", "trace", "--target", "com.testlab.vulnerable", "--include", "*auth*"]

    for invalid_req in (
        {"lab": "android", "action": "trace", "target": "sshd"},
        {"lab": "android", "action": "trace", "target": "../bad"},
        {"lab": "android", "action": "trace", "glob": "--help"},
        {"lab": "android", "action": "start", "target": "com.testlab.vulnerable"},
        {"lab": "windows", "action": "trace"},
    ):
        with pytest.raises(oslab.PlanError):
            oslab.plan(REPO_ROOT, invalid_req, host)
