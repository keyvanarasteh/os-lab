"""Signed content packs: signature, hashes, paths, hooks gating, downgrade, reset (console/content.py)."""
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "console"))
import content  # noqa: E402

@pytest.fixture(autouse=True)
def online(monkeypatch):
    """conftest switches content updates off for the suite; these tests use an injected fetch."""
    monkeypatch.delenv("OSLAB_CONTENT_OFFLINE", raising=False)


needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


@pytest.fixture(scope="module")
def keypair(tmp_path_factory):
    d = tmp_path_factory.mktemp("keys")
    pem = d / "k.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(pem)], check=True, capture_output=True)
    der = subprocess.run(["openssl", "pkey", "-in", str(pem), "-pubout", "-outform", "DER"], check=True, capture_output=True).stdout
    return pem, base64.b64encode(der[-32:]).decode()


def openssl_sign(pem, data, tmp_path):
    src, dst = tmp_path / "m", tmp_path / "s"
    src.write_bytes(data)
    subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(pem), "-in", str(src), "-out", str(dst)], check=True, capture_output=True)
    return dst.read_bytes()


def build(files, sequence=5, pack_extra=None):
    """A manifest and pack for {path: bytes}; the class comes from content.classify."""
    entries = [
        {"path": p, "class": content.classify(p), "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
        for p, b in sorted(files.items())
    ]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for p, b in {**files, **(pack_extra or {})}.items():
            info = tarfile.TarInfo(p)
            info.size = len(b)
            tar.addfile(info, io.BytesIO(b))
    pack = raw.getvalue()
    manifest = {
        "schema": 1, "version": f"v{sequence}", "sequence": sequence, "commit": "abc",
        "pack": {"name": "content-pack.tar.gz", "size": len(pack), "sha256": hashlib.sha256(pack).hexdigest()},
        "files": entries,
    }
    return json.dumps(manifest).encode(), pack


FILES = {
    "firewall-lab/companies/acme/company.json": json.dumps({"slug": "acme", "branches": []}).encode(),
    "docs/legal/PRIVACY.md": b"# Privacy\n",
    "android-lab/lab/hooks/ssl.js": b"console.log('hook');\n",
}


@pytest.fixture
def store_for(tmp_path, keypair):
    pem, public = keypair
    bundled = tmp_path / "bundled"
    (bundled / "firewall-lab" / "companies" / "seed").mkdir(parents=True)
    (bundled / "firewall-lab" / "companies" / "seed" / "company.json").write_text(json.dumps({"slug": "seed", "branches": []}))
    (bundled / "android-lab" / "lab" / "hooks").mkdir(parents=True)
    (bundled / "android-lab" / "lab" / "hooks" / "old.js").write_text("// bundled")

    def make(manifest, pack, sign_with=None, tamper_manifest=False):
        sig = openssl_sign(sign_with or pem, manifest, tmp_path)
        served = manifest + b" " if tamper_manifest else manifest
        urls = {
            "https://x/manifest.json": served,
            "https://x/manifest.json.sig": base64.b64encode(sig),
            "https://x/content-pack.tar.gz": pack,
        }

        def fetch(url, limit):
            if url not in urls:
                raise content.ContentError("404 " + url)
            return urls[url]

        return content.ContentStore(str(tmp_path / "content"), str(bundled), "https://x", public, fetch)

    return make


def test_the_embedded_public_key_is_a_valid_point():
    assert len(base64.b64decode(content.PUBLIC_KEY)) == 32
    assert content._decompress(base64.b64decode(content.PUBLIC_KEY)) is not None


@needs_openssl
def test_ed25519_matches_openssl_and_rejects_tampering(keypair, tmp_path):
    pem, public = keypair
    msg = b"hello os-lab"
    sig = openssl_sign(pem, msg, tmp_path)
    pub = base64.b64decode(public)
    assert content.ed25519_verify(pub, msg, sig)
    assert not content.ed25519_verify(pub, msg + b"!", sig)
    assert not content.ed25519_verify(pub, msg, sig[:-1] + bytes([sig[-1] ^ 1]))
    assert not content.ed25519_verify(pub, msg, b"\0" * 64)
    assert not content.ed25519_verify(b"\0" * 31, msg, sig)


@pytest.mark.parametrize("rel,cls", [
    ("firewall-lab/companies/a/company.json", "data"),
    ("docs/legal/TERMS.md", "data"),
    ("android-lab/lab/hooks/x.js", "hooks"),
    ("android-lab/lab/hooks/x.json", None),
    ("firewall-lab/companies/a/run.sh", None),
    ("labctl", None),
    ("console/oslab.py", None),
    ("../etc/passwd", None),
    ("/etc/passwd", None),
    ("docs/legal/../../labctl", None),
    ("docs\\legal\\a.md", None),
])
def test_classify_allows_only_content_paths(rel, cls):
    assert content.classify(rel) == cls


@needs_openssl
def test_update_installs_data_but_not_hooks_by_default(store_for):
    store = store_for(*build(FILES))
    status = store.check()
    assert status["updateAvailable"] and status["latest"]["files"] == {"data": 2, "hooks": 1}
    state = store.update()
    assert state["installed"] and state["version"] == "v5" and not state["hooks"] and state["fileCount"] == 2
    assert [c["slug"] for c in store.companies()["companies"]] == ["acme"]
    assert store.companies()["source"] == "downloaded"
    assert store.read_text("docs/legal/PRIVACY.md") == "# Privacy\n"
    # hooks were not asked for: the bundled hook is still what is shown
    assert [h["name"] for h in store.hooks()] == ["old.js"]
    assert store.resolve("android-lab/lab/hooks/ssl.js") is None


@needs_openssl
def test_update_with_hooks_installs_them_and_dropping_them_removes_them(store_for):
    store = store_for(*build(FILES))
    assert store.update(include_hooks=True)["hooks"]
    assert [h["name"] for h in store.hooks()] == ["ssl.js"]
    assert not store.update(include_hooks=False)["hooks"]
    assert [h["name"] for h in store.hooks()] == ["old.js"]


@needs_openssl
def test_a_manifest_signed_with_another_key_is_rejected(store_for, tmp_path):
    other = tmp_path / "other.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(other)], check=True, capture_output=True)
    store = store_for(*build(FILES), sign_with=other)
    with pytest.raises(content.ContentError, match="signature"):
        store.update()
    assert not store.state()["installed"]


@needs_openssl
def test_a_tampered_manifest_is_rejected(store_for):
    store = store_for(*build(FILES), tamper_manifest=True)
    with pytest.raises(content.ContentError, match="signature"):
        store.check()


@needs_openssl
def test_a_file_that_differs_from_the_manifest_is_rejected_and_nothing_is_installed(store_for):
    manifest, _ = build(FILES)
    evil = dict(FILES)
    evil["docs/legal/PRIVACY.md"] = b"# Privacy\n"[:-1] + b"!"
    _, pack = build(evil)
    # the pack hash in the (signed) manifest no longer matches the swapped pack
    with pytest.raises(content.ContentError, match="pack does not match"):
        store_for(manifest, pack).update()
    # same pack hash but a wrong member: build a manifest around the evil pack, with a stale file hash
    m = json.loads(manifest)
    m["pack"]["sha256"] = hashlib.sha256(pack).hexdigest()
    store = store_for(json.dumps(m).encode(), pack)
    with pytest.raises(content.ContentError, match="does not match the signed manifest"):
        store.update()
    assert not store.state()["installed"]


@needs_openssl
def test_unlisted_unsafe_or_missing_members_are_rejected(store_for):
    for extra, expect in [
        ({"../evil.md": b"x"}, "not allowed"),
        ({"labctl": b"#!/bin/sh\n"}, "not allowed"),
    ]:
        manifest, pack = build(FILES, pack_extra=extra)
        with pytest.raises(content.ContentError, match=expect):
            store_for(manifest, pack).update()
    # a listed file that the pack lacks
    manifest, _ = build(FILES)
    short = dict(FILES)
    del short["docs/legal/PRIVACY.md"]
    _, pack = build(short)
    m = json.loads(manifest)
    m["pack"]["sha256"] = hashlib.sha256(pack).hexdigest()
    with pytest.raises(content.ContentError, match="missing"):
        store_for(json.dumps(m).encode(), pack).update()


@needs_openssl
def test_links_in_the_pack_are_rejected(store_for):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        link = tarfile.TarInfo("docs/legal/PRIVACY.md")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)
    pack = raw.getvalue()
    manifest, _ = build({"docs/legal/PRIVACY.md": b"x"})
    m = json.loads(manifest)
    m["pack"]["sha256"] = hashlib.sha256(pack).hexdigest()
    with pytest.raises(content.ContentError, match="not a plain file"):
        store_for(json.dumps(m).encode(), pack).update()


@needs_openssl
def test_an_older_manifest_than_the_installed_one_is_refused(store_for, tmp_path):
    newer = store_for(*build(FILES, sequence=9))
    newer.update()
    older = store_for(*build(FILES, sequence=4))
    with pytest.raises(content.ContentError, match="older"):
        older.update()
    assert older.state()["sequence"] == 9
    assert older.check()["updateAvailable"] is False


@needs_openssl
def test_reset_goes_back_to_the_bundled_copy(store_for):
    store = store_for(*build(FILES))
    store.update(include_hooks=True)
    state = store.reset()
    assert not state["installed"] and not state["hooks"]
    assert [c["slug"] for c in store.companies()["companies"]] == ["seed"]
    assert store.companies()["source"] == "bundled"
    assert [h["name"] for h in store.hooks()] == ["old.js"]


def test_offline_switch_blocks_the_network(tmp_path, monkeypatch):
    monkeypatch.setenv("OSLAB_CONTENT_OFFLINE", "1")
    called = []
    store = content.ContentStore(str(tmp_path / "c"), str(tmp_path), "https://x", content.PUBLIC_KEY, lambda u, n: called.append(u))
    with pytest.raises(content.ContentError, match="switched off"):
        store.check()
    assert not called


def test_downloads_must_be_https():
    with pytest.raises(content.ContentError, match="HTTPS"):
        content.default_fetch("http://example.com/manifest.json", 10)
    with pytest.raises(content.ContentError, match="HTTPS"):
        content.default_fetch("file:///etc/passwd", 10)


def test_read_text_cannot_leave_the_content_roots(tmp_path):
    (tmp_path / "secret.md").write_text("no")
    store = content.ContentStore(str(tmp_path / "c"), str(tmp_path), "https://x", content.PUBLIC_KEY, None)
    assert store.read_text("secret.md") is None
    assert store.read_text("docs/legal/../../secret.md") is None


def test_the_repo_content_builds_and_the_client_accepts_it():
    """build-content.py --check runs the client's own manifest validation on the real repo files."""
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build-content.py"), "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "data files" in out.stdout


def test_verify_content_report_runs_on_the_repo_files():
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "verify-content.py"), "--all"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "PASS: company manifests match the schema" in out.stdout
    assert "| `docs/legal/PRIVACY.md` | data |" in out.stdout


def test_content_cli_status_is_json_and_offline_safe(tmp_path):
    env = {**os.environ, "OSLAB_CONTENT_DIR": str(tmp_path / "c"), "OSLAB_CONTENT_OFFLINE": "1"}
    status = subprocess.run([sys.executable, os.path.join(ROOT, "console", "content.py"), "status"], capture_output=True, text=True, env=env)
    assert status.returncode == 0 and json.loads(status.stdout)["installed"] is False
    check = subprocess.run([sys.executable, os.path.join(ROOT, "console", "content.py"), "check"], capture_output=True, text=True, env=env)
    assert check.returncode == 1 and "switched off" in check.stderr
