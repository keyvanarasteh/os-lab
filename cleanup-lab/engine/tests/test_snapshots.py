"""CLN-31 snapshot tests: interchange roundtrip, honest refusals, diffing.

Everything runs on generated trees and generated documents inside ``tempfile``
folders; nothing touches a real user folder (rule 8).
"""
import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import explorer, snapshots  # noqa: E402

OVER_LIMIT = snapshots._MAX_VALUE_CHARS + 16


def header(progname="os-lab-cleanup", progver="0.4.0", timestamp=1700000000):
    return {"progname": progname, "progver": progver, "timestamp": timestamp}


def build_tree():
    """A generated explorer-style tree with nested dirs and every marker."""
    return {
        "name": "root", "sizeBytes": 1000, "files": 3, "folders": 4,
        "truncated": False, "unreadable": 3, "ignored": 0,
        "children": [
            {"name": "docs", "sizeBytes": 400, "files": 2, "folders": 0,
             "children": [
                 {"name": "notes.txt", "sizeBytes": 200, "sizeOnDiskBytes": 4096},
                 {"name": "spec.md", "sizeBytes": 200},
             ]},
            {"name": "dev", "sizeBytes": 0, "files": 1, "folders": 1,
             "children": [
                 {"name": "sock", "sizeBytes": 0, "notregular": True},
                 {"name": "procdir", "sizeBytes": 0, "unreadable": 3, "children": []},
             ]},
            {"name": "big", "sizeBytes": 600, "files": 0, "folders": 0,
             "truncated": True, "children": []},
        ],
    }


def project(node):
    """The fields the interchange preserves, for the roundtrip comparison."""
    out = {"name": node["name"], "sizeBytes": node["sizeBytes"]}
    if node.get("sizeOnDiskBytes") is not None:
        out["sizeOnDiskBytes"] = node["sizeOnDiskBytes"]
    if "children" in node:
        out["children"] = [project(child) for child in node["children"]]
    if node.get("notregular"):
        out["notregular"] = True
    if node.get("truncated"):
        out["truncated"] = True
    if node.get("ino") is not None:
        out["ino"] = node["ino"]
    if node.get("dev") is not None:
        out["dev"] = node["dev"]
    return out


def deep_doc(levels):
    """A document with ``levels`` nested directories under the root."""
    item = '{"name":"leaf","asize":1}'
    for index in range(levels):
        item = '[{{"name":"d{0}","asize":1}},[{1}]]'.format(index, item)
    return "[1,1," + json.dumps(header()) + ',{"name":"root","asize":1},[' + item + "]]"


def make_old():
    return {
        "name": "root", "sizeBytes": 750, "children": [
            {"name": "keep", "sizeBytes": 100, "sizeOnDiskBytes": 4096, "children": []},
            {"name": "grow", "sizeBytes": 300, "sizeOnDiskBytes": 4096, "children": [
                {"name": "f", "sizeBytes": 300},
            ]},
            {"name": "shrink", "sizeBytes": 200, "sizeOnDiskBytes": 8192, "children": []},
            {"name": "gone", "sizeBytes": 150, "children": []},
        ],
    }


def make_new():
    return {
        "name": "root", "sizeBytes": 800, "children": [
            {"name": "keep", "sizeBytes": 100, "sizeOnDiskBytes": 4096, "children": []},
            {"name": "grow", "sizeBytes": 400, "sizeOnDiskBytes": 8192, "children": [
                {"name": "f", "sizeBytes": 400},
            ]},
            {"name": "shrink", "sizeBytes": 50, "sizeOnDiskBytes": 4096, "children": []},
            {"name": "fresh", "sizeBytes": 250, "children": []},
        ],
    }


def make_deep_old():
    return {"name": "root", "sizeBytes": 500, "children": [
        {"name": "deep", "sizeBytes": 500, "children": [
            {"name": "mid", "sizeBytes": 500, "children": [
                {"name": "a", "sizeBytes": 100, "children": []},
                {"name": "b", "sizeBytes": 400, "children": []},
            ]},
        ]},
    ]}


def make_deep_new():
    return {"name": "root", "sizeBytes": 500, "children": [
        {"name": "deep", "sizeBytes": 500, "children": [
            {"name": "mid", "sizeBytes": 500, "children": [
                {"name": "a", "sizeBytes": 100, "children": []},
                {"name": "c", "sizeBytes": 400, "children": []},
            ]},
        ]},
    ]}


class SnapshotCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-snap-")
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, size):
        target = os.path.join(self.home, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(b"x" * size)
        return target

    def write_doc(self, text):
        path = os.path.join(self.home, "doc.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def write_bytes(self, blob):
        path = os.path.join(self.home, "doc.json")
        with open(path, "wb") as handle:
            handle.write(blob)
        return path


class RoundtripTests(SnapshotCase):
    def test_roundtrip_preserves_the_generated_tree(self):
        tree = build_tree()
        out = os.path.join(self.home, "tree.json")
        self.assertEqual(snapshots.export_snapshot(tree, out), out)
        read = snapshots.read_snapshot(out)
        self.assertEqual(project(tree), project(read["root"]))
        # unreadable is a count on the way in, an honest fact on the way out
        self.assertEqual(read["root"]["unreadable"], 1)
        dev = read["root"]["children"][1]
        self.assertEqual(dev["unreadable"], 0)
        procdir = dev["children"][1]
        self.assertEqual(procdir["unreadable"], 1)
        self.assertEqual(read["header"]["progname"], "os-lab-cleanup")
        self.assertEqual(read["header"]["progver"], "0.4.0")
        self.assertIsInstance(read["header"]["timestamp"], int)

    def test_truncated_is_recorded_as_excluded_budget_and_restored(self):
        out = os.path.join(self.home, "tree.json")
        snapshots.export_snapshot(build_tree(), out)
        big = snapshots.read_snapshot(out)["root"]["children"][2]
        self.assertEqual(big["name"], "big")
        self.assertEqual(big["excluded"], "budget")
        self.assertTrue(big["truncated"])

    def test_derived_file_and_folder_counts(self):
        out = os.path.join(self.home, "tree.json")
        snapshots.export_snapshot(build_tree(), out)
        root = snapshots.read_snapshot(out)["root"]
        self.assertEqual(root["files"], 3)
        self.assertEqual(root["folders"], 4)
        docs = root["children"][0]
        self.assertEqual(docs["files"], 2)
        self.assertEqual(docs["folders"], 0)
        dev = root["children"][1]
        self.assertEqual(dev["files"], 1)
        self.assertEqual(dev["folders"], 1)

    def test_ino_and_dev_are_written_by_the_format_rules(self):
        tree = {"name": "r", "sizeBytes": 10, "dev": 5, "ino": 1, "children": [
            {"name": "same", "sizeBytes": 5, "ino": 2, "children": []},
            {"name": "other", "sizeBytes": 5, "dev": 9, "ino": 3, "children": []},
        ]}
        out = os.path.join(self.home, "dev.json")
        snapshots.export_snapshot(tree, out)
        with open(out, encoding="utf-8") as handle:
            doc = json.load(handle)
        self.assertEqual([doc[0], doc[1]], [1, 1])
        self.assertEqual(doc[3]["dev"], 5)
        self.assertNotIn("dev", doc[4][0][0])  # same device as the parent: omitted
        self.assertEqual(doc[4][0][0]["ino"], 2)
        self.assertEqual(doc[4][1][0]["dev"], 9)
        read = snapshots.read_snapshot(out)
        self.assertEqual(read["root"]["ino"], 1)
        self.assertEqual(read["root"]["dev"], 5)
        self.assertEqual(read["root"]["children"][0]["ino"], 2)
        self.assertNotIn("dev", read["root"]["children"][0])
        self.assertEqual(read["root"]["children"][1]["dev"], 9)

    def test_explorer_walk_tree_roundtrips(self):
        self.write("alpha/one.bin", 100)
        self.write("alpha/two.bin", 50)
        self.write("beta/three.bin", 200)
        node, _ = explorer.walk(self.home)
        out = os.path.join(self.home, "walk.json")
        snapshots.export_snapshot(node, out)
        root = snapshots.read_snapshot(out)["root"]
        self.assertEqual(root["name"], self.home)  # the root keeps the walked path
        self.assertEqual(root["sizeBytes"], 350)
        by_name = {child["name"]: child for child in root["children"]}
        self.assertEqual(sorted(by_name), ["alpha", "beta"])
        self.assertEqual(by_name["alpha"]["sizeBytes"], 150)
        self.assertEqual(by_name["beta"]["sizeBytes"], 200)
        # the explorer counts files on the directory (no file leaves), so the
        # interchange carries sizes and dirs only: counts re-derive honestly
        self.assertEqual(by_name["alpha"]["children"], [])
        self.assertEqual(by_name["alpha"]["files"], 0)
        self.assertEqual(by_name["alpha"]["folders"], 0)
        self.assertEqual(root["files"], 0)
        self.assertEqual(root["folders"], 2)

    def test_foreign_minor_two_document_imports(self):
        doc = [1, 2, header("foreign-tool", "2.0", 1234567890),
               {"name": "/data/foreign", "asize": 4096, "dsize": 4096, "dev": 12, "ino": 2},
               [
                   {"name": "plain.bin", "asize": 100},
                   {"name": "link.thing", "asize": 0, "notreg": True},
                   [{"name": "sub", "asize": 300}, [
                       {"name": "deep.dat", "asize": 300, "dsize": 320},
                   ]],
               ]]
        read = snapshots.read_snapshot(self.write_doc(json.dumps(doc)))
        self.assertEqual(read["header"], {"progname": "foreign-tool", "progver": "2.0",
                                          "timestamp": 1234567890})
        root = read["root"]
        self.assertEqual(root["name"], "/data/foreign")
        self.assertEqual(root["sizeBytes"], 4096)
        self.assertEqual(root["sizeOnDiskBytes"], 4096)
        self.assertEqual([child["name"] for child in root["children"]],
                         ["plain.bin", "link.thing", "sub"])
        self.assertIsNone(root["children"][0]["sizeOnDiskBytes"])  # asize only stays unknown
        self.assertTrue(root["children"][1]["notregular"])
        self.assertEqual(root["children"][2]["children"][0]["sizeOnDiskBytes"], 320)
        self.assertEqual(root["files"], 3)
        self.assertEqual(root["folders"], 1)


class RefusalTests(SnapshotCase):
    def test_wrong_major_version_refused(self):
        doc = [2, 1, header(), {"name": "root", "asize": 0}, []]
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(self.write_doc(json.dumps(doc)))
        self.assertIn("major version", str(caught.exception))

    def test_unknown_minor_version_refused(self):
        doc = [1, 3, header(), {"name": "root", "asize": 0}, []]
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(self.write_doc(json.dumps(doc)))
        self.assertIn("minor version", str(caught.exception))

    def test_garbage_refused(self):
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.read_snapshot(self.write_doc("this is not json"))

    def test_truncated_file_refused(self):
        doc = json.dumps([1, 1, header(), {"name": "root", "asize": 10},
                          [{"name": "a", "asize": 5}]])
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.read_snapshot(self.write_doc(doc[: len(doc) // 2]))

    def test_oversized_name_refused(self):
        doc = [1, 1, header(), {"name": "root", "asize": 0},
               [{"name": "a" * OVER_LIMIT, "asize": 1}]]
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(self.write_doc(json.dumps(doc)))
        self.assertIn("too large", str(caught.exception))

    def test_node_budget_refused(self):
        doc = [1, 1, header(), {"name": "root", "asize": 0},
               [{"name": "f{0}".format(index), "asize": index} for index in range(5)]]
        path = self.write_doc(json.dumps(doc))
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(path, max_nodes=3)
        self.assertIn("too many nodes", str(caught.exception))
        # the same document reads fine inside the budget
        self.assertEqual(len(snapshots.read_snapshot(path)["root"]["children"]), 5)

    def test_deeply_nested_document_refused(self):
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(self.write_doc(deep_doc(300)))
        self.assertIn("deeper", str(caught.exception))
        # a shallow document of the same shape is fine (d9 is the outermost wrap)
        read = snapshots.read_snapshot(self.write_doc(deep_doc(10)))
        self.assertEqual(read["root"]["children"][0]["name"], "d9")
        self.assertEqual(read["root"]["children"][0]["children"][0]["name"], "d8")

    def test_header_shape_refused(self):
        bad_name = [1, 1, {"progver": "x", "timestamp": 1}, {"name": "r", "asize": 0}, []]
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(self.write_doc(json.dumps(bad_name)))
        self.assertIn("progname", str(caught.exception))
        bad_time = [1, 1, header(timestamp=1.5), {"name": "r", "asize": 0}, []]
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(self.write_doc(json.dumps(bad_time)))
        self.assertIn("timestamp", str(caught.exception))

    def test_entry_without_asize_refused(self):
        doc = [1, 1, header(), {"name": "root", "asize": 0}, [{"name": "a"}]]
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(self.write_doc(json.dumps(doc)))
        self.assertIn("asize", str(caught.exception))

    def test_non_utf8_document_refused(self):
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.read_snapshot(self.write_bytes(b"\xff\xfe not utf-8"))

    def test_missing_file_refused(self):
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(os.path.join(self.home, "nope.json"))
        self.assertIn("does not exist", str(caught.exception))

    def test_symlinked_snapshot_refused(self):
        real = self.write_doc(json.dumps([1, 1, header(), {"name": "r", "asize": 0}, []]))
        link = real + ".link"
        os.symlink(real, link)
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.read_snapshot(link)
        self.assertIn("symlink", str(caught.exception))

    def test_directory_path_refused(self):
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.read_snapshot(self.home)


class ExportDisciplineTests(SnapshotCase):
    def test_export_is_atomic_private_and_leaves_no_temp(self):
        out = os.path.join(self.home, "snap.json")
        self.assertEqual(snapshots.export_snapshot(build_tree(), out), out)
        self.assertEqual(
            [name for name in os.listdir(self.home) if name.endswith(".tmp")], []
        )
        mode = stat.S_IMODE(os.stat(out).st_mode)
        self.assertEqual(mode, 0o600)
        with open(out, encoding="utf-8") as handle:
            doc = json.load(handle)
        self.assertEqual([doc[0], doc[1]], [1, 1])
        self.assertEqual(doc[2]["progname"], "os-lab-cleanup")
        self.assertEqual(doc[2]["progver"], "0.4.0")
        self.assertIsInstance(doc[2]["timestamp"], int)

    def test_symlink_destination_refused_and_target_untouched(self):
        target = os.path.join(self.home, "real.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("keep")
        link = os.path.join(self.home, "link.json")
        os.symlink(target, link)
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.export_snapshot(build_tree(), link)
        self.assertIn("symlink", str(caught.exception))
        self.assertTrue(os.path.islink(link))
        with open(link, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "keep")

    def test_export_refuses_a_shared_parent_folder(self):
        shared = os.path.join(self.home, "shared")
        os.makedirs(shared)
        os.chmod(shared, 0o755)
        out = os.path.join(shared, "snap.json")
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.export_snapshot(build_tree(), out)
        self.assertIn("0700", str(caught.exception))
        os.chmod(shared, 0o700)

    def test_export_refuses_a_missing_parent_folder(self):
        out = os.path.join(self.home, "nowhere", "snap.json")
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.export_snapshot(build_tree(), out)
        self.assertIn("does not exist", str(caught.exception))

    def test_invalid_node_refused_with_nothing_written(self):
        out = os.path.join(self.home, "snap.json")
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.export_snapshot({"name": "x"}, out)
        self.assertIn("sizeBytes", str(caught.exception))
        self.assertEqual(os.listdir(self.home), [])

    def test_empty_progver_refused(self):
        out = os.path.join(self.home, "snap.json")
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.export_snapshot(build_tree(), out, progver="")
        self.assertIn("progver", str(caught.exception))
        self.assertEqual(os.listdir(self.home), [])


class DiffTests(SnapshotCase):
    def test_added_removed_grown_shrunk_unchanged(self):
        result = snapshots.diff_snapshots(make_old(), make_new())
        self.assertEqual(result["added"], [
            {"path": "fresh", "oldBytes": 0, "newBytes": 250, "delta": 250},
        ])
        self.assertEqual(result["removed"], [
            {"path": "gone", "oldBytes": 150, "newBytes": 0, "delta": -150},
        ])
        self.assertEqual(result["grown"], [
            {"path": "grow", "oldBytes": 300, "newBytes": 400, "delta": 100},
            {"path": "grow/f", "oldBytes": 300, "newBytes": 400, "delta": 100},
        ])
        self.assertEqual(result["shrunk"], [
            {"path": "shrink", "oldBytes": 200, "newBytes": 50, "delta": -150},
        ])
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["more"], None)

    def test_disk_sizes_compared_only_when_both_sides_carry_them(self):
        result = snapshots.diff_snapshots(make_old(), make_new())
        self.assertEqual(result["grownOnDisk"], [
            {"path": "grow", "oldBytes": 4096, "newBytes": 8192, "delta": 4096},
        ])
        self.assertEqual(result["shrunkOnDisk"], [
            {"path": "shrink", "oldBytes": 8192, "newBytes": 4096, "delta": -4096},
        ])
        # grow/f and gone carry no dsize: no on-disk claims for them
        self.assertEqual(
            [entry["path"] for entry in result["grownOnDisk"] + result["shrunkOnDisk"]],
            ["grow", "shrink"],
        )

    def test_all_input_forms_agree(self):
        old_path = os.path.join(self.home, "old.json")
        new_path = os.path.join(self.home, "new.json")
        snapshots.export_snapshot(make_old(), old_path)
        snapshots.export_snapshot(make_new(), new_path)
        from_paths = snapshots.diff_snapshots(old_path, new_path)
        from_read = snapshots.diff_snapshots(
            snapshots.read_snapshot(old_path), snapshots.read_snapshot(new_path)
        )
        from_nodes = snapshots.diff_snapshots(make_old(), make_new())
        self.assertEqual(from_paths, from_read)
        self.assertEqual(from_paths, from_nodes)

    def test_prefix_limits_the_comparison_to_the_subtree(self):
        result = snapshots.diff_snapshots(make_old(), make_new(), prefix=["grow"])
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["grown"], [
            {"path": "grow/f", "oldBytes": 300, "newBytes": 400, "delta": 100},
        ])
        self.assertEqual(result["grownOnDisk"], [])  # the anchor itself is never compared
        self.assertEqual(result["unchanged"], 0)

    def test_prefix_missing_on_one_side_reports_the_whole_subtree(self):
        result = snapshots.diff_snapshots(make_old(), make_new(), prefix=["gone"])
        self.assertEqual(result["removed"], [
            {"path": "gone", "oldBytes": 150, "newBytes": 0, "delta": -150},
        ])
        self.assertEqual(result["added"], [])

    def test_prefix_missing_on_both_sides_refused(self):
        with self.assertRaises(snapshots.SnapshotError) as caught:
            snapshots.diff_snapshots(make_old(), make_new(), prefix=["nope"])
        self.assertIn("prefix", str(caught.exception))

    def test_depth_summarizes_below_the_cut(self):
        detailed = snapshots.diff_snapshots(make_deep_old(), make_deep_new())
        self.assertEqual([entry["path"] for entry in detailed["added"]], ["deep/mid/c"])
        self.assertEqual([entry["path"] for entry in detailed["removed"]], ["deep/mid/b"])
        self.assertEqual(detailed["summarized"], [])
        self.assertEqual(detailed["unchanged"], 3)  # deep, mid, a

        cut = snapshots.diff_snapshots(make_deep_old(), make_deep_new(), depth=2)
        self.assertEqual(cut["added"], [])
        self.assertEqual(cut["removed"], [])
        self.assertEqual(cut["summarized"], [
            {"path": "deep/mid", "addedCount": 1, "removedCount": 1, "netBytes": 0},
        ])
        self.assertEqual(cut["unchanged"], 1)  # deep only

        tighter = snapshots.diff_snapshots(make_deep_old(), make_deep_new(), depth=1)
        self.assertEqual(tighter["summarized"], [
            {"path": "deep", "addedCount": 1, "removedCount": 1, "netBytes": 0},
        ])
        self.assertEqual(tighter["unchanged"], 0)

    def test_summary_limit_caps_each_list_and_notes_the_overflow(self):
        old = {"name": "root", "sizeBytes": 0, "children": []}
        new = {"name": "root", "sizeBytes": 70, "children": [
            {"name": "f{0}".format(index), "sizeBytes": 10} for index in range(7)
        ]}
        capped = snapshots.diff_snapshots(old, new, summary_limit=5)
        self.assertEqual(len(capped["added"]), 5)
        self.assertEqual(capped["more"], {"added": 2})
        full = snapshots.diff_snapshots(old, new, summary_limit=10)
        self.assertEqual(len(full["added"]), 7)
        self.assertEqual(full["more"], None)

    def test_invalid_diff_arguments_refused(self):
        for kwargs in (
            {"depth": 0}, {"depth": "2"}, {"prefix": "grow"},
            {"summary_limit": -1}, {"summary_limit": True},
        ):
            with self.assertRaises(snapshots.SnapshotError):
                snapshots.diff_snapshots(make_old(), make_new(), **kwargs)
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.diff_snapshots(None, make_new())
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.diff_snapshots({"name": "no-size"}, make_new())


if __name__ == "__main__":
    unittest.main()
