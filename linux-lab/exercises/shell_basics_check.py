#!/usr/bin/env python3
"""OS-11: read-only shell directory exercise checker for a Linux lab."""

import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import sys


STUDENTS = ("ali", "eda", "aleyna")
FOLDERS = ("odevler", "sinavlar", "sunumlar")
EXPECTED = tuple(
    item
    for student in STUDENTS
    for item in [(student, "directory")]
    + [(f"{student}/{folder}", "directory") for folder in FOLDERS]
    + [(f"{student}/puan.txt", "file")]
)


def inspect_path(root_fd, relative, expected):
    """Inspect relative to the open root; never traverse child symlinks."""
    current = os.dup(root_fd)
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=current)
            os.close(current)
            current = child
        mode = os.stat(parts[-1], dir_fd=current, follow_symlinks=False).st_mode
        if stat.S_ISLNK(mode):
            return "symlink"
        valid = stat.S_ISDIR(mode) if expected == "directory" else stat.S_ISREG(mode)
        return "pass" if valid else "wrong-type"
    except FileNotFoundError:
        return "missing"
    except NotADirectoryError:
        return "blocked-parent"
    except OSError:
        return "unavailable"
    finally:
        os.close(current)


def hint_for(root, relative, expected, status):
    if status == "pass":
        return "Dogru konum ve tur."
    if status == "missing":
        target = shlex.quote(str(root / relative))
        if expected == "directory":
            return f"Labda kendiniz olusturun: mkdir -p -- {target}"
        return f"Once ust klasoru olusturun, sonra: touch -- {target}"
    if status in {"symlink", "blocked-parent"}:
        return "Sembolik bag kabul edilmez; ust yollarin gercek klasor oldugunu kontrol edin."
    if status == "wrong-type":
        return f"Bu yolda {expected} bekleniyor. Mevcut nesneyi inceleyin; otomatik silinmez."
    return "Yol okunamadi. Lab klasorunun erisim izinlerini kontrol edin."


def grade(root):
    root = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        results = []
        for relative, expected in EXPECTED:
            status = inspect_path(root_fd, relative, expected)
            results.append({"path": relative, "expected": expected, "status": status,
                            "hint": hint_for(root, relative, expected, status)})
    finally:
        os.close(root_fd)
    passed = sum(row["status"] == "pass" for row in results)
    return {"schema_version": 1, "root": str(root), "passed": passed,
            "total": len(results), "success": passed == len(results), "results": results}


def render(report):
    lines = ["OS-11 | Shell Basics Checker", f"Lab: {ascii(report['root'])}"]
    for row in report["results"]:
        label = "PASS" if row["status"] == "pass" else "FAIL"
        lines.append(f"[{label}] {row['path']} ({row['expected']}, {row['status']})")
        if label == "FAIL":
            lines.append("  Ipucu: " + row["hint"])
    lines.append(f"Sonuc: {report['passed']}/{report['total']} dogru")
    lines.append("Dosyalar degistirilmedi. Bu sonuc yalnizca ornek yapiyi denetler.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", help="exercise root containing ali, eda and aleyna")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument("--show-exercise", action="store_true", help="list the expected paths")
    parser.add_argument("--interactive", action="store_true", help="ask for the lab root")
    args = parser.parse_args(argv)
    if args.show_exercise:
        if args.json or args.interactive or args.root:
            parser.error("--show-exercise must be used alone")
        for relative, expected in EXPECTED:
            print(f"{expected:9} {relative}")
        return 0
    if args.interactive:
        if args.json or args.root:
            parser.error("--interactive cannot be combined with root or --json")
        try:
            args.root = input("Alistirma klasoru: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("Giris iptal edildi.", file=sys.stderr)
            return 2
    if not args.root:
        parser.error("provide a lab root or use --interactive")
    if not sys.platform.startswith("linux"):
        parser.error("run this checker inside your Linux lab")
    try:
        report = grade(args.root)
    except OSError as exc:
        message = f"Lab klasoru acilamadi (errno={exc.errno}); gercek ve erisilebilir bir klasor secin."
        if args.json:
            print(json.dumps({"schema_version": 1, "success": False, "error": message}))
        else:
            print(message, file=sys.stderr)
        return 2
    output = json.dumps(report, indent=2, ensure_ascii=True) if args.json else render(report)
    # Escape control characters in user-selected paths and support ASCII terminals.
    if not args.json:
        output = "".join(c if c == "\n" or c.isprintable() else ascii(c)[1:-1] for c in output)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(output.encode(encoding, errors="backslashreplace").decode(encoding))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
