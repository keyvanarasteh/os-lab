"""Local volume filtering and disk-pressure reports, with no real disk probes."""
import plistlib
import unittest
from types import SimpleNamespace

from cleanup_lab import volumes


def usage(mount):
    if mount in ("/home", "D:\\"):
        return SimpleNamespace(total=1000, free=100)
    return SimpleNamespace(total=1000, free=400)


class VolumeTests(unittest.TestCase):
    def test_linux_filters_pseudo_network_and_marks_home(self):
        mounts = "\n".join((
            "1 0 8:1 / / rw - ext4 /dev/sda1 rw",
            "2 1 8:2 / /home rw - ext4 /dev/sda2 rw",
            "3 1 0:2 / /proc rw - proc proc rw",
            "4 1 0:3 / /mnt/server rw - nfs server:/data rw",
        ))
        report = volumes.report(platform="linux", env={"HOME": "/home/ada"},
                                mountinfo=mounts, usage=usage,
                                removable_reader=lambda path: "0")
        self.assertEqual([row["mountPoint"] for row in report["volumes"]], ["/", "/home"])
        self.assertEqual(report["homeVolume"], "/home")
        self.assertTrue(report["volumes"][0]["root"])
        self.assertFalse(report["volumes"][0]["pressure"])
        self.assertTrue(report["volumes"][1]["pressure"])
        self.assertTrue(report["volumes"][1]["internal"])

    def test_macos_local_only_and_diskutil_flags(self):
        output = ("/dev/disk1s5 on / (apfs, local, read-only)\n"
                  "/dev/disk1s1 on /System/Volumes/Data (apfs, local)\n"
                  "/dev/disk1s2 on /System/Volumes/Preboot (apfs, local)\n"
                  "server on /Volumes/net (smbfs, nodev)")
        def runner(argv, **kwargs):
            self.assertEqual(argv[:3], ["diskutil", "info", "-plist"])
            return SimpleNamespace(returncode=0,
                                   stdout=plistlib.dumps({"Internal": True, "RemovableMedia": False}))
        report = volumes.report(platform="macos", env={"HOME": "/Users/ada"},
                                mount_output=output, usage=usage, runner=runner,
                                stat_fn=lambda path: SimpleNamespace(st_dev=2 if path in
                                    ("/Users/ada", "/System/Volumes/Data") else 1))
        self.assertEqual(len(report["volumes"]), 2)
        self.assertTrue(report["volumes"][0]["internal"])
        self.assertEqual(report["homeVolume"], "/System/Volumes/Data")

    def test_windows_drive_types(self):
        report = volumes.report(platform="windows",
                                env={"USERPROFILE": "C:\\Users\\Ada", "SystemDrive": "C:"},
                                drives=(1 << 2) | (1 << 3),
                                drive_type=lambda drive: 2 if drive == "D:\\" else 3,
                                usage=usage)
        self.assertEqual(len(report["volumes"]), 2)
        self.assertEqual(report["homeVolume"], "C:\\")
        self.assertTrue(report["volumes"][0]["root"])
        self.assertTrue(report["volumes"][1]["removable"])
