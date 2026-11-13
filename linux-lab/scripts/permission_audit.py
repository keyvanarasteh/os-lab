#!/usr/bin/env python3
"""OS-26: read-only Unix mode/ownership audit for an owned Linux lab directory."""

import argparse
from contextlib import closing
import json
import os
import platform
import re
import shlex
import stat


def parse_mode(value):
    """Accept rwx masks, not special bits or symbolic chmod expressions."""
    if not re.fullmatch(r"0?[0-7]{3}", value):
        raise argparse.ArgumentTypeError("use an octal rwx mask such as 0644 or 0755")
    return int(value, 8)


def parse_identity(value, kind):
    if re.fullmatch(r"[0-9]+", value):
        number = int(value)
        if number < 2**32 - 1:
            return number
        raise argparse.ArgumentTypeError(f"{kind} ID is outside the Linux ID range")
    try:
        if kind == "owner":
            import pwd
            return pwd.getpwnam(value).pw_uid
        import grp
        return grp.getgrnam(value).gr_gid
    except KeyError:
        raise argparse.ArgumentTypeError(f"unknown {kind}: {value!r}") from None


def entry_limit(value):
    try:
        number = int(value)
    except ValueError:
        number = 0
    if not 1 <= number <= 1_000_000:
        raise argparse.ArgumentTypeError("max-entries must be between 1 and 1000000")
    return number


def inspect_entry(path, info, owner, group, file_mode, dir_mode):
    """Compare metadata with an explicit policy; never execute the suggestions."""
    is_dir = stat.S_ISDIR(info.st_mode)
    mode = stat.S_IMODE(info.st_mode)
    limit = dir_mode if is_dir else file_mode
    excess = (mode & 0o777) & ~limit
    privileged = 0 if is_dir else mode & 0o6000
    rules = []
    if mode & stat.S_IWOTH:
        rules.append("world-writable")
    if excess:
        rules.append("over-permissive-mode")
    if privileged:
        rules.append("setuid-or-setgid-file")
    if info.st_uid != owner:
        rules.append("owner-drift")
    if group is not None and info.st_gid != group:
        rules.append("group-drift")
    if not rules:
        return None

    suggestions = []
    # Remove only flagged bits: never grant permissions absent from the original.
    # Preserve directory sticky/setgid bits (shared-directory semantics).
    target_mode = mode & ~(excess | privileged | stat.S_IWOTH)
    if target_mode != mode:
        suggestions.append(["chmod", f"{target_mode:04o}", "--", path])
    if "owner-drift" in rules or "group-drift" in rules:
        target_owner = str(owner) if "owner-drift" in rules else ""
        if "group-drift" in rules:
            target_owner += f":{group}"
        suggestions.append(["chown", "--no-dereference", target_owner, "--", path])
    return {
        "path": path, "type": "directory" if is_dir else "file",
        "mode": f"{mode:04o}", "symbolic_mode": stat.filemode(info.st_mode),
        "uid": info.st_uid, "gid": info.st_gid, "rules": rules,
        "sticky_directory": is_dir and bool(mode & stat.S_ISVTX),
        "suggested_commands": suggestions,
    }


def audit_tree(root, owner=None, group=None, file_mode=0o644, dir_mode=0o755,
               max_entries=10000):
    """Inspect root and descendants using directory-relative, no-follow stat."""
    root = os.path.abspath(os.fspath(root))
    owner = os.getuid() if owner is None else owner
    report = {
        "schema_version": 1, "root": root, "complete": True,
        "policy": {"owner_uid": owner, "group_gid": group,
                   "file_mode_max": f"{file_mode:04o}",
                   "dir_mode_max": f"{dir_mode:04o}",
                   "max_entries": max_entries, "follow_symlinks": False,
                   "cross_filesystems": False},
        "visited": 0, "audited": 0,
        "skipped": {"symlinks": 0, "special_files": 0, "other_filesystems": 0},
        "findings": [], "errors": [],
    }

    def error(path, message):
        report["complete"] = False
        report["errors"].append({"path": os.fsdecode(path), "message": str(message)})

    def audit(path, info):
        report["audited"] += 1
        finding = inspect_entry(path, info, owner, group, file_mode, dir_mode)
        if finding:
            report["findings"].append(finding)

    try:
        root_info = os.lstat(root)
        if not stat.S_ISDIR(root_info.st_mode):
            error(root, "root must be a directory, not a file or symbolic link")
            return report
        if os.path.realpath(root) == os.path.sep:
            error(root, "choose a specific lab directory instead of the filesystem root")
            return report
        report["visited"] = 1
        audit(root, root_info)

        def walk_error(exc):
            error(exc.filename or root, exc.strerror or str(exc))

        root_opened = False
        with closing(os.fwalk(root, topdown=True, onerror=walk_error,
                              follow_symlinks=False)) as walker:
            for directory, dirs, files, directory_fd in walker:
                opened_info = os.fstat(directory_fd)
                if not root_opened:
                    root_opened = True
                    if (opened_info.st_dev, opened_info.st_ino) != (root_info.st_dev, root_info.st_ino):
                        error(root, "root directory changed during the scan")
                        return report
                # Also check the opened directory: a mount could change while walking.
                if opened_info.st_dev != root_info.st_dev:
                    dirs[:] = []
                    error(directory, "filesystem changed during the scan")
                    continue
                descend = []
                original_dirs = set(dirs)
                for name in sorted(dirs + files):
                    path = os.path.join(directory, name)
                    if report["visited"] >= max_entries:
                        error(path, "entry limit reached; scan is incomplete")
                        return report
                    report["visited"] += 1
                    try:
                        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    except OSError as exc:
                        error(path, exc.strerror or str(exc))
                        continue
                    if stat.S_ISLNK(info.st_mode):
                        report["skipped"]["symlinks"] += 1
                    elif info.st_dev != root_info.st_dev:
                        report["skipped"]["other_filesystems"] += 1
                    elif stat.S_ISDIR(info.st_mode):
                        audit(path, info)
                        # Do not add a file that changed to a directory to fwalk's list.
                        if name in original_dirs:
                            descend.append(name)
                    elif stat.S_ISREG(info.st_mode):
                        audit(path, info)
                    else:
                        report["skipped"]["special_files"] += 1
                dirs[:] = descend
        if not root_opened and report["complete"]:
            error(root, "root directory could not be opened; it may have changed during the scan")
    except (OSError, RecursionError) as exc:
        error(root, str(exc))
    return report


def exit_status(report):
    if not report["complete"]:
        return 2
    return 1 if report["findings"] else 0


def render_text(report):
    policy = report["policy"]
    lines = ["OS-26 | File Permission & Ownership Auditor",
             f"Root: {report['root']!r}",
             "Scan: " + ("complete" if report["complete"] else "incomplete"),
             f"Policy: uid={policy['owner_uid']}, gid={policy['group_gid']}; "
             f"max file={policy['file_mode_max']}, dir={policy['dir_mode_max']}",
             f"Visited: {report['visited']} | Audited: {report['audited']} | "
             f"Entries with findings: {len(report['findings'])}",
             f"Skipped: {report['skipped']}",
             "Suggestions require review; no changes were made."]
    for item in report["findings"]:
        lines += ["", f"{item['path']!r} [{item['type']}]",
                  f"  {item['mode']} {item['symbolic_mode']} "
                  f"uid={item['uid']} gid={item['gid']}",
                  "  Rules: " + ", ".join(item["rules"])]
        if item["sticky_directory"]:
            lines.append("  Sticky bit is present; shared-directory write access may be intentional.")
        for argv in item["suggested_commands"]:
            command = shlex.join(argv)
            # Keep hostile filenames from injecting terminal controls or fake lines.
            if not command.isprintable():
                lines.append(f"  Suggestion (escaped; use JSON argv): {command!r}")
            else:
                lines.append(f"  Suggestion: {command}")
    for item in report["errors"]:
        lines.append(f"ERROR {item['path']!r}: {item['message']!r}")
    if not report["findings"] and report["complete"]:
        lines.append("No findings under this policy.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=
        "Exit codes: 0 = no findings, 1 = findings, 2 = usage/error/incomplete scan. "
        "Unix mode bits only; ACLs/capabilities are outside this audit.")
    parser.add_argument("directory", help="owned lab directory to inspect (root included)")
    parser.add_argument("--owner", type=lambda v: parse_identity(v, "owner"),
                        help="expected user name or UID (default: current user's UID)")
    parser.add_argument("--group", type=lambda v: parse_identity(v, "group"),
                        help="expected group name or GID (default: do not check group drift)")
    parser.add_argument("--file-mode", type=parse_mode, default=0o644,
                        help="maximum permitted file rwx bits (default: 0644)")
    parser.add_argument("--dir-mode", type=parse_mode, default=0o755,
                        help="maximum permitted directory rwx bits (default: 0755)")
    parser.add_argument("--max-entries", type=entry_limit, default=10000,
                        help="entry budget including root and skipped entries (default: 10000)")
    parser.add_argument("--json", action="store_true", help="emit a structured JSON report")
    args = parser.parse_args(argv)
    if platform.system() != "Linux":
        parser.error("run this tool inside your Linux lab/VM")
    report = audit_tree(args.directory, args.owner, args.group, args.file_mode,
                        args.dir_mode, args.max_entries)
    print(json.dumps(report, indent=2, ensure_ascii=True) if args.json else render_text(report))
    return exit_status(report)


if __name__ == "__main__":
    raise SystemExit(main())
