"""Offline PENT-18 regression tests; fixtures never execute native hosts."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/analysis/ext_native_host.py"
spec = importlib.util.spec_from_file_location("ext_native_host", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
ID = "a" * 32
OTHER = "b" * 32


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def lab(tmp_path):
    root = tmp_path / "lab"
    extension = root / "extension"
    extension.mkdir(parents=True)
    manifest = {"manifest_version": 3, "name": "Owned lab", "version": "1.0",
                "permissions": ["nativeMessaging"]}
    write(extension / "manifest.json", manifest)
    (extension / "background.js").write_text(
        "chrome.runtime.connectNative('org.oslab.echo');\n", encoding="utf-8")
    binary = root / "echo.py"
    binary.write_text("#!/usr/bin/env python3\nraise RuntimeError('MUST NOT RUN')\n", encoding="utf-8")
    binary.chmod(0o700)
    host = dict(name="org.oslab.echo", description="Owned inert fixture", type="stdio",
                path=str(binary), allowed_origins=[f"chrome-extension://{ID}/"])
    host_path = root / "host.json"
    write(host_path, host)
    return root, extension, host_path, host, manifest, binary


def run(lab, **kwargs):
    root, extension, host_path, *_ = lab
    return audit.analyze(root, extension, [host_path],
                         platform="windows" if os.name == "nt" else "posix",
                         extension_id=ID, **kwargs)


def rules(report):
    return {f["rule"] for f in report["findings"]}


def test_valid_bridge_is_not_called_malware(lab, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("executed a process"))
    result = run(lab)
    assert result["summary"]["high"] == 0
    assert result["hosts"][0]["binary"]["format"] == "script"
    assert len(result["hosts"][0]["binary"]["sha256"]) == 64
    assert result["calls"][0]["host"] == "org.oslab.echo"
    assert result["coverage"]["binary_execution"] is False


@pytest.mark.parametrize("allowed", [["*"], ["chrome-extension://*/"], [], [f"chrome-extension://{OTHER}/"]])
def test_bad_allowlist(lab, allowed):
    lab[3]["allowed_origins"] = allowed
    write(lab[2], lab[3])
    assert run(lab)["summary"]["high"] > 0


def test_multiple_callers(lab):
    lab[3]["allowed_origins"].append(f"chrome-extension://{OTHER}/")
    write(lab[2], lab[3])
    assert "multiple-callers" in rules(run(lab))


def test_firefox_id_and_optional_permission(lab):
    lab[4]["permissions"] = []
    lab[4]["optional_permissions"] = ["nativeMessaging"]
    lab[4]["browser_specific_settings"] = {"gecko": {"id": "owned@oslab.test"}}
    write(lab[1] / "manifest.json", lab[4])
    del lab[3]["allowed_origins"]
    lab[3]["allowed_extensions"] = ["owned@oslab.test"]
    write(lab[2], lab[3])
    report = run(lab)
    assert "caller-not-allowed" not in rules(report)
    assert report["extension"]["optional_native_permission"] is True


def test_dynamic_and_unprovided_hosts(lab):
    (lab[1] / "background.js").write_text(
        "browser.runtime.sendNativeMessage(variable, {});\n"
        "chrome . runtime . connectNative('org.oslab.missing');", encoding="utf-8")
    assert {"dynamic-host", "host-not-provided"} <= rules(run(lab))


def test_calls_without_permission(lab):
    lab[4]["permissions"] = []
    write(lab[1] / "manifest.json", lab[4])
    assert "missing-native-permission" in rules(run(lab))


def test_binary_outside_scope_is_never_read(lab, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("private outside lab", encoding="utf-8")
    lab[3]["path"] = str(outside)
    write(lab[2], lab[3])
    report = run(lab)
    assert "binary-out-of-scope" in rules(report)
    assert report["hosts"][0]["binary"] == {"inspected": False}


def test_outside_input_refused(lab, tmp_path):
    with pytest.raises(audit.AnalysisError, match="outside"):
        audit.analyze(lab[0], tmp_path, [], platform="posix")


@pytest.mark.skipif(os.name == "nt", reason="requires native POSIX permissions/symlinks")
def test_symlink_escape_and_writable_ancestors(lab, tmp_path):
    outside = tmp_path / "outside.js"
    outside.write_text("private", encoding="utf-8")
    (lab[1] / "escape.js").symlink_to(outside)
    with pytest.raises(audit.AnalysisError, match="outside"):
        run(lab)
    (lab[1] / "escape.js").unlink()
    lab[5].chmod(0o4777)
    assert {"writable-host-chain", "privileged-mode"} <= rules(run(lab))


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX symlinks")
def test_linked_directory_refused(lab):
    (lab[1] / "linked").symlink_to(lab[0], target_is_directory=True)
    with pytest.raises(audit.AnalysisError, match="linked"):
        run(lab)


@pytest.mark.parametrize("contents", ['[]', '{broken', '{"name":"x","name":"y"}', 'null'])
def test_invalid_json_refused(lab, contents):
    lab[2].write_text(contents, encoding="utf-8")
    with pytest.raises(audit.AnalysisError):
        run(lab)


@pytest.mark.parametrize("field,value", [("permissions", "nativeMessaging"), ("optional_permissions", [1])])
def test_invalid_permission_schema(lab, field, value):
    lab[4][field] = value
    write(lab[1] / "manifest.json", lab[4])
    with pytest.raises(audit.AnalysisError):
        run(lab)


def test_duplicate_hosts_refused(lab):
    with pytest.raises(audit.AnalysisError, match="duplicate native"):
        audit.analyze(lab[0], lab[1], [lab[2], lab[2]], platform="posix")


def test_missing_binary_and_wrong_type(lab):
    lab[3]["type"] = "shell"
    lab[5].unlink()
    write(lab[2], lab[3])
    assert {"invalid-host-type", "binary-missing"} <= rules(run(lab))


@pytest.mark.skipif(os.name == "nt", reason="POSIX relative-path rule")
def test_relative_posix_binary(lab):
    lab[3]["path"] = lab[5].name
    write(lab[2], lab[3])
    assert "relative-posix-path" in rules(run(lab))


def test_resource_limits_refuse_partial_scan(lab, monkeypatch):
    monkeypatch.setattr(audit, "MAX_FILES", 1)
    with pytest.raises(audit.AnalysisError, match="file limit"):
        run(lab)


def test_large_source_refused(lab, monkeypatch):
    monkeypatch.setattr(audit, "MAX_SOURCE", 4)
    with pytest.raises(audit.AnalysisError, match="byte limit"):
        run(lab)


def test_unverified_identity(lab):
    report = audit.analyze(lab[0], lab[1], [lab[2]], platform="windows" if os.name == "nt" else "posix")
    assert "identity-unverified" in rules(report)


def test_cli_json_and_exit_codes(lab, capsys):
    args = [str(lab[1]), "--lab-root", str(lab[0]), "--host", str(lab[2]),
            "--extension-id", ID, "--json"]
    assert audit.main(args) == 0
    assert json.loads(capsys.readouterr().out)["task"] == "PENT-18"
    lab[3]["allowed_origins"] = ["*"]
    write(lab[2], lab[3])
    assert audit.main(args) == 1
    assert audit.main(args + ["--fail-on", "never"]) == 0
    lab[2].write_text("broken", encoding="utf-8")
    assert audit.main(args) == 2
    assert "analysis refused" in capsys.readouterr().err
