"""CLW-01: the widget snapshot folds existing module payloads, read-only.

No test touches the real App Group container: the container path is a temp
folder (or missing entirely), the module payloads are fakes, and nothing
here starts a job or probes a disk (README rule 8).
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cleanup_lab import widget  # noqa: E402


def volume(mount, free, total, is_home=False):
    measurable = isinstance(free, int) and isinstance(total, int)
    return {"mountPoint": mount, "name": mount, "device": mount, "filesystem": "apfs",
            "kind": "root", "totalBytes": total, "freeBytes": free,
            "usedBytes": (total - free) if measurable else None,
            "usage": ((total - free) / total) if measurable else None,
            "purgeableBytes": None, "isHome": is_home, "pressure": "ok", "error": None}


def scan_job(state="done", result=None):
    return {"id": "scan-1", "kind": "scan", "state": state, "request": {},
            "progress": {"pathsDone": 3, "pathsTotal": 5},
            "result": result or {"totals": {"paths": 4, "sizeBytes": 4_200_000_000, "unreadable": 1}},
            "error": None, "startedAt": 100.0, "finishedAt": 200.0}


def clean_job(kind="clean", state="running"):
    return {"id": "job-2", "kind": kind, "state": state,
            "progress": {"itemsDone": 1, "itemsTotal": 3}, "result": None,
            "error": None, "startedAt": 300.0, "finishedAt": None}


def history_payload():
    def result(bytes_, finished):
        return {"totals": {"bytes": bytes_}, "finishedAt": finished}
    return {"entries": [
        {"id": 2, "result": result(1500, 500.0), "hmac": "sig"},
        {"id": 1, "result": result(2500, 400.0), "hmac": "sig"},
    ], "total": 2, "verified": True}


def monitor_payload(enabled=True):
    return {
        "enabled": enabled, "intervalSeconds": 300, "cooldownSeconds": 3600,
        "volumes": [], "state": {
            "volumes": {},
            "events": [
                {"at": 700.0, "kind": "warning", "volume": "/", "freeBytes": 100,
                 "thresholdBytes": 200, "message": "low"},
                {"at": 710.0, "kind": "error", "volume": "/", "freeBytes": None,
                 "thresholdBytes": None, "message": "probe failed"},
            ],
            "lastEvaluationAt": 700.0, "lastError": None,
        },
        "activeWarnings": [], "configError": None, "checkedAt": 800.0,
    }


BOOKMARKS = [
    {"entryId": "a", "quickClean": True, "autoCleanHook": {"enabled": True}, "sizeAlert": {"enabled": False}},
    {"entryId": "b", "quickClean": False, "autoCleanHook": {"enabled": False}, "sizeAlert": {"enabled": True}},
]


def build(**overrides):
    args = dict(
        latest_scan=scan_job(), running_job=None, env={"HOME": "/tmp/x"},
        platform="macos", clock=lambda: 900.0,
        volumes_fn=lambda: {"volumes": [volume("/", 200, 1000, is_home=True)]},
        history_fn=history_payload, monitor_fn=monitor_payload,
        bookmarks_fn=lambda: {"bookmarks": BOOKMARKS, "error": None},
        fda_fn=lambda: {"granted": True},
    )
    args.update(overrides)
    return widget.build(**args)


class Build(unittest.TestCase):
    def test_snapshot_folds_every_capability(self):
        snapshot = build()
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertEqual(snapshot["capturedAt"], 900.0)
        self.assertEqual(snapshot["disk"]["freeBytes"], 200)
        self.assertEqual(snapshot["disk"]["usedPercent"], 80.0)
        self.assertEqual(snapshot["lastScan"]["foundBytes"], 4_200_000_000)
        self.assertEqual(snapshot["lastScan"]["foundItems"], 4)
        self.assertEqual(snapshot["lastScan"]["unreadable"], 1)
        self.assertEqual(snapshot["cleanup"]["totalReclaimedBytes"], 4000)
        self.assertEqual(snapshot["cleanup"]["lastRunAt"], 500.0)
        self.assertEqual(snapshot["monitor"]["intervalSeconds"], 300)
        self.assertEqual(snapshot["monitor"]["nextCheckAt"], 1000.0)
        self.assertEqual(snapshot["monitor"]["lastWarningAt"], 700.0)
        self.assertEqual(snapshot["monitor"]["warningCount"], 1)
        self.assertEqual(snapshot["bookmarks"]["count"], 2)
        self.assertEqual(snapshot["bookmarks"]["quickCleanCount"], 1)
        self.assertEqual(snapshot["bookmarks"]["hookCount"], 1)
        self.assertEqual(snapshot["bookmarks"]["alertCount"], 1)
        self.assertIs(snapshot["permissions"]["fullDiskAccess"], True)

    def test_status_states_follow_the_reference_derivation(self):
        self.assertEqual(build()["status"], "ready-to-clean")
        self.assertEqual(build(latest_scan=None)["status"], "up-to-date")
        self.assertEqual(build(running_job=clean_job())["status"], "cleaning")
        self.assertEqual(build(running_job=scan_job(state="running"))["status"], "scanning")
        self.assertEqual(
            build(latest_scan=None, running_job=clean_job(kind="container-prune"))["status"],
            "cleaning",
        )

    def test_progress_comes_from_the_running_job(self):
        self.assertIsNone(build()["progress"])
        progress = build(running_job=scan_job(state="running"))["progress"]
        self.assertEqual(progress, {"done": 3, "total": 5})
        items = build(running_job=clean_job())["progress"]
        self.assertEqual(items, {"done": 1, "total": 3})

    def test_missing_data_degrades_without_raising(self):
        empty = build(latest_scan=None, running_job=None,
                      volumes_fn=lambda: {"volumes": []},
                      history_fn=lambda: {"entries": []},
                      monitor_fn=lambda: {"enabled": False, "intervalSeconds": None,
                                          "state": {"events": [], "lastEvaluationAt": None}},
                      bookmarks_fn=lambda: {"bookmarks": [], "error": None},
                      fda_fn=lambda: {"granted": None})
        self.assertIsNone(empty["disk"]["totalBytes"])
        self.assertIsNone(empty["lastScan"])
        self.assertEqual(empty["cleanup"]["totalReclaimedBytes"], 0)
        self.assertIsNone(empty["cleanup"]["lastRunAt"])
        self.assertFalse(empty["monitor"]["enabled"])
        self.assertIsNone(empty["monitor"]["nextCheckAt"])
        self.assertIsNone(empty["permissions"]["fullDiskAccess"])
        self.assertEqual(empty["status"], "up-to-date")

    def test_unreadable_history_never_breaks_the_snapshot(self):
        def broken():
            raise RuntimeError("db gone")
        snapshot = build(history_fn=broken)
        self.assertEqual(snapshot["cleanup"]["totalReclaimedBytes"], 0)

    def test_stale_scan_jobs_are_ignored(self):
        snapshot = build(latest_scan=scan_job(state="failed"))
        self.assertIsNone(snapshot["lastScan"])
        self.assertEqual(snapshot["status"], "up-to-date")


class Container(unittest.TestCase):
    def test_macos_without_container_is_not_capable(self):
        self.assertIsNone(widget.container_dir({"HOME": "/nonexistent"}, "macos"))
        snapshot = build()
        self.assertFalse(snapshot["capable"])

    def test_override_must_exist(self):
        self.assertIsNone(widget.container_dir({"OSLAB_WIDGET_GROUP_DIR": "/nonexistent-xyz"}, "macos"))
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(widget.container_dir({"OSLAB_WIDGET_GROUP_DIR": base}, "macos"),
                             os.path.realpath(base))
            snapshot = build(env={"OSLAB_WIDGET_GROUP_DIR": base})
            self.assertTrue(snapshot["capable"])

    def test_other_platforms_have_no_container(self):
        self.assertIsNone(widget.container_dir({"HOME": "/tmp"}, "linux"))
        self.assertIsNone(widget.container_dir({"HOME": "/tmp"}, "windows"))

    def test_no_absolute_paths_beyond_the_mount_point(self):
        blob = json.dumps(build())
        self.assertNotIn("/Users/", blob)
        self.assertNotIn("/Volumes/Projects", blob)
        self.assertNotIn("planId", blob)
        self.assertNotIn("path\"", blob)


class Publish(unittest.TestCase):
    def test_publish_writes_atomically_into_the_container(self):
        seen = {}
        result = widget.publish({"status": "up-to-date"}, group_dir="/tmp/nowhere",
                                write_fn=lambda path, blob: seen.update(path=path, blob=blob))
        self.assertTrue(result["published"])
        self.assertEqual(seen["path"], os.path.join("/tmp/nowhere", widget.SNAPSHOT_FILE_NAME))
        self.assertIn(b'"status":"up-to-date"', seen["blob"])

    def test_publish_without_container_is_honest(self):
        result = widget.publish({}, env={"HOME": "/nonexistent"}, platform="macos")
        self.assertFalse(result["published"])
        self.assertIsNone(result["path"])
        self.assertTrue(result["reason"])

    def test_publish_on_other_platforms_is_honest(self):
        result = widget.publish({}, env={"HOME": "/tmp"}, platform="linux")
        self.assertFalse(result["published"])

    def test_publish_writes_a_real_file_atomically(self):
        with tempfile.TemporaryDirectory() as base:
            result = widget.publish({"schemaVersion": 1}, env={"OSLAB_WIDGET_GROUP_DIR": base})
            self.assertTrue(result["published"])
            path = os.path.join(base, widget.SNAPSHOT_FILE_NAME)
            with open(path) as handle:
                self.assertEqual(json.load(handle), {"schemaVersion": 1})
            self.assertFalse(os.path.exists(path + ".tmp"))
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
