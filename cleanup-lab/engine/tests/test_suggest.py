"""CUX-08: suggestion logic and the preference store, over fake catalogs and fake disks."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cleanup_lab import preferences, suggest  # noqa: E402

MB = 1024 ** 2
GB = 1024 ** 3


def entry(entry_id, risk="low", default=False, privilege=False, cleanable=True):
    return {"id": entry_id, "name": entry_id.title(), "risk": risk, "defaultSelected": default,
            "needsPrivilege": privilege, "cleanable": cleanable}


CATALOG = [
    entry("system.user-caches", default=True),
    entry("developers.npm"),
    entry("developers.uv"),
    entry("browser.chrome", risk="medium"),
    entry("developers.cellar", risk="high", cleanable=False),
    entry("agents.codex", risk="credentials", cleanable=False),
    entry("system.shared-temp", risk="medium", privilege=True),
    entry("developers.rustup", cleanable=False),
]
SCAN = [{"id": "system.user-caches", "sizeBytes": 3 * GB}, {"id": "developers.npm", "sizeBytes": 2 * GB},
        {"id": "developers.uv", "sizeBytes": 1 * GB}, {"id": "browser.chrome", "sizeBytes": 1 * GB},
        {"id": "developers.cellar", "sizeBytes": 11 * GB}, {"id": "agents.codex", "sizeBytes": 3 * GB},
        {"id": "system.shared-temp", "sizeBytes": 3 * GB}, {"id": "developers.rustup", "sizeBytes": 4 * GB}]


def prefs(**over):
    return dict(preferences.default_suggestion(), **over)


def ids(result):
    return [item["id"] for item in result["items"]]


class Suggest(unittest.TestCase):
    def test_a_healthy_disk_gets_only_the_recommended_set(self):
        result = suggest.suggest(CATALOG, SCAN, prefs(), free_bytes=100 * GB, threshold_bytes=20 * GB)
        self.assertEqual(ids(result), ["system.user-caches"])
        self.assertFalse(result["pressure"]["underPressure"])
        self.assertTrue(result["pressure"]["covers"])

    def test_pressure_adds_the_safest_largest_entries_until_the_shortfall_is_covered(self):
        result = suggest.suggest(CATALOG, SCAN, prefs(), free_bytes=4 * GB, threshold_bytes=10 * GB)
        # need 6 GB: the 3 GB default plus the low-risk npm (2) and uv (1); medium chrome is not needed.
        self.assertEqual(ids(result), ["system.user-caches", "developers.npm", "developers.uv"])
        self.assertEqual([item["reason"] for item in result["items"]], ["recommended", "extra for space", "extra for space"])
        self.assertTrue(result["pressure"]["covers"])
        self.assertEqual(result["pressure"]["shortfallBytes"], 6 * GB)

    def test_it_says_so_when_safe_entries_cannot_cover_the_shortfall(self):
        result = suggest.suggest(CATALOG, SCAN, prefs(), free_bytes=1 * GB, threshold_bytes=40 * GB)
        self.assertFalse(result["pressure"]["covers"])
        self.assertEqual(result["totalBytes"], 7 * GB)  # 3 + 2 + 1 + 1, never the high/credentials/privileged/measured-only ones
        self.assertEqual(result["pressure"]["remainingBytes"], 39 * GB - 7 * GB)

    def test_unsafe_entries_are_never_suggested_even_when_included(self):
        include = ["developers.cellar", "agents.codex", "system.shared-temp", "developers.rustup"]
        result = suggest.suggest(CATALOG, SCAN, prefs(include=include), free_bytes=100 * GB, threshold_bytes=20 * GB)
        self.assertEqual(ids(result), ["system.user-caches"])
        self.assertEqual({row["id"] for row in result["skipped"]}, set(include))

    def test_include_adds_and_exclude_removes_and_min_size_hides_small_entries(self):
        result = suggest.suggest(CATALOG, SCAN, prefs(include=["developers.uv"], exclude=["system.user-caches"]),
                                 free_bytes=100 * GB, threshold_bytes=20 * GB)
        self.assertEqual(ids(result), ["developers.uv"])
        self.assertEqual(result["items"][0]["reason"], "included by you")
        small = suggest.suggest(CATALOG, SCAN, prefs(mode="extended", minEntryBytes=int(1.5 * GB)), free_bytes=None, threshold_bytes=None)
        self.assertEqual(ids(small), ["system.user-caches", "developers.npm"])

    def test_extended_takes_every_safe_measured_entry_and_recommended_ignores_pressure(self):
        extended = suggest.suggest(CATALOG, SCAN, prefs(mode="extended"), free_bytes=100 * GB, threshold_bytes=20 * GB)
        self.assertEqual(sorted(ids(extended)), sorted(["system.user-caches", "developers.npm", "developers.uv", "browser.chrome"]))
        recommended = suggest.suggest(CATALOG, SCAN, prefs(mode="recommended"), free_bytes=1 * GB, threshold_bytes=40 * GB)
        self.assertEqual(ids(recommended), ["system.user-caches"])

    def test_a_custom_target_changes_the_pressure_and_unknown_ids_are_ignored_not_lost(self):
        result = suggest.suggest(CATALOG, SCAN, prefs(targetFreeBytes=50 * GB, include=["gone.entry"]), free_bytes=40 * GB, threshold_bytes=10 * GB)
        self.assertTrue(result["pressure"]["underPressure"])
        self.assertEqual(result["ignoredIds"], ["gone.entry"])


class Store(unittest.TestCase):
    def env(self, base):
        return {"HOME": base, "USERPROFILE": base, "OSLAB_CLEANUP_STATE": base}

    def test_round_trip_and_defaults(self):
        with tempfile.TemporaryDirectory() as base:
            env = self.env(base)
            self.assertEqual(preferences.load(env=env)["suggestion"], preferences.default_suggestion())
            saved = preferences.save(prefs(mode="extended", include=["developers.uv"], exclude=["browser.chrome"], targetFreeBytes=30 * GB), env=env)
            self.assertEqual(preferences.load(env=env), saved)

    def test_invalid_input_is_refused(self):
        for bad in ({"mode": "wild"}, {"include": "x"}, {"include": ["a"], "exclude": ["a"]}, {"include": ["a", "a"]},
                    {"minEntryBytes": -1}, {"targetFreeBytes": 0}, {"surprise": 1}, {"include": [""]}):
            with self.assertRaises(preferences.PreferencesError):
                preferences.validate_suggestion(bad)

    def test_a_store_from_another_version_and_unknown_ids_survive(self):
        with tempfile.TemporaryDirectory() as base:
            env = self.env(base)
            with open(os.path.join(base, "preferences.json"), "w", encoding="utf-8") as handle:
                json.dump({"version": 7, "suggestion": {"mode": "extended", "include": ["entry.from.a.newer.catalog"]}}, handle)
            loaded = preferences.load(env=env)
            self.assertIsNone(loaded["configError"])
            self.assertEqual(loaded["suggestion"]["mode"], "extended")
            self.assertEqual(loaded["suggestion"]["include"], ["entry.from.a.newer.catalog"])

    def test_corruption_falls_back_to_defaults_with_a_reason(self):
        with tempfile.TemporaryDirectory() as base:
            env = self.env(base)
            path = os.path.join(base, "preferences.json")
            for text, expect in (("{nope", "unreadable"), ('{"version": "x"}', "unknown shape"), ('{"version": 1, "suggestion": {"mode": "x"}}', "invalid")):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(text)
                loaded = preferences.load(env=env)
                self.assertIn(expect, loaded["configError"])
                self.assertEqual(loaded["suggestion"], preferences.default_suggestion())


if __name__ == "__main__":
    unittest.main()
