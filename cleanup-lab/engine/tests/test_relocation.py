"""CLN-27: typed move/restore/relink plans and a crash-safe executor.

Every test uses a generated tree under ``tempfile`` — never a real cache or home
folder (rule 8). The executor is driven directly, so the failure at every step is
deterministic rather than simulated with a full console job.
"""
import errno
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import relocation as rel  # noqa: E402
from cleanup_lab.relocation import FolderStatus as S  # noqa: E402


class FlipAfter:
    """A cancel flag that flips to True after N calls."""

    def __init__(self, calls):
        self.calls = calls

    def is_set(self):
        self.calls -= 1
        return self.calls < 0


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-relocation-")
        root = os.path.realpath(self.tmp.name)
        self.home_volume = os.path.join(root, "home-volume")
        self.store_volume = os.path.join(root, "store-volume")
        self.home = os.path.join(self.home_volume, ".npm")
        self.store = os.path.join(self.store_volume, "os-lab-caches", "npm")
        os.makedirs(self.home_volume)
        os.makedirs(self.store_volume)
        os.makedirs(os.path.dirname(self.store))

    def tearDown(self):
        self.tmp.cleanup()

    def make_home(self, root=None):
        root = root or self.home
        os.makedirs(os.path.join(root, "sub"), exist_ok=True)
        with open(os.path.join(root, "sub", "one.bin"), "wb") as handle:
            handle.write(b"x" * 100)
        with open(os.path.join(root, "two.bin"), "wb") as handle:
            handle.write(b"y" * 25)
        return root

    def plan(self, action="move", *, home=None, store=None, free_bytes=10**12, **kwargs):
        return rel.build_plan(
            home or self.home,
            store or self.store,
            action,
            volume_id=self.store_volume,
            destination_root=self.store_volume if action == "move" else self.home_volume,
            free_bytes=free_bytes,
            clock=lambda: 1000.0,
            **kwargs,
        )

    def execute(self, plan, **kwargs):
        return rel.execute(plan, clock=lambda: 1001.0, **kwargs)

    # ── classification: the seven states ────────────────────────────────────

    def test_every_state_is_classified(self):
        self.assertIs(rel.classify(self.home, self.store), S.MISSING)
        self.make_home()
        self.assertIs(rel.classify(self.home, self.store), S.LOCAL_ONLY)
        os.makedirs(self.store)
        self.assertIs(rel.classify(self.home, self.store), S.CONFLICT)
        shutil.rmtree(self.home)
        self.assertIs(rel.classify(self.home, self.store), S.MISSING_LINK)
        os.symlink(self.store, self.home)
        self.assertIs(rel.classify(self.home, self.store), S.LINKED_OK)
        os.rmdir(self.store)
        self.assertIs(rel.classify(self.home, self.store), S.BROKEN_LINK)
        other = os.path.join(self.store_volume, "other")
        os.makedirs(other)
        os.unlink(self.home)
        os.symlink(other, self.home)
        self.assertIs(rel.classify(self.home, self.store), S.WRONG_TARGET)

    def test_relative_link_target_is_resolved_from_the_link_directory(self):
        os.makedirs(self.store)
        os.symlink(os.path.relpath(self.store, os.path.dirname(self.home)), self.home)
        self.assertIs(rel.classify(self.home, self.store), S.LINKED_OK)

    def test_fingerprint_counts_files_and_links_without_following(self):
        self.make_home()
        os.symlink("/", os.path.join(self.home, "rootlink"))
        self.assertEqual(rel.tree_fingerprint(self.home), (3, 125))
        self.assertEqual(rel.measure(self.home), (3, 125))

    # ── planning ─────────────────────────────────────────────────────────────

    def test_move_plan_verifies_before_anything_is_removed(self):
        self.make_home()
        plan = self.plan()
        ops = [step.op for step in plan.steps]
        self.assertEqual(
            ops, ["copy", "verify_copy", "rename", "symlink", "verify_link", "remove_tree"]
        )
        self.assertLess(ops.index("verify_copy"), ops.index("remove_tree"))
        self.assertEqual(plan.steps[-1].src, self.home + rel.ASIDE_SUFFIX)
        self.assertEqual(plan.size_bytes, 125)
        self.assertEqual(plan.status, "local_only")
        self.assertIsNone(plan.interrupted)
        self.assertEqual(plan.expires_at, 1000.0 + rel.PLAN_TTL)

    def test_move_is_refused_without_space_or_in_a_wrong_state(self):
        self.make_home()
        with self.assertRaises(rel.RelocationError) as caught:
            self.plan(free_bytes=0)
        self.assertEqual(caught.exception.code, "no-space")
        os.makedirs(self.store)
        with self.assertRaises(rel.RelocationError) as caught:
            self.plan()
        self.assertEqual(caught.exception.code, "state")

    def test_destination_must_be_inside_the_configured_volume(self):
        self.make_home()
        outside = os.path.join(self.home_volume, "elsewhere")
        os.makedirs(outside)
        with self.assertRaises(rel.RelocationError) as caught:
            rel.build_plan(
                self.home, os.path.join(outside, "npm"), "move",
                volume_id=self.store_volume, destination_root=self.store_volume,
                free_bytes=10**12,
            )
        self.assertEqual(caught.exception.code, "destination-outside")

    def test_plans_are_refused_for_bad_actions_and_nesting(self):
        self.make_home()
        with self.assertRaises(rel.RelocationError) as caught:
            self.plan("shred")
        self.assertEqual(caught.exception.code, "bad-action")
        with self.assertRaises(rel.RelocationError) as caught:
            self.plan(store=os.path.join(self.home, "store"))
        self.assertIn(caught.exception.code, ("nested", "destination-outside"))

    def test_an_interrupted_move_asks_for_a_resume(self):
        self.make_home()
        os.rename(self.home, self.home + rel.ASIDE_SUFFIX)
        with self.assertRaises(rel.RelocationError) as caught:
            self.plan()
        self.assertEqual(caught.exception.code, "interrupted")
        self.assertEqual(rel.interrupted_kind(self.home, self.store), "move")
        self.assertEqual([step.op for step in self.plan("resume").steps], ["rename"])

    # ── executing a move ─────────────────────────────────────────────────────

    def test_a_confirmed_move_copies_verifies_links_then_removes_the_aside(self):
        self.make_home()
        plan = self.plan()
        result = self.execute(plan)
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["preserved"], "store")
        self.assertEqual(result["linkStatus"], "linked_ok")
        self.assertTrue(os.path.islink(self.home))
        self.assertTrue(rel._same(rel._link_target(self.home), self.store))
        self.assertFalse(os.path.lexists(self.home + rel.ASIDE_SUFFIX))
        with open(os.path.join(self.store, "sub", "one.bin"), "rb") as handle:
            self.assertEqual(handle.read(), b"x" * 100)
        self.assertTrue(all(step["state"] == "done" for step in result["steps"]))
        self.assertEqual(result["progress"]["stepsDone"], 6)

    def test_a_file_can_be_relocated(self):
        self.make_home()
        first = os.path.join(self.home, "two.bin")
        plan = self.plan(home=first, store=os.path.join(self.store_volume, "one-file"))
        result = self.execute(plan)
        self.assertEqual(result["state"], "done")
        self.assertTrue(os.path.islink(first))
        with open(os.path.join(self.store_volume, "one-file"), "rb") as handle:
            self.assertEqual(handle.read(), b"y" * 25)

    def test_a_symlink_inside_the_tree_is_preserved_not_followed(self):
        self.make_home()
        target = os.path.join(self.home_volume, "outside.bin")
        with open(target, "wb") as handle:
            handle.write(b"outside")
        os.symlink(target, os.path.join(self.home, "link.bin"))
        plan = self.plan()
        result = self.execute(plan)
        self.assertEqual(result["state"], "done")
        copied = os.path.join(self.store, "link.bin")
        self.assertTrue(os.path.islink(copied))
        self.assertEqual(os.readlink(copied), target)
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"outside")

    # ── failure at every step ────────────────────────────────────────────────

    def test_a_failed_copy_leaves_the_original_untouched(self):
        self.make_home()
        plan = self.plan()

        def refuse(src, dst, **kwargs):
            raise OSError(errno.EACCES, "Permission denied")

        result = self.execute(plan, copy_tree=refuse)
        self.assertEqual(result["state"], "failed")
        self.assertIn("Permission denied", result["error"])
        self.assertEqual(result["preserved"], "original")
        self.assertTrue(os.path.isdir(self.home))
        self.assertTrue(os.path.exists(os.path.join(self.home, "two.bin")))
        self.assertFalse(os.path.lexists(self.store))

    def test_a_mismatched_copy_leaves_the_original_untouched(self):
        self.make_home()
        plan = self.plan()
        with mock.patch.object(
            rel, "_verify_copy", side_effect=rel.RelocationError("copy is short", "copy-mismatch")
        ):
            result = self.execute(plan)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["steps"][1]["state"], "failed")
        self.assertEqual(result["preserved"], "original")
        self.assertTrue(os.path.isdir(self.home))

    def test_a_failed_rename_leaves_the_original_and_a_verified_copy(self):
        self.make_home()
        plan = self.plan()

        def refuse(src, dst):
            raise OSError(errno.EACCES, "Permission denied")

        result = self.execute(plan, rename=refuse)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["preserved"], "original")
        self.assertTrue(os.path.isdir(self.home))
        self.assertEqual(rel.measure(self.store), (2, 125))

    def test_a_failed_symlink_leaves_the_aside_original_and_can_resume(self):
        self.make_home()
        plan = self.plan()

        def refuse(target, path):
            raise OSError(errno.EACCES, "Permission denied")

        result = self.execute(plan, symlink=refuse)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["preserved"], "aside")
        self.assertFalse(os.path.lexists(self.home))
        self.assertTrue(os.path.isdir(self.home + rel.ASIDE_SUFFIX))
        self.assertEqual(rel.interrupted_kind(self.home, self.store), "move")

        resumed = self.execute(self.plan("resume"))
        self.assertEqual(resumed["state"], "done")
        self.assertTrue(os.path.islink(self.home))
        self.assertFalse(os.path.lexists(self.home + rel.ASIDE_SUFFIX))

    def test_a_wrong_link_is_repaired_by_resume(self):
        self.make_home()
        plan = self.plan()

        def wrong_link(target, path):
            return os.symlink(os.path.join(self.home_volume, "wrong"), path)

        result = self.execute(plan, symlink=wrong_link)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(rel.interrupted_kind(self.home, self.store), "move")
        resumed = self.execute(self.plan("resume"))
        self.assertEqual(resumed["state"], "done")
        self.assertTrue(rel._same(rel._link_target(self.home), self.store))

    def test_a_failed_aside_removal_keeps_the_link_and_resumes(self):
        self.make_home()
        plan = self.plan()
        aside = self.home + rel.ASIDE_SUFFIX

        def refuse(path):
            if path == aside:
                raise OSError(errno.EACCES, "Permission denied")
            return os.rmdir(path)

        result = self.execute(plan, rmdir=refuse)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["linkStatus"], "linked_ok")
        self.assertTrue(os.path.islink(self.home))
        self.assertTrue(os.path.isdir(aside))

        resumed = self.execute(self.plan("resume"))
        self.assertEqual(resumed["state"], "done")
        self.assertFalse(os.path.lexists(aside))

    def test_resume_rolls_back_when_no_store_copy_survived(self):
        self.make_home()
        aside = self.home + rel.ASIDE_SUFFIX
        os.rename(self.home, aside)
        plan = self.plan("resume")
        self.assertEqual([step.op for step in plan.steps], ["rename"])
        result = self.execute(plan)
        self.assertEqual(result["state"], "done")
        self.assertTrue(os.path.isdir(self.home))
        self.assertFalse(os.path.lexists(aside))
        self.assertEqual(rel.classify(self.home, self.store), S.LOCAL_ONLY)

    def test_cancel_between_steps_stops_without_removing_more(self):
        self.make_home()
        plan = self.plan()
        result = self.execute(plan, cancel=FlipAfter(1))
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["preserved"], "original")
        self.assertTrue(os.path.isdir(self.home))
        states = [step["state"] for step in result["steps"]]
        self.assertEqual(states[0], "done")
        self.assertEqual(set(states[1:]), {"skipped"})

    # ── restore and relink ───────────────────────────────────────────────────

    def linked(self):
        self.make_home()
        self.execute(self.plan())
        return rel.classify(self.home, self.store)

    def test_restore_copies_back_and_keeps_the_store(self):
        self.assertEqual(self.linked(), S.LINKED_OK)
        plan = rel.build_plan(
            self.home, self.store, "restore",
            volume_id=self.home_volume, destination_root=self.home_volume,
            free_bytes=10**12, clock=lambda: 1000.0,
        )
        self.assertEqual([step.op for step in plan.steps],
                         ["copy", "verify_copy", "remove_link", "rename"])
        result = self.execute(plan)
        self.assertEqual(result["state"], "done")
        self.assertFalse(os.path.islink(self.home))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "two.bin")))
        self.assertTrue(os.path.isfile(os.path.join(self.store, "two.bin")))

    def test_restore_can_remove_the_store_only_when_the_plan_says_so(self):
        self.linked()
        steps = rel.plan_restore(self.home, self.store, keep_store_copy=False)
        self.assertEqual(steps[-1].op, "remove_tree")
        plan = rel.build_plan(
            self.home, self.store, "restore",
            volume_id=self.home_volume, destination_root=self.home_volume,
            free_bytes=10**12, clock=lambda: 1000.0,
        )
        plan.steps = steps
        result = self.execute(plan)
        self.assertEqual(result["state"], "done")
        self.assertFalse(os.path.lexists(self.store))
        self.assertTrue(os.path.isdir(self.home))

    def test_relink_repairs_a_missing_or_wrong_link(self):
        os.makedirs(self.store)
        with open(os.path.join(self.store, "one.bin"), "wb") as handle:
            handle.write(b"x")
        plan = rel.build_plan(
            self.home, self.store, "relink",
            volume_id=self.store_volume, destination_root=self.store_volume,
            free_bytes=10**12,
        )
        self.assertEqual([step.op for step in plan.steps], ["symlink", "verify_link"])
        self.assertEqual(self.execute(plan)["state"], "done")
        self.assertTrue(os.path.islink(self.home))

        wrong = os.path.join(self.home_volume, "wrong")
        os.makedirs(wrong)
        os.unlink(self.home)
        os.symlink(wrong, self.home)
        self.assertEqual(rel.classify(self.home, self.store), S.WRONG_TARGET)
        plan = rel.build_plan(
            self.home, self.store, "relink",
            volume_id=self.store_volume, destination_root=self.store_volume,
            free_bytes=10**12,
        )
        self.assertEqual([step.op for step in plan.steps],
                         ["remove_link", "symlink", "verify_link"])
        self.assertEqual(self.execute(plan)["state"], "done")
        self.assertTrue(rel._same(rel._link_target(self.home), self.store))

    def test_relink_refuses_a_real_folder(self):
        self.make_home()
        os.makedirs(self.store)
        with self.assertRaises(rel.RelocationError) as caught:
            rel.build_plan(
                self.home, self.store, "relink",
                volume_id=self.store_volume, destination_root=self.store_volume,
                free_bytes=10**12,
            )
        self.assertEqual(caught.exception.code, "state")

    def test_an_interrupted_restore_is_detected_and_resumed(self):
        self.linked()
        staging = self.home + rel.RESTORE_SUFFIX
        shutil.copytree(self.store, staging, symlinks=True)
        self.assertEqual(rel.interrupted_kind(self.home, self.store), "restore")
        with self.assertRaises(rel.RelocationError) as caught:
            rel.build_plan(
                self.home, self.store, "restore",
                volume_id=self.home_volume, destination_root=self.home_volume,
                free_bytes=10**12,
            )
        self.assertEqual(caught.exception.code, "interrupted")
        plan = self.plan("resume")
        result = self.execute(plan)
        self.assertEqual(result["state"], "done")
        self.assertTrue(os.path.isdir(self.home))
        self.assertFalse(os.path.islink(self.home))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "two.bin")))


if __name__ == "__main__":
    unittest.main()
