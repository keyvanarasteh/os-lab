#!/usr/bin/env python3
"""Per-run audit report writer for the PENT-03 pipeline.

Every pipeline run can emit a timestamped, reproducible record (JSON for
machines, Markdown for humans) listing each step, whether it passed, and a
detail line. This makes a run auditable after the fact — useful in a report and
required by the lab's "log every step" expectation.

The renderers are pure functions over a plain dict, so they are unit-tested
offline with no pipeline or device.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import secrets
import sys

#: Any character that is not a safe filename atom becomes ``_`` so a crafted
#: package id can never introduce a path separator or traversal into a report path.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(value: str) -> str:
    """Return ``value`` reduced to safe filename characters (no path control)."""
    cleaned = _UNSAFE.sub("_", value or "")
    cleaned = cleaned.strip("._") or "unknown"
    return cleaned[:80]


def utc_stamp(now: _dt.datetime | None = None) -> str:
    """Return a filesystem-safe UTC timestamp like ``20261115T102233Z``."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def report_to_dict(report, *, now: _dt.datetime | None = None) -> dict:
    """Convert a pipeline ``PipelineReport`` (or compatible object) to a dict."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return {
        "task": "PENT-03",
        "timestamp": now.isoformat(),
        "package": report.package,
        "serial": report.serial,
        "ok": report.ok,
        "steps": [
            {"name": s.name, "ok": s.ok, "detail": s.detail} for s in report.steps
        ],
    }


def render_markdown(data: dict) -> str:
    """Render a run dict as a Markdown report."""
    status = "✅ success" if data.get("ok") else "❌ failed"
    lines = [
        f"# PENT-03 run — {data.get('package', '?')}",
        "",
        f"- **Status:** {status}",
        f"- **Timestamp:** {data.get('timestamp', '?')}",
        f"- **Serial:** {data.get('serial', '?')}",
        "",
        "| Step | Result | Detail |",
        "|------|--------|--------|",
    ]
    for s in data.get("steps", []):
        mark = "PASS" if s.get("ok") else "FAIL"
        lines.append(f"| {s.get('name')} | {mark} | {s.get('detail', '')} |")
    lines.append("")
    return "\n".join(lines)


def write_report(report, out_dir: str, *, now: _dt.datetime | None = None) -> tuple[str, str]:
    """Write JSON + Markdown reports into ``out_dir``. Returns both paths."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    data = report_to_dict(report, now=now)
    os.makedirs(out_dir, exist_ok=True)
    stamp = utc_stamp(now)
    # safe_name() strips any path control from the package id, and a short random
    # suffix keeps two runs in the same second from overwriting each other.
    base = f"pent03-{safe_name(data['package'])}-{stamp}-{secrets.token_hex(3)}"
    json_path = os.path.join(out_dir, base + ".json")
    md_path = os.path.join(out_dir, base + ".md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(data))
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    # Standalone: pretty-print an existing run JSON as Markdown.
    parser = argparse.ArgumentParser(description="Render a PENT-03 run JSON to Markdown.")
    parser.add_argument("json_file", help="a run report .json produced by the pipeline")
    args = parser.parse_args(argv)
    try:
        with open(args.json_file, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        print(f"cannot read {args.json_file}: {exc}", file=sys.stderr)
        return 1
    print(render_markdown(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
