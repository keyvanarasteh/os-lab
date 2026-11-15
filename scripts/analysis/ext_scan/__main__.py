"""Command line: python -m ext_scan scan <extension folder> [--json] [--fail-on GRADE]

Exit codes: 0 ok, 2 bad input, 3 risk grade is at or above --fail-on (for CI).
"""
import argparse
import json
import sys

from .manifest import ManifestError
from .scanner import GRADE_ORDER, format_text, scan


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ext_scan",
                                     description="PENT-02 browser extension scanner (lab use only)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scan", help="scan an unpacked extension folder")
    p.add_argument("folder")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    p.add_argument("--fail-on", choices=GRADE_ORDER,
                   help="exit with code 3 if the grade is this or worse")
    args = parser.parse_args(argv)

    try:
        result = scan(args.folder)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=True) if args.json else format_text(result))

    grade = result["risk"]["grade"]
    if args.fail_on and GRADE_ORDER.index(grade) >= GRADE_ORDER.index(args.fail_on):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
