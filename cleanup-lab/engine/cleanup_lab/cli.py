"""Headless Cleanup Lab status, scan, plan and single-use clean commands."""
from __future__ import annotations

import argparse
import json
import sys

from .catalog import CatalogError, report as catalog_report
from .readiness import probe, repo_root
from . import history, scan, clean, cli_plans

USAGE_EXIT = 2


def _colour(text, code, stream):
    if not getattr(stream, "isatty", lambda: False)():
        return text
    return "{0}{1}\033[0m".format(code, text)


def _mark(found, stream):
    if found:
        return _colour("[ok]", "\033[32m", stream)
    return _colour("[--]", "\033[31m", stream)


def _safe(value):
    """Escape control characters so a path or process name cannot rewrite the terminal."""
    return "".join(
        character if character.isprintable() else "\\x{:02x}".format(ord(character))
        for character in str(value)
    )


def _status_lines(report, stream):
    engine = report["engine"]
    lines = [
        "Cleanup Lab {0} · {1} · {2}".format(
            _safe(engine["version"]), _safe(report["platform"]["label"]), _safe(report["state"])
        ),
    ]
    for item in report["requirements"]:
        lines.append(
            "  {0} {1:<32} {2}".format(
                _mark(item["found"], stream), _safe(item["label"]), _safe(item["detail"])
            )
        )
    lines.append("")
    lines.append("Capabilities:")
    for item in report["capabilities"]:
        lines.append(
            "  {0} {1:<32} {2}".format(
                _mark(item["found"], stream), _safe(item["label"]), _safe(item["detail"])
            )
        )
    if report["reasons"]:
        lines.append("")
        lines.append("What to fix:")
        lines.extend("  - {0}".format(_safe(reason)) for reason in report["reasons"])
    return lines


def _doctor_lines(report, stream):
    lines = _status_lines(report, stream)
    lines.append("")
    lines.append("Paths:")
    lines.append("  home        {0}".format(_safe(report["home"])))
    lines.append("  state       {0}".format(_safe(report["stateDir"])))
    lines.append("")
    lines.append("Hints:")
    for item in report["requirements"]:
        marker = "" if item["found"] else " (needs attention)"
        lines.append("  {0}{1}: {2}".format(_safe(item["label"]), marker, _safe(item["hint"])))
    readiness = {
        "ready": "Every readiness check passed; nothing has been scanned yet.",
        "needs-setup": "The engine is installed but something it needs is missing.",
        "unavailable": "This operating system is not supported by Cleanup Lab.",
    }[report["state"]]
    lines.append("  {0}".format(readiness))
    return lines


def _catalog_lines(report, stream):
    entries = report["entries"]
    count = len(entries)
    lines = [
        "Cleanup Lab catalog · {0} · {1} {2}".format(
            report["platform"], count, "entry" if count == 1 else "entries"
        )
    ]
    for entry in entries:
        flag = "pre-selected" if entry["defaultSelected"] else "not pre-selected"
        lines.append(
            "  {0:<22} {1:<26} {2:<11} {3}".format(entry["id"], entry["name"], entry["risk"], flag)
        )
        for path in entry["paths"]:
            if path["path"]:
                lines.append("      {0}".format(path["path"]))
            else:
                lines.append("      {0}  ({1})".format(path["template"], path["reason"]))
    return lines


def build_parser():
    parser = argparse.ArgumentParser(
        prog="labctl cleanup",
        description="Cleanup Lab: inspect readiness, scan, plan and confirmed clean.",
    )
    sub = parser.add_subparsers(dest="command", metavar="status|doctor|catalog|history|scan|plan|clean")
    for name, text in (
        ("status", "one-screen readiness summary"),
        ("doctor", "every check, path and hint"),
        ("catalog", "detector catalog for this computer, with resolved paths"),
        ("history", "recent cleanup runs from the private audit store"),
    ):
        command = sub.add_parser(name, help=text, description=text)
        command.add_argument("--json", action="store_true", help="print the probe as JSON")
        if name == "history":
            command.add_argument("--verify", action="store_true", help="verify the full HMAC chain")
    scan_cmd = sub.add_parser("scan", help="measure catalog targets read-only")
    scan_cmd.add_argument("--entry", action="append", dest="entry_ids", help="catalog detector id; repeatable")
    scan_cmd.add_argument("--json", action="store_true")
    plan_cmd = sub.add_parser("plan", help="build and save a ten-minute clean plan")
    plan_cmd.add_argument("--entry", action="append", required=True, dest="entry_ids",
                          help="catalog detector id; repeatable")
    plan_cmd.add_argument("--mode", choices=clean.MODES, default=clean.DEFAULT_MODE)
    plan_cmd.add_argument("--json", action="store_true")
    clean_cmd = sub.add_parser("clean", help="consume a confirmed plan once")
    clean_cmd.add_argument("--plan", required=True, dest="plan_id")
    clean_cmd.add_argument("--yes", action="store_true", help="confirm the plan's named mode")
    clean_cmd.add_argument("--json", action="store_true")
    return parser


def main(argv=None, stream=None):
    stream = sys.stdout if stream is None else stream
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(stream)
        return USAGE_EXIT
    if args.command in ("scan", "plan", "clean"):
        if args.command == "clean" and not args.yes:
            sys.stderr.write("cleanup clean: --yes is required to confirm the plan\n")
            return USAGE_EXIT
        try:
            if args.command == "scan":
                report = scan.scan_catalog(repo_root(), args.entry_ids)
            elif args.command == "plan":
                plan = clean.build_plan(repo_root(), args.entry_ids, mode=args.mode)
                cli_plans.save(plan)
                report = plan.to_dict()
            else:
                plan = cli_plans.claim(args.plan_id)
                measures = clean.verify_plan(plan)
                report = clean.execute_plan(plan, measures)
                history.append(report)
        except (clean.PlanError, history.HistoryError, CatalogError, OSError, ValueError) as exc:
            if args.json:
                stream.write(json.dumps({"error": str(exc)}) + "\n")
            else:
                sys.stderr.write("cleanup {0}: {1}\n".format(args.command, exc))
            return 1
        if args.json:
            stream.write(json.dumps(report, indent=2) + "\n")
        elif args.command == "scan":
            totals = report["totals"]
            stream.write("Scanned {0} path(s) · {1} bytes\n".format(totals["paths"], totals["sizeBytes"]))
        elif args.command == "plan":
            totals = report["totals"]
            stream.write("Plan {0} · {1} ready · {2} bytes · {3}\n".format(
                report["planId"], totals["ready"], totals["bytes"], report["mode"]))
        else:
            totals = report["totals"]
            stream.write("Cleaned {0} byte(s) · {1} failed · {2} skipped\n".format(
                totals["bytes"], totals["failed"], totals["skipped"]))
        if args.command == "clean":
            return 1 if report["cancelled"] or report["totals"]["failed"] or report["totals"]["skipped"] else 0
        if args.command == "plan":
            return 1 if report["totals"]["ready"] == 0 else 0
        return 1 if report.get("cancelled") or report["totals"]["unreadable"] else 0
    try:
        report = (catalog_report(repo_root()) if args.command == "catalog" else
                  history.read(verify=args.verify) if args.command == "history" else probe())
    except CatalogError as exc:
        sys.stderr.write("cleanup catalog: {0}\n".format(exc))
        return 1
    except (history.HistoryError, OSError, ValueError) as exc:
        sys.stderr.write("cleanup history: {0}\n".format(exc))
        return 1
    if args.json:
        stream.write(json.dumps(report, indent=2) + "\n")
    else:
        lines = {
            "status": _status_lines,
            "doctor": _doctor_lines,
            "catalog": _catalog_lines,
            "history": lambda value, _: [
                "Cleanup history · {0} run(s) · integrity verified".format(value["total"])
            ] + [
                "  #{0} {1} {2} · {3} bytes · {4} item(s)".format(
                    entry["id"], entry["result"]["mode"],
                    "cancelled" if entry["result"]["cancelled"] else "finished",
                    entry["result"]["totals"]["bytes"],
                    entry["result"]["totals"]["items"],
                ) for entry in value["entries"]
            ],
        }[args.command](report, stream)
        stream.write("\n".join(lines) + "\n")
    if args.command in ("catalog", "history"):
        return 0
    return 0 if report["state"] == "ready" else 1


if __name__ == "__main__":  # pragma: no cover - exercised through labctl
    sys.exit(main())
