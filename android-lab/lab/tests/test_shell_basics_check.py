"""OS-11 regression tests; temporary lab paths only, no network or shell."""

import importlib.util
import io
import json
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "shell_basics_check", Path(__file__).resolve().parents[3]
    / "linux-lab/exercises/shell_basics_check.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)
pytestmark = pytest.mark.skipif(not checker.sys.platform.startswith("linux"), reason="Linux lab")


@pytest.fixture
def lab(tmp_path):
    for student in ("ali", "eda", "aleyna"):
        for folder in ("odevler", "sinavlar", "sunumlar"):
            (tmp_path / student / folder).mkdir(parents=True)
        (tmp_path / student / "puan.txt").write_text("75\n")
    return tmp_path


def row(report, path):
    return next(item for item in report["results"] if item["path"] == path)


def test_complete_lab_is_read_only(lab):
    before = {p.relative_to(lab): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
              for p in lab.rglob("*")}
    report = checker.grade(lab)
    assert report["success"] and report["passed"] == report["total"] == 15
    after = {p.relative_to(lab): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
             for p in lab.rglob("*")}
    assert before == after


def test_empty_lab_has_fifteen_missing_paths(tmp_path):
    report = checker.grade(tmp_path)
    assert report["passed"] == 0 and len(report["results"]) == 15
    assert all(r["status"] == "missing" for r in report["results"])
    assert list(tmp_path.iterdir()) == []


def test_missing_file_has_actionable_hint(lab):
    (lab / "eda/puan.txt").unlink()
    report = checker.grade(lab)
    assert report["passed"] == 14 and not report["success"]
    assert "touch --" in row(report, "eda/puan.txt")["hint"]


@pytest.mark.parametrize("path", ["ali/puan.txt", "ali/odevler"])
def test_wrong_type(lab, path):
    target = lab / path
    if target.is_file():
        target.unlink()
        target.mkdir()
    else:
        target.rmdir()
        target.touch()
    assert row(checker.grade(lab), path)["status"] == "wrong-type"


@pytest.mark.parametrize("broken", [False, True])
def test_file_links_are_not_followed(lab, broken):
    path = lab / "ali/puan.txt"
    path.unlink()
    path.symlink_to(lab / ("missing" if broken else "eda/puan.txt"))
    assert row(checker.grade(lab), "ali/puan.txt")["status"] == "symlink"


def test_parent_link_cannot_produce_passing_children(lab):
    (lab / "ali").rename(lab / "outside")
    (lab / "ali").symlink_to(lab / "outside", target_is_directory=True)
    report = checker.grade(lab)
    assert report["passed"] == 10
    assert all(r["status"] != "pass" for r in report["results"] if r["path"].startswith("ali"))


def test_special_file_is_rejected(lab):
    (lab / "ali/puan.txt").unlink()
    os.mkfifo(lab / "ali/puan.txt")
    assert row(checker.grade(lab), "ali/puan.txt")["status"] == "wrong-type"


def test_permission_error_is_not_success(lab, monkeypatch):
    monkeypatch.setattr(checker.os, "stat", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    report = checker.grade(str(lab))
    assert report["passed"] == 0
    assert all(r["status"] == "unavailable" for r in report["results"])


def test_extra_files_and_empty_score_are_allowed(lab):
    (lab / "extra").touch()
    (lab / "ali/puan.txt").write_text("")
    assert checker.grade(lab)["success"]


def test_json_cli_success(lab, capsys):
    assert checker.main([str(lab), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] == 15 and report["schema_version"] == 1


def test_text_cli_failure(tmp_path, capsys):
    assert checker.main([str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "0/15" in output and "[FAIL] ali" in output


@pytest.mark.parametrize("kind", ["missing", "file", "link"])
def test_invalid_root_exit_two(tmp_path, kind, capsys):
    root = tmp_path / "root"
    if kind == "file":
        root.touch()
    elif kind == "link":
        root.symlink_to(tmp_path, target_is_directory=True)
    assert checker.main([str(root), "--json"]) == 2
    assert "error" in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("args", [[], ["--interactive", "--json"], ["--show-exercise", "--json"]])
def test_invalid_arguments(args):
    with pytest.raises(SystemExit) as exc:
        checker.main(args)
    assert exc.value.code == 2


def test_show_exercise(capsys):
    assert checker.main(["--show-exercise"]) == 0
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 15 and "aleyna/puan.txt" in output


def test_interactive(lab, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: str(lab))
    assert checker.main(["--interactive"]) == 0
    assert "15/15" in capsys.readouterr().out


def test_interactive_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    assert checker.main(["--interactive"]) == 2


def test_ascii_stdout_and_shell_sensitive_path(tmp_path, monkeypatch):
    root = tmp_path / "İsim ' $(echo x)"
    root.mkdir()
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    monkeypatch.setattr(checker.sys, "stdout", stream)
    assert checker.main([str(root)]) == 1
    stream.flush()
    assert b"0/15" in stream.buffer.getvalue()
    assert list(root.iterdir()) == []
