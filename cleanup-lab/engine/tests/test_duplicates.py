"""CLN-30 duplicates tests: identical content grouped, same-size near-misses
dissolved at the prehash, the full hasher spent only on survivors, links and
special nodes skipped with reasons, drift caught before hashing, cancel
honoured mid-run with partial results.

Every test builds a generated tree under ``tempfile``; nothing reads a real
user folder (rule 8).
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import duplicates  # noqa: E402


class CountingHasher:
    """A sha256 stand-in that counts constructions — the full-hash stage only."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return hashlib.sha256()


class GrownOpen:
    """Serves the real file for the prehash, then more bytes than the walk
    stat promised for the full hash — a file that changed while being read."""

    def __init__(self, target):
        self.target = os.fspath(target)
        self.opens = {}

    def __call__(self, path, mode="rb"):
        key = os.fspath(path)
        self.opens[key] = self.opens.get(key, 0) + 1
        if key == self.target and self.opens[key] >= 2:
            return io.BytesIO(b"x" * 99999)
        return open(path, mode)


class FindDuplicatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-dup-")
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, body=b"x"):
        target = os.path.join(self.home, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(body)
        return target

    def find(self, roots=None, **kwargs):
        return duplicates.find_duplicates(self.home if roots is None else roots, **kwargs)

    def reasons_of(self, result):
        return {item["path"]: item["reason"] for item in result["skipped"]}

    # ── grouping ─────────────────────────────────────────────────────────────

    def test_identical_files_are_grouped_with_the_newest_keeper(self):
        body = b"payload" * 8
        first = self.write("a/one.bin", body)
        second = self.write("b/nested/two.bin", body)
        first_ns, second_ns = 1_000_000_000, 9_000_000_000
        os.utime(first, ns=(first_ns, first_ns))
        os.utime(second, ns=(second_ns, second_ns))
        result = self.find()
        self.assertFalse(result["cancelled"])
        self.assertEqual(len(result["groups"]), 1)
        group = result["groups"][0]
        self.assertEqual(group["digest"], hashlib.sha256(body).hexdigest())
        self.assertEqual(group["sizeBytes"], len(body))
        self.assertEqual([f["path"] for f in group["files"]], sorted([first, second]))
        self.assertEqual(group["keeper"], second)  # the newest mtime wins
        info = os.lstat(first)
        record = group["files"][0]
        self.assertEqual(
            sorted(record), ["dev", "ino", "mtimeNs", "path", "sizeBytes"]
        )
        self.assertEqual(record["sizeBytes"], len(body))
        self.assertEqual(record["dev"], info.st_dev)
        self.assertEqual(record["ino"], info.st_ino)
        self.assertEqual(record["mtimeNs"], info.st_mtime_ns)
        self.assertEqual(result["skipped"], [])
        self.assertEqual(
            result["totals"],
            {"groups": 1, "duplicateFiles": 1, "reclaimableBytes": len(body)},
        )
        json.dumps(result)  # the report is plain, JSON-ready data

    def test_same_size_different_content_is_never_grouped(self):
        self.write("x/one.bin", b"alpha!")
        self.write("x/two.bin", b"beta!!")
        result = self.find()
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(
            result["totals"], {"groups": 0, "duplicateFiles": 0, "reclaimableBytes": 0}
        )

    def test_totals_are_largest_first_and_match_reclaimable(self):
        small = b"s" * 10
        big = b"b" * 400
        self.write("g1/a.bin", small)
        self.write("g1/b.bin", small)
        self.write("g2/a.bin", big)
        self.write("g2/b.bin", big)
        result = self.find()
        self.assertEqual([g["sizeBytes"] for g in result["groups"]], [400, 10])
        self.assertEqual(
            result["totals"],
            {"groups": 2, "duplicateFiles": 2, "reclaimableBytes": 410},
        )
        for group in result["groups"]:
            self.assertEqual(duplicates.reclaimable(group), group["sizeBytes"] * 1)

    def test_a_deep_nested_tree_walks_correctly(self):
        body = b"deep" * 8
        deep = self.write("l1/l2/l3/l4/one.bin", body)
        twin = self.write("l1/l2/other/two.bin", body)
        self.write("l1/l2/l3/l4/l5/three.bin", b"unique" * 6)
        result = self.find()
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(
            sorted(f["path"] for f in result["groups"][0]["files"]),
            sorted([deep, twin]),
        )
        self.assertEqual(result["skipped"], [])

    def test_a_single_string_root_works_like_a_list(self):
        body = b"twin"
        self.write("s/a.bin", body)
        self.write("s/b.bin", body)
        self.assertEqual(self.find(self.home)["groups"], self.find([self.home])["groups"])

    def test_no_roots_reports_an_empty_honest_result(self):
        self.assertEqual(
            duplicates.find_duplicates([]),
            {
                "cancelled": False,
                "groups": [],
                "skipped": [],
                "totals": {"groups": 0, "duplicateFiles": 0, "reclaimableBytes": 0},
            },
        )

    # ── the prehash short-circuit ─────────────────────────────────────────────

    def test_groups_dissolved_by_prehash_never_reach_the_full_hasher(self):
        self.write("x/one.bin", b"alpha!")
        self.write("x/two.bin", b"beta!!")
        hasher = CountingHasher()
        result = self.find(hasher=hasher)
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(hasher.calls, 0)

    def test_only_surviving_groups_are_hashed_whole(self):
        body = b"payload" * 3
        self.write("x/one.bin", body)
        self.write("x/two.bin", body)
        self.write("x/three.bin", b"gamma!!")  # own size group: never hashed
        hasher = CountingHasher()
        result = self.find(hasher=hasher)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["digest"], hashlib.sha256(body).hexdigest())
        self.assertEqual(hasher.calls, 2)  # the dissolved file never reaches it

    def test_large_files_surviving_prehash_are_grouped_by_the_full_hash(self):
        body = b"head" + b"m" * 200 + b"tail"
        self.write("big/one.bin", body)
        self.write("big/two.bin", body)
        hasher = CountingHasher()
        result = self.find(prehash_bytes=8, hasher=hasher)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["digest"], hashlib.sha256(body).hexdigest())
        self.assertEqual(hasher.calls, 2)

    def test_large_files_with_equal_ends_but_different_middles_are_not_duplicates(self):
        prefix = b"head" + b"P" * 50
        suffix = b"P" * 50 + b"tail"
        self.write("big/one.bin", prefix + b"A" * 100 + suffix)
        self.write("big/two.bin", prefix + b"B" * 100 + suffix)
        hasher = CountingHasher()
        result = self.find(prehash_bytes=8, hasher=hasher)
        # the ends match, so prehash cannot dissolve the pair — the full hash does
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(hasher.calls, 2)

    # ── skips: links, specials, sizes, unreadable paths ───────────────────────

    def test_a_hard_link_is_skipped_as_a_duplicate_of_the_first_path(self):
        body = b"linked" * 4
        one = self.write("a/one.bin", body)
        os.makedirs(os.path.join(self.home, "b"))
        link = os.path.join(self.home, "b", "copy.bin")
        os.link(one, link)
        three = self.write("c/three.bin", body)
        result = self.find()
        self.assertEqual(self.reasons_of(result).get(link), "hard-link-duplicate")
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(
            sorted(f["path"] for f in result["groups"][0]["files"]),
            sorted([one, three]),
        )
        self.assertEqual(result["totals"]["reclaimableBytes"], len(body))

    def test_a_symlink_to_a_duplicate_is_skipped_and_never_followed(self):
        one = self.write("d1/a.bin", b"twin")
        two = self.write("d2/b.bin", b"twin")
        link = os.path.join(self.home, "d2", "link.bin")
        os.symlink(one, link)
        os.symlink(self.home, os.path.join(self.home, "loop"))  # a link loop
        result = self.find()
        reasons = self.reasons_of(result)
        self.assertEqual(reasons.get(link), "symlink")
        self.assertEqual(reasons.get(os.path.join(self.home, "loop")), "symlink")
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(
            sorted(f["path"] for f in result["groups"][0]["files"]), sorted([one, two])
        )

    def test_a_symlink_root_is_reported_and_never_followed(self):
        self.write("real/data.bin", b"body")
        self.write("real/other.bin", b"body")
        link = os.path.join(self.home, "link")
        os.symlink(os.path.join(self.home, "real"), link)
        result = self.find([link])
        self.assertEqual([item["reason"] for item in result["skipped"]], ["symlink"])
        self.assertEqual(result["groups"], [])
        self.assertTrue(os.path.lexists(link))

    @unittest.skipIf(sys.platform == "win32", "POSIX FIFOs")
    def test_a_fifo_root_and_a_missing_root_are_skipped_not_fatal(self):
        one = self.write("data/a.bin", b"aa")
        two = self.write("data/b.bin", b"aa")
        fifo = os.path.join(self.home, "pipe")
        os.mkfifo(fifo)
        missing = os.path.join(self.home, "gone")
        result = self.find([fifo, self.home, missing])
        reasons = self.reasons_of(result)
        self.assertEqual(reasons.get(fifo), "not-regular")
        self.assertEqual(reasons.get(missing), "unreadable")
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(
            sorted(f["path"] for f in result["groups"][0]["files"]), sorted([one, two])
        )

    @unittest.skipIf(sys.platform == "win32", "POSIX FIFOs")
    def test_a_fifo_inside_the_tree_is_skipped(self):
        one = self.write("ok/a.bin", b"twin" * 2)
        two = self.write("ok/b.bin", b"twin" * 2)
        pipe = os.path.join(self.home, "ok", "pipe")
        os.mkfifo(pipe)
        result = self.find()
        self.assertEqual(self.reasons_of(result).get(pipe), "not-regular")
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(
            sorted(f["path"] for f in result["groups"][0]["files"]), sorted([one, two])
        )

    def test_files_below_min_size_are_skipped(self):
        one = self.write("e/one.bin", b"")
        two = self.write("e/two.bin", b"")
        result = self.find()  # the default min_size=1 keeps empties out
        reasons = self.reasons_of(result)
        self.assertEqual(reasons.get(one), "below-min-size")
        self.assertEqual(reasons.get(two), "below-min-size")
        self.assertEqual(result["groups"], [])
        opened = self.find(min_size=0)  # opting in groups the empty files
        self.assertEqual(len(opened["groups"]), 1)
        self.assertEqual(opened["groups"][0]["sizeBytes"], 0)
        self.assertEqual(opened["totals"]["reclaimableBytes"], 0)

    @unittest.skipIf(sys.platform == "win32" or os.geteuid() == 0, "needs a non-root POSIX user")
    def test_a_file_that_cannot_be_opened_is_skipped_as_unreadable(self):
        one = self.write("u/a.bin", b"secret" * 2)
        two = self.write("u/b.bin", b"secret" * 2)
        os.chmod(two, 0o000)
        try:
            result = self.find()
        finally:
            os.chmod(two, 0o644)
        reasons = self.reasons_of(result)
        self.assertEqual(reasons.get(two), "unreadable")
        self.assertNotIn(one, reasons)
        self.assertEqual(result["groups"], [])

    @unittest.skipIf(sys.platform == "win32" or os.geteuid() == 0, "needs a non-root POSIX user")
    def test_an_unreadable_directory_is_reported_not_fatal(self):
        one = self.write("ok/a.bin", b"twin" * 2)
        two = self.write("ok/b.bin", b"twin" * 2)
        blocked = os.path.join(self.home, "blocked")
        os.makedirs(blocked)
        self.write("blocked/hidden.bin", b"hidden")
        os.chmod(blocked, 0o000)
        try:
            result = self.find()
        finally:
            os.chmod(blocked, 0o755)
        self.assertEqual(self.reasons_of(result).get(blocked), "unreadable")
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(
            sorted(f["path"] for f in result["groups"][0]["files"]), sorted([one, two])
        )

    def test_a_root_listed_twice_counts_each_file_once(self):
        one = self.write("r1/a.bin", b"same")
        two = self.write("r2/a.bin", b"same")
        result = self.find([os.path.join(self.home, "r1"), os.path.join(self.home, "r2"),
                            os.path.join(self.home, "r1")])
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(
            sorted(f["path"] for f in result["groups"][0]["files"]), sorted([one, two])
        )
        self.assertEqual(self.reasons_of(result).get(one), "hard-link-duplicate")

    # ── drift: a file that changes between the walk and the hash ─────────────

    def test_changed_mtime_is_caught_by_the_restat_before_hashing(self):
        first = self.write("a/one.bin", b"same")
        second = self.write("b/two.bin", b"same")
        shifted = os.lstat(second).st_mtime_ns + 1_000_000
        calls = {}
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            key = os.fspath(path)
            calls[key] = calls.get(key, 0) + 1
            if key == second and calls[key] >= 2:  # the re-stat before hashing
                os.utime(second, ns=(shifted, shifted))
            return real_lstat(path, *args, **kwargs)

        result = self.find(lstat=lstat)
        self.assertEqual(self.reasons_of(result).get(second), "changed-during-scan")
        self.assertNotIn(first, self.reasons_of(result))
        self.assertEqual(result["groups"], [])

    def test_a_file_that_grows_before_the_full_hash_is_skipped(self):
        body = b"head" + b"m" * 200 + b"tail"
        one = self.write("g/one.bin", body)
        two = self.write("g/two.bin", body)
        result = self.find(prehash_bytes=8, open_func=GrownOpen(two))
        self.assertEqual(self.reasons_of(result).get(two), "changed-during-scan")
        self.assertNotIn(one, self.reasons_of(result))
        self.assertEqual(result["groups"], [])

    # ── cancellation ─────────────────────────────────────────────────────────

    def test_cancel_before_start_returns_an_empty_partial(self):
        self.write("x/a.bin", b"twin")
        self.write("x/b.bin", b"twin")
        hasher = CountingHasher()
        result = self.find(cancel=lambda: True, hasher=hasher)
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(
            result["totals"], {"groups": 0, "duplicateFiles": 0, "reclaimableBytes": 0}
        )
        self.assertEqual(hasher.calls, 0)

    def test_cancel_mid_pipeline_keeps_the_verified_groups(self):
        body = b"payload" * 20
        self.write("p1/a.bin", body)
        self.write("p1/b.bin", body)
        self.write("p2/a.bin", body + b"x")
        self.write("p2/b.bin", body + b"x")
        seen = []

        def progress(payload):
            seen.append(payload)

        def cancel():
            # stop as soon as one whole pair has been verified by the full hash
            return any(p["phase"] == "hashing" and p["filesDone"] >= 2 for p in seen)

        result = self.find(progress=progress, cancel=cancel)
        self.assertTrue(result["cancelled"])
        self.assertEqual(len(result["groups"]), 1)  # the pair fully hashed first
        group = result["groups"][0]
        paths = [f["path"] for f in group["files"]]
        self.assertEqual(len(paths), 2)
        self.assertEqual(len({os.path.dirname(path) for path in paths}), 1)
        self.assertEqual(group["sizeBytes"], os.lstat(paths[0]).st_size)
        self.assertEqual(result["totals"]["duplicateFiles"], 1)
        self.assertEqual(result["totals"]["reclaimableBytes"], group["sizeBytes"])

    # ── progress ─────────────────────────────────────────────────────────────

    def test_progress_reports_each_phase_with_the_documented_keys(self):
        body = b"payload"
        self.write("x/a.bin", body)
        self.write("x/b.bin", body)
        self.write("x/c.bin", b"berload")  # same size, different content
        seen = []
        result = self.find(progress=seen.append)
        self.assertFalse(result["cancelled"])
        self.assertTrue(seen)
        for payload in seen:
            self.assertEqual(
                sorted(payload), ["currentPath", "filesDone", "filesTotal", "phase"]
            )
            self.assertIn(payload["phase"], ("walking", "prehash", "hashing"))
        self.assertEqual(
            {payload["phase"] for payload in seen},
            {"walking", "prehash", "hashing"},
        )
        for payload in seen:
            if payload["phase"] == "walking":
                self.assertEqual(payload["filesTotal"], 0)  # unknown during the walk
        prehash = [p for p in seen if p["phase"] == "prehash"]
        self.assertEqual(prehash[-1]["filesTotal"], 3)
        self.assertEqual(prehash[-1]["filesDone"], 3)
        hashing = [p for p in seen if p["phase"] == "hashing"]
        self.assertEqual(hashing[-1]["filesTotal"], 2)  # only the true pair survives
        self.assertEqual(hashing[-1]["filesDone"], 2)
        for phase_payloads in (prehash, hashing):  # each phase counts on its own
            done = 0
            for payload in phase_payloads:
                self.assertGreaterEqual(payload["filesDone"], done)
                done = payload["filesDone"]
        self.assertTrue(all(p["currentPath"] for p in prehash + hashing))

    # ── interface guards ─────────────────────────────────────────────────────

    def test_follow_symlinks_true_is_refused(self):
        with self.assertRaises(ValueError):
            self.find(follow_symlinks=True)

    def test_the_reported_keeper_matches_newest_selection_end_to_end(self):
        body = b"keeper" * 5
        old = self.write("k/old.bin", body)
        new = self.write("k/new.bin", body)
        os.utime(old, ns=(1_000_000_000, 1_000_000_000))
        os.utime(new, ns=(9_000_000_000, 9_000_000_000))
        result = self.find()
        group = result["groups"][0]
        self.assertEqual(group["keeper"], new)
        selection = duplicates.select_for_removal(group)
        self.assertEqual(selection, [old])
        self.assertNotIn(group["keeper"], selection)
        self.assertEqual(duplicates.reclaimable(group), len(body))
        self.assertEqual(result["totals"]["reclaimableBytes"], len(body))


class KeeperSelectionTests(unittest.TestCase):
    """The keeper vocabulary: pure functions over a group's files."""

    @staticmethod
    def make_group(entries):
        files = [
            {"path": path, "sizeBytes": size, "dev": 1, "ino": index + 1, "mtimeNs": mtime}
            for index, (path, size, mtime) in enumerate(entries)
        ]
        return {
            "digest": "0" * 64,
            "sizeBytes": files[0]["sizeBytes"] if files else 0,
            "files": files,
            "keeper": "",
        }

    def setUp(self):
        # sizes and mtimes disagree on purpose so every method picks differently
        self.group = self.make_group([("/a", 20, 300), ("/b", 30, 100), ("/c", 10, 200)])

    def test_the_vocabulary_is_exactly_the_five_methods(self):
        self.assertEqual(
            duplicates.KEEPER_METHODS,
            ("newest", "oldest", "biggest", "smallest", "first-path"),
        )

    def test_newest_and_oldest_pick_by_mtime(self):
        self.assertEqual(duplicates.select_for_removal(self.group, "newest"), ["/b", "/c"])
        self.assertEqual(duplicates.select_for_removal(self.group, "oldest"), ["/a", "/c"])

    def test_biggest_and_smallest_pick_by_size(self):
        self.assertEqual(duplicates.select_for_removal(self.group, "biggest"), ["/a", "/c"])
        self.assertEqual(duplicates.select_for_removal(self.group, "smallest"), ["/a", "/b"])

    def test_first_path_picks_the_lexicographically_first_file(self):
        self.assertEqual(duplicates.select_for_removal(self.group, "first-path"), ["/b", "/c"])

    def test_newest_is_the_default_method(self):
        self.assertEqual(
            duplicates.select_for_removal(self.group),
            duplicates.select_for_removal(self.group, "newest"),
        )

    def test_ties_break_to_the_first_path(self):
        tied = self.make_group([("/x", 10, 500), ("/y", 10, 500), ("/z", 10, 100)])
        # the tie for newest keeps /x (the lexicographically first path)
        self.assertEqual(duplicates.select_for_removal(tied, "newest"), ["/y", "/z"])
        self.assertEqual(duplicates.select_for_removal(tied, "first-path"), ["/y", "/z"])
        self.assertEqual(duplicates.select_for_removal(tied, "oldest"), ["/x", "/y"])

    def test_a_one_file_group_returns_empty_for_every_method(self):
        single = self.make_group([("/only", 5, 1)])
        empty = self.make_group([])
        for method in duplicates.KEEPER_METHODS:
            self.assertEqual(duplicates.select_for_removal(single, method), [])
            self.assertEqual(duplicates.select_for_removal(empty, method), [])

    def test_a_multi_file_group_never_returns_empty_and_never_the_keeper(self):
        for method in duplicates.KEEPER_METHODS:
            selection = duplicates.select_for_removal(self.group, method)
            self.assertEqual(len(selection), 2)
            self.assertTrue(all(path in ("/a", "/b", "/c") for path in selection))
            self.assertEqual(len(set(selection)), 2)

    def test_an_unknown_method_is_refused(self):
        for method in ("largest", "NEWEST", "", None):
            with self.assertRaises(ValueError):
                duplicates.select_for_removal(self.group, method)

    def test_reclaimable_counts_the_duplicates_only(self):
        self.assertEqual(duplicates.reclaimable(self.group), 20 * 2)
        self.assertEqual(duplicates.reclaimable(self.make_group([("/only", 5, 1)])), 0)


if __name__ == "__main__":
    unittest.main()
