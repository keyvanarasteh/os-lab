#!/usr/bin/env python3
"""Build, inspect and interactively install the local os-lab cursor plugin.

    scripts/cursor-plugin.py doctor | status | check | verify | updates [--online]
    scripts/cursor-plugin.py build [--check]
    scripts/cursor-plugin.py requirements [--area A]
    scripts/cursor-plugin.py install | update | uninstall
"""
import argparse
import json
import os
import sys

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "console"))
import host_plugin  # noqa: E402

HOST = "cursor"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "build", "check", "doctor", "status", "requirements", "updates",
        "install", "update", "uninstall", "verify"))
    parser.add_argument("--check", action="store_true", help="build: report skill drift without writing")
    parser.add_argument("--area", help="check or requirements: one catalog area")
    parser.add_argument("--online", action="store_true", help="updates: also ask GitHub for the published version")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            changed = (host_plugin.skill_drift(ROOT, HOST) if args.check
                       else host_plugin.build_skills(ROOT, HOST))
            for line in changed:
                print(line)
            return int(args.check and bool(changed))
        if args.command in ("install", "update", "uninstall"):
            preview = host_plugin.plan(ROOT, HOST, args.command)
            print("This will run:")
            for command in preview["commands"]:
                print("  " + command)
            for warning in preview.get("warnings") or []:
                print("Warning: " + warning, file=sys.stderr)
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                print("Nothing changed: this requires an interactive terminal.", file=sys.stderr)
                return 2
            if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Nothing changed.")
                return 1
            result = host_plugin.apply(ROOT, HOST, preview["token"], True, audience="terminal")
            print(json.dumps(result, indent=2))
            return int(not result["ok"])
        if args.command == "check":
            result = host_plugin.check(ROOT, HOST, args.area)
        elif args.command == "requirements":
            result = host_plugin.requirements(HOST, args.area)
        elif args.command == "updates":
            result = host_plugin.updates(ROOT, HOST, online=args.online)
        else:
            result = getattr(host_plugin, args.command)(ROOT, HOST)
        print(json.dumps(result, indent=2))
        return int(result.get("ok") is False or result.get("ready") is False)
    except host_plugin.PluginError as exc:
        print(exc.code + ": " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
