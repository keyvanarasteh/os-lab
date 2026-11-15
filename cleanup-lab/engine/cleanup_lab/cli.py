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
import os
import sys
import time

from .catalog import CatalogError, load as catalog_load, report as catalog_report
from .readiness import probe, repo_root
from . import clean, history, ignore, monitor, paths, plan_store, scan, schedules, settings, volumes

USAGE_EXIT = 2


def _load_catalog():
    """The catalog for this computer, resolved against the real environment."""
    return catalog_load(repo_root(), dict(os.environ))


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


def _settings_command(args, stream):
    """`labctl cleanup settings [show] | settings set <key> <value>` — 0/1/2."""
    if args.action == "show":
        if args.first or args.second:
            sys.stderr.write("cleanup settings show: no further arguments\n")
            return USAGE_EXIT
        values, problem = settings.all_values()
        if problem is not None:
            if args.json:
                stream.write(json.dumps({"settings": values, "error": problem["message"]}, indent=2) + "\n")
            else:
                sys.stderr.write("cleanup settings: {0}\n".format(problem["message"]))
            return 1
        if args.json:
            stream.write(json.dumps({"settings": values, "error": None}, indent=2) + "\n")
        else:
            lines = ["Cleanup Lab settings · {0}".format(paths.platform_id())]
            for key, allowed in settings.SETTINGS.items():
                lines.append("  {0:<14} {1}   (one of: {2})".format(key, values[key], ", ".join(allowed)))
            stream.write("\n".join(lines) + "\n")
        return 0

    # set
    if not args.first or not args.second:
        sys.stderr.write("cleanup settings set: usage is `settings set <key> <value>`\n")
        return USAGE_EXIT
    if args.first not in settings.SETTINGS:
        sys.stderr.write("cleanup settings set: unknown setting {0}; known: {1}\n".format(
            args.first, ", ".join(sorted(settings.SETTINGS))))
        return USAGE_EXIT
    if args.second not in settings.SETTINGS[args.first]:
        sys.stderr.write("cleanup settings set: {0} must be one of: {1}\n".format(
            args.first, ", ".join(settings.SETTINGS[args.first])))
        return USAGE_EXIT
    try:
        stored = settings.set({args.first: args.second})
    except settings.SettingsError as exc:
        sys.stderr.write("cleanup settings set: {0}\n".format(exc))
        return 1
    if args.json:
        stream.write(json.dumps({"settings": stored, "error": None}, indent=2) + "\n")
    else:
        stream.write("Set {0} = {1}\n".format(args.first, stored[args.first]))
    return 0


def _scan_lines(result):
    """The labctl scan summary: one row per entry, then the honest totals."""
    lines = ["Cleanup Lab scan · {0} · {1} · measured {2} across {3} categories".format(
        result["platform"], "cancelled" if result["cancelled"] else "complete",
        _bytes(result["totals"]["sizeBytes"]), result["totals"]["entries"])]
    for entry in result["entries"]:
        ignored = sum(1 for p in entry["paths"] if p.get("ignored"))
        bits = []
        if ignored:
            bits.append("{0} ignored".format(ignored))
        if entry["unreadable"]:
            bits.append("{0} unreadable".format(len(entry["unreadable"])))
        lines.append("  {0:<28} {1:>12}  {2}".format(
            _safe(entry["id"]), _bytes(entry["sizeBytes"]), " · ".join(bits)))
        for item in entry["unreadable"][:3]:  # the first few, sanitised; more in --json
            lines.append("      unreadable: {0}".format(_safe(item)))
    return lines


def _plan_lines(payload):
    """The labctl plan preview: what is ready, what is refused, and the deadline."""
    totals = payload["totals"]
    lines = ["Cleanup Lab plan · {0} · {1} · {2} ready ({3}) · {4} skipped · expires in {5}s".format(
        payload["planId"], payload["mode"], totals["ready"], _bytes(totals["bytes"]),
        totals["items"] - totals["ready"], max(0, int(payload["expiresAt"] - payload["createdAt"])))]
    lines.append("  Review it, then clean with: labctl cleanup clean --plan {0} --yes".format(payload["planId"]))
    for item in payload["items"]:
        if item["status"] == "ready":
            lines.append("  + {0:>12}  {1}".format(_bytes(item["sizeBytes"]), _safe(item["path"])))
        else:
            lines.append("  - {0:<10} {1} · {2}".format(item["code"], _safe(item["path"] or "-"), item["reason"]))
    return lines


def _clean_lines(result):
    """The labctl clean report: honest counts first, then every path."""
    totals = result["totals"]
    lines = ["Cleanup Lab clean · {0} · {1} · {2} item(s) · {3}".format(
        result["mode"], "cancelled" if result["cancelled"] else "finished",
        totals["items"], _bytes(totals["bytes"]))]
    for row in result["results"]:
        if row["status"] in ("trashed", "deleted", "shredded"):
            lines.append("  {0:>10}  {1}  {2}".format(row["status"], _bytes(row["bytes"]), _safe(row["path"])))
        elif row["status"] == "skipped":
            lines.append("  {0:>10}  {1}  {2}".format("skipped", row["code"], row["reason"]))
        else:
            lines.append("  {0:>10}  {1}  {2}".format(row["status"], _safe(row["path"] or "-"), row["error"] or ""))
    return lines


def _bytes(value):
    """A short human byte count for the CLI summaries."""
    size = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return "{0:.0f} {1}".format(size, unit) if unit == "B" else "{0:.1f} {1}".format(size, unit)
        size /= 1024
    return "{0:.1f} TiB".format(size)


def _collect_entries(args, catalog_entries):
    """Validate the ``--entry`` list against the catalog; ``None`` means all."""
    if not args.entry:
        return None
    known = {entry["id"] for entry in catalog_entries}
    unknown = [eid for eid in args.entry if eid not in known]
    if unknown:
        raise ValueError("Unknown detector id(s): {0}".format(", ".join(unknown)))
    return list(args.entry)


def _scan_command(args, stream):
    """`labctl cleanup scan` — read-only, the same engine the console job runs."""
    scan_mod = scan
    if args.workers is not None and not 1 <= args.workers <= scan_mod.MAX_WORKERS:
        sys.stderr.write("cleanup scan: workers must be between 1 and {0}\n".format(scan_mod.MAX_WORKERS))
        return USAGE_EXIT
    try:
        entries = _load_catalog()
        entry_ids = _collect_entries(args, entries)
    except ValueError as exc:
        sys.stderr.write("cleanup scan: {0}\n".format(exc))
        return USAGE_EXIT
    except Exception as exc:
        sys.stderr.write("cleanup scan: the detector catalog is invalid: {0}\n".format(exc))
        return 1
    try:
        result = scan_mod.scan_catalog(
            repo_root(), entry_ids, workers=args.workers, env=dict(os.environ),
        )
    except KeyboardInterrupt:
        sys.stderr.write("cleanup scan: cancelled\n")
        return 1
    except scan_mod.ScanError as exc:
        sys.stderr.write("cleanup scan: {0}\n".format(exc))
        return 1
    if args.json:
        stream.write(json.dumps(result, indent=2) + "\n")
    else:
        stream.write("\n".join(_scan_lines(result)) + "\n")
    return 0


def _plan_command(args, stream):
    """`labctl cleanup plan` — build and store a confirmable plan (read-only)."""
    clean_mod = clean
    scan_mod = scan
    if args.workers is not None and not 1 <= args.workers <= scan_mod.MAX_WORKERS:
        sys.stderr.write("cleanup plan: workers must be between 1 and {0}\n".format(scan_mod.MAX_WORKERS))
        return USAGE_EXIT
    try:
        entries = _load_catalog()
        entry_ids = _collect_entries(args, entries)
    except ValueError as exc:
        sys.stderr.write("cleanup plan: {0}\n".format(exc))
        return USAGE_EXIT
    except Exception as exc:
        sys.stderr.write("cleanup plan: the detector catalog is invalid: {0}\n".format(exc))
        return 1
    try:
        plan = clean_mod.build_plan(repo_root(), entry_ids, mode=args.mode, workers=args.workers,
                                    env=dict(os.environ))
        if plan.payload is None:
            sys.stderr.write("cleanup plan: the plan build was cancelled\n")
            return 1
        plan_store.save(plan, env=dict(os.environ))
    except clean_mod.PlanError as exc:
        sys.stderr.write("cleanup plan: {0} (code: {1})\n".format(exc, exc.code))
        return 1
    if args.json:
        stream.write(json.dumps(plan.payload, indent=2) + "\n")
    else:
        stream.write("\n".join(_plan_lines(plan.payload)) + "\n")
    return 0


def _clean_command(args, stream):
    """`labctl cleanup clean --plan <id> --yes` — the only mutating command.

    The plan is claimed from the store (single-use, atomically), verified
    again, executed and audited — the same engine flow the console job runs.
    Without ``--yes`` nothing is ever removed.
    """
    clean_mod = clean
    if not args.yes:
        sys.stderr.write(
            "cleanup clean: refusing to run without --yes; review the plan with "
            "`labctl cleanup plan` first.\n"
        )
        return USAGE_EXIT
    if not args.plan:
        sys.stderr.write("cleanup clean: --plan <id> is required\n")
        return USAGE_EXIT
    try:
        history.prepare()
    except (history.HistoryError, OSError) as exc:
        sys.stderr.write("cleanup clean: audit history is unavailable: {0}\n".format(exc))
        return 1
    try:
        claimed, record = plan_store.claim(args.plan, env=dict(os.environ))
    except plan_store.PlanStoreError as exc:
        sys.stderr.write("cleanup clean: {0}\n".format(exc))
        return 1
    try:
        plan = clean_mod.Plan(
            id=record["id"], mode=record["mode"],
            created_at=record["createdAt"], expires_at=record["expiresAt"],
            payload=record["payload"],
            # JSON round-trips the fingerprint tuples as lists; rebuild them so
            # verify_plan compares like with like.
            fingerprints={path: tuple(key) for path, key in record["fingerprints"].items()},
            progress=record.get("progress", {}),
        )
        try:
            if plan.expires_at < time.time():
                raise clean_mod.PlanError("This plan expired; build a new one.", "expired")
            if plan.mode not in clean_mod.MODES:
                raise clean_mod.PlanError("The plan names an unknown mode.", "plan-invalid")
            measures = clean_mod.verify_plan(plan)
            result = clean_mod.execute_plan(plan, measures)
        except clean_mod.PlanError as exc:
            sys.stderr.write("cleanup clean: {0} (code: {1})\n".format(exc, exc.code))
            return 1
        except (OSError, clean_mod.CleanError) as exc:
            sys.stderr.write("cleanup clean: {0}\n".format(exc))
            return 1
        try:
            history.append(result)
        except (history.HistoryError, OSError) as exc:
            # The run happened and is reported; the audit gap is a problem (rule 6).
            sys.stderr.write("cleanup clean: the run could not be audited: {0}\n".format(exc))
            result = dict(result, auditError=str(exc))
    finally:
        plan_store.discard(claimed)
    if args.json:
        stream.write(json.dumps(result, indent=2) + "\n")
    else:
        stream.write("\n".join(_clean_lines(result)) + "\n")
    totals = result["totals"]
    return 1 if totals["failed"] or result["cancelled"] else 0


def _schedules_command(args, stream):
    """`labctl cleanup schedules list|add|remove|enable|disable` — 0/1/2."""
    if args.action == "list":
        if args.first or args.second:
            sys.stderr.write("cleanup schedules list: no further arguments\n")
            return USAGE_EXIT
        rows, problem = schedules.list_schedules()
        if problem is not None:
            if args.json:
                stream.write(json.dumps({"schedules": [], "error": problem["message"]}, indent=2) + "\n")
            else:
                sys.stderr.write("cleanup schedules: {0}\n".format(problem["message"]))
            return 1
        if args.json:
            stream.write(json.dumps({"schedules": rows, "error": None}, indent=2) + "\n")
        else:
            lines = ["Cleanup Lab schedules · {0} · {1} {2}".format(
                paths.platform_id(), len(rows), "schedule" if len(rows) == 1 else "schedules")]
            for row in rows:
                state = "enabled" if row["enabled"] else "disabled"
                last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["lastRunAt"])) if row["lastRunAt"] else "never"
                lines.append("  {0:<9} {1}  last run {2}  ({3})".format(
                    state, _safe(row["cron"]), last, row["id"]))
            stream.write("\n".join(lines) + "\n")
        return 0
    if args.action == "add":
        if not args.first or args.second:
            sys.stderr.write("cleanup schedules add: usage is `schedules add '<cron>'`\n")
            return USAGE_EXIT
        try:
            row = schedules.add(args.first)
        except ValueError as exc:
            sys.stderr.write("cleanup schedules add: {0}\n".format(exc))
            return USAGE_EXIT
        except schedules.SchedulesError as exc:
            sys.stderr.write("cleanup schedules add: {0}\n".format(exc))
            return 1
        if args.json:
            stream.write(json.dumps({"added": row, "error": None}, indent=2) + "\n")
        else:
            stream.write("Added schedule {0}  ({1})\n".format(row["cron"], row["id"]))
        return 0
    if args.action in ("enable", "disable"):
        if not args.first or args.second:
            sys.stderr.write("cleanup schedules {0}: usage is `schedules {0} <id>`\n".format(args.action))
            return USAGE_EXIT
        try:
            row = schedules.set_enabled(args.first, args.action == "enable")
        except ValueError as exc:
            sys.stderr.write("cleanup schedules {0}: {1}\n".format(args.action, exc))
            return 1
        except schedules.SchedulesError as exc:
            sys.stderr.write("cleanup schedules {0}: {1}\n".format(args.action, exc))
            return 1
        if args.json:
            stream.write(json.dumps({"schedule": row, "error": None}, indent=2) + "\n")
        else:
            stream.write("{0} schedule {1}  ({2})\n".format(
                "Enabled" if row["enabled"] else "Disabled", row["cron"], row["id"]))
        return 0
    # remove
    if not args.first or args.second:
        sys.stderr.write("cleanup schedules remove: usage is `schedules remove <id>`\n")
        return USAGE_EXIT
    try:
        removed = schedules.remove(args.first)
    except schedules.SchedulesError as exc:
        sys.stderr.write("cleanup schedules remove: {0}\n".format(exc))
        return 1
    if not removed:
        sys.stderr.write("cleanup schedules remove: no schedule with id {0}\n".format(args.first))
        return 1
    if args.json:
        stream.write(json.dumps({"removed": args.first, "error": None}, indent=2) + "\n")
    else:
        stream.write("Removed schedule {0}\n".format(args.first))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="labctl cleanup",
        description="Cleanup Lab: inspect readiness (read-only) and, from CLN-19, scan/plan/clean.",
    )
    sub = parser.add_subparsers(dest="command", metavar="status|doctor|catalog|history|volumes|monitor|bookmarks|ignore|settings|schedules|scan|plan|clean")
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
    settings_cmd = sub.add_parser(
        "settings", help="the typed engine settings (CLN-14)",
        description="Show the settings store or set one typed value. A corrupt store "
                    "is reported honestly; shred fails closed until it is fixed.",
    )
    settings_cmd.add_argument("action", nargs="?", default="show", choices=("show", "set"))
    settings_cmd.add_argument("first", nargs="?", metavar="KEY", help="set: the setting key (e.g. shredPolicy)")
    settings_cmd.add_argument("second", nargs="?", metavar="VALUE", help="set: the value (e.g. 1-pass)")
    settings_cmd.add_argument("--json", action="store_true", help="print the result as JSON")
    schedules_cmd = sub.add_parser(
        "schedules", help="scheduled dry-run scans (CLN-18)",
        description="A schedule fires a scan-only job on its cron; it can never clean.",
    )
    schedules_cmd.add_argument("action", nargs="?", default="list",
                               choices=("list", "add", "remove", "enable", "disable"))
    schedules_cmd.add_argument("first", nargs="?", metavar="CRON_OR_ID",
                               help="add: the cron expression (quoted); remove/enable/disable: the schedule id")
    schedules_cmd.add_argument("second", nargs="?", help=argparse.SUPPRESS)
    schedules_cmd.add_argument("--json", action="store_true", help="print the result as JSON")
    # --- CLN-19: the headless scan / plan / clean flow ---
    for name, text in (
        ("scan", "measure the catalog entries for this computer (read-only)"),
        ("plan", "build a confirmable plan and store it (read-only)"),
        ("clean", "run one stored plan; requires --plan <id> and --yes"),
    ):
        command = sub.add_parser(name, help=text, description=text)
        command.add_argument("--entry", action="append", metavar="ID",
                             help="restrict to this catalog id (repeatable; default: every entry)")
        command.add_argument("--workers", type=int, default=None, metavar="N",
                             help="parallel measurement workers (1-{0})".format(scan.MAX_WORKERS))
        command.add_argument("--json", action="store_true", help="print the full result as JSON")
        if name == "plan":
            command.add_argument("--mode", default=clean.DEFAULT_MODE,
                                 choices=list(clean.MODES), metavar="MODE",
                                 help="trash (default), delete or shred (shred needs the settings policy)")
        if name == "clean":
            command.add_argument("--plan", metavar="ID", help="the plan id from `labctl cleanup plan`")
            command.add_argument("--yes", action="store_true",
                                 help="required: cleaning never runs without it")
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
    if args.command == "settings":
        return _settings_command(args, stream)
    if args.command == "schedules":
        return _schedules_command(args, stream)
    if args.command == "scan":
        return _scan_command(args, stream)
    if args.command == "plan":
        return _plan_command(args, stream)
    if args.command == "clean":
        return _clean_command(args, stream)
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
