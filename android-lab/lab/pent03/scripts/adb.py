#!/usr/bin/env python3
"""Thin, testable wrapper around the Android Debug Bridge (adb).

The *argv builders* (``adb_argv``, ``shell_argv``, ...) are pure functions that
return the exact command list without running anything, so they can be asserted
in offline tests. The *runners* (``run``, ``shell``, ``get_prop`` ...) execute
those argv via :mod:`subprocess` and are only exercised against a real device.

No command strings are ever built from page input or interpolated into a shell;
everything is argv lists passed to ``subprocess.run(..., shell=False)``.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time

DEFAULT_ADB = "adb"


class AdbError(RuntimeError):
    """An adb invocation failed."""


def adb_argv(serial: str | None, *args: str, adb: str = DEFAULT_ADB) -> list[str]:
    """Build an ``adb [-s serial] <args...>`` argv list."""
    argv = [adb]
    if serial:
        argv += ["-s", serial]
    argv += [str(a) for a in args]
    return argv


def shell_argv(serial: str | None, *args: str, adb: str = DEFAULT_ADB) -> list[str]:
    """Build an ``adb -s serial shell <args...>`` argv list."""
    return adb_argv(serial, "shell", *args, adb=adb)


def push_argv(
    serial: str | None, local: str, remote: str, adb: str = DEFAULT_ADB
) -> list[str]:
    """Build an ``adb push local remote`` argv list."""
    return adb_argv(serial, "push", local, remote, adb=adb)


def run(
    argv: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: float | None = 120,
) -> subprocess.CompletedProcess:
    """Run an adb argv list. Raises :class:`AdbError` on non-zero exit."""
    # Safe by construction: argv is always a list and shell is False (the
    # default), so no string is ever handed to a shell for interpretation and no
    # metacharacter can be expanded. Callers build argv from scope-validated
    # inputs only. The opengrep audit rule flags any non-literal argv regardless.
    try:
        proc = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            argv,
            check=False,
            text=True,
            capture_output=capture,
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as exc:  # adb not installed
        raise AdbError(f"adb binary not found: {argv[0]!r}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb timed out after {timeout}s: {' '.join(argv)}") from exc
    if check and proc.returncode != 0:
        raise AdbError(
            f"adb failed ({proc.returncode}): {' '.join(argv)}\n"
            f"{(proc.stderr or '').strip()}"
        )
    return proc


def shell(
    serial: str | None, *args: str, adb: str = DEFAULT_ADB, check: bool = True
) -> str:
    """Run ``adb shell`` and return stdout (stripped)."""
    proc = run(shell_argv(serial, *args, adb=adb), check=check)
    return (proc.stdout or "").strip()


def get_prop(serial: str | None, prop: str, adb: str = DEFAULT_ADB) -> str:
    """Return a single ``getprop`` value."""
    return shell(serial, "getprop", prop, adb=adb).strip()


def get_abi(serial: str | None, adb: str = DEFAULT_ADB) -> str:
    """Return the device's primary CPU ABI (e.g. ``arm64-v8a``, ``x86_64``)."""
    return get_prop(serial, "ro.product.cpu.abi", adb=adb)


def get_sdk(serial: str | None, adb: str = DEFAULT_ADB) -> int:
    """Return the device API level (SDK int), or ``0`` if unknown."""
    raw = get_prop(serial, "ro.build.version.sdk", adb=adb)
    try:
        return int(raw)
    except ValueError:
        return 0


def is_booted(serial: str | None, adb: str = DEFAULT_ADB) -> bool:
    """Return True once ``sys.boot_completed`` is ``1``."""
    try:
        return get_prop(serial, "sys.boot_completed", adb=adb) == "1"
    except AdbError:
        return False


def wait_for_boot(
    serial: str | None,
    *,
    timeout: float = 300,
    poll: float = 3,
    adb: str = DEFAULT_ADB,
    sleep=time.sleep,
    clock=time.monotonic,
) -> None:
    """Block until the device reports a completed boot or ``timeout`` elapses.

    ``sleep`` and ``clock`` are injectable so tests drive it without real waits.
    """
    run(adb_argv(serial, "wait-for-device", adb=adb), timeout=timeout)
    deadline = clock() + timeout
    while clock() < deadline:
        if is_booted(serial, adb=adb):
            return
        sleep(poll)
    raise AdbError(f"device {serial!r} did not finish booting within {timeout}s")


def enable_root(serial: str | None, adb: str = DEFAULT_ADB) -> None:
    """Restart adbd as root (userdebug/eng emulator images only)."""
    run(adb_argv(serial, "root", adb=adb), check=False)
    run(adb_argv(serial, "wait-for-device", adb=adb), timeout=60)


def is_root(serial: str | None, adb: str = DEFAULT_ADB) -> bool:
    """Return True if the adb shell runs as uid 0 (root) on the device."""
    try:
        out = shell(serial, "id", "-u", adb=adb, check=False)
    except AdbError:
        return False
    return out.strip() == "0"


def remount(serial: str | None, adb: str = DEFAULT_ADB) -> None:
    """Remount ``/system`` read-write (needs a rooted emulator image)."""
    run(adb_argv(serial, "remount", adb=adb), check=False)


def have_adb(adb: str = DEFAULT_ADB) -> bool:
    """Return True if an adb binary is on PATH."""
    return shutil.which(adb) is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="adb probe helper (lab).")
    parser.add_argument("-s", "--serial", default=None)
    parser.add_argument(
        "action", choices=["abi", "sdk", "booted", "wait-boot", "prop"]
    )
    parser.add_argument("name", nargs="?", help="property name for 'prop'")
    args = parser.parse_args(argv)
    if not have_adb():
        print("adb not found on PATH", file=sys.stderr)
        return 1
    try:
        if args.action == "abi":
            print(get_abi(args.serial))
        elif args.action == "sdk":
            print(get_sdk(args.serial))
        elif args.action == "booted":
            print("yes" if is_booted(args.serial) else "no")
        elif args.action == "wait-boot":
            wait_for_boot(args.serial)
            print("booted")
        elif args.action == "prop":
            if not args.name:
                parser.error("prop requires a property name")
            print(get_prop(args.serial, args.name))
    except AdbError as exc:
        print(f"adb error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
