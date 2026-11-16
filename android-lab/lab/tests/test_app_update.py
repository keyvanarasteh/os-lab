"""App update feed: platform pick, version compare, verified download and opener (console/app_update.py)."""
import hashlib
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "console"))
import app_update  # noqa: E402

FEED = "https://feed/latest.json"
ASSET = "https://github.com/keyvanarasteh/os-lab/releases/download/app-v0.2.8/os-lab_0.2.8_linux_amd64.AppImage"


def feed(version="0.2.8", url=ASSET):
    return json.dumps({"version": version, "platforms": {app_update.platform_key(): {"url": url, "signature": "sig"}}}).encode()


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("OSLAB_APP_KIND", "appimage")
    payload = b"new-appimage"
    digest = hashlib.sha256(payload).hexdigest()
    served = {
        FEED: feed(),
        ASSET: payload,
        ASSET + ".sha256": f"{digest}  os-lab_0.2.8_linux_amd64.AppImage\n".encode(),
    }
    opened = []

    def fetch(url, limit):
        if url not in served:
            raise app_update.AppUpdateError("404 " + url)
        return served[url]

    def opener(path, kind):
        opened.append((path, kind))

    store = app_update.AppUpdateStore(version="0.2.7", feed_url=FEED, fetch=fetch, opener=opener,
                                      download_dir=str(tmp_path / "downloads"))
    return store, opened, payload, served


def test_version_compare_orders_prereleases_before_releases():
    assert app_update.version_tuple("0.2.7") < app_update.version_tuple("0.2.8")
    assert app_update.version_tuple("0.2.8-rc1") < app_update.version_tuple("0.2.8")
    assert app_update.version_tuple("v0.10.0") > app_update.version_tuple("0.9.9")


def test_check_reports_the_newer_release(store):
    store, _, _, _ = store
    state = store.check()
    assert state["installed"] == "0.2.7"
    assert state["latest"] == "0.2.8"
    assert state["updateAvailable"] is True
    assert state["asset"]["name"] == "os-lab_0.2.8_linux_amd64.AppImage"
    assert state["releaseUrl"].endswith("/app-v0.2.8")


def test_check_hides_the_card_when_current(store):
    store, _, _, served = store
    served[FEED] = feed(version="0.2.7")
    assert store.check()["updateAvailable"] is False


def test_install_downloads_verifies_and_opens(store, tmp_path):
    store, opened, payload, _ = store
    store.check()
    assert store.install()["installing"] is True
    for _ in range(100):
        state = store.state()
        if state["install"] and state["install"]["phase"] in ("done", "error"):
            break
        import time

        time.sleep(0.01)
    assert state["install"]["phase"] == "done", state["install"]
    assert opened and opened[0][1] == "appimage"
    assert open(opened[0][0], "rb").read() == payload
    assert os.access(opened[0][0], os.X_OK)


def test_install_refuses_a_bad_checksum(store, tmp_path):
    store, opened, _, served = store
    served[ASSET + ".sha256"] = f"{'0' * 64}  os-lab_0.2.8_linux_amd64.AppImage\n".encode()
    store.check()
    store.install()
    for _ in range(100):
        state = store.state()
        if state["install"] and state["install"]["phase"] in ("done", "error"):
            break
        import time

        time.sleep(0.01)
    assert state["install"]["phase"] == "error"
    assert "SHA-256" in state["install"]["error"]
    assert not opened


def test_check_refuses_a_foreign_url(monkeypatch, tmp_path):
    monkeypatch.setenv("OSLAB_APP_KIND", "appimage")
    served = {FEED: feed(url="https://evil.example/os-lab.AppImage")}

    def fetch(url, limit):
        return served[url]

    store = app_update.AppUpdateStore(version="0.2.7", feed_url=FEED, fetch=fetch,
                                      download_dir=str(tmp_path))
    with pytest.raises(app_update.AppUpdateError):
        store.check()


def test_unsupported_without_a_running_version(monkeypatch):
    monkeypatch.delenv("OSLAB_APP_VERSION", raising=False)
    store = app_update.AppUpdateStore(version="")
    assert store.supported() is False
    assert store.state()["updateAvailable"] is False
