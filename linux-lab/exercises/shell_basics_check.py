#!/usr/bin/env python3
"""OS-11: read-only shell directory exercise checker for a Linux lab."""

import argparse
import errno
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
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=current)
            except OSError as exc:
                if exc.errno not in (errno.ELOOP, errno.ENOTDIR):
                    raise
                # O_NOFOLLOW reports a symlink and a plain file the same way; ask lstat.
                parent_mode = os.stat(part, dir_fd=current, follow_symlinks=False).st_mode
                return "symlink" if stat.S_ISLNK(parent_mode) else "blocked-parent"
            os.close(current)
            current = child
        mode = os.stat(parts[-1], dir_fd=current, follow_symlinks=False).st_mode
        if stat.S_ISLNK(mode):
            return "symlink"
        valid = stat.S_ISDIR(mode) if expected == "directory" else stat.S_ISREG(mode)
        if not valid:
            return "wrong-type"
        if expected == "file":
            # Existence is not enough: the score file must be openable (contents are not read).
            try:
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=current)
            except OSError:
                return "unreadable"
            os.close(fd)
        return "pass"
    except FileNotFoundError:
        return "missing"
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
    if status == "symlink":
        return "Sembolik bag kabul edilmez; bu yol ve ust yollar gercek klasor/dosya olmali."
    if status == "blocked-parent":
        return "Bir ust yol klasor degil (normal dosya olabilir). Mevcut nesneyi inceleyin; otomatik silinmez."
    if status == "wrong-type":
        return f"Bu yolda {expected} bekleniyor. Mevcut nesneyi inceleyin; otomatik silinmez."
    if status == "unreadable":
        return "Dosya var ama okunamiyor. Izinleri kontrol edin: ls -l ve chmod u+r."
    return "Yol okunamadi. Lab klasorunun erisim izinlerini kontrol edin."


def clean(text):
    """Escape every non-printable character, newlines included, in user-derived text."""
    return "".join(c if c.isprintable() else ascii(c)[1:-1] for c in str(text))


def grade(root):
    # Let the OS resolve the path (".." after a symlink included); only the final
    # component must not be a symlink.
    root_fd = os.open(os.path.expanduser(os.fspath(root)),
                      os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        resolved = True
        try:
            root = Path(os.readlink(f"/proc/self/fd/{root_fd}"))
        except OSError:
            resolved = False
            root = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
        results = []
        for relative, expected in EXPECTED:
            status = inspect_path(root_fd, relative, expected)
            results.append({"path": relative, "expected": expected, "status": status,
                            "hint": hint_for(root, relative, expected, status)})
        # The report is a snapshot; fail loudly if the lab root itself was swapped meanwhile.
        if resolved:
            try:
                now, held = os.stat(root), os.fstat(root_fd)
            except FileNotFoundError:
                raise OSError(errno.ESTALE, "lab root changed during the check") from None
            except OSError:
                now = held = None  # cannot tell; the per-path statuses already carry the errors
            if now is not None and (now.st_dev, now.st_ino) != (held.st_dev, held.st_ino):
                raise OSError(errno.ESTALE, "lab root changed during the check")
    finally:
        os.close(root_fd)
    passed = sum(row["status"] == "pass" for row in results)
    return {"schema_version": 1, "root": str(root), "passed": passed,
            "total": len(results), "success": passed == len(results), "results": results}


def render(report):
    lines = ["OS-11 | Shell Basics Checker", f"Lab: {ascii(report['root'])}"]
    for row in report["results"]:
        label = "PASS" if row["status"] == "pass" else "FAIL"
        lines.append(f"[{label}] {clean(row['path'])} ({row['expected']}, {row['status']})")
        if label == "FAIL":
            lines.append("  Ipucu: " + clean(row["hint"]))
    lines.append(f"Sonuc: {report['passed']}/{report['total']} dogru")
    lines.append("Dosyalar degistirilmedi. Sonuc, kontrol anindaki bir goruntudur ve yalnizca ornek yapiyi denetler.")
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
            args.root = input("Alistirma klasoru: ")
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
    # render() already escapes user-derived fields; stdout may still be ASCII-only.
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(output.encode(encoding, errors="backslashreplace").decode(encoding))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
