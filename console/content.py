"""Signed content packs: data that updates between app releases.

What can change without a new app release is data: the Firewall Lab companies, the catalog,
the knowledge guides, templates and the legal documents. The Frida hook scripts can too, but
they run inside other processes, so they are a separate class that is only installed when the
person asks for it.

How it stays safe (see lat.md/content.md):

* `scripts/build-content.py` lists every file with its SHA-256 in `manifest.json` and signs the
  manifest with an Ed25519 key that is not in the repository. The matching public key is
  `PUBLIC_KEY` below.
* This module downloads the manifest, checks the signature before it believes anything in it,
  then downloads the pack and checks every file against the manifest. A file that is not listed,
  has the wrong hash or size, or has an unsafe path rejects the whole update.
* Nothing is installed in place. The verified files are staged, then swapped in; the bundled
  copy is never modified, so `reset()` always returns to what shipped with the app.
* An older manifest than the installed one is refused (no downgrade replay).
* The only network access is the two downloads, only when `check()` or `update()` is called.

Ed25519 verification is pure Python (RFC 8032), so the console needs nothing beyond the
standard library.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import posixpath
import shutil
import tarfile
import sys
import time
import urllib.request
from typing import Callable, Optional

DEFAULT_URL = "https://github.com/keyvanarasteh/os-lab/releases/download/content-latest"
# Ed25519 public key (raw, base64) that content manifests must be signed with.
PUBLIC_KEY = "JdxTXvLEaxIROSVC/ODFJv0IaYhivKc+fCcLqPC2CgU="

MANIFEST = "manifest.json"
SIGNATURE = "manifest.json.sig"
SCHEMA = 1
MAX_MANIFEST = 2 * 1024 * 1024
MAX_PACK = 32 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024

# Where each class may live. build-content.py applies the same rules; both sides check them.
CLASSES = {
    "data": (
        "firewall-lab/companies/",
        "firewall-lab/catalog.json",
        "firewall-lab/catalog.md",
        "firewall-lab/schema/",
        "firewall-lab/knowledge/",
        "firewall-lab/templates/",
        "ios-lab/knowledge/",
        "docs/legal/",
    ),
    "hooks": ("android-lab/lab/hooks/",),
}
DATA_SUFFIXES = (".json", ".md", ".txt", ".yml", ".yaml")
HOOK_SUFFIXES = (".js",)


class ContentError(Exception):
    """A content update that must not be applied (bad signature, hash, path, size, ...)."""


# --- Ed25519 verification (RFC 8032, section 6) ------------------------------------------------

_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> Optional[int]:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s: int, point):
    result = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            result = _add(result, point)
        point = _add(point, point)
        s >>= 1
    return result


def _equal(a, b) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _decompress(raw: bytes):
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def ed25519_verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True when `signature` is a valid Ed25519 signature of `message` under `public`."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    r = _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _Q
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))


# --- paths and manifests -----------------------------------------------------------------------

def classify(rel: str) -> Optional[str]:
    """The class a repo-relative path may belong to, or None when it is not allowed at all."""
    if not rel or rel.startswith("/") or "\\" in rel or "\0" in rel:
        return None
    if posixpath.normpath(rel) != rel or any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    for cls, roots in CLASSES.items():
        suffixes = HOOK_SUFFIXES if cls == "hooks" else DATA_SUFFIXES
        for root in roots:
            under = rel == root or (root.endswith("/") and rel.startswith(root))
            if under and rel.endswith(suffixes):
                return cls
    return None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_manifest(raw: bytes) -> dict:
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ContentError(f"The manifest is not valid JSON: {e}") from e
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ContentError("The manifest has an unsupported schema.")
    if not isinstance(manifest.get("sequence"), int) or isinstance(manifest.get("sequence"), bool):
        raise ContentError("The manifest has no sequence number.")
    files = manifest.get("files")
    pack = manifest.get("pack")
    if not isinstance(files, list) or not files or not isinstance(pack, dict):
        raise ContentError("The manifest lists no files or no pack.")
    seen = set()
    for f in files:
        if not isinstance(f, dict):
            raise ContentError("A manifest entry is malformed.")
        rel, cls = f.get("path"), f.get("class")
        digest, size = f.get("sha256"), f.get("size")
        if not isinstance(rel, str) or classify(rel) != cls:
            raise ContentError(f"The manifest lists a path that is not allowed: {rel!r}")
        if rel in seen:
            raise ContentError(f"The manifest lists {rel} twice.")
        seen.add(rel)
        if not (isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)):
            raise ContentError(f"Bad hash for {rel}.")
        if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= MAX_FILE:
            raise ContentError(f"Bad size for {rel}.")
    if not isinstance(pack.get("sha256"), str) or not isinstance(pack.get("name"), str) or "/" in pack["name"]:
        raise ContentError("The manifest's pack entry is malformed.")
    return manifest


def default_fetch(url: str, limit: int) -> bytes:
    """GET `url` over HTTPS, refusing anything larger than `limit` bytes."""
    if not url.startswith("https://"):
        raise ContentError("Content is only downloaded over HTTPS.")
    request = urllib.request.Request(url, headers={"User-Agent": "os-lab-content"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 (https only, checked above)
            data = response.read(limit + 1)
    except OSError as e:
        raise ContentError(f"Could not download {url}: {e}") from e
    if len(data) > limit:
        raise ContentError(f"{url} is larger than {limit} bytes.")
    return data


# --- the store ---------------------------------------------------------------------------------

class ContentStore:
    """The downloaded overlay in `content_dir`, on top of the bundled files in `bundled_root`."""

    def __init__(
        self,
        content_dir: str,
        bundled_root: str,
        base_url: Optional[str] = None,
        public_key: Optional[str] = None,
        fetch: Optional[Callable[[str, int], bytes]] = None,
    ):
        self.dir = os.path.abspath(content_dir)
        self.root = os.path.abspath(bundled_root)
        self.base_url = (base_url or os.environ.get("OSLAB_CONTENT_URL") or DEFAULT_URL).rstrip("/")
        self.public_key = base64.b64decode(public_key or PUBLIC_KEY)
        self.fetch = fetch or default_fetch
        self.files_dir = os.path.join(self.dir, "files")
        self.state_path = os.path.join(self.dir, "state.json")

    # state --------------------------------------------------------------------------------

    def offline(self) -> bool:
        return os.environ.get("OSLAB_CONTENT_OFFLINE", "") not in ("", "0")

    def state(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                state = json.load(f)
            if not isinstance(state, dict):
                raise ValueError
        except (OSError, ValueError):
            state = {}
        installed = bool(state.get("installed")) and os.path.isdir(self.files_dir)
        return {
            "installed": installed,
            "version": state.get("version") if installed else None,
            "sequence": state.get("sequence", 0) if installed else 0,
            "hooks": bool(state.get("hooks")) if installed else False,
            "updatedAt": state.get("updatedAt") if installed else None,
            "fileCount": state.get("fileCount", 0) if installed else 0,
            "latest": state.get("latest"),
            "checkedAt": state.get("checkedAt"),
            "offline": self.offline(),
            "source": self.base_url,
        }

    def _save(self, **changes) -> None:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                state = json.load(f)
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError):
            state = {}
        state.update(changes)
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, self.state_path)

    # network ------------------------------------------------------------------------------

    def _manifest(self) -> dict:
        if self.offline():
            raise ContentError("Content updates are switched off (OSLAB_CONTENT_OFFLINE).")
        raw = self.fetch(f"{self.base_url}/{MANIFEST}", MAX_MANIFEST)
        sig_text = self.fetch(f"{self.base_url}/{SIGNATURE}", 4096)
        try:
            signature = base64.b64decode(sig_text.strip(), validate=True)
        except ValueError as e:
            raise ContentError("The manifest signature is not valid base64.") from e
        if not ed25519_verify(self.public_key, raw, signature):
            raise ContentError("The manifest signature does not match: the update was not signed by the os-lab content key.")
        return parse_manifest(raw)

    def check(self) -> dict:
        """Fetch and verify the latest manifest; report whether it is newer. Installs nothing."""
        manifest = self._manifest()
        counts = {"data": 0, "hooks": 0}
        for f in manifest["files"]:
            counts[f["class"]] += 1
        latest = {
            "version": manifest.get("version"),
            "sequence": manifest["sequence"],
            "commit": manifest.get("commit"),
            "generated": manifest.get("generated"),
            "files": counts,
        }
        self._save(latest=latest, checkedAt=int(time.time()))
        state = self.state()
        state["updateAvailable"] = manifest["sequence"] > state["sequence"]
        return state

    def update(self, include_hooks: bool = False) -> dict:
        """Download, verify and install the latest pack. `include_hooks` also installs the hooks class."""
        manifest = self._manifest()
        installed = self.state()
        if installed["installed"] and manifest["sequence"] < installed["sequence"]:
            raise ContentError("The published content is older than what is installed; refusing to go back.")
        wanted = {f["path"]: f for f in manifest["files"] if f["class"] == "data" or include_hooks}
        pack_name = manifest["pack"]["name"]
        pack = self.fetch(f"{self.base_url}/{pack_name}", MAX_PACK)
        if sha256_hex(pack) != manifest["pack"]["sha256"]:
            raise ContentError("The downloaded pack does not match the signed manifest.")

        staging = os.path.join(self.dir, f"staging-{os.getpid()}")
        shutil.rmtree(staging, ignore_errors=True)
        try:
            self._extract(pack, wanted, staging)
            old = os.path.join(self.dir, "files.old")
            shutil.rmtree(old, ignore_errors=True)
            if os.path.isdir(self.files_dir):
                os.replace(self.files_dir, old)
            os.replace(staging, self.files_dir)
            shutil.rmtree(old, ignore_errors=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        self._save(
            installed=True,
            version=manifest.get("version"),
            sequence=manifest["sequence"],
            hooks=bool(include_hooks),
            updatedAt=int(time.time()),
            fileCount=len(wanted),
        )
        return self.check_state_after_update()

    def check_state_after_update(self) -> dict:
        state = self.state()
        state["updateAvailable"] = False
        return state

    @staticmethod
    def _extract(pack: bytes, wanted: dict, staging: str) -> None:
        got = set()
        try:
            archive = tarfile.open(fileobj=io.BytesIO(pack), mode="r:gz")
        except (tarfile.TarError, OSError, EOFError) as e:
            raise ContentError(f"The pack is not a readable archive: {e}") from e
        with archive:
            for member in archive:
                if not member.isfile():
                    raise ContentError(f"The pack contains something that is not a plain file: {member.name}")
                entry = wanted.get(member.name)
                if entry is None:
                    if classify(member.name) is None:
                        raise ContentError(f"The pack contains a path that is not allowed: {member.name}")
                    continue  # a listed file of a class that was not asked for
                if member.name in got:
                    raise ContentError(f"The pack contains {member.name} twice.")
                if member.size != entry["size"] or member.size > MAX_FILE:
                    raise ContentError(f"{member.name} has the wrong size.")
                handle = archive.extractfile(member)
                data = handle.read(MAX_FILE + 1) if handle else b""
                if len(data) != entry["size"] or sha256_hex(data) != entry["sha256"]:
                    raise ContentError(f"{member.name} does not match the signed manifest.")
                target = os.path.join(staging, *member.name.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as out:
                    out.write(data)
                got.add(member.name)
        missing = sorted(set(wanted) - got)
        if missing:
            raise ContentError(f"The pack is missing {len(missing)} listed file(s), e.g. {missing[0]}.")

    def reset(self) -> dict:
        """Forget every downloaded file and go back to the bundled copy."""
        shutil.rmtree(self.files_dir, ignore_errors=True)
        self._save(installed=False, version=None, sequence=0, hooks=False, fileCount=0)
        return self.state()

    # reading ------------------------------------------------------------------------------

    def _overlay(self, rel: str) -> Optional[str]:
        cls = classify(rel)
        if cls is None or not self.state()["installed"]:
            return None
        if cls == "hooks" and not self.state()["hooks"]:
            return None
        path = os.path.join(self.files_dir, *rel.split("/"))
        real = os.path.realpath(path)
        if os.path.commonpath([os.path.realpath(self.files_dir), real]) != os.path.realpath(self.files_dir):
            return None
        return real if os.path.isfile(real) else None

    def resolve(self, rel: str) -> Optional[str]:
        """The file to read for `rel`: the downloaded copy if there is one, else the bundled one."""
        if classify(rel) is None:
            return None
        overlay = self._overlay(rel)
        if overlay:
            return overlay
        path = os.path.realpath(os.path.join(self.root, *rel.split("/")))
        if os.path.commonpath([os.path.realpath(self.root), path]) != os.path.realpath(self.root):
            return None
        return path if os.path.isfile(path) else None

    def read_text(self, rel: str) -> Optional[str]:
        path = self.resolve(rel)
        if not path:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def _companies_base(self) -> tuple:
        state = self.state()
        overlay = os.path.join(self.files_dir, "firewall-lab", "companies")
        if state["installed"] and os.path.isdir(overlay):
            return overlay, "downloaded"
        return os.path.join(self.root, "firewall-lab", "companies"), "bundled"

    def companies(self) -> dict:
        """Every company.json: from the downloaded pack when installed, else from the bundle."""
        base, source = self._companies_base()
        found = []
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                path = os.path.join(base, name, "company.json")
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, encoding="utf-8") as f:
                        company = json.load(f)
                except (OSError, ValueError):
                    continue
                if isinstance(company, dict) and company.get("slug") == name and isinstance(company.get("branches"), list):
                    found.append(company)
        state = self.state()
        return {"companies": found, "source": source, "version": state["version"]}

    def hooks(self) -> list:
        """The hook scripts to show: the downloaded ones when installed with hooks, else the bundled ones."""
        hooks_dir = os.path.join(self.root, "android-lab", "lab", "hooks")
        source = hooks_dir
        state = self.state()
        overlay = os.path.join(self.files_dir, "android-lab", "lab", "hooks")
        if state["installed"] and state["hooks"] and os.path.isdir(overlay):
            source = overlay
        found = []
        if os.path.isdir(source):
            for name in sorted(os.listdir(source)):
                full = os.path.join(source, name)
                if name.endswith(".js") and os.path.isfile(full):
                    with open(full, encoding="utf-8", errors="replace") as f:
                        found.append({"name": name, "path": f"hooks/{name}", "code": f.read(65536)})
        return found


def default_content_dir() -> str:
    explicit = os.environ.get("OSLAB_CONTENT_DIR")
    if explicit:
        return explicit
    return os.path.join(os.path.expanduser("~"), ".oslab", "content")


def main(argv=None) -> int:
    """`python3 console/content.py status|check|update [--hooks]|reset` (same store the console uses)."""
    import argparse

    ap = argparse.ArgumentParser(prog="content.py", description="Signed content packs for os-lab.")
    ap.add_argument("action", choices=["status", "check", "update", "reset"])
    ap.add_argument("--hooks", action="store_true", help="with update: also install the Frida hook scripts")
    args = ap.parse_args(argv)
    root = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    store = ContentStore(default_content_dir(), root)
    try:
        result = {"status": store.state, "check": store.check, "reset": store.reset}.get(args.action)
        result = result() if result else store.update(include_hooks=args.hooks)
    except ContentError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
