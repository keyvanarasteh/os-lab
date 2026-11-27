#!/usr/bin/env python3
"""Automated ``frida-server`` deployment for the lab emulator.

Pipeline:

1. Read the device ABI with adb and map it to a frida release arch.
2. Resolve the frida version (pinned default, or ``latest`` via the GitHub API).
3. Download the matching ``frida-server-<ver>-android-<arch>.xz`` from the
   official frida releases and decompress it with the stdlib :mod:`lzma`.
4. ``adb push`` it to ``/data/local/tmp/frida-server``, ``chmod 755`` and start
   it detached as root.

No frida binary is committed to the repo (os-lab rule: download vendor binaries
at setup time). The pure helpers — arch mapping and URL/asset builders — carry
no side effects and are unit-tested offline; the network and adb calls live in
``fetch_server`` / ``deploy`` and are only hit against a real device.
"""
from __future__ import annotations

import argparse
import json
import lzma
import os
import sys
import tempfile
import urllib.error
import urllib.request

import adb
import scope

#: A known-good pinned version so an offline/air-gapped lab still has a target.
#: Override with ``--version`` (or ``latest`` to resolve the newest release).
DEFAULT_FRIDA_VERSION = "16.5.9"

REMOTE_PATH = "/data/local/tmp/frida-server"
RELEASES_BASE = "https://github.com/frida/frida/releases/download"
LATEST_API = "https://api.github.com/repos/frida/frida/releases/latest"

#: Android ``ro.product.cpu.abi`` -> frida release arch token.
ABI_TO_FRIDA_ARCH = {
    "arm64-v8a": "arm64",
    "armeabi-v7a": "arm",
    "armeabi": "arm",
    "x86_64": "x86_64",
    "x86": "x86",
}


class FridaDeployError(RuntimeError):
    """Deployment of frida-server failed."""


# --- pure helpers (offline-testable) ---------------------------------------


def frida_arch(abi: str) -> str:
    """Map an Android ABI string to a frida-server arch token."""
    abi = (abi or "").strip().lower()
    try:
        return ABI_TO_FRIDA_ARCH[abi]
    except KeyError:
        raise FridaDeployError(
            f"unsupported ABI {abi!r}; known: {sorted(ABI_TO_FRIDA_ARCH)}"
        ) from None


def server_asset_name(version: str, arch: str) -> str:
    """Return the release asset filename for a version+arch."""
    version = version.lstrip("v").strip()
    return f"frida-server-{version}-android-{arch}.xz"


def download_url(version: str, arch: str) -> str:
    """Return the full download URL for the compressed frida-server asset."""
    version = version.lstrip("v").strip()
    return f"{RELEASES_BASE}/{version}/{server_asset_name(version, arch)}"


# --- side-effecting helpers ------------------------------------------------


def resolve_version(version: str, *, opener=urllib.request.urlopen) -> str:
    """Return a concrete version. ``latest`` is resolved via the GitHub API."""
    if version and version.lower() != "latest":
        return version.lstrip("v")
    try:
        with opener(LATEST_API, timeout=30) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FridaDeployError(
            f"could not reach the GitHub API to resolve the latest frida version: {exc}"
        ) from exc
    tag = data.get("tag_name")
    if not tag:
        raise FridaDeployError("could not read latest frida version from GitHub API")
    return str(tag).lstrip("v")


def fetch_server(
    version: str, arch: str, dest_dir: str, *, opener=urllib.request.urlopen
) -> str:
    """Download and xz-decompress frida-server into ``dest_dir``.

    Returns the path to the decompressed binary. The ``opener`` is injectable
    so tests feed a local ``.xz`` payload with no network access.
    """
    url = download_url(version, arch)
    out_path = os.path.join(dest_dir, "frida-server")
    try:
        with opener(url, timeout=120) as resp:
            compressed = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise FridaDeployError(f"failed to download {url}: {exc}") from exc
    try:
        binary = lzma.decompress(compressed)
    except lzma.LZMAError as exc:
        raise FridaDeployError(f"failed to decompress {url}: {exc}") from exc
    with open(out_path, "wb") as fh:
        fh.write(binary)
    os.chmod(out_path, 0o755)
    return out_path


def start_server_command(remote_path: str = REMOTE_PATH) -> str:
    """Return the on-device shell command that starts frida-server detached."""
    return f"nohup {remote_path} >/dev/null 2>&1 &"


def deploy(
    serial: str | None,
    *,
    version: str = DEFAULT_FRIDA_VERSION,
    adb_bin: str = adb.DEFAULT_ADB,
    opener=urllib.request.urlopen,
) -> str:
    """Full deploy: scope check -> arch detect -> fetch -> push -> start.

    Returns the resolved version actually deployed.
    """
    serial = scope.require_serial(serial)
    abi = adb.get_abi(serial, adb=adb_bin)
    arch = frida_arch(abi)
    resolved = resolve_version(version, opener=opener)

    adb.enable_root(serial, adb=adb_bin)
    if not adb.is_root(serial, adb=adb_bin):
        raise FridaDeployError(
            f"device {serial!r} is not rooted after 'adb root'; frida-server must "
            f"run as root (use an emulator 'userdebug'/'eng' image)"
        )
    with tempfile.TemporaryDirectory(prefix="frida-") as tmp:
        local = fetch_server(resolved, arch, tmp, opener=opener)
        adb.run(adb.push_argv(serial, local, REMOTE_PATH, adb=adb_bin))
    adb.shell(serial, "chmod", "755", REMOTE_PATH, adb=adb_bin)
    # Detached launch; non-zero is tolerated because the shell returns at once.
    adb.run(
        adb.shell_argv(serial, start_server_command(), adb=adb_bin),
        check=False,
        timeout=15,
    )
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy frida-server to the lab emulator.")
    parser.add_argument("-s", "--serial", default="emulator-5554")
    parser.add_argument(
        "--version",
        default=DEFAULT_FRIDA_VERSION,
        help="frida version, or 'latest' to resolve from GitHub",
    )
    args = parser.parse_args(argv)
    try:
        resolved = deploy(args.serial, version=args.version)
    except (FridaDeployError, adb.AdbError, scope.ScopeError) as exc:
        print(f"frida deploy failed: {exc}", file=sys.stderr)
        return 1
    print(f"frida-server {resolved} deployed and started on {args.serial}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
