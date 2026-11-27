"""SSL-pinning bypass tests — argv builders are pure; the background session
lifecycle (start/alive/stop) is driven with a fake Popen so nothing is spawned."""
import pytest

import sslpinning_bypass as sb


class FakePopen:
    """Stand-in for subprocess.Popen: records argv, simulates a live process."""

    def __init__(self, argv, **kw):
        self.argv = argv
        self.kw = kw
        self.pid = 4242
        self._rc = None          # None == still running
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        self._rc = -15

    def wait(self, timeout=None):
        return self._rc

    def kill(self):
        self.killed = True
        self._rc = -9


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


def test_frida_fallback_argv_selects_device():
    argv = sb.frida_fallback_argv("com.securebank.mobile", serial="emulator-5554")
    assert argv[0] == "frida"
    assert "-D" in argv and "emulator-5554" in argv   # specific device, not -U
    assert "-f" in argv and "com.securebank.mobile" in argv
    assert argv[argv.index("-l") + 1].endswith("ssl-pinning-universal.js")
    assert "--no-pause" in argv


def test_frida_fallback_argv_usb_when_no_serial():
    argv = sb.frida_fallback_argv("com.securebank.mobile")
    assert "-U" in argv


def test_select_argv_prefers_objection():
    tool, argv = sb.select_argv("com.securebank.mobile", serial="emulator-5554",
                                have=lambda b: b == "objection")
    assert tool == "objection" and argv[0] == "objection"


def test_select_argv_falls_back_to_frida():
    tool, argv = sb.select_argv("com.securebank.mobile", serial="emulator-5554",
                                have=lambda b: b == "frida")
    assert tool == "frida" and argv[0] == "frida"


def test_select_argv_errors_when_nothing_installed():
    with pytest.raises(sb.BypassError):
        sb.select_argv("com.securebank.mobile", have=lambda b: False)


def test_start_bypass_launches_in_background_and_is_scope_checked():
    procs = []

    def fake_popen(argv, **kw):
        p = FakePopen(argv, **kw)
        procs.append(p)
        return p

    proc = sb.start_bypass("com.securebank.mobile", serial="emulator-5554",
                           popen=fake_popen, have=lambda b: b == "objection")
    assert sb.is_alive(proc)                 # background process is running
    assert procs[0].argv[0] == "objection"


def test_start_bypass_refuses_out_of_scope():
    with pytest.raises(sb.scope.ScopeError):
        sb.start_bypass("com.whatsapp", serial="emulator-5554",
                        popen=FakePopen, have=lambda b: True)


def test_stop_bypass_terminates_running_process():
    proc = sb.start_bypass("com.securebank.mobile", serial="emulator-5554",
                           popen=FakePopen, have=lambda b: b == "objection")
    assert sb.is_alive(proc)
    sb.stop_bypass(proc)
    assert proc.terminated
    assert not sb.is_alive(proc)


def test_bypass_session_context_manager_always_stops():
    captured = {}

    def fake_popen(argv, **kw):
        p = FakePopen(argv, **kw)
        captured["proc"] = p
        return p

    with sb.bypass_session("com.securebank.mobile", serial="emulator-5554",
                           popen=fake_popen, have=lambda b: b == "objection") as proc:
        assert sb.is_alive(proc)
    # on exit the session is torn down
    assert captured["proc"].terminated
