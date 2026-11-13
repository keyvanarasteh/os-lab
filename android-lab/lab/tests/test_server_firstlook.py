"""Offline OS-16 tests: no system changes, subprocesses or network required."""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "linux-lab/scripts/server_firstlook.py"
SPEC = importlib.util.spec_from_file_location("server_firstlook", SCRIPT)
firstlook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(firstlook)

OUTPUTS = {
    "uname": "Linux 6.8.0-lab x86_64\n",
    "lsb_release": "Example Linux 1.0\n",
    "inxi": "CPU: Info: dual core model: Lab CPU\n",
    "free": "              total used free shared buff/cache available\n"
            "Mem:          10000 4000 2000 0 4000 6000\nSwap: 0 0 0\n",
    "df": "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
          "/dev/vda1 10000 8000 2000 80% /\n"
          "/dev/vdb1 20000 1000 19000 5% /media/Lab Data\n",
    "systemctl": "ssh.service loaded active running OpenSSH Server\n"
                 "demo.service loaded failed failed Demo\n"
                 "cron.service loaded inactive dead Cron\n",
}


@pytest.fixture
def fake_commands(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, OUTPUTS[argv[0]], "")

    monkeypatch.setattr(firstlook.subprocess, "run", run)
    return calls


def test_full_report_preserves_units_and_failed_services(fake_commands):
    report = firstlook.collect_report()
    assert report["complete"] is True
    assert report["memory"]["available_bytes"] == 6000
    assert report["disks"][0]["total_bytes"] == 10240000
    assert report["disks"][1]["mountpoint"] == "/media/Lab Data"
    assert report["services"]["failed"] == ["demo.service"]
    assert report["services"]["units"][2]["active"] == "inactive"
    text = firstlook.render_text(report)
    assert "demo.service: failed/failed" in text
    assert "amd64" in text
    for argv, kwargs in fake_commands:
        assert isinstance(argv, list)
        assert not kwargs.get("shell", False)
        assert kwargs["env"]["LC_ALL"] == "C"
        assert kwargs["timeout"] == 5.0


@pytest.mark.parametrize("error,status", [
    (FileNotFoundError(), "missing"),
    (subprocess.TimeoutExpired(["inxi"], 1), "timeout"),
    (PermissionError("permission denied"), "error"),
])
def test_command_failures_are_explicit(monkeypatch, error, status):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(firstlook.subprocess, "run", fail)
    check = firstlook.run_command(["inxi"], 1)
    assert check["status"] == status
    assert check["returncode"] is None
    assert check["stderr"]


def test_missing_systemd_does_not_claim_zero_failed_services(monkeypatch, fake_commands):
    original = firstlook.subprocess.run

    def run(argv, **kwargs):
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(argv, 1, "", "System has not been booted with systemd.")
        return original(argv, **kwargs)

    monkeypatch.setattr(firstlook.subprocess, "run", run)
    report = firstlook.collect_report()
    assert not report["complete"]
    assert report["services"] is None
    assert report["checks"]["systemctl"]["returncode"] == 1
    assert "service health could not be determined" in firstlook.render_text(report)
    assert report["memory"] is not None


def test_malformed_memory_is_not_silently_reported_as_zero(monkeypatch, fake_commands):
    monkeypatch.setitem(OUTPUTS, "free", "not a memory table\n")
    report = firstlook.collect_report()
    assert report["memory"] is None
    assert report["checks"]["free"]["status"] == "parse-error"
    assert not report["complete"]


@pytest.mark.parametrize("name", ["uname", "free", "df", "lsb_release", "inxi"])
def test_empty_required_output_marks_report_partial(monkeypatch, fake_commands, name):
    monkeypatch.setitem(OUTPUTS, name, "")
    report = firstlook.collect_report()
    assert report["checks"][name]["status"] == "parse-error"
    assert not report["complete"]


def test_json_cli_is_json_only(monkeypatch, fake_commands, capsys):
    monkeypatch.setattr(firstlook.platform, "system", lambda: "Linux")
    assert firstlook.main(["--json", "--timeout", "2"]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["schema_version"] == 1
    assert report["services"]["failed"] == ["demo.service"]
    assert output.err == ""
    assert all(options["timeout"] == 2 for _, options in fake_commands)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "61", "invalid"])
def test_invalid_timeout_rejected(value):
    with pytest.raises(SystemExit) as exc:
        firstlook.main(["--timeout", value])
    assert exc.value.code == 2


def test_non_linux_rejected(monkeypatch):
    monkeypatch.setattr(firstlook.platform, "system", lambda: "Windows")
    with pytest.raises(SystemExit) as exc:
        firstlook.main([])
    assert exc.value.code == 2


def test_architecture_and_terminal_control_characters():
    assert "arm64" in firstlook.architecture_note("aarch64")
    assert "Check the distro" in firstlook.architecture_note("unknown-arch")
    assert firstlook.clean_text("\x1b[31merror\x1b[0m\x07") == "error"


def test_malformed_disk_or_service_rows_rejected():
    with pytest.raises(ValueError):
        firstlook.parse_disks("Filesystem blocks used available percent mount\nbroken row")
    with pytest.raises(ValueError):
        firstlook.parse_services("not a service table")
    assert firstlook.parse_services("") == {"units": [], "failed": []}
