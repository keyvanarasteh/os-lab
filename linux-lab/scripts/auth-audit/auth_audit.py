#!/usr/bin/env python3
"""auth_audit.py - read-only auth log audit (OS-04).

Extracts failed SSH logins (grouped by source IP, flagged when they reach a
threshold) and unauthorized sudo attempts from /var/log/auth.log, the systemd
journal, or stdin. Standard library only; never modifies anything.

Exit codes: 0 = clean, 1 = findings (suspicious IP or sudo violation),
            2 = usage or read error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from typing import Iterable

DEFAULT_LOG = "/var/log/auth.log"
DEFAULT_THRESHOLD = 4

RE_FAILED = re.compile(
    r"Failed (?:password|publickey|keyboard-interactive/pam) for "
    r"(?:invalid user )?(?P<user>\S+) from (?P<ip>[0-9A-Fa-f:.]+) port \d+"
)
RE_INVALID = re.compile(r"Invalid user (?P<user>\S*) from (?P<ip>[0-9A-Fa-f:.]+)")
RE_NOT_IN_SUDOERS = re.compile(
    r"sudo(?:\[\d+\])?:\s+(?P<user>\S+) : user NOT in sudoers"
)
RE_BAD_PASSWORD = re.compile(
    r"sudo(?:\[\d+\])?:\s+(?P<user>\S+) : (?P<n>\d+) incorrect password attempts?"
)


class AuditError(Exception):
    """Raised for problems reading the log source (exit code 2)."""


def analyze(lines: Iterable[str], threshold: int, source: str) -> dict:
    """Parse log lines and return the audit report as a dict."""
    attempts: Counter = Counter()
    users: dict[str, set[str]] = defaultdict(set)
    sudo: Counter = Counter()

    for line in lines:
        m = RE_FAILED.search(line)
        if m:
            attempts[m["ip"]] += 1
            users[m["ip"]].add(m["user"])
            continue
        m = RE_INVALID.search(line)
        if m:
            if m["user"]:
                users[m["ip"]].add(m["user"])
            continue
        m = RE_NOT_IN_SUDOERS.search(line)
        if m:
            sudo[(m["user"], "not_in_sudoers")] += 1
            continue
        m = RE_BAD_PASSWORD.search(line)
        if m:
            sudo[(m["user"], "incorrect_password")] += int(m["n"])

    ips = [
        {
            "ip": ip,
            "attempts": n,
            "suspicious": n >= threshold,
            "users": sorted(users[ip]),
        }
        for ip, n in sorted(attempts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    sudo_events = [
        {"user": user, "type": kind, "count": count}
        for (user, kind), count in sorted(sudo.items())
    ]
    return {
        "source": source,
        "threshold": threshold,
        "failed_logins": sum(attempts.values()),
        "unique_ips": len(ips),
        "suspicious_ips": [i for i in ips if i["suspicious"]],
        "ips": ips,
        "sudo_violations": sum(e["count"] for e in sudo_events),
        "sudo_events": sudo_events,
    }


def format_summary(report: dict) -> str:
    """Human-readable table for --summary."""
    out = [
        f"Source: {report['source']}   Threshold: {report['threshold']}",
        f"Failed SSH logins: {report['failed_logins']} "
        f"from {report['unique_ips']} IP(s)",
        "",
        f"{'IP':<40} {'ATTEMPTS':>8}  {'STATUS':<10}  USERS",
    ]
    if not report["ips"]:
        out.append("(no failed SSH logins found)")
    for item in report["ips"]:
        status = "SUSPICIOUS" if item["suspicious"] else "normal"
        out.append(
            f"{item['ip']:<40} {item['attempts']:>8}  {status:<10}  "
            f"{','.join(item['users'])}"
        )
    out.append("")
    out.append(f"Unauthorized sudo attempts: {report['sudo_violations']}")
    for event in report["sudo_events"]:
        label = (
            "not in sudoers"
            if event["type"] == "not_in_sudoers"
            else "incorrect password"
        )
        out.append(f"  {event['user']}: {label} ({event['count']})")
    return "\n".join(out)


def read_lines(path: str | None, use_journal: bool) -> tuple[list[str], str]:
    """Return (lines, source_label). Raises AuditError on failure."""
    if use_journal:
        try:
            proc = subprocess.run(
                ["journalctl", "-t", "sshd", "-t", "sudo", "--no-pager"],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
        except FileNotFoundError:
            raise AuditError("journalctl not found; use --file instead")
        if proc.returncode != 0:
            raise AuditError(proc.stderr.strip() or "journalctl failed (try sudo)")
        return proc.stdout.splitlines(), "journal"

    path = path or DEFAULT_LOG
    if path == "-":
        return sys.stdin.read().splitlines(), "stdin"
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines(), path
    except FileNotFoundError:
        raise AuditError(f"file not found: {path} (try --journal)")
    except PermissionError:
        raise AuditError(f"permission denied: {path} (try: sudo {sys.argv[0]} ...)")
    except IsADirectoryError:
        raise AuditError(f"not a file: {path}")


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}")
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auth-audit.sh",
        description="Audit SSH brute-force attempts and unauthorized sudo use "
        "from an auth log (read-only). Prints JSON by default.",
        epilog="exit codes: 0 clean, 1 findings, 2 usage/read error",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--file", metavar="PATH",
        help=f"log file to read, '-' for stdin (default: {DEFAULT_LOG})",
    )
    source.add_argument(
        "--journal", action="store_true",
        help="read sshd/sudo entries from the systemd journal instead",
    )
    parser.add_argument(
        "--threshold", type=positive_int, default=DEFAULT_THRESHOLD, metavar="N",
        help=f"failed attempts from one IP to flag it (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="print a human-readable table instead of JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lines, source = read_lines(args.file, args.journal)
    except AuditError as exc:
        print(f"auth-audit: {exc}", file=sys.stderr)
        return 2

    report = analyze(lines, args.threshold, source)
    if args.summary:
        print(format_summary(report))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["suspicious_ips"] or report["sudo_violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
