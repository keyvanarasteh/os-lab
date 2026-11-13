"""OS-26 regressions: offline temp directories; no sudo or ownership changes."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import stat
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "linux-lab/scripts/permission_audit.py"
SPEC = importlib.util.spec_from_file_location("os26_permission_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
pytestmark = pytest.mark.skipif(platform.system() != "Linux", reason="Linux lab tool")


def make_file(root, name="sample.txt", mode=0o600):
    path = root / name
    path.write_text("owned lab fixture\n")
    path.chmod(mode)
    return path


def finding_for(report, path):
    return next(item for item in report["findings"] if item["path"] == str(path))


def run_cli(root, *args):
    return subprocess.run([sys.executable, str(SCRIPT), str(root), *args],
                          text=True, capture_output=True, timeout=10)


def test_clean_modes_and_ownership(tmp_path):
    make_file(tmp_path)
    report = audit.audit_tree(tmp_path, group=os.getgid())
    assert report["complete"] and report["audited"] == 2
    assert report["findings"] == []
    assert audit.exit_status(report) == 0


@pytest.mark.parametrize("mode,rules", [
    (0o666, {"world-writable", "over-permissive-mode"}),
    (0o664, {"over-permissive-mode"}),
    (0o755, {"over-permissive-mode"}),
    (0o4644, {"setuid-or-setgid-file"}),
    (0o2644, {"setuid-or-setgid-file"}),
])
def test_permission_rules(tmp_path, mode, rules):
    path = make_file(tmp_path, mode=mode)
    item = finding_for(audit.audit_tree(tmp_path), path)
    assert set(item["rules"]) == rules
    assert item["mode"] == f"{mode:04o}"


def test_masks_compare_bits_not_octal_magnitude(tmp_path):
    path = make_file(tmp_path, mode=0o604)
    item = finding_for(audit.audit_tree(tmp_path, file_mode=0o640), path)
    assert item["suggested_commands"][0][1] == "0600"


def test_fix_does_not_grant_missing_permissions(tmp_path):
    path = make_file(tmp_path, mode=0o620)
    item = finding_for(audit.audit_tree(tmp_path), path)
    assert item["suggested_commands"][0] == ["chmod", "0600", "--", str(path)]


def test_custom_executable_policy(tmp_path):
    make_file(tmp_path, "demo.sh", 0o755)
    assert audit.audit_tree(tmp_path, file_mode=0o755)["findings"] == []


def test_world_writable_is_reported_even_if_mask_allows_it(tmp_path):
    path = make_file(tmp_path, mode=0o666)
    item = finding_for(audit.audit_tree(tmp_path, file_mode=0o666), path)
    assert item["rules"] == ["world-writable"]
    assert item["suggested_commands"][0][1] == "0664"


def test_sticky_directory_is_explained_and_sticky_bit_preserved(tmp_path):
    path = tmp_path / "shared"
    path.mkdir()
    path.chmod(0o1777)
    report = audit.audit_tree(tmp_path)
    item = finding_for(report, path)
    assert item["sticky_directory"] is True
    assert item["suggested_commands"][0][1] == "1755"
    assert "may be intentional" in audit.render_text(report)


def test_directory_setgid_is_not_treated_as_privileged_executable(tmp_path):
    tmp_path.chmod(0o2755)
    assert audit.audit_tree(tmp_path)["findings"] == []


def test_root_itself_is_audited(tmp_path):
    tmp_path.chmod(0o777)
    assert finding_for(audit.audit_tree(tmp_path), tmp_path)["type"] == "directory"


def test_owner_and_group_drift_without_chown(tmp_path):
    path = make_file(tmp_path)
    owner, group = os.getuid() + 1, os.getgid() + 1
    item = finding_for(audit.audit_tree(tmp_path, owner, group), path)
    assert set(item["rules"]) == {"owner-drift", "group-drift"}
    assert item["suggested_commands"] == [
        ["chown", "--no-dereference", f"{owner}:{group}", "--", str(path)]]


def test_group_only_drift_preserves_owner(tmp_path):
    path = make_file(tmp_path)
    item = finding_for(audit.audit_tree(tmp_path, group=os.getgid() + 1), path)
    assert item["suggested_commands"][0][2] == f":{os.getgid() + 1}"


def test_symlinks_and_broken_links_are_not_followed(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    # This fixture tests links; its root must be clean regardless of the umask.
    root.chmod(0o755)
    outside.mkdir()
    bad = make_file(outside, mode=0o666)
    (root / "file-link").symlink_to(bad)
    (root / "directory-link").symlink_to(outside, target_is_directory=True)
    (root / "broken-link").symlink_to(outside / "missing")
    (root / "cycle").symlink_to(root, target_is_directory=True)
    report = audit.audit_tree(root)
    assert report["skipped"]["symlinks"] == 4
    assert report["audited"] == 1 and report["findings"] == []
    assert report["complete"]


def test_root_symlink_is_refused(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    report = audit.audit_tree(link)
    assert audit.exit_status(report) == 2 and report["audited"] == 0


def test_fifo_is_not_opened(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    report = audit.audit_tree(tmp_path)
    assert report["skipped"]["special_files"] == 1
    assert report["complete"]


def test_stat_failure_is_not_reported_as_clean(tmp_path, monkeypatch):
    path = make_file(tmp_path)
    original = os.stat

    def denied(name, *args, **kwargs):
        if name == path.name:
            raise PermissionError(13, "Permission denied", name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(audit.os, "stat", denied)
    report = audit.audit_tree(tmp_path)
    assert audit.exit_status(report) == 2
    assert report["errors"][0]["path"] == str(path)
    assert "No findings under this policy" not in audit.render_text(report)


def test_unreadable_directory_reports_incomplete_scan(tmp_path, monkeypatch):
    def denied_walk(root, **kwargs):
        kwargs["onerror"](PermissionError(13, "Permission denied", str(root)))
        yield from ()

    monkeypatch.setattr(audit.os, "fwalk", denied_walk)
    report = audit.audit_tree(tmp_path)
    assert audit.exit_status(report) == 2
    assert "Permission denied" in report["errors"][0]["message"]


def test_mount_is_skipped_and_not_descended_into(tmp_path, monkeypatch):
    mount = tmp_path / "mounted"
    mount.mkdir()
    make_file(mount, mode=0o666)
    original = os.stat

    def other_device(name, *args, **kwargs):
        info = original(name, *args, **kwargs)
        if name == "mounted":
            values = list(info)
            values[stat.ST_DEV] += 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(audit.os, "stat", other_device)
    report = audit.audit_tree(tmp_path)
    assert report["skipped"]["other_filesystems"] == 1
    assert report["audited"] == 1 and report["findings"] == []


@pytest.mark.parametrize("replacement", ["directory", "symlink"])
def test_root_replacement_is_not_reported_as_success(tmp_path, monkeypatch, replacement):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    make_file(outside, mode=0o666)
    original = os.fwalk

    def replaced_walk(path, **kwargs):
        root.rename(tmp_path / "original")
        if replacement == "symlink":
            root.symlink_to(outside, target_is_directory=True)
        else:
            root.mkdir()
        yield from original(path, **kwargs)

    monkeypatch.setattr(audit.os, "fwalk", replaced_walk)
    report = audit.audit_tree(root)
    assert audit.exit_status(report) == 2
    assert report["errors"]
    assert all(not item["path"].startswith(str(outside)) for item in report["findings"])


def test_entry_limit_counts_skipped_links(tmp_path):
    (tmp_path / "a").symlink_to(tmp_path / "missing")
    make_file(tmp_path, "b")
    report = audit.audit_tree(tmp_path, max_entries=2)
    assert report["visited"] == 2 and audit.exit_status(report) == 2
    assert "entry limit" in report["errors"][0]["message"]


def test_read_only_and_no_shell_execution(tmp_path):
    path = make_file(tmp_path, "odd ' name; $(touch PWNED).txt", 0o666)
    before = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    report = audit.audit_tree(tmp_path)
    after = path.stat()
    assert (before.st_mode, before.st_uid, before.st_gid, before.st_mtime_ns,
            before.st_ctime_ns) == (after.st_mode, after.st_uid, after.st_gid,
                                   after.st_mtime_ns, after.st_ctime_ns)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert not (tmp_path / "PWNED").exists()
    argv = finding_for(report, path)["suggested_commands"][0]
    assert shlex.split(shlex.join(argv)) == ["chmod", "0644", "--", str(path)]


def test_control_characters_are_escaped_in_text_and_preserved_in_json(tmp_path):
    path = make_file(tmp_path, "line\n\x1b[31mname.txt", 0o666)
    report = audit.audit_tree(tmp_path)
    rendered = audit.render_text(report)
    assert "\x1b" not in rendered and "line\n" not in rendered
    decoded = json.loads(json.dumps(report, ensure_ascii=True))
    assert finding_for(decoded, path)["path"] == str(path)


@pytest.mark.parametrize("kind", ["missing", "file", "filesystem-root"])
def test_invalid_roots_produce_json_error_report(tmp_path, kind):
    root = {"missing": tmp_path / "missing", "file": make_file(tmp_path),
            "filesystem-root": Path("/")}[kind]
    proc = run_cli(root, "--json")
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["complete"] is False


@pytest.mark.parametrize("mode,expected", [(0o600, 0), (0o666, 1)])
def test_cli_json_exit_codes(tmp_path, mode, expected):
    make_file(tmp_path, mode=mode)
    proc = run_cli(tmp_path, "--json")
    assert proc.returncode == expected and proc.stderr == ""
    assert json.loads(proc.stdout)["complete"] is True


@pytest.mark.parametrize("args", [
    ("--file-mode", "888"), ("--dir-mode", "1777"), ("--file-mode", "u=rw"),
    ("--owner", "os26-nonexistent-user-xyz"), ("--group", "os26-nonexistent-group-xyz"),
    ("--owner", "4294967295"), ("--max-entries", "0"),
    ("--max-entries", "1000001"), ("--max-entries", "nan"),
])
def test_invalid_cli_arguments(tmp_path, args):
    proc = run_cli(tmp_path, *args)
    assert proc.returncode == 2 and "error:" in proc.stderr


def test_names_and_numeric_ids_resolve_to_same_policy(tmp_path):
    import grp
    import pwd
    proc = run_cli(tmp_path, "--json", "--owner", pwd.getpwuid(os.getuid()).pw_name,
                   "--group", grp.getgrgid(os.getgid()).gr_name)
    assert proc.returncode == 0
    policy = json.loads(proc.stdout)["policy"]
    assert (policy["owner_uid"], policy["group_gid"]) == (os.getuid(), os.getgid())
