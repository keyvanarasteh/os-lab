#!/usr/bin/env python3
"""Build, check, install and verify the os-lab Claude plugin from this checkout.

    scripts/claude-plugin.py doctor | status | check | verify
    scripts/claude-plugin.py build [--check]          generate the plugin's lab skills
    scripts/claude-plugin.py bundle [--out FILE]      Claude Desktop .mcpb
    scripts/claude-plugin.py updates [--online]       Claude Code and Claude Desktop
    scripts/claude-plugin.py extension-install        install or update in Claude Desktop
    scripts/claude-plugin.py install | update | configure | enable | disable [--scope S] [--yes]
    scripts/claude-plugin.py uninstall [--scope S]    asks in a terminal
    scripts/claude-plugin.py remove-duplicate --name N [--scope S]

Changes are previewed first. uninstall and remove-duplicate need an interactive terminal.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "console"))

import claude_desktop as desktop  # noqa: E402
import claude_plugin as engine  # noqa: E402


def change(args) -> int:
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if args.command in engine.TERMINAL_ONLY and not interactive:
        print("{0} needs an interactive terminal".format(args.command), file=sys.stderr)
        return 2
    check = None if args.auto_check is None else args.auto_check == "on"
    preview = engine.plan(ROOT, args.command, args.scope, args.name, update_check=check)
    print("This will run:")
    for command in preview["commands"]:
        print("  " + command)
    for step in preview["manual"]:
        print("by hand: " + step)
    for warning in preview["warnings"]:
        print("warning: " + warning)
    if not preview["commands"]:
        if args.command == "extension-install":
            os.makedirs(os.path.dirname(desktop.bundle_path(ROOT)), exist_ok=True)
            with open(desktop.bundle_path(ROOT), "wb") as handle:
                handle.write(engine.build_mcpb(ROOT))
            print("The bundle was built.")
        return 0
    if not (args.yes and args.command not in engine.TERMINAL_ONLY):
        if not interactive:
            print("Nothing was changed. Run in a terminal, or add --yes.", file=sys.stderr)
            return 2
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing was changed.")
            return 1
    result = engine.apply(ROOT, preview["token"], True, audience="terminal")
    for step in result["steps"]:
        print("{0} {1}\n    {2}".format("ok  " if step["ok"] else "FAIL", step["command"], step["message"]))
    print(result["next"])
    return 0 if result["ok"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("doctor", "status", "check", "verify", "updates", "build", "bundle") + engine.ACTIONS)
    parser.add_argument("--scope", default="user", choices=engine.SCOPES)
    parser.add_argument("--name", choices=engine.DUPLICATE_NAMES)
    parser.add_argument("--yes", action="store_true", help="skip the question (not for removals)")
    parser.add_argument("--check", action="store_true", help="build: fail when generated files differ")
    parser.add_argument("--online", action="store_true", help="updates: also ask for the published version")
    parser.add_argument("--auto-check", choices=("on", "off"),
                        help="install/configure: the daily update check at session start")
    parser.add_argument("--no-cli", action="store_true", help="check: skip rules that need Claude Code")
    parser.add_argument("--out", help="bundle: output file (default build/os-lab.mcpb)")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            drift = engine.skill_drift(ROOT) if args.check else engine.build_skills(ROOT)
            for line in drift:
                print(line)
            print("{0} difference(s){1}".format(len(drift), "" if args.check else " rewritten"))
            return 1 if args.check and drift else 0
        if args.command == "bundle":
            out = args.out or os.path.join(ROOT, "build", "os-lab.mcpb")
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            with open(out, "wb") as handle:
                handle.write(engine.build_mcpb(ROOT))
            print(out)
            return 0
        if args.command in engine.ACTIONS:
            return change(args)
        if args.command == "updates":
            report = desktop.updates(ROOT, online=args.online)
        elif args.command == "status":
            report = dict(engine.status(ROOT), claudeDesktop=desktop.status(ROOT))
        elif args.command == "check":
            report = engine.check(ROOT, use_cli=not args.no_cli)
        else:
            report = getattr(engine, args.command)(ROOT)
        print(json.dumps(report, indent=2))
        if args.command == "doctor":
            return 0 if report["ready"] else 1
        return 0 if report.get("ok", True) else 1
    except engine.PluginError as exc:
        print("{0}: {1}".format(exc.code, exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
