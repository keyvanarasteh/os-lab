#!/usr/bin/env python3
"""Verify a Tauri-signed release download with the published minisign public key."""
from __future__ import annotations

import base64
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="downloaded package with an adjacent .sig file")
    parser.add_argument("--version", help="require the signature's trusted comment to bind this version")
    args = parser.parse_args()
    package = Path(args.package).resolve()
    signature = Path(f"{package}.sig")
    key = Path(__file__).resolve().parents[1] / "UPDATER_MINISIGN.pub"
    if not package.is_file() or not signature.is_file():
        print(f"Expected {package} and {signature}", file=sys.stderr)
        return 2
    if not shutil.which("minisign"):
        print("Install minisign to verify release signatures.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="oslab-signature-") as directory:
        decoded = Path(directory) / "signature.minisig"
        decoded.write_bytes(base64.b64decode(signature.read_text().strip(), validate=True))
        result = subprocess.run(["minisign", "-Vm", str(package), "-x", str(decoded), "-p", str(key)], check=False, capture_output=True, text=True)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        return result.returncode
    comment = result.stdout.partition("Trusted comment:")[2].splitlines()
    trusted = comment[0].strip().split("\t") if comment else []
    if args.version and f"version:{args.version}" not in trusted:
        print(f"Signature is not bound to version {args.version}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
