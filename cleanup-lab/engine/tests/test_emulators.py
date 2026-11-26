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
USED = "system-images;android-34;google_apis;arm64-v8a"
UNUSED = "system-images;android-28;default;x86"


class FakeAvdManager:
    def __init__(self, tool):
        self.tool = tool
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert kwargs["shell"] is False
        self.calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")


class FakeSdkManager:
    def __init__(self, tool, packages):
        self.tool = tool
        self.packages = list(packages)
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert kwargs["shell"] is False
        self.calls.append(list(argv))
        if "--list_installed" in argv:
            lines = ["Installed packages:", "Path | Version | Description | Location"]
            for item in self.packages:
                lines.append("{id} | {version} | {name} | {location}".format(**item))
            return SimpleNamespace(returncode=0, stdout="\n".join(lines) + "\n", stderr="")
        if "--uninstall" in argv:
            package = argv[argv.index("--uninstall") + 1]
            self.packages = [item for item in self.packages if item["id"] != package]
            return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="unexpected")


class EmulatorCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        home = pathlib.Path(self.temp.name)
        self.avd = home / ".android" / "avd"
        self.avd.mkdir(parents=True)
        self._write_avd("Pixel_7", target="android-34", size=5, available=True, image=USED)
        self._write_avd("Missing_8", target="android-28", size=0, available=False)
        self._write_avd("Running_9", target="android-34", size=3, available=True, lock=True, image=USED)
        self.sdk = home / "Android" / "Sdk"
        self._write_image(USED, b"used-image")
        self._write_image(UNUSED, b"unused-image")
        bindir = home / "bin"
        bindir.mkdir()
        tool = bindir / "avdmanager"
        tool.write_text("#!/bin/sh\n", encoding="utf-8")
        tool.chmod(0o755)
        sdktool = bindir / "sdkmanager"
        sdktool.write_text("#!/bin/sh\n", encoding="utf-8")
        sdktool.chmod(0o755)
        self.tool = str(tool)
        self.sdktool = str(sdktool)
        self.env = {"HOME": str(home), "PATH": str(bindir), "USERPROFILE": str(home)}
        self.fake = FakeAvdManager(self.tool)
        self.packages = [
            {"id": USED, "version": "2", "name": "Google APIs ARM 64 v8a System Image",
             "location": "system-images/android-34/google_apis/arm64-v8a"},
            {"id": UNUSED, "version": "1", "name": "Intel x86 Atom System Image",
             "location": "system-images/android-28/default/x86"},
        ]
        self.sdk_fake = FakeSdkManager(self.sdktool, self.packages)
        self.kw = {"platform": "linux", "env": self.env, "process_list": []}

    def tearDown(self):
        self.temp.cleanup()

    def _write_avd(self, name, *, target, size, available, lock=False, image=None):
        folder = self.avd / (name + ".avd")
        if available:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "userdata-qemu.img").write_bytes(b"x" * size)
            (folder / "snapshots").mkdir(exist_ok=True)
            (folder / "snapshots" / "snap.bin").write_bytes(b"s")
            if lock:
                (folder / "hardware-qemu.ini.lock").mkdir()
            if image:
                (folder / "config.ini").write_text(
                    "image.sysdir.1={0}/\n".format(image.replace(";", "/")), encoding="utf-8")
        (self.avd / (name + ".ini")).write_text(
            "target={0}\npath={1}\n".format(target, folder), encoding="utf-8")

    def _write_image(self, package, payload):
        folder = self.sdk.joinpath(*package.split(";"))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "system.img").write_bytes(payload)

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

    def test_images_mark_unused_packages(self):
        report = emulators.images(platform="linux", env=self.env, run=self.sdk_fake)
        self.assertTrue(report["available"])
        by_id = {item["id"]: item for item in report["images"]}
        self.assertFalse(by_id[USED]["unused"])
        self.assertIn("Pixel_7", by_id[USED]["avds"])
        self.assertTrue(by_id[UNUSED]["unused"])
        self.assertGreater(by_id[UNUSED]["sizeBytes"], 0)

    def test_uninstall_unused_image_previews_then_runs(self):
        plan = emulators.preview(ROOT, "emulators.uninstall-images", [UNUSED], run=self.sdk_fake, **self.kw)
        self.assertEqual(plan.op, "uninstall")
        self.assertIn("--uninstall", plan.argv)
        self.assertIn(UNUSED, plan.argv)
        result = emulators.execute(ROOT, plan, run=self.sdk_fake, **self.kw)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["kind"], "emulators")
        self.assertTrue(any("--uninstall" in call and UNUSED in call for call in self.sdk_fake.calls))

    def test_uninstall_refuses_an_image_an_avd_still_uses(self):
        with self.assertRaisesRegex(emulators.EmulatorError, "still used"):
            emulators.preview(ROOT, "emulators.uninstall-images", [USED], run=self.sdk_fake, **self.kw)

    def test_uninstall_refuses_unknown_or_invalid_packages(self):
        for ids in (None, [], [USED, USED], ["system-images;nope"], ["../x"], ["platforms;android-34"]):
            with self.assertRaises(emulators.EmulatorError):
                emulators.preview(ROOT, "emulators.uninstall-images", ids, run=self.sdk_fake, **self.kw)

    def test_changed_images_never_run(self):
        plan = emulators.preview(ROOT, "emulators.uninstall-images", [UNUSED], run=self.sdk_fake, **self.kw)
        self.sdk_fake.packages = [item for item in self.sdk_fake.packages if item["id"] != UNUSED]
        with self.assertRaises(emulators.EmulatorError):
            emulators.execute(ROOT, plan, run=self.sdk_fake, **self.kw)

    def test_sysdir_backslash_maps_to_package(self):
        self.assertEqual(emulators._sysdir_to_package(r"system-images\android-34\google_apis\arm64-v8a\\"), USED)

    def test_windows_sdk_default_lists_images(self):
        local = pathlib.Path(self.env["HOME"]) / "AppData" / "Local" / "Android" / "Sdk"
        folder = local.joinpath(*UNUSED.split(";"))
        folder.mkdir(parents=True)
        (folder / "system.img").write_bytes(b"win")
        env = {**self.env, "USERPROFILE": self.env["HOME"], "LOCALAPPDATA": str(pathlib.Path(self.env["HOME"]) / "AppData" / "Local")}
        report = emulators.images(platform="windows", env=env, run=self.sdk_fake)
        self.assertTrue(report["available"])
        self.assertEqual(report["sdkRoot"], str(local))

    def test_list_installed_without_table_still_parses(self):
        def run(argv, **kwargs):
            return SimpleNamespace(returncode=0, stdout=UNUSED + "\nplatforms;android-34\n", stderr="")
        report = emulators.images(platform="linux", env=self.env, run=run)
        self.assertEqual([item["id"] for item in report["images"]], [UNUSED])


if __name__ == "__main__":
    unittest.main()
