"""CLN-18 tests: the schedule store and the cron evaluation behind it.

The behaviours the task calls out get dedicated tests: cron validation (the
accepted forms — ranges, lists, steps — and the precise refusals for empty,
miscounted, out-of-range, stepped and garbage expressions), ``next_run``
firing on the naive local wall clock strictly after the base time within its
scan window, the typed store with settings-store discipline (roundtrip,
duplicate refusal, 0700 folder / 0600 file, atomic write, fail-closed corrupt
and symlinked store) and the ``due()`` truth table. Every test runs on
generated temp state with injected clocks and env — never a real user folder
or the real store (rule 8).
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import paths as paths_module  # noqa: E402
from cleanup_lab import schedules as schedules_module  # noqa: E402


def ts(*args):
    """A local wall-clock timestamp, the same conversion the engine applies to fire times."""
    return datetime(*args).timestamp()


class TickingClock:
    """An injectable clock handing out fixed values in order, repeating the last."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


class CronValidationTests(unittest.TestCase):
    """validate_cron: the accepted dialect and the precise refusals."""

    def test_accepts_the_documented_forms(self):
        for expr in (
            "* * * * *",
            "30 2 * * *",
            "*/15 * * * *",
            "0 12 1-15 * 1",
            "5,10,15 0 1 1 0",
            "10-30/2 * * * *",
            "1-5,10 * * * *",
            "0 0 29 2 *",
            "0 12 * * 7",  # dow 7 is Sunday too (7 == 0)
            "0 0 * * 1-5",
            "59 23 31 12 6",
            "0 0 1 1 0-6",
        ):
            self.assertEqual(schedules_module.validate_cron(expr), expr)

    def test_whitespace_is_collapsed(self):
        self.assertEqual(schedules_module.validate_cron("  30   2\t*  *  * "), "30 2 * * *")
        self.assertEqual(schedules_module.validate_cron("30\n2 * * *"), "30 2 * * *")

    def test_field_count_is_exact(self):
        for bad in ("", "   ", "30 2 * *", "30 2 * * * *", "*"):
            with self.assertRaises(ValueError) as caught:
                schedules_module.validate_cron(bad)
            self.assertIn("5 fields", str(caught.exception))

    def test_out_of_range_values_are_refused_with_the_field_named(self):
        cases = (
            ("60 * * * *", "minute", "60"),
            ("* 25 * * *", "hour", "25"),
            ("* * 32 * *", "day of month", "32"),
            ("* * 0 * *", "day of month", "0"),
            ("* * * 13 *", "month", "13"),
            ("* * * * 8", "day of week", "8"),
        )
        for expr, field, value in cases:
            with self.assertRaises(ValueError) as caught:
                schedules_module.validate_cron(expr)
            message = str(caught.exception)
            self.assertIn(field, message)
            self.assertIn(value, message)

    def test_steps_zero_and_non_integer_are_refused(self):
        with self.assertRaises(ValueError) as caught:
            schedules_module.validate_cron("*/0 * * * *")
        self.assertIn("step", str(caught.exception))
        with self.assertRaises(ValueError):
            schedules_module.validate_cron("*/x * * * *")
        with self.assertRaises(ValueError):
            schedules_module.validate_cron("1-5/0 * * * *")

    def test_garbage_and_non_integers_are_refused(self):
        for bad in (
            "a b c d e",
            "1.5 * * * *",
            "-1 * * * *",
            "1,,2 * * * *",
            "10-5 * * * *",
            "5/2 * * * *",  # a step needs * or a range, never a bare value
            "1-2-3 * * * *",
            "30\x002 * * * *",
            "JAN * * * *",
            None,
            30,
        ):
            with self.assertRaises(ValueError):
                schedules_module.validate_cron(bad)


class NextRunTests(unittest.TestCase):
    """next_run: naive local wall clock, strictly after, inside the scan window."""

    def fire(self, expr, *after, **kwargs):
        return schedules_module.next_run(expr, ts(*after), **kwargs)

    def test_daily_0230_fires_next_morning(self):
        self.assertEqual(self.fire("30 2 * * *", 2026, 11, 16, 10, 0, 0), ts(2026, 11, 17, 2, 30, 0))
        self.assertEqual(self.fire("30 2 * * *", 2026, 11, 16, 1, 0, 0), ts(2026, 11, 16, 2, 30, 0))

    def test_quarter_hours(self):
        self.assertEqual(self.fire("*/15 * * * *", 2026, 11, 16, 10, 7, 0), ts(2026, 11, 16, 10, 15, 0))
        # strictly after: a fire exactly at the base time does not count
        self.assertEqual(self.fire("*/15 * * * *", 2026, 11, 16, 10, 0, 0), ts(2026, 11, 16, 10, 15, 0))
        self.assertEqual(self.fire("*/15 * * * *", 2026, 11, 16, 10, 15, 0), ts(2026, 11, 16, 10, 30, 0))
        self.assertEqual(self.fire("*/15 * * * *", 2026, 11, 16, 10, 45, 30), ts(2026, 11, 16, 11, 0, 0))

    def test_fractional_seconds_are_strictly_after_the_base_minute(self):
        self.assertEqual(
            self.fire("0 * * * *", 2026, 11, 16, 10, 0, 0, 500000), ts(2026, 11, 16, 11, 0, 0)
        )

    def test_lists_ranges_and_steps(self):
        self.assertEqual(self.fire("5,35 * * * *", 2026, 11, 16, 10, 10, 0), ts(2026, 11, 16, 10, 35, 0))
        self.assertEqual(self.fire("5,35 * * * *", 2026, 11, 16, 10, 40, 0), ts(2026, 11, 16, 11, 5, 0))
        self.assertEqual(
            self.fire("10-30/10 * * * *", 2026, 11, 16, 10, 11, 0), ts(2026, 11, 16, 10, 20, 0)
        )
        self.assertEqual(self.fire("0 0 * * 1-5", 2026, 11, 16, 0, 30, 0), ts(2026, 11, 17, 0, 0, 0))

    def test_day_of_week_sunday_zero_and_seven_agree(self):
        # the next Sunday noon lies 146 h after the Monday base: widen the window
        sunday = self.fire("0 12 * * 0", 2026, 11, 16, 10, 0, 0, limit_hours=24 * 7)
        self.assertEqual(sunday, ts(2026, 11, 22, 12, 0, 0))
        self.assertEqual(
            self.fire("0 12 * * 7", 2026, 11, 16, 10, 0, 0, limit_hours=24 * 7), sunday
        )

    def test_day_of_month_and_restricted_dom_and_dow_match_either(self):
        self.assertEqual(
            self.fire("0 0 13 * *", 2026, 11, 16, 10, 0, 0, limit_hours=24 * 30),
            ts(2026, 12, 13, 0, 0, 0),
        )
        # classic cron semantics: a restricted day-of-month OR day-of-week fires on either
        self.assertEqual(
            self.fire("0 0 13 * 5", 2026, 11, 16, 10, 0, 0, limit_hours=24 * 30),
            ts(2026, 11, 20, 0, 0, 0),
        )

    def test_nothing_within_the_limit_returns_none(self):
        self.assertIsNone(self.fire("0 0 30 2 *", 2026, 11, 16, 10, 0, 0))  # Feb 30 never exists
        self.assertIsNone(self.fire("59 23 31 4 *", 2026, 11, 16, 10, 0, 0))  # April 31 never exists
        self.assertIsNone(self.fire("0 0 1 * *", 2026, 11, 16, 10, 0, 0))  # Dec 1 is beyond 48 h
        self.assertIsNone(self.fire("0 0 29 2 *", 2026, 11, 16, 10, 0, 0))  # leap day beyond 48 h

    def test_a_wider_limit_reaches_far_fires(self):
        self.assertEqual(
            self.fire("0 0 1 * *", 2026, 11, 16, 10, 0, 0, limit_hours=24 * 20),
            ts(2026, 12, 1, 0, 0, 0),
        )
        self.assertEqual(
            self.fire("0 0 29 2 *", 2026, 11, 16, 10, 0, 0, limit_hours=24 * 500),
            ts(2028, 2, 29, 0, 0, 0),
        )
        self.assertEqual(
            self.fire("0 0 1 1-6 *", 2026, 11, 16, 10, 0, 0, limit_hours=24 * 60),
            ts(2027, 1, 1, 0, 0, 0),
        )

    def test_next_run_validates_the_expression(self):
        with self.assertRaises(ValueError):
            schedules_module.next_run("garbage", ts(2026, 11, 16, 10, 0, 0))


class StoreTests(unittest.TestCase):
    """The typed store: roundtrip, dedup, discipline, fail-closed reads."""

    platform = "macos"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-sched-")
        self.env = {"HOME": self.tmp.name, "USERPROFILE": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def store_path(self):
        return os.path.join(paths_module.state_dir(self.env, self.platform), "schedules.json")

    def test_roundtrip_add_list_remove_set_enabled_and_mark_run(self):
        clock = TickingClock(1765000000.0, 1765000100.0)
        first = schedules_module.add("30 2 * * *", env=self.env, platform=self.platform, clock=clock)
        second = schedules_module.add("*/15 * * * *", env=self.env, platform=self.platform, clock=clock)
        self.assertEqual(set(first), {"id", "cron", "enabled", "createdAt", "lastRunAt"})
        self.assertEqual(first["cron"], "30 2 * * *")
        self.assertTrue(first["enabled"])
        self.assertEqual(first["createdAt"], 1765000000.0)
        self.assertIsNone(first["lastRunAt"])
        self.assertNotEqual(first["id"], second["id"])
        found, problem = schedules_module.list_schedules(self.env, self.platform)
        self.assertIsNone(problem)
        self.assertEqual([record["id"] for record in found], [first["id"], second["id"]])

        disabled = schedules_module.set_enabled(first["id"], False, env=self.env, platform=self.platform)
        self.assertFalse(disabled["enabled"])
        marked = schedules_module.mark_run(
            second["id"], 1765000900.0, env=self.env, platform=self.platform
        )
        self.assertEqual(marked["lastRunAt"], 1765000900.0)
        found, _ = schedules_module.list_schedules(self.env, self.platform)
        by_id = {record["id"]: record for record in found}
        self.assertFalse(by_id[first["id"]]["enabled"])
        self.assertEqual(by_id[second["id"]]["lastRunAt"], 1765000900.0)

        self.assertTrue(schedules_module.remove(first["id"], env=self.env, platform=self.platform))
        found, _ = schedules_module.list_schedules(self.env, self.platform)
        self.assertEqual([record["id"] for record in found], [second["id"]])
        self.assertFalse(schedules_module.remove("nope", env=self.env, platform=self.platform))

    def test_the_store_roundtrip_feeds_due(self):
        created = ts(2026, 7, 15, 10, 0, 0)
        record = schedules_module.add(
            "*/15 * * * *", env=self.env, platform=self.platform, clock=lambda: created
        )
        now = ts(2026, 7, 15, 10, 20, 0)
        found, _ = schedules_module.list_schedules(self.env, self.platform)
        self.assertTrue(schedules_module.due(found[0], now))
        schedules_module.mark_run(
            record["id"], ts(2026, 7, 15, 10, 16, 0), env=self.env, platform=self.platform
        )
        found, _ = schedules_module.list_schedules(self.env, self.platform)
        self.assertFalse(schedules_module.due(found[0], now))  # the next fire moved to 10:30
        self.assertTrue(schedules_module.due(found[0], ts(2026, 7, 15, 10, 31, 0)))

    def test_a_whitespace_variant_of_an_existing_cron_is_the_same_schedule(self):
        schedules_module.add("30 2 * * *", env=self.env)
        with self.assertRaises(ValueError):
            schedules_module.add("  30   2 * * * ", env=self.env)

    def test_an_invalid_cron_is_refused_and_writes_nothing(self):
        schedules_module.add("*/15 * * * *", env=self.env)
        with self.assertRaises(ValueError):
            schedules_module.add("garbage", env=self.env)
        found, problem = schedules_module.list_schedules(self.env, self.platform)
        self.assertIsNone(problem)
        self.assertEqual(len(found), 1)

    def test_enabled_and_timestamp_arguments_are_typed(self):
        record = schedules_module.add("30 2 * * *", env=self.env)
        with self.assertRaises(ValueError):
            schedules_module.set_enabled(record["id"], "yes", env=self.env)
        with self.assertRaises(ValueError):
            schedules_module.mark_run(record["id"], "soon", env=self.env)
        with self.assertRaises(ValueError):
            schedules_module.add("0 12 * * *", enabled=1, env=self.env)

    def test_unknown_ids_are_refused(self):
        with self.assertRaises(ValueError):
            schedules_module.set_enabled("nope", True, env=self.env)
        with self.assertRaises(ValueError):
            schedules_module.mark_run("nope", 1.0, env=self.env)
        self.assertFalse(schedules_module.remove("nope", env=self.env))

    def test_a_missing_store_means_no_schedules_and_no_problem(self):
        found, problem = schedules_module.list_schedules(self.env, self.platform)
        self.assertEqual(found, [])
        self.assertIsNone(problem)

    def test_a_corrupt_store_fails_closed(self):
        os.makedirs(paths_module.state_dir(self.env, self.platform), mode=0o700, exist_ok=True)
        bodies = (
            "{not json",
            "[]",
            '{"version": 2, "schedules": []}',
            '{"version": 1, "schedules": [{"id": "a"}]}',
            '{"version": 1, "schedules": [{"id": "a", "cron": "garbage", "enabled": true,'
            ' "createdAt": 1.0, "lastRunAt": null}]}',
            '{"version": 1, "schedules": [{"id": "a", "cron": "30 2 * * *", "enabled": 1,'
            ' "createdAt": 1.0, "lastRunAt": null}]}',
            '{"version": 1, "schedules": [{"id": "a", "cron": "30 2 * * *", "enabled": true,'
            ' "createdAt": 1.0, "lastRunAt": null, "note": "extra"}]}',
        )
        for body in bodies:
            with open(self.store_path(), "w", encoding="utf-8") as handle:
                handle.write(body)
            found, problem = schedules_module.list_schedules(self.env, self.platform)
            self.assertEqual(found, [])
            self.assertIsNotNone(problem)
            self.assertEqual(problem["code"], "schedules-corrupt")
        # mutators refuse to write on top of a store they cannot trust
        with self.assertRaises(schedules_module.SchedulesError):
            schedules_module.add("0 6 * * *", env=self.env)
        with self.assertRaises(schedules_module.SchedulesError):
            schedules_module.remove("a", env=self.env)
        with self.assertRaises(schedules_module.SchedulesError):
            schedules_module.set_enabled("a", False, env=self.env)
        with self.assertRaises(schedules_module.SchedulesError):
            schedules_module.mark_run("a", 1.0, env=self.env)

    def test_a_symlinked_store_is_refused(self):
        os.makedirs(paths_module.state_dir(self.env, self.platform), mode=0o700, exist_ok=True)
        os.symlink(os.path.join(self.tmp.name, "elsewhere.json"), self.store_path())
        _, problem = schedules_module.list_schedules(self.env, self.platform)
        self.assertIsNotNone(problem)
        self.assertIn("symlink", problem["message"])

    def test_a_loose_permissions_store_is_refused(self):
        if os.name == "nt":
            self.skipTest("POSIX permission checks")
        os.makedirs(paths_module.state_dir(self.env, self.platform), mode=0o700, exist_ok=True)
        with open(self.store_path(), "w", encoding="utf-8") as handle:
            handle.write('{"version": 1, "schedules": []}')
        os.chmod(self.store_path(), 0o644)
        _, problem = schedules_module.list_schedules(self.env, self.platform)
        self.assertIsNotNone(problem)
        self.assertIn("0600", problem["message"])

    def test_the_store_file_is_private_and_the_write_is_atomic(self):
        if os.name == "nt":
            self.skipTest("POSIX permission checks")
        schedules_module.add("30 2 * * *", env=self.env, platform=self.platform)
        folder = paths_module.state_dir(self.env, self.platform)
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)
        path = self.store_path()
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.islink(path))
        self.assertFalse(os.path.lexists(path + ".tmp"))  # nothing half-written left behind

    def test_a_symlinked_state_folder_is_refused_on_write(self):
        if os.name == "nt":
            self.skipTest("POSIX symlinks")
        real = os.path.join(self.tmp.name, "real-state")
        os.makedirs(real, mode=0o700)
        link = os.path.join(self.tmp.name, "linked-state")
        os.symlink(real, link)
        env = {"HOME": self.tmp.name, "USERPROFILE": self.tmp.name, "OSLAB_CLEANUP_STATE": link}
        with self.assertRaises(schedules_module.SchedulesError):
            schedules_module.add("30 2 * * *", env=env, platform=self.platform)

    def test_the_store_can_be_reached_through_the_environment_override(self):
        state = os.path.join(self.tmp.name, "env-state")
        with mock.patch.dict(os.environ, {"OSLAB_CLEANUP_STATE": state}):
            record = schedules_module.add("30 2 * * *")
            found, problem = schedules_module.list_schedules()
        self.assertIsNone(problem)
        self.assertEqual([item["id"] for item in found], [record["id"]])
        self.assertTrue(os.path.isdir(state))


class DueTests(unittest.TestCase):
    """due(): enabled, and the next fire from lastRunAt (or createdAt) has arrived."""

    def record(self, *, cron="*/15 * * * *", enabled=True, created, last_run=None):
        return {
            "id": "abc123",
            "cron": cron,
            "enabled": enabled,
            "createdAt": ts(*created),
            "lastRunAt": None if last_run is None else ts(*last_run),
        }

    def test_a_disabled_schedule_is_never_due(self):
        schedule = self.record(created=(2026, 7, 15, 10, 0, 0), enabled=False)
        self.assertFalse(schedules_module.due(schedule, ts(2026, 7, 15, 10, 20, 0)))

    def test_an_enabled_schedule_is_due_when_a_fire_fell_after_its_base(self):
        schedule = self.record(created=(2026, 7, 15, 10, 0, 0))
        self.assertFalse(schedules_module.due(schedule, ts(2026, 7, 15, 10, 10, 0)))
        self.assertTrue(schedules_module.due(schedule, ts(2026, 7, 15, 10, 16, 0)))

    def test_after_a_run_the_next_fire_moves(self):
        schedule = self.record(created=(2026, 7, 15, 10, 0, 0))
        now = ts(2026, 7, 15, 10, 20, 0)
        self.assertTrue(schedules_module.due(schedule, now))
        schedule["lastRunAt"] = ts(2026, 7, 15, 10, 16, 0)
        self.assertFalse(schedules_module.due(schedule, now))  # next fire is 10:30
        self.assertTrue(schedules_module.due(schedule, ts(2026, 7, 15, 10, 31, 0)))

    def test_a_schedule_that_never_fires_is_never_due(self):
        schedule = self.record(cron="0 0 30 2 *", created=(2026, 7, 15, 10, 0, 0))
        self.assertFalse(schedules_module.due(schedule, ts(2026, 7, 15, 12, 0, 0)))

    def test_a_malformed_record_fails_closed(self):
        self.assertFalse(schedules_module.due("not a dict", 2.0))
        self.assertFalse(
            schedules_module.due({"cron": "*/15 * * * *", "enabled": True}, ts(2026, 7, 15, 10, 20, 0))
        )
        self.assertFalse(
            schedules_module.due(
                {
                    "id": "x",
                    "cron": "garbage",
                    "enabled": True,
                    "createdAt": 1.0,
                    "lastRunAt": None,
                },
                2.0,
            )
        )
        self.assertFalse(
            schedules_module.due(
                {"id": "x", "cron": "*/15 * * * *", "enabled": True, "createdAt": None}, 2.0
            )
        )


if __name__ == "__main__":
    unittest.main()
