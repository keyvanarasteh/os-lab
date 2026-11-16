#!/usr/bin/env python3
"""Verification report for a content contribution: the proof to paste into your pull request.

    python3 scripts/verify-content.py                      files changed since origin/master, as Markdown
    python3 scripts/verify-content.py --base origin/main   compare against another ref
    python3 scripts/verify-content.py --all                every content file, not only the changed ones
    python3 scripts/verify-content.py --out proof.md       write the report to a file as well

It runs the same checks CI runs (company schema, pack build with the client's own manifest
validation, secret scan) and lists each changed content file with its class, size and SHA-256,
so a reviewer can see exactly what would reach users. It never uploads anything. Exit code 1
when a check fails. Videos and animations are not part of this report: attach them to the
pull request itself (see docs/CONTENT.md, "Proof for contributions").
"""
from __future__ import annotations

import argparse
import hashlib
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "console"))
import content  # noqa: E402

MEDIA = (".mp4", ".mov", ".webm", ".gif", ".apng", ".mkv", ".avi")


def run(*cmd: str) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def changed(base: str) -> list[str]:
    code, out = run("git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD")
    if code != 0:
        code, out = run("git", "diff", "--name-only", "--diff-filter=ACMR", base)
    code2, untracked = run("git", "ls-files", "--others", "--exclude-standard")
    names = set(out.splitlines()) | set(untracked.splitlines() if code2 == 0 else [])
    return sorted(n for n in names if n)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/master")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    _, commit = run("git", "rev-parse", "--short", "HEAD")
    if args.all:
        _, listing = run("git", "ls-files")
        names = [n for n in listing.splitlines() if content.classify(n)]
    else:
        names = [n for n in changed(args.base) if content.classify(n) or n.lower().endswith(MEDIA)]

    lines = ["## os-lab content verification", "",
             f"- commit `{commit}`, compared with `{args.base}`" if not args.all else f"- commit `{commit}`, all content files",
             f"- {platform.system()} {platform.machine()}, Python {platform.python_version()}, {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", ""]
    failures = 0

    def check(title: str, *cmd: str) -> None:
        nonlocal failures
        code, out = run(*cmd)
        failures += code != 0
        lines.append(f"- {'PASS' if code == 0 else 'FAIL'}: {title}")
        if code != 0:
            lines.extend(["", "```text", *out.splitlines()[-25:], "```", ""])

    lines.append("### Checks")
    check("company manifests match the schema", sys.executable, "firewall-lab/scripts/validate.py")
    check("the pack builds and the client accepts its manifest (JSON validity, secret scan, allowed paths)", sys.executable, "scripts/build-content.py", "--check")
    committed_media = [n for n in names if n.lower().endswith(MEDIA) and (ROOT / n).is_file()]
    if committed_media:
        lines.append("- WARNING: video files are in the change. Proof recordings belong on the pull request, not in git (they bloat the history); ignore this if they are real project assets:")
        lines.extend(f"  - `{n}`" for n in committed_media)
    else:
        lines.append("- PASS: no video or image files committed")

    lines += ["", "### Content files in this change", ""]
    rows = [n for n in names if content.classify(n) and (ROOT / n).is_file()]
    if not rows:
        lines.append("None: this change does not touch anything that ships in a content pack.")
    else:
        lines += ["| File | Class | Size | SHA-256 |", "|---|---|---:|---|"]
        for n in rows:
            data = (ROOT / n).read_bytes()
            cls = content.classify(n)
            lines.append(f"| `{n}` | {cls}{' (runs inside other processes)' if cls == 'hooks' else ''} | {len(data)} | `{hashlib.sha256(data).hexdigest()[:16]}…` |")
        if any(content.classify(n) == "hooks" for n in rows):
            lines += ["", "This change touches Frida hooks. Users only receive hooks when they choose to install them, and a reviewer must read the code."]
    lines += ["", f"**Result: {'FAILED, see above' if failures else 'all checks passed'}**"]

    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
