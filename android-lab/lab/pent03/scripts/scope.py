#!/usr/bin/env python3
"""Lab-only scope guard for the PENT-03 Android pipeline.

Every destructive or network-touching action in this lab routes through
``assert_in_scope`` first. The guard refuses to act on anything that is not an
isolated lab emulator / lab package, enforcing the authorization-only rule in
code rather than in a README nobody reads.

What counts as "in scope":

* **Devices / serials** — local emulators (``emulator-5554``), loopback adb
  (``127.0.0.1:5555``), the docker-compose ``emulator`` service endpoint, and
  the Android emulator NAT range (``10.0.2.0/24``). Physical USB serials are
  refused by default; opt in with ``OSLAB_EXTRA_SERIALS``.
* **Packages** — must be a syntactically valid Android application id (so path
  separators / traversal can never reach a filesystem path) *and* match a lab
  prefix (``com.securebank.``, ``org.oslab.``, ``com.lab.``). Extend with
  ``OSLAB_EXTRA_PACKAGES``.
* **Proxy / MITM hosts** — the exact loopback / emulator-host-alias endpoints
  only (``127.0.0.1``, ``localhost``, ``10.0.2.2``, ``::1``). A whole subnet is
  never trusted; widen with ``OSLAB_EXTRA_PROXY_HOSTS`` for a named lab host.

Environment escape hatches are intentionally explicit and comma-separated so an
instructor can widen scope for a known lab without editing code:

    OSLAB_EXTRA_SERIALS="emulator-5556,192.168.56.101:5555"
    OSLAB_EXTRA_PACKAGES="com.myorg.testapp"
    OSLAB_EXTRA_PROXY_HOSTS="mitmproxy"

Usage (library)::

    from scope import assert_in_scope, ScopeError
    assert_in_scope(serial="emulator-5554", package="com.securebank.mobile")

Usage (CLI)::

    python3 scope.py --serial emulator-5554 --package com.securebank.mobile
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys

# --- Static lab allowlists -------------------------------------------------

#: Emulator / loopback serials that are always considered lab devices.
LAB_SERIAL_EXACT = frozenset(
    {
        "emulator-5554",
        "emulator-5556",
        "emulator-5558",
        "127.0.0.1:5555",
        "localhost:5555",
        "emulator:5555",  # docker-compose service endpoint
    }
)

#: Non-IP hostnames that denote a lab device endpoint (host part of host:port).
LAB_SERIAL_HOSTS = frozenset({"localhost", "emulator"})

#: adb host:port serials whose host lies in one of these nets are in scope.
LAB_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.2.0/24"),  # Android emulator NAT
)

#: Package name prefixes that denote lab-owned apps.
LAB_PACKAGE_PREFIXES = (
    "com.securebank.",
    "org.oslab.",
    "com.lab.",
)

#: A syntactically valid Android application id — letters/digits/underscore
#: segments separated by dots. This is also the gate that stops a package value
#: carrying ``/`` or ``..`` from ever reaching a filesystem path downstream.
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")

#: Exact hosts a lab proxy / MITM endpoint may be. A whole subnet is never ok.
LAB_PROXY_HOSTS = frozenset({"127.0.0.1", "localhost", "10.0.2.2", "::1"})


class ScopeError(RuntimeError):
    """Raised when a target is outside the authorized lab scope."""


def _extra(env_name: str) -> frozenset[str]:
    raw = os.environ.get(env_name, "")
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def is_valid_package(package: str) -> bool:
    """Return True if ``package`` is a syntactically valid Android app id."""
    return bool(package) and bool(PACKAGE_RE.match(package.strip()))


def serial_in_scope(serial: str) -> bool:
    """Return True if ``serial`` is an authorized lab device."""
    if not serial:
        return False
    serial = serial.strip()
    if serial in LAB_SERIAL_EXACT or serial in _extra("OSLAB_EXTRA_SERIALS"):
        return True
    if serial.startswith("emulator-"):
        return True
    host = serial.rsplit(":", 1)[0] if ":" in serial else serial
    if host in LAB_SERIAL_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in LAB_NETS)


def package_in_scope(package: str) -> bool:
    """Return True if ``package`` is a *valid* lab-owned application id."""
    if not is_valid_package(package):
        return False
    package = package.strip()
    if package in _extra("OSLAB_EXTRA_PACKAGES"):
        return True
    return any(package.startswith(p) for p in LAB_PACKAGE_PREFIXES)


def proxy_host_in_scope(host: str) -> bool:
    """Return True if ``host`` is an allowed lab proxy / MITM endpoint.

    Only the exact loopback / emulator-host-alias endpoints are trusted; a whole
    subnet is never accepted. Widen with ``OSLAB_EXTRA_PROXY_HOSTS``.
    """
    if not host:
        return False
    host = host.strip()
    return host in LAB_PROXY_HOSTS or host in _extra("OSLAB_EXTRA_PROXY_HOSTS")


def assert_in_scope(
    *,
    serial: str | None = None,
    package: str | None = None,
    proxy_host: str | None = None,
) -> None:
    """Raise :class:`ScopeError` unless every supplied target is in scope.

    Only the arguments you pass are checked, so the same guard works for a
    device-only action (frida deploy) and a full run (device + package + proxy).
    A value that is an empty string is always a failure (never silently skipped).
    """
    problems: list[str] = []
    if serial is not None and not serial_in_scope(serial):
        problems.append(
            f"device {serial!r} is not a recognized lab emulator "
            f"(set OSLAB_EXTRA_SERIALS to widen scope for a known lab)"
        )
    if package is not None and not package_in_scope(package):
        if package and not is_valid_package(package):
            problems.append(f"package {package!r} is not a valid Android app id")
        else:
            problems.append(
                f"package {package!r} is not a lab-owned app "
                f"(set OSLAB_EXTRA_PACKAGES to widen scope for a known lab)"
            )
    if proxy_host is not None and not proxy_host_in_scope(proxy_host):
        problems.append(f"proxy host {proxy_host!r} is not a loopback/lab host")
    if problems:
        raise ScopeError(
            "refusing to act outside the authorized lab scope:\n  - "
            + "\n  - ".join(problems)
        )


def require_serial(serial: str | None) -> str:
    """Return ``serial`` if it is an in-scope lab device, else raise.

    Device-changing operations call this so a missing/empty serial can never
    fall through to adb's implicit default device.
    """
    if not serial:
        raise ScopeError(
            "a lab device serial is required (refusing to use adb's default device)"
        )
    assert_in_scope(serial=serial)
    return serial


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a target against lab scope.")
    parser.add_argument("--serial")
    parser.add_argument("--package")
    parser.add_argument("--proxy-host")
    args = parser.parse_args(argv)
    try:
        assert_in_scope(
            serial=args.serial,
            package=args.package,
            proxy_host=args.proxy_host,
        )
    except ScopeError as exc:
        print(f"OUT OF SCOPE: {exc}", file=sys.stderr)
        return 2
    print("in scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
