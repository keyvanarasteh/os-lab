"""CUX-07: notifications use fixed argv and never splice text into a script."""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cleanup_lab import notify  # noqa: E402

GIB = 1024 ** 3


class Done:
    def __init__(self, code=0):
        self.returncode = code


class Notify(unittest.TestCase):
    def test_only_warning_levels_are_notifiable(self):
        self.assertIsNone(notify.describe({"kind": "recovered"}))
        self.assertIsNone(notify.describe({"kind": "error"}))
        title, message = notify.describe({"kind": "critical", "volume": "/", "freeBytes": 4 * GIB})
        self.assertEqual(title, "Disk almost full")
        self.assertIn("4.0 GB free", message)

    def test_macos_passes_the_text_as_arguments_not_script_source(self):
        hostile = 'x" & do shell script "touch /tmp/pwned" & "'
        argv = notify.command("Low disk space", hostile, platform="darwin")
        self.assertEqual(argv[0], "osascript")
        self.assertEqual(argv[-2:], [hostile, "Low disk space"])
        self.assertTrue(all(hostile not in part for part in argv[1:-2]))

    def test_linux_needs_notify_send_and_other_systems_skip(self):
        self.assertIsNone(notify.command("t", "m", platform="linux", which=lambda name: None))
        self.assertEqual(notify.command("t", "m", platform="linux", which=lambda name: "/usr/bin/notify-send")[0], "notify-send")
        self.assertIsNone(notify.command("t", "m", platform="win32"))

    def test_send_reports_sent_failed_and_skipped(self):
        event = {"kind": "warning", "volume": "/", "freeBytes": 5 * GIB}
        self.assertEqual(notify.send(event, platform="darwin", run=lambda *a, **k: Done())["status"], "sent")
        self.assertEqual(notify.send(event, platform="darwin", run=lambda *a, **k: Done(1))["status"], "failed")

        def boom(*a, **k):
            raise subprocess.TimeoutExpired("osascript", 5)

        self.assertEqual(notify.send(event, platform="darwin", run=boom)["status"], "failed")
        self.assertEqual(notify.send(event, platform="win32")["status"], "skipped")
        self.assertEqual(notify.send({"kind": "recovered"}, platform="darwin")["status"], "skipped")

    def test_send_all_honours_the_switch_and_filters_kinds(self):
        calls = []
        run = lambda argv, **k: calls.append(argv) or Done()  # noqa: E731
        events = [{"kind": "recovered"}, {"kind": "warning", "volume": "/", "freeBytes": 1}, {"kind": "reminder", "volume": "/", "freeBytes": 1}]
        self.assertEqual(notify.send_all(events, enabled=False, platform="darwin", run=run), [])
        self.assertEqual(len(notify.send_all(events, platform="darwin", run=run)), 2)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
