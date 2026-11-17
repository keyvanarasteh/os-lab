#!/usr/bin/env python3
"""Build a wheel of the os-lab MCP server with the standard library only (a wheel is a zip).

  scripts/build-mcp-wheel.py [--out DIR]     writes DIR/oslab_mcp-<version>-py3-none-any.whl (default dist/)

Installing it gives the `oslab-mcp` command, a stdio MCP server for qLar, Claude, Codex and the rest:
  pipx install dist/oslab_mcp-*.whl     then register the command `oslab-mcp`
The wheel carries console/*.py|json and ios-lab/mac (scripts and example config; never config.env or build/).
Set OSLAB_ROOT to a checkout to share the dashboard's armed state and audit log instead of the bundled copy.
# @lat: [[ios-lab#Native macOS path#MCP dev mode]]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import zipfile

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NAME, PKG, VERSION = "oslab-mcp", "oslab_mcp", "0.1.0"
SKIP_MAC = {"config.env", "build", "__pycache__", ".DS_Store"}

CLI = '''"""Entry point of the oslab-mcp command: run the bundled stdio MCP server."""
import os
import sys


def main() -> None:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "console"))
    import mcp_server
    mcp_server.main()
'''


def files() -> dict[str, bytes]:
    out: dict[str, bytes] = {f"{PKG}/__init__.py": b"", f"{PKG}/cli.py": CLI.encode()}
    console = os.path.join(REPO, "console")
    for name in sorted(os.listdir(console)):
        if name.endswith((".py", ".json")) and name != "scope.json":
            out[f"{PKG}/console/{name}"] = open(os.path.join(console, name), "rb").read()
    mac = os.path.join(REPO, "ios-lab", "mac")
    for base, dirs, names in os.walk(mac):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_MAC)
        for name in sorted(names):
            if name in SKIP_MAC:
                continue
            path = os.path.join(base, name)
            out[f"{PKG}/ios-lab/mac/{os.path.relpath(path, mac)}"] = open(path, "rb").read()
    return out


def build(outdir: str) -> str:
    dist = f"{PKG}-{VERSION}.dist-info"
    meta = f"Metadata-Version: 2.1\nName: {NAME}\nVersion: {VERSION}\nSummary: os-lab macOS Lab MCP server (guarded computer-use tools over stdio)\nRequires-Python: >=3.9\n"
    content = files()
    content[f"{dist}/METADATA"] = meta.encode()
    content[f"{dist}/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: build-mcp-wheel\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    content[f"{dist}/entry_points.txt"] = f"[console_scripts]\noslab-mcp = {PKG}.cli:main\n".encode()
    rows = []
    for path, data in content.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append(f"{path},sha256={digest},{len(data)}")
    rows.append(f"{dist}/RECORD,,")
    content[f"{dist}/RECORD"] = ("\n".join(rows) + "\n").encode()
    os.makedirs(outdir, exist_ok=True)
    target = os.path.join(outdir, f"{PKG}-{VERSION}-py3-none-any.whl")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as wheel:
        for path, data in content.items():
            info = zipfile.ZipInfo(path, (2026, 1, 1, 0, 0, 0))  # fixed time: the same sources give the same wheel
            info.external_attr = (0o755 if path.endswith(".sh") else 0o644) << 16
            wheel.writestr(info, data)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=os.path.join(REPO, "dist"))
    print(build(parser.parse_args().out))
