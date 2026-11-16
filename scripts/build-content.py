#!/usr/bin/env python3
"""Build the signed content pack that installed apps download.

    scripts/build-content.py                       build into dist-content/, unsigned (local check)
    scripts/build-content.py --sign                ...and sign the manifest (key from the environment or secrets/)
    scripts/build-content.py --require-signature   fail when no key is available (CI)
    scripts/build-content.py --check               validate only: nothing is written

Output (dist-content/):
    manifest.json        every file with its SHA-256, size and class; sequence = commit count
    manifest.json.sig    base64 Ed25519 signature of manifest.json's exact bytes
    content-pack.tar.gz  the files at their repo-relative paths (reproducible: sorted, no timestamps)

Only git-tracked files are packed, and only what console/content.py allows (classify): data
files under the content roots, plus the Frida hooks as their own class. Nothing secret-looking
ever goes in. The signing key is an Ed25519 private key in PEM form, taken from
$OSLAB_CONTENT_SIGNING_KEY (the PEM text, for CI), $OSLAB_CONTENT_SIGNING_KEY_FILE, or
secrets/content/content-signing.pem. It never lives in the repository (secrets/ is git-ignored).
Signing needs the `openssl` command (3.0 or newer).
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "console"))
import content  # noqa: E402

OUT = ROOT / "dist-content"
PACK = "content-pack.tar.gz"
NEVER = [
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)config\.env$"),
    re.compile(r"\.local\.md$"),
    re.compile(r"\.(pem|key|p12|pfx|p8|keystore|jks)$", re.I),
    re.compile(r"(^|/)id_(rsa|ed25519|ecdsa)"),
    re.compile(r"(^|/)storage/"),
]
SECRET_TEXT = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|xox[baprs]-[A-Za-z0-9-]{20,}"
)


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout


def collect() -> list[dict]:
    tracked = [p for p in git("ls-files", "-z").split("\0") if p]
    files = []
    problems = []
    for rel in sorted(tracked):
        cls = content.classify(rel)
        if cls is None:
            continue
        if any(rx.search(rel) for rx in NEVER):
            problems.append(f"{rel}: looks like a secret file")
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > content.MAX_FILE:
            problems.append(f"{rel}: larger than {content.MAX_FILE} bytes")
            continue
        if cls == "data":
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                problems.append(f"{rel}: not UTF-8")
                continue
            if SECRET_TEXT.search(text):
                problems.append(f"{rel}: contains something that looks like a credential")
                continue
            if rel.endswith(".json"):
                try:
                    json.loads(text)
                except ValueError as e:
                    problems.append(f"{rel}: invalid JSON ({e})")
                    continue
        files.append({"path": rel, "class": cls, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    if problems:
        raise SystemExit("refusing to build:\n  " + "\n  ".join(problems))
    if not any(f["class"] == "data" for f in files):
        raise SystemExit("no content files found")
    return files


def make_pack(files: list[dict]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in files:
            data = (ROOT / f["path"]).read_bytes()
            info = tarfile.TarInfo(f["path"])
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def signing_key() -> tuple[Path | None, bool]:
    """(path to a PEM key, whether it is a temporary file to delete)."""
    pem = os.environ.get("OSLAB_CONTENT_SIGNING_KEY")
    if pem:
        handle = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
        os.chmod(handle.name, 0o600)
        handle.write(pem if pem.endswith("\n") else pem + "\n")
        handle.close()
        return Path(handle.name), True
    for candidate in (os.environ.get("OSLAB_CONTENT_SIGNING_KEY_FILE"), str(ROOT / "secrets" / "content" / "content-signing.pem")):
        if candidate and Path(candidate).is_file():
            return Path(candidate), False
    return None, False


def sign(manifest_bytes: bytes, key: Path) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp, "manifest.json"), Path(tmp, "sig")
        src.write_bytes(manifest_bytes)
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(src), "-out", str(dst)],
            check=True, capture_output=True,
        )
        return dst.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sign", action="store_true", help="sign the manifest when a key is available")
    ap.add_argument("--require-signature", action="store_true", help="fail when the manifest cannot be signed")
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    files = collect()
    pack = make_pack(files)
    try:
        sequence = int(git("rev-list", "--count", "HEAD").strip())
        commit = git("rev-parse", "--short", "HEAD").strip()
    except (subprocess.CalledProcessError, ValueError):
        sequence, commit = 0, "unknown"
    manifest = {
        "schema": content.SCHEMA,
        "version": f"{time.strftime('%Y.%m.%d', time.gmtime())}+{commit}",
        "sequence": sequence,
        "commit": commit,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pack": {"name": PACK, "size": len(pack), "sha256": hashlib.sha256(pack).hexdigest()},
        "files": files,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    content.parse_manifest(manifest_bytes)  # the client's own validation, on what we are about to publish

    counts = {c: sum(1 for f in files if f["class"] == c) for c in ("data", "hooks")}
    print(f"{counts['data']} data files, {counts['hooks']} hook files, pack {len(pack)} bytes, sequence {sequence}")
    if args.check:
        return 0

    signature = None
    if args.sign or args.require_signature:
        key, temporary = signing_key()
        try:
            if key is None:
                if args.require_signature:
                    print("error: no signing key (set OSLAB_CONTENT_SIGNING_KEY or add secrets/content/content-signing.pem)", file=sys.stderr)
                    return 1
                print("warning: no signing key found, manifest left unsigned", file=sys.stderr)
            else:
                signature = base64.b64encode(sign(manifest_bytes, key)) + b"\n"
                if not content.ed25519_verify(base64.b64decode(content.PUBLIC_KEY), manifest_bytes, base64.b64decode(signature)):
                    print("error: the signature does not verify against the public key in console/content.py (wrong key?)", file=sys.stderr)
                    return 1
        finally:
            if temporary and key:
                key.unlink(missing_ok=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_bytes(manifest_bytes)
    (out / PACK).write_bytes(pack)
    sig_path = out / "manifest.json.sig"
    if signature:
        sig_path.write_bytes(signature)
        print(f"signed: {sig_path}")
    else:
        sig_path.unlink(missing_ok=True)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
