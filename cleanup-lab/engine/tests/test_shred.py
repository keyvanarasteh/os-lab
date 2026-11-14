"""CLN-14 tests: secure shred overwrites, renames, unlinks — and reports failures.

The behaviours the task calls out get dedicated tests: the passes really reach a
real temp file (zeros, ones, random, each fsynced), the random rename happens
and the name is gone, every injected failure (open, write, rename, unlink) is a
reported failure with honest bytes, folders are shredded bottom-up, symlinks
are never followed, and the policy gate refuses shred plans while Trash keeps
working. Every test runs on a generated tree under ``tempfile`` — never a real
user folder (rule 8).
"""
import errno
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import clean  # noqa: E402
from cleanup_lab import cli  # noqa: E402
from cleanup_lab import paths as paths_module  # noqa: E402
from cleanup_lab import settings as settings_module  # noqa: E402
from cleanup_lab import shred  # noqa: E402


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


class ShredTests(unittest.TestCase):
    platform = "macos"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-shred-")
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

    def read_bytes(self, path):
        with open(path, "rb") as handle:
            return handle.read()

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

    def run_plan(self, plan, **kwargs):
        """verify + execute, the way the console job runs a confirmed plan."""
        measures = clean.verify_plan(plan, **kwargs.pop("verify_kwargs", {}))
        return clean.execute_plan(plan, measures, env=self.env, platform=self.platform, **kwargs)

    def state_dir(self):
        return paths_module.state_dir(self.env, self.platform)

    def set_policy(self, value):
        settings_module.set({"shredPolicy": value}, env=self.env, platform=self.platform)

    def snapshotting_fsync(self, snapshots):
        """A fsync that records what each pass actually left in the file."""

        def fsync(fd):
            os.lseek(fd, 0, os.SEEK_SET)
            snapshots.append(os.read(fd, shred.CHUNK))
            os.fsync(fd)

        return fsync

    # ── the overwrite passes ─────────────────────────────────────────────────

    def test_one_pass_writes_zeros_then_renames_and_unlinks(self):
        target = self.write("Library/Caches/data.bin", b"secret" * 10)
        snapshots = []
        size = shred.shred_file(target, 1, fsync=self.snapshotting_fsync(snapshots))
        self.assertEqual(size, 60)
        self.assertEqual(snapshots, [b"\x00" * 60])
        self.assertFalse(os.path.lexists(target))
        self.assertEqual(os.listdir(os.path.dirname(target)), [])

    def test_three_passes_write_zeros_ones_then_random(self):
        target = self.write("Library/Caches/data.bin", b"secret" * 10)
        snapshots = []
        shred.shred_file(
            target, 3,
            fsync=self.snapshotting_fsync(snapshots),
            urandom=lambda size: b"\xab" * size,
        )
        self.assertEqual(snapshots, [b"\x00" * 60, b"\xff" * 60, b"\xab" * 60])
        self.assertFalse(os.path.lexists(target))

    def test_the_renamed_file_disappears_from_its_folder(self):
        renames = []

        def recording_rename(source, destination):
            renames.append(destination)
            return os.rename(source, destination)

        target = self.write("Library/Caches/data.bin", b"secret")
        shred.shred_file(target, 1, rename=recording_rename)
        self.assertEqual(len(renames), 1)
        self.assertTrue(os.path.basename(renames[0]).startswith(shred.RENAME_PREFIX))
        self.assertEqual(os.path.dirname(renames[0]), os.path.dirname(target))
        self.assertFalse(os.path.lexists(target))
        self.assertFalse(os.path.lexists(renames[0]))

    # ── every failure is reported, nothing is counted ────────────────────────

    def test_a_failing_open_leaves_the_file_alone(self):
        target = self.write("Library/Caches/data.bin", b"secret")

        def refusing_open(path):
            raise OSError(errno.EACCES, "Permission denied")

        with self.assertRaises(shred.ShredError) as caught:
            shred.shred_file(target, 1, open=refusing_open)
        self.assertIn("cannot be opened", str(caught.exception))
        self.assertEqual(self.read_bytes(target), b"secret")

    def test_a_failing_write_is_reported_not_swallowed(self):
        target = self.write("Library/Caches/data.bin", b"secret")

        def failing_write(fd, data):
            raise OSError(errno.EIO, "I/O error")

        with self.assertRaises(shred.ShredError) as caught:
            shred.shred_file(target, 1, write=failing_write)
        self.assertIn("Overwrite failed", str(caught.exception))
        self.assertTrue(os.path.lexists(target))

        summary, entries = shred.shred_path(target, 1, write=failing_write)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["bytes"], 0)
        self.assertEqual(entries[0]["status"], "failed")
        self.assertIn("Overwrite failed", entries[0]["error"])

    def test_a_failing_rename_reports_the_overwritten_contents(self):
        target = self.write("Library/Caches/data.bin", b"secret")

        def refusing_rename(source, destination):
            raise OSError(errno.EACCES, "Permission denied")

        with self.assertRaises(shred.ShredError) as caught:
            shred.shred_file(target, 1, rename=refusing_rename)
        self.assertIn("could not be renamed", str(caught.exception))
        self.assertTrue(os.path.lexists(target))

        summary, entries = shred.shred_path(target, 1, rename=refusing_rename)
        self.assertEqual(entries[0]["status"], "failed")
        self.assertEqual(summary["bytes"], 0)

    def test_a_failing_unlink_names_the_renamed_file(self):
        target = self.write("Library/Caches/data.bin", b"secret")
        real_unlink = os.unlink

        def failing_unlink(path):
            if os.path.basename(path).startswith(shred.RENAME_PREFIX):
                raise OSError(errno.EPERM, "Operation not permitted")
            return real_unlink(path)

        with self.assertRaises(shred.ShredError) as caught:
            shred.shred_file(target, 1, unlink=failing_unlink)
        self.assertIn("renamed file", str(caught.exception))
        leftovers = os.listdir(os.path.dirname(target))
        self.assertEqual(len(leftovers), 1)
        self.assertTrue(leftovers[0].startswith(shred.RENAME_PREFIX))

    # ── folders: bottom-up, links never followed, specials refused ───────────

    def test_a_folder_is_shredded_bottom_up(self):
        one = self.write("Library/Caches/app/one.bin", b"a" * 10)
        two = self.write("Library/Caches/app/nested/two.bin", b"b" * 20)
        caches = os.path.join(self.home, "Library", "Caches")
        app = os.path.join(caches, "app")
        nested = os.path.join(app, "nested")
        summary, entries = shred.shred_path(caches, 1)
        self.assertEqual(summary["files"], 2)
        self.assertEqual(summary["bytes"], 30)
        self.assertEqual(summary["folders"], 3)
        self.assertEqual(summary["errors"], 0)
        statuses = {entry["path"]: entry["status"] for entry in entries}
        self.assertEqual(statuses[one], "shredded")
        self.assertEqual(statuses[two], "shredded")
        removed = [entry["path"] for entry in entries if entry["status"] == "removed"]
        self.assertEqual(removed, [nested, app, caches])  # deepest first, root last
        self.assertFalse(os.path.exists(caches))

    def test_a_symlink_inside_the_tree_is_unlinked_never_followed(self):
        outside = self.write("Library/keep.bin", b"precious")
        self.write("Library/Caches/app/data.bin", b"x")
        link = os.path.join(self.home, "Library", "Caches", "app", "link.bin")
        os.symlink(outside, link)
        summary, entries = shred.shred_path(os.path.join(self.home, "Library", "Caches"), 1)
        self.assertEqual(summary["errors"], 0)
        by_status = {entry["path"]: entry["status"] for entry in entries}
        self.assertEqual(by_status[link], "unlinked")
        self.assertEqual(by_status[os.path.join(self.home, "Library", "Caches", "app", "data.bin")], "shredded")
        self.assertTrue(os.path.exists(outside))   # the referent is untouched
        self.assertFalse(os.path.lexists(link))    # the bare link is gone
        self.assertEqual(self.read_bytes(outside), b"precious")

    def test_a_symlink_target_is_refused(self):
        outside = self.write("Library/keep.bin", b"precious")
        link = os.path.join(self.home, "Library", "link.bin")
        os.symlink(outside, link)
        summary, entries = shred.shred_path(link, 1)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["bytes"], 0)
        self.assertEqual(entries[0]["status"], "failed")
        self.assertIn("never follows links", entries[0]["error"])
        self.assertTrue(os.path.lexists(link))
        self.assertEqual(self.read_bytes(outside), b"precious")

    def test_a_fifo_is_refused_and_blocks_the_folder_honestly(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("no mkfifo on this platform")
        caches = os.path.join(self.home, "Library", "Caches")
        os.makedirs(os.path.join(caches, "app"), exist_ok=True)
        pipe = os.path.join(caches, "app", "pipe")
        os.mkfifo(pipe)
        summary, entries = shred.shred_path(caches, 1)
        statuses = {entry["path"]: entry["status"] for entry in entries}
        errors = {entry["path"]: entry["error"] for entry in entries}
        self.assertEqual(statuses[pipe], "failed")
        self.assertIn("refused", errors[pipe])                              # the reason says so
        self.assertEqual(statuses[os.path.join(caches, "app")], "failed")   # ENOTEMPTY
        self.assertEqual(statuses[caches], "failed")                        # ENOTEMPTY
        self.assertEqual(summary["errors"], 3)
        self.assertEqual(summary["files"], 0)
        self.assertTrue(os.path.lexists(pipe))

    def test_an_unreadable_folder_is_reported(self):
        caches = os.path.join(self.home, "Library", "Caches")
        os.makedirs(caches, exist_ok=True)

        def refusing_scandir(path):
            raise OSError(errno.EACCES, "Permission denied")

        summary, entries = shred.shred_path(caches, 1, scandir=refusing_scandir)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(entries[0]["status"], "failed")
        self.assertIn("cannot be read", entries[0]["error"])
        self.assertTrue(os.path.isdir(caches))

    # ── the settings policy gates the shred mode ─────────────────────────────

    def test_the_policy_defaults_to_off_and_refuses_shred_plans(self):
        self.write("Library/Caches/data.bin", b"secret")
        with self.assertRaises(clean.PlanError) as caught:
            self.build([self.caches_entry()], mode="shred")
        self.assertEqual(caught.exception.code, "shred-disabled")
        self.assertIn("Secure shred is disabled", str(caught.exception))

    def test_policy_on_plans_and_runs_a_shred(self):
        self.set_policy("3-pass")
        target = self.write("Library/Caches/data.bin", b"secret")
        plan = self.build([self.caches_entry()], mode="shred")
        self.assertEqual(plan.mode, "shred")
        self.assertEqual(plan.payload["shredPasses"], 3)
        item = plan.payload["items"][0]
        self.assertEqual(item["mode"], "shred")
        self.assertEqual(item["status"], "ready")
        result = self.run_plan(plan)
        row = result["results"][0]
        self.assertEqual(row["status"], "shredded")
        self.assertIsNone(row["trashPath"])
        self.assertFalse(os.path.lexists(target))
        self.assertEqual(len(row["shred"]), 2)  # the file, then the folder
        self.assertEqual(result["totals"], {
            "items": 1, "trashed": 0, "deleted": 0, "skipped": 0, "failed": 0,
            "bytes": 6, "files": 1, "folders": 1,
            "shredded": 1,
        })

    def test_the_default_mode_stays_trash_even_when_the_policy_is_on(self):
        self.set_policy("1-pass")
        target = self.write("Library/Caches/data.bin", b"secret")
        result = self.run_plan(self.build([self.caches_entry()]))
        row = result["results"][0]
        self.assertEqual(result["mode"], "trash")
        self.assertNotIn("shredded", result["totals"])
        self.assertEqual(row["status"], "trashed")
        self.assertFalse(os.path.lexists(target))          # the original moved away…
        trashed_file = os.path.join(row["trashPath"], "data.bin")
        self.assertTrue(os.path.lexists(trashed_file))     # …and survives in the Trash
        with open(trashed_file, "rb") as handle:
            self.assertEqual(handle.read(), b"secret")

    def test_corrupt_settings_fail_shred_closed_and_never_block_trash(self):
        self.write("Library/Caches/data.bin", b"secret")
        os.makedirs(self.state_dir(), mode=0o700, exist_ok=True)
        with open(os.path.join(self.state_dir(), "settings.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(clean.PlanError) as caught:
            self.build([self.caches_entry()], mode="shred")
        self.assertEqual(caught.exception.code, "shred-settings-corrupt")
        result = self.run_plan(self.build([self.caches_entry()]))
        self.assertEqual(result["results"][0]["status"], "trashed")

    def test_the_guard_still_refuses_a_running_app_for_shred(self):
        self.set_policy("1-pass")
        self.write("Library/Caches/app/data.bin", b"secret")
        busy = self.caches_entry(owningProcesses=["DemoApp"])
        plan = self.build([busy], mode="shred", names=["DemoApp"])
        self.assertEqual(plan.payload["items"][0]["code"], "app-running")

    def test_a_partial_shred_keeps_the_honest_bytes_and_reports_the_rest(self):
        self.set_policy("1-pass")
        good = self.write("Library/Caches/good.bin", b"a" * 10)
        bad = self.write("Library/Caches/bad.bin", b"b" * 20)
        os.chmod(bad, 0o400)  # the overwrite will be refused with EACCES
        plan = self.build([self.caches_entry()], mode="shred")
        result = self.run_plan(plan)
        row = result["results"][0]
        self.assertEqual(row["status"], "failed")
        self.assertIn("cannot be opened", row["error"])
        # good.bin is verifiably gone and is counted; bad.bin is still there.
        self.assertEqual(row["bytes"], 10)
        self.assertEqual(row["files"], 1)
        self.assertEqual(row["folders"], 0)
        self.assertEqual(self.read_bytes(bad), b"b" * 20)
        self.assertFalse(os.path.lexists(good))
        statuses = {entry["path"]: entry["status"] for entry in row["shred"]}
        self.assertEqual(statuses[good], "shredded")
        self.assertEqual(statuses[bad], "failed")
        self.assertEqual(result["totals"]["bytes"], 10)
        self.assertEqual(result["totals"]["shredded"], 0)
        self.assertEqual(result["totals"]["failed"], 1)

    # ── the settings store itself ────────────────────────────────────────────

    def test_the_settings_store_roundtrips_and_validates(self):
        self.assertEqual(
            settings_module.shred_policy(env=self.env, platform=self.platform),
            ("off", None),
        )
        stored = settings_module.set({"shredPolicy": "3-pass"}, env=self.env, platform=self.platform)
        self.assertEqual(stored, {"shredPolicy": "3-pass"})
        self.assertEqual(
            settings_module.get("shredPolicy", env=self.env, platform=self.platform),
            "3-pass",
        )
        self.assertEqual(
            settings_module.shred_policy(env=self.env, platform=self.platform),
            ("3-pass", None),
        )
        for bad in ({"nope": "1-pass"}, {"shredPolicy": "5-pass"}, {"shredPolicy": 3}, "3-pass"):
            with self.assertRaises(ValueError):
                settings_module.set(bad, env=self.env, platform=self.platform)
        with self.assertRaises(ValueError):
            settings_module.get("nope", env=self.env, platform=self.platform)

    def test_the_settings_store_is_private_and_atomic(self):
        if os.name == "nt":
            self.skipTest("POSIX permission checks")
        self.set_policy("1-pass")
        folder = self.state_dir()
        path = os.path.join(folder, "settings.json")
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)
        self.assertFalse(os.path.islink(path))
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"shredPolicy": "1-pass"})
        self.assertFalse(os.path.lexists(path + ".tmp"))

    def test_broken_values_in_the_settings_file_fail_closed(self):
        self.set_policy("1-pass")
        path = os.path.join(self.state_dir(), "settings.json")
        for body in ('{"shredPolicy": "bogus"}', '{"shredPolicy": 1}', "[]"):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
            policy, problem = settings_module.shred_policy(env=self.env, platform=self.platform)
            self.assertEqual(policy, "off")
            self.assertIsNotNone(problem)
            self.assertEqual(problem["code"], "settings-corrupt")

    def test_a_missing_state_folder_means_the_default_policy(self):
        self.assertEqual(
            settings_module.shred_policy(env=self.env, platform=self.platform),
            ("off", None),
        )
        self.write("Library/Caches/data.bin", b"secret")  # trash planning works regardless
        plan = self.build([self.caches_entry()])
        self.assertEqual(plan.mode, "trash")


if __name__ == "__main__":
    unittest.main()


class SettingsSurfaceTests(unittest.TestCase):
    """`labctl cleanup settings` and the all_values helper (CLN-14 slice 3)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-settings-")
        self.state = os.path.join(self.tmp.name, "state")
        os.makedirs(self.state, mode=0o700)
        self.env = {"OSLAB_CLEANUP_STATE": self.state}
        # The CLI reads os.environ — pin it to the generated store so the
        # tests never touch a real user's settings (rule 8).
        patcher = mock.patch.dict(os.environ, {"OSLAB_CLEANUP_STATE": self.state})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv):
        stream = io.StringIO()
        code = cli.main(argv, stream=stream)
        return code, stream.getvalue()

    def test_all_values_defaults_and_roundtrip(self):
        values, problem = settings_module.all_values(env=self.env)
        self.assertIsNone(problem)
        self.assertEqual(values, {"shredPolicy": "off"})
        settings_module.set({"shredPolicy": "3-pass"}, env=self.env)
        values, _ = settings_module.all_values(env=self.env)
        self.assertEqual(values, {"shredPolicy": "3-pass"})

    def test_all_values_reports_a_corrupt_store(self):
        with open(os.path.join(self.state, "settings.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        values, problem = settings_module.all_values(env=self.env)
        self.assertEqual(values, {"shredPolicy": "off"})
        self.assertIsNotNone(problem)
        self.assertEqual(problem["code"], "settings-corrupt")

    def test_cli_show_prints_the_store_and_fails_closed(self):
        code, text = self.run_cli(["settings", "show"])
        self.assertEqual(code, 0)
        self.assertIn("shredPolicy", text)
        code, text = self.run_cli(["settings", "show", "--json"])
        self.assertEqual(json.loads(text)["settings"]["shredPolicy"], "off")
        with open(os.path.join(self.state, "settings.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.run_cli(["settings", "show"])[0], 1)

    def test_cli_set_validates_and_persists(self):
        self.assertEqual(self.run_cli(["settings", "set"])[0], 2)
        self.assertEqual(self.run_cli(["settings", "set", "shredPolicy"])[0], 2)
        self.assertEqual(self.run_cli(["settings", "set", "nope", "1-pass"])[0], 2)
        self.assertEqual(self.run_cli(["settings", "set", "shredPolicy", "5-pass"])[0], 2)
        code, text = self.run_cli(["settings", "set", "shredPolicy", "1-pass"])
        self.assertEqual(code, 0)
        self.assertIn("shredPolicy = 1-pass", text)
        code, text = self.run_cli(["settings", "show", "--json"])
        self.assertEqual(json.loads(text)["settings"]["shredPolicy"], "1-pass")
