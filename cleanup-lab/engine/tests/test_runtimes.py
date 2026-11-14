"""CLN-29 tests: Xcode simulator runtimes, Android AVDs and system images.

The ``xcrun`` and ``avdmanager`` answers are recorded fixtures kept inline;
every probe is an injectable fake ``run`` and every tree is generated under
``tempfile`` — never a real user folder and never a real probe (rule 8).
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import runtimes  # noqa: E402

ROOT = str(pathlib.Path(__file__).resolve().parents[3])

# A recorded `xcrun simctl runtime list -j` answer (trimmed): two runtimes,
# the second without a runtimeBundlePath.
SIMCTL_RUNTIMES_FIXTURE = """{
  "runtimes" : {
    "com.apple.CoreSimulator.SimRuntime.iOS-17-4" : {
      "bundleIdentifier" : "com.apple.CoreSimulator.SimRuntime.iOS-17-4",
      "build" : "21E215",
      "platform" : "iOS",
      "runtimeIdentifier" : "com.apple.CoreSimulator.SimRuntime.iOS-17-4",
      "identifier" : "iOS-17-4",
      "version" : "17.4",
      "name" : "iOS 17.4",
      "supportedDeviceRuntimes" : [
        "com.apple.CoreSimulator.SimRuntime.iOS-17-4"
      ],
      "state" : "Ready",
      "runtimeBundlePath" : "__BUNDLE_PATH__",
      "available" : true,
      "isInternal" : false,
      "isUnavailable" : false,
      "supportedArchitectures" : [
        "arm64"
      ],
      "doesNotSupportOnboarding" : false,
      "usesDeviceRuntime" : true
    },
    "com.apple.CoreSimulator.SimRuntime.watchOS-10-4" : {
      "bundleIdentifier" : "com.apple.CoreSimulator.SimRuntime.watchOS-10-4",
      "build" : "21T215",
      "platform" : "watchOS",
      "runtimeIdentifier" : "com.apple.CoreSimulator.SimRuntime.watchOS-10-4",
      "identifier" : "watchOS-10-4",
      "version" : "10.4",
      "name" : "watchOS 10.4",
      "supportedDeviceRuntimes" : [
        "com.apple.CoreSimulator.SimRuntime.watchOS-10-4"
      ],
      "state" : "Ready",
      "available" : true,
      "isInternal" : false,
      "isUnavailable" : false,
      "supportedArchitectures" : [
        "arm64"
      ],
      "doesNotSupportOnboarding" : false,
      "usesDeviceRuntime" : true
    }
  }
}
"""

# A recorded `avdmanager list avd` answer (trimmed): two loadable AVDs and one
# from the "could not be loaded" section.
AVDMANAGER_TEXT = """Available Android Virtual Devices:
    Name: Pixel_7_API_34
    Path: {pixel}
          Based on: Android 14 ("UpsideDownCake") Tag/ABI: google_apis
---------
    Name: Watch_API_33
    Path: {watch}
          Based on: Android 13 ("Tiramisu") Tag/ABI: android-wear
---------
The following Android Virtual Devices could not be loaded:
    Name: Gallery
    Path: {gallery}
    Error: This AVD's configuration file is missing
"""


class RuntimesCase(unittest.TestCase):
    """A generated home tree plus a generated stand-in for the repo root."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cln-runtimes-")
        self.home = self.temp.name
        self.env = {"HOME": self.home, "USERPROFILE": self.home}
        self.repo = os.path.join(self.home, "repo")
        self.devices = os.path.join(self.home, "Library", "Developer",
                                    "CoreSimulator", "Devices")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, body=b"x"):
        target = os.path.join(self.home, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(body)
        return target

    def configure_roots(self):
        os.makedirs(os.path.join(self.repo, "cleanup-lab"))
        with open(os.path.join(self.repo, "cleanup-lab", "simulator-roots.json"),
                  "w", encoding="utf-8") as handle:
            json.dump({"macos": self.devices}, handle)

    def fake_run(self, stdout="", returncode=0, stderr="", exc=None):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if exc is not None:
                raise exc
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

        run.calls = calls
        return run

    def assert_probe_call(self, fake, argv):
        self.assertEqual(fake.calls[0][0], argv)
        self.assertFalse(fake.calls[0][1]["shell"])
        self.assertTrue(fake.calls[0][1]["capture_output"])
        self.assertTrue(fake.calls[0][1]["text"])
        self.assertEqual(fake.calls[0][1]["timeout"], 5)
        self.assertFalse(fake.calls[0][1]["check"])


class XcodeRuntimeTests(RuntimesCase):
    def bundle(self, relative, files=(("runtime.cfg", b"12345"),
                                      ("Resources/info.plist", b"abc"))):
        for name, body in files:
            self.write(os.path.join(relative, name), body)
        return os.path.join(self.home, relative)

    def fixture(self, bundle_path):
        return SIMCTL_RUNTIMES_FIXTURE.replace("__BUNDLE_PATH__", bundle_path)

    def test_non_macos_refuses_honestly(self):
        self.configure_roots()
        result = runtimes.xcode_runtimes(self.repo, platform="linux", env=self.env,
                                         run=self.fake_run())
        self.assertEqual(result, {"available": False,
                                  "reason": "Xcode simulator runtimes require macOS",
                                  "items": []})

    def test_recorded_fixture_lists_two_runtimes_and_walks_the_inside_path(self):
        self.configure_roots()
        bundle = self.bundle("Library/Developer/CoreSimulator/Devices/"
                             "Runtimes/iOS 17.4.simruntime")
        fake = self.fake_run(stdout=self.fixture(bundle))
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env, run=fake)
        self.assertEqual(len(fake.calls), 1)
        self.assert_probe_call(fake, ["xcrun", "simctl", "runtime", "list", "-j"])
        self.assertTrue(result["available"])
        self.assertIsNone(result["reason"])
        self.assertEqual([item["id"] for item in result["items"]],
                         ["com.apple.CoreSimulator.SimRuntime.iOS-17-4",
                          "com.apple.CoreSimulator.SimRuntime.watchOS-10-4"])
        first = result["items"][0]
        self.assertEqual(first["kind"], "xcode-runtime")
        self.assertEqual(first["name"], "iOS 17.4")
        self.assertEqual(first["build"], "21E215")
        self.assertEqual(first["platform"], "iOS")
        self.assertEqual(first["path"], bundle)
        self.assertEqual(first["sizeBytes"], 8)  # 5 + 3 apparent bytes
        self.assertEqual(first["unreadable"], 0)
        self.assertFalse(first["inUse"])
        self.assertTrue(first["deletable"])
        self.assertNotIn("note", first)
        second = result["items"][1]  # the runtime without a runtimeBundlePath
        self.assertEqual(second["name"], "watchOS 10.4")
        self.assertIsNone(second["path"])
        self.assertIsNone(second["sizeBytes"])
        self.assertIsNone(second["sizeOnDiskBytes"])

    def test_the_shipped_simulator_roots_file_configures_the_allowed_root(self):
        bundle = self.bundle("Library/Developer/CoreSimulator/Devices/"
                             "Runtimes/iOS.simruntime")
        result = runtimes.xcode_runtimes(ROOT, platform="macos", env=self.env,
                                         run=self.fake_run(stdout=self.fixture(bundle)))
        self.assertNotIn("note", result["items"][0])
        self.assertEqual(result["items"][0]["sizeBytes"], 8)

    def test_a_bare_map_without_the_wrapper_is_accepted(self):
        self.configure_roots()
        bundle = self.bundle("Library/Developer/CoreSimulator/Devices/"
                             "Runtimes/iOS.simruntime")
        bare = json.loads(self.fixture(bundle))["runtimes"]
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(stdout=json.dumps(bare)))
        self.assertTrue(result["available"])
        self.assertEqual([item["id"] for item in result["items"]],
                         ["com.apple.CoreSimulator.SimRuntime.iOS-17-4",
                          "com.apple.CoreSimulator.SimRuntime.watchOS-10-4"])
        self.assertEqual(result["items"][0]["sizeBytes"], 8)

    def test_garbage_and_wrong_shapes_are_honest(self):
        self.configure_roots()
        for stdout, expected in [("not json", "invalid JSON"), ("[1, 2]", "unexpected JSON shape"),
                                 ('{"runtimes": [1]}', "unexpected JSON shape")]:
            result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                             run=self.fake_run(stdout=stdout))
            self.assertFalse(result["available"])
            self.assertIn(expected, result["reason"])
            self.assertEqual(result["items"], [])

    def test_failed_probe_and_missing_binary_are_honest(self):
        self.configure_roots()
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(returncode=1, stderr="boom"))
        self.assertEqual(result, {"available": False, "reason": "boom", "items": []})
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(returncode=1, stderr=""))
        self.assertEqual(result["reason"], "simctl failed")
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(exc=FileNotFoundError("xcrun")))
        self.assertFalse(result["available"])
        self.assertIn("xcrun", result["reason"])
        self.assertEqual(result["items"], [])
        expired = subprocess.TimeoutExpired(cmd="xcrun", timeout=5)
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(exc=expired))
        self.assertFalse(result["available"])

    def test_a_path_outside_the_configured_roots_carries_a_note(self):
        self.configure_roots()
        outside = self.bundle("outside/Foo.simruntime")
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(stdout=self.fixture(outside)))
        first = result["items"][0]
        self.assertTrue(result["available"])
        self.assertIsNone(first["sizeBytes"])
        self.assertEqual(first["note"], "outside the configured simulator roots")

    def test_a_missing_or_corrupt_roots_file_refuses_sizes(self):
        outside = self.bundle("anything/iOS.simruntime")
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(stdout=self.fixture(outside)))
        self.assertTrue(result["available"])
        self.assertEqual(result["items"][0]["note"],
                         "the configured simulator roots cannot be read")
        self.assertIsNone(result["items"][0]["sizeBytes"])
        os.makedirs(os.path.join(self.repo, "cleanup-lab"), exist_ok=True)
        with open(os.path.join(self.repo, "cleanup-lab", "simulator-roots.json"),
                  "w", encoding="utf-8") as handle:
            handle.write("{not json")
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(stdout=self.fixture(outside)))
        self.assertEqual(result["items"][0]["note"],
                         "the configured simulator roots cannot be read")

    def test_malformed_entries_are_skipped(self):
        self.configure_roots()
        data = {"runtimes": {"bad": "not an object",
                             "com.apple.CoreSimulator.SimRuntime.iOS-17-4": {"name": "iOS 17.4"}}}
        result = runtimes.xcode_runtimes(self.repo, platform="macos", env=self.env,
                                         run=self.fake_run(stdout=json.dumps(data)))
        self.assertEqual([item["id"] for item in result["items"]],
                         ["com.apple.CoreSimulator.SimRuntime.iOS-17-4"])


class AndroidAvdTests(RuntimesCase):
    def test_avdmanager_text_lists_three_avds_and_locks_mark_in_use(self):
        pixel_dir = os.path.dirname(self.write("Android-avd/Pixel_7_API_34.avd/data", b"12345"))
        self.write("Android-avd/Pixel_7_API_34.avd/multiinstance.lock")
        watch_dir = os.path.dirname(self.write("Android-avd/Watch_API_33.avd/data", b"abcd"))
        gallery_dir = os.path.dirname(self.write("Android-avd/Gallery.avd/data", b"xy"))
        self.write("Android-avd/Gallery.avd.lock")  # a sibling lock
        self.env["ANDROID_AVD_HOME"] = os.path.join(self.home, "Android-avd")
        text = AVDMANAGER_TEXT.format(pixel=pixel_dir, watch=watch_dir, gallery=gallery_dir)
        fake = self.fake_run(stdout=text)
        result = runtimes.android_avds(self.repo, platform="linux", env=self.env, run=fake)
        self.assertEqual(len(fake.calls), 1)
        self.assert_probe_call(fake, ["avdmanager", "list", "avd"])
        self.assertTrue(result["available"])  # the avdmanager probe answered
        self.assertIn("was not found", result["reason"])  # the SDK probe did not
        avds = result["items"]
        self.assertEqual([item["kind"] for item in avds], ["avd", "avd", "avd"])
        self.assertEqual([item["id"] for item in avds],
                         ["Pixel_7_API_34", "Watch_API_33", "Gallery"])
        self.assertEqual([item["path"] for item in avds], [pixel_dir, watch_dir, gallery_dir])
        self.assertEqual([item["inUse"] for item in avds], [True, False, True])
        self.assertEqual([item["sizeBytes"] for item in avds], [6, 4, 2])
        self.assertEqual(avds[0]["basedOn"],
                         'Android 14 ("UpsideDownCake") Tag/ABI: google_apis')
        self.assertIsNone(avds[2]["basedOn"])
        self.assertTrue(all(item["deletable"] for item in avds))

    def test_the_avd_home_fills_a_missing_path_and_refuses_a_relative_override(self):
        custom = os.path.join(self.home, "custom-avd")
        no_path_dir = os.path.dirname(self.write("custom-avd/NoPath.avd/data", b"abc"))
        default_dir = os.path.dirname(self.write(".android/avd/Home.avd/data", b"z"))
        self.env["ANDROID_AVD_HOME"] = custom
        result = runtimes.android_avds(
            self.repo, platform="macos", env=self.env,
            run=self.fake_run(stdout="    Name: NoPath\n          Based on: Android 14\n"))
        avd = [item for item in result["items"] if item["kind"] == "avd"][0]
        self.assertEqual(avd["path"], no_path_dir)  # filled from ANDROID_AVD_HOME
        self.assertEqual(avd["sizeBytes"], 3)
        self.assertEqual(avd["basedOn"], "Android 14")
        # A relative override is refused; the default home answers instead.
        self.env["ANDROID_AVD_HOME"] = "relative-avd"
        result = runtimes.android_avds(self.repo, platform="macos", env=self.env,
                                       run=self.fake_run(stdout="    Name: Home\n"))
        avd = [item for item in result["items"] if item["kind"] == "avd"][0]
        self.assertEqual(avd["path"], default_dir)
        self.assertEqual(avd["sizeBytes"], 1)

    def test_missing_avdmanager_and_sdk_are_honest(self):
        fake = self.fake_run(exc=FileNotFoundError("avdmanager"))
        result = runtimes.android_avds(self.repo, platform="linux", env=self.env, run=fake)
        self.assertFalse(result["available"])
        self.assertIn("avdmanager", result["reason"])
        self.assertIn("was not found", result["reason"])
        self.assertEqual(result["items"], [])

    def test_a_failing_avdmanager_still_lets_the_sdk_answer(self):
        self.env["ANDROID_SDK_ROOT"] = os.path.join(self.home, "sdk")
        self.write("sdk/system-images/android-34/google_apis/arm64-v8a/system.img", b"0123456789")
        result = runtimes.android_avds(self.repo, platform="linux", env=self.env,
                                       run=self.fake_run(returncode=1,
                                                         stderr="Error while loading AVD"))
        self.assertTrue(result["available"])
        self.assertIn("Error while loading AVD", result["reason"])
        images = [item for item in result["items"] if item["kind"] == "system-image"]
        self.assertEqual([item["id"] for item in images], ["android-34/google_apis/arm64-v8a"])
        self.assertEqual(images[0]["sizeBytes"], 10)

    def test_system_images_are_walked_with_ids_relative_to_system_images(self):
        self.env["ANDROID_SDK_ROOT"] = os.path.join(self.home, "sdk")
        self.write("sdk/system-images/android-34/google_apis/arm64-v8a/system.img", b"0123456789")
        self.write("sdk/system-images/android-34/google_apis/arm64-v8a/build.prop", b"prop")
        self.write("sdk/system-images/android-35/aosp_atd/x86_64/system.img", b"xy")
        outside = self.write("outside/keep.bin", b"precious")
        os.symlink(outside, os.path.join(self.home, "sdk/system-images/android-34/"
                                                "google_apis/arm64-v8a/link.bin"))
        result = runtimes.android_avds(self.repo, platform="linux", env=self.env,
                                       run=self.fake_run(stdout=""))  # no AVDs
        self.assertTrue(result["available"])
        self.assertIsNone(result["reason"])  # both probes answered
        images = [item for item in result["items"] if item["kind"] == "system-image"]
        self.assertEqual([item["id"] for item in images],
                         ["android-34/google_apis/arm64-v8a", "android-35/aosp_atd/x86_64"])
        by_id = {item["id"]: item for item in images}
        self.assertEqual(by_id["android-34/google_apis/arm64-v8a"]["sizeBytes"], 14)
        self.assertEqual(by_id["android-35/aosp_atd/x86_64"]["sizeBytes"], 2)
        self.assertFalse(images[0]["inUse"])
        self.assertTrue(images[0]["deletable"])
        self.assertTrue(os.path.exists(outside))  # the link was never followed
        self.assertNotIn("android-34/google_apis", [item["id"] for item in images])

    def test_missing_sdk_root_and_the_macos_default_location(self):
        self.env["ANDROID_SDK_ROOT"] = os.path.join(self.home, "missing-sdk")
        result = runtimes.android_avds(self.repo, platform="linux", env=self.env,
                                       run=self.fake_run(exc=FileNotFoundError("avdmanager")))
        self.assertFalse(result["available"])
        self.assertIn("missing-sdk", result["reason"])
        self.env.pop("ANDROID_SDK_ROOT")
        self.write("Library/Android/sdk/system-images/android-33/default/arm64-v8a/system.img",
                   b"1234")
        result = runtimes.android_avds(self.repo, platform="macos", env=self.env,
                                       run=self.fake_run(stdout=""))
        self.assertTrue(result["available"])
        images = [item for item in result["items"] if item["kind"] == "system-image"]
        self.assertEqual([item["id"] for item in images], ["android-33/default/arm64-v8a"])

    def test_the_size_walk_never_follows_links_and_counts_a_hard_link_once(self):
        avd_dir = os.path.dirname(self.write(".android/avd/Hard.avd/one.bin", b"12345"))
        try:
            os.link(os.path.join(avd_dir, "one.bin"), os.path.join(avd_dir, "hard.bin"))
        except OSError:
            self.skipTest("hard links are not supported here")
        self.write(".android/avd/Hard.avd/nested/two.bin", b"abcd")
        outside = self.write("Library/keep.bin", b"precious")
        os.symlink(outside, os.path.join(avd_dir, "link.bin"))
        text = "    Name: Hard\n    Path: {0}\n".format(avd_dir)
        result = runtimes.android_avds(self.repo, platform="macos", env=self.env,
                                       run=self.fake_run(stdout=text))
        avd = [item for item in result["items"] if item["kind"] == "avd"][0]
        self.assertEqual(avd["sizeBytes"], 9)  # 5 + 4: the hard link once, the symlink never
        self.assertTrue(os.path.exists(outside))
        with open(outside, "rb") as handle:
            self.assertEqual(handle.read(), b"precious")
        if not hasattr(os.stat_result, "st_blocks"):
            return
        self.assertIsNotNone(avd["sizeOnDiskBytes"])
        self.assertEqual(avd["sizeOnDiskBytes"] % 512, 0)

    def test_an_unreadable_branch_is_counted_not_fatal(self):
        if os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0:
            self.skipTest("needs a non-root POSIX account")
        avd_dir = os.path.dirname(self.write(".android/avd/Locked.avd/readable", b"123"))
        locked = os.path.join(avd_dir, "locked")
        self.write(".android/avd/Locked.avd/locked/secret", b"zz")
        os.chmod(locked, 0o000)
        try:
            text = "    Name: Locked\n    Path: {0}\n".format(avd_dir)
            result = runtimes.android_avds(self.repo, platform="macos", env=self.env,
                                           run=self.fake_run(stdout=text))
            avd = [item for item in result["items"] if item["kind"] == "avd"][0]
            self.assertEqual(avd["sizeBytes"], 3)  # the readable file still counts
            self.assertGreaterEqual(avd["unreadable"], 1)
        finally:
            os.chmod(locked, 0o700)  # let TemporaryDirectory clean up


if __name__ == "__main__":
    unittest.main()
