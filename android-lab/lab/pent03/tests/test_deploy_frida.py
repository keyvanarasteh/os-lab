"""frida-server deploy tests — arch map + URL builders pure; fetch uses a
fake opener feeding a local xz payload, so no network is touched."""
import io
import lzma

import pytest

import deploy_frida as df


def test_frida_arch_mapping():
    assert df.frida_arch("arm64-v8a") == "arm64"
    assert df.frida_arch("armeabi-v7a") == "arm"
    assert df.frida_arch("x86_64") == "x86_64"
    assert df.frida_arch("X86") == "x86"


def test_frida_arch_unknown_raises():
    with pytest.raises(df.FridaDeployError):
        df.frida_arch("mips")


def test_asset_name_and_url():
    assert df.server_asset_name("16.5.9", "arm64") == (
        "frida-server-16.5.9-android-arm64.xz"
    )
    assert df.server_asset_name("v16.5.9", "arm64").startswith("frida-server-16.5.9")
    url = df.download_url("16.5.9", "x86_64")
    assert url.endswith("/16.5.9/frida-server-16.5.9-android-x86_64.xz")
    assert url.startswith("https://github.com/frida/frida/releases/download")


def _fake_opener(payload: bytes):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    def opener(url, timeout=0):
        return _Resp(payload)

    return opener


def test_fetch_server_decompresses(tmp_path):
    binary = b"\x7fELF-fake-frida-server"
    payload = lzma.compress(binary)
    opener = _fake_opener(payload)
    out = df.fetch_server("16.5.9", "arm64", str(tmp_path), opener=opener)
    with open(out, "rb") as fh:
        assert fh.read() == binary


def test_fetch_server_bad_xz_raises(tmp_path):
    opener = _fake_opener(b"not-an-xz-stream")
    with pytest.raises(df.FridaDeployError):
        df.fetch_server("16.5.9", "arm64", str(tmp_path), opener=opener)


def test_resolve_version_pinned_is_passthrough():
    assert df.resolve_version("16.5.9") == "16.5.9"
    assert df.resolve_version("v16.5.9") == "16.5.9"


def test_resolve_version_latest_reads_api():
    import json

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    def opener(url, timeout=0):
        assert "releases/latest" in url
        return _Resp(json.dumps({"tag_name": "16.6.0"}).encode())

    assert df.resolve_version("latest", opener=opener) == "16.6.0"


def test_start_server_command_detaches():
    cmd = df.start_server_command()
    assert cmd.startswith("nohup ")
    assert cmd.rstrip().endswith("&")
