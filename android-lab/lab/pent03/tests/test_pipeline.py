"""Pipeline orchestrator tests — plan() is pure; a full run is driven with every
side-effecting module monkeypatched, so no device/network is needed."""
import pytest

import pipeline
import scope


def test_plan_full_order():
    assert pipeline.plan() == ["scope", "boot", "frida", "ca", "proxy", "unpin"]


def test_plan_respects_skip():
    assert pipeline.plan(skip=("frida", "ca")) == ["scope", "boot", "proxy", "unpin"]


def test_proxy_commands():
    assert pipeline.set_proxy_command("10.0.2.2:8080") == [
        "settings", "put", "global", "http_proxy", "10.0.2.2:8080",
    ]
    assert pipeline.clear_proxy_command()[-1] == ":0"


def test_parse_proxy_rejects_shell_injection():
    # the classic payload: a shell metachar smuggled through the port
    with pytest.raises(ValueError):
        pipeline.parse_proxy("10.0.2.2:8080;id")
    with pytest.raises(ValueError):
        pipeline.parse_proxy("10.0.2.2:$(reboot)")
    with pytest.raises(ValueError):
        pipeline.parse_proxy("10.0.2.2:70000")  # port out of range
    with pytest.raises(ValueError):
        pipeline.parse_proxy("8.8.8.8:8080")     # host not in scope
    assert pipeline.parse_proxy("10.0.2.2:8080") == ("10.0.2.2", 8080)


def test_set_proxy_command_rejects_injection():
    with pytest.raises(ValueError):
        pipeline.set_proxy_command("10.0.2.2:8080;rm -rf /")


def test_partial_report_written_on_step_failure(monkeypatch):
    # frida blows up; boot already passed. The report must still carry both.
    monkeypatch.setattr(pipeline.adb, "wait_for_boot", lambda s, **k: None)

    def boom(*a, **k):
        raise pipeline.deploy_frida.FridaDeployError("no network")

    monkeypatch.setattr(pipeline.deploy_frida, "deploy", boom)
    report = pipeline.run_pipeline("com.securebank.mobile", serial="emulator-5554")
    names = [s.name for s in report.steps]
    assert names == ["scope", "boot", "frida"]      # stopped at the failure
    assert report.steps[-1].name == "frida" and not report.steps[-1].ok
    assert not report.ok


class _Proc:
    """Fake background unpinning process (alive unless `dead=True`)."""
    def __init__(self, dead=False):
        self.pid = 4242
        self._rc = 1 if dead else None
        self.terminated = False

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        self._rc = -15

    def wait(self, timeout=None):
        return self._rc

    def kill(self):
        self._rc = -9


def _nosleep(*_a, **_k):
    pass


def test_run_pipeline_happy_path(monkeypatch):
    monkeypatch.setattr(pipeline.adb, "wait_for_boot", lambda s, **k: None)
    monkeypatch.setattr(pipeline.deploy_frida, "deploy", lambda s, **k: "16.5.9")
    monkeypatch.setattr(pipeline.install_ca, "install", lambda s, c=None, **k: "/system/etc/security/cacerts/abcd1234.0")
    monkeypatch.setattr(pipeline.adb, "shell", lambda s, *a, **k: "")
    monkeypatch.setattr(pipeline.sslpinning_bypass, "start_bypass", lambda p, **k: _Proc())

    report = pipeline.run_pipeline(
        "com.securebank.mobile", serial="emulator-5554", proxy="10.0.2.2:8080",
        sleep=_nosleep,
    )
    assert report.ok
    names = [s.name for s in report.steps]
    # unpin runs in the background, then the session is torn down.
    assert names == ["scope", "boot", "frida", "ca", "proxy", "unpin", "teardown"]


def test_unpin_runs_in_background_and_is_stopped(monkeypatch):
    started = {}

    def fake_start(pkg, **k):
        started["proc"] = _Proc()
        return started["proc"]

    monkeypatch.setattr(pipeline.adb, "wait_for_boot", lambda s, **k: None)
    monkeypatch.setattr(pipeline.deploy_frida, "deploy", lambda s, **k: "16.5.9")
    monkeypatch.setattr(pipeline.install_ca, "install", lambda s, c=None, **k: "/x")
    monkeypatch.setattr(pipeline.adb, "shell", lambda s, *a, **k: "")
    monkeypatch.setattr(pipeline.sslpinning_bypass, "start_bypass", fake_start)

    report = pipeline.run_pipeline(
        "com.securebank.mobile", serial="emulator-5554", hold=5, sleep=_nosleep,
    )
    assert report.ok
    assert started["proc"].terminated                      # background proc stopped
    names = [s.name for s in report.steps]
    assert "analysis" in names and names[-1] == "teardown"  # held, then torn down


def test_run_pipeline_out_of_scope_refuses(monkeypatch):
    with pytest.raises(scope.ScopeError):
        pipeline.run_pipeline("com.whatsapp", serial="emulator-5554")


def test_run_pipeline_unpin_failure_marks_report(monkeypatch):
    monkeypatch.setattr(pipeline.adb, "wait_for_boot", lambda s, **k: None)
    monkeypatch.setattr(pipeline.deploy_frida, "deploy", lambda s, **k: "16.5.9")
    monkeypatch.setattr(pipeline.install_ca, "install", lambda s, c=None, **k: "/x")
    monkeypatch.setattr(pipeline.adb, "shell", lambda s, *a, **k: "")
    # tool exits immediately -> dead process -> unpin must be marked failed
    monkeypatch.setattr(pipeline.sslpinning_bypass, "start_bypass", lambda p, **k: _Proc(dead=True))

    report = pipeline.run_pipeline("com.securebank.mobile", serial="emulator-5554", sleep=_nosleep)
    assert not report.ok
    assert report.steps[-1].name == "unpin"
    assert not report.steps[-1].ok


def test_run_pipeline_skip_steps(monkeypatch):
    monkeypatch.setattr(pipeline.adb, "wait_for_boot", lambda s, **k: None)
    monkeypatch.setattr(pipeline.adb, "shell", lambda s, *a, **k: "")
    monkeypatch.setattr(pipeline.sslpinning_bypass, "start_bypass", lambda p, **k: _Proc())

    report = pipeline.run_pipeline(
        "com.securebank.mobile", serial="emulator-5554", skip=("frida", "ca"),
        sleep=_nosleep,
    )
    names = [s.name for s in report.steps]
    assert "frida" not in names and "ca" not in names
    assert report.ok


def test_dry_run_main_prints_plan(capsys):
    rc = pipeline.main(["com.securebank.mobile", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "objection" in out


def test_main_out_of_scope_exit_2(capsys):
    rc = pipeline.main(["com.whatsapp"])
    assert rc == 2
    assert "OUT OF SCOPE" in capsys.readouterr().err
