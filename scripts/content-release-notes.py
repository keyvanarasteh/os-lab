#!/usr/bin/env python3
"""Describe the actual content changes since the last published content pack."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "console"))
import content  # noqa: E402


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence", required=True, type=int)
    args = parser.parse_args()
    try:
        base = git("rev-parse", "content-latest")
        raw = git("diff", "--name-status", f"{base}..HEAD", "--", "firewall-lab", "ios-lab/knowledge", "docs/legal", "android-lab/lab/hooks")
    except subprocess.CalledProcessError:
        raw = ""
    changes = []
    for line in raw.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        status, path = fields[0], fields[-1]
        if content.classify(path) or status.startswith("D"):
            changes.append((status, path))
    print(f"Signed content pack, sequence {args.sequence}.")
    print()
    print(f"Source commit: `{git('rev-parse', '--short', 'HEAD')}`.")
    print()
    print("### Changes since the previous content release")
    print()
    if changes:
        for status, path in changes[:100]:
            verb = "Added" if status.startswith("A") else "Removed" if status.startswith("D") else "Updated"
            print(f"- {verb} `{path}`")
        if len(changes) > 100:
            print(f"- …and {len(changes) - 100} more files")
    else:
        print("- No content file changes; this release refreshes the signed pack metadata.")
    print()
    print("The app verifies the signed manifest and every included file before installing this pack.")


if __name__ == "__main__":
    main()
