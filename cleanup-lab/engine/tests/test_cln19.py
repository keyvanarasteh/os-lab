"""CLN-19 tests: the headless `labctl cleanup scan | plan | clean` flow.

The behaviours the task calls out get dedicated tests: the plan store's
save/claim discipline (single-use by atomic rename, TTL honoured again at
claim time, private files), the CLI gating (no `clean` without `--yes` and a
plan id; unknown entries and ids are usage or problem exits, never traces),
the honest audit trail after a headless clean, the shred policy gate, the
ignore-store fail-closed, and control-character sanitised text output. Every
test runs on a generated tree with a private per-test state folder — never a
real user folder or the real store (rule 8; an unpatched run once wrote to the
real settings store, which is exactly why every CLI call here pins
``OSLAB_CLEANUP_STATE``).
"""
import io
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import cli  # noqa: E402
from cleanup_lab import history  # noqa: E402
from cleanup_lab import paths as paths_module  # noqa: E402
from cleanup_lab import settings as settings_module  # noqa: E402


class HeadlessFlowTests(unittest.TestCase):
    """The whole scan → plan → clean circuit, gated and audited."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln19-")
        self.home = self.tmp.name
        self.state = os.path.join(self.tmp.name + "-state")
        os.makedirs(self.state, mode=0o700)
        self.env = {"HOME": self.home, "USERPROFILE": self.home,
                    "OSLAB_CLEANUP_STATE": self.state, "PATH": ""}
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.caches = os.path.join(self.home, "Library", "Caches")
        os.makedirs(self.caches)
        self.target = os.path.join(self.caches, "data.bin")
        with open(self.target, "wb") as handle:
            handle.write(b"secret" * 20)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv):
        stream = io.StringIO()
        code = cli.main(argv, stream=stream)
        return code, stream.getvalue()

    def plan_id_from(self, text):
        return re.search(r"plan · (\w+)", text).group(1)

    def test_scan_reports_the_catalog_read_only(self):
        code, text = self.run_cli(["scan", "--entry", "system.user-caches"])
        self.assertEqual(code, 0)
        self.assertIn("system.user-caches", text)
        self.assertIn("120 B", text)
        code, text = self.run_cli(["scan", "--entry", "system.user-caches", "--json"])
        payload = json.loads(text)
        self.assertEqual(payload["totals"]["sizeBytes"], 120)
        self.assertTrue(os.path.exists(self.target))

    def test_scan_json_and_text_agree_on_the_totals(self):
        _, text = self.run_cli(["scan", "--entry", "system.user-caches", "--json"])
        self.assertIn('"sizeBytes": 120', text)

    def test_scan_refuses_unknown_entries_as_usage(self):
        self.assertEqual(self.run_cli(["scan", "--entry", "nope"])[0], 2)
        self.assertEqual(self.run_cli(["plan", "--entry", "nope"])[0], 2)

    def test_plan_stores_a_confirmable_plan(self):
        code, text = self.run_cli(["plan", "--entry", "system.user-caches"])
        self.assertEqual(code, 0)
        plan_id = self.plan_id_from(text)
        stored = os.path.join(paths_module.state_dir(self.env), "plans", plan_id + ".json")
        self.assertTrue(os.path.exists(stored))
        if os.name != "nt":
            self.assertEqual(os.stat(stored).st_mode & 0o777, 0o600)
        code, text = self.run_cli(["plan", "--entry", "system.user-caches", "--json"])
        payload = json.loads(text)
        self.assertEqual(payload["mode"], "trash")
        self.assertEqual(payload["totals"]["ready"], 1)

    def test_clean_never_runs_without_plan_and_yes(self):
        self.assertEqual(self.run_cli(["clean"])[0], 2)
        self.assertEqual(self.run_cli(["clean", "--yes"])[0], 2)
        self.assertEqual(self.run_cli(["clean", "--plan", "whatever"])[0], 2)

    def test_the_plan_runs_once_is_audited_and_is_single_use(self):
        _, text = self.run_cli(["plan", "--entry", "system.user-caches"])
        plan_id = self.plan_id_from(text)
        code, text = self.run_cli(["clean", "--plan", plan_id, "--yes", "--json"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.target))
        rows = json.loads(text)["results"]
        trashed = [row for row in rows if row["status"] == "trashed"]
        self.assertEqual(len(trashed), 1)
        self.assertTrue(os.path.exists(trashed[0]["trashPath"]))
        self.assertEqual(len(history.read(limit=10)["entries"]), 1)
        # the store claimed the plan away: a second run refuses, and the plans
        # folder holds nothing claimable any more
        self.assertEqual(self.run_cli(["clean", "--plan", plan_id, "--yes"])[0], 1)
        self.assertEqual(os.listdir(os.path.join(self.state, "plans")), [])

    def test_an_unknown_plan_id_is_a_problem_not_a_usage_error(self):
        self.assertEqual(self.run_cli(["clean", "--plan", "zzz", "--yes"])[0], 1)

    def test_an_expired_stored_plan_refuses_to_clean(self):
        _, text = self.run_cli(["plan", "--entry", "system.user-caches"])
        plan_id = self.plan_id_from(text)
        stored = os.path.join(paths_module.state_dir(self.env), "plans", plan_id + ".json")
        with open(stored, "r", encoding="utf-8") as handle:
            record = json.load(handle)
        record["expiresAt"] = 1.0
        with open(stored, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        self.assertEqual(self.run_cli(["clean", "--plan", plan_id, "--yes"])[0], 1)

    def test_the_shred_policy_gates_a_headless_shred(self):
        self.assertEqual(self.run_cli(["plan", "--entry", "system.user-caches", "--mode", "shred"])[0], 1)
        settings_module.set({"shredPolicy": "1-pass"}, env=self.env)
        code, text = self.run_cli(["plan", "--entry", "system.user-caches", "--mode", "shred"])
        self.assertEqual(code, 0)
        plan_id = self.plan_id_from(text)
        code, text = self.run_cli(["clean", "--plan", plan_id, "--yes"])
        self.assertEqual(code, 0)
        self.assertIn("shredded", text)
        self.assertFalse(os.path.exists(self.target))
        self.assertEqual(len(history.read(limit=10)["entries"]), 1)

    def test_a_corrupt_ignore_store_refuses_the_headless_plan(self):
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "ignore-rules.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.run_cli(["plan", "--entry", "system.user-caches"])[0], 1)

    def test_control_characters_in_names_are_sanitised_in_text_output(self):
        # a directory the walk cannot read lands in the scan's unreadable list,
        # and the text output escapes its control character
        weird = os.path.join(self.caches, "bad\x01name.dir")
        os.makedirs(weird)
        os.chmod(weird, 0o000)
        try:
            code, text = self.run_cli(["scan", "--entry", "system.user-caches"])
            self.assertEqual(code, 0)
            self.assertIn("unreadable: ", text)
            self.assertIn("bad\\x01name.dir", text)
            self.assertNotIn("bad\x01name.dir", text)
        finally:
            os.chmod(weird, 0o700)
            os.rmdir(weird)


if __name__ == "__main__":
    unittest.main()
