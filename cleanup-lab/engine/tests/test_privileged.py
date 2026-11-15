"""Privileged previews only accept fixed actions; tests never elevate."""
import stat
import unittest
from types import SimpleNamespace

from cleanup_lab import privileged, readiness, safety


class PrivilegedTests(unittest.TestCase):
    def setUp(self):
        privileged.PLANS.clear()
        self.commands = []

    def which(self, name):
        return "/usr/bin/" + name

    def binary(self, path):
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)

    def runner(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    def test_fixed_preview_and_single_use_run(self):
        plan = privileged.preview(["system.journald-vacuum"], platform="linux",
                                  which=self.which, lstat=self.binary, clock=lambda: 60)
        self.assertEqual(plan["actions"][0]["argv"], ["/usr/bin/journalctl", "--vacuum-time=7d"])
        result = privileged.run(plan["planId"], platform="linux", which=self.which,
                                lstat=self.binary, runner=self.runner, clock=lambda: 61)
        self.assertEqual(result["totals"]["failed"], 0)
        self.assertEqual(self.commands[0][0], ["/usr/bin/pkexec", "/usr/bin/journalctl", "--vacuum-time=7d"])
        self.assertIs(self.commands[0][1]["shell"], False)
        with self.assertRaises(privileged.PrivilegedError):
            privileged.run(plan["planId"], platform="linux", which=self.which,
                           lstat=self.binary, runner=self.runner)

    def test_no_arbitrary_action_or_other_os(self):
        for ids in (["rm -rf /"], ["system.spotlight-rebuild"], ["system.apt-cache-clean"] * 2):
            with self.assertRaises(privileged.PrivilegedError):
                privileged.preview(ids, platform="linux", which=self.which, lstat=self.binary)
        self.assertEqual(self.commands, [])
        with self.assertRaises(safety.SafetyError):
            safety.assert_privileged_action("system.apt-cache-clean", "linux", ("apt-get", "install", "x"))

    def test_untrusted_tool_is_refused_before_preview(self):
        with self.assertRaises(privileged.PrivilegedError):
            privileged.preview(["system.apt-cache-clean"], platform="linux",
                               which=lambda name: "/tmp/" + name, lstat=self.binary)

    def test_disk_access_probe_is_read_only_and_honest(self):
        report = readiness.disk_access(platform="linux")
        self.assertEqual(report["state"], "not-applicable")
        report = readiness.disk_access(platform="macos", env={"HOME": "/nonexistent"})
        self.assertEqual(report["state"], "unknown")
        self.assertIn("cannot prove", report["guidance"])
