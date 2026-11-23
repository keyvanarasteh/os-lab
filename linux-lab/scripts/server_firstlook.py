#!/usr/bin/env python3
"""OS-16: read-only first-look report for an owned Linux lab (stdlib only)."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
import platform
import re
import subprocess
import sys


COMMANDS = {
    "uname": ["uname", "-srm"],
    "lsb_release": ["lsb_release", "-d"],
    "inxi": ["inxi", "-C", "-c", "0"],
    "free": ["free", "-b"],
    "df": ["df", "-P", "-k", "-l"],
    "systemctl": ["systemctl", "--no-pager", "--plain", "list-units",
                  "--type=service", "--all", "--no-legend"],
}


def clean_text(text):
    """Do not echo terminal escape/control sequences from command output."""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return "".join(c for c in text if c in "\n\t" or c.isprintable()).strip()


def execute_fixed_command(name, options):
    """Only literal argument lists reach subprocess; no caller-supplied argv."""
    if name == "uname":
        return subprocess.run(["uname", "-srm"], **options)
    if name == "lsb_release":
        return subprocess.run(["lsb_release", "-d"], **options)
    if name == "inxi":
        return subprocess.run(["inxi", "-C", "-c", "0"], **options)
    if name == "free":
        return subprocess.run(["free", "-b"], **options)
    if name == "df":
        return subprocess.run(["df", "-P", "-k", "-l"], **options)
    if name == "systemctl":
        return subprocess.run(["systemctl", "--no-pager", "--plain", "list-units",
                               "--type=service", "--all", "--no-legend"], **options)
    raise ValueError("Unknown diagnostic command.")


def run_command(name, timeout):
    if not isinstance(name, str) or name not in COMMANDS:
        raise ValueError("Unknown diagnostic command.")
    argv = COMMANDS[name]
    result = {"command": argv, "status": "ok", "returncode": None,
              "stdout": "", "stderr": ""}
    env = dict(os.environ, LC_ALL="C", LANG="C", SYSTEMD_COLORS="0")
    try:
        proc = execute_fixed_command(name, dict(capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", shell=False,
                                     timeout=timeout, env=env, check=False))
        result.update(returncode=proc.returncode,
                      stdout=clean_text(proc.stdout), stderr=clean_text(proc.stderr))
        if proc.returncode != 0:
            result["status"] = "error"
    except FileNotFoundError:
        result.update(status="missing", stderr=f"{argv[0]} is not installed.")
    except subprocess.TimeoutExpired:
        result.update(status="timeout", stderr=f"Command exceeded {timeout:g} seconds.")
    except OSError as exc:
        result.update(status="error", stderr=clean_text(str(exc)))
    return result


def parse_uname(text):
    fields = text.split()
    if len(fields) != 3:
        raise ValueError("Expected kernel name, release and architecture from uname -srm.")
    return dict(zip(("kernel", "release", "architecture"), fields))


def parse_distribution(text):
    match = re.fullmatch(r"Description:[ \t]+(\S[^\n]*)", text.strip())
    if not match:
        raise ValueError("Unrecognized lsb_release -d description.")
    return match.group(1).strip()


def parse_hardware(text):
    if not (re.search(r"(?m)^\s*CPU:\s*\S", text)
            and re.search(r"\bmodel:[ \t]*\S", text)):
        raise ValueError("Unrecognized inxi CPU report (CPU/model fields missing).")
    return text


def parse_memory(text):
    lines = [line.split() for line in text.splitlines() if line.strip()]
    header = next((row for row in lines if row[0] == "total"), None)
    mem = next((row[1:] for row in lines if row[0] == "Mem:"), None)
    if not header or not mem or len(header) != len(mem):
        raise ValueError("Unrecognized free -b output.")
    values = dict(zip(header, map(int, mem)))
    if not {"total", "used", "free", "available"} <= values.keys():
        raise ValueError("free -b does not expose total/used/free/available memory.")
    if any(value < 0 for value in values.values()):
        raise ValueError("Memory values must be non-negative.")
    return {key + "_bytes": values[key] for key in ("total", "used", "free", "available")}


def parse_disks(text):
    lines = text.splitlines()
    disks = []
    for line in lines[1:]:
        if not line.strip():
            continue
        match = re.fullmatch(r"(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+%|-)\s+(.+)", line)
        if not match:
            raise ValueError("Unrecognized df -P -k -l row.")
        device, size, used, available, percent, mount = match.groups()
        if percent == "-" and int(size) != 0:
            raise ValueError("Unavailable df capacity is only valid for zero-sized filesystems.")
        disks.append({"filesystem": device, "mountpoint": mount,
                      "total_bytes": int(size) * 1024,
                      "used_bytes": int(used) * 1024,
                      "available_bytes": int(available) * 1024,
                      "used_percent": None if percent == "-" else int(percent[:-1])})
    if not disks:
        raise ValueError("df returned no local filesystems.")
    return disks


def parse_services(text):
    units = []
    load_states = {"loaded", "error", "not-found", "bad-setting", "masked", "merged", "stub"}
    active_states = {"active", "reloading", "inactive", "failed", "activating",
                     "deactivating", "maintenance", "refreshing"}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split(None, 4)
        if len(fields) < 4 or not fields[0].endswith(".service"):
            raise ValueError("Unrecognized systemctl service row.")
        if fields[1] not in load_states or fields[2] not in active_states:
            raise ValueError("Unrecognized systemctl load/active state.")
        units.append(dict(zip(("unit", "load", "active", "sub"), fields[:4])))
    if not units:
        raise ValueError("systemctl returned no service data.")
    return {"units": units, "failed": [u["unit"] for u in units if u["active"] == "failed"]}


def architecture_note(arch):
    names = {
        "x86_64": "Debian/Ubuntu packages usually use amd64; RPM packages use x86_64.",
        "aarch64": "Debian/Ubuntu packages usually use arm64; RPM packages use aarch64.",
        "arm64": "Debian/Ubuntu packages usually use arm64; RPM packages use aarch64.",
        "i686": "This is a 32-bit x86 kernel; check i386 package support for the distro.",
        "i386": "This is a 32-bit x86 kernel; check i386 package support for the distro.",
    }
    return (names.get(arch, "Check the distro package architecture before choosing a download.")
            + " uname reports the kernel architecture; userspace may differ. "
            "Confirm with dpkg --print-architecture or rpm --eval '%{_arch}' when available.")


def collect_report(timeout=5.0):
    checks = {name: run_command(name, timeout) for name in COMMANDS}

    def parsed(name, parser):
        check = checks[name]
        if check["status"] != "ok":
            return None
        try:
            return parser(check["stdout"])
        except ValueError as exc:
            check.update(status="parse-error", stderr=str(exc))
            return None

    system = parsed("uname", parse_uname)
    memory = parsed("free", parse_memory)
    disks = parsed("df", parse_disks)
    services = parsed("systemctl", parse_services)
    distro = parsed("lsb_release", parse_distribution)
    hardware = parsed("inxi", parse_hardware)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": all(c["status"] == "ok" for c in checks.values()),
        "system": system,
        "distribution": distro,
        "architecture_note": architecture_note(system["architecture"] if system else None),
        "hardware": hardware,
        "memory": memory, "disks": disks, "services": services, "checks": checks,
    }


def render_text(report):
    lines = ["OS-16 | Server First-Look Health Report", f"UTC: {report['generated_at']}",
             "Collection: " + ("complete" if report["complete"] else "partial (see command checks)"),
             "", "SYSTEM", f"Distribution: {report['distribution'] or 'unavailable'}"]
    system = report["system"]
    if system:
        lines.append(f"Kernel: {system['kernel']} {system['release']}")
        lines.append(f"Architecture: {system['architecture']}")
    else:
        lines.append("Kernel / architecture: unavailable")
    lines += [report["architecture_note"], "", "CPU (inxi)", report["hardware"] or "unavailable",
              "", "MEMORY"]
    mem = report["memory"]
    if mem:
        lines.append(" | ".join(f"{key.removesuffix('_bytes')}: {value / 2**30:.2f} GiB"
                                for key, value in mem.items()))
    else:
        lines.append("unavailable")
    lines += ["", "LOCAL DISKS"]
    if report["disks"]:
        for disk in report["disks"]:
            usage = ("usage unavailable" if disk['used_percent'] is None
                     else f"{disk['used_percent']}% used")
            lines.append(f"{disk['mountpoint']}: {usage}, "
                         f"{disk['available_bytes'] / 2**30:.2f} GiB available "
                         f"({disk['filesystem']})")
    else:
        lines.append("unavailable")
    lines += ["", "SERVICES (loaded service units, including inactive)"]
    services = report["services"]
    if services is not None:
        lines.append(f"Listed: {len(services['units'])}; failed: {len(services['failed'])}")
        for unit in services["units"]:
            lines.append(f"{unit['unit']}: {unit['active']}/{unit['sub']} (load={unit['load']})")
    else:
        lines.append("unavailable; service health could not be determined")
    lines += ["", "COMMAND CHECKS"]
    for name, check in report["checks"].items():
        detail = f": {check['stderr']}" if check["stderr"] else ""
        lines.append(f"{name}: {check['status']}{detail}")
    return "\n".join(lines)


def timeout_value(value):
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 60:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 60 seconds")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit only JSON to stdout")
    parser.add_argument("--timeout", type=timeout_value, default=5.0,
                        help="timeout per command in seconds (default: 5; maximum: 60)")
    args = parser.parse_args(argv)
    if platform.system() != "Linux":
        parser.error("run this tool inside your Linux lab/VM")
    report = collect_report(args.timeout)
    output = json.dumps(report, indent=2, ensure_ascii=True) if args.json else render_text(report)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(output.encode(encoding, errors="backslashreplace").decode(encoding))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
