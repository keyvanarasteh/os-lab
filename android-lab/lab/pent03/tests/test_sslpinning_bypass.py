"""SSL-pinning bypass tests — argv builders pure; runners use fake subprocess
and a fake ``have`` so nothing is launched."""
import types

import pytest

import sslpinning_bypass as sb


def test_objection_argv_basic():
    argv = sb.objection_argv("com.securebank.mobile", serial="emulator-5554")
    assert argv[:3] == ["objection", "-g", "com.securebank.mobile"]
    assert "-S" in argv and "emulator-5554" in argv
    assert "explore" in argv
    assert "--startup-command" in argv
    assert "android sslpinning disable" in argv


def test_objection_argv_requires_package():
    with pytest.raises(sb.BypassError):
        sb.objection_argv("")


def test_frida_fallback_argv():
    argv = sb.frida_fallback_argv("com.securebank.mobile")
    assert argv[0] == "frida"
    assert "-U" in argv
    assert "-f" in argv and "com.securebank.mobile" in argv
    assert "-l" in argv
    assert "--no-pause" in argv
    assert argv[argv.index("-l") + 1].endswith("ssl-pinning-universal.js")


def _ok_runner(argv, **kw):
    return types.SimpleNamespace(returncode=0)


def test_run_objection_scope_checked_and_runs():
    rc = sb.run_objection("com.securebank.mobile", serial="emulator-5554", runner=_ok_runner)
    assert rc == 0


def test_run_objection_out_of_scope_blocked():
    with pytest.raises(sb.scope.ScopeError):
        sb.run_objection("com.whatsapp", serial="emulator-5554", runner=_ok_runner)


def test_bypass_prefers_objection_when_present():
    seen = {}

    def runner(argv, **kw):
        seen["bin"] = argv[0]
        return types.SimpleNamespace(returncode=0)

    rc = sb.bypass(
        "com.securebank.mobile",
        serial="emulator-5554",
        runner=runner,
        have=lambda b: b == "objection",
    )
    assert rc == 0
    assert seen["bin"] == "objection"


def test_bypass_falls_back_to_frida(tmp_path, monkeypatch):
    # Point the hook at a real file so the fallback's existence check passes.
    hook = tmp_path / "ssl-pinning-universal.js"
    hook.write_text("// hook")
    monkeypatch.setattr(sb, "UNIVERSAL_HOOK", str(hook))

    seen = {}

    def runner(argv, **kw):
        seen["bin"] = argv[0]
        return types.SimpleNamespace(returncode=0)

    rc = sb.bypass(
        "com.securebank.mobile",
        serial="emulator-5554",
        runner=runner,
        have=lambda b: b == "frida",
    )
    assert rc == 0
    assert seen["bin"] == "frida"


def test_bypass_errors_when_nothing_installed():
    with pytest.raises(sb.BypassError):
        sb.bypass(
            "com.securebank.mobile",
            serial="emulator-5554",
            runner=_ok_runner,
            have=lambda b: False,
        )
