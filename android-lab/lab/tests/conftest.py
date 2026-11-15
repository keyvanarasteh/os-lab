import os
import sys
import zipfile
import pytest

# Ensure lab directory and scripts directory are in sys.path
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
LAB_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
SCRIPTS_DIR = os.path.join(LAB_DIR, "scripts")

# Tests run offline: preflight must never download platform-tools from Google
os.environ.setdefault("OSLAB_NO_DOWNLOAD", "1")
# ...and must neither read nor write the real downloaded content, nor reach GitHub for it
os.environ.setdefault("OSLAB_CONTENT_DIR", os.path.join(__import__("tempfile").mkdtemp(prefix="oslab-content-test-"), "content"))
os.environ.setdefault("OSLAB_CONTENT_OFFLINE", "1")

for p in [LAB_DIR, SCRIPTS_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _normalize_windows_oslab_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normalize console/oslab POSIX-style path expectations when pytest runs on Windows."""
    if os.name != "nt":
        return
    for mod_name in ("oslab", "console.oslab"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        orig_scoped = getattr(mod, "_scoped", None)
        if callable(orig_scoped) and not getattr(orig_scoped, "_pent07_patched", False):
            def _posix_scoped(root: str, *parts: str, _fn=orig_scoped) -> str:
                return _fn(root, *parts).replace("\\", "/")
            _posix_scoped._pent07_patched = True  # type: ignore[attr-defined]
            monkeypatch.setattr(mod, "_scoped", _posix_scoped)

        orig_lab_config = getattr(mod, "lab_config", None)
        if callable(orig_lab_config) and not getattr(orig_lab_config, "_pent07_patched", False):
            def _posix_lab_config(root: str, lab: str, _fn=orig_lab_config) -> dict:
                cfg = _fn(root, lab)
                if isinstance(cfg, dict) and isinstance(cfg.get("path"), str):
                    cfg["path"] = cfg["path"].replace("\\", "/")
                return cfg
            _posix_lab_config._pent07_patched = True  # type: ignore[attr-defined]
            monkeypatch.setattr(mod, "lab_config", _posix_lab_config)


@pytest.fixture(scope="session")
def sample_apk(tmp_path_factory):
    """Generates a test APK fixture containing manifest and secrets for testing."""
    tmp_dir = tmp_path_factory.mktemp("apk_fixture")
    apk_path = os.path.join(str(tmp_dir), "fixture-test.apk")

    manifest_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        'package="com.testlab.fixture" android:versionCode="1" android:versionName="1.0">\n'
        '    <uses-permission android:name="android.permission.INTERNET"/>\n'
        '    <uses-permission android:name="android.permission.CAMERA"/>\n'
        '    <uses-permission android:name="android.permission.READ_SMS"/>\n'
        '    <application android:debuggable="true" android:allowBackup="true" '
        'android:usesCleartextTraffic="true" android:label="FixtureTest">\n'
        '        <activity android:name=".MainActivity" android:exported="true"/>\n'
        '        <activity android:name=".DeepLinkActivity" android:exported="true">\n'
        '            <intent-filter>\n'
        '                <action android:name="android.intent.action.VIEW"/>\n'
        '                <category android:name="android.intent.category.DEFAULT"/>\n'
        '                <data android:scheme="testlab" android:host="profile"/>\n'
        '            </intent-filter>\n'
        '        </activity>\n'
        '    </application>\n'
        '</manifest>'
    )

    strings_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<resources>\n'
        '    <string name="app_name">FixtureTest</string>\n'
        '    <string name="google_api_key">AIzaSyB_MockGoogleApiKey1234567890ABCDE</string>\n'
        '    <string name="firebase_db">https://testlab-db.firebaseio.com</string>\n'
        '    <string name="aws_key">AKIAIOSFODNN7EXAMPLE</string>\n'
        '    <string name="backend_url">http://api.insecure-internal.corp:8080/v1/auth</string>\n'
        '</resources>'
    )

    from build_dex import build_minimal_dex
    dex_bytes = build_minimal_dex()

    with zipfile.ZipFile(apk_path, "w") as z:
        z.writestr("AndroidManifest.xml", manifest_xml.encode("utf-8"))
        z.writestr("res/values/strings.xml", strings_xml.encode("utf-8"))
        z.writestr("classes.dex", dex_bytes)

    return apk_path
