"""App updates: detect the newest signed os-lab release and fetch its installer.

The desktop app's Tauri updater reads `app-updates/latest.json`, which lists one
signed bundle per platform. The dashboard is served by this console and has no
Tauri IPC, so this module reads the same feed for the running app version, and
can download the installer for this host, check its SHA-256 and hand it to the
operating system. Nothing is installed without that OS step.

The running app version and package kind come from the desktop app through
OSLAB_APP_VERSION and OSLAB_APP_KIND. When they are absent (the console is run
with `./labctl ui` in a browser) the feature reports itself as unsupported and
the dashboard shows no card.

Only the two GitHub release URLs below are downloaded, only when `check()` or
`install()` is called, and every download is size-limited.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Callable, Optional

DEFAULT_FEED = "https://github.com/keyvanarasteh/os-lab/releases/download/app-updates/latest.json"
RELEASE_DOWNLOADS = "https://github.com/keyvanarasteh/os-lab/releases/download/"
RELEASE_TAG = "https://github.com/keyvanarasteh/os-lab/releases/tag/"
MAX_FEED = 2 * 1024 * 1024
MAX_ASSET = 320 * 1024 * 1024
MAX_SHA = 4096

ASSET_NAMES = {
    "appimage": "os-lab_{version}_linux_{arch}.AppImage",
    "deb": "os-lab_{version}_linux_{arch}.deb",
    "rpm": "os-lab_{version}_linux_{arch}.rpm",
    "dmg": "os-lab_{version}_macos_universal.dmg",
    "exe": "os-lab_{version}_windows_x64-setup.exe",
}


class AppUpdateError(Exception):
    """An update that must not be used (bad feed, URL, hash, size, ...)."""


def default_fetch(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "os-lab-updater"})
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status != 200:
            raise AppUpdateError(f"{url} answered {response.status}")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise AppUpdateError(f"{url} is larger than {limit} bytes")
    return data


def _machine() -> str:
    import platform

    return platform.machine().lower()


def platform_key() -> Optional[str]:
    """The Tauri updater platform name for this host."""
    machine = _machine()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "darwin-aarch64" if arm else "darwin-x86_64"
    if sys.platform.startswith("win") or os.name == "nt":
        return "windows-x86_64"
    if sys.platform.startswith("linux"):
        return "linux-aarch64" if arm else "linux-x86_64"
    return None


def linux_arch() -> str:
    return "arm64" if _machine() in ("arm64", "aarch64") else "amd64"


def version_tuple(text: str) -> tuple:
    """Compare dotted versions; a pre-release suffix sorts before its release."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?", str(text or ""))
    if not match:
        raise AppUpdateError(f"Not a version: {text!r}")
    core = tuple(int(part) for part in match.group(1).split("."))
    return core + ((0,) if match.group(2) else (1,))


def package_kind() -> str:
    """How this app was installed, used to pick the right downloaded file."""
    explicit = os.environ.get("OSLAB_APP_KIND", "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if sys.platform == "darwin":
        return "dmg"
    if sys.platform.startswith("win") or os.name == "nt":
        return "exe"
    if sys.platform.startswith("linux"):
        return rpm_distribution() and "rpm" or "deb"
    return "unknown"


def rpm_distribution() -> bool:
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            text = handle.read().lower()
    except OSError:
        return False
    return any(marker in text for marker in ("rhel", "fedora", "centos", "suse", "rpm"))


def _safe_download_name(url: str) -> str:
    name = url.rsplit("/", 1)[-1]
    if not re.match(r"^[A-Za-z0-9._-]+$", name or ""):
        raise AppUpdateError("The release asset name is not safe.")
    return name


def _check_url(url: str) -> None:
    if not url.startswith(RELEASE_DOWNLOADS) or ".." in url:
        raise AppUpdateError("The update URL is not on the os-lab release downloads.")


def default_opener(path: str, kind: str) -> None:
    """Hand a verified installer to the operating system (never runs it directly)."""
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform.startswith("linux"):
        target = os.path.dirname(path) if kind == "appimage" else path
        subprocess.run(["xdg-open", target], check=False)
    else:
        raise AppUpdateError("Opening installers is not supported on this platform.")


class AppUpdateStore:
    """Read the updater feed, report updates and fetch the installer for this host."""

    def __init__(
        self,
        version: Optional[str] = None,
        feed_url: Optional[str] = None,
        fetch: Optional[Callable[[str, int], bytes]] = None,
        opener: Optional[Callable[[str, str], None]] = None,
        download_dir: Optional[str] = None,
    ) -> None:
        self.version = (version if version is not None else os.environ.get("OSLAB_APP_VERSION") or "").strip()
        self.feed_url = (feed_url or os.environ.get("OSLAB_APP_UPDATE_URL") or DEFAULT_FEED).rstrip("/")
        self.fetch = fetch or default_fetch
        self.opener = opener or default_opener
        self.download_dir = download_dir or os.environ.get("OSLAB_APP_UPDATE_DIR") or os.path.join(os.path.expanduser("~"), ".oslab", "app-updates")
        self.kind = package_kind()
        self._latest: Optional[str] = None
        self._release: Optional[dict] = None
        self._checked_at: Optional[int] = None
        self._install: Optional[dict] = None
        self._lock = threading.Lock()

    # state --------------------------------------------------------------------------------

    def offline(self) -> bool:
        return os.environ.get("OSLAB_APP_OFFLINE", "") not in ("", "0")

    def installed(self) -> Optional[str]:
        try:
            version_tuple(self.version)
        except AppUpdateError:
            return None
        return self.version.lstrip("v")

    def supported(self) -> bool:
        return bool(self.installed()) and platform_key() is not None

    def update_available(self) -> bool:
        try:
            return bool(self.installed() and self._latest and version_tuple(self._latest) > version_tuple(self.installed() or ""))
        except AppUpdateError:
            return False

    def state(self) -> dict:
        update = self.update_available()
        return {
            "installed": self.installed(),
            "latest": self._latest,
            "updateAvailable": update,
            "checkedAt": self._checked_at,
            "platform": platform_key(),
            "kind": self.kind,
            "releaseUrl": f"{RELEASE_TAG}app-v{self._latest}" if self._latest else None,
            "asset": self._release if update else None,
            "supported": self.supported(),
            "offline": self.offline(),
            "installing": bool(self._install and self._install.get("phase") in ("downloading", "opening")),
            "install": self._install,
        }

    # network ------------------------------------------------------------------------------

    def check(self) -> dict:
        if self.offline():
            raise AppUpdateError("App updates are switched off (OSLAB_APP_OFFLINE).")
        raw = self.fetch(self.feed_url, MAX_FEED)
        try:
            feed = json.loads(raw.decode("utf-8"))
            latest = str(feed["version"])
            platforms = feed["platforms"]
        except (ValueError, KeyError, TypeError) as error:
            raise AppUpdateError("The app update feed is not valid JSON.") from error
        version_tuple(latest)
        key = platform_key()
        entry = platforms.get(key) if isinstance(platforms, dict) and key else None
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            raise AppUpdateError(f"The update feed has no file for {key or 'this platform'}.")
        _check_url(entry["url"])
        self._latest = latest
        self._release = self._release_for(latest, entry["url"])
        self._checked_at = int(time.time())
        return self.state()

    def _release_for(self, latest: str, feed_url: str) -> dict:
        """Pick the installer that matches this host (the feed points at AppImage on Linux)."""
        base = f"{RELEASE_DOWNLOADS}app-v{latest}/"
        kind = self.kind
        if kind in ("deb", "rpm"):
            name = ASSET_NAMES[kind].format(version=latest, arch=linux_arch())
        elif kind == "appimage":
            name = ASSET_NAMES["appimage"].format(version=latest, arch=linux_arch())
        elif kind == "dmg":
            name = ASSET_NAMES["dmg"].format(version=latest, arch=linux_arch())
        elif kind == "exe":
            name = ASSET_NAMES["exe"].format(version=latest, arch=linux_arch())
        else:
            return {"name": _safe_download_name(feed_url), "url": feed_url}
        return {"name": name, "url": base + name}

    # install ------------------------------------------------------------------------------

    def install(self) -> dict:
        """Start downloading, verifying and opening the installer in the background."""
        if not self.update_available() or not self._release:
            raise AppUpdateError("No newer app version is available.")
        with self._lock:
            if self._install and self._install.get("phase") in ("downloading", "opening"):
                return self.state()
            self._install = {"phase": "downloading", "error": None, "path": None, "version": self._latest}
        threading.Thread(target=self._install_worker, daemon=True).start()
        return self.state()

    def _install_worker(self) -> None:
        try:
            asset = self._release or {}
            url, name = asset.get("url", ""), asset.get("name", "")
            _check_url(url)
            data = self.fetch(url, MAX_ASSET)
            digest = hashlib.sha256(data).hexdigest()
            checksum = self.fetch(url + ".sha256", MAX_SHA).decode("utf-8").strip()
            expected = checksum.split()[0].lower() if checksum else ""
            if not re.fullmatch(r"[0-9a-f]{64}", expected) or expected != digest:
                raise AppUpdateError("The downloaded update does not match its SHA-256 file.")
            os.makedirs(self.download_dir, exist_ok=True)
            path = os.path.join(self.download_dir, name)
            with open(path, "wb") as handle:
                handle.write(data)
            if self.kind == "appimage":
                os.chmod(path, 0o755)
            with self._lock:
                self._install = {"phase": "opening", "error": None, "path": path, "version": self._latest}
            self.opener(path, self.kind)
            with self._lock:
                self._install = {"phase": "done", "error": None, "path": path, "version": self._latest}
        except Exception as error:  # a failed update must never crash the console
            with self._lock:
                self._install = {"phase": "error", "error": str(error), "path": None, "version": self._latest}


def main(argv=None) -> int:
    """`python3 console/app_update.py status|check|install` (same store the console uses)."""
    import argparse

    parser = argparse.ArgumentParser(prog="app_update.py", description="os-lab app updates.")
    parser.add_argument("action", choices=["status", "check", "install"])
    parser.add_argument("--version", help="running app version (default: OSLAB_APP_VERSION)")
    args = parser.parse_args(argv)
    store = AppUpdateStore(version=args.version)
    try:
        result = store.check() if args.action == "check" else store.install() if args.action == "install" else store.state()
    except AppUpdateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
