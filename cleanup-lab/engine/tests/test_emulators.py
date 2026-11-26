"""CLA-01 typed Android emulator cleanup against a fake avdmanager."""
import os
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cleanup_lab import emulators  # noqa: E402

ROOT = str(pathlib.Path(__file__).resolve().parents[3])


class FakeAvdManager:
    def __init__(self, tool):
        self.tool = tool
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert kwargs["shell"] is False
        self.calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")


class EmulatorCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        home = pathlib.Path(self.temp.name)
        self.avd = home / ".android" / "avd"
        self.avd.mkdir(parents=True)
        self._write_avd("Pixel_7", target="android-34", size=5, available=True)
        self._write_avd("Missing_8", target="android-28", size=0, available=False)
        self._write_avd("Running_9", target="android-34", size=3, available=True, lock=True)
        bindir = home / "bin"
        bindir.mkdir()
        tool = bindir / "avdmanager"
        tool.write_text("#!/bin/sh\n", encoding="utf-8")
        tool.chmod(0o755)
        self.tool = str(tool)
        self.env = {"HOME": str(home), "PATH": str(bindir), "USERPROFILE": str(home)}
        self.fake = FakeAvdManager(self.tool)
        self.kw = {"platform": "linux", "env": self.env, "process_list": []}

    def tearDown(self):
        self.temp.cleanup()

    def _write_avd(self, name, *, target, size, available, lock=False):
        folder = self.avd / (name + ".avd")
        if available:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "userdata-qemu.img").write_bytes(b"x" * size)
            (folder / "snapshots").mkdir(exist_ok=True)
            (folder / "snapshots" / "snap.bin").write_bytes(b"s")
            if lock:
                (folder / "hardware-qemu.ini.lock").mkdir()
        (self.avd / (name + ".ini")).write_text(
            "target={0}\npath={1}\n".format(target, folder), encoding="utf-8")

    def test_actions_are_fixed_and_unselected(self):
        listed = emulators.actions()
        self.assertEqual({item["id"] for item in listed}, set(emulators.ACTIONS))
        self.assertTrue(all(not item["defaultSelected"] for item in listed))

    def test_inventory_lists_ini_files_and_lock_as_running(self):
        report = emulators.inventory(**self.kw)
        self.assertTrue(report["available"])
        by_id = {item["id"]: item for item in report["devices"]}
        self.assertTrue(by_id["Pixel_7"]["available"])
        self.assertEqual(by_id["Pixel_7"]["state"], "Shutdown")
        self.assertGreater(by_id["Pixel_7"]["sizeBytes"], 0)
        self.assertFalse(by_id["Missing_8"]["available"])
        self.assertEqual(by_id["Running_9"]["state"], "Running")

    def test_android_avd_home_override(self):
        other = pathlib.Path(self.temp.name) / "other-avd"
        other.mkdir()
        (other / "Tablet.ini").write_text("target=android-33\npath={0}\n".format(other / "Tablet.avd"), encoding="utf-8")
        (other / "Tablet.avd").mkdir()
        (other / "Tablet.avd" / "cache.img").write_bytes(b"yy")
        env = {**self.env, "ANDROID_AVD_HOME": str(other)}
        report = emulators.inventory(platform="linux", env=env, process_list=[])
        self.assertEqual(report["source"], "env:ANDROID_AVD_HOME")
        self.assertEqual([item["id"] for item in report["devices"]], ["Tablet"])

    def test_windows_default_uses_userprofile(self):
        report = emulators.inventory(platform="windows", env=self.env, process_list=[])
        self.assertTrue(report["available"])
        self.assertIn("Pixel_7", {item["id"] for item in report["devices"]})

    def test_delete_unavailable_previews_then_runs_fixed_argv(self):
        plan = emulators.preview(ROOT, "emulators.delete-unavailable", **self.kw)
        self.assertEqual(plan.device_ids, ("Missing_8",))
        self.assertEqual(plan.argv[0], "avdmanager")
        result = emulators.execute(ROOT, plan, run=self.fake, **self.kw)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["kind"], "emulators")
        self.assertEqual(self.fake.calls, [[self.tool, "delete", "avd", "-n", "Missing_8"]])

    def test_wipe_selected_shutdown_avd(self):
        plan = emulators.preview(ROOT, "emulators.wipe-data", ["Pixel_7"], **self.kw)
        emulators.execute(ROOT, plan, run=self.fake, **self.kw)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse((self.avd / "Pixel_7.avd" / "userdata-qemu.img").exists())
        self.assertFalse((self.avd / "Pixel_7.avd" / "snapshots").exists())
        self.assertTrue((self.avd / "Pixel_7.ini").exists())

    def test_running_avd_is_refused(self):
        with self.assertRaisesRegex(emulators.EmulatorError, "Shut down Running_9"):
            emulators.preview(ROOT, "emulators.delete-avds", ["Running_9"], **self.kw)

    def test_invalid_selection_is_refused(self):
        for ids in (None, [], ["../x"], ["Pixel_7", "Pixel_7"], ["no such"]):
            with self.assertRaises(emulators.EmulatorError):
                emulators.preview(ROOT, "emulators.delete-avds", ids, **self.kw)
        with self.assertRaises(emulators.EmulatorError):
            emulators.preview(ROOT, "emulators.delete-unavailable", ["Pixel_7"], **self.kw)
        with self.assertRaises(emulators.EmulatorError):
            emulators.preview(ROOT, "emulators.rm-rf", **self.kw)

    def test_changed_avds_never_run(self):
        plan = emulators.preview(ROOT, "emulators.delete-avds", ["Pixel_7"], **self.kw)
        (self.avd / "Pixel_7.avd" / "hardware-qemu.ini.lock").mkdir()
        with self.assertRaises(emulators.EmulatorError):
            emulators.execute(ROOT, plan, run=self.fake, **self.kw)
        self.assertEqual(self.fake.calls, [])

    def test_expired_preview_never_runs(self):
        plan = emulators.preview(ROOT, "emulators.delete-unavailable", clock=lambda: 0, **self.kw)
        with self.assertRaisesRegex(emulators.EmulatorError, "expired"):
            emulators.execute(ROOT, plan, run=self.fake, clock=lambda: 601, **self.kw)
        self.assertEqual(self.fake.calls, [])

    def test_delete_refuses_without_avdmanager(self):
        env = {**self.env, "PATH": str(pathlib.Path(self.temp.name) / "empty")}
        (pathlib.Path(self.temp.name) / "empty").mkdir(exist_ok=True)
        with self.assertRaisesRegex(emulators.EmulatorError, "avdmanager"):
            emulators.preview(ROOT, "emulators.delete-unavailable", platform="linux", env=env, process_list=[])


if __name__ == "__main__":
    unittest.main()
