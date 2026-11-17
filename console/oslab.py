"""os-lab host engine: host detection, lab availability, typed action plans, jobs and monitoring.

A standard-library port of the OS Lab desktop runtime in qLar PR #174
(os_lab_runtime.rs, os_lab_provider.rs, os_lab_jobs.rs, os_lab_monitor.rs):

- ``host_info()``      what this computer is: OS, arch, CPU, memory, disk, KVM, WSL and host tools.
- ``lab_catalog()``    which labs this host can run, through which provider, and what is missing.
- ``plan()``           a typed, validated command for one lab action. Pages never send command
                       strings: they send {lab, action, profile, ...} and get back the exact
                       program, arguments, effects and setup prerequisites to confirm.
- ``JobService``       runs a confirmed plan in the background with captured, secret-redacted
                       output, a timeout and cancellation.
- ``monitor()``        container state and resource use for a lab.
- ``scope_status()``   the declared lab scope; scope_guard.py refuses targets outside it.

The web console in android-lab/lab/web_ui.py exposes these over a localhost JSON API.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import platform
import re
import secrets as _secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

# ── Static lab model ─────────────────────────────────────────────────────────

LAB_ORDER = ["android", "windows", "winapps", "linux", "ios", "macos", "source", "web"]

LABS = {
    "source": {"label": "Source Lab", "dir": "source-lab", "labctl": "source", "containers": [],
               "summary": "Local source and package analysis across five platforms."},
    "web": {"label": "Web Lab", "dir": "web-lab", "labctl": "web", "containers": [],
            "summary": "Embedded in-app browser with JavaScript injection for webview security work."},
    "android": {
        "label": "Android Lab",
        "dir": "android-lab/lab",
        "labctl": "android",
        "containers": ["lab-android", "lab-mobsf", "lab-mitmproxy", "lab-tools"],
        "summary": "Docker-Android emulator, MobSF, mitmproxy and Frida for mobile security work.",
    },
    "windows": {
        "label": "Windows Lab",
        "dir": "win-lab",
        "labctl": "win",
        "containers": ["win-lab"],
        "disk_default": "64G",
        "summary": "Windows in Docker with KVM, a web desktop, RDP and shared storage.",
    },
    "winapps": {
        "label": "Windows Apps Lab",
        "dir": "console",  # the lab is console/winapps.py; there is no lab folder of its own
        "labctl": None,
        "containers": [],
        "summary": "Read-only mirror of visible desktop applications on this Windows host.",
    },
    "linux": {
        "label": "Linux Lab",
        "dir": "linux-lab",
        "labctl": "linux",
        "containers": ["linux-lab"],
        "summary": "Linux in Docker with KVM, a web console, SSH and shared storage.",
    },
    "ios": {
        "label": "iOS Lab",
        "dir": "ios-lab",
        "labctl": "ios",
        "containers": ["ios-lab"],
        "disk_default": "128G",
        "summary": "iOS tooling through a macOS VM on a Linux/KVM host, or native Xcode on a Mac.",
    },
    "macos": {
        "label": "macOS Lab",
        "dir": "ios-lab/mac",
        "labctl": None,
        "containers": [],
        "summary": "Automate this Mac's applications with Appium and the mac2 driver.",
    },
}

# Tools reported on the host page (id, label). Mirrors os_lab_runtime.rs plus a few installers.
TOOLS = [
    ("docker", "Docker CLI"),
    ("podman", "Podman CLI"),
    ("bash", "Bash"),
    ("make", "Make"),
    ("git", "Git"),
    ("python3", "Python 3"),
    ("cargo", "Rust (Cargo)"),
    ("adb", "Android Debug Bridge"),
    ("java", "Java"),
    ("xcrun", "Xcode tools"),
    ("brew", "Homebrew"),
    ("node", "Node.js"),
    ("appium", "Appium"),
    ("wsl", "Windows Subsystem for Linux"),
    ("apt-get", "APT package manager"),
    ("pkexec", "Polkit (graphical sudo)"),
    ("sudo", "sudo"),
    ("idb", "idb client"),
    ("idb-companion", "idb companion"),
]

# Tools that only make sense on some hosts; everything else is reported everywhere.
TOOL_HOSTS = {
    "xcrun": {"macos"}, "brew": {"macos"}, "idb": {"macos"}, "idb-companion": {"macos"},
    "wsl": {"windows"},
    "apt-get": {"linux"}, "pkexec": {"linux"}, "sudo": {"linux", "macos"},
}


def tools_for_host(os_name: str) -> list[tuple[str, str]]:
    return [(t, label) for t, label in TOOLS if os_name in TOOL_HOSTS.get(t, {os_name})]


LABCTL_ACTIONS = ["status", "doctor", "urls", "logs", "monitor", "start", "stop", "restart",
                  "profile", "resize", "setup", "backup", "service-install", "service-uninstall"]
# The iOS Lab's native path: simulator lifecycle plus optional Appium/idb device automation.
MAC_ACTIONS = ["status", "doctor", "setup", "start", "stop", "appium-install", "appium-start", "appium-stop",
               "idb-install", "idb-start", "idb-stop", "xcuitest-smoke"]
# The macOS Lab automates installed macOS applications through Appium mac2 — no simulator.
# macos-click, macos-input and macos-element drive the app mirror panel (never plain buttons).
MACOS_APP_ACTIONS = ["status", "doctor", "setup", "appium-install", "appium-start", "appium-stop", "macos-smoke",
                     "macos-click", "macos-input", "macos-element", "macos-set-value", "macos-perform",
                     "macos-scroll"]

ACTION_INFO = {
    "csv-merge": ("Join catalogs", "Join operator catalogs into private storage."),
    "detect": ("Detect", "Analyze a selected local target."),
    "crawl": ("Crawl", "Analyze explicitly selected repositories."),
    "merge": ("Merge", "Plan or build selected authorized extensions."),
    "runtime": ("Runtime settings", "Change private Source Lab runtime settings."),
    "status": ("Status", "One-shot state, endpoints and resource report."),
    "doctor": ("Doctor", "Run the lab preflight: OS, KVM, runtime, ports and disk."),
    "urls": ("URLs", "Print the lab's access addresses."),
    "logs": ("Logs", "Show recent container logs."),
    "monitor": ("Snapshot", "One monitor frame: containers, CPU and memory."),
    "start": ("Start", "Start the lab stack with the current configuration."),
    "stop": ("Stop", "Stop the lab stack."),
    "restart": ("Restart", "Recreate the stack from the current configuration."),
    "profile": ("Apply profile", "Write a profile preset (lightweight/development/performance) to .env."),
    "resize": ("Resize", "Change CPU/RAM (and disk for Windows) in .env; restart to apply."),
    "setup": ("Install dependencies", "Install the host prerequisites for this lab."),
    "backup": ("Backup", "Write a guest backup archive into the lab's backups/ folder."),
    "service-install": ("Install boot service", "Start this lab automatically at boot (systemd)."),
    "service-uninstall": ("Remove boot service", "Remove the systemd boot unit."),
    "appium-install": ("Install Appium", "Install Node (Homebrew if needed), Appium and the XCUITest/mac2 drivers for this user only. No administrator rights."),
    "appium-start": ("Start Appium", "Start the Appium server for the installed automation drivers."),
    "appium-stop": ("Stop Appium", "Stop the Appium server."),
    "idb-install": ("Install idb", "Install idb companion (Homebrew) and the idb client for this user only. No administrator rights."),
    "idb-start": ("Start idb", "Start an idb companion for the booted simulator."),
    "idb-stop": ("Stop idb", "Stop the idb companion."),
    "xcuitest-smoke": ("XCUITest smoke test", "Run one real XCUITest session through Appium and WebDriverAgent on the booted simulator."),
    "macos-smoke": ("macOS app smoke test", "Run one real Appium mac2 session that activates Finder on this Mac."),
    "macos-click": ("Click in app", "Bring the mirrored app to the front and click once at the chosen point."),
    "macos-input": ("Mirror input action", "Run the previewed double-click, right-click, typed text or key press from the app mirror. Typed text never sends Return."),
    "macos-element": ("Deep-inspect element action", "Click or type into one element through the open mac2 deep-inspect session for the mirrored app."),
    "macos-set-value": ("Set element value", "Write a value straight into one accessibility element (settable elements only) via the native AX helper."),
    "macos-perform": ("Perform element action", "Run one action the element advertises (e.g. AXPress, AXShowMenu) through the native AX helper."),
    "macos-scroll": ("Scroll in app", "Scroll the mirrored window vertically at the chosen point (line-based; horizontal is not supported)."),
}

# On the iOS Lab's native path "start" and "stop" drive the iOS Simulator, not a container stack.
NATIVE_SIMULATOR_INFO = {
    "start": ("Start iOS Simulator", "Boot an installed iOS Simulator device on this Mac."),
    "stop": ("Stop iOS Simulator", "Shut every booted iOS Simulator down."),
}

# Offered while a required dependency is missing: install it, install Appium or idb, or run the preflight.
SETUP_STATE_ACTIONS = {"setup", "appium-install", "idb-install", "doctor"}

PRIVILEGED = {"setup", "service-install", "service-uninstall"}
SECRET_PARTS = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "PRIVATE_KEY", "CREDENTIAL")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SIZE = re.compile(r"^[1-9][0-9]{0,5}[MmGgTt]?$")


class PlanError(ValueError):
    """A request the lab model refuses; the message is safe to show to the user. Agent-surface
    failures carry a machine code (MIR-08) and a retry hint, like computer-use runtimes."""

    def __init__(self, message: str, code: str | None = None, retry: str | None = None):
        super().__init__(message)
        self.code = code
        self.retry = retry


# ── Host detection ───────────────────────────────────────────────────────────

def host_os() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    return sys.platform


def host_arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(m, m)


def _managed_appium() -> str | None:
    """Appium installed by ios-lab/mac/appium.sh install (user folder, no global npm)."""
    path = os.path.join(os.environ.get("OSLAB_APPIUM_HOME") or os.path.expanduser("~/.oslab/appium"),
                        "node_modules", ".bin", "appium")
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


def _managed_idb() -> str | None:
    """idb client installed by ios-lab/mac/idb.sh install (its own virtualenv, no PATH changes)."""
    path = os.path.join(os.environ.get("OSLAB_IDB_HOME") or os.path.expanduser("~/.oslab/idb"), "bin", "idb")
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


def _idb_companion() -> str | None:
    """Homebrew's idb-companion formula installs `idb_companion` (underscore); accept both spellings."""
    return shutil.which("idb_companion") or shutil.which("idb-companion")


def _which(name: str) -> str | None:
    found = shutil.which(name)
    return found or {"appium": _managed_appium, "idb": _managed_idb, "idb-companion": _idb_companion}.get(name, lambda: None)()


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _capture(args: list[str], timeout: float = 5.0, decode: str = "utf-8") -> tuple[int, str]:
    try:
        out = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return out.returncode, out.stdout.decode(decode, errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def os_pretty(os_name: str) -> str:
    if os_name == "linux":
        for line in _read("/etc/os-release").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
        return "Linux " + platform.release()
    if os_name == "macos":
        return "macOS " + (platform.mac_ver()[0] or platform.release())
    if os_name == "windows":
        return "Windows " + platform.release() + " (" + platform.version() + ")"
    return platform.platform()


def memory_bytes(os_name: str) -> int | None:
    try:
        if os_name == "linux":
            m = re.search(r"MemTotal:\s+(\d+)\s+kB", _read("/proc/meminfo"))
            return int(m.group(1)) * 1024 if m else None
        if os_name == "macos":
            code, out = _capture(["sysctl", "-n", "hw.memsize"])
            return int(out.strip()) if code == 0 else None
        if os_name == "windows":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return int(status.ullTotalPhys)
    except (OSError, ValueError, AttributeError):
        return None
    return None


def wsl_distributions() -> list[str]:
    """Installed WSL distributions (Windows host only). `wsl -l -q` prints UTF-16LE."""
    if host_os() != "windows" or not _which("wsl"):
        return []
    code, out = _capture(["wsl", "-l", "-q"], timeout=10, decode="utf-16-le")
    if code != 0:
        return []
    return [d.strip().strip("\x00") for d in out.splitlines() if d.strip().strip("\x00")]


def container_runtime() -> str | None:
    for name in ("docker", "podman"):
        if _which(name) and _capture([name, "info"], timeout=5)[0] == 0 \
                and _capture([name, "compose", "version"], timeout=5)[0] == 0:
            return name
    return None


def xcode_status() -> dict:
    """Full Xcode and an available iOS Simulator, not just the command-line tools.

    Detection follows ``xcode-select``/PATH, never an assumed install path, so a
    copy of Xcode on a non-system volume is reported with its real location.
    """
    if host_os() != "macos":
        return {"installed": False, "developerDir": None, "xcodeApp": None, "iosRuntime": False, "iosDevice": False}
    installed = _capture(["xcodebuild", "-version"], timeout=5)[0] == 0
    developer_dir = None
    if installed:
        code, output = _capture(["xcode-select", "-p"], timeout=5)
        if code == 0:
            developer_dir = output.strip() or None
    xcode_app = None
    if developer_dir and developer_dir.endswith("/Contents/Developer"):
        xcode_app = developer_dir[: -len("/Contents/Developer")]
    if not installed:
        return {"installed": False, "developerDir": None, "xcodeApp": None, "iosRuntime": False, "iosDevice": False}
    code, output = _capture(["xcrun", "simctl", "list", "-j", "devices", "available"], timeout=10)
    try:
        devices = json.loads(output)["devices"] if code == 0 else {}
        ios_device = any("iOS" in runtime and any(d.get("isAvailable", True) for d in entries)
                         for runtime, entries in devices.items())
    except (ValueError, KeyError, TypeError, AttributeError):
        ios_device = False
    code, output = _capture(["xcrun", "simctl", "list", "runtimes"], timeout=10)
    ios_runtime = code == 0 and any(line.startswith("iOS ") for line in output.splitlines())
    return {"installed": installed, "developerDir": developer_dir, "xcodeApp": xcode_app,
            "iosRuntime": ios_runtime, "iosDevice": ios_device}


# ── iOS Simulator panel (native macOS) ───────────────────────────────────────

UDID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")


def _simctl_json(args: list[str]) -> dict:
    """`xcrun simctl list -j …` as a dict, or {} when simctl is missing, slow or fails."""
    if host_os() != "macos" or not _which("xcrun"):
        return {}
    code, output = _capture(["xcrun", "simctl"] + args, timeout=15)
    try:
        return json.loads(output) if code == 0 else {}
    except ValueError:
        return {}


def ios_simulator(root: str) -> dict:
    """Simulator panel data for the iOS Lab: installed devices, runtimes and what is booted."""
    devices_json = _simctl_json(["list", "-j", "devices"])
    if not devices_json:
        return {"available": False, "reason": "Xcode and its simulator tooling are not usable on this Mac",
                "devices": [], "runtimes": [], "booted": [], "configuredDevice": None}
    runtimes_json = _simctl_json(["list", "-j", "runtimes"])
    runtimes = {r.get("identifier", ""): r.get("name") or f"iOS {r.get('version', '')}"
                for r in runtimes_json.get("runtimes", []) if "iOS" in r.get("name", "")}
    devices = []
    for runtime, entries in devices_json.get("devices", {}).items():
        if "iOS" not in runtime:
            continue
        for d in entries:
            if not d.get("isAvailable", True):
                continue
            devices.append({"udid": d.get("udid", ""), "name": d.get("name", ""),
                            "runtime": runtimes.get(runtime, runtime), "state": d.get("state", "")})
    devices.sort(key=lambda d: (d["name"], d["runtime"]))
    config = env_entries(_read(os.path.join(root, "ios-lab", "mac", "config.env")))
    return {"available": True, "reason": None, "devices": devices,
            "runtimes": sorted(set(runtimes.values())),
            "booted": [d for d in devices if d["state"] == "Booted"],
            "configuredDevice": config.get("SIM_DEVICE") or None}


def ios_screenshot(udid: str | None = None) -> bytes:
    """A PNG of the selected booted simulator, or the sole/default booted device."""
    if udid and not UDID.fullmatch(udid):
        raise PlanError("That simulator id does not look like a UDID")
    code, output = _capture(["xcrun", "simctl", "list", "devices"], timeout=15)
    if code != 0 or not any("Booted" in line and (not udid or udid in line) for line in output.splitlines()):
        raise PlanError("The selected iOS Simulator is not booted; attach it first" if udid else "No iOS Simulator is booted; attach one first")
    fd, path = tempfile.mkstemp(suffix=".png")
    try:
        os.close(fd)
        code, output = _capture(["xcrun", "simctl", "io", udid or "booted", "screenshot", "--type=png", path], timeout=30)
        if code != 0:
            raise PlanError("Could not take a simulator screenshot: " + output.strip()[:200])
        with open(path, "rb") as f:
            png = f.read()
        if not png.startswith(b"\x89PNG"):
            raise PlanError("The simulator screenshot was not a readable PNG")
        return png
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def ios_real_device_screenshot(udid: str) -> bytes:
    """Capture a selected physical device with Xcode's devicectl, without starting automation."""
    if not isinstance(udid, str) or not UDID.fullmatch(udid):
        raise PlanError("That device id does not look like a UDID")
    if host_os() != "macos" or not _which("xcrun"):
        raise PlanError("Xcode device capture is not available on this Mac")
    fd, path = tempfile.mkstemp(suffix=".png")
    try:
        os.close(fd)
        os.unlink(path)  # devicectl creates its destination file.
        code, output = _capture(["xcrun", "devicectl", "device", "capture", "screenshot",
                                 "--device", udid, "--destination", path], timeout=30)
        if code != 0:
            raise PlanError("Could not capture the real device: " + (output.strip().splitlines()[-1][:200] if output.strip() else "the device did not answer"))
        with open(path, "rb") as f:
            png = f.read()
        if not png.startswith(b"\x89PNG"):
            raise PlanError("The real-device screenshot was not a readable PNG")
        return png
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _os_version(value) -> str:
    """devicectl reports an osVersion string or a {major, minor, patch} dict; both become a string."""
    if isinstance(value, dict):
        parts = [value.get(key) for key in ("major", "minor", "patch")]
        return ".".join(str(part) for part in parts if part is not None)
    return str(value or "")


def ios_devices() -> dict:
    """Real iOS devices (connected or paired) via `xcrun devicectl`, read-only.

    Screen capture is available separately; driving a device still needs
    Developer Mode and a signed WebDriverAgent (ios-lab/mac/README.md).
    """
    if host_os() != "macos" or not _which("xcrun"):
        return {"available": False, "reason": "Xcode and its device tooling are not usable on this Mac",
                "devices": []}
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        os.close(fd)
        code, output = _capture(["xcrun", "devicectl", "list", "devices", "--json-output", path], timeout=15)
        if code != 0:
            reason = output.strip().splitlines()[-1][:200] if output.strip() else "devicectl failed"
            return {"available": False, "reason": reason, "devices": []}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {"available": False, "reason": "devicectl returned unreadable output", "devices": []}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    devices = []
    for entry in (data.get("result") or {}).get("devices") or []:
        if not isinstance(entry, dict):
            continue
        # devicectl also lists simulators here; visibilityClass separates them from real hardware.
        if (entry.get("visibilityClass") or "") == "simulators":
            continue
        props = entry.get("deviceProperties") or {}
        hardware = entry.get("hardwareProperties") or {}
        connection = entry.get("connectionProperties") or {}
        # transportType names how the device is paired: localNetwork (Wi-Fi) vs a USB
        # wire. A Wi-Fi-paired device stays listed even while its tunnel is down.
        devices.append({
            "udid": entry.get("identifier") or hardware.get("udid") or "",
            "name": props.get("name") or "",
            "osVersion": _os_version(props.get("osVersionNumber") or props.get("osVersion")),
            "state": connection.get("tunnelState") or connection.get("pairingState") or "",
            "paired": (connection.get("pairingState") or "") == "paired",
            "transport": connection.get("transportType") or None,
            "lastSeen": connection.get("lastConnectionDate") or None,
        })
    devices.sort(key=lambda d: (d["name"], d["udid"]))
    return {"available": True, "reason": None, "devices": devices}


def ios_device_check(udid: str) -> dict:
    """Check a device's current tunnel state; details can succeed for an offline paired device."""
    if not isinstance(udid, str) or not UDID.match(udid):
        raise PlanError("That device id does not look like a UDID")
    if host_os() != "macos" or not _which("xcrun"):
        return {"reachable": False, "reason": "The device tooling is not usable on this Mac"}
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        os.close(fd)
        code, output = _capture(["xcrun", "devicectl", "device", "info", "details", "--device", udid,
                                 "--json-output", path], timeout=25)
        if code != 0:
            reason = output.strip().splitlines()[-1][:200] if output.strip() else "the device did not answer"
            return {"reachable": False, "reason": reason}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"reachable": False, "reason": "devicectl returned unreadable output"}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    result = data.get("result") or {}
    props = result.get("deviceProperties") or {}
    connection = result.get("connectionProperties") or {}
    state = connection.get("tunnelState") or "unavailable"
    reachable = state == "connected"
    return {"reachable": reachable,
            "reason": None if reachable else f"Device is paired, but its connection tunnel is {state}.",
            "name": props.get("name") or "",
            "osVersion": _os_version(props.get("osVersionNumber") or props.get("osVersion")),
            "developerMode": (props.get("developerModeStatus") or "") == "enabled",
            "state": state}


#: The previous kern.cp_time reading; CPU percent is the delta between polls.
_CPU_SAMPLE: dict = {"ticks": None}
_CPU_WARN, _CPU_CRITICAL = 85.0, 95.0
_MEM_WARN, _MEM_CRITICAL = 85.0, 92.0


def _memory_pressure(run) -> dict:
    """Total vs used RAM on macOS: vm_stat's free + inactive + speculative pages count as available."""
    code, output = run(["sysctl", "-n", "hw.memsize"], timeout=5)
    if code != 0:
        return {"totalBytes": None, "usedBytes": None, "percent": None}
    try:
        total = int(output.strip())
    except ValueError:
        return {"totalBytes": None, "usedBytes": None, "percent": None}
    code, output = run(["vm_stat"], timeout=5)
    if code != 0:
        return {"totalBytes": total, "usedBytes": None, "percent": None}
    page_size = 4096
    available = 0
    for line in output.splitlines():
        if "page size of" in line:
            digits = "".join(ch for ch in line if ch.isdigit())
            try:
                page_size = int(digits)
            except ValueError:
                pass
            continue
        for label in ("Pages free", "Pages inactive", "Pages speculative"):
            if line.startswith(label):
                digits = "".join(ch for ch in line.rsplit(":", 1)[-1] if ch.isdigit())
                try:
                    available += int(digits) * page_size
                except ValueError:
                    pass
    used = max(total - available, 0)
    return {"totalBytes": total, "usedBytes": used,
            "percent": round(used * 100.0 / total, 1) if total else None}


def _cpu_ticks() -> list[int] | None:
    """Host CPU ticks (user, system, idle, nice) via mach host_statistics64 — no subprocess.

    kern.cp_time is gone on current macOS; this is the same source Activity
    Monitor uses. Returns None honestly when the mach call fails.
    """
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        libc.mach_host_self.restype = ctypes.c_uint
        libc.mach_host_self.argtypes = []
        libc.host_statistics64.restype = ctypes.c_int
        libc.host_statistics64.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint)]
        libc.mach_port_deallocate.argtypes = [ctypes.c_uint, ctypes.c_uint]
        host = libc.mach_host_self()
        ticks = (ctypes.c_int * 4)()
        count = ctypes.c_uint(4)
        kr = libc.host_statistics64(host, 3, ticks, ctypes.byref(count))  # HOST_CPU_LOAD_INFO
        libc.mach_port_deallocate(host, host)
        if kr != 0:
            return None
        return [ticks[i] for i in range(4)]
    except (OSError, ValueError):
        return None


def _cpu_percent(run=None) -> float | None:
    """CPU busy-percent as the tick delta since the previous call (None on the first poll)."""
    ticks = _cpu_ticks()
    if not ticks or len(ticks) < 4:
        return None
    previous = _CPU_SAMPLE["ticks"]
    _CPU_SAMPLE["ticks"] = ticks
    if not previous:
        return None
    busy = [b - p for b, p in zip(ticks[:3], previous[:3])]
    idle = ticks[3] - previous[3]
    total = sum(busy) + idle
    if total <= 0:
        return None
    return round(min(sum(busy) * 100.0 / total, 100.0), 1)


def _simulator_process(run) -> dict:
    """CPU and RSS of Simulator.app and its helpers; the honest proxy for what the booted device costs."""
    code, output = run(["ps", "-axo", "comm=,%cpu=,rss="], timeout=5)
    if code != 0:
        return {"running": False, "cpuPercent": None, "rssBytes": None}
    cpu, rss = 0.0, 0
    for line in output.splitlines():
        parts = line.strip().rsplit(None, 2)
        if len(parts) != 3 or "Simulator.app" not in parts[0]:
            continue
        try:
            cpu += float(parts[1])
            rss += int(parts[2]) * 1024
        except ValueError:
            continue
    return {"running": cpu > 0 or rss > 0, "cpuPercent": round(cpu, 1), "rssBytes": rss or None}


def ios_resources() -> dict:
    """Host CPU/RAM pressure plus what Simulator.app costs, for the drawer's watchdog.

    CPU percent is None on the first poll (it needs a delta); memory is a
    vm_stat approximation of Activity Monitor's "used".
    """
    if host_os() != "macos":
        return {"available": False, "reason": "Resource monitoring runs on macOS only", "cpu": None, "memory": None, "simulator": None}
    memory = _memory_pressure(_capture)
    cpu = _cpu_percent(_capture)
    simulator = _simulator_process(_capture)
    return {"available": True, "reason": None,
            "cpu": {"percent": cpu, "warn": _CPU_WARN, "critical": _CPU_CRITICAL},
            "memory": {**memory, "warn": _MEM_WARN, "critical": _MEM_CRITICAL},
            "simulator": simulator}


# ── macOS app mirror ─────────────────────────────────────────────────────────
# Read-only host inspection for the app mirror panel: the window list comes from CoreGraphics
# through ctypes (the osascript ObjC bridge segfaults on current macOS), a window's pixels come
# from `screencapture -l` and its accessibility tree from System Events. Control mode posts real
# clicks through the same macos-app.sh click action the previewed flow uses.

def _load_macos_config() -> dict:
    """One config file with a clear precedence (QcU parity): environment > ios-lab/mac/mac-lab.json
    > defaults. Missing or malformed files fall back to the defaults; values are clamped so a
    typo cannot turn the safety timers off."""
    limits = {"controlTimeout": (600, 30, 3600, "OSLAB_MAC_CONTROL_TIMEOUT"),
              "auditMax": (500, 50, 5000, "OSLAB_MAC_AUDIT_MAX"),
              "streamCap": (600, 30, 3600, "OSLAB_MAC_STREAM_CAP")}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ios-lab", "mac", "mac-lab.json")
    try:
        with open(path, encoding="utf-8") as f:
            stored = json.load(f)
        if not isinstance(stored, dict):
            stored = {}
    except (OSError, ValueError):
        stored = {}
    config = {}
    for key, (default, low, high, env) in limits.items():
        value = default
        for candidate in (os.environ.get(env), stored.get(key)):
            try:
                number = int(candidate)
            except (TypeError, ValueError):
                continue
            value = min(high, max(low, number))
            break
        config[key] = value
    return config


_MACOS_CONFIG = _load_macos_config()

_MACOS_CONTROL = {"armed": False, "armedAt": 0.0, "owner": None, "ownerAt": 0.0}
_MACOS_CONTROL_LOCK = threading.Lock()
_MACOS_CONTROL_TIMEOUT = _MACOS_CONFIG["controlTimeout"]  # control mode disarms itself after idle time (default ten minutes)
_MACOS_STREAM_EPOCH = 0  # bumped by the panic stop; every stream loop checks it and exits

# MIR-11 agent-safety layer: actions that can submit, send or overwrite get one more gate
# than plain clicks — they need an explicit confirm flag even while control is armed. The
# human's arm is the session consent; this flag is the actor's explicit acknowledgement,
# and both land in the audit log.
_MACOS_CONFIRM_KINDS = {"enter", "return", "paste"}


class _MacosWindows:
    """Minimal ctypes bindings for the CG window list. Listing needs no permission; window
    titles are only populated when the console holds Screen Recording."""

    UTF8 = 0x08000100

    def __init__(self) -> None:
        self.cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cg, cf = self.cg, self.cf
        cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_int32]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.POINTER(ctypes.c_int64)]

        class _CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        class _CGSize(ctypes.Structure):
            _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

        class _CGRect(ctypes.Structure):
            _fields_ = [("origin", _CGPoint), ("size", _CGSize)]

        self._rect = _CGRect
        cg.CGGetActiveDisplayList.restype = ctypes.c_int32
        cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                              ctypes.POINTER(ctypes.c_uint32)]
        cg.CGDisplayBounds.restype = _CGRect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
        cg.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
        for name in ("CGDisplayModeGetWidth", "CGDisplayModeGetHeight",
                     "CGDisplayModeGetPixelWidth", "CGDisplayModeGetPixelHeight"):
            fn = getattr(cg, name)
            fn.restype = ctypes.c_size_t
            fn.argtypes = [ctypes.c_void_p]
        cf.CFGetTypeID.restype = ctypes.c_ulong
        cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
        cf.CFStringGetTypeID.restype = ctypes.c_ulong
        cf.CFNumberGetTypeID.restype = ctypes.c_ulong

    def _cfstr(self, text: str) -> int:
        return self.cf.CFStringCreateWithCString(None, text.encode(), self.UTF8)

    def _string(self, ref: int) -> str:
        buf = ctypes.create_string_buffer(1024)
        return buf.value.decode() if ref and self.cf.CFStringGetCString(ref, buf, 1024, self.UTF8) else ""

    def _number(self, ref: int) -> int:
        value = ctypes.c_int64()
        return value.value if ref and self.cf.CFNumberGetValue(ref, 4, ctypes.byref(value)) else 0  # 4 = SInt64

    def value(self, dictionary: int, key: str):
        ref = self.cf.CFDictionaryGetValue(dictionary, self._cfstr(key))
        if not ref:
            return None
        return self._string(ref) if self.cf.CFGetTypeID(ref) == self.cf.CFStringGetTypeID() else self._number(ref)

    def screens(self) -> list[dict]:
        """Displays with origin, size and backing scale (MIR-03): CGWindowBounds are points and
        pixels are 2x on Retina, so remote coordinates can be reasoned about per display. The
        scale is the current display mode's pixel-to-point ratio (CGWindowCopyScreenInfo is not
        exported on current macOS)."""
        count = ctypes.c_uint32()
        ids = (ctypes.c_uint32 * 16)()
        if self.cg.CGGetActiveDisplayList(16, ids, ctypes.byref(count)) != 0:
            return []
        out = []
        for i in range(count.value):
            did = ids[i]
            rect = self.cg.CGDisplayBounds(did)
            mode = self.cg.CGDisplayCopyDisplayMode(did)
            scale = 1.0
            if mode:
                points, pixels = self.cg.CGDisplayModeGetWidth(mode), self.cg.CGDisplayModeGetPixelWidth(mode)
                scale = round(pixels / points, 2) if points else 1.0
            out.append({"x": int(rect.origin.x), "y": int(rect.origin.y),
                        "width": int(rect.size.width), "height": int(rect.size.height), "scale": scale})
        return out

    def windows(self) -> list[dict]:
        screens = self.screens()
        arr = self.cg.CGWindowListCopyWindowInfo(1, 0)  # on-screen only
        out = []
        for i in range(self.cf.CFArrayGetCount(arr)):
            d = self.cf.CFArrayGetValueAtIndex(arr, i)
            if self.value(d, "kCGWindowLayer") != 0:
                continue
            owner = self.value(d, "kCGWindowOwnerName") or ""
            width = self.value(self.cf.CFDictionaryGetValue(d, self._cfstr("kCGWindowBounds")), "Width")
            height = self.value(self.cf.CFDictionaryGetValue(d, self._cfstr("kCGWindowBounds")), "Height")
            if not owner or not width or not height or width < 40 or height < 40:
                continue  # desktop-stage and helper windows are not app windows
            x = self.value(self.cf.CFDictionaryGetValue(d, self._cfstr("kCGWindowBounds")), "X")
            y = self.value(self.cf.CFDictionaryGetValue(d, self._cfstr("kCGWindowBounds")), "Y")
            scale = next((s["scale"] for s in screens
                          if s["width"] and s["height"]
                          and s["x"] <= x < s["x"] + s["width"] and s["y"] <= y < s["y"] + s["height"]), 1.0)
            out.append({"windowId": self.value(d, "kCGWindowNumber"), "pid": self.value(d, "kCGWindowOwnerPID"),
                        "app": owner, "title": self.value(d, "kCGWindowName") or "",
                        "x": x, "y": y, "width": width, "height": height, "scale": scale})
        return out


_MACOS_CG: _MacosWindows | None = None


def _macos_cg() -> _MacosWindows:
    global _MACOS_CG
    if _MACOS_CG is None:
        _MACOS_CG = _MacosWindows()
    return _MACOS_CG


def macos_windows() -> dict:
    """Visible ordinary windows for the app mirror panel. Listing needs no permission; the
    screenRecording flag is a hint: titles only appear when the console holds Screen Recording."""
    if host_os() != "macos":
        return {"available": False, "reason": "The app mirror needs a Mac.", "screenRecording": False, "windows": []}
    try:
        windows = _macos_cg().windows()
    except OSError as e:
        return {"available": False, "reason": f"CoreGraphics is unavailable: {e}", "screenRecording": False, "windows": []}
    return {"available": True, "reason": None, "screenRecording": any(w["title"] for w in windows), "windows": windows}


def macos_window_screenshot(window_id: int) -> bytes:
    """A PNG of one on-screen window. Raises PlanError when the id is stale or Screen Recording is missing."""
    if host_os() != "macos":
        raise PlanError("The app mirror needs a Mac")
    try:
        window_id = int(window_id)
    except (TypeError, ValueError):
        raise PlanError("Invalid window id") from None
    fd, path = tempfile.mkstemp(suffix=".png")
    try:
        os.close(fd)
        code, output = _capture(["screencapture", "-x", "-o", f"-l{window_id}", path], timeout=15)
        with open(path, "rb") as f:
            png = f.read()
        if code != 0 or not png.startswith(b"\x89PNG"):
            raise PlanError("Could not capture that window. If this keeps failing, grant Screen Recording "
                            "to the console (System Settings > Privacy & Security) and retry.")
        return png
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# MIR-02: the last read element tree per window powers the diff overlay. A revision token is
# the digest of the tree, so the same tree keeps the same token and a matching token means the
# client is asking for a diff against exactly this snapshot.
_MACOS_ELEMENTS: dict[int, dict] = {}
_MACOS_ELEMENTS_LOCK = threading.Lock()
_ELEMENT_MATCH_POINT = 24  # a same-role, same-label element within this distance is unchanged


def _element_revision(elements: list[dict]) -> str:
    digest = hashlib.sha256()
    for element in elements:
        digest.update(json.dumps(element, sort_keys=True).encode())
    return digest.hexdigest()[:16]


def _diff_elements(previous: list[dict], current: list[dict]) -> dict:
    """Added / removed / changed entries between two element trees, matched by role+label and
    geometry proximity. Every list is bounded like the tree itself (150 entries)."""
    unused = list(previous)
    added, changed = [], []
    for element in current:
        same = [p for p in unused if p["role"] == element["role"] and p["label"] == element["label"]]
        near = min(same, key=lambda p: abs(p["x"] - element["x"]) + abs(p["y"] - element["y"])) if same else None
        if near is not None and abs(near["x"] - element["x"]) <= _ELEMENT_MATCH_POINT \
                and abs(near["y"] - element["y"]) <= _ELEMENT_MATCH_POINT \
                and abs(near["w"] - element["w"]) <= 8 and abs(near["h"] - element["h"]) <= 8:
            unused.remove(near)
        elif near is not None:
            unused.remove(near)
            changed.append({**element, "movedFrom": {"x": near["x"], "y": near["y"]}})
        else:
            added.append(element)
    return {"added": added[:150], "changed": changed[:150], "removed": unused[:150]}


# ── Native AX helper (MIR-09) ────────────────────────────────────────────────
# The compiled Swift reader in ios-lab/mac/build/ax-helper: full attribute trees in
# milliseconds with values, focus, enabled state and advertised actions, elements
# addressable by a child-index path whose identity hash fails closed. Everything
# falls back to the osascript path when the helper is absent.

_AX_ATTRS = ("AXValue", "AXTitle", "AXDescription", "AXRole", "AXPlaceholderValue", "AXFocused")
_AX_PATH = re.compile(r"^[0-9.]{0,80}$")
_AX_INTERACTIVE = {"Button", "CheckBox", "RadioButton", "PopUpButton", "MenuButton", "TextField",
                   "TextArea", "ComboBox", "SearchField", "Slider", "TabGroup", "Menu", "MenuItem",
                   "MenuBarItem", "Link", "Switch", "SegmentedControl", "TableRow", "OutlineRow"}
_AX_ELEMENT_CAP = 400


def _ax_helper(root: str) -> str | None:
    """The native helper binary. OSLAB_AX_HELPER points at a stand-in (the fake helper used by
    tests and Linux CI) so the act/verify paths run without a Mac."""
    override = os.environ.get("OSLAB_AX_HELPER")
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    path = os.path.join(root, "ios-lab", "mac", "build", "ax-helper")
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


def _ax_call(root: str, args: list[str], timeout: float = 20) -> dict:
    """One ax-helper invocation; its JSON error payload becomes a coded PlanError."""
    helper = _ax_helper(root)
    if not helper:
        raise PlanError("The native AX helper is not built; run Build AX helper in the macOS Lab page "
                        "(or reads fall back to osascript where supported)", code="HELPER_MISSING", retry="retry")
    code, output = _capture([helper] + args, timeout=timeout)
    payload: dict = {}
    if output.strip().startswith("{"):
        try:
            payload = json.loads(output)
        except ValueError:
            payload = {}
    if code != 0 or payload.get("error"):
        raise PlanError(payload.get("error") or output.strip()[:200] or "the AX helper failed",
                        code=payload.get("code") or "INTERNAL", retry="reobserve")
    return payload


def _ax_window_index(root: str, window: dict) -> int:
    """The AX window matching the CG window record, by rect proximity (no private APIs)."""
    payload = _ax_call(root, ["windows", "--pid", str(window["pid"])], timeout=15)
    best, best_distance = None, None
    for entry in payload.get("windows", []):
        rect = entry.get("rect") or {}
        distance = (abs(rect.get("x", 0) - window["x"]) + abs(rect.get("y", 0) - window["y"])
                    + abs(rect.get("w", 0) - window["width"]) + abs(rect.get("h", 0) - window["height"]))
        if best_distance is None or distance < best_distance:
            best, best_distance = entry.get("index"), distance
    if best is None:
        raise PlanError("That app exposes no accessibility windows; it may have quit",
                        code="APP_QUIT", retry="reobserve")
    return int(best)


def _ax_priority(element: dict) -> int:
    """0 = interactive or advertised actions or focused; 1 = carries text; 2 = decoration."""
    if element.get("focused") or element.get("actions") or element["role"] in _AX_INTERACTIVE:
        return 0
    return 1 if (element.get("label") or element.get("value")) else 2


def _flatten_ax(node: dict, out: list, window: dict) -> None:
    role = (node.get("role") or "").replace("AX", "")
    rect = node.get("rect") or {}
    try:
        x = int(rect.get("x", 0)) - window["x"]
        y = int(rect.get("y", 0)) - window["y"]
        w, h = int(rect.get("w", 0)), int(rect.get("h", 0))
    except (TypeError, ValueError):
        return
    if w <= 0 or h <= 0 or x >= window["width"] or y >= window["height"] or x + w <= 0 or y + h <= 0:
        return  # invisible: same rules the osascript path applies
    out.append((_ax_priority({
        "role": role, "actions": node.get("actions") or [], "focused": bool(node.get("focused")),
        "label": node.get("label") or node.get("title"), "value": node.get("value"),
    }), {
        "role": role,
        "label": (node.get("label") or node.get("title") or "")[:120],
        "value": (node.get("value") or "")[:200] or None,
        "placeholder": node.get("placeholder") or None,
        "enabled": node.get("enabled", True),
        "focused": bool(node.get("focused")),
        "actions": node.get("actions") or [],
        "path": node.get("path") or "",
        "identity": node.get("identity") or "",
        "x": x, "y": y, "w": w, "h": h,
    }))
    for child in node.get("children") or []:
        _flatten_ax(child, out, window)


def _ax_elements(root: str, window: dict) -> dict:
    """The helper tree of one pinned window, window-relative, priority-trimmed (MIR-08)."""
    index = _ax_window_index(root, window)
    payload = _ax_call(root, ["tree", "--pid", str(window["pid"]), "--window", str(index),
                              "--depth", "14"], timeout=30)
    flat: list = []
    _flatten_ax(payload.get("tree") or {}, flat, window)
    flat.sort(key=lambda pair: (pair[0], -(pair[1]["w"] * pair[1]["h"])))
    trimmed = len(flat) > _AX_ELEMENT_CAP
    elements = [entry for _, entry in flat[:_AX_ELEMENT_CAP]]
    focused = next((e for e in elements if e["focused"]), None)
    return {"engine": "ax-helper", "trimmed": trimmed, "elements": elements,
            "focusedPath": focused["path"] if focused else None}


def _osascript_elements(root: str, window: dict) -> dict:
    """The original System Events read; the fallback when the helper is not built."""
    # A property read is the honest probe: counting windows works without permission, reads do not.
    code, output = _capture(["osascript", "-e",
                             f'tell application "System Events" to get position of window 1 of '
                             f'(first application process whose unix id is {int(window["pid"])})'], timeout=10)
    if code != 0:
        raise PlanError("Reading UI elements needs Accessibility permission for the console "
                        "(System Settings > Privacy & Security > Accessibility), and the app needs a visible window.",
                        code="PERMISSION_DENIED", retry="retry")
    script = os.path.join(root, "ios-lab", "mac", "ax-elements.applescript")
    if not os.path.isfile(script):
        raise PlanError("ax-elements.applescript is missing from ios-lab/mac", code="INTERNAL")
    code, output = _capture(["osascript", script, str(window["pid"]), str(window["x"]), str(window["y"])], timeout=60)
    if code != 0:
        raise PlanError("Could not read UI elements: " + output.strip()[:200], code="INTERNAL", retry="reobserve")
    elements = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        role, label, x, y, w, h = parts[0], "\t".join(parts[1:-4]), parts[-4], parts[-3], parts[-2], parts[-1]
        try:
            element = {"role": role.replace("AX", ""), "label": label[:120],
                       "x": int(float(x)) - window["x"], "y": int(float(y)) - window["y"],
                       "w": int(float(w)), "h": int(float(h))}
        except ValueError:
            continue
        if element["w"] <= 0 or element["h"] <= 0:
            continue
        if element["x"] >= window["width"] or element["y"] >= window["height"] \
                or element["x"] + element["w"] <= 0 or element["y"] + element["h"] <= 0:
            continue
        elements.append(element)
    return {"engine": "osascript", "trimmed": len(elements) >= 150, "elements": elements, "focusedPath": None}


def macos_window_elements(root: str, window_id: int, revision: str | None = None) -> dict:
    """The accessibility tree of one window as window-relative hotspots: the native helper
    (values, focus, actions, paths) with the osascript path as the honest fallback."""
    if host_os() != "macos":
        raise PlanError("The app mirror needs a Mac")
    try:
        window_id = int(window_id)
    except (TypeError, ValueError):
        raise PlanError("Invalid window id") from None
    window = next((w for w in macos_windows()["windows"] if w["windowId"] == window_id), None)
    if window is None:
        raise PlanError("That window is not on screen anymore; refresh the mirror", code="APP_QUIT", retry="reobserve")
    read: dict | None = None
    if _ax_helper(root):
        try:
            read = _ax_elements(root, window)
        except PlanError as e:
            if e.code in ("PERMISSION_DENIED", "APP_QUIT", "TIMEOUT"):
                raise  # the fallback cannot fix a permission or a dead app
            read = None  # helper-specific trouble: fall back to osascript below
    if read is None:
        read = _osascript_elements(root, window)
    elements = read["elements"]
    with _MACOS_ELEMENTS_LOCK:
        token = _element_revision(elements)
        cached = _MACOS_ELEMENTS.get(window_id)
        result = {"windowId": window_id, "app": window["app"], "revision": token,
                  "engine": read["engine"], "trimmed": read["trimmed"],
                  "focusedPath": read["focusedPath"],
                  "bounds": {"x": window["x"], "y": window["y"],
                             "width": window["width"], "height": window["height"]},
                  "elements": elements,
                  "diff": _diff_elements(cached["elements"], elements)
                  if revision and cached and cached["revision"] == revision and revision != token
                  else {"added": [], "changed": [], "removed": []}}
        _MACOS_ELEMENTS[window_id] = {"revision": token, "elements": elements, "at": time.time()}
        if len(_MACOS_ELEMENTS) > 16:  # keep the cache bounded to the windows seen recently
            oldest = min(_MACOS_ELEMENTS, key=lambda k: _MACOS_ELEMENTS[k]["at"])
            _MACOS_ELEMENTS.pop(oldest, None)
    return result


def _ax_window_arg(root: str, window_id) -> str:
    """The AX window index for a CG window id, or "-" when the caller has none: tree paths
    are window-relative, so element actions must resolve against the same pinned window."""
    if window_id in (None, ""):
        return "-"
    try:
        window_id = int(window_id)
    except (TypeError, ValueError):
        raise PlanError("windowId must be an integer", code="INVALID_ARGS") from None
    window = next((w for w in macos_windows()["windows"] if w["windowId"] == window_id), None)
    if window is None:
        raise PlanError("That window is not on screen anymore; refresh the mirror",
                        code="APP_QUIT", retry="reobserve")
    return str(_ax_window_index(root, window))


def macos_ax_read(root: str, data: dict) -> dict:
    """One attribute of one element by path (read-only; no armed mode needed)."""
    pid = _ax_pid(data)
    path = _ax_path(data)
    attr = data.get("attr") or "AXValue"
    if attr not in _AX_ATTRS:
        raise PlanError(f"attr must be one of: {', '.join(_AX_ATTRS)}", code="INVALID_ARGS")
    args = ["read", "--pid", str(pid), "--path", path, "--identity", _ax_identity(data), "--attr", attr]
    window_arg = _ax_window_arg(root, data.get("windowId"))
    if window_arg != "-":
        args += ["--window", window_arg]
    payload = _ax_call(root, args, timeout=15)
    return {"pid": pid, "path": path, "attr": attr, "value": payload.get("value")}


def macos_ax_set(root: str, data: dict) -> dict:
    """Set one element's value through the AX helper (MIR-07). Armed control mode; audited."""
    _macos_control_gate(root, data)
    pid = _ax_pid(data)
    path = _ax_path(data)
    value = data.get("value")
    if not isinstance(value, str) or not value or len(value) > 2000 \
            or not all(c.isprintable() and c != "\n" and c != "\r" for c in value):
        raise PlanError("value must be 1-2000 printable characters (no Return)", code="INVALID_ARGS",
                        retry="never")
    args = ["set", "--pid", str(pid), "--path", path, "--identity", _ax_identity(data), "--value", value]
    window_arg = _ax_window_arg(root, data.get("windowId"))
    if window_arg != "-":
        args += ["--window", window_arg]
    payload = _ax_call(root, args, timeout=20)
    _macos_audit(root, "ax-set", window=_macos_window_for_pid(pid),
                 detail={"path": path, "textLength": len(value), "ok": True}, thumbnail=True)
    return {"ok": True, "pid": pid, "path": path, "actionSent": True, "verify": payload.get("verify")}


def macos_ax_perform(root: str, data: dict) -> dict:
    """One advertised AX action on one element (MIR-07). Armed control mode; audited."""
    _macos_control_gate(root, data)
    pid = _ax_pid(data)
    path = _ax_path(data)
    action = data.get("action")
    if not isinstance(action, str) or not re.match(r"^AX[A-Za-z]{2,40}$", action):
        raise PlanError("action must be an advertised AX action name (e.g. AXPress)", code="INVALID_ARGS",
                        retry="never")
    args = ["perform", "--pid", str(pid), "--path", path, "--identity", _ax_identity(data), "--action", action]
    window_arg = _ax_window_arg(root, data.get("windowId"))
    if window_arg != "-":
        args += ["--window", window_arg]
    payload = _ax_call(root, args, timeout=20)
    _macos_audit(root, "ax-perform", window=_macos_window_for_pid(pid),
                 detail={"path": path, "axAction": action, "ok": True}, thumbnail=True)
    return {"ok": True, "pid": pid, "path": path, "action": action, "actionSent": True}


def macos_ax_windows(root: str, data: dict) -> dict:
    """The AX window list of one app: rects, titles, subroles, sheets and alerts flagged (MIR-10)."""
    pid = _ax_pid(data)
    return _ax_call(root, ["windows", "--pid", str(pid)], timeout=15)


def macos_ax_menubar(root: str, data: dict) -> dict:
    """The menu-bar tree of one app (MIR-10): menus and items with enabled state and actions."""
    pid = _ax_pid(data)
    return _ax_call(root, ["menubar", "--pid", str(pid)], timeout=15)


def macos_ax_focused(root: str, data: dict) -> dict:
    """The focused element of one app with its attributes (MIR-08)."""
    pid = _ax_pid(data)
    return _ax_call(root, ["focused", "--pid", str(pid)], timeout=15)


def _ax_pid(data: dict) -> int:
    try:
        pid = int(data.get("pid"))
    except (TypeError, ValueError):
        raise PlanError("pid must be an integer", code="INVALID_ARGS") from None
    if not 0 <= pid <= 100000:
        raise PlanError("pid is out of range", code="INVALID_ARGS")
    return pid


def _ax_path(data: dict) -> str:
    path = data.get("path")
    if not isinstance(path, str) or not _AX_PATH.match(path):
        raise PlanError("path must be a child-index chain like 0.3.1", code="INVALID_ARGS")
    return path


def _ax_identity(data: dict) -> str:
    identity = data.get("identity") or ""
    if not isinstance(identity, str) or not re.match(r"^[0-9a-f]{0,16}$", identity):
        raise PlanError("identity must be the hex hash from the tree read", code="INVALID_ARGS")
    return identity


def macos_control_state() -> dict:
    """Whether armed control mode is active; it disarms itself after ten idle minutes."""
    with _MACOS_CONTROL_LOCK:
        armed = _MACOS_CONTROL["armed"] and time.time() - _MACOS_CONTROL["armedAt"] < _MACOS_CONTROL_TIMEOUT
        if not armed:
            _MACOS_CONTROL["armed"] = False
            _MACOS_CONTROL["owner"] = None
        return {"armed": armed,
                "owner": _MACOS_CONTROL["owner"] if armed else None,
                "expiresInSec": int(_MACOS_CONTROL_TIMEOUT - (time.time() - _MACOS_CONTROL["armedAt"])) if armed else 0}


def macos_screen_locked() -> bool | None:
    """Whether the screen is locked (MIR-11): CGSessionCopyCurrentDictionary carries the
    CGSSessionScreenIsLocked key. None when macOS does not tell us."""
    if host_os() != "macos":
        return None
    try:
        cg = _macos_cg()
        cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        cg.CFBooleanGetValue.restype = ctypes.c_bool
        cg.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        session = cg.CGSessionCopyCurrentDictionary()
        if not session:
            return None
        ref = cg.cf.CFDictionaryGetValue(session, cg._cfstr("CGSSessionScreenIsLocked"))
        if not ref:
            return None
        if cg.cf.CFGetTypeID(ref) == cg.cf.CFBooleanGetTypeID():
            return bool(cg.CFBooleanGetValue(ref))
        return bool(cg._number(ref))
    except (OSError, AttributeError):
        return None


def _macos_allowlist(root: str, app: str | None = None, bundle: str | None = None) -> None:
    """The agent app allowlist (MIR-11): ios-lab/mac/agent-apps.json lists app names or bundle
    ids that input actions may drive; missing or empty means every mirror-visible app."""
    path = os.path.join(root, "ios-lab", "mac", "agent-apps.json")
    try:
        with open(path, encoding="utf-8") as f:
            allowed = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(allowed, list) or not allowed:
        return
    names = {str(entry).strip().lower() for entry in allowed if isinstance(entry, str)}
    if bundle and bundle.lower() in names:
        return
    app_name = (app or "").lower()
    if app_name and app_name in names:
        return
    resolved = None
    if app_name and '"' not in app_name:
        code, output = _capture(["osascript", "-e", f'id of app "{app_name.title()}"'], timeout=10)
        if code == 0:
            resolved = output.strip().lower()
    if resolved and resolved in names:
        return
    raise PlanError(f"{app or bundle or 'That app'} is not on this lab's agent allowlist (ios-lab/mac/agent-apps.json)",
                    code="APP_NOT_ALLOWED", retry="never")


def _macos_control_gate(root: str, data: dict, *, app: str | None = None,
                        submit_kind: str | None = None) -> None:
    """Every armed input passes this gate (MIR-11): armed with a live timer, one owner,
    an unlocked screen, an allowlisted app, and — for submit-class kinds — an explicit
    confirm flag even while armed."""
    with _MACOS_CONTROL_LOCK:
        armed = _MACOS_CONTROL["armed"] and time.time() - _MACOS_CONTROL["armedAt"] < _MACOS_CONTROL_TIMEOUT
        owner = _MACOS_CONTROL["owner"] if armed else None
    if not armed:
        raise PlanError("Control mode is not armed; arm the app mirror first", code="NOT_ARMED", retry="retry")
    requested = data.get("owner")
    if owner and requested and requested != owner:
        raise PlanError(f"Another client (armed {int(time.time() - _MACOS_CONTROL['armedAt'])}s ago) holds control; "
                        "disarm it there or stop the session first", code="INPUT_BUSY", retry="never")
    locked = macos_screen_locked()
    if locked:
        raise PlanError("The screen is locked; unlock this Mac to run input actions",
                        code="SCREEN_LOCKED", retry="retry")
    _macos_allowlist(root, app)
    if submit_kind and submit_kind in _MACOS_CONFIRM_KINDS and data.get("confirm") is not True:
        raise PlanError(f"{submit_kind} can submit or overwrite: send confirm:true from the explicit "
                        "dialog, even while control is armed", code="CONFIRM_REQUIRED", retry="never")


def macos_control_arm(root: str, armed: bool, owner: str | None = None) -> dict:
    if not isinstance(armed, bool):
        raise PlanError("armed must be true or false", code="INVALID_ARGS")
    with _MACOS_CONTROL_LOCK:
        if armed and _MACOS_CONTROL["armed"] and _MACOS_CONTROL["owner"] \
                and owner and owner != _MACOS_CONTROL["owner"]:
            held = int(time.time() - _MACOS_CONTROL["armedAt"])
            raise PlanError(f"{_MACOS_CONTROL['owner']} already holds armed control (armed {held}s ago); "
                            "it must disarm or stop the session before another client can arm "
                            "(single-owner input, MIR-11)", code="ARMED_BY_OTHER", retry="never")
        _MACOS_CONTROL["armed"] = armed
        _MACOS_CONTROL["armedAt"] = time.time()
        _MACOS_CONTROL["owner"] = owner if armed else None
    _macos_audit(root, "arm" if armed else "disarm", detail={"owner": owner} if owner else None)
    return macos_control_state()


def macos_panic_stop(root: str) -> dict:
    """The panic stop (MIR-11): disarm, close every deep-inspect session, end every stream,
    record one audit row. Idempotent and always safe to call."""
    closed = []
    with _MACOS_CONTROL_LOCK:
        _MACOS_CONTROL["armed"] = False
        _MACOS_CONTROL["owner"] = None
    with _MACOS_SESSIONS_LOCK:
        sessions = list(_MACOS_SESSIONS.items())
        _MACOS_SESSIONS.clear()
    global _MACOS_STREAM_EPOCH
    with _MACOS_CONTROL_LOCK:
        _MACOS_STREAM_EPOCH += 1
        epoch = _MACOS_STREAM_EPOCH
    for bundle, entry in sessions:
        try:
            _appium_request(_macos_appium_base(root), "DELETE", f"/session/{entry['sessionId']}", timeout=10)
            closed.append(bundle)
        except PlanError:
            closed.append(bundle)  # Appium unreachable — the session record is dropped regardless
    _macos_audit(root, "panic-stop", detail={"sessionsClosed": closed, "epoch": epoch})
    return {"ok": True, "disarmed": True, "sessionsClosed": closed, "streamEpoch": epoch}


def macos_control_click(root: str, data: dict) -> dict:
    """One immediate click while control mode is armed: bring the owning app forward, then post
    the event through macos-app.sh click — the same script the previewed flow runs."""
    values = {}
    for key in ("pid", "x", "y"):
        try:
            value = int(data.get(key))
        except (TypeError, ValueError):
            raise PlanError(f"{key} must be an integer", code="INVALID_ARGS") from None
        if not 0 <= value <= 100000:
            raise PlanError(f"{key} is out of range", code="INVALID_ARGS")
        values[key] = value
    window = _macos_window_for_pid(values["pid"])
    _macos_control_gate(root, data, app=window.get("app") if window else None)
    script = _scoped(root, "ios-lab", "mac", "macos-app.sh")
    code, output = _capture(["bash", script, "click", str(values["pid"]), str(values["x"]), str(values["y"])], timeout=30)
    with _MACOS_CONTROL_LOCK:
        _MACOS_CONTROL["armedAt"] = time.time()  # each click slides the disarm timer
    _macos_audit(root, "click", window=window,
                 detail={"x": values["x"], "y": values["y"], "ok": code == 0}, thumbnail=True)
    if code != 0:
        raise PlanError(output.strip()[:200] or "The click did not run", code="INTERNAL", retry="retry")
    return {"ok": True, "actionSent": True, **values}


# ── macOS app mirror roadmap (MIR-01…06) ─────────────────────────────────────
# The app-mirror follow-ups: an input family beyond the single click (MIR-01), a diff overlay
# for the accessibility tree (MIR-02), per-display scale factors (MIR-03), an MJPEG stream
# (MIR-04), mac2 deep-inspect sessions with stable element ids (MIR-05) and a local audit log
# of everything the console does on this Mac (MIR-06). The guardrails do not move: read-only
# endpoints by default, preview → confirm, armed control mode that disarms itself, localhost
# POSTs only.

# MIR-06: every host action the console performs for the app mirror lands in a bounded
# in-memory ring and an append-only JSONL file under ios-lab/artifacts/. Rows carry a small
# frame thumbnail at action time; nothing ever leaves this Mac.
_MACOS_AUDIT_MAX = _MACOS_CONFIG["auditMax"]
_MACOS_AUDIT_SEQ = 0  # monotonically increasing row number, for the live event feed
_MACOS_AUDIT: list[dict] = []
_MACOS_AUDIT_LOCK = threading.Lock()


def _macos_window_for_pid(pid: int) -> dict | None:
    """The largest visible window of one pid, for audit rows; None when it is gone."""
    candidates = [w for w in macos_windows()["windows"] if w.get("pid") == pid]
    return max(candidates, key=lambda w: w["width"] * w["height"]) if candidates else None


def _macos_audit_thumbnail(window_id: int) -> str | None:
    """A small base64 JPEG of the window at action time; None when capture or resize fails."""
    fd, png = tempfile.mkstemp(suffix=".png")
    fd2, small = tempfile.mkstemp(suffix=".jpg")
    try:
        os.close(fd)
        os.close(fd2)
        code, _ = _capture(["screencapture", "-x", "-o", f"-l{window_id}", png], timeout=15)
        if code == 0:
            _capture(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "50", "-Z", "480", png,
                      "--out", small], timeout=15)
            with open(small, "rb") as f:
                data = f.read()
            if data.startswith(b"\xff\xd8"):
                return base64.b64encode(data).decode()
    except OSError:
        return None
    finally:
        for path in (png, small):
            try:
                os.unlink(path)
            except OSError:
                pass
    return None


def _macos_audit(root: str | None, kind: str, *, window: dict | None = None,
                 detail: dict | None = None, thumbnail: bool = False) -> None:
    """Record one audit row (MIR-06). Never raises: auditing must not break the action."""
    global _MACOS_AUDIT_SEQ
    row: dict = {"time": time.time(), "kind": kind}
    if window:
        row.update({"app": window.get("app"), "windowId": window.get("windowId"),
                    "title": (window.get("title") or "")[:120]})
    if detail:
        row.update(detail)
    if thumbnail and window and window.get("windowId"):
        try:
            row["thumbnail"] = _macos_audit_thumbnail(int(window["windowId"]))
        except (OSError, ValueError):
            row["thumbnail"] = None
    with _MACOS_AUDIT_LOCK:
        _MACOS_AUDIT_SEQ += 1
        row["seq"] = _MACOS_AUDIT_SEQ
        _MACOS_AUDIT.append(row)
        del _MACOS_AUDIT[:-_MACOS_AUDIT_MAX]
    if root:
        try:
            folder = os.path.join(root, "ios-lab", "artifacts")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "macos-audit-%s.jsonl" % time.strftime("%Y%m%d")),
                      "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            pass


def macos_audit_rows() -> dict:
    """The last audit rows for the panel; the full download includes every stored row."""
    with _MACOS_AUDIT_LOCK:
        return {"recording": True, "rows": [dict(r, thumbnail=None) for r in _MACOS_AUDIT[-200:]]}


def macos_audit_download() -> bytes:
    """The audit log as one JSON file with embedded thumbnails (panel download button)."""
    with _MACOS_AUDIT_LOCK:
        payload = {"generatedAt": time.time(), "recording": True, "rows": list(_MACOS_AUDIT)}
    return json.dumps(payload).encode()


# ── QcU parity: displays, capabilities, search, permissions, live events ─────
# QcU is the mac-lab engine extracted as a standalone package; these are the engine-level
# pieces it has that the console lacked. All read-only except the consent request.

_MACOS_PANES = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen-recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
}


def macos_displays() -> dict:
    """Displays as JSON (MIR-03 data): origin, size and backing scale of every active display,
    so a remote client can reason about coordinates without running doctor."""
    if host_os() != "macos":
        return {"available": False, "reason": "The app mirror needs a Mac.", "displays": []}
    try:
        return {"available": True, "reason": None, "displays": _macos_cg().screens()}
    except OSError as e:
        return {"available": False, "reason": f"CoreGraphics is unavailable: {e}", "displays": []}


def macos_search_elements(root: str, window_id: int, query: str) -> dict:
    """Find elements of one window by label, value or placeholder substring (max 50) so an
    agent does not need the whole tree. Reads the same tree as the mirror, so paths and the
    revision are valid for the element actions."""
    if not isinstance(query, str) or not query.strip():
        raise PlanError("query must be a non-empty string", code="INVALID_ARGS")
    needle = query.strip().lower()[:120]
    state = macos_window_elements(root, window_id)
    hits = []
    for element in state["elements"]:
        haystack = " ".join(str(element.get(key) or "") for key in ("label", "title", "value", "placeholder")).lower()
        if needle in haystack:
            hits.append(element)
            if len(hits) >= 50:
                break
    return {"windowId": state["windowId"], "app": state["app"], "revision": state["revision"],
            "engine": state["engine"], "query": query.strip(), "count": len(hits), "hits": hits}


def macos_responsible_app() -> str | None:
    """The app that macOS will ask for permissions on behalf of: the nearest ancestor of this
    process that lives in an .app bundle (Terminal, an IDE, the os-lab app). Doctor names it so
    the user grants Accessibility to the right entry, not to "the helper"."""
    if host_os() != "macos":
        return None
    pid = os.getppid()  # start above this process: a Python.app interpreter is not the grantee
    for _ in range(12):
        code, output = _capture(["ps", "-o", "ppid=,comm=", "-p", str(pid)], timeout=5)
        line = output.strip()
        if code != 0 or not line:
            return None
        parent, _, command = line.partition(" ")
        marker = ".app/Contents/"
        if marker in command:
            return os.path.basename(command.split(marker, 1)[0].rstrip("/")) + ".app"
        try:
            pid = int(parent)
        except ValueError:
            return None
        if pid <= 1:
            return None
    return None


def macos_permissions(root: str) -> dict:
    """Accessibility and Screen Recording state, and which app each grant belongs to."""
    app = macos_responsible_app()
    named = app or "the app that launched the console"
    trusted: bool | None = None
    if host_os() == "macos" and _ax_helper(root):
        code, output = _capture([_ax_helper(root), "trusted"], timeout=10)
        if code == 0 and output.strip().startswith("{"):
            try:
                trusted = bool(json.loads(output).get("trusted"))
            except ValueError:
                trusted = None
    recording = macos_windows().get("screenRecording") if host_os() == "macos" else None
    return {"accessibility": {"granted": trusted,
                              "grantTo": named,
                              "hint": None if trusted else f"Enable {named} in System Settings > Privacy & Security > Accessibility"},
            "screenRecording": {"granted": recording,
                                "grantTo": named,
                                "hint": None if recording else f"Enable {named} in System Settings > Privacy & Security > Screen Recording"},
            "responsibleApp": app}


def macos_request_access(root: str, data: dict) -> dict:
    """Ask macOS for a permission. Accessibility fires the consent dialog through the helper
    when it is built; either pane can also be opened directly. Nothing else changes."""
    if host_os() != "macos":
        raise PlanError("The app mirror needs a Mac", code="UNSUPPORTED_PLATFORM")
    pane = data.get("pane")
    if pane not in _MACOS_PANES:
        raise PlanError("pane must be accessibility or screen-recording", code="INVALID_ARGS")
    prompted: bool | None = None
    if pane == "accessibility" and _ax_helper(root):
        code, output = _capture([_ax_helper(root), "request-access"], timeout=20)
        if code == 0 and output.strip().startswith("{"):
            try:
                prompted = bool(json.loads(output).get("trusted"))
            except ValueError:
                prompted = None
    code, output = _capture(["open", _MACOS_PANES[pane]], timeout=10)
    _macos_audit(root, "permission-request", detail={"pane": pane, "opened": code == 0})
    return {"ok": code == 0, "pane": pane, "trusted": prompted, "openedPane": code == 0,
            "grantTo": macos_responsible_app()}


def macos_capabilities(root: str) -> dict:
    """What this console can do right now (capability handshake): engine, input kinds, keys,
    safety layer and permissions in one read-only answer, so a client adapts instead of probing."""
    on_mac = host_os() == "macos"
    helper = bool(_ax_helper(root))
    return {"platform": host_os(), "available": on_mac,
            "engine": "ax-helper" if helper else ("osascript" if on_mac else None),
            "helperBuilt": helper,
            "canObserve": ["apps", "windows", "displays", "elements", "search", "diff", "screenshot",
                           "stream", "menubar", "focused", "audit", "events"] if on_mac else [],
            "canAct": {"click": on_mac, "input": list(_MACOS_INPUT_KINDS) if on_mac else [],
                       "keys": list(_MACOS_INPUT_KEYS), "setValue": helper, "perform": helper,
                       "deepInspect": on_mac},
            "safety": {"controlTimeoutSec": _MACOS_CONTROL_TIMEOUT, "submitKinds": sorted(_MACOS_CONFIRM_KINDS),
                       "singleOwner": True, "panicStop": True, "auditMax": _MACOS_AUDIT_MAX,
                       "streamCapSec": _MACOS_STREAM_CAP,
                       "allowlist": os.path.isfile(os.path.join(root, "ios-lab", "mac", "agent-apps.json"))},
            "control": macos_control_state()}


def macos_audit_since(seq: int) -> tuple[list[dict], int]:
    """Audit rows newer than seq (thumbnails dropped) and the latest sequence number, for the
    live event feed."""
    with _MACOS_AUDIT_LOCK:
        rows = [dict(r, thumbnail=None) for r in _MACOS_AUDIT if r.get("seq", 0) > seq]
        return rows, _MACOS_AUDIT_SEQ


# The mirror actions that run through the preview → confirm → job pipeline; the armed halves of
# these (and arm/disarm, sessions) audit themselves where they run.
_MACOS_MIRROR_ACTIONS = ("macos-click", "macos-input", "macos-element", "macos-set-value", "macos-perform",
                         "macos-scroll")


def macos_audit_preview(root: str, request: dict, kind: str, token: str | None = None) -> None:
    """Audit rows for the previewed half of the mirror pipeline (MIR-06): a plan preview and a
    confirmed start. The token is recorded only as a short digest, never the signed secret."""
    if not isinstance(request, dict) or request.get("lab") != "macos" \
            or request.get("action") not in _MACOS_MIRROR_ACTIONS:
        return
    detail = {"action": request.get("action"), "x": request.get("clickX"), "y": request.get("clickY"),
              "inputKind": request.get("inputKind"), "key": request.get("inputKey"),
              "textLength": len(request.get("inputText") or "")}
    if isinstance(token, str) and token:
        detail["token"] = hashlib.sha256(token.encode()).hexdigest()[:16]
    _macos_audit(root, kind, detail=detail)


# MIR-01: the input family — double-click, right-click, type and press-key — with the same
# preview → confirm (or armed) pipeline as the single click. Typing never sends Return:
# newlines are refused here and in the script, and Enter is its own explicit key action.
_MACOS_INPUT_KINDS = ("double", "right", "type", "key", "paste", "scroll")
_MACOS_INPUT_KEYS = ("tab", "escape", "delete", "forward-delete", "up", "down", "left", "right",
                     "space", "enter", "return")
_INPUT_TEXT_MAX = 200
_PASTE_TEXT_MAX = 2000


def _validated_input(data: dict) -> dict:
    """pid/x/y plus one kind with its payload, for the armed route and the plan builder alike."""
    values = {"owner": data.get("owner"), "confirm": data.get("confirm") is True}
    for key in ("pid", "x", "y"):
        try:
            value = int(data.get(key))
        except (TypeError, ValueError):
            raise PlanError(f"{key} must be an integer", code="INVALID_ARGS") from None
        if not 0 <= value <= 100000:
            raise PlanError(f"{key} is out of range", code="INVALID_ARGS")
        values[key] = value
    kind = data.get("kind")
    if kind not in _MACOS_INPUT_KINDS:
        raise PlanError("kind must be one of: " + ", ".join(_MACOS_INPUT_KINDS), code="INVALID_ARGS")
    values["kind"] = kind
    if kind in ("type", "paste"):
        text = data.get("text")
        limit = _INPUT_TEXT_MAX if kind == "type" else _PASTE_TEXT_MAX
        # A paste may legitimately carry newlines (multiline paste); typing may never: Return
        # is its own explicit key action, and pastes are gated separately (MIR-11).
        ok_chars = all(32 <= ord(c) <= 126 or (kind == "paste" and c in "\n\t") for c in text or "")
        if not isinstance(text, str) or not text or len(text) > limit or not ok_chars:
            raise PlanError(f"The text must be 1-{limit} printable characters"
                            + ("" if kind == "paste" else "; Return is never sent by a type action"),
                            code="INVALID_ARGS", retry="never")
        values["text"] = text
        values["submitKind"] = "paste" if kind == "paste" else None
    if kind == "key":
        if data.get("key") not in _MACOS_INPUT_KEYS:
            raise PlanError("key must be one of: " + ", ".join(_MACOS_INPUT_KEYS), code="INVALID_ARGS")
        values["key"] = data.get("key")
        values["submitKind"] = "enter" if data.get("key") in ("enter", "return") else None
    if kind == "scroll":
        direction = data.get("direction")
        if direction not in ("up", "down"):
            raise PlanError("direction must be up or down (horizontal scrolling is not supported)",
                            code="INVALID_ARGS")
        try:
            pages = int(data.get("pages"))
        except (TypeError, ValueError):
            raise PlanError("pages must be an integer", code="INVALID_ARGS") from None
        if not 1 <= pages <= 10:
            raise PlanError("pages must be 1-10", code="INVALID_ARGS")
        values["direction"], values["pages"] = direction, pages
        values["text"] = f"{direction}:{pages}"
    return values


def _run_control_script(root: str, args: list[str], values: dict) -> dict:
    """One armed input action through macos-app.sh input: gated, audited with a frame
    thumbnail, and verified after the fact when the helper can read the focused element."""
    window = _macos_window_for_pid(values["pid"])
    _macos_control_gate(root, {"owner": values.get("owner"), "confirm": values.get("confirm")},
                        app=window.get("app") if window else None,
                        submit_kind=values.get("submitKind"))
    script = _scoped(root, "ios-lab", "mac", "macos-app.sh")
    code, output = _capture(["bash", script] + args, timeout=30)
    with _MACOS_CONTROL_LOCK:
        _MACOS_CONTROL["armedAt"] = time.time()
    _macos_audit(root, "input-" + values["kind"], window=window,
                 detail={"x": values["x"], "y": values["y"], "key": values.get("key"),
                         "textLength": len(values.get("text", "")), "ok": code == 0,
                         "confirmed": bool(values.get("confirm"))}, thumbnail=True)
    if code != 0:
        raise PlanError(output.strip()[:200] or "The action did not run", code="INTERNAL", retry="retry")
    verify = _ax_verify_after(root, values["pid"])
    return {"ok": True, "actionSent": True, **values, "verify": verify} if verify else {"ok": True, "actionSent": True, **values}


def _ax_verify_after(root: str, pid: int) -> dict | None:
    """Re-read the focused element after an input action (MIR-08 verify-after-act); best effort."""
    if not _ax_helper(root):
        return None
    try:
        payload = _ax_call(root, ["focused", "--pid", str(pid)], timeout=10)
        node = payload.get("focused") or {}
        if not isinstance(node, dict) or not node:
            return None
        return {"role": node.get("role"), "value": (node.get("value") or "")[:200] or None,
                "path": node.get("path"), "label": (node.get("label") or "")[:80] or None}
    except PlanError:
        return None


def macos_control_input(root: str, data: dict) -> dict:
    """One immediate double-click, right-click, typed text, key press or paste while armed."""
    values = _validated_input(data)
    args = ["input", str(values["pid"]), str(values["x"]), str(values["y"]), values["kind"]]
    if values["kind"] in ("type", "paste", "scroll"):
        args.append(values["text"])
    elif values["kind"] == "key":
        args.append(values["key"])
    return _run_control_script(root, args, values)


# MIR-04: the streaming mirror — one multipart MJPEG response instead of a poll per frame.
_MACOS_STREAM_CAP = _MACOS_CONFIG["streamCap"]  # a stream never outlives this many seconds, so handlers cannot dangle


def macos_window_stream(window_id: int, fps: float, epoch: int | None = None):
    """Yield PNG frames for the multipart response at the requested pace. Ends when the
    window is gone, when a panic stop bumped the epoch, or at the handler's hard cap."""
    interval = 1.0 / fps
    while True:
        if epoch is not None and epoch != _MACOS_STREAM_EPOCH:
            return  # a panic stop ended this stream
        try:
            yield macos_window_screenshot(window_id)
        except PlanError:
            return
        time.sleep(interval)


# MIR-05: deep inspect — one Appium mac2 session per app bundle id with stable WebDriver
# element ids behind the mirror. A session launches or activates the app, so it exists only
# while control mode is armed and closes when control disarms, the panel hides or the app quits.
_MACOS_SESSIONS: dict[str, dict] = {}
_MACOS_SESSIONS_LOCK = threading.Lock()
_MACOS_ELEMENT_ID_KEY = "element-6066-11e4-a52e-4f735466cecf"
_BUNDLE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,198}[A-Za-z0-9])?$")
_ELEMENT_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _macos_appium_base(root: str) -> str:
    config = env_entries(_read(os.path.join(root, "ios-lab", "mac", "config.env")))
    return "http://{}:{}".format(config.get("APPIUM_HOST") or "127.0.0.1",
                                 config.get("APPIUM_PORT") or "4723")


def _appium_request(base: str, method: str, path: str, body: dict | None = None,
                    timeout: float = 30) -> tuple[int, dict]:
    """One Appium WebDriver call via stdlib urllib; returns (status, parsed body)."""
    data = json.dumps(body or {}).encode() if body is not None or method == "POST" else None
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
        except (OSError, ValueError):
            return e.code, {}
    except (OSError, ValueError) as e:
        raise PlanError(f"Appium is not reachable: {e}") from None


def _macos_control_armed() -> bool:
    with _MACOS_CONTROL_LOCK:
        armed = _MACOS_CONTROL["armed"] and time.time() - _MACOS_CONTROL["armedAt"] < _MACOS_CONTROL_TIMEOUT
    return armed


def _macos_sessions_enforce(root: str) -> None:
    """Deep inspect exists only while control mode is armed; disarming closes every session."""
    if _macos_control_armed():
        return
    with _MACOS_SESSIONS_LOCK:
        sessions = list(_MACOS_SESSIONS.items())
        _MACOS_SESSIONS.clear()
    for bundle, entry in sessions:
        try:
            _appium_request(_macos_appium_base(root), "DELETE", f"/session/{entry['sessionId']}", timeout=15)
        except PlanError:
            pass
        _macos_audit(root, "session-close", detail={"bundleId": bundle, "reason": "disarmed"})


def _macos_sessions_entry(bundle: str, required: bool = True) -> dict | None:
    if not isinstance(bundle, str) or not _BUNDLE_ID.match(bundle):
        raise PlanError("Unknown deep-inspect session (invalid bundleId)")
    with _MACOS_SESSIONS_LOCK:
        entry = _MACOS_SESSIONS.get(bundle)
    if required and entry is None:
        raise PlanError("No deep-inspect session is open for that app; open one in the panel first")
    return entry


def macos_session_state(root: str) -> dict:
    """The open deep-inspect sessions and whether Appium answers at all."""
    _macos_sessions_enforce(root)
    try:
        _appium_request(_macos_appium_base(root), "GET", "/status", timeout=5)
        reachable = True
    except PlanError:
        reachable = False
    with _MACOS_SESSIONS_LOCK:
        sessions = [{"bundleId": bundle, "sessionId": entry["sessionId"], "startedAt": entry["startedAt"]}
                    for bundle, entry in _MACOS_SESSIONS.items()]
    return {"appium": reachable, "sessions": sessions}


def _macos_bundle_id_for_app(app: str) -> str:
    """The bundle identifier of an installed app by name (`id of app …`): a metadata read that
    needs no automation permission. Names that could break the quoting are refused."""
    if not isinstance(app, str) or not app or len(app) > 120 or any(c in app for c in '"\\\r\n\x00'):
        raise PlanError("Invalid app name")
    code, output = _capture(["osascript", "-e", f'id of app "{app}"'], timeout=15)
    bundle = output.strip()
    if code != 0 or "." not in bundle or not _BUNDLE_ID.match(bundle):
        raise PlanError(f"Could not resolve a bundle id for {app}; the app may not be installed")
    return bundle


def macos_session_open(root: str, data: dict) -> dict:
    """Open one mac2 session for an app bundle id (or an app name, resolved here). Armed
    control mode only; a repeated open returns the session that is already open, and
    disarming closes every session."""
    if not _macos_control_armed():
        raise PlanError("Control mode is not armed; arm the app mirror to open a deep-inspect session",
                        code="NOT_ARMED", retry="retry")
    locked = macos_screen_locked()
    if locked:
        raise PlanError("The screen is locked; unlock this Mac to open a deep-inspect session",
                        code="SCREEN_LOCKED", retry="retry")
    bundle = data.get("bundleId")
    if bundle in (None, "") and data.get("app"):
        bundle = _macos_bundle_id_for_app(data.get("app"))
    if not isinstance(bundle, str) or not _BUNDLE_ID.match(bundle) or "." not in bundle:
        raise PlanError("bundleId must look like com.example.app", code="INVALID_ARGS")
    _macos_allowlist(root, data.get("app") if isinstance(data.get("app"), str) else None, bundle)
    with _MACOS_SESSIONS_LOCK:
        entry = _MACOS_SESSIONS.get(bundle)
    if entry:
        return {"bundleId": bundle, "sessionId": entry["sessionId"], "startedAt": entry["startedAt"]}
    base = _macos_appium_base(root)
    caps = {"capabilities": {"alwaysMatch": {
        "platformName": "mac", "appium:automationName": "mac2", "appium:bundleId": bundle,
        "appium:elementResponseAttributes": "type,label,name"}}}
    code, body = _appium_request(base, "POST", "/session", caps, timeout=300)
    value = body.get("value") if isinstance(body, dict) else None
    session_id = value.get("sessionId") if isinstance(value, dict) else None
    if code != 200 or not session_id:
        detail = value.get("message") if isinstance(value, dict) else None
        raise PlanError((detail or "Appium did not open a mac2 session; is the mac2 driver installed?")[:200])
    with _MACOS_SESSIONS_LOCK:
        _MACOS_SESSIONS[bundle] = {"sessionId": session_id, "startedAt": time.time()}
    _macos_audit(root, "session-open", detail={"bundleId": bundle})
    return {"bundleId": bundle, "sessionId": session_id}


def macos_session_elements(root: str, bundle: str) -> dict:
    """The deep-inspect element list: stable WebDriver ids with type, label and rect. Rects
    are screen points and are converted to window points like the AX overlay. Reading stops
    at 150 elements or a 20-second rect budget, whichever comes first."""
    _macos_sessions_enforce(root)
    entry = _macos_sessions_entry(bundle)
    base = _macos_appium_base(root)
    session = entry["sessionId"]
    code, body = _appium_request(base, "POST", f"/session/{session}/elements",
                                 {"using": "class name", "value": "XCUIElementTypeWindow"}, timeout=30)
    windows = (body.get("value") or []) if isinstance(body.get("value"), list) else []
    if code != 200 or not windows or not windows[0].get(_MACOS_ELEMENT_ID_KEY):
        raise PlanError("The mac2 session does not see a window for that app; it may have quit")
    window_el = windows[0][_MACOS_ELEMENT_ID_KEY]
    code, wrect = _appium_request(base, "GET", f"/session/{session}/window/rect", timeout=15)
    value = wrect.get("value") if isinstance(wrect.get("value"), dict) else {}
    wx, wy = int(value.get("x") or 0), int(value.get("y") or 0)
    code, body = _appium_request(base, "POST", f"/session/{session}/element/{window_el}/elements",
                                 {"using": "xpath", "value": "//*"}, timeout=60)
    if code != 200:
        detail = (body.get("value") or {}).get("message") if isinstance(body.get("value"), dict) else None
        raise PlanError((detail or "The deep-inspect element read failed")[:200])
    elements, deadline = [], time.time() + 20
    for raw in (body.get("value") or []):
        if len(elements) >= 150 or time.time() > deadline:
            break
        element_id = raw.get(_MACOS_ELEMENT_ID_KEY)
        if not element_id or not _ELEMENT_ID.match(str(element_id)):
            continue
        try:
            code2, rect = _appium_request(base, "GET", f"/session/{session}/element/{element_id}/rect",
                                          timeout=5)
            r = rect.get("value") if isinstance(rect.get("value"), dict) else {}
            x, y, w, h = int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])
        except (KeyError, TypeError, ValueError, PlanError):
            continue
        if w <= 0 or h <= 0:
            continue
        elements.append({"elementId": str(element_id), "role": (raw.get("type") or "").replace("XCUIElementType", ""),
                         "label": (raw.get("label") or "")[:120], "name": (raw.get("name") or "")[:120],
                         "x": x - wx, "y": y - wy, "w": w, "h": h})
    return {"bundleId": bundle, "sessionId": session, "window": {"x": wx, "y": wy}, "elements": elements}


def macos_session_action(root: str, bundle: str, data: dict) -> dict:
    """One click or typed text through the open session's element id (armed control mode)."""
    _macos_sessions_enforce(root)
    entry = _macos_sessions_entry(bundle)
    kind = data.get("kind")
    if kind not in ("click", "type"):
        raise PlanError("kind must be click or type")
    element = data.get("elementId")
    if not isinstance(element, str) or not _ELEMENT_ID.match(element):
        raise PlanError("Invalid element id")
    text = ""
    if kind == "type":
        text = data.get("text") if isinstance(data.get("text"), str) else ""
        if not text or len(text) > _INPUT_TEXT_MAX or not all(32 <= ord(c) <= 126 for c in text):
            raise PlanError(f"The text must be 1-{_INPUT_TEXT_MAX} printable characters; "
                            "Return is never sent by a type action")
    base = _macos_appium_base(root)
    if kind == "click":
        _appium_request(base, "POST", f"/session/{entry['sessionId']}/element/{element}/click", {}, timeout=30)
    else:
        _appium_request(base, "POST", f"/session/{entry['sessionId']}/element/{element}/value",
                        {"text": text}, timeout=30)
    _macos_audit(root, "session-" + kind, detail={"bundleId": bundle, "elementId": element,
                                                  "textLength": len(text)})
    return {"ok": True, "bundleId": bundle, "elementId": element, "kind": kind}


def macos_session_close(root: str, bundle: str) -> dict:
    """Close one deep-inspect session (panel hide, tab unload, app quit) — never left dangling."""
    entry = _macos_sessions_entry(bundle, required=False)
    if entry:
        with _MACOS_SESSIONS_LOCK:
            _MACOS_SESSIONS.pop(bundle, None)
        try:
            _appium_request(_macos_appium_base(root), "DELETE", f"/session/{entry['sessionId']}", timeout=15)
        except PlanError:
            pass
        _macos_audit(root, "session-close", detail={"bundleId": bundle, "reason": "panel"})
    return {"closed": bool(entry), "bundleId": bundle}


def _validated_ios_device(root: str, device: str) -> dict:
    """A device record from the simulator panel: exact UDID, or a name that names exactly one device."""
    info = ios_simulator(root)
    if not info["available"]:
        raise PlanError(info["reason"] or "The simulator tooling is not usable on this Mac")
    if any(d["udid"] == device for d in info["devices"]):
        return next(d for d in info["devices"] if d["udid"] == device)
    by_name = [d for d in info["devices"] if d["name"] == device]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise PlanError("Several installed devices share that name; pick one in the simulator panel")
    raise PlanError("That simulator device is not installed on this Mac")


def host_info(root: str) -> dict:
    os_name = host_os()
    arch = host_arch()
    kvm_path = "/dev/kvm"
    kvm_exists = os.path.exists(kvm_path)
    try:
        disk = shutil.disk_usage(root)
        disk_info = {"total": disk.total, "free": disk.free}
    except OSError:
        disk_info = None
    in_wsl = os_name == "linux" and "microsoft" in _read("/proc/version").lower()
    return {
        "os": os_name,
        "osPretty": os_pretty(os_name),
        "arch": arch,
        "hostname": platform.node(),
        "cpus": os.cpu_count(),
        "memory": memory_bytes(os_name),
        "disk": disk_info,
        "kvm": {"present": kvm_exists, "usable": kvm_exists and os.access(kvm_path, os.R_OK | os.W_OK)},
        "wsl": {"guest": in_wsl, "distributions": wsl_distributions()},
        "runtime": container_runtime(),
        "xcode": xcode_status() if os_name == "macos" else None,
        "python": platform.python_version(),
        "root": root,
        "tools": [{"id": t, "label": label, "found": bool(_which(t)), "path": _which(t)} for t, label in tools_for_host(os_name)],
        "providers": [p for p in provider_report(os_name, arch) if p["candidate"]],
    }


def provider_report(os_name: str, arch: str) -> list[dict]:
    """Which providers are candidates on this host (os_lab_runtime.rs::provider_report)."""
    vm_linux = os_name == "linux" and arch == "x86_64"
    return [
        {"id": "native-python", "guest": "Source / package analysis", "candidate": os_name in ("linux", "macos", "windows"),
         "requirements": "Native Python 3.11+ and writable private storage; no VM or containers"},
        {"id": "windows-container", "guest": "Windows", "candidate": vm_linux or os_name == "windows",
         "requirements": "WSL2 Linux, working Docker/Podman and usable KVM" if os_name == "windows"
         else "x86_64 Linux, working Docker/Podman and usable KVM"},
        {"id": "linux-container", "guest": "Linux", "candidate": os_name in ("linux", "windows"),
         "requirements": "Linux (or WSL2), working Docker/Podman and usable KVM"},
        {"id": "android-container", "guest": "Android / static analysis", "candidate": True,
         "requirements": "Working Docker/Podman; the dynamic emulator also needs usable acceleration"},
        {"id": "native-macos", "guest": "iOS Simulator / Appium", "candidate": os_name == "macos",
         "requirements": "Mac with Xcode, an installed Simulator runtime and Appium/XCUITest"},
        {"id": "ios-vm", "guest": "macOS VM / iOS tooling", "candidate": vm_linux or os_name == "windows",
         "requirements": "Suitable Linux/KVM host and guest/tool prerequisites"},
    ]


# ── Lab availability ─────────────────────────────────────────────────────────

def _req(id_: str, label: str, found: bool, required: bool = True, hint: str = "") -> dict:
    return {"id": id_, "label": label, "found": bool(found), "required": required, "hint": hint}


def provider_for(lab: str, os_name: str) -> str | None:
    if lab == "source":
        return "native-python" if os_name in ("linux", "macos", "windows") else None
    if lab == "web":
        return "native-rust" if os_name in ("linux", "macos", "windows") else None
    if lab == "macos":
        return "native-macos" if os_name == "macos" else None
    if lab == "winapps":
        return "native-windows" if os_name == "windows" else None
    if os_name == "macos":
        if lab == "ios":
            return "native-macos"
        if lab == "android":
            return "macos-containers"
        return None
    if os_name == "windows":
        return "wsl2"
    if os_name == "linux":
        return "linux-containers"
    return None


def lab_status(lab: str, host: dict) -> dict:
    """Availability of one lab on this host: ready, needs-setup or unavailable, with the reasons."""
    if lab == "source":
        import source_control
        return source_control.lab_status(host["root"], host["os"])
    if lab == "web":
        return web_lab_status(host)
    meta = LABS[lab]
    os_name, arch = host["os"], host["arch"]
    tools = {t["id"]: t["found"] for t in host["tools"]}
    runtime = bool(host["runtime"])
    kvm = host["kvm"]["usable"]
    provider = provider_for(lab, os_name)
    reasons: list[str] = []
    reqs: list[dict] = []
    notes: list[str] = []
    state = "ready"

    if provider is None:
        if lab == "macos":
            reasons.append("macOS application automation needs a Mac.")
        elif lab == "winapps":
            reasons.append("The Windows Apps Lab needs a Windows host.")
        else:
            reasons.append("This lab needs a Linux/KVM host (or Windows with WSL2). Use a remote Linux machine.")
        return {"id": lab, "label": meta["label"], "summary": meta["summary"], "state": "unavailable",
                "provider": None, "reasons": reasons, "requirements": reqs, "notes": notes,
                "actions": [], "installed": os.path.isdir(os.path.join(host["root"], meta["dir"]))}

    if provider == "native-macos":
        if lab == "macos":
            # The macOS Lab drives installed applications through Appium mac2 — no Xcode or simulator needed.
            reqs += [
                _req("brew", "Homebrew", tools.get("brew"), required=False, hint="https://brew.sh (needed for automated Appium setup)"),
                _req("node", "Node.js", tools.get("node"), required=False, hint="brew install node"),
                _req("appium", "Appium (mac2)", tools.get("appium"), required=False, hint="Install Appium (no administrator rights)"),
            ]
            if not tools.get("appium"):
                notes.append("macOS app automation needs Appium with its mac2 driver; status and doctor work without it.")
            notes.append("mac2 sessions need Accessibility permission (System Settings > Privacy & Security) to control applications.")
        else:
            notes.append("Uses the same native Xcode installation as macOS Lab on this Mac.")
            xcode = host.get("xcode") or {}
            idb_ready = bool(tools.get("idb")) and bool(tools.get("idb-companion"))
            reqs += [
                _req("xcode", "Full Xcode", xcode.get("installed"), hint="Install and open Xcode, then accept its license"),
                _req("ios-runtime", "iOS Simulator runtime", xcode.get("iosRuntime"), hint="Xcode > Settings > Components"),
                _req("ios-device", "Available iOS Simulator device", xcode.get("iosDevice"), hint="Add a simulator in Xcode"),
                _req("brew", "Homebrew", tools.get("brew"), required=False, hint="https://brew.sh (needed for automated Appium and idb setup)"),
                _req("node", "Node.js", tools.get("node"), required=False, hint="brew install node"),
                _req("appium", "Appium (XCUITest)", tools.get("appium"), required=False, hint="Install Appium (no administrator rights)"),
                _req("idb", "idb (companion + client)", idb_ready, required=False, hint="Install idb (companion via Homebrew, client for this user)"),
            ]
            if not tools.get("appium"):
                notes.append("Appium automation needs Appium and its XCUITest driver; the simulator can run without them.")
            if not idb_ready:
                notes.append("idb device automation needs the idb companion and client; the simulator can run without them.")
    elif provider == "native-windows" and lab == "winapps":
        # The Windows Apps Lab reads the current desktop directly; no VM/container runtime is involved.
        installed = os.path.isfile(os.path.join(host["root"], "console", "winapps.py"))
        if not installed:
            state = "unavailable"
            reasons.append("The Windows Apps Lab is not installed on this host.")
        else:
            state = "ready"
        return {"id": lab, "label": meta["label"], "summary": meta["summary"], "state": state,
                "provider": provider, "reasons": reasons, "requirements": reqs, "notes": notes,
                "actions": [], "installed": installed}
    elif provider == "wsl2":
        distros = host["wsl"]["distributions"]
        reqs += [
            _req("wsl", "WSL2", tools.get("wsl"), hint="wsl --install"),
            _req("wsl-distro", "A WSL2 Linux distribution", bool(distros), hint="wsl --install -d Ubuntu"),
        ]
        notes.append("Commands run inside the selected WSL2 distribution; Docker/Podman and KVM are checked there by Doctor.")
    else:
        reqs.append(_req("runtime", "Working Docker or Podman with Compose", runtime,
                         hint="Start the engine and install its Compose plugin if needed"))
        reqs.append(_req("bash", "Bash", tools.get("bash")))
        needs_kvm = lab in ("windows", "linux", "ios")
        if os_name == "linux":
            reqs.append(_req("kvm", "Usable /dev/kvm", kvm, required=needs_kvm,
                             hint="Enable virtualization in firmware, then Install dependencies (adds you to the kvm group)"))
        if lab in ("windows", "ios") and arch != "x86_64":
            reasons.append(f"{meta['label']} guests need an x86_64 host; this host is {arch}.")
            state = "unavailable"
        if lab == "android":
            reqs.append(_req("adb", "Android Debug Bridge", tools.get("adb"), required=False, hint="Install dependencies"))
            if os_name == "linux" and not kvm:
                notes.append("No usable KVM: static analysis (MobSF, mitmproxy, tools) works; the emulator needs KVM.")
        if provider == "macos-containers":
            notes.append("On macOS only the lightweight/static Android profile runs; the emulator needs a Linux/KVM host.")

    if state != "unavailable" and any(r["required"] and not r["found"] for r in reqs):
        state = "needs-setup"
        reasons.append("Missing: " + ", ".join(r["label"] for r in reqs if r["required"] and not r["found"]) + ".")

    actions = actions_for(lab, provider) if state != "unavailable" else []
    if state == "needs-setup":
        # Something this lab requires is missing: only the ways to fix or diagnose that are offered.
        # Start, stop, resize, logs and the rest come back once the requirements are met.
        actions = [x for x in actions if x["id"] in SETUP_STATE_ACTIONS]
    if provider == "native-macos":
        # Installed tooling: offer start/stop, not install. Missing tooling: offer install, not start/stop.
        # The XCUITest/mac2 smoke runs additionally need Appium with their driver.
        if lab == "macos":
            drop = {"appium-install"} if tools.get("appium") else {"appium-start", "appium-stop", "macos-smoke"}
        else:
            drop = {"appium-install"} if tools.get("appium") else {"appium-start", "appium-stop"}
            drop |= {"idb-install"} if tools.get("idb") and tools.get("idb-companion") else {"idb-start", "idb-stop"}
            if not tools.get("appium"):
                drop.add("xcuitest-smoke")
        actions = [a for a in actions if a["id"] not in drop]
        for a in actions:
            if a["id"] in NATIVE_SIMULATOR_INFO:
                a["label"], a["description"] = NATIVE_SIMULATOR_INFO[a["id"]]
    summary = ("Run the iOS Simulator with this Mac's Xcode; Appium automation is optional."
               if lab == "ios" and provider == "native-macos" else meta["summary"])
    return {"id": lab, "label": meta["label"], "summary": summary, "state": state, "provider": provider,
            "reasons": reasons, "requirements": reqs, "notes": notes, "actions": actions,
            "installed": os.path.isdir(os.path.join(host["root"], meta["dir"]))}


def web_lab_status(host: dict) -> dict:
    """Web Lab readiness from console/web_api.py: cargo and make decide the state.

    ``ready`` covers both a running engine and a built-but-stopped one: the
    console can start the engine itself, so only the binary really gates use.
    """
    meta = LABS["web"]
    tools = {t["id"]: t["found"] for t in host["tools"]}
    try:
        import web_api
        engine = web_api.WebLabAPI(host["root"]).status()
    except ImportError:
        engine = None
    binary = bool(engine and engine.get("binary"))
    reqs = [
        _req("cargo", "Rust (Cargo)", tools.get("cargo"), required=not binary, hint="Install Rust via rustup (https://rustup.rs)"),
        _req("make", "Make", tools.get("make"), required=not binary),
        _req("bash", "Bash", tools.get("bash"), required=not binary),
    ]
    state = "ready"
    reasons: list[str] = []
    if not binary:
        state = "needs-setup" if tools.get("cargo") else "unavailable"
        reasons.append("The Web Lab engine is not built. Install dependencies (cargo build --release)."
                       if tools.get("cargo") else "Cargo is missing, so the engine cannot be built.")
    notes: list[str] = []
    if engine and engine.get("state") == "ready":
        notes.append("The engine is running on port %d." % engine.get("port"))
    else:
        notes.append("The engine runs locally on 127.0.0.1 and starts from the console when needed.")
    provider = provider_for("web", host["os"])
    if provider is None:
        state = "unavailable"
        reasons.append("Web Lab needs a Linux, macOS or Windows host.")
    return {"id": "web", "label": meta["label"], "summary": meta["summary"], "state": state,
            "provider": provider, "reasons": reasons, "requirements": reqs, "notes": notes,
            "actions": actions_for("web", provider) if state != "unavailable" else [],
            "installed": os.path.isdir(os.path.join(host["root"], meta["dir"]))}


def actions_for(lab: str, provider: str | None) -> list[dict]:
    if provider == "native-macos":
        names = MACOS_APP_ACTIONS if lab == "macos" else MAC_ACTIONS
    elif provider == "native-rust":
        names = ["status", "doctor", "setup", "start", "stop"]
    elif provider:
        names = [a for a in LABCTL_ACTIONS if not (a == "backup" and lab == "android")]
        if provider == "macos-containers":
            names = [a for a in names if a not in PRIVILEGED]
    else:
        names = []
    return [{"id": n, "label": ACTION_INFO[n][0], "description": ACTION_INFO[n][1],
             "privileged": n in PRIVILEGED and provider != "native-macos"} for n in names]


def lab_catalog(root: str, host: dict | None = None) -> dict:
    host = host or host_info(root)
    return {"host": {"os": host["os"], "arch": host["arch"]},
            "labs": [lab_status(lab, host) for lab in LAB_ORDER]}


def capability_catalog() -> dict:
    """Health's platform tree. Lab support levels follow the same provider rules as lab_status."""
    with open(os.path.join(os.path.dirname(__file__), "capabilities.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    for group in catalog["groups"]:
        for item in group["items"]:
            lab = item.get("lab")
            if not lab:
                continue
            for platform in ("macos", "windows", "linux"):
                provider = provider_for(lab, platform)
                if provider is None:
                    level = "none"
                elif provider in ("wsl2", "macos-containers") or (lab == "ios" and platform == "linux"):
                    level = "partial"
                else:
                    level = "full"
                item["support"][platform]["level"] = level
    return catalog


def scope_status(root: str) -> dict:
    """The declared lab scope that console/scope_guard.py enforces: scope.json or $OSLAB_SCOPE_FILE."""
    import scope_guard
    return scope_guard.scope_status(root)


# ── Configuration ────────────────────────────────────────────────────────────

def env_entries(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            out[key] = value.strip().strip("'\"")
    return out


def is_secret(key: str) -> bool:
    return any(part in key.upper() for part in SECRET_PARTS)


def lab_config(root: str, lab: str) -> dict:
    """Effective configuration: .env.example defaults overlaid by .env, with secrets masked."""
    if lab == "source":
        import source_control
        base = source_control.storage(root)
        resources = os.environ.get("SOURCE_LAB_RESOURCES", str(base / "resources"))
        return {"lab": lab, "path": "Process environment (example files are not loaded)", "exists": False,
                "fields": [{"key": "SOURCE_LAB_STORAGE", "value": str(base), "local": "SOURCE_LAB_STORAGE" in os.environ},
                           {"key": "SOURCE_LAB_RESOURCES", "value": resources, "local": "SOURCE_LAB_RESOURCES" in os.environ}],
                "profiles": [], "backups": [], "endpoints": []}
    meta = LABS[lab]
    base = os.path.join(root, meta["dir"])
    config_name = "config.env" if lab == "macos" else ".env"
    values = env_entries(_read(os.path.join(base, config_name + ".example")))
    local = env_entries(_read(os.path.join(base, config_name)))
    values.update(local)
    fields = [{"key": k, "value": "••••••" if is_secret(k) and v else v, "local": k in local}
              for k, v in sorted(values.items())]
    prof_dir = os.path.join(base, "profiles")
    profiles = sorted(n[:-4] for n in os.listdir(prof_dir) if n.endswith(".env")) if os.path.isdir(prof_dir) else []
    backups_dir = os.path.join(base, "backups")
    backups = sorted(n for n in os.listdir(backups_dir) if n.endswith(".tar.gz")) if os.path.isdir(backups_dir) else []
    return {"lab": lab, "path": os.path.join(meta["dir"], config_name), "exists": os.path.isfile(os.path.join(base, config_name)),
            "fields": fields, "profiles": profiles, "backups": backups, "endpoints": endpoints(lab, values)}


def endpoints(lab: str, values: dict[str, str]) -> list[dict]:
    web = values.get("WEB_PORT", "8006")
    if lab == "windows":
        return [{"label": "Web desktop", "address": f"http://127.0.0.1:{web}/"},
                {"label": "RDP", "address": f"127.0.0.1:{values.get('RDP_PORT', '3389')}"}]
    if lab == "linux":
        return [{"label": "Web console", "address": f"http://127.0.0.1:{web}/"},
                {"label": "SSH", "address": f"ssh -p {values.get('SSH_PORT', '2222')} {values.get('LINUX_USER', 'root')}@127.0.0.1"}]
    if lab == "ios":
        return [{"label": "Web viewer", "address": f"http://127.0.0.1:{web}/"},
                {"label": "VNC", "address": f"127.0.0.1:{values.get('VNC_PORT', '5900')}"}]
    if lab == "android":
        return [{"label": "noVNC", "address": "http://127.0.0.1:6080/"},
                {"label": "MobSF", "address": "http://127.0.0.1:8000/"},
                {"label": "mitmweb", "address": "http://127.0.0.1:8081/"},
                {"label": "mitmproxy", "address": "127.0.0.1:8080"},
                {"label": "ADB", "address": "127.0.0.1:5555"}]
    if lab == "macos":
        return [{"label": "Appium", "address": f"http://127.0.0.1:{values.get('APPIUM_PORT', '4723')}/"}]
    return []


def secret_values(root: str) -> list[str]:
    values = []
    for lab, meta in LABS.items():
        name = "config.env" if lab == "macos" else ".env"
        for key, value in env_entries(_read(os.path.join(root, meta["dir"], name))).items():
            if is_secret(key) and len(value) >= 3:
                values.append(value)
    for key, value in os.environ.items():
        if is_secret(key) and len(value) >= 3:
            values.append(value)
    try:
        from source_artifacts import SourceArtifacts
        raw = SourceArtifacts(root)._read(("control", "session-hmac.key"), 4096, optional=True)
        if raw:
            values.append(raw.decode("utf-8").strip())
    except (ValueError, OSError):
        pass
    key_file = os.environ.get("IQ_SESSION_HMAC_KEY_FILE")
    if key_file:
        try:
            import stat
            fd = os.open(key_file, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                if stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raw = stream.read(4097)
                    if len(raw) <= 4096:
                        values.append(raw.decode("utf-8").strip())
        except (OSError, ValueError):
            pass
    return sorted(set(values), key=len, reverse=True)


def redact_text(root: str, text: str, values=None) -> str:
    for value in secret_values(root) if values is None else values:
        if value:
            text = text.replace(value, "[redacted]")
    text = re.sub(r"(?i)(https?://)[^/\s@]+@", r"\1[redacted]@", text)
    text = re.sub(r"(?i)((?:password|token|secret|api[_-]?key|authorization)\s*[=:]\s*)[^\s,;]+", r"\1[redacted]", text)
    return text


# ── Plans ────────────────────────────────────────────────────────────────────

def setup_details(root: str, lab: str, provider: str) -> dict:
    """What "Install dependencies" needs and changes (os_lab_provider.rs::setup_details)."""
    meta = LABS[lab]
    values = {}
    if lab != "macos":
        values = env_entries(_read(os.path.join(root, meta["dir"], ".env.example")))
        values.update(env_entries(_read(os.path.join(root, meta["dir"], ".env"))))
    disk = values.get("DISK_SIZE") if SIZE.match(values.get("DISK_SIZE", "")) else meta.get("disk_default")
    if provider == "native-macos":
        if lab == "macos":
            deps = ["Homebrew (optional)", "Node.js", "Appium with the mac2 driver"]
            downloads = ["The setup installs Appium and the mac2 driver into your user folder. macOS may ask to "
                         "grant Accessibility permission before mac2 can control applications."]
            privileges = "Runs as the current user; no administrator rights."
        else:
            deps = ["Xcode and an installed iOS Simulator runtime", "Homebrew", "Node.js", "Appium with XCUITest"]
            downloads = ["The setup script checks prerequisites and installs Homebrew packages. Xcode/runtime "
                         "installation and license acceptance remain explicit user actions."]
            privileges = "Runs as the current user; Xcode installation or license acceptance may need macOS authorization."
    else:
        deps = ["Ubuntu/Debian host or WSL2 distribution", "Docker or Podman and Compose",
                "KVM for accelerated guests", "Python 3 for restore/report workflows"]
        if lab == "android":
            deps.insert(2, "adb (Android platform tools)")
        downloads = ["The setup script may install system packages and a container runtime. Image tags and guest "
                     "install media resolve at start; their download size is unknown until then."]
        privileges = ("Requires administrator authorization. The script may change groups (docker, kvm), services, "
                      "KVM modules and explicitly configured firewall rules.")
    return {
        "dependencies": deps,
        "downloads": downloads,
        "privileges": privileges,
        "guestDisk": disk,
        "diskNote": ("Configured guest virtual disk capacity; allow extra space for images, install media, logs "
                     "and backups. Sparse allocation is not a free-space guarantee.") if disk else
                    ("Download and expanded sizes are unresolved. Reserve space for images, artifacts and backups."),
        "verifiedDownloads": False,
    }


def _scoped(root: str, *parts: str) -> str:
    path = os.path.realpath(os.path.join(root, *parts))
    real_root = os.path.realpath(root)
    if os.path.commonpath([real_root, path]) != real_root:
        raise PlanError("Path escapes the os-lab checkout")
    return path


def plan(root: str, request: dict, host: dict | None = None) -> dict:
    """Validate a lab request and build the exact command to run. Raises PlanError."""
    if request.get("lab") == "source":
        import source_control
        return source_control.plan(root, request)
    allowed = {"lab", "action", "profile", "cpus", "ram", "disk", "device", "wslDistro", "backup",
               "clickPid", "clickX", "clickY", "inputKind", "inputText", "inputKey",
               "elementId", "elementKind", "elementSession", "elementBundle",
               "elementPid", "elementPath", "elementIdentity", "axAction", "elementValue", "elementWindowId",
               "scrollDirection", "scrollPages"}
    unknown = set(request) - allowed
    if unknown:
        raise PlanError("Unknown request fields: " + ", ".join(sorted(unknown)))
    lab = request.get("lab")
    action = request.get("action")
    if lab not in LABS:
        raise PlanError("Unknown lab")
    host = host or host_info(root)
    status = lab_status(lab, host)
    provider = status["provider"]
    if status["state"] == "unavailable" or not provider:
        raise PlanError(" ".join(status["reasons"]) or "This lab is unavailable on this host")
    if action not in {a["id"] for a in status["actions"]}:
        raise PlanError(f"Unsupported action for {LABS[lab]['label']}: {action}")

    profile = request.get("profile") or None
    if profile is not None and (not isinstance(profile, str) or not SAFE_NAME.match(profile) or profile.startswith("-")):
        raise PlanError("Invalid profile name")
    distro = request.get("wslDistro") or None
    if distro is not None and (not isinstance(distro, str) or len(distro) > 128 or distro.startswith("-")
                               or any(c in distro for c in "\r\n\0")):
        raise PlanError("Invalid WSL distribution")
    device = request.get("device")
    ios_attach = lab == "ios" and action == "start" and provider == "native-macos"
    if device not in (None, ""):
        # A device picks the simulator the start action boots; resize uses one for Android's emulator.
        if not ios_attach and action != "resize":
            raise PlanError("Resource parameters are only accepted by resize")
        if not isinstance(device, str) or len(device) > 128 or any(c in device for c in "\r\n\0"):
            raise PlanError("Invalid simulator device")
    for key in ("cpus", "ram", "disk"):
        if request.get(key) not in (None, "") and action != "resize":
            raise PlanError("Resource parameters are only accepted by resize")
    click = {"pid": request.get("clickPid"), "x": request.get("clickX"), "y": request.get("clickY")}
    if any(v not in (None, "") for v in click.values()) and action not in ("macos-click", "macos-input", "macos-scroll"):
        raise PlanError("Click coordinates are only accepted by the app mirror actions")
    if action in ("macos-click", "macos-input", "macos-scroll"):
        for name, value in click.items():
            try:
                if not 0 <= int(value) <= 100000:
                    raise ValueError
            except (TypeError, ValueError):
                raise PlanError(f"click{name.capitalize()} must be a screen coordinate") from None
            click[name] = int(value)
    scroll_values: dict = {}
    if any(request.get(k) not in (None, "") for k in ("scrollDirection", "scrollPages")) and action != "macos-scroll":
        raise PlanError("Scroll parameters are only accepted by the app mirror scroll action")
    if action == "macos-scroll":
        scroll_values = _validated_input({"pid": click["pid"], "x": click["x"], "y": click["y"],
                                          "kind": "scroll", "direction": request.get("scrollDirection"),
                                          "pages": request.get("scrollPages")})
    input_values: dict = {}
    # inputText is the shared typed-text payload of macos-input and macos-element; the kind and
    # key fields belong to macos-input alone.
    if request.get("inputText") not in (None, "") and action not in ("macos-input", "macos-element"):
        raise PlanError("Input text is only accepted by the app mirror actions")
    if any(request.get(k) not in (None, "") for k in ("inputKind", "inputKey")) and action != "macos-input":
        raise PlanError("Input parameters are only accepted by the app mirror input action")
    if action == "macos-input":
        input_values = _validated_input({"pid": click["pid"], "x": click["x"], "y": click["y"],
                                         "kind": request.get("inputKind"),
                                         "text": request.get("inputText"), "key": request.get("inputKey")})
    element_values: dict = {}
    if any(request.get(k) not in (None, "") for k in ("elementId", "elementKind", "elementSession", "elementBundle")) \
            and action != "macos-element":
        raise PlanError("Element parameters are only accepted by the deep-inspect element action")
    if action == "macos-element":
        if not isinstance(request.get("elementSession"), str) or not _ELEMENT_ID.match(request["elementSession"]):
            raise PlanError("elementSession must be an open Appium session id")
        if not isinstance(request.get("elementId"), str) or not _ELEMENT_ID.match(request["elementId"]):
            raise PlanError("elementId must be a deep-inspect element id")
        if request.get("elementKind") not in ("click", "type"):
            raise PlanError("elementKind must be click or type")
        element_values = {"session": request["elementSession"], "element": request["elementId"],
                          "kind": request.get("elementKind")}
        if element_values["kind"] == "type":
            text = request.get("inputText")
            if not isinstance(text, str) or not text or len(text) > _INPUT_TEXT_MAX \
                    or not all(32 <= ord(c) <= 126 for c in text):
                raise PlanError(f"The text must be 1-{_INPUT_TEXT_MAX} printable characters; "
                                "Return is never sent by a type action")
            element_values["text"] = text
        bundle = request.get("elementBundle")
        if bundle is not None and (not isinstance(bundle, str) or not _BUNDLE_ID.match(bundle)):
            raise PlanError("elementBundle must look like com.example.app")
        element_values["bundle"] = bundle or "the app"
    ax_values: dict = {}
    if any(request.get(k) not in (None, "") for k in ("elementPid", "elementPath", "elementIdentity", "axAction", "elementValue", "elementWindowId")) \
            and action not in ("macos-set-value", "macos-perform"):
        raise PlanError("AX element parameters are only accepted by the set-value and perform actions")
    if action in ("macos-set-value", "macos-perform"):
        try:
            ax_pid = int(request.get("elementPid"))
        except (TypeError, ValueError):
            raise PlanError("elementPid must be an integer", code="INVALID_ARGS") from None
        if not 0 <= ax_pid <= 100000:
            raise PlanError("elementPid is out of range", code="INVALID_ARGS")
        path = request.get("elementPath")
        if not isinstance(path, str) or not _AX_PATH.match(path):
            raise PlanError("elementPath must be a child-index chain like 0.3.1", code="INVALID_ARGS")
        identity = request.get("elementIdentity") or ""
        if not isinstance(identity, str) or not re.match(r"^[0-9a-f]{0,16}$", identity):
            raise PlanError("elementIdentity must be the hex hash from the tree read", code="INVALID_ARGS")
        try:
            ax_window = int(request.get("elementWindowId"))
        except (TypeError, ValueError):
            raise PlanError("elementWindowId must be the CG window id from the mirror", code="INVALID_ARGS") from None
        ax_values = {"pid": ax_pid, "path": path, "identity": identity, "window": ax_window}
        if action == "macos-set-value":
            value = request.get("elementValue")
            if not isinstance(value, str) or not value or len(value) > 2000 \
                    or not all(c.isprintable() and c not in "\r\n" for c in value):
                raise PlanError("elementValue must be 1-2000 printable characters (no Return)",
                                code="INVALID_ARGS", retry="never")
            ax_values["value"] = value
        else:
            ax_action = request.get("axAction")
            if not isinstance(ax_action, str) or not re.match(r"^AX[A-Za-z]{2,40}$", ax_action):
                raise PlanError("axAction must be an advertised AX action name (e.g. AXPress)",
                                code="INVALID_ARGS", retry="never")
            ax_values["action"] = ax_action
    if request.get("backup"):
        raise PlanError("Restore is not available from the web console; use the lab's scripts/restore.sh")

    meta = LABS[lab]
    effects = ["Runs os-lab scripts in " + root + " and reads the lab's environment configuration"]
    privileged = action in PRIVILEGED
    timeout = 120
    manual = None

    if provider == "native-macos":
        if profile:
            raise PlanError("Native settings live in ios-lab/mac/config.env")
        if lab == "macos":
            # macOS Lab: applications on this Mac through Appium mac2 — the simulator stays in the iOS Lab.
            script, extra = {
                "status": ("macos-app.sh", "status"), "doctor": ("macos-app.sh", "doctor"),
                "setup": ("appium.sh", "install"), "appium-install": ("appium.sh", "install"),
                "appium-start": ("appium.sh", "start"), "appium-stop": ("appium.sh", "stop"),
                "macos-smoke": ("macos-app.sh", "smoke"), "macos-click": ("macos-app.sh", "click"),
                "macos-input": ("macos-app.sh", "input"), "macos-scroll": ("macos-app.sh", "input"),
                "macos-element": ("macos-app.sh", "element"),
                "macos-set-value": ("macos-app.sh", "axset"), "macos-perform": ("macos-app.sh", "axperform"),
            }[action]
        else:
            script, extra = {
                "status": ("status-mac.sh", None), "doctor": ("doctor-mac.sh", None),
                "setup": ("setup-mac.sh", "--install"), "start": ("run-simulator.sh", None),
                "stop": ("stop-simulator.sh", None), "appium-install": ("appium.sh", "install"), "appium-start": ("appium.sh", "start"),
                "appium-stop": ("appium.sh", "stop"), "idb-install": ("idb.sh", "install"), "idb-start": ("idb.sh", "start"),
                "idb-stop": ("idb.sh", "stop"), "xcuitest-smoke": ("xcuitest.sh", "smoke"),
            }[action]
        selected = []
        if action == "start" and device not in (None, ""):
            picked = _validated_ios_device(root, device)
            selected = ["--device", picked["udid"]]
            effects.append(f"Boots the iOS Simulator device {picked['name']} ({picked['runtime']}) on this Mac.")
        if action == "stop" and device not in (None, ""):
            picked = _validated_ios_device(root, device)
            selected = ["--device", picked["udid"]]
            effects.append(f"Shuts down the iOS Simulator device {picked['name']} on this Mac. Other devices keep running.")
        if action == "macos-click":
            selected = [str(click["pid"]), str(click["x"]), str(click["y"])]
            effects.append(f"Brings the app (pid {click['pid']}) to the front and clicks once at "
                           f"({click['x']}, {click['y']}) on this Mac.")
        if action == "macos-input":
            selected = [str(click["pid"]), str(click["x"]), str(click["y"]), input_values["kind"]]
            if input_values["kind"] == "type":
                selected.append(input_values["text"])
                effects.append(f"Brings the app (pid {click['pid']}) to the front and types "
                               f"{len(input_values['text'])} characters ({input_values['text'][:60]}) — "
                               "no Return is sent.")
            elif input_values["kind"] == "key":
                selected.append(input_values["key"])
                effects.append(f"Brings the app (pid {click['pid']}) to the front and presses the "
                               f"{input_values['key']} key.")
            else:
                effects.append(f"Brings the app (pid {click['pid']}) to the front and performs a "
                               f"{input_values['kind']} click at ({click['x']}, {click['y']}) on this Mac.")
        if action == "macos-scroll":
            selected = [str(click["pid"]), str(click["x"]), str(click["y"]), "scroll",
                        f"{scroll_values['direction']}:{scroll_values['pages']}"]
            effects.append(f"Brings the app (pid {click['pid']}) to the front and scrolls "
                           f"{scroll_values['direction']} {scroll_values['pages']} pages at "
                           f"({click['x']}, {click['y']}) on this Mac.")
        if action == "macos-element":
            selected = [element_values["session"], element_values["element"], element_values["kind"]]
            if element_values["kind"] == "type":
                selected.append(element_values["text"])
                effects.append(f"Types {len(element_values['text'])} characters into element "
                               f"{element_values['element']} through the open mac2 session for "
                               f"{element_values['bundle']} — no Return is sent.")
            else:
                effects.append(f"Clicks element {element_values['element']} through the open mac2 "
                               f"session for {element_values['bundle']}.")
        if action == "macos-set-value":
            selected = [str(ax_values["pid"]), str(ax_values["window"]), ax_values["path"],
                        ax_values["identity"], ax_values["value"]]
            effects.append(f"Writes {len(ax_values['value'])} characters straight into element "
                           f"{ax_values['path']} of pid {ax_values['pid']} through the AX helper — "
                           "no Return is sent.")
        if action == "macos-perform":
            selected = [str(ax_values["pid"]), str(ax_values["window"]), ax_values["path"],
                        ax_values["identity"], ax_values["action"]]
            effects.append(f"Performs {ax_values['action']} on element {ax_values['path']} of pid "
                           f"{ax_values['pid']} through the AX helper; the element must advertise it.")
        path = _scoped(root, "ios-lab", "mac", script)
        if not os.path.isfile(path):
            raise PlanError("Provider script is missing: ios-lab/mac/" + script)
        program, args = "bash", [path] + ([extra] if extra else []) + selected
        privileged = False
        timeout = 3600 if action == "setup" and lab != "macos" else 1800 if action in ("setup", "appium-install", "idb-install") \
            else 1500 if action == "xcuitest-smoke" else 600 if action == "macos-smoke" else 300
    else:
        labctl = _scoped(root, "labctl")
        if not os.path.isfile(labctl):
            raise PlanError("labctl is missing from the checkout")
        lab_dir = meta["dir"]
        if action in PRIVILEGED or action == "backup":
            name = {"setup": "setup-ubuntu.sh", "service-install": "install-service.sh",
                    "service-uninstall": "uninstall-service.sh", "backup": "backup.sh"}[action]
            script = _scoped(root, lab_dir, "scripts", name)
            if not os.path.isfile(script):
                raise PlanError("This lab does not provide " + name)
            if profile:
                raise PlanError("Apply a profile first, then run this action")
            program, args = "bash", [script]
            if lab == "web":
                effects.append("Installs the Rust toolchain via rustup if cargo is missing, then builds the Web Lab engine (cargo build --release).")
            else:
                effects.append({
                    "setup": "Installs packages, changes user groups and may alter firewall rules according to configuration.",
                    "service-install": "Changes system service boot configuration and may start the lab.",
                    "service-uninstall": "Removes the systemd unit; a running lab keeps running until stopped.",
                    "backup": "Writes a guest backup into the lab's backups/ folder. Ensure enough free space.",
                }[action])
            timeout = 3600
        else:
            args = [labctl, meta["labctl"]]
            if action == "monitor":
                args += ["monitor", "--once"]
            elif action == "profile":
                if not profile:
                    raise PlanError("Choose a profile to apply")
                if not os.path.isfile(_scoped(root, lab_dir, "profiles", profile + ".env")):
                    raise PlanError("Profile not found")
                args += ["profile", "use", profile]
                effects.append(f"Writes the {profile} preset into {lab_dir}/.env.")
                profile = None
            elif action == "resize":
                args.append("resize")
                cpus = request.get("cpus")
                if cpus not in (None, ""):
                    try:
                        cpus = int(cpus)
                    except (TypeError, ValueError):
                        raise PlanError("CPU count must be a number") from None
                    if not 1 <= cpus <= 128:
                        raise PlanError("CPU count must be 1–128")
                    args += ["--cpus", str(cpus)]
                for flag, key in (("--ram", "ram"), ("--disk", "disk")):
                    value = request.get(key)
                    if value in (None, ""):
                        continue
                    if not isinstance(value, str) or not SIZE.match(value):
                        raise PlanError("Sizes must be positive numbers with an optional M/G/T unit")
                    if key == "disk" and lab != "windows":
                        raise PlanError("Disk resize supports the Windows lab only")
                    args += [flag, value]
                device = request.get("device")
                if device not in (None, ""):
                    if lab != "android" or not isinstance(device, str) or len(device) > 128 or any(c in device for c in "\r\n\0"):
                        raise PlanError("Invalid Android device")
                    args += ["--device", device]
                if len(args) == 3:
                    raise PlanError("Choose a resource to resize")
                effects.append("Writes resource configuration to .env. Restart to apply; guest disks only grow.")
            else:
                args.append(action)
            if profile:
                if action not in ("status", "doctor", "start", "restart"):
                    raise PlanError("A one-shot profile applies to status, doctor, start and restart only")
                if not os.path.isfile(_scoped(root, lab_dir, "profiles", profile + ".env")):
                    raise PlanError("Profile not found")
                args += ["--profile", profile]
            program = "bash"
            if provider == "macos-containers" and action in ("start", "restart"):
                mode = env_entries(_read(os.path.join(root, lab_dir, ".env"))).get("LAB_MODE")
                if mode != "static" and profile != "lightweight":
                    raise PlanError("On macOS apply Android's lightweight (static) profile first; the emulator needs Linux/KVM")
            timeout = 900 if action in ("start", "restart") else 120

    if action in ("start", "stop", "restart", "appium-start", "appium-stop", "idb-start", "idb-stop"):
        effects.append("Changes guest, container or service lifecycle.")

    # Elevation and WSL wrapping
    os_name = host["os"]
    if provider == "wsl2":
        if not distro:
            raise PlanError("Choose an installed WSL2 distribution")
        if distro not in host["wsl"]["distributions"]:
            raise PlanError("That WSL distribution is not installed")
        args = [wsl_path(distro, a) if os.path.isabs(a) else a for a in args]
        prefix = ["--distribution", distro, "--cd", wsl_path(distro, root), "--exec"]
        prefix += ["sudo", "-n", "bash"] if privileged else ["bash"]
        program, args = "wsl.exe", prefix + args
        if privileged:
            effects.append("Uses passwordless sudo inside the distribution; configure it or run the command in a WSL terminal.")
    elif privileged and os_name == "linux":
        user = os.environ.get("USER", "")
        graphical = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        manual = "sudo " + (f"LAB_USER={user} " if SAFE_NAME.match(user or "-") else "") + "bash " + " ".join(args)
        if _which("pkexec") and graphical:
            env = ["/usr/bin/env", f"LAB_USER={user}"] if SAFE_NAME.match(user or "-") else []
            program, args = "pkexec", env + ["/bin/bash"] + args
            effects.append("Asks for your password through the system authorization dialog (pkexec).")
        else:
            program = None
            effects.append("No graphical authorization agent is available here: run the command below in a terminal.")

    if privileged:
        effects.append("Administrator rights are required.")

    result = {
        "lab": lab, "action": action, "provider": provider, "workspace": root,
        "program": program, "args": args, "effects": effects, "timeoutSec": timeout,
        "privileged": privileged, "runnable": program is not None,
        "manualCommand": manual if program is None else None,
        "setup": setup_details(root, lab, provider) if action == "setup" else None,
        "display": " ".join(_quote(p) for p in ([program] if program else []) + args),
    }
    return result


def _quote(value: str) -> str:
    return value if re.match(r"^[A-Za-z0-9_./:=@%+,-]+$", value) else "'" + value.replace("'", "'\\''") + "'"


def wsl_path(distro: str, path: str) -> str:
    code, out = _capture(["wsl.exe", "--distribution", distro, "--exec", "wslpath", "-a", "-u", path], timeout=10)
    mapped = out.strip()
    if code != 0 or not mapped.startswith("/") or any(c in mapped for c in "\r\n\0"):
        raise PlanError("WSL could not translate the workspace path")
    return mapped


class PlanSigner:
    """Binds a confirmed plan to its request, so /start only runs what was previewed."""

    def __init__(self) -> None:
        self._key = _secrets.token_bytes(32)

    def sign(self, request: dict) -> str:
        body = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self._key, body, hashlib.sha256).hexdigest()

    def verify(self, request: dict, token: str) -> bool:
        return isinstance(token, str) and hmac.compare_digest(self.sign(request), token)


# ── Jobs ─────────────────────────────────────────────────────────────────────

MAX_LINES = 4000


class Job:
    def __init__(self, label: str, lab: str, action: str, plan_: dict) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.label = label
        self.lab = lab
        self.action = action
        self.command = plan_["display"]
        self.state = "running"
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.exit_code: int | None = None
        self.error: str | None = None
        self.truncated = False
        self.lines: list[str] = []
        self.proc: subprocess.Popen | None = None
        self.cancelled = False

    def to_dict(self, logs: bool = False) -> dict:
        d = {"id": self.id, "label": self.label, "lab": self.lab, "action": self.action, "command": self.command,
             "state": self.state, "startedAt": self.started_at, "finishedAt": self.finished_at,
             "exitCode": self.exit_code, "error": self.error, "truncated": self.truncated, "lines": len(self.lines)}
        if logs:
            d["logs"] = list(self.lines)
        return d


class JobService:
    def __init__(self, root: str) -> None:
        self.root = root
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def list(self) -> list[dict]:
        import source_jobs
        with self.lock:
            source_jobs.recover(self)
            return [j.to_dict() for j in sorted(self.jobs.values(), key=lambda j: j.started_at, reverse=True)]

    def get(self, job_id: str) -> Job | None:
        self.list()
        return self.jobs.get(job_id)

    def start(self, plan_: dict) -> Job:
        if not plan_.get("runnable"):
            raise PlanError("This action must be run in a terminal: " + (plan_.get("manualCommand") or ""))
        import source_jobs
        with self.lock:
            source_jobs.recover(self)
            busy = [j for j in self.jobs.values() if j.lab == plan_["lab"] and (j.state == "running" or j.proc is not None)]
            if busy:
                raise PlanError(f"Wait for the running {busy[0].label} job on this lab to finish")
            job = Job(f"{LABS[plan_['lab']]['label']} · {ACTION_INFO[plan_['action']][0]}", plan_["lab"], plan_["action"], plan_)
            if job.lab == "source":
                job.source_lock = source_jobs.claim(self.root)
            self.jobs[job.id] = job
            if job.lab == "source":
                try:
                    source_jobs.save(self)
                except Exception:
                    source_jobs.release(job.source_lock)
                    self.jobs.pop(job.id, None)
                    raise
            # Keep the 50 most recent jobs
            for old in sorted(self.jobs.values(), key=lambda j: j.started_at)[:-50]:
                if old.state != "running":
                    self.jobs.pop(old.id, None)
        try:
            threading.Thread(target=self._run, args=(job, plan_), daemon=True).start()
        except RuntimeError as e:
            job.state = "failed"
            job.error = f"Could not start the job worker: {e}"
            job.finished_at = time.time()
            if job.lab == "source":
                try:
                    source_jobs.save(self)
                finally:
                    source_jobs.release(job.source_lock)
                    job.source_lock = None
        return job

    def _run(self, job: Job, plan_: dict) -> None:
        timer: threading.Timer | None = None
        redact: list[str] = []
        try:
            redact = secret_values(self.root)
            env = dict(os.environ, NO_COLOR="1", TERM="dumb", PYTHONUNBUFFERED="1")
            if job.lab == "source" and job.action != "runtime" and not env.get("IQ_SESSION_HMAC_KEY") and not env.get("IQ_SESSION_HMAC_KEY_FILE"):
                import source_control
                key = source_control.checked(source_control.storage(self.root), "control/session-hmac.key")
                if key.is_file():
                    env["IQ_SESSION_HMAC_KEY_FILE"] = str(key)
            popen_kw: dict = {}
            if os.name == "posix":
                popen_kw["start_new_session"] = True
                if job.lab == "source":
                    popen_kw["pass_fds"] = (job.source_lock,)
            else:
                popen_kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if job.cancelled:
                job.state = "cancelled"
                return
            job.proc = subprocess.Popen([plan_["program"]] + plan_["args"], cwd=self.root, env=env,
                                        stdin=subprocess.PIPE if job.lab == "source" else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        bufsize=1, text=True, encoding="utf-8", errors="replace", **popen_kw)
            timer = threading.Timer(plan_["timeoutSec"], self._timeout, args=(job,))
            timer.daemon = True
            timer.start()
            if job.cancelled:
                self._signal(job)
            assert job.proc.stdout is not None
            discard_line = False
            log_bytes = 0
            while True:
                line = job.proc.stdout.readline(8193)
                if not line:
                    break
                if len(line) > 8192 or discard_line:
                    discard_line = not line.endswith("\n")
                    job.truncated = True
                    if not discard_line:
                        job.lines.append("[oversized log line omitted]")
                    continue
                line = redact_text(self.root, ANSI.sub("", line.rstrip("\r\n")), redact)
                job.lines.append(line)
                log_bytes += len(line)
                if job.lab == "source":
                    while log_bytes > 1024 * 1024 and job.lines:
                        log_bytes -= len(job.lines.pop(0))
                        job.truncated = True
                if len(job.lines) > MAX_LINES:
                    del job.lines[: len(job.lines) - MAX_LINES]
                    job.truncated = True
            job.exit_code = job.proc.wait()
            if job.state == "running":
                job.state = "cancelled" if job.cancelled else ("succeeded" if job.exit_code == 0 else "failed")
                if job.state == "failed":
                    job.error = f"Command exited with status {job.exit_code}. See output below."
        except Exception as e:
            if job.state == "running":
                job.state = "failed"
            if job.proc and job.proc.poll() is None:
                self._signal(job)
                try:
                    job.exit_code = job.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    job.proc.kill()
                    job.exit_code = job.proc.wait()
            error = str(e)
            for value in redact:
                error = error.replace(value, "[redacted]")
            job.error = error or type(e).__name__
        finally:
            if timer:
                timer.cancel()
            job.finished_at = time.time()
            if job.lab == "source":
                import source_jobs
                try:
                    source_jobs.save(self)
                except (OSError, ValueError):
                    job.error = "Could not save the private Source job record; inspect storage permissions."
                    if job.state == "succeeded":
                        job.state = "failed"
                finally:
                    source_jobs.release(job.source_lock)
                    job.source_lock = None
            if job.proc and job.proc.stdin:
                job.proc.stdin.close()
            job.proc = None

    def _timeout(self, job: Job) -> None:
        if job.state == "running" and job.proc:
            job.state = "timed-out"
            job.error = "Timed out"
            self._signal(job)

    def cancel(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        if getattr(job, "external", False) and job.state == "running":
            raise PlanError("This Source job is owned by another console process")
        if job.state == "running":
            job.cancelled = True
            if job.proc:
                self._signal(job)
        return job

    @staticmethod
    def _signal(job: Job) -> None:
        proc = job.proc
        if not proc:
            return
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
        except (OSError, ProcessLookupError, subprocess.SubprocessError):
            pass
        if os.name == "posix":
            def force():
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
            timer = threading.Timer(2, force)
            timer.daemon = True
            timer.start()


# ── Monitor ──────────────────────────────────────────────────────────────────

def _json_lines(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            data = json.loads(text)
            return data if isinstance(data, list) else []
        except ValueError:
            return []
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def monitor(root: str, lab: str, host: dict | None = None) -> dict:
    """Container state and resource use for a lab (docker or podman on this host)."""
    if lab not in LABS:
        raise PlanError("Unknown lab")
    if lab == "source":
        import source_control
        return {"lab": lab, "state": source_control.readiness(root)["state"], "containers": [],
                "note": "Native Python analysis; no containers."}
    host = host or host_info(root)
    names = LABS[lab]["containers"]
    runtime = host["runtime"]
    if host["os"] == "windows":
        return {"lab": lab, "state": "unknown", "note": "On Windows the lab runs inside WSL2; run Status or Snapshot.", "containers": []}
    if not names:
        return {"lab": lab, "state": "unknown", "note": "This lab runs natively; use Status.", "containers": []}
    if not runtime:
        return {"lab": lab, "state": "no-runtime", "note": "No working Docker or Podman engine with Compose is available.", "containers": []}
    fmt = ["--format", "json"] if runtime == "podman" else ["--format", "{{json .}}"]
    code, out = _capture([runtime, "ps", "-a"] + fmt, timeout=8)
    if code != 0:
        return {"lab": lab, "state": "error", "note": out.strip()[:300] or "The container runtime did not answer.", "containers": []}
    containers = {}
    for row in _json_lines(out):
        raw = row.get("Names")
        row_names = raw if isinstance(raw, list) else str(raw or "").split(",")
        for name in row_names:
            name = name.strip().lstrip("/")
            if name in names:
                ports = row.get("Ports")
                if isinstance(ports, list):
                    ports = ", ".join(f"{p.get('host_ip') or '0.0.0.0'}:{p.get('host_port')}→{p.get('container_port')}"
                                      for p in ports if isinstance(p, dict) and p.get("host_port"))
                containers[name] = {"name": name, "state": str(row.get("State") or "").lower(),
                                    "status": row.get("Status") or "", "ports": ports or "", "cpu": "—", "memory": "—"}
    running = [n for n, c in containers.items() if c["state"] == "running"]
    if running:
        code, out = _capture([runtime, "stats", "--no-stream"] + fmt + running, timeout=10)
        if code == 0:
            for row in _json_lines(out):
                name = str(row.get("Name") or row.get("name") or "").lstrip("/")
                if name in containers:
                    containers[name]["cpu"] = row.get("CPUPerc") or row.get("cpu_percent") or row.get("CPU") or "—"
                    containers[name]["memory"] = row.get("MemUsage") or row.get("mem_usage") or "—"
    rows = [containers.get(n) or {"name": n, "state": "absent", "status": "not created", "ports": "", "cpu": "—", "memory": "—"}
            for n in names]
    overall = "running" if running and len(running) == len(rows) else "partial" if running else "stopped"
    return {"lab": lab, "state": overall, "runtime": runtime, "containers": rows, "checkedAt": time.time()}
