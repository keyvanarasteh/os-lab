#!/usr/bin/env python3
"""Authorization & Scope-Guard Library (PENT-21).

Enforces the isolated lab-only rule in code by validating hosts, IPs,
URLs, ADB/Frida device serials, and Android package names before any
analysis or instrumentation runs.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlparse


class ScopeViolationError(PermissionError):
    """Raised when a target falls outside the authorized lab scope."""


DEFAULT_ALLOWED_HOST_SUFFIXES = (".lab", ".local", ".test", ".localhost")
DEFAULT_ALLOWED_EXACT_HOSTS = frozenset({"localhost", "host.docker.internal"})
DEFAULT_ALLOWED_PACKAGE_PREFIXES = (
    "com.oslab.",
    "com.example.",
    "org.owasp.",
    "io.github.oslab.",
    "com.android.insecurebankv2",
    "jakhar.aseem.diva",
)
DEFAULT_ALLOWED_DEVICE_PREFIXES = ("emulator-", "127.0.0.1:", "localhost:")
_LOCAL_SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


@dataclass(frozen=True)
class LabScopePolicy:
    """Configurable allowlist policy for isolated lab environments."""

    allowed_cidrs: tuple[ipaddress._BaseNetwork, ...] = field(
        default_factory=lambda: (
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("::1/128"),
            ipaddress.ip_network("fc00::/7"),
            ipaddress.ip_network("fe80::/10"),
        )
    )
    allowed_exact_hosts: frozenset[str] = DEFAULT_ALLOWED_EXACT_HOSTS
    allowed_host_suffixes: tuple[str, ...] = DEFAULT_ALLOWED_HOST_SUFFIXES
    allowed_package_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PACKAGE_PREFIXES
    allowed_device_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_DEVICE_PREFIXES
    allow_usb_serials: bool = True


DEFAULT_POLICY = LabScopePolicy()


def _extract_host(target: str) -> str:
    raw = target.strip()
    if "://" in raw:
        parsed = urlparse(raw)
        if not parsed.hostname:
            raise ScopeViolationError(f"Invalid URL without hostname: {target!r}")
        return parsed.hostname.lower().rstrip(".")
    if raw.startswith("[") and "]" in raw:
        return raw[1 : raw.index("]")].lower()
    if ":" in raw and raw.count(":") == 1:
        host_part, _ = raw.split(":", 1)
        return host_part.lower().rstrip(".")
    return raw.lower().rstrip(".")


def is_host_in_scope(target: str, policy: LabScopePolicy = DEFAULT_POLICY) -> bool:
    """Return True if a hostname, IP address, or URL points to an isolated lab."""
    if not target or not target.strip():
        return False
    try:
        host = _extract_host(target)
    except ScopeViolationError:
        return False

    if host in policy.allowed_exact_hosts:
        return True
    if any(host.endswith(suffix) for suffix in policy.allowed_host_suffixes):
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    return any(ip in net for net in policy.allowed_cidrs)


def is_package_in_scope(package_name: str, policy: LabScopePolicy = DEFAULT_POLICY) -> bool:
    """Return True if an Android package identifier belongs to lab test apps."""
    pkg = (package_name or "").strip()
    if not pkg or "." not in pkg:
        return False
    return any(pkg == p.rstrip(".") or pkg.startswith(p) for p in policy.allowed_package_prefixes)


def is_device_in_scope(device_id: str, policy: LabScopePolicy = DEFAULT_POLICY) -> bool:
    """Return True if an ADB/Frida device identifier is a local/lab target."""
    dev = (device_id or "").strip()
    if not dev:
        return False
    if any(dev.startswith(prefix) for prefix in policy.allowed_device_prefixes):
        return True
    if ":" in dev:
        return is_host_in_scope(dev, policy=policy)
    if policy.allow_usb_serials and _LOCAL_SERIAL_RE.match(dev) and "." not in dev:
        return True
    return False


def assert_in_scope(
    *,
    host: str | None = None,
    package: str | None = None,
    device: str | None = None,
    policy: LabScopePolicy = DEFAULT_POLICY,
) -> dict[str, str]:
    """Validate provided targets against the lab scope policy."""
    checked: dict[str, str] = {}

    if host is not None:
        if not is_host_in_scope(host, policy=policy):
            raise ScopeViolationError(
                f"Refusing out-of-scope host/URL: {host!r}. Only isolated lab networks/hosts are permitted."
            )
        checked["host"] = host.strip()

    if package is not None:
        if not is_package_in_scope(package, policy=policy):
            raise ScopeViolationError(
                f"Refusing out-of-scope package: {package!r}. Only lab-owned test packages are permitted."
            )
        checked["package"] = package.strip()

    if device is not None:
        if not is_device_in_scope(device, policy=policy):
            raise ScopeViolationError(
                f"Refusing out-of-scope device: {device!r}. Only local/lab devices are permitted."
            )
        checked["device"] = device.strip()

    if not checked:
        raise ScopeViolationError("No target provided to assert_in_scope().")

    return checked


def filter_in_scope_hosts(
    targets: Iterable[str], policy: LabScopePolicy = DEFAULT_POLICY
) -> list[str]:
    """Return only the hosts/URLs from targets that satisfy the lab scope policy."""
    return [t for t in targets if is_host_in_scope(t, policy=policy)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate whether a host, package, or device is within authorized os-lab scope."
    )
    parser.add_argument("--host", help="Hostname, IP, or URL to verify")
    parser.add_argument("--package", help="Android package name to verify")
    parser.add_argument("--device", help="ADB/Frida device serial or endpoint to verify")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output")
    args = parser.parse_args(argv)

    try:
        verified = assert_in_scope(host=args.host, package=args.package, device=args.device)
    except ScopeViolationError as exc:
        if args.json:
            print(json.dumps({"in_scope": False, "error": str(exc)}, indent=2))
        else:
            print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"in_scope": True, "verified": verified}, indent=2))
    else:
        print(f"[ALLOWED] Target verified in lab scope: {verified}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
