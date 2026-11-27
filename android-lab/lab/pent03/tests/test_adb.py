"""adb wrapper tests — argv builders are pure; runners use a fake subprocess."""
import subprocess

import pytest

import adb


def test_adb_argv_with_and_without_serial():
    assert adb.adb_argv(None, "devices") == ["adb", "devices"]
    assert adb.adb_argv("emulator-5554", "shell", "id") == [
        "adb", "-s", "emulator-5554", "shell", "id",
    ]


def test_shell_and_push_argv():
    assert adb.shell_argv("emulator-5554", "getprop") == [
        "adb", "-s", "emulator-5554", "shell", "getprop",
    ]
    assert adb.push_argv("emulator-5554", "/l/x", "/d/x") == [
        "adb", "-s", "emulator-5554", "push", "/l/x", "/d/x",
    ]


def _fake_run(returncode=0, stdout="", stderr=""):
    def runner(argv, **kw):
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
    return runner


def test_run_raises_adberror_on_nonzero(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(1, "", "boom"))
    with pytest.raises(adb.AdbError) as ei:
        adb.run(["adb", "shell", "false"])
    assert "boom" in str(ei.value)


def test_run_ok_returns_completedprocess(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(0, "ok\n"))
    proc = adb.run(["adb", "shell", "true"])
    assert proc.returncode == 0


def test_get_sdk_parses_int(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(0, "33\n"))
    assert adb.get_sdk("emulator-5554") == 33


def test_get_sdk_bad_value_is_zero(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(0, "notanint\n"))
    assert adb.get_sdk("emulator-5554") == 0


def test_is_booted_true_false(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(0, "1\n"))
    assert adb.is_booted("emulator-5554") is True
    monkeypatch.setattr(subprocess, "run", _fake_run(0, "0\n"))
    assert adb.is_booted("emulator-5554") is False


def test_wait_for_boot_polls_until_booted(monkeypatch):
    calls = {"n": 0}

    def fake_run(argv, **kw):
        # wait-for-device call and getprop calls both land here.
        if "getprop" in argv:
            calls["n"] += 1
            val = "1" if calls["n"] >= 3 else "0"
            return subprocess.CompletedProcess(argv, 0, val, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    slept = []
    adb.wait_for_boot(
        "emulator-5554",
        timeout=100,
        poll=1,
        sleep=slept.append,
        clock=lambda: 0.0,  # never advances -> loop bounded by booted flag
    )
    assert calls["n"] >= 3


def test_wait_for_boot_times_out(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(0, "0\n"))
    t = {"v": 0.0}

    def clock():
        t["v"] += 10
        return t["v"]

    with pytest.raises(adb.AdbError):
        adb.wait_for_boot(
            "emulator-5554", timeout=5, poll=1, sleep=lambda *_: None, clock=clock
        )


def test_run_missing_binary(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(adb.AdbError):
        adb.run(["adb", "devices"])
