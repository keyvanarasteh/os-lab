#!/usr/bin/env python3
"""Automated universal SSL-pinning bypass via objection (frida fallback).

Primary path: drive `objection <https://github.com/sensepost/objection>`_, which
ships a battle-tested ``android sslpinning disable`` module covering OkHttp,
TrustManager, HostnameVerifier, Conscrypt and the common pinning libraries.

Fallback path: spawn the app under frida with the bundled universal unpinning
hook (``hooks/ssl-pinning-universal.js``) for cases where objection isn't
installed or the app needs an early-spawn gadget.

**Lifecycle (important):** the unpinning tool only neutralises pins *while its
session is alive* — an objection ``explore`` REPL or a ``frida -f`` spawn keeps
the hooks loaded until it exits. So this module does NOT run the tool and wait
for it to return (a clean exit would mean the hooks are gone). Instead it starts
the tool in the **background** with :class:`subprocess.Popen` and hands back the
handle; the pipeline keeps that process alive for the analysis/capture window
and then terminates it with :func:`stop_bypass`. Use :func:`bypass_session` as a
context manager to guarantee teardown.

The argv builders are pure functions asserted in offline tests; the launcher
takes an injectable ``popen`` so tests never spawn a real process.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import time

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

    ``objection -g <package> [-S <serial>] explore --startup-command "..."``.
    The resulting process is long-lived (it holds the explore session), so it is
    launched in the background — see :func:`start_bypass`.
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
    connected USB/emulator device). Also long-lived (the hook stays resident).
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


def _have(binary: str) -> bool:
    import shutil

    return shutil.which(binary) is not None


def select_argv(
    package: str,
    *,
    serial: str | None = None,
    prefer: str = "objection",
    have=_have,
) -> tuple[str, list[str]]:
    """Return ``(tool, argv)`` for the preferred available unpinning tool.

    Prefers objection; falls back to the bundled frida hook. Raises
    :class:`BypassError` if neither tool is installed (or the hook is missing).
    """
    if prefer == "objection" and have("objection"):
        return "objection", objection_argv(package, serial=serial)
    if have("frida"):
        if not os.path.isfile(UNIVERSAL_HOOK):
            raise BypassError(f"frida hook not found: {UNIVERSAL_HOOK}")
        return "frida", frida_fallback_argv(package, serial=serial)
    raise BypassError(
        "neither 'objection' nor 'frida' is installed; pip install objection frida-tools"
    )


# --- background session lifecycle ------------------------------------------


def start_bypass(
    package: str,
    *,
    serial: str | None = None,
    prefer: str = "objection",
    popen=subprocess.Popen,
    have=_have,
):
    """Start the unpinning tool in the **background** and return its handle.

    The returned object is a :class:`subprocess.Popen` (or an injected stand-in).
    It keeps the pins neutralised only while alive, so the caller must terminate
    it with :func:`stop_bypass` when the analysis window is over.
    """
    scope.assert_in_scope(serial=serial, package=package)
    tool, argv = select_argv(package, serial=serial, prefer=prefer, have=have)
    # Detach stdio so a long-lived session does not block on a full pipe.
    return popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def is_alive(proc) -> bool:
    """Return True if the background unpinning process is still running."""
    return proc is not None and proc.poll() is None


def stop_bypass(proc, *, timeout: float = 10) -> None:
    """Terminate the background unpinning process (SIGTERM, then SIGKILL)."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except Exception:
        proc.kill()


@contextlib.contextmanager
def bypass_session(
    package: str,
    *,
    serial: str | None = None,
    prefer: str = "objection",
    popen=subprocess.Popen,
    have=_have,
):
    """Context manager: start the unpinning session and always tear it down."""
    proc = start_bypass(package, serial=serial, prefer=prefer, popen=popen, have=have)
    try:
        yield proc
    finally:
        stop_bypass(proc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start a background SSL-pinning bypass session (objection, frida fallback)."
    )
    parser.add_argument("package", help="target application id, e.g. com.securebank.mobile")
    parser.add_argument("-s", "--serial", default="emulator-5554")
    parser.add_argument("--prefer", choices=["objection", "frida"], default="objection")
    parser.add_argument(
        "--hold", type=float, default=0,
        help="seconds to hold the session open for analysis (0 = until Ctrl-C)",
    )
    args = parser.parse_args(argv)
    try:
        proc = start_bypass(args.package, serial=args.serial, prefer=args.prefer)
    except (BypassError, scope.ScopeError) as exc:
        print(f"bypass failed: {exc}", file=sys.stderr)
        return 1

    print(f"unpinning running in background (pid={proc.pid}); hooks stay active "
          f"while this session is alive.")
    try:
        if args.hold > 0:
            time.sleep(args.hold)
        else:
            print("holding session — press Ctrl-C to stop.")
            while is_alive(proc):
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_bypass(proc)
        print("unpinning session stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
