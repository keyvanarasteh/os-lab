"""Unit tests for console/frida_inventory.py: table parsing, scope guard and the read-only inventory.

No Frida, device or network is used: the runner that would call frida-ls-devices
and frida-ps is replaced by a fake that records the argv it was given.
"""
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))

import frida_inventory as fi  # noqa: E402

DEVICES = (
    "Id             Type    Name                   OS\n"
    "-------------  ------  ---------------------  ------------------\n"
    "local          local   Local System           Windows 10.0.26300\n"
    "emulator-5554  usb     Android Emulator 5554  Android 14\n"
    "barebone       remote  GDB Remote Stub\n"
    "socket         remote  Local Socket\n"
)

PS_TABLE = (
    "  PID  Name\n"
    "-----  -----------------------\n"
    "19708  ApplicationFrameHost.exe\n"
    "  412  hedef\n"
    " 5840  My Lab App\n"
)

PS_APPS_TABLE = (
    " PID  Name      Identifier\n"
    "----  --------  ----------------------\n"
    "2114  Lab Bank  com.testlab.bank\n"
    "   -  Settings  com.android.settings\n"
)

PS_JSON = json.dumps([
    {"pid": 412, "name": "hedef"},
    {"pid": 2114, "name": "Lab Bank", "identifier": "com.testlab.bank"},
])


class FakeRunner:
    """Stands in for run_tool: answers by tool name and remembers every argv."""

    def __init__(self, devices=DEVICES, processes=PS_JSON):
        self.devices = devices
        self.processes = processes
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        answer = self.devices if "ls-devices" in os.path.basename(argv[0]) else self.processes
        if isinstance(answer, Exception):
            raise answer
        return answer

    def ps_calls(self):
        return [call for call in self.calls if "frida-ps" in os.path.basename(call[0])]


class FakeDevice:
    def __init__(self, id, type, name, os_info=None, processes=(), apps=(), fail=None):
        self.id, self.type, self.name = id, type, name
        self._os, self._processes, self._apps, self._fail = os_info, processes, apps, fail
        self.calls = []

    def query_system_parameters(self):
        self.calls.append("query_system_parameters")
        return {"os": self._os} if self._os else {}

    def enumerate_processes(self):
        self.calls.append("enumerate_processes")
        if self._fail:
            raise self._fail
        return [SimpleNamespace(pid=pid, name=name) for pid, name in self._processes]

    def enumerate_applications(self):
        self.calls.append("enumerate_applications")
        return [SimpleNamespace(pid=pid, name=name, identifier=ident) for pid, name, ident in self._apps]


class FakeFrida:
    """Stands in for the `frida` module: only the listing calls exist, so anything else would fail."""

    __version__ = "0.0-test"

    def __init__(self, devices):
        self._devices = {device.id: device for device in devices}
        self.remote_hosts = []

    def enumerate_devices(self):
        return list(self._devices.values())

    def get_device(self, device_id, timeout=0):
        return self._devices[device_id]

    def get_device_manager(self):
        return self

    def add_remote_device(self, host):
        self.remote_hosts.append(host)
        return self._devices["socket"]


def fake_frida(**socket_kwargs):
    return FakeFrida([
        FakeDevice("local", "local", "Local System", {"name": "Windows", "version": "10.0.26300"},
                   processes=[(412, "hedef"), (5840, "My Lab App")]),
        FakeDevice("emulator-5554", "usb", "Android Emulator 5554", {"name": "Android", "version": "14"},
                   processes=[(2114, "Lab Bank")],
                   apps=[(2114, "Lab Bank", "com.testlab.bank"), (0, "Settings", "com.android.settings")]),
        FakeDevice("socket", "remote", "Local Socket", processes=[(77, "lab-target")], **socket_kwargs),
    ])


@pytest.fixture(autouse=True)
def tools_present(monkeypatch):
    """CLI tools "installed", frida module absent: tests opt into the API backend explicitly."""
    monkeypatch.setattr(fi, "find_tool", lambda name: "/lab/bin/" + name)
    monkeypatch.setattr(fi, "load_frida", lambda: None)


# --- parsing -------------------------------------------------------------------

def test_parse_devices_maps_type_to_transport():
    devices = fi.parse_devices(DEVICES)
    assert [(d["id"], d["transport"]) for d in devices] == [
        ("local", "local"), ("emulator-5554", "USB"), ("barebone", "TCP"), ("socket", "TCP"),
    ]
    assert devices[0]["name"] == "Local System" and devices[0]["os"] == "Windows 10.0.26300"
    assert devices[2]["os"] is None


def test_parse_table_handles_right_aligned_pids_and_spaces_in_names():
    assert fi.parse_processes(PS_TABLE) == [
        {"pid": 19708, "name": "ApplicationFrameHost.exe"},
        {"pid": 412, "name": "hedef"},
        {"pid": 5840, "name": "My Lab App"},
    ]


def test_parse_processes_keeps_identifier_and_tolerates_missing_pid():
    assert fi.parse_processes(PS_APPS_TABLE) == [
        {"pid": 2114, "name": "Lab Bank", "identifier": "com.testlab.bank"},
        {"pid": None, "name": "Settings", "identifier": "com.android.settings"},
    ]


def test_parse_processes_prefers_json_and_falls_back_to_table():
    assert fi.parse_processes(PS_JSON)[1]["identifier"] == "com.testlab.bank"
    assert fi.parse_processes("[not json\n" + PS_TABLE)[1] == {"pid": 412, "name": "hedef"}


@pytest.mark.parametrize("text", ["", "No running applications.\n", "Id  Type\n"])
def test_parsers_return_empty_for_output_without_a_table(text):
    assert fi.parse_devices(text) == [] and fi.parse_processes(text) == []


# --- scope guard ---------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("127.0.0.1", "127.0.0.1:27042"),
    ("localhost:27043", "127.0.0.1:27043"),
    ("192.168.56.101:27042", "192.168.56.101:27042"),
    ("10.25.130.7", "10.25.130.7:27042"),
    ("[::1]:27042", "[::1]:27042"),
])
def test_lab_hosts_are_accepted_and_normalised(value, expected):
    assert fi.parse_lab_host(value) == expected


@pytest.mark.parametrize("value", [
    "8.8.8.8", "example.com", "example.com:27042", "1.1.1.1:27042", "[2606:4700::1111]:27042",
    "127.0.0.1:0", "127.0.0.1:99999", "127.0.0.1:abc", "", "[::1", "-H",
])
def test_public_or_malformed_hosts_are_refused(value):
    with pytest.raises(fi.ScopeError):
        fi.parse_lab_host(value)


@pytest.mark.parametrize("value", ["", "-U", "--host=8.8.8.8", "a b", "x;rm", "a" * 200])
def test_device_ids_that_could_be_read_as_options_are_refused(value):
    with pytest.raises(fi.ScopeError):
        fi.check_device_id(value)


def test_out_of_scope_host_never_reaches_a_frida_tool():
    runner = FakeRunner()
    with pytest.raises(fi.ScopeError):
        fi.build_inventory(host="8.8.8.8", runner=runner)
    assert runner.calls == []


# --- inventory -----------------------------------------------------------------

def test_default_inventory_lists_processes_for_local_and_usb_only():
    runner = FakeRunner()
    inv = fi.build_inventory(runner=runner, now=datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc))
    assert inv["schema"] == fi.SCHEMA and inv["readOnly"] is True
    assert inv["generatedAt"] == "2026-11-12T09:00:00Z"
    by_id = {d["id"]: d for d in inv["devices"]}
    assert by_id["local"]["processCount"] == 2 and by_id["emulator-5554"]["processCount"] == 2
    assert by_id["barebone"]["processes"] is None and by_id["socket"]["processes"] is None
    assert inv["summary"] == {"devices": 4, "usb": 1, "tcp": 2, "processes": 4}
    assert inv["errors"] == []
    assert [call[1:3] for call in runner.ps_calls()] == [["-D", "local"], ["-D", "emulator-5554"]]


def test_only_read_only_listing_flags_are_ever_passed():
    runner = FakeRunner()
    fi.build_inventory(runner=runner, apps=True)
    fi.build_inventory(runner=runner, host="127.0.0.1")
    allowed = {"-D", "-H", "-j", "-e", "-a", "local", "emulator-5554", "127.0.0.1:27042"}
    for call in runner.calls:
        assert os.path.basename(call[0]) in fi.TOOLS
        assert set(call[1:]) <= allowed


def test_usb_filter_and_missing_usb_device():
    inv = fi.build_inventory(usb=True, runner=FakeRunner())
    assert [d["id"] for d in inv["devices"]] == ["emulator-5554"]
    no_usb = fi.build_inventory(usb=True, runner=FakeRunner(devices=DEVICES.replace("usb   ", "remote")))
    assert no_usb["devices"] == [] and no_usb["errors"][0]["message"] == "no USB device attached"


def test_unknown_device_id_is_reported():
    inv = fi.build_inventory(device="emulator-9999", runner=FakeRunner())
    assert inv["devices"] == [] and "not attached" in inv["errors"][0]["message"]


def test_host_target_is_one_tcp_device_queried_with_dash_h():
    runner = FakeRunner()
    inv = fi.build_inventory(host="localhost", runner=runner)
    assert [(d["id"], d["transport"]) for d in inv["devices"]] == [("tcp@127.0.0.1:27042", "TCP")]
    assert runner.ps_calls()[0][1:3] == ["-H", "127.0.0.1:27042"]
    assert runner.calls == runner.ps_calls() and inv["errors"] == []


def test_host_target_does_not_depend_on_the_device_listing():
    runner = FakeRunner(devices=fi.ToolError("frida-ls-devices timed out after 20s"))
    inv = fi.build_inventory(host="127.0.0.1", runner=runner)
    assert inv["errors"] == [] and inv["devices"][0]["processCount"] is not None


def test_name_filter_matches_name_or_identifier():
    inv = fi.build_inventory(device="local", name_filter="TESTLAB", runner=FakeRunner())
    assert inv["devices"][0]["processes"] == [{"pid": 2114, "name": "Lab Bank", "identifier": "com.testlab.bank"}]


def test_no_processes_never_calls_frida_ps():
    runner = FakeRunner()
    inv = fi.build_inventory(processes=False, runner=runner)
    assert runner.ps_calls() == [] and inv["summary"]["processes"] == 0


def test_process_listing_failure_is_recorded_per_device_not_fatal():
    runner = FakeRunner(processes=fi.ToolError("unable to connect to remote frida-server"))
    inv = fi.build_inventory(host="127.0.0.1", runner=runner)
    assert inv["devices"][0]["error"] == "unable to connect to remote frida-server"
    assert inv["errors"][0]["stage"] == "processes"


def test_missing_tools_are_reported_instead_of_raising(monkeypatch):
    monkeypatch.setattr(fi, "find_tool", lambda name: None)
    inv = fi.build_inventory(runner=FakeRunner())
    assert inv["tools"]["frida-ps"] == {"found": False, "path": None}
    assert inv["devices"] == [] and "not found" in inv["errors"][0]["message"]


def test_more_than_one_target_is_a_usage_error():
    with pytest.raises(fi.ScopeError):
        fi.build_inventory(usb=True, host="127.0.0.1", runner=FakeRunner())


# --- frida module backend ------------------------------------------------------

def test_api_backend_is_preferred_when_frida_is_importable(monkeypatch):
    frida = fake_frida()
    monkeypatch.setattr(fi, "load_frida", lambda: frida)
    runner = FakeRunner()
    inv = fi.build_inventory(runner=runner)
    assert inv["backend"] == "api" and runner.calls == []
    assert inv["tools"]["frida-python"] == {"found": True, "version": "0.0-test"}
    by_id = {d["id"]: d for d in inv["devices"]}
    assert by_id["local"]["os"] == "Windows 10.0.26300" and by_id["emulator-5554"]["transport"] == "USB"
    assert by_id["local"]["processes"] == [{"pid": 412, "name": "hedef"}, {"pid": 5840, "name": "My Lab App"}]
    assert by_id["socket"]["processes"] is None and by_id["socket"]["os"] is None
    assert inv["summary"] == {"devices": 3, "usb": 1, "tcp": 1, "processes": 3}


def test_api_backend_never_touches_an_unnamed_remote_device(monkeypatch):
    frida = fake_frida()
    monkeypatch.setattr(fi, "load_frida", lambda: frida)
    fi.build_inventory()
    assert frida.get_device("socket").calls == [] and frida.remote_hosts == []


def test_api_backend_lists_running_apps_with_identifier(monkeypatch):
    monkeypatch.setattr(fi, "load_frida", fake_frida)
    inv = fi.build_inventory(usb=True, apps=True)
    assert inv["devices"][0]["processes"] == [{"pid": 2114, "name": "Lab Bank", "identifier": "com.testlab.bank"}]


def test_api_backend_host_goes_through_the_scope_guard(monkeypatch):
    frida = fake_frida()
    monkeypatch.setattr(fi, "load_frida", lambda: frida)
    with pytest.raises(fi.ScopeError):
        fi.build_inventory(host="8.8.8.8")
    assert frida.remote_hosts == []
    inv = fi.build_inventory(host="192.168.56.101")
    assert frida.remote_hosts == ["192.168.56.101:27042"]
    assert inv["devices"][0]["processes"] == [{"pid": 77, "name": "lab-target"}]


def test_api_backend_records_a_failed_listing(monkeypatch):
    monkeypatch.setattr(fi, "load_frida", lambda: fake_frida(fail=RuntimeError("unable to connect")))
    inv = fi.build_inventory(host="127.0.0.1")
    assert inv["devices"][0]["error"] == "process listing failed: unable to connect"


def test_api_backend_times_out_on_a_silent_device():
    release = threading.Event()
    backend = fi.ApiBackend(SimpleNamespace(enumerate_devices=lambda: release.wait(30)), timeout=1)
    with pytest.raises(fi.ToolError, match="device listing timed out after 1s"):
        backend.devices()
    release.set()


def test_backend_choice(monkeypatch):
    assert fi.build_inventory(backend="api", runner=FakeRunner())["errors"][0]["stage"] == "backend"
    monkeypatch.setattr(fi, "load_frida", fake_frida)
    runner = FakeRunner()
    assert fi.build_inventory(backend="cli", runner=runner)["backend"] == "cli" and runner.calls


# --- run_tool and CLI ----------------------------------------------------------

def test_run_tool_returns_stdout_and_raises_on_failure():
    assert fi.run_tool([sys.executable, "-c", "print('ok')"], 30).strip() == "ok"
    with pytest.raises(fi.ToolError, match="boom"):
        fi.run_tool([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"], 30)
    with pytest.raises(fi.ToolError, match="not found"):
        fi.run_tool([os.path.join(REPO_ROOT, "no-such-frida-tool")], 30)


def test_run_tool_times_out_and_stops_the_command():
    with pytest.raises(fi.ToolError, match="timed out after 1s"):
        fi.run_tool([sys.executable, "-c", "import time; time.sleep(60)"], 1)


def test_cli_prints_json_writes_file_and_exits_zero(capsysbinary, tmp_path):
    out = tmp_path / "inventory.json"
    code = fi.main(["--usb", "--compact", "-o", str(out)], runner=FakeRunner())
    printed = json.loads(capsysbinary.readouterr().out.decode("utf-8"))
    assert code == 0 and printed["devices"][0]["id"] == "emulator-5554"
    assert json.loads(out.read_text(encoding="utf-8")) == printed


def test_cli_exit_codes_for_scope_and_listing_errors(capsysbinary):
    assert fi.main(["--host", "8.8.8.8"], runner=FakeRunner()) == 2
    assert b"refusing" in capsysbinary.readouterr().err
    assert fi.main(["--usb"], runner=FakeRunner(devices="")) == 1
    assert fi.main(["--timeout", "0"], runner=FakeRunner()) == 2


def test_script_runs_standalone_and_refuses_public_host():
    script = os.path.join(REPO_ROOT, "console", "frida_inventory.py")
    done = subprocess.run([sys.executable, script, "--host", "8.8.8.8"], capture_output=True, timeout=60)
    assert done.returncode == 2 and b"refusing" in done.stderr and done.stdout == b""
