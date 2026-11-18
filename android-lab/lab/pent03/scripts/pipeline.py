#!/usr/bin/env python3
"""End-to-end PENT-03 orchestrator: boot -> frida -> CA -> proxy -> unpin.

Runs the headless analysis pipeline against a lab emulator, logging every step
so a run is reproducible and auditable (PENT-14 style per-step log). Order:

1. **scope** — refuse anything that isn't a lab emulator + lab package.
2. **boot** — wait for the emulator to finish booting.
3. **frida** — deploy and start ``frida-server`` for the device ABI.
4. **ca** — install the mitmproxy CA into the system trust store.
5. **proxy** — point the device's global HTTP proxy at the mitmproxy host.
6. **unpin** — run objection's universal SSL-pinning bypass on the target app.

``plan()`` is a pure function (used in tests). ``--dry-run`` prints the plan and
the exact commands without touching a device.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

import adb
import deploy_frida
import install_ca
import report as report_mod
import scope
import sslpinning_bypass

#: host:port the emulator reaches mitmproxy on. ``10.0.2.2`` is the emulator's
#: alias for its own host, so this is correct for the host-mode run (a local
#: emulator with mitmproxy on the host). For the docker-compose stack, pass
#: ``--proxy`` with the address at which the emulator container reaches the
#: ``mitmproxy`` service (see docker/docker-compose.yml and the README).
DEFAULT_PROXY = "10.0.2.2:8080"

STEPS = ("scope", "boot", "frida", "ca", "proxy", "unpin")


def plan(*, skip: tuple[str, ...] = ()) -> list[str]:
    """Return the ordered list of steps that will run, minus ``skip``."""
    return [s for s in STEPS if s not in skip]


def parse_proxy(proxy: str) -> tuple[str, int]:
    """Parse and validate a ``host:port`` proxy string.

    Returns ``(host, port)``. Raises :class:`ValueError` on anything that is not
    a bare host plus a numeric 1–65535 port — so no shell metacharacters (e.g.
    ``10.0.2.2:8080;id``) can ever reach ``adb shell`` as a device-side command.
    The host must also be an in-scope lab proxy host.
    """
    proxy = (proxy or "").strip()
    if proxy.count(":") != 1:
        raise ValueError(f"proxy must be exactly host:port, got {proxy!r}")
    host, port = proxy.rsplit(":", 1)
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        raise ValueError(f"proxy port must be a number in 1..65535, got {port!r}")
    if not scope.proxy_host_in_scope(host):
        raise ValueError(f"proxy host {host!r} is not an in-scope lab host")
    return host, int(port)


def set_proxy_command(proxy: str) -> list[str]:
    """adb args that set the device-wide HTTP proxy to a validated ``host:port``."""
    host, port = parse_proxy(proxy)
    return ["settings", "put", "global", "http_proxy", f"{host}:{port}"]


def clear_proxy_command() -> list[str]:
    """adb args that clear the device-wide HTTP proxy."""
    return ["settings", "put", "global", "http_proxy", ":0"]


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class PipelineReport:
    package: str
    serial: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append(StepResult(name, ok, detail))
        mark = "ok " if ok else "FAIL"
        print(f"  [{mark}] {name}: {detail}")


def run_pipeline(
    package: str,
    *,
    serial: str = "emulator-5554",
    proxy: str = DEFAULT_PROXY,
    frida_version: str = deploy_frida.DEFAULT_FRIDA_VERSION,
    ca_path: str | None = None,
    skip: tuple[str, ...] = (),
    sleep=time.sleep,
) -> PipelineReport:
    """Execute the pipeline against a device. Returns a :class:`PipelineReport`."""
    report = PipelineReport(package=package, serial=serial)
    steps = plan(skip=skip)
    # parse_proxy validates host:port up front (and raises on anything unsafe).
    proxy_host, _ = parse_proxy(proxy)

    # 1. scope — always enforced, never skippable. A scope failure is fatal and
    #    raises before any device action.
    scope.assert_in_scope(serial=serial, package=package, proxy_host=proxy_host)
    report.add("scope", True, f"{serial} / {package} / {proxy_host}")

    # Each subsequent step is recorded even on failure, and the first failure
    # stops the run so a partial but complete audit trail is always available.
    def _step(name: str, fn) -> bool:
        try:
            detail = fn()
            report.add(name, True, detail)
            return True
        except Exception as exc:  # recorded, not swallowed — run stops after this
            report.add(name, False, f"{type(exc).__name__}: {exc}")
            return False

    if "boot" in steps:
        def _boot():
            adb.wait_for_boot(serial, sleep=sleep)
            return "emulator boot_completed"
        if not _step("boot", _boot):
            return report

    if "frida" in steps:
        def _frida():
            ver = deploy_frida.deploy(serial, version=frida_version)
            return f"frida-server {ver} running"
        if not _step("frida", _frida):
            return report

    if "ca" in steps:
        def _ca():
            remote = install_ca.install(serial, ca_path)
            return f"mitmproxy CA at {remote}"
        if not _step("ca", _ca):
            return report

    if "proxy" in steps:
        def _proxy():
            adb.shell(serial, *set_proxy_command(proxy))
            return f"global http_proxy -> {proxy}"
        if not _step("proxy", _proxy):
            return report

    if "unpin" in steps:
        def _unpin():
            code = sslpinning_bypass.bypass(package, serial=serial)
            if code != 0:
                raise sslpinning_bypass.BypassError(f"objection exit={code}")
            return "objection exit=0"
        _step("unpin", _unpin)

    return report


def _print_dry_run(package: str, serial: str, proxy: str, skip: tuple[str, ...]) -> None:
    steps = plan(skip=skip)
    print(f"DRY RUN — pipeline for {package} on {serial}")
    print(f"  steps: {' -> '.join(steps)}")
    print("  commands that would run:")
    if "frida" in steps:
        print(f"    deploy_frida.deploy({serial!r}, version={deploy_frida.DEFAULT_FRIDA_VERSION!r})")
    if "ca" in steps:
        print(f"    install_ca.install({serial!r})")
    if "proxy" in steps:
        print(f"    adb -s {serial} shell {' '.join(set_proxy_command(proxy))}")
    if "unpin" in steps:
        print("    " + " ".join(sslpinning_bypass.objection_argv(package, serial=serial)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PENT-03 analysis pipeline.")
    parser.add_argument("package", help="target application id (lab-owned)")
    parser.add_argument("-s", "--serial", default="emulator-5554")
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    parser.add_argument("--frida-version", default=deploy_frida.DEFAULT_FRIDA_VERSION)
    parser.add_argument("--ca", default=None)
    parser.add_argument(
        "--skip", default="", help="comma-separated steps to skip (boot,frida,ca,proxy,unpin)"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report",
        nargs="?",
        const="runs",
        default=None,
        metavar="DIR",
        help="write a timestamped JSON+Markdown run report into DIR (default: runs/)",
    )
    args = parser.parse_args(argv)
    skip = tuple(s.strip() for s in args.skip.split(",") if s.strip())

    try:
        proxy_host, _ = parse_proxy(args.proxy)
    except ValueError as exc:
        print(f"invalid --proxy: {exc}", file=sys.stderr)
        return 2

    try:
        scope.assert_in_scope(
            serial=args.serial,
            package=args.package,
            proxy_host=proxy_host,
        )
    except scope.ScopeError as exc:
        print(f"OUT OF SCOPE: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        _print_dry_run(args.package, args.serial, args.proxy, skip)
        return 0

    # run_pipeline records each step (including failures) and returns a report;
    # only a scope/validation error raises, which we already guarded above.
    report = run_pipeline(
        args.package,
        serial=args.serial,
        proxy=args.proxy,
        frida_version=args.frida_version,
        ca_path=args.ca,
        skip=skip,
    )

    # Always write the report (even a partial one on failure) before returning.
    if args.report:
        json_path, md_path = report_mod.write_report(report, args.report)
        print(f"  [report] {json_path}")
        print(f"  [report] {md_path}")

    print()
    if report.ok:
        print("pipeline complete — point mitmproxy at the flows and start analysis.")
        return 0
    print("pipeline finished with failures.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
