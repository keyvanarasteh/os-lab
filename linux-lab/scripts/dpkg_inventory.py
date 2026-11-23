#!/usr/bin/env python3
"""OS-23: salt okunur dpkg envanteri, dosya listesi ve tam yol sahipliği.

Python 3.11+ ve Debian/Ubuntu dpkg gerekir. Root, shell, ağ veya paket değişikliği yoktur.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys


class InventoryError(Exception):
    """A collector failed; never disguise this as an empty successful result."""


def run_dpkg(*args: str, admindir: str | None = None) -> str:
    env = dict(os.environ, LC_ALL="C", LANG="C", COLUMNS="1000")
    try:
        result = subprocess.run(
            ["dpkg", *(["--admindir=" + admindir] if admindir else []), *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20, env=env, check=False,
        )
    except FileNotFoundError as exc:
        raise InventoryError("dpkg bulunamadı; Debian veya Ubuntu üzerinde çalıştırın") from exc
    except subprocess.TimeoutExpired as exc:
        raise InventoryError("dpkg, 20 saniyelik süre sınırını aştı") from exc
    except OSError as exc:
        raise InventoryError(f"dpkg çalıştırılamadı: {exc}") from exc
    if result.returncode:
        raise InventoryError(result.stderr.strip() or f"dpkg çıkış kodu: {result.returncode}")
    return result.stdout


def package_name(value: str) -> str:
    # Concrete package only: no dpkg patterns or option injection.
    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+(?::[a-z0-9][a-z0-9-]*)?", value):
        raise argparse.ArgumentTypeError("somut bir Debian paket adı girin (isteğe bağlı :mimari eki)")
    return value


def literal_path(value: str) -> str:
    if not value.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise argparse.ArgumentTypeError("kontrol karakteri içermeyen mutlak dosya yolu girin")
    return value


def parse_inventory(output: str) -> list[dict]:
    records = []
    if not output.strip():
        return records
    started = False
    for line in output.splitlines():
        if line.startswith("+++-"):
            started = True
            continue
        if not started or not line.strip():
            continue
        # dpkg -l: three status columns, space, name/version/arch/description.
        if len(line) < 5 or line[3] != " ":
            raise InventoryError("beklenmeyen dpkg -l kaydı")
        fields = line[4:].split(None, 3)
        if len(fields) != 4:
            raise InventoryError("eksik dpkg -l kaydı")
        name, version, architecture, description = fields
        status = line[:3]
        records.append(dict(package=name, version=version, architecture=architecture,
                            description=description, status=status,
                            installed=status[1] == "i"))
    if not started:
        raise InventoryError("dpkg -l başlığı tanınmadı")
    return records


def inventory(**options) -> dict:
    records = parse_inventory(run_dpkg("-l", **options))
    return {"packages": records, "count": len(records),
            "installed_count": sum(p["installed"] for p in records)}


def files(package: str, **options) -> dict:
    package_name(package)
    paths = []
    for line in run_dpkg("-L", "--", package, **options).splitlines():
        if line.startswith("/"):
            paths.append(line)
    return {"package": package, "files": paths, "count": len(paths)}


def owners(path: str, **options) -> dict:
    literal_path(path)
    # dpkg -S interprets shell-style patterns even without a shell. Escape each
    # metacharacter and still compare the returned path exactly, including spaces.
    pattern = "".join({"*": "[*]", "?": "[?]", "[": "[[]", "]": "[]]"}.get(c, c) for c in path)
    packages = set()
    for line in run_dpkg("-S", "--", pattern, **options).splitlines():
        owner, sep, reported_path = line.partition(": ")
        if sep and reported_path == path:
            for item in owner.split(", "):
                try:
                    packages.add(package_name(item))
                except argparse.ArgumentTypeError:
                    # dpkg can emit diversion metadata as well as ownership.
                    continue
    if not packages:
        raise InventoryError(f"tam yol için kayıtlı paket sahibi bulunamadı: {path}")
    return {"path": path, "packages": sorted(packages)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("-l", "--list", action="store_true", help="artık yapılandırma dahil paket durumlarını listele")
    modes.add_argument("-L", "--files", type=package_name, metavar="PAKET")
    modes.add_argument("-S", "--owner", type=literal_path, metavar="MUTLAK_YOL")
    parser.add_argument("--admindir", type=literal_path, help="alternatif dpkg veritabanını oku (örneğin test kopyası)")
    args = parser.parse_args(argv)
    operation = "list" if args.list else "files" if args.files else "owner"
    try:
        options = {"admindir": args.admindir} if args.admindir else {}
        data = inventory(**options) if args.list else files(args.files, **options) if args.files else owners(args.owner, **options)
    except (InventoryError, argparse.ArgumentTypeError) as exc:
        print(json.dumps({"schema_version": 1, "ok": False, "operation": operation,
                          "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"schema_version": 1, "ok": True, "operation": operation,
                      "data": data}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
