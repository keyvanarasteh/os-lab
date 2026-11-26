"""CLA-02 emulator storage: saved destination, location states and suggestions."""
import os
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cleanup_lab import emulator_storage as storage  # noqa: E402
ROOT = str(pathlib.Path(__file__).resolve().parents[3])
GIB = 1024 ** 3


class EmulatorStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.temp.name)
        self.home = base / "home"
        self.avd = self.home / ".android" / "avd"
        self.avd.mkdir(parents=True)
        self.sdk = self.home / "Android" / "Sdk"
        self.sdk.mkdir(parents=True)
        self.external = base / "Volumes" / "Fast"
        self.external.mkdir(parents=True)
        self.env = {"HOME": str(self.home), "OSLAB_CLEANUP_STATE": str(base / "state")}
        self.rows = [
            {"mountPoint": "/", "kind": "root", "isHome": True, "freeBytes": 5 * GIB, "totalBytes": 500 * GIB},
            {"mountPoint": str(self.external), "name": "Fast", "kind": "removable", "isHome": False,
             "freeBytes": 900 * GIB, "totalBytes": 1000 * GIB},
            {"mountPoint": "/net", "kind": "unknown", "isHome": False, "freeBytes": 1, "totalBytes": 2},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def status(self, platform="linux"):
        return storage.status(ROOT, platform=platform, env=self.env, inventory={"volumes": self.rows})

    def test_defaults_offer_other_volumes_only(self):
        report = self.status()
        self.assertTrue(report["available"])
        self.assertEqual(report["state"], "local")
        self.assertEqual(report["linkKind"], "symlink")
        self.assertEqual([d["mountPoint"] for d in report["destinations"]], [str(self.external)])
        self.assertEqual(report["suggestion"]["action"], "setup")

    def test_low_system_disk_suggests_move_to_saved_destination(self):
        storage.save({"destination": str(self.external)}, env=self.env, platform="linux",
                     destinations=[str(self.external)])
        report = self.status()
        self.assertEqual(report["suggestion"]["action"], "move")
        title, message = storage.notification(report)
        self.assertIn(str(self.external), message)
        self.assertIn("Android", title)
        self.rows[0]["freeBytes"] = 50 * GIB
        self.assertEqual(self.status()["suggestion"]["action"], "setup")

    def test_setup_does_not_notify(self):
        report = self.status()
        self.assertEqual(report["suggestion"]["action"], "setup")
        self.assertIsNone(storage.notification(report))

    def test_local_without_another_disk_has_no_suggestion(self):
        self.rows = [self.rows[0]]
        self.assertIsNone(self.status()["suggestion"]["action"])

    def test_linked_and_disconnected_states(self):
        store = self.external / "oslab-caches" / storage.ENTRY_ID
        store.mkdir(parents=True)
        self.avd.rmdir()
        self.avd.symlink_to(store)
        report = self.status()
        self.assertEqual(report["state"], "linked")
        self.assertEqual(report["volume"]["mountPoint"], str(self.external))
        store.rmdir()
        report = self.status()
        self.assertEqual(report["state"], "disk-missing")
        self.assertEqual(report["suggestion"]["action"], "reconnect")
        title, message = storage.notification(report)
        self.assertIn("Emulator disk", title)
        self.assertIn("Android Studio", message)

    def test_hidden_without_sdk_or_avd_folder(self):
        self.avd.rmdir()
        self.sdk.rmdir()
        self.sdk.parent.rmdir()
        report = self.status()
        self.assertFalse(report["available"])
        self.assertIn("No Android SDK", report["reason"])

    def test_sdk_without_avd_folder_is_available(self):
        self.avd.rmdir()
        report = self.status()
        self.assertTrue(report["available"])
        self.assertTrue(report["hasSdk"])
        self.assertEqual(report["state"], "missing")

    def test_windows_destination_and_volume(self):
        ok = storage.validate_config({"destination": "D:\\"}, platform="windows")
        self.assertEqual(ok["destination"], "D:\\")
        with self.assertRaises(storage.StorageConfigError):
            storage.validate_config({"destination": "/Volumes/Ext"}, platform="windows")
        with self.assertRaises(storage.StorageConfigError):
            storage.validate_config({"destination": "relative"}, platform="linux")
        row = storage._volume_of("D:\\oslab-caches\\simulators.android-avd",
                                 [{"mountPoint": "C:\\", "kind": "root"},
                                  {"mountPoint": "D:\\", "kind": "internal"}], "windows")
        self.assertEqual(row["mountPoint"], "D:\\")
        local = self.home / "AppData" / "Local" / "Android" / "Sdk"
        local.mkdir(parents=True)
        env = {**self.env, "USERPROFILE": str(self.home), "LOCALAPPDATA": str(self.home / "AppData" / "Local")}
        report = storage.status(ROOT, platform="windows", env=env, inventory={"volumes": [
            {"mountPoint": "C:\\", "kind": "root", "isHome": True, "freeBytes": 5 * GIB, "totalBytes": 500 * GIB},
            {"mountPoint": "D:\\", "name": "Data", "kind": "internal", "isHome": False,
             "freeBytes": 900 * GIB, "totalBytes": 1000 * GIB},
        ]})
        self.assertEqual(report["linkKind"], "junction")

    def test_config_validation(self):
        for bad in ({"destination": "relative"}, {"floorBytes": 1}, {"suggest": "yes"}, {"extra": 1}, []):
            with self.assertRaises(storage.StorageConfigError):
                storage.validate_config(bad, "linux")
        with self.assertRaises(storage.StorageConfigError):
            storage.save({"destination": "/Volumes/Other"}, env=self.env, platform="linux", destinations=["/x"])

    def test_corrupt_store_falls_back_to_defaults(self):
        path = pathlib.Path(self.env["OSLAB_CLEANUP_STATE"]) / storage.STORE
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        loaded = storage.load(self.env, "linux")
        self.assertEqual(loaded["config"], storage.default_config())
        self.assertTrue(loaded["configError"])


if __name__ == "__main__":
    unittest.main()
