"""CLN-30: the notification outbox is pure state over an injectable clock.

No test touches a notification facility: the store lives in a generated
temp state folder (OSLAB_CLEANUP_STATE), the clock is a fake, and delivery
is the desktop app's business, never this module's.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cleanup_lab import notifications  # noqa: E402


class ConfigValidation(unittest.TestCase):
    def test_defaults_are_enabled_with_every_category_on(self):
        base = notifications.default_config()
        self.assertTrue(base["enabled"])
        self.assertEqual(set(base["categories"]), set(notifications.CATEGORIES))
        self.assertTrue(all(base["categories"].values()))

    def test_unknown_keys_and_bad_types_are_refused(self):
        for bad in [
            None,
            "on",
            {"nope": True},
            {"enabled": "yes"},
            {"categories": []},
            {"categories": "x"},
            {"categories": {"volume-low": True}},
            {"categories": {"job-done": "yes"}},
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(notifications.NotificationsConfigError):
                    notifications.validate_config(bad)

    def test_missing_categories_default_to_on_and_unknown_are_refused(self):
        config = notifications.validate_config({"enabled": True, "categories": {"job-done": False}})
        self.assertFalse(config["categories"]["job-done"])
        self.assertTrue(config["categories"]["monitor-warning"])


class StoreRoundTrip(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="oslab-notifications-")
        self.env = {"HOME": self.base, "USERPROFILE": self.base, "OSLAB_CLEANUP_STATE": self.base}
        self.now = 1700.0

    def tearDown(self):
        for name in os.listdir(self.base):
            os.remove(os.path.join(self.base, name))
        os.rmdir(self.base)

    def test_empty_store_reports_defaults_without_a_file(self):
        loaded = notifications.load(env=self.env)
        self.assertIsNone(loaded["configError"])
        self.assertTrue(loaded["config"]["enabled"])
        self.assertEqual(loaded["events"], [])

    def test_emit_gates_on_enabled_and_category(self):
        first = notifications.emit("job-done", "Cleanup finished", "Scan found 3 items",
                                   env=self.env, clock=lambda: self.now)
        self.assertTrue(first["emitted"])
        self.assertEqual(first["event"]["id"], 1)
        notifications.save_config({"enabled": False}, env=self.env)
        gated = notifications.emit("job-done", "Cleanup finished", "again", env=self.env, clock=lambda: self.now)
        self.assertFalse(gated["emitted"])
        self.assertEqual(gated["reason"], "disabled")
        notifications.save_config({"enabled": True, "categories": {"job-done": False}}, env=self.env)
        category_gated = notifications.emit("job-done", "Cleanup finished", "again", env=self.env, clock=lambda: self.now)
        self.assertFalse(category_gated["emitted"])

    def test_emit_keeps_a_bounded_typed_outbox_with_monotonic_ids(self):
        clock = lambda: self.now  # noqa: E731
        for index in range(notifications.MAX_EVENTS + 5):
            result = notifications.emit("monitor-warning", "Free space is running low",
                                        "volume {0}".format(index),
                                        route="scan",
                                        actions=[{"id": "scan", "label": "Run a scan", "route": "scan"}],
                                        env=self.env, clock=clock)
            self.assertTrue(result["emitted"])
        loaded = notifications.load(env=self.env)
        self.assertEqual(len(loaded["events"]), notifications.MAX_EVENTS)
        ids = [event["id"] for event in loaded["events"]]
        self.assertEqual(ids, list(range(6, notifications.MAX_EVENTS + 6)))

    def test_unknown_routes_and_actions_are_refused_not_stored(self):
        result = notifications.emit("job-failed", "Cleanup failed", "boom",
                                    route="../../etc",
                                    actions=[{"id": "open", "label": "Open", "route": "nope"}],
                                    env=self.env, clock=lambda: self.now)
        event = result["event"]
        self.assertIsNone(event["route"])
        self.assertEqual(event["actions"], [{"id": "open", "label": "Open", "route": None}])

    def test_corrupt_store_falls_back_to_defaults(self):
        with open(notifications._store_path(env=self.env), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        loaded = notifications.load(env=self.env)
        self.assertIn("unreadable", loaded["configError"])
        self.assertEqual(loaded["events"], [])
        # A store of the wrong version never arms a stale gate either.
        with open(notifications._store_path(env=self.env), "w", encoding="utf-8") as handle:
            json.dump({"version": 99, "config": {"enabled": False}, "events": []}, handle)
        loaded = notifications.load(env=self.env)
        self.assertIn("unknown version", loaded["configError"])
        self.assertTrue(loaded["config"]["enabled"])

    def test_outbox_yields_events_after_the_cursor(self):
        for index in range(3):
            notifications.emit("job-done", "Cleanup finished", str(index), env=self.env,
                               clock=lambda: self.now + index)
        box = notifications.outbox(1, env=self.env)
        self.assertEqual([event["id"] for event in box["events"]], [2, 3])
        self.assertEqual(box["cursor"], 3)
        self.assertEqual(notifications.outbox(99, env=self.env)["events"], [])
        self.assertEqual(notifications.outbox(None, env=self.env)["cursor"], 3)
        # A pruned cursor cannot wedge the watcher: garbage yields everything.
        self.assertEqual(len(notifications.outbox("x", env=self.env)["events"]), 3)

    def test_emit_is_best_effort_when_the_store_is_unwritable(self):
        os.chmod(self.base, 0o500)  # read-only folder
        try:
            result = notifications.emit("job-done", "Cleanup finished", "x", env=self.env,
                                        clock=lambda: self.now)
            self.assertFalse(result["emitted"])
            self.assertIsNotNone(result["reason"])
        finally:
            os.chmod(self.base, 0o700)


class SettingsLinks(unittest.TestCase):
    def test_fixed_panes_per_platform(self):
        self.assertTrue(notifications.settings_urls("macos")[0].startswith("x-apple.systempreferences:"))
        self.assertEqual(notifications.settings_urls("windows"), ("ms-settings:notifications",))
        self.assertEqual(notifications.settings_urls("linux"), ())
        self.assertEqual(notifications.settings_urls(None), ())


if __name__ == "__main__":
    unittest.main()
