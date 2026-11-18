#!/usr/bin/env python3
"""Automated universal SSL-pinning bypass via objection (frida fallback).

Primary path: drive `objection <https://github.com/sensepost/objection>`_, which
ships a battle-tested ``android sslpinning disable`` module covering OkHttp,
TrustManager, HostnameVerifier, Conscrypt and the common pinning libraries.

Fallback path: spawn the app under frida with the bundled universal unpinning
hook (``hooks/ssl-pinning-universal.js``) for cases where objection isn't
installed or the app needs an early-spawn gadget.

Both entry points build their argv as pure functions so they're asserted in
offline tests; the runners just hand the argv to :mod:`subprocess` after a scope
check. frida-server must already be running on the device (see
``deploy_frida.py``).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

import scope

HOOK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks")
UNIVERSAL_HOOK = os.path.normpath(os.path.join(HOOK_DIR, "ssl-pinning-universal.js"))

#: objection command run inside the explore REPL to drop pinning.
OBJECTION_DISABLE_CMD = "android sslpinning disable"


class BypassError(RuntimeError):
    """SSL-pinning bypass could not be started."""


# --- pure argv builders (offline-testable) ---------------------------------


def objection_argv(
    package: str,
    *,
    serial: str | None = None,
    startup_command: str = OBJECTION_DISABLE_CMD,
    spawn: bool = True,
    objection_bin: str = "objection",
) -> list[str]:
    """Build the objection argv that disables SSL pinning for ``package``.

    ``objection -g <package> [-S <serial>] explore -s "android sslpinning disable"``
    adding ``--startup-command`` plus ``--spawn`` behaviour via the gadget.
    """
    if not package:
        raise BypassError("a target package id is required")
    argv = [objection_bin, "-g", package]
    if serial:
        argv += ["-S", serial]
    argv += ["explore", "--startup-command", startup_command]
    if not spawn:
        argv += ["--no-spawn"]
    return argv


def frida_fallback_argv(
    package: str,
    *,
    serial: str | None = None,
    hook: str = UNIVERSAL_HOOK,
    frida_bin: str = "frida",
) -> list[str]:
    """Build a ``frida`` fallback argv that targets a *specific* device.

    When ``serial`` is given, select that device with ``-D <serial>`` so the
    hook never lands on the wrong device; otherwise fall back to ``-U`` (the one
    connected USB/emulator device).
    """
    if not package:
        raise BypassError("a target package id is required")
    argv = [frida_bin]
    if serial:
        argv += ["-D", serial]
    else:
        argv += ["-U"]
    argv += ["-f", package, "-l", hook, "--no-pause"]
    return argv


# --- runners ---------------------------------------------------------------


def _have(binary: str) -> bool:
    import shutil

    return shutil.which(binary) is not None


def run_objection(
    package: str,
    *,
    serial: str | None = None,
    objection_bin: str = "objection",
    runner=subprocess.run,
) -> int:
    """Launch objection to disable pinning. Returns the process exit code."""
    scope.assert_in_scope(serial=serial, package=package)
    argv = objection_argv(package, serial=serial, objection_bin=objection_bin)
    proc = runner(argv)
    return getattr(proc, "returncode", 0)


def run_frida_fallback(
    package: str,
    *,
    serial: str | None = None,
    hook: str = UNIVERSAL_HOOK,
    frida_bin: str = "frida",
    runner=subprocess.run,
) -> int:
    """Launch the frida universal unpinning hook on ``serial``. Returns exit code.

    Note: the unpinning hook must stay resident to keep pins neutralised, so this
    spawns the app and holds the session; run it as the last pipeline step (or in
    its own process) rather than expecting it to return immediately.
    """
    scope.assert_in_scope(serial=serial, package=package)
    if not os.path.isfile(hook):
        raise BypassError(f"frida hook not found: {hook}")
    argv = frida_fallback_argv(package, serial=serial, hook=hook, frida_bin=frida_bin)
    proc = runner(argv)
    return getattr(proc, "returncode", 0)


def bypass(
    package: str,
    *,
    serial: str | None = None,
    prefer: str = "objection",
    runner=subprocess.run,
    have=_have,
) -> int:
    """Disable SSL pinning, preferring objection and falling back to frida."""
    scope.assert_in_scope(serial=serial, package=package)
    if prefer == "objection" and have("objection"):
        return run_objection(package, serial=serial, runner=runner)
    if have("frida"):
        return run_frida_fallback(package, serial=serial, runner=runner)
    raise BypassError(
        "neither 'objection' nor 'frida' is installed; "
        "pip install objection frida-tools"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Disable SSL pinning for a lab app (objection, frida fallback)."
    )
    parser.add_argument("package", help="target application id, e.g. com.securebank.mobile")
    parser.add_argument("-s", "--serial", default="emulator-5554")
    parser.add_argument(
        "--prefer", choices=["objection", "frida"], default="objection"
    )
    args = parser.parse_args(argv)
    try:
        code = bypass(args.package, serial=args.serial, prefer=args.prefer)
    except (BypassError, scope.ScopeError) as exc:
        print(f"bypass failed: {exc}", file=sys.stderr)
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
