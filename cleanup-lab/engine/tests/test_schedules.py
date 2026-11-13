"""Scheduled dry runs only: parsing, private CRUD and one claim per minute."""
import os
import stat
import tempfile
import unittest
from datetime import datetime

from cleanup_lab import schedules


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = {"HOME": self.temp.name,
                    "OSLAB_CLEANUP_STATE": os.path.join(self.temp.name, "state")}

    def test_cron_validation_and_calendar(self):
        self.assertTrue(schedules.matches("30 9 * * 1-5", datetime(2026, 11, 13, 9, 30)))
        self.assertFalse(schedules.matches("30 9 * * 1-5", datetime(2026, 11, 14, 9, 30)))
        self.assertTrue(schedules.matches("*/15 9 13 * 2", datetime(2026, 11, 13, 9, 30)))
        for expression in ("* * * *", "61 * * * *", "*/0 * * * *", "* * * * 7", "* * * * *;rm"):
            with self.assertRaises(schedules.ScheduleError):
                schedules.parse_cron(expression)

    def test_crud_claim_and_report(self):
        row = schedules.add("* * * * *", ["system.user-caches"], env=self.env)
        folder = self.env["OSLAB_CLEANUP_STATE"]
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(folder, schedules.FILE)).st_mode), 0o600)
        self.assertEqual(len(schedules.claim_due(60, env=self.env)), 1)
        self.assertEqual(schedules.claim_due(61, env=self.env), [])
        schedules.record(row["id"], {"state": "done"}, env=self.env)
        self.assertEqual(schedules.read(env=self.env)["schedules"][0]["lastRun"]["state"], "done")
        schedules.toggle(row["id"], False, env=self.env)
        self.assertEqual(schedules.claim_due(120, env=self.env), [])
        schedules.delete(row["id"], env=self.env)
        self.assertEqual(schedules.read(env=self.env)["schedules"], [])
