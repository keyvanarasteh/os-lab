"""CLN-17 tests: the ignore-rule store, matching, and engine enforcement.

The behaviours the task calls out get dedicated tests: the typed store with
settings-store discipline (roundtrip, validation, dedup, fail-closed corrupt
store), the three matching semantics (``path`` covers the subtree, ``glob``
matches at any depth, ``extension`` case-insensitively), the scan prune, and
the plan refusals — ``ignored`` for a direct match, ``contains-ignored`` for a
folder holding an ignored path (by rule and by walk), and
``ignore-store-corrupt`` failing the plan closed — plus the project sweep and
the Space Explorer pruning against the same rules and the `labctl cleanup
ignore` command surface. Every test runs on a generated temp tree — never a
real user folder (rule 8).
"""
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import clean  # noqa: E402
from cleanup_lab import cli  # noqa: E402
from cleanup_lab import deep  # noqa: E402
from cleanup_lab import explorer  # noqa: E402
from cleanup_lab import ignore as ignore_module  # noqa: E402
from cleanup_lab import paths as paths_module  # noqa: E402
from cleanup_lab import scan as scan_module  # noqa: E402

ROOT = str(pathlib.Path(__file__).resolve().parents[3])


def make_entry(entry_id, paths, **overrides):
    entry = {
        "id": entry_id,
        "name": entry_id,
        "family": entry_id.split(".")[0],
        "category": "system",
        "risk": "low",
        "hint": "hint",
        "impact": "impact",
        "defaultSelected": True,
        "needsPrivilege": False,
        "owningProcesses": [],
        "detector": "paths",
        "paths": paths,
    }
    entry.update(overrides)
    return entry


class StoreTests(unittest.TestCase):
    """The typed store: validation, dedup, discipline, fail-closed reads."""

    platform = "macos"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-ignore-")
        self.env = {"HOME": self.tmp.name, "USERPROFILE": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def store_path(self):
        return os.path.join(paths_module.state_dir(self.env, self.platform), "ignore-rules.json")

    def test_roundtrip_add_list_remove(self):
        rule = ignore_module.add_rule("path", os.path.join(self.tmp.name, "keep"), env=self.env)
        self.assertEqual(rule["type"], "path")
        glob_rule = ignore_module.add_rule("glob", "*.draft", note="working files", env=self.env)
        ext_rule = ignore_module.add_rule("extension", ".log", env=self.env)
        self.assertEqual(ext_rule["value"], "log")  # the leading dot is stripped
        rules, problem = ignore_module.load_rules(self.env, self.platform)
        self.assertIsNone(problem)
        self.assertEqual([r["id"] for r in rules], [rule["id"], glob_rule["id"], ext_rule["id"]])
        self.assertTrue(ignore_module.remove_rule(rule["id"], env=self.env))
        rules, _ = ignore_module.load_rules(self.env, self.platform)
        self.assertEqual([r["id"] for r in rules], [glob_rule["id"], ext_rule["id"]])
        self.assertFalse(ignore_module.remove_rule("nope", env=self.env))

    def test_path_rules_must_be_absolute_and_useful(self):
        for bad in ("keep", "", "  ", "/"):
            with self.assertRaises(ValueError):
                ignore_module.add_rule("path", bad, env=self.env)
        with self.assertRaises(ValueError):
            ignore_module.add_rule("path", self.tmp.name, env=self.env)  # the home folder
        with self.assertRaises(ValueError):
            ignore_module.add_rule("path", "with\x00nul", env=self.env)
        with self.assertRaises(ValueError):
            ignore_module.add_rule("wat", "x", env=self.env)

    def test_a_trailing_separator_is_normalised(self):
        rule = ignore_module.add_rule(
            "path", os.path.join(self.tmp.name, "keep") + os.sep, env=self.env
        )
        self.assertFalse(rule["value"].endswith(os.sep))

    def test_extensions_reject_wildcards_and_store_lowercase(self):
        for bad in ("*", "a/b", "sp ace", ""):
            with self.assertRaises(ValueError):
                ignore_module.add_rule("extension", bad, env=self.env)
        rule = ignore_module.add_rule("extension", ".TMP", env=self.env)
        self.assertEqual(rule["value"], "tmp")

    def test_duplicate_type_and_value_is_refused(self):
        target = os.path.join(self.tmp.name, "keep")
        ignore_module.add_rule("path", target, env=self.env)
        with self.assertRaises(ValueError):
            ignore_module.add_rule("path", target + os.sep, env=self.env)

    def test_a_missing_store_means_no_rules_and_no_problem(self):
        rules, problem = ignore_module.load_rules(self.env, self.platform)
        self.assertEqual(rules, [])
        self.assertIsNone(problem)

    def test_a_corrupt_store_fails_closed(self):
        os.makedirs(paths_module.state_dir(self.env, self.platform), mode=0o700, exist_ok=True)
        for body in ("{not json", "[]", '{"version": 2, "rules": []}',
                     '{"version": 1, "rules": [{"id": "a"}]}',
                     '{"version": 1, "rules": [{"id": "a", "type": "wat", "value": "x"}]}'):
            with open(self.store_path(), "w", encoding="utf-8") as handle:
                handle.write(body)
            rules, problem = ignore_module.load_rules(self.env, self.platform)
            self.assertEqual(rules, [])
            self.assertIsNotNone(problem)
            self.assertEqual(problem["code"], "ignore-store-corrupt")

    def test_a_symlinked_store_is_refused(self):
        os.makedirs(paths_module.state_dir(self.env, self.platform), mode=0o700, exist_ok=True)
        link = self.store_path()
        os.symlink(os.path.join(self.tmp.name, "elsewhere.json"), link)
        _, problem = ignore_module.load_rules(self.env, self.platform)
        self.assertIsNotNone(problem)
        self.assertIn("symlink", problem["message"])

    def test_a_loose_permissions_store_is_refused(self):
        if os.name == "nt":
            self.skipTest("POSIX permission checks")
        os.makedirs(paths_module.state_dir(self.env, self.platform), mode=0o700, exist_ok=True)
        with open(self.store_path(), "w", encoding="utf-8") as handle:
            handle.write('{"version": 1, "rules": []}')
        os.chmod(self.store_path(), 0o644)
        _, problem = ignore_module.load_rules(self.env, self.platform)
        self.assertIsNotNone(problem)
        self.assertIn("0600", problem["message"])

    def test_the_store_file_is_private_and_the_write_is_atomic(self):
        if os.name == "nt":
            self.skipTest("POSIX permission checks")
        ignore_module.add_rule("glob", "*.tmp", env=self.env)
        folder = paths_module.state_dir(self.env, self.platform)
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)
        path = self.store_path()
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.islink(path))
        self.assertFalse(os.path.lexists(path + ".tmp"))


class MatchingTests(unittest.TestCase):
    """The three rule semantics: subtree paths, depth-free globs, suffixes."""

    def test_a_path_rule_covers_the_folder_and_everything_under_it(self):
        rule = {"id": "1", "type": "path", "value": "/Users/u/keep"}
        self.assertIsNotNone(ignore_module.match([rule], "/Users/u/keep"))
        self.assertIsNotNone(ignore_module.match([rule], "/Users/u/keep/child/deep.bin"))
        self.assertIsNone(ignore_module.match([rule], "/Users/u/keeper"))
        self.assertIsNone(ignore_module.match([rule], "/Users/u"))

    def test_a_glob_rule_matches_at_any_depth(self):
        rule = {"id": "1", "type": "glob", "value": "node_modules*"}
        self.assertIsNotNone(ignore_module.match([rule], "/Users/u/proj/node_modules"))
        self.assertIsNotNone(ignore_module.match([rule], "/Users/u/a/b/node_modules/x"))
        self.assertIsNone(ignore_module.match([rule], "/Users/u/proj/src"))

    def test_a_glob_rule_matches_a_full_path_pattern(self):
        rule = {"id": "1", "type": "glob", "value": "/Users/u/keep/*.bin"}
        self.assertIsNotNone(ignore_module.match([rule], "/Users/u/keep/a.bin"))
        self.assertIsNone(ignore_module.match([rule], "/Users/u/keep/sub/a.bin"))

    def test_an_extension_rule_matches_case_insensitively(self):
        rule = {"id": "1", "type": "extension", "value": "log"}
        self.assertIsNotNone(ignore_module.match([rule], "/Users/u/app.LOG"))
        self.assertIsNone(ignore_module.match([rule], "/Users/u/app.logx"))
        self.assertIsNone(ignore_module.match([rule], "/Users/u/logs"))

    def test_contains_is_strictly_inside(self):
        rule = {"id": "1", "type": "path", "value": "/Users/u/keep/data"}
        self.assertIsNotNone(ignore_module.contains([rule], "/Users/u/keep"))
        self.assertIsNone(ignore_module.contains([rule], "/Users/u/keep/data"))  # equal, not inside
        self.assertIsNone(ignore_module.contains([rule], "/Users/u/keeper/data"))


class PlanScanTests(unittest.TestCase):
    """The engine refuses to scan or plan against ignored or protected-by-rule paths."""

    platform = "macos"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-ignore-plan-")
        self.home = self.tmp.name
        self.env = {"HOME": self.home, "USERPROFILE": self.home}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, body=b"x"):
        target = os.path.join(self.home, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(body)
        return target

    def caches_entry(self, template="~/Library/Caches", **overrides):
        return make_entry("system.caches", {"macos": [template], "linux": [template]}, **overrides)

    def build(self, entries, entry_ids=None, **kwargs):
        entry_ids = entry_ids or [entry["id"] for entry in entries]
        return clean.build_plan(
            None,
            entry_ids,
            env=self.env,
            platform=self.platform,
            catalog_entries=entries,
            **kwargs,
        )

    def state_dir(self):
        return paths_module.state_dir(self.env, self.platform)

    def test_an_ignored_entry_path_is_skipped_not_planned(self):
        target = self.write("Library/Caches/data.bin")
        rule = ignore_module.add_rule("path", os.path.join(self.home, "Library", "Caches"), env=self.env)
        plan = self.build([self.caches_entry()])
        item = plan.payload["items"][0]
        self.assertEqual(item["status"], "skipped")
        self.assertEqual(item["code"], "ignored")
        self.assertEqual(item["reason"], "This path is ignored by the user's rules.")
        self.assertEqual(plan.payload["totals"]["ready"], 0)
        # passing the rule explicitly produces the same refusal
        plan2 = self.build([self.caches_entry()], rules=[rule])
        self.assertEqual(plan2.payload["items"][0]["code"], "ignored")

    def test_a_folder_holding_a_path_rule_inside_is_refused(self):
        self.write("Library/Caches/app/data.bin")
        self.write("Library/Caches/other.bin")
        ignore_module.add_rule(
            "path", os.path.join(self.home, "Library", "Caches", "app", "data.bin"), env=self.env
        )
        plan = self.build([self.caches_entry()])
        item = plan.payload["items"][0]
        self.assertEqual(item["status"], "skipped")
        self.assertEqual(item["code"], "contains-ignored")
        self.assertIn("not removed", item["reason"])

    def test_a_folder_holding_a_matching_glob_inside_is_refused_by_the_walk(self):
        self.write("Library/Caches/app/data.bin")
        self.write("Library/Caches/app/keep.me", b"keep")
        ignore_module.add_rule("glob", "*.bin", env=self.env)
        plan = self.build([self.caches_entry()])
        item = plan.payload["items"][0]
        self.assertEqual(item["status"], "skipped")
        self.assertEqual(item["code"], "contains-ignored")
        self.assertTrue(os.path.exists(os.path.join(self.home, "Library", "Caches", "app", "data.bin")))

    def test_extension_rules_protect_their_files_inside_a_planned_folder(self):
        self.write("Library/Caches/app/notes.log", b"precious")
        self.write("Library/Caches/app/cache.bin")
        ignore_module.add_rule("extension", "log", env=self.env)
        plan = self.build([self.caches_entry()])
        item = plan.payload["items"][0]
        self.assertEqual(item["code"], "contains-ignored")
        self.assertEqual(self._read(os.path.join(self.home, "Library", "Caches", "app", "notes.log")), b"precious")

    def test_a_corrupt_store_refuses_every_plan_fail_closed(self):
        self.write("Library/Caches/data.bin")
        os.makedirs(self.state_dir(), mode=0o700, exist_ok=True)
        with open(os.path.join(self.state_dir(), "ignore-rules.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        for mode in ("trash", "delete"):
            with self.assertRaises(clean.PlanError) as caught:
                self.build([self.caches_entry()], mode=mode)
            self.assertEqual(caught.exception.code, "ignore-store-corrupt")

    def test_an_unreadable_store_refuses_the_scan_fail_closed(self):
        self.write("Library/Caches/data.bin")
        os.makedirs(self.state_dir(), mode=0o700, exist_ok=True)
        with open(os.path.join(self.state_dir(), "ignore-rules.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(scan_module.ScanError) as caught:
            scan_module.scan_catalog(
                None, env=self.env, platform=self.platform,
                catalog_entries=[self.caches_entry()],
            )
        self.assertIn("ignore-store-corrupt", str(caught.exception))

    def test_the_scan_skips_ignored_paths_and_counts_them(self):
        kept = self.write("Library/Keep/data.bin")
        dropped = self.write("Library/Caches/data.bin")
        entry = self.caches_entry(template="~/Library/Keep")
        entry2 = self.caches_entry(template="~/Library/Caches")
        entry2["id"] = "system.caches2"
        ignore_module.add_rule("path", os.path.join(self.home, "Library", "Caches"), env=self.env)
        result = scan_module.scan_catalog(
            None, env=self.env, platform=self.platform,
            catalog_entries=[entry, entry2],
        )
        by_entry = {r["id"]: r for r in result["entries"]}
        self.assertTrue(by_entry["system.caches"]["paths"][0]["measured"])
        ignored_report = by_entry["system.caches2"]["paths"][0]
        self.assertTrue(ignored_report["ignored"])
        self.assertFalse(ignored_report["measured"])
        self.assertIn("ignored", ignored_report["reason"])
        self.assertEqual(result["totals"]["ignoredPaths"], 1)
        self.assertEqual(os.path.getsize(kept), 1)
        self.assertTrue(os.path.exists(dropped))

    def _read(self, path):
        with open(path, "rb") as handle:
            return handle.read()


if __name__ == "__main__":
    unittest.main()


class DeepSweepTests(unittest.TestCase):
    """The project sweep prunes against the same rules — and fails closed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-ignore-deep-")
        self.home = self.tmp.name
        self.env = {"HOME": self.home, "USERPROFILE": self.home}
        self.projects = os.path.join(self.home, "Projects")
        os.makedirs(self.projects)
        web = os.path.join(self.projects, "web")
        os.makedirs(web)
        with open(os.path.join(web, "package.json"), "w") as handle:
            handle.write("{}")
        cache = os.path.join(web, "node_modules")
        os.makedirs(cache)
        with open(os.path.join(cache, "file"), "wb") as handle:
            handle.write(b"12345")

    def tearDown(self):
        self.tmp.cleanup()

    def _sweep(self):
        return deep.sweep(ROOT, ["home-projects"], env=self.env, platform="linux")

    def test_the_sweep_reports_a_candidate_without_rules(self):
        result = self._sweep()
        self.assertEqual({item["id"] for item in result["items"]}, {"projects.node-modules"})

    def test_the_sweep_refuses_an_ignored_candidate(self):
        ignore_module.add_rule("glob", "node_modules", env=self.env, platform="linux")
        self.assertEqual(self._sweep()["items"], [])

    def test_the_sweep_prunes_the_subtree_of_an_ignored_folder(self):
        ignore_module.add_rule("path", os.path.join(self.projects, "web"), env=self.env, platform="linux")
        self.assertEqual(self._sweep()["items"], [])

    def test_the_sweep_refuses_a_corrupt_store(self):
        state = paths_module.state_dir(self.env, "linux")
        os.makedirs(state, mode=0o700, exist_ok=True)
        with open(os.path.join(state, "ignore-rules.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(deep.DeepError) as caught:
            self._sweep()
        self.assertIn("ignore-store-corrupt", str(caught.exception))


class ExplorerTests(unittest.TestCase):
    """The Space Explorer prunes ignored entries from the tree — and fails closed."""

    platform = "macos"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-ignore-explore-")
        self.base = self.tmp.name
        # The rules store must live outside the scanned tree: the registered
        # root is the temp home itself, and a store created inside it would
        # show up as an ordinary folder.
        self.state = os.path.join(self.tmp.name + "-state")
        os.makedirs(self.state, mode=0o700)
        self.env = {"HOME": self.base, "USERPROFILE": self.base, "PATH": "",
                    "OSLAB_CLEANUP_STATE": self.state}
        self.root = tempfile.mkdtemp(prefix="cln-ignore-explore-root-")
        os.makedirs(os.path.join(self.root, "cleanup-lab", "catalog"))
        with open(os.path.join(self.root, "cleanup-lab", "deep-roots.json"), "w") as handle:
            json.dump({"home-projects": self.base}, handle)
        demo = os.path.join(self.base, "projects", "demo")
        os.makedirs(demo)
        with open(os.path.join(demo, "f.bin"), "wb") as handle:
            handle.write(b"x" * 100)
        keep = os.path.join(self.base, "projects", "keep")
        os.makedirs(keep)
        with open(os.path.join(keep, "k.txt"), "wb") as handle:
            handle.write(b"y" * 10)

    def tearDown(self):
        self.tmp.cleanup()
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def _explore(self):
        return explorer.explore(self.root, "home-projects", env=self.env, platform=self.platform)

    def _projects_node(self, payload):
        return next(child for child in payload["tree"]["children"] if child["name"] == "projects")

    def test_the_explorer_prunes_ignored_entries_from_the_tree(self):
        ignore_module.add_rule(
            "path", os.path.join(self.base, "projects", "demo"),
            env=self.env, platform=self.platform,
        )
        payload = self._explore()
        projects = self._projects_node(payload)
        self.assertEqual({child["name"] for child in projects["children"]}, {"keep"})
        self.assertEqual(projects["ignored"], 1)  # demo was pruned, counted here
        self.assertEqual(payload["tree"]["sizeBytes"], 10)
        self.assertTrue(os.path.exists(os.path.join(self.base, "projects", "demo", "f.bin")))

    def test_an_extension_rule_prunes_its_files_from_the_tree(self):
        ignore_module.add_rule("extension", "bin", env=self.env, platform=self.platform)
        payload = self._explore()
        projects = self._projects_node(payload)
        demo = next(child for child in projects["children"] if child["name"] == "demo")
        self.assertEqual(demo["sizeBytes"], 0)
        self.assertEqual(demo["ignored"], 1)
        self.assertEqual(payload["tree"]["sizeBytes"], 10)

    def test_the_explorer_refuses_a_corrupt_store(self):
        state = paths_module.state_dir(self.env, self.platform)
        os.makedirs(state, mode=0o700, exist_ok=True)
        with open(os.path.join(state, "ignore-rules.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(explorer.ExplorerError) as caught:
            self._explore()
        self.assertIn("ignore-store-corrupt", str(caught.exception))


class CliIgnoreTests(unittest.TestCase):
    """`labctl cleanup ignore list|add|remove` — exit codes 0/1/2."""

    def run_cli(self, argv):
        stream = io.StringIO()
        code = cli.main(argv, stream=stream)
        return code, stream.getvalue()

    def test_ignore_list_prints_the_rules_as_json_and_text(self):
        rule = {"id": "abc123", "type": "glob", "value": "*.tmp"}
        with mock.patch.object(cli.ignore, "load_rules", return_value=([rule], None)):
            code, text = self.run_cli(["ignore", "list", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(text)["rules"][0]["id"], "abc123")
            code, text = self.run_cli(["ignore", "list"])
            self.assertEqual(code, 0)
            self.assertIn("Cleanup Lab ignore rules", text)
            self.assertIn("*.tmp", text)
            self.assertIn("abc123", text)

    def test_ignore_list_fails_closed_on_a_corrupt_store(self):
        problem = {"code": "ignore-store-corrupt", "message": "boom"}
        with mock.patch.object(cli.ignore, "load_rules", return_value=([], problem)):
            code, _ = self.run_cli(["ignore", "list", "--json"])
            self.assertEqual(code, 1)

    def test_ignore_add_validates_and_reports(self):
        self.assertEqual(self.run_cli(["ignore", "add"])[0], 2)
        self.assertEqual(self.run_cli(["ignore", "add", "wat", "x"])[0], 2)
        self.assertEqual(self.run_cli(["ignore", "add", "glob"])[0], 2)
        rule = {"id": "abc123", "type": "glob", "value": "*.tmp"}
        with mock.patch.object(cli.ignore, "add_rule", return_value=rule) as added:
            code, text = self.run_cli(["ignore", "add", "glob", "*.tmp", "--note", "drafts"])
            self.assertEqual(code, 0)
            self.assertIn("Added glob rule", text)
            self.assertEqual(added.call_args[0], ("glob", "*.tmp"))
            self.assertEqual(added.call_args[1]["note"], "drafts")
        with mock.patch.object(cli.ignore, "add_rule", side_effect=ValueError("bad value")):
            self.assertEqual(self.run_cli(["ignore", "add", "glob", "*.tmp"])[0], 2)
        with mock.patch.object(cli.ignore, "add_rule",
                               side_effect=cli.ignore.RulesError("unreadable store")):
            self.assertEqual(self.run_cli(["ignore", "add", "glob", "*.tmp"])[0], 1)

    def test_ignore_remove_reports_unknown_ids(self):
        self.assertEqual(self.run_cli(["ignore", "remove"])[0], 2)
        self.assertEqual(self.run_cli(["ignore", "remove", "abc", "extra"])[0], 2)
        with mock.patch.object(cli.ignore, "remove_rule", return_value=True):
            code, text = self.run_cli(["ignore", "remove", "abc123", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(text)["removed"], "abc123")
        with mock.patch.object(cli.ignore, "remove_rule", return_value=False):
            self.assertEqual(self.run_cli(["ignore", "remove", "abc123"])[0], 1)

    def test_ignore_add_and_remove_roundtrip_through_a_real_store(self):
        with tempfile.TemporaryDirectory(prefix="cln-ignore-cli-") as state:
            with mock.patch.dict(os.environ, {"OSLAB_CLEANUP_STATE": state}):
                code, _ = self.run_cli(["ignore", "add", "extension", "log"])
                self.assertEqual(code, 0)
                with open(os.path.join(state, "ignore-rules.json"), encoding="utf-8") as handle:
                    stored = json.load(handle)
                self.assertEqual(stored["rules"][0]["value"], "log")
                rule_id = stored["rules"][0]["id"]
                code, _ = self.run_cli(["ignore", "remove", rule_id])
                self.assertEqual(code, 0)
                with open(os.path.join(state, "ignore-rules.json"), encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["rules"], [])
