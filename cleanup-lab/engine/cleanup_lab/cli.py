"""`labctl cleanup status|doctor|catalog|history|volumes [--json]`.

Mostly read: they print the readiness probe, the detector catalog, the audit
history or the volume inventory and change nothing. The `ignore` command
manages the typed ignore rules (CLN-17): `list` is read-only, `add` and
`remove` write the private-state store. The exit code follows the lab CLI
contract — ``0`` when the command succeeded, ``1`` when it could not (a
corrupt rules store, an unknown rule id), ``2`` for a usage error.
"""
from __future__ import annotations

import argparse
import json
import sys

from .catalog import CatalogError, report as catalog_report
from .readiness import probe, repo_root
from . import history, ignore, monitor, paths, volumes

USAGE_EXIT = 2


def _bookmarks_report():
    """CLNP-19: the bookmark list joined with the catalog's names and risks."""
    from . import bookmarks

    loaded = bookmarks.load()
    try:
        entries = {entry["id"]: entry for entry in catalog_report(repo_root())["entries"]}
    except CatalogError:
        entries = {}
    resolved = []
    for item in loaded["bookmarks"]:
        entry = entries.get(item["entryId"])
        resolved.append(dict(item, entry=None if entry is None else {
            "name": entry["name"], "risk": entry["risk"],
        }))
    return {"platform": paths.platform_id(), "bookmarks": resolved, "error": loaded["error"]}


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
    try:
        from .permissions import report as permissions_report

        lines.append("")
        lines.extend(_permissions_lines(permissions_report(), stream))
    except Exception as exc:  # the permission surface is optional; doctor still answers
        lines.append("")
        lines.append("Permissions: unavailable ({0})".format(exc))
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


def _permissions_lines(payload, stream):
    """CLNP-02: the doctor's permission lines (read-only probes, hints, deep link)."""
    lines = ["Permissions:"]
    for record in payload["permissions"]:
        if not record["applicable"]:
            continue
        if record["granted"] is True:
            mark = _mark(True, stream)
        elif record["granted"] is False:
            mark = _mark(False, stream)
        else:
            mark = "[??]"
        lines.append("  {0} {1:<32} {2}".format(
            mark, record["name"],
            "granted" if record["granted"] is True
            else "not granted" if record["granted"] is False
            else "unknown (no evidence yet)",
        ))
        for result in record["results"]:
            state = "readable" if result["readable"] else result["reason"] or "unreadable"
            lines.append("      {0}  ({1})".format(result["path"], state))
        if record["guidance"]:
            lines.append("      hint: {0}".format(record["guidance"]))
        if record["grantUrl"]:
            lines.append("      open: {0}".format(record["grantUrl"]))
    for item in payload.get("classification", {}).get("classified", []):
        lines.append("  ! {0}: needs {1}".format(item["path"], item["permissionId"]))
    return lines


def _volumes_lines(report, stream):
    count = len(report["volumes"])
    lines = [
        "Cleanup Lab volumes · {0} · {1} {2}".format(
            report["platform"], count, "volume" if count == 1 else "volumes"
        )
    ]
    if report.get("error"):
        lines.append("  {0}".format(_safe(report["error"])))
    for volume in report["volumes"]:
        usage = (
            "{0:.0f}% used".format(volume["usage"] * 100)
            if volume["usage"] is not None
            else "usage unknown"
        )
        mark = "[ok]" if volume["pressure"] == "ok" else "[!!]"
        suffix = " · home" if volume["isHome"] else ""
        lines.append(
            "  {0} {1:<28} {2:<8} {3:<10} {4}{5}".format(
                mark, _safe(volume["mountPoint"]), _safe(volume["filesystem"] or "?"),
                _safe(volume["kind"]), usage, suffix,
            )
        )
        if volume["error"]:
            lines.append("      {0}".format(_safe(volume["error"])))
    lines.extend("  ! {0}".format(_safe(text)) for text in report["warnings"])
    return lines


def _monitor_lines(report, stream):
    """CLNP-12: the labctl monitor status (read-only, engine-backed)."""
    lines = [
        "Cleanup Lab monitor · {0}".format("enabled" if report["enabled"] else "disabled"),
        "  runner      {0}".format("active" if report.get("running") else "not running in this process"),
        "  interval    every {0} s".format(report["intervalSeconds"]),
    ]
    if report["configError"]:
        lines.append("  config      {0}".format(_safe(report["configError"])))
    for entry in report["volumes"]:
        live = entry.get("volume")
        usage = (
            "{0} free".format(_safe("{0:.1f} GiB".format(live["freeBytes"] / 2**30)))
            if live and live.get("freeBytes") is not None
            else "no measurement yet"
        )
        state = report["state"]["volumes"].get("volumes:{0}".format(entry["mountPoint"])) or {}
        mark = "[!!]" if state.get("state") == "warning" else "[ok]" if state.get("state") == "ok" else "[--]"
        lines.append("  {0} {1:<28} {2:<10} warn < {3} GiB or {4:g}%".format(
            mark, _safe(entry["mountPoint"] or "home volume"), usage,
            entry["minFreeBytes"] / 2**30, entry["minFreePercent"],
        ))
    warnings = report["activeWarnings"]
    if warnings:
        lines.append("")
        lines.extend("  ! below threshold: {0}".format(_safe(item["volume"])) for item in warnings)
    events = report["state"]["events"]
    if events:
        lines.append("")
        lines.append("Recent events:")
        for event in events[-5:]:
            lines.append("  {0} {1} {2} {3}".format(
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event["at"])),
                event["kind"], _safe(event["volume"] or "-"), _safe(event["message"]),
            ))
    return lines


def _bookmarks_lines(report, stream):
    """CLNP-19: the labctl bookmarks list (read-only, with resolved names)."""
    items = report["bookmarks"]
    lines = ["Cleanup Lab bookmarks · {0} · {1} {2}".format(
        report.get("platform", "-"), len(items), "bookmark" if len(items) == 1 else "bookmarks")]
    if report.get("error"):
        lines.append("  {0}".format(_safe(report["error"])))
    for item in items:
        entry = item.get("entry") or {}
        name = entry.get("name") or item["entryId"]
        risk = entry.get("risk") or "?"
        flags = []
        if item["quickClean"]:
            flags.append("quick")
        if item["autoCleanHook"]["enabled"]:
            flags.append("hook")
        if item["sizeAlert"]["enabled"]:
            flags.append("alert")
        lines.append("  {0}. {1:<26} {2:<11} {3}".format(
            item["priority"], _safe(name), risk, " ".join(flags) or "-"))
        if item["autoCleanHook"]["lastRunAt"]:
            lines.append("      last automated run {0}".format(
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item["autoCleanHook"]["lastRunAt"]))))
    return lines


def _ignore_lines(rules):
    """The labctl ignore list: one row per rule, with type, value, note and id."""
    lines = ["Cleanup Lab ignore rules · {0} · {1} {2}".format(
        paths.platform_id(), len(rules), "rule" if len(rules) == 1 else "rules")]
    for rule in rules:
        note = "  — {0}".format(_safe(rule["note"])) if rule.get("note") else ""
        lines.append("  {0:<10} {1}{2}  ({3})".format(
            rule["type"], _safe(rule["value"]), note, rule["id"]))
    return lines


def _ignore_command(args, stream):
    """`labctl cleanup ignore list|add|remove` — exit 0 ok, 1 problem, 2 usage."""
    if args.action == "list":
        if args.first or args.second:
            sys.stderr.write("cleanup ignore list: no further arguments\n")
            return USAGE_EXIT
        rules, problem = ignore.load_rules()
        if problem is not None:
            if args.json:
                stream.write(json.dumps({"rules": [], "error": problem["message"]}, indent=2) + "\n")
            else:
                sys.stderr.write("cleanup ignore: {0}\n".format(problem["message"]))
            return 1
        if args.json:
            stream.write(json.dumps({"rules": rules, "error": None}, indent=2) + "\n")
        else:
            stream.write("\n".join(_ignore_lines(rules)) + "\n")
        return 0

    if args.action == "add":
        if not args.first or not args.second or args.first not in ignore.RULE_TYPES:
            sys.stderr.write(
                "cleanup ignore add: usage is `ignore add <path|glob|extension> <value> [--note ...]`\n"
            )
            return USAGE_EXIT
        try:
            rule = ignore.add_rule(args.first, args.second, note=args.note)
        except ValueError as exc:
            sys.stderr.write("cleanup ignore add: {0}\n".format(exc))
            return USAGE_EXIT
        except ignore.RulesError as exc:
            sys.stderr.write("cleanup ignore add: {0}\n".format(exc))
            return 1
        if args.json:
            stream.write(json.dumps({"added": rule, "error": None}, indent=2) + "\n")
        else:
            stream.write("Added {0} rule: {1}  ({2})\n".format(
                rule["type"], rule["value"], rule["id"]))
        return 0

    # remove
    if not args.first or args.second:
        sys.stderr.write("cleanup ignore remove: usage is `ignore remove <rule-id>`\n")
        return USAGE_EXIT
    try:
        removed = ignore.remove_rule(args.first)
    except ignore.RulesError as exc:
        sys.stderr.write("cleanup ignore remove: {0}\n".format(exc))
        return 1
    if not removed:
        sys.stderr.write("cleanup ignore remove: no rule with id {0}\n".format(args.first))
        return 1
    if args.json:
        stream.write(json.dumps({"removed": args.first, "error": None}, indent=2) + "\n")
    else:
        stream.write("Removed ignore rule {0}\n".format(args.first))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="labctl cleanup",
        description="Cleanup Lab: inspect readiness (read-only) and, from CLN-19, scan/plan/clean.",
    )
    sub = parser.add_subparsers(dest="command", metavar="status|doctor|catalog|history|volumes|monitor|bookmarks|ignore")
    for name, text in (
        ("status", "one-screen readiness summary"),
        ("doctor", "every check, path and hint"),
        ("catalog", "detector catalog for this computer, with resolved paths"),
        ("history", "recent cleanup runs from the private audit store"),
        ("volumes", "local volumes, capacity and disk-pressure warnings"),
        ("monitor", "the optional background monitor's state and events"),
        ("bookmarks", "bookmarked cleanup items with their flags"),
    ):
        command = sub.add_parser(name, help=text, description=text)
        command.add_argument("--json", action="store_true", help="print the probe as JSON")
        if name == "history":
            command.add_argument("--verify", action="store_true", help="verify the full HMAC chain")
    ignore_cmd = sub.add_parser(
        "ignore", help="the user's ignore rules the engine enforces (CLN-17)",
        description="List, add or remove ignore rules. The scan and the plan refuse "
                    "ignored paths and any folder holding an ignored path.",
    )
    ignore_cmd.add_argument("action", choices=("list", "add", "remove"))
    ignore_cmd.add_argument("first", nargs="?", metavar="TYPE_OR_ID",
                            help="add: the rule type (path, glob, extension); remove: the rule id")
    ignore_cmd.add_argument("second", nargs="?", metavar="VALUE",
                            help="add: the rule value (absolute path, glob pattern, or bare suffix)")
    ignore_cmd.add_argument("--note", help="add: an optional note stored with the rule")
    ignore_cmd.add_argument("--json", action="store_true", help="print the result as JSON")
    return parser


def main(argv=None, stream=None):
    stream = sys.stdout if stream is None else stream
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(stream)
        return USAGE_EXIT
    if args.command == "ignore":
        return _ignore_command(args, stream)
    try:
        report = (catalog_report(repo_root()) if args.command == "catalog" else
                  history.read(verify=args.verify) if args.command == "history" else
                  volumes.inventory() if args.command == "volumes" else
                  monitor.status() if args.command == "monitor" else
                  _bookmarks_report() if args.command == "bookmarks" else probe())
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
            "volumes": _volumes_lines,
            "monitor": _monitor_lines,
            "bookmarks": _bookmarks_lines,
        }[args.command](report, stream)
        stream.write("\n".join(lines) + "\n")
    if args.command == "volumes":
        return 1 if report.get("error") else 0
    if args.command == "monitor":
        return 1 if report.get("configError") else 0
    if args.command == "bookmarks":
        return 1 if report.get("error") else 0
    if args.command in ("catalog", "history"):
        return 0
    return 0 if report["state"] == "ready" else 1


if __name__ == "__main__":  # pragma: no cover - exercised through labctl
    sys.exit(main())
