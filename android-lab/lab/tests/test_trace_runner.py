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

    for forbidden in (
        "",
        "   ",
        "-f",
        "--help",
        "init",
        "systemd",
        "sshd",
        "launchd",
        "lsass.exe",
        "0",
        "1",
        "00",
        "01",
        "../hedef",
        "app;id",
        "app|cat",
    ):
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
    # Explicit device_id uses -D without competing -U selector
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

    # Specialized traces (e.g. java_globs or objc_globs only) do not inject -i *
    java_only_cmd = trace_runner.build_frida_trace_cmd(
        target="com.testlab.fixture",
        java_globs=["com.testlab.*!*"],
        transport="usb",
        frida_trace_bin="frida-trace",
    )
    assert java_only_cmd == [
        "frida-trace",
        "-U",
        "-j",
        "com.testlab.*!*",
        "-n",
        "com.testlab.fixture",
    ]

    # Default include_globs falls back to "*" only when no other inclusion pattern is supplied
    default_cmd = trace_runner.build_frida_trace_cmd(
        target="com.testlab.fixture",
        transport="usb",
        frida_trace_bin="frida-trace",
    )
    assert default_cmd == ["frida-trace", "-U", "-i", "*", "-n", "com.testlab.fixture"]

    pid_cmd = trace_runner.build_frida_trace_cmd(
        target="31337",
        include_globs=["open*"],
        transport="remote",
        host="127.0.0.1:27042",
        spawn=False,
        frida_trace_bin="frida-trace",
    )
    assert pid_cmd == ["frida-trace", "-H", "127.0.0.1:27042", "-i", "open*", "-p", "31337"]

    # Incompatible device_id + remote transport is rejected
    with pytest.raises(trace_runner.TraceScopeError):
        trace_runner.build_frida_trace_cmd(
            target="com.testlab.fixture",
            device_id="emulator-5554",
            transport="remote",
        )


def test_parse_args_string_snapshots_diverse_argument_types():
    raw = (
        'user="student_lab", ptr=0x7ff90100 ("Bearer xyz"), count=0x10, '
        'retries=3, active=true, meta={"role": "lab", "tags": [1, 2]}, '
        "empty=null, status=0xffffffff (-1), raw_hex=0xdeadbeef"
    )
    snaps = trace_runner.parse_args_string(raw)
    assert len(snaps) == 9

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
    assert snaps[7]["name"] == "status" and snaps[7]["value"] == "0xffffffff" and snaps[7]["type"] == "int"
    # Ambiguous unannotated 8-digit hex value without signature metadata is marked unknown, not pointer
    assert snaps[8]["name"] == "raw_hex" and snaps[8]["value"] == "0xdeadbeef" and snaps[8]["type"] == "unknown"

    # Signature metadata overrides ambiguous hex types
    typed_snaps = trace_runner.parse_args_string("0xdeadbeef, 0x7ff90100", arg_types=["int", "pointer"])
    assert typed_snaps[0]["type"] == "int"
    assert typed_snaps[1]["type"] == "pointer"


def test_generate_and_instrument_handlers_dir(tmp_path: Path):
    handlers = tmp_path / "__handlers__"
    (handlers / "libauth.so").mkdir(parents=True)
    stub_file = handlers / "libauth.so" / "check_password.js"
    stub_file.write_text("defineHandler({ onEnter(log, args, state) {} });\n", encoding="utf-8")

    custom_file = handlers / "libauth.so" / "custom_hook.js"
    custom_code = (
        "defineHandler({\n"
        "  onEnter(log, args, state) {\n"
        "    const customSecret = args[0].readUtf8String();\n"
        "    send({ customSecret });\n"
        "  },\n"
        "  onLeave(log, retval, state) {\n"
        "    retval.replace(1);\n"
        "  }\n"
        "});\n"
    )
    custom_file.write_text(custom_code, encoding="utf-8")

    updated = trace_runner.instrument_handlers_dir(handlers, arg_count=3)
    assert updated == [str(stub_file)]
    content = stub_file.read_text(encoding="utf-8")
    assert "defineHandler" in content
    assert "[OSLAB_TRACE]" in content
    assert '"libauth.so!check_password"' in content
    assert "for (let i = 0; i < 3; i++)" in content
    assert "timestamp_ms: relStartMs" in content
    assert "duration_ms: durMs" in content
    assert "depthMap[tidKey] = currentDepth + 1" in content
    assert 'let argType = sigTypes[i] || "unknown";' in content

    # Custom user-authored handler must be preserved untouched
    assert custom_file.read_text(encoding="utf-8") == custom_code


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

    assert cmap["schema_version"] == "1.0"
    assert cmap["task_id"] == "PENT-06"
    assert cmap["target"] == "com.testlab.vulnerable"
    assert cmap["action"] == "login_flow"
    assert cmap["summary"]["discovered_count"] == 5
    assert cmap["summary"]["total_calls"] == 7
    assert cmap["summary"]["functions_called_count"] == 4
    assert cmap["summary"]["unique_edges"] == 3
    assert cmap["summary"]["uncalled_functions"] == ["libauth.so!unused_helper"]
    assert cmap["summary"]["max_depth"] == 2
    assert cmap["summary"]["threads_observed"] == ["0x1a2b"]
    assert cmap["summary"]["entry_points"] == ["libauth.so!Java_com_testlab_AuthBridge_verifyCredentials"]

    disc_by_name = {d["qualified_name"]: d for d in cmap["discovered_functions"]}
    assert disc_by_name["libauth.so!check_password"]["call_count"] == 2
    assert disc_by_name["libauth.so!unused_helper"]["call_count"] == 0

    funcs = cmap["functions"]
    verify_fn = funcs["libauth.so!Java_com_testlab_AuthBridge_verifyCredentials"]
    assert verify_fn["call_count"] == 2
    assert verify_fn["callees"] == ["libauth.so!check_password", "libcrypto.so!derive_session_token"]
    assert verify_fn["return_values"] == ["0x0 (0)", "0x1 (1)"]

    check_fn = funcs["libauth.so!check_password"]
    assert check_fn["call_count"] == 2
    assert check_fn["callers"] == ["libauth.so!Java_com_testlab_AuthBridge_verifyCredentials"]
    assert check_fn["callees"] == ["libc.so!strcmp"]
    assert check_fn["arg_snapshots"][0]["args"][0]["value"] == "deneme123"
    assert check_fn["arg_snapshots"][1]["args"][0]["value"] == "gizli_parola"

    edges = {(e["caller"], e["callee"]): e["count"] for e in cmap["call_graph"]}
    assert edges[("libauth.so!Java_com_testlab_AuthBridge_verifyCredentials", "libauth.so!check_password")] == 2
    assert edges[("libauth.so!check_password", "libc.so!strcmp")] == 2
    assert edges[("libauth.so!Java_com_testlab_AuthBridge_verifyCredentials", "libcrypto.so!derive_session_token")] == 1

    # Verify parent/child links and durations on call_sequence
    first_root = cmap["call_sequence"][0]
    assert first_root["call_id"] == 1
    assert first_root["depth"] == 0
    assert first_root["parent_call_id"] is None
    assert first_root["children_call_ids"] == [2]
    assert first_root["duration_ms"] == 10

    # Verify redaction mode masks credentials and session tokens
    redacted_map = trace_runner.build_call_map(
        target="com.testlab.vulnerable",
        patterns=["*verify*", "check_*", "strcmp", "derive_*"],
        raw_output=extra_log,
        redact=True,
    )
    redacted_check = redacted_map["functions"]["libauth.so!check_password"]
    assert redacted_check["arg_snapshots"][0]["args"][0]["value"] == "[REDACTED]"
    redacted_token_fn = redacted_map["functions"]["libcrypto.so!derive_session_token"]
    assert redacted_token_fn["return_values"] == ['0x7ff90200 ("[REDACTED]")']


def test_parse_oslab_structured_json_and_objc_trace_lines():
    # Includes structured events without CLI <n> ms prefix (relying on payload timestamp_ms/duration_ms)
    # and an inline-return Objective-C call whose unmeasured duration must be None (not 0)
    structured_log = """
[OSLAB_TRACE] {"event": "enter", "module": "hedef", "symbol": "main_loop", "qualified_name": "hedef!main_loop", "thread_id": "0x99", "depth": 0, "timestamp_ms": 10, "args": [{"index": 0, "name": "arg0", "value": "start", "type": "string"}]}
[OSLAB_TRACE] {"event": "enter", "module": "hedef", "symbol": "check_pin", "qualified_name": "hedef!check_pin", "thread_id": "0x99", "depth": 1, "timestamp_ms": 12, "args": [{"index": 0, "name": "pin", "value": 1234, "type": "int"}]}
[OSLAB_TRACE] {"event": "leave", "module": "hedef", "symbol": "check_pin", "qualified_name": "hedef!check_pin", "thread_id": "0x99", "depth": 1, "timestamp_ms": 15, "duration_ms": 3, "retval": "0x1"}
[OSLAB_TRACE] {"event": "leave", "module": "hedef", "symbol": "main_loop", "qualified_name": "hedef!main_loop", "thread_id": "0x99", "depth": 0, "timestamp_ms": 18, "duration_ms": 8, "retval": "0x0"}
   25 ms [0x99]  -[NSURLSession dataTaskWithRequest:0x600001 completionHandler:0x700002] => 0x800003
"""
    cmap = trace_runner.build_call_map("hedef", ["*"], structured_log, transport="local")
    assert cmap["summary"]["total_calls"] == 3
    seq = cmap["call_sequence"]
    assert seq[0]["children_call_ids"] == [2]
    assert seq[0]["timestamp_ms"] == 10
    assert seq[0]["duration_ms"] == 8
    assert seq[1]["caller"] == "hedef!main_loop"
    assert seq[1]["retval"] == "0x1"
    assert seq[1]["duration_ms"] == 3
    assert seq[2]["symbol"] == "-[NSURLSession dataTaskWithRequest:completionHandler:]"
    assert seq[2]["retval"] == "0x800003"
    assert seq[2]["duration_ms"] is None

    # Enforce call volume cap and report truncation
    capped = trace_runner.build_call_map("hedef", ["*"], structured_log, transport="local", max_calls=2)
    assert capped["summary"]["total_calls"] == 2
    assert capped["summary"]["truncated"] is True


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

    raw_json_text = out_json.read_text(encoding="utf-8")
    loaded = json.loads(raw_json_text)
    assert loaded["task_id"] == "PENT-06"
    assert loaded["schema_version"] == "1.0"
    assert loaded["summary"]["total_calls"] == cmap["summary"]["total_calls"] == 7

    # Sensitive passwords and session tokens must be redacted in written artifacts by default
    assert "deneme123" not in raw_json_text
    assert "gizli_parola" not in raw_json_text
    assert "tok_9f8a7b6c" not in raw_json_text
    assert "[REDACTED]" in raw_json_text

    md_text = session_md.read_text(encoding="utf-8")
    assert "os-lab frida-trace Annotated Session Log (PENT-06)" in md_text
    assert "libauth.so!check_password" in md_text
    assert "Caller -> Callee Graph Edges" in md_text
    assert "deneme123" not in md_text
    assert "gizli_parola" not in md_text
    assert "tok_9f8a7b6c" not in md_text


def test_run_trace_session_with_mocked_frida_trace_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    handlers_dir = tmp_path / "__handlers__"
    lib_dir = handlers_dir / "libauth.so"
    lib_dir.mkdir(parents=True)
    handler_js = lib_dir / "check_password.js"
    handler_js.write_text("// initial stub\n", encoding="utf-8")

    invoked_cmds: list[list[str]] = []
    handler_instrumented_before_spawn: list[bool] = []
    mock_returncode = 0

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = list(cmd)
            self.args = list(cmd)
            self.returncode = mock_returncode
            self.stdout = None
            invoked_cmds.append(list(cmd))
            handler_instrumented_before_spawn.append(
                "[OSLAB_TRACE]" in handler_js.read_text(encoding="utf-8")
            )

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def poll(self):
            return self.returncode

        def communicate(self, input=None, timeout=None):
            if self.returncode != 0:
                return ("Failed to attach to target process", "")
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
    assert handler_instrumented_before_spawn == [True]
    assert invoked_cmds == [[
        "/usr/local/bin/frida-trace",
        "-U",
        "-d",
        str(handlers_dir),
        "-i",
        "*auth*",
        "-n",
        "com.testlab.vulnerable",
    ]]

    # Non-zero exit code from frida-trace raises RuntimeError and does not write artifacts
    mock_returncode = 1
    failed_json = tmp_path / "should-not-exist.json"
    with pytest.raises(RuntimeError, match="frida-trace exited with code 1"):
        trace_runner.run_trace_session(
            target="com.testlab.vulnerable",
            include_globs=["*auth*"],
            out_json=failed_json,
            simulate=False,
        )
    assert not failed_json.exists()


def test_cli_simulate_and_scope_guard_exit_codes(tmp_path: Path):
    out_json = tmp_path / "cli-map.json"
    # Verify CLI accepts Objective-C globs with leading hyphen and spaces (-m "-[NSURLSession *]")
    rc = hooks_trace_runner.main([
        "--target",
        "com.testlab.vulnerable",
        "-m",
        "-[NSURLSession *]",
        "--simulate",
        "--out",
        str(out_json),
    ])
    assert rc == 0
    loaded = json.loads(out_json.read_text(encoding="utf-8"))
    assert loaded["target"] == "com.testlab.vulnerable"
    assert loaded["patterns"] == ["-[NSURLSession *]"]

    # Protected system target returns exit code 2
    rc_bad = hooks_trace_runner.main(["--target", "sshd", "--simulate"])
    assert rc_bad == 2

    # Invalid flag-like glob returns scope exit code 2
    rc_bad_glob = hooks_trace_runner.main(["--target", "com.testlab.vulnerable", "-i", "--bad-flag", "--simulate"])
    assert rc_bad_glob == 2

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
        {"lab": "android", "action": "trace", "target": "com.testlab.vulnerable", "glob": "-[NSURLSession *]"},
        host,
    )
    assert plan["program"] == "bash"
    assert plan["args"][1:] == ["android", "trace", "--target", "com.testlab.vulnerable", "--include", "-[NSURLSession *]"]


    for invalid_req in (
        {"lab": "android", "action": "trace", "target": "sshd"},
        {"lab": "android", "action": "trace", "target": "0"},
        {"lab": "android", "action": "trace", "target": "1"},
        {"lab": "android", "action": "trace", "target": "00"},
        {"lab": "android", "action": "trace", "target": "01"},
        {"lab": "android", "action": "trace", "target": "../bad"},
        {"lab": "android", "action": "trace", "glob": "--help"},
        {"lab": "android", "action": "start", "target": "com.testlab.vulnerable"},
        {"lab": "windows", "action": "trace"},
    ):
        with pytest.raises(oslab.PlanError):
            oslab.plan(REPO_ROOT, invalid_req, host)
