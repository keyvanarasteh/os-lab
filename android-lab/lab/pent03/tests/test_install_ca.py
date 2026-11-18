"""mitmproxy system-CA install tests — filename/path builders are pure; the
subject-hash step runs against a real self-signed cert generated with the
local openssl (no network)."""
import os
import shutil
import subprocess

import pytest

import install_ca as ic


def test_system_cert_filename_and_path():
    assert ic.system_cert_filename("c8750f0d") == "c8750f0d.0"
    assert ic.system_cert_path("c8750f0d") == (
        "/system/etc/security/cacerts/c8750f0d.0"
    )


def test_system_cert_filename_rejects_empty():
    with pytest.raises(ic.CaInstallError):
        ic.system_cert_filename("   ")


def test_default_ca_path_points_at_mitmproxy():
    p = ic.default_mitmproxy_ca_path()
    assert p.endswith(".mitmproxy/mitmproxy-ca-cert.pem")


@pytest.fixture
def self_signed_pem(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl not available")
    key = tmp_path / "k.pem"
    crt = tmp_path / "mitmproxy-ca-cert.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(crt), "-days", "1",
            "-subj", "/CN=mitmproxy/O=mitmproxy/OU=lab",
        ],
        check=True,
        capture_output=True,
    )
    return str(crt)


def test_subject_hash_old_real_cert(self_signed_pem):
    h = ic.subject_hash_old(self_signed_pem)
    assert len(h) == 8
    int(h, 16)  # it is a hex hash


def test_subject_hash_old_missing_file():
    with pytest.raises(ic.CaInstallError):
        ic.subject_hash_old("/no/such/cert.pem")


def test_prepare_cert_copies_to_hashed_name(self_signed_pem, tmp_path):
    out = ic.prepare_cert(self_signed_pem, "c8750f0d", str(tmp_path))
    assert out.endswith("c8750f0d.0")
    with open(out, "rb") as a, open(self_signed_pem, "rb") as b:
        assert a.read() == b.read()


def test_subject_hash_old_injected_runner():
    # No openssl needed: the runner is injectable. The path just has to exist.
    here = os.path.abspath(__file__)
    h = ic.subject_hash_old(here, runner=lambda argv: "deadbeef\n")
    assert h == "deadbeef"
