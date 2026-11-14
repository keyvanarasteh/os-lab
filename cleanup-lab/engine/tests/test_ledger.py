"""CLN-26 tests: the cleaned-items ledger and learned pre-selection.

The behaviours the task calls out get dedicated tests: record filters (only
``trashed``/``deleted``/``shredded`` rows with bytes are recorded; skipped,
failed and zero-byte rows are ignored), aggregation with the ``min_runs``
threshold and bytes-descending order, the rule-5 risk filter
(``high``/``credentials``/``privacy`` are never suggested), the corrupt-store
discipline (moved aside as ``ledger.corrupt-<epoch>.json``, never overwritten,
store starts empty with a reported problem), the 1000-run cap evicting the
oldest run, ``clear``, and the privacy discipline (0700 folder, 0600 file,
atomic write with no ``.tmp`` left behind, symlinked store refused). Every
test runs on a generated temp state folder through an injected ``env`` —
never a real user folder or the real store (rule 8).
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import ledger as ledger_module  # noqa: E402
from cleanup_lab import paths as paths_module  # noqa: E402


def entry(entry_id, risk="low", **overrides):
    """A minimal catalog entry dict, the shape ``suggest`` receives."""
    data = {"id": entry_id, "name": entry_id, "risk": risk}
    data.update(overrides)
    return data


def seq_clock(values):
    """A clock returning the given values in order; a surplus call fails loudly."""
    remaining = list(values)
    return lambda: remaining.pop(0)


def run_row(entry_id="dev.node-modules", path="/tmp/node_modules", status="trashed", **overrides):
    """One clean-plan result row, the shape ``record`` receives from CLN-13."""
    data = {"entryId": entry_id, "path": path, "status": status, "bytes": 1234}
    data.update(overrides)
    return data


def stored_runs(entry_id, count, total_bytes, start_at=1.0):
    """``count`` stored runs for one entry id, splitting ``total_bytes`` between them."""
    return [
        {
            "at": start_at + index,
            "entryId": entry_id,
            "path": "/p/{0}-{1}".format(entry_id, index),
            "bytes": total_bytes // count,
        }
        for index in range(count)
    ]


class LedgerTestCase(unittest.TestCase):
    """Shared plumbing: a generated temp home, injected env, store helpers."""

    platform = "macos"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-ledger-")
        self.home = self.tmp.name
        self.env = {"HOME": self.home, "USERPROFILE": self.home}

    def tearDown(self):
        self.tmp.cleanup()

    def state(self):
        return paths_module.state_dir(self.env, self.platform)

    def store_path(self):
        return os.path.join(self.state(), "ledger.json")

    def seed(self, body):
        """Write the store file with the private discipline (0700 folder, 0600 file)."""
        os.makedirs(self.state(), mode=0o700, exist_ok=True)
        path = self.store_path()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(path, 0o600)
        return path

    def seed_runs(self, runs):
        self.seed(json.dumps({"version": 1, "runs": runs}) + "\n")

    def stored(self):
        with open(self.store_path(), encoding="utf-8") as handle:
            return json.load(handle)

    def asides(self):
        return sorted(glob.glob(os.path.join(self.state(), "ledger.corrupt-*.json")))


class RecordTests(LedgerTestCase):
    """Only rows the user really cleaned, with bytes, reach the ledger."""

    def test_successful_rows_with_bytes_are_recorded(self):
        rows = [
            run_row("dev.a", status="trashed"),
            run_row("dev.b", status="deleted"),
            run_row("dev.c", status="shredded"),
        ]
        count, problem = ledger_module.record(rows, env=self.env, platform=self.platform)
        self.assertEqual(count, 3)
        self.assertIsNone(problem)
        payload, problem = ledger_module.stats(env=self.env, platform=self.platform)
        self.assertIsNone(problem)
        self.assertEqual(payload, {"runs": 3, "entries": 3, "bytes": 3702})

    def test_skipped_failed_and_zero_byte_rows_are_ignored(self):
        rows = [
            run_row(status="skipped"),
            run_row(status="failed"),
            run_row(status="ready"),
            run_row(bytes=0),
            run_row(bytes=-5),
            run_row(bytes="1234"),
            run_row(bytes=None),
            run_row(bytes=True),
            "not a row",
            {"entryId": "dev.pip", "status": "trashed", "bytes": 10},  # no path
            {"path": "/tmp/x", "status": "trashed", "bytes": 10},  # no entryId
            {"entryId": "", "path": "/tmp/x", "status": "trashed", "bytes": 10},
        ]
        count, problem = ledger_module.record(rows, env=self.env, platform=self.platform)
        self.assertEqual(count, 0)
        self.assertIsNone(problem)
        payload, _ = ledger_module.stats(env=self.env, platform=self.platform)
        self.assertEqual(payload["runs"], 0)

    def test_each_row_keeps_its_data_and_own_timestamp(self):
        clock = seq_clock([100.0, 200.5])
        count, problem = ledger_module.record(
            [run_row("dev.a", path="/p/one"), run_row("dev.b", path="/p/two", status="shredded")],
            env=self.env,
            platform=self.platform,
            clock=clock,
        )
        self.assertEqual(count, 2)
        self.assertIsNone(problem)
        self.assertEqual(self.stored()["runs"], [
            {"at": 100.0, "entryId": "dev.a", "path": "/p/one", "bytes": 1234},
            {"at": 200.5, "entryId": "dev.b", "path": "/p/two", "bytes": 1234},
        ])

    def test_record_appends_to_earlier_runs(self):
        ledger_module.record([run_row("dev.a")], env=self.env, platform=self.platform)
        ledger_module.record([run_row("dev.b")], env=self.env, platform=self.platform)
        payload, problem = ledger_module.stats(env=self.env, platform=self.platform)
        self.assertIsNone(problem)
        self.assertEqual(payload["runs"], 2)
        self.assertEqual(payload["entries"], 2)

    def test_a_non_list_rows_argument_is_refused(self):
        for bad in ("nope", None, 42, {"entryId": "dev.a"}):
            with self.assertRaises(ValueError):
                ledger_module.record(bad, env=self.env, platform=self.platform)

    def test_recording_over_a_corrupt_store_recovers_and_reports(self):
        self.seed("{not json")
        count, problem = ledger_module.record(
            [run_row("dev.a")], env=self.env, platform=self.platform
        )
        self.assertEqual(count, 1)
        self.assertIsNotNone(problem)
        self.assertEqual(problem["code"], "ledger-corrupt")
        self.assertIn("moved aside", problem["message"])
        self.assertEqual(len(self.asides()), 1)
        payload, problem = ledger_module.stats(env=self.env, platform=self.platform)
        self.assertIsNone(problem)
        self.assertEqual(payload["runs"], 1)


class LearnedTests(LedgerTestCase):
    """Patterns aggregate by entry id above the min_runs threshold."""

    def test_runs_aggregate_by_entry_id(self):
        self.seed_runs([
            {"at": 1.0, "entryId": "dev.gradle", "path": "/g/one", "bytes": 100},
            {"at": 2.0, "entryId": "dev.gradle", "path": "/g/two", "bytes": 250},
            {"at": 3.0, "entryId": "dev.pip", "path": "/p/one", "bytes": 50},
        ])
        patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertIsNone(problem)
        self.assertEqual(patterns, [{"entryId": "dev.gradle", "runs": 2, "bytes": 350}])

    def test_the_min_runs_threshold(self):
        self.seed_runs(
            stored_runs("a.pair", 2, 200)
            + stored_runs("b.single", 1, 300)
            + stored_runs("c.triple", 3, 300)
        )
        ids = lambda patterns: {pattern["entryId"] for pattern in patterns}  # noqa: E731
        patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertIsNone(problem)
        self.assertEqual(ids(patterns), {"a.pair", "c.triple"})
        patterns, _ = ledger_module.learned(env=self.env, platform=self.platform, min_runs=3)
        self.assertEqual(ids(patterns), {"c.triple"})
        patterns, _ = ledger_module.learned(env=self.env, platform=self.platform, min_runs=1)
        self.assertEqual(ids(patterns), {"a.pair", "b.single", "c.triple"})
        with self.assertRaises(ValueError):
            ledger_module.learned(env=self.env, platform=self.platform, min_runs=0)

    def test_patterns_are_sorted_by_bytes_descending(self):
        self.seed_runs(
            stored_runs("a.small", 2, 200)
            + stored_runs("b.large", 2, 900)
            + stored_runs("c.middle", 2, 500)
        )
        patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertIsNone(problem)
        self.assertEqual([pattern["entryId"] for pattern in patterns], ["b.large", "c.middle", "a.small"])
        self.assertEqual([pattern["bytes"] for pattern in patterns], [900, 500, 200])

    def test_equal_bytes_break_the_tie_alphabetically(self):
        self.seed_runs(stored_runs("b.thing", 2, 300) + stored_runs("a.thing", 2, 300))
        patterns, _ = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertEqual([pattern["entryId"] for pattern in patterns], ["a.thing", "b.thing"])

    def test_an_empty_or_missing_store_has_no_patterns(self):
        patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertEqual(patterns, [])
        self.assertIsNone(problem)


class SuggestTests(LedgerTestCase):
    """Suggestions tick boxes for learned, safe entries — never rule-5 risks."""

    def suggest(self, entries, **kwargs):
        return ledger_module.suggest(entries, env=self.env, platform=self.platform, **kwargs)

    def test_learned_entries_are_suggested_with_a_reason(self):
        self.seed_runs(stored_runs("dev.gradle", 2, 1024))
        suggestions, problem = self.suggest([entry("dev.gradle"), entry("dev.pip")])
        self.assertIsNone(problem)
        self.assertEqual(suggestions, [
            {"entryId": "dev.gradle", "reason": "You have cleaned this 2 times (1.0 KB total)"},
        ])

    def test_the_reason_honours_bytes_and_singular(self):
        self.seed_runs(stored_runs("dev.a", 1, 500))
        suggestions, _ = self.suggest([entry("dev.a")], min_runs=1)
        self.assertEqual(suggestions, [
            {"entryId": "dev.a", "reason": "You have cleaned this 1 time (500 B total)"},
        ])

    def test_risky_entries_are_never_suggested(self):
        runs = []
        for index, entry_id in enumerate(("a.high", "b.credentials", "c.privacy", "d.low", "e.upper")):
            runs.extend(stored_runs(entry_id, 2, 100, start_at=float(index) * 10))
        self.seed_runs(runs)
        entries = [
            entry("a.high", risk="high"),
            entry("b.credentials", risk="credentials"),
            entry("c.privacy", risk="privacy"),
            entry("d.low", risk="low"),
            entry("e.upper", risk="HIGH"),  # the catalog stores lowercase; be safe anyway
        ]
        suggestions, problem = self.suggest(entries)
        self.assertIsNone(problem)
        self.assertEqual([item["entryId"] for item in suggestions], ["d.low"])

    def test_suggestions_follow_the_caller_s_order(self):
        self.seed_runs(stored_runs("zz.late", 2, 200) + stored_runs("aa.early", 2, 900))
        suggestions, _ = self.suggest([entry("aa.early"), entry("zz.late")])
        self.assertEqual([item["entryId"] for item in suggestions], ["aa.early", "zz.late"])

    def test_min_runs_is_honoured_in_suggestions(self):
        self.seed_runs(stored_runs("a.pair", 2, 100) + stored_runs("b.single", 1, 900))
        suggestions, _ = self.suggest([entry("a.pair"), entry("b.single")])
        self.assertEqual([item["entryId"] for item in suggestions], ["a.pair"])
        suggestions, _ = self.suggest([entry("a.pair"), entry("b.single")], min_runs=3)
        self.assertEqual(suggestions, [])

    def test_nothing_is_suggested_without_learned_patterns(self):
        suggestions, problem = self.suggest([entry("dev.gradle")])
        self.assertEqual(suggestions, [])
        self.assertIsNone(problem)

    def test_a_corrupt_store_reports_and_suggests_nothing(self):
        self.seed("{not json")
        suggestions, problem = self.suggest([entry("dev.gradle")])
        self.assertEqual(suggestions, [])
        self.assertIsNotNone(problem)
        self.assertEqual(problem["code"], "ledger-corrupt")

    def test_a_non_dict_entry_is_refused(self):
        with self.assertRaises(ValueError):
            self.suggest(["dev.gradle"])
        with self.assertRaises(ValueError):
            self.suggest("dev.gradle")


class StoreDisciplineTests(LedgerTestCase):
    """Corrupt data is preserved aside, the cap evicts honestly, privacy holds."""

    def test_a_corrupt_store_is_moved_aside_and_reported(self):
        self.seed("{not json")
        patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertEqual(patterns, [])
        self.assertIsNotNone(problem)
        self.assertEqual(problem["code"], "ledger-corrupt")
        self.assertIn("moved aside", problem["message"])
        asides = self.asides()
        self.assertEqual(len(asides), 1)
        self.assertRegex(os.path.basename(asides[0]), r"^ledger\.corrupt-\d+\.json$")
        self.assertFalse(os.path.exists(self.store_path()))
        with open(asides[0], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{not json")

    def test_a_wrong_shaped_store_is_moved_aside(self):
        bodies = (
            "[]",
            '"a string"',
            '{"version": 2, "runs": []}',
            '{"version": 1, "runs": {}}',
            '{"version": 1, "runs": [{}]}',
            '{"version": 1, "runs": [{"at": "x", "entryId": "a", "path": "p", "bytes": 1}]}',
            '{"version": 1, "runs": [{"at": true, "entryId": "a", "path": "p", "bytes": 1}]}',
            '{"version": 1, "runs": [{"at": 1, "entryId": "", "path": "p", "bytes": 1}]}',
            '{"version": 1, "runs": [{"at": 1, "entryId": "a", "path": "", "bytes": 1}]}',
            '{"version": 1, "runs": [{"at": 1, "entryId": "a", "path": "p", "bytes": true}]}',
            '{"version": 1, "runs": [{"at": 1, "entryId": "a", "path": "p", "bytes": -1}]}',
            '{"version": 1, "runs": [{"at": 1, "entryId": "a", "path": "p", "bytes": 1, "extra": 2}]}',
        )
        for body in bodies:
            shutil.rmtree(self.state(), ignore_errors=True)
            self.seed(body)
            patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
            self.assertEqual(patterns, [], body)
            self.assertIsNotNone(problem, body)
            self.assertEqual(problem["code"], "ledger-corrupt", body)
            self.assertIn("moved aside", problem["message"], body)
            self.assertEqual(len(self.asides()), 1, body)
            self.assertFalse(os.path.exists(self.store_path()), body)
            with open(self.asides()[0], encoding="utf-8") as handle:
                self.assertEqual(handle.read(), body)

    def test_a_moved_aside_ledger_is_never_overwritten(self):
        self.seed("{not json")
        fixed = 1700000000.5
        first_aside = os.path.join(self.state(), "ledger.corrupt-1700000000.json")
        with open(first_aside, "w", encoding="utf-8") as handle:
            handle.write("an earlier corrupt ledger")
        with mock.patch.object(ledger_module, "time") as fake_time:
            fake_time.time.return_value = fixed
            patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertEqual(patterns, [])
        self.assertIsNotNone(problem)
        second_aside = first_aside.replace(".json", "-2.json")
        self.assertEqual(set(self.asides()), {first_aside, second_aside})
        with open(first_aside, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "an earlier corrupt ledger")
        with open(second_aside, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{not json")

    def test_the_cap_evicts_the_oldest_run_on_insert(self):
        runs = [
            {"at": float(index), "entryId": "dev.cycle", "path": "/p/{0}".format(index), "bytes": 1}
            for index in range(ledger_module.MAX_RUNS)
        ]
        self.seed_runs(runs)
        row = run_row("dev.new", path="/p/new", status="deleted", bytes=7)
        count, problem = ledger_module.record(
            [row], env=self.env, platform=self.platform, clock=lambda: 5000.0
        )
        self.assertEqual(count, 1)
        self.assertIsNone(problem)
        payload, problem = ledger_module.stats(env=self.env, platform=self.platform)
        self.assertIsNone(problem)
        self.assertEqual(payload["runs"], ledger_module.MAX_RUNS)
        stamps = [run["at"] for run in self.stored()["runs"]]
        self.assertNotIn(0.0, stamps)  # the oldest run was evicted
        self.assertEqual(stamps[0], 1.0)
        self.assertEqual(stamps[-1], 5000.0)  # the new run is kept

    def test_clear_resets_the_store(self):
        ledger_module.record([run_row("dev.a")], env=self.env, platform=self.platform)
        self.assertTrue(ledger_module.clear(env=self.env, platform=self.platform))
        self.assertEqual(self.stored(), {"version": 1, "runs": []})
        payload, problem = ledger_module.stats(env=self.env, platform=self.platform)
        self.assertIsNone(problem)
        self.assertEqual(payload, {"runs": 0, "entries": 0, "bytes": 0})
        # the reset file still exists, so a later clear also saw a file
        self.assertTrue(ledger_module.clear(env=self.env, platform=self.platform))

    def test_clear_without_a_store_is_a_no_op(self):
        self.assertFalse(ledger_module.clear(env=self.env, platform=self.platform))
        self.assertFalse(os.path.isdir(self.state()))  # clearing never creates the store

    def test_clear_on_a_corrupt_store_preserves_it_and_resets(self):
        self.seed("{not json")
        self.assertTrue(ledger_module.clear(env=self.env, platform=self.platform))
        self.assertEqual(len(self.asides()), 1)
        self.assertEqual(self.stored(), {"version": 1, "runs": []})

    def test_a_symlinked_store_is_refused(self):
        os.makedirs(self.state(), mode=0o700)
        target = os.path.join(self.home, "elsewhere.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("not a ledger")
        os.symlink(target, self.store_path())
        patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertEqual(patterns, [])
        self.assertIsNotNone(problem)
        self.assertIn("symlink", problem["message"])
        count, problem = ledger_module.record([run_row("dev.a")], env=self.env, platform=self.platform)
        self.assertEqual(count, 0)
        self.assertIsNotNone(problem)
        self.assertTrue(os.path.islink(self.store_path()))
        _, problem = ledger_module.stats(env=self.env, platform=self.platform)
        self.assertIsNotNone(problem)
        with self.assertRaises(ledger_module.LedgerError):
            ledger_module.clear(env=self.env, platform=self.platform)
        with open(target, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "not a ledger")
        self.assertEqual(self.asides(), [])  # a link is refused in place, never moved aside

    def test_a_loose_permissions_store_is_refused_in_place(self):
        if os.name == "nt":
            self.skipTest("POSIX permission checks")
        self.seed(json.dumps({"version": 1, "runs": []}))
        os.chmod(self.store_path(), 0o644)
        patterns, problem = ledger_module.learned(env=self.env, platform=self.platform)
        self.assertEqual(patterns, [])
        self.assertIsNotNone(problem)
        self.assertIn("0600", problem["message"])
        self.assertTrue(os.path.exists(self.store_path()))
        self.assertEqual(self.asides(), [])

    def test_a_loose_state_folder_is_reported(self):
        if os.name == "nt":
            self.skipTest("POSIX permission checks")
        os.makedirs(self.state(), mode=0o700)
        os.chmod(self.state(), 0o755)
        _, problem = ledger_module.stats(env=self.env, platform=self.platform)
        self.assertIsNotNone(problem)
        self.assertIn("0700", problem["message"])

    def test_the_store_is_private_and_the_write_is_atomic(self):
        if os.name == "nt":
            self.skipTest("POSIX permission checks")
        ledger_module.record([run_row("dev.a")], env=self.env, platform=self.platform)
        self.assertEqual(os.stat(self.state()).st_mode & 0o777, 0o700)
        path = self.store_path()
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.islink(path))
        self.assertEqual([name for name in os.listdir(self.state()) if name.endswith(".tmp")], [])

    def test_the_state_override_is_honoured(self):
        state = os.path.join(self.home, "custom-state")
        env = dict(self.env)
        env["OSLAB_CLEANUP_STATE"] = state
        count, problem = ledger_module.record([run_row("dev.a")], env=env, platform=self.platform)
        self.assertEqual(count, 1)
        self.assertIsNone(problem)
        self.assertTrue(os.path.isfile(os.path.join(state, "ledger.json")))


if __name__ == "__main__":
    unittest.main()
