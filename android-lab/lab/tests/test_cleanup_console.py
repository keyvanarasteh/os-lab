"""Console contract: typed scan, plan and clean jobs with polling and cancel.

The engine behaviour is covered by ``cleanup-lab/engine/tests/test_scan.py`` and
``test_clean.py``; these tests hold the HTTP-shaped layer to the same rules: no
free-form paths, catalog ids only, a plan that is single-use and expires when an
item changes, and a job that always answers.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer

import pytest

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))
sys.path.insert(0, os.path.join(REPO_ROOT, "cleanup-lab", "engine"))

import cleanup_api  # noqa: E402
from cleanup_lab import catalog as catalog_module  # noqa: E402
from cleanup_lab import paths as paths_module  # noqa: E402
from cleanup_lab import privileged as privileged_module  # noqa: E402
from cleanup_lab import volumes as volumes_module  # noqa: E402


def wait_for(job, state=None, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if state is None and job.state != "running":
            return job
        if state is not None and job.state == state:
            return job
        time.sleep(0.01)
    raise AssertionError("job stayed {0!r}".format(job.state))


@pytest.fixture(autouse=True)
def clean_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("OSLAB_CLEANUP_STATE", str(tmp_path / "state"))
    def drain():
        for job in list(cleanup_api.JOBS.jobs.values()):
            job.cancel.set()
        deadline = time.time() + 10
        while time.time() < deadline:
            if not any(job.state == "running" for job in cleanup_api.JOBS.jobs.values()):
                return
            time.sleep(0.01)

    drain()
    cleanup_api.JOBS.jobs.clear()
    cleanup_api.PLANS.plans.clear()
    yield
    drain()
    cleanup_api.JOBS.jobs.clear()
    cleanup_api.PLANS.plans.clear()


def catalog_cache_target(tmp_path, monkeypatch):
    """Point HOME at the temp tree and return the catalog's user-cache folder."""
    platform = paths_module.platform_id()
    if platform not in ("macos", "linux"):
        pytest.skip("no catalog path for this test platform")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    if platform == "linux":
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))
    entry = next(
        item for item in catalog_module.load(REPO_ROOT) if item["id"] == "system.user-caches"
    )
    target = catalog_module.resolve(entry, platform)[0]["path"]
    os.makedirs(target, exist_ok=True)
    return target


def test_a_scan_job_measures_the_catalog_paths(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    with open(os.path.join(target, "one.bin"), "wb") as handle:
        handle.write(b"x" * 64)
    with open(os.path.join(target, "two.bin"), "wb") as handle:
        handle.write(b"y" * 36)

    api = cleanup_api.CleanupAPI(REPO_ROOT)
    job = api.post(
        "/api/cleanup/scan", {"entryIds": ["system.user-caches"], "workers": 1}
    )
    wait_for(job, "done")

    assert job.kind == "scan"
    assert job.request == {"entryIds": ["system.user-caches"], "workers": 1}
    assert job.error is None
    assert job.result["cancelled"] is False
    assert job.result["totals"]["sizeBytes"] == 100
    assert job.result["progress"]["phase"] == "done"
    path_report = job.result["entries"][0]["paths"][0]
    assert path_report["measured"] is True
    assert path_report["sizeBytes"] == 100
    assert job.finishedAt is not None

    polled = api.get("/api/cleanup/jobs/" + job.id, {})
    assert polled["id"] == job.id
    assert polled["state"] == "done"
    listed = api.get("/api/cleanup/jobs", {})
    assert [row["id"] for row in listed["jobs"]] == [job.id]


def test_ignore_rule_crud_and_plan_enforcement(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    ignored = os.path.join(target, "keep.bin")
    with open(ignored, "wb") as handle:
        handle.write(b"keep")
    api = cleanup_api.CleanupAPI(REPO_ROOT)

    assert api.get("/api/cleanup/rules", {})["rules"] == []
    rule = api.post("/api/cleanup/rules", {"kind": "extension", "value": ".bin"})
    assert rule["enabled"] is True
    assert api.get("/api/cleanup/rules", {})["rules"] == [rule]
    scanned = wait_done(api.post("/api/cleanup/scan", {"entryIds": ["system.user-caches"]}))
    report = scanned.result["entries"][0]["paths"][0]
    assert report["sizeBytes"] == 0
    assert ignored in report["ignored"]
    plan = wait_done(api.post("/api/cleanup/plan", {"entryIds": ["system.user-caches"]}))
    assert plan.result["items"][0]["code"] == "ignored"
    assert plan.result["totals"]["ready"] == 0

    updated = api.post("/api/cleanup/rules/{0}/update".format(rule["id"]), {"enabled": False})
    assert updated["enabled"] is False
    ready = wait_done(api.post("/api/cleanup/plan", {"entryIds": ["system.user-caches"]}))
    assert ready.result["totals"]["ready"] == 1
    api.post("/api/cleanup/rules/{0}/update".format(rule["id"]), {"enabled": True})
    refused = wait_for(api.post("/api/cleanup/clean", {"planId": ready.result["planId"]}), "failed")
    assert "Ignore rules changed" in refused.error
    assert os.path.exists(ignored)
    assert api.post("/api/cleanup/rules/{0}/delete".format(rule["id"]), {}) == {"deleted": rule["id"]}
    assert api.get("/api/cleanup/rules", {})["rules"] == []

    for body in ({"kind": "extension", "value": ".bin", "command": "rm"},
                 {"kind": "path", "value": "relative"},
                 {"kind": "extension", "value": "bin"}):
        with pytest.raises(cleanup_api.CleanupError) as caught:
            api.post("/api/cleanup/rules", body)
        assert caught.value.status == 400
    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.post("/api/cleanup/rules/nope/delete", {})
    assert caught.value.status == 404


def test_scheduled_scan_crud_and_runner(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    with open(os.path.join(target, "report.bin"), "wb") as handle:
        handle.write(b"report")
    api = cleanup_api.CleanupAPI(REPO_ROOT)
    assert api.get("/api/cleanup/schedules", {})["schedules"] == []
    row = api.post("/api/cleanup/schedules", {"cron": "* * * * *",
                                            "entryIds": ["system.user-caches"]})
    assert row["enabled"] is True
    jobs = cleanup_api.run_due_schedules(REPO_ROOT, now=60)
    assert len(jobs) == 1
    assert jobs[0].kind == "scan"
    assert jobs[0].request["scheduleId"] == row["id"]
    wait_done(jobs[0])
    assert cleanup_api.run_due_schedules(REPO_ROOT, now=61) == []
    deadline = time.time() + 5
    while api.get("/api/cleanup/schedules", {})["schedules"][0]["lastRun"] is None and time.time() < deadline:
        time.sleep(0.01)
    report = api.get("/api/cleanup/schedules", {})["schedules"][0]["lastRun"]
    assert report["state"] == "done"
    assert report["totals"]["sizeBytes"] == 6
    api.post("/api/cleanup/schedules/{0}/toggle".format(row["id"]), {"enabled": False})
    assert cleanup_api.run_due_schedules(REPO_ROOT, now=120) == []
    assert api.post("/api/cleanup/schedules/{0}/delete".format(row["id"]), {}) == {"deleted": row["id"]}
    for body in ({"cron": "bad", "entryIds": ["system.user-caches"]},
                 {"cron": "* * * * *", "entryIds": ["nope"]},
                 {"cron": "* * * * *", "entryIds": ["system.user-caches"], "command": "rm"}):
        with pytest.raises(cleanup_api.CleanupError) as caught:
            api.post("/api/cleanup/schedules", body)
        assert caught.value.status == 400


def test_privileged_contract_requires_preview_and_audits_result(monkeypatch):
    api = cleanup_api.CleanupAPI(REPO_ROOT)
    assert api.get("/api/cleanup/disk-access", {})["state"] in ("not-applicable", "unknown", "accessible", "limited")
    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.post("/api/cleanup/privileged/plan", {"actionIds": ["system.apt-cache-clean"], "command": "sh"})
    assert caught.value.status == 400

    monkeypatch.setattr(privileged_module, "preview", lambda ids: {"planId": "abc", "actions": ids})
    monkeypatch.setattr(privileged_module, "run", lambda plan_id: {
        "planId": plan_id, "mode": "privileged", "results": [],
        "totals": {"items": 0, "failed": 0, "bytes": 0}, "cancelled": False})
    preview = api.post("/api/cleanup/privileged/plan", {"actionIds": ["system.apt-cache-clean"]})
    assert preview["planId"] == "abc"
    result = api.post("/api/cleanup/privileged/run", {"planId": preview["planId"]})
    assert result["mode"] == "privileged"
    assert api.get("/api/cleanup/history", {})["total"] == 1


def test_volumes_endpoint_is_read_only_and_rejects_queries(monkeypatch):
    monkeypatch.setattr(volumes_module, "report", lambda: {
        "platform": "linux", "thresholdPercent": 85, "homeVolume": "/",
        "volumes": [{"mountPoint": "/", "pressure": False, "home": True}],
    })
    api = cleanup_api.CleanupAPI(REPO_ROOT)
    assert api.get("/api/cleanup/volumes", {})["volumes"][0]["home"] is True
    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.get("/api/cleanup/volumes", {"path": ["/tmp"]})
    assert caught.value.status == 400


def test_the_scan_request_accepts_catalog_ids_only():
    api = cleanup_api.CleanupAPI(REPO_ROOT)
    refused = [
        {"path": "/tmp"},
        {"entryIds": ["system.user-caches"], "root": "/tmp"},
        {"entryIds": []},
        {"entryIds": "system.user-caches"},
        {"entryIds": ["nope.entry"]},
        {"entryIds": ["system.user-caches", "system.user-caches"]},
        {"entryIds": [1]},
        {"workers": 0},
        {"workers": cleanup_api._module(REPO_ROOT, "scan").MAX_WORKERS + 1},
        {"workers": True},
        {"workers": "4"},
    ]
    for body in refused:
        with pytest.raises(cleanup_api.CleanupError) as caught:
            api.post("/api/cleanup/scan", body)
        assert caught.value.status == 400, body


def test_unknown_jobs_and_endpoints_are_404():
    api = cleanup_api.CleanupAPI(REPO_ROOT)
    for path in ("/api/cleanup/jobs/nope", "/api/cleanup/jobs/nope/cancel"):
        with pytest.raises(cleanup_api.CleanupError) as caught:
            if path.endswith("/cancel"):
                api.post(path, {})
            else:
                api.get(path, {})
        assert caught.value.status == 404
    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.get("/api/cleanup/jobs/nope/deeper", {})
    assert caught.value.status == 404
    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.post("/api/cleanup/nope", {})
    assert caught.value.status == 404
    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.get("/api/cleanup/jobs", {"x": ["1"]})
    assert caught.value.status == 400


def test_cancel_reaches_a_running_scan(monkeypatch):
    """A fake catalog keeps the job running until cancel; the store maps it honestly."""

    def fake_scan(root, entry_ids, *, cancel, progress_callback, workers):
        progress_callback(
            {
                "phase": "scanning",
                "pathsDone": 0,
                "pathsTotal": 1,
                "bytesSeen": 0,
                "filesSeen": 0,
                "currentPath": "/fake",
            }
        )
        while not cancel.is_set():
            time.sleep(0.01)
        return {
            "cancelled": True,
            "entries": [],
            "totals": {},
            "progress": {"phase": "cancelled", "pathsDone": 0, "pathsTotal": 1},
        }

    class FakeModule:
        MAX_WORKERS = 4
        scan_catalog = staticmethod(fake_scan)

        @staticmethod
        def load(root):
            return [{"id": "fake.entry"}]

    monkeypatch.setattr(cleanup_api, "_module", lambda root, name: FakeModule())
    api = cleanup_api.CleanupAPI(REPO_ROOT)
    job = api.post("/api/cleanup/scan", {"entryIds": ["fake.entry"]})
    deadline = time.time() + 5
    while job.progress["currentPath"] != "/fake" and time.time() < deadline:
        time.sleep(0.01)
    assert job.progress["currentPath"] == "/fake"

    answer = api.post("/api/cleanup/jobs/{0}/cancel".format(job.id), {})
    assert answer["id"] == job.id
    wait_for(job, "cancelled")
    assert job.result["cancelled"] is True
    assert job.progress["phase"] == "cancelled"

    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.post("/api/cleanup/jobs/{0}/cancel".format(job.id), {"force": True})
    assert caught.value.status == 400


def test_the_browser_route_starts_polls_and_cancels(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    with open(os.path.join(target, "blob.bin"), "wb") as handle:
        handle.write(b"z" * 4096)

    from web_ui import LabHttpHandler

    server = HTTPServer(("127.0.0.1", 0), LabHttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:{0}".format(server.server_address[1])

    def call(path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = (
            {"Content-Type": "application/json", "X-OSLab": "1"} if body is not None else {}
        )
        request = urllib.request.Request(base + path, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, json.loads(answer.read().decode("utf-8"))

    try:
        status, started = call(
            "/api/cleanup/scan", {"entryIds": ["system.user-caches"], "workers": 1}
        )
        assert status == 202
        assert started["kind"] == "scan"
        deadline = time.time() + 10
        while time.time() < deadline:
            _, polled = call("/api/cleanup/jobs/" + started["id"])
            if polled["state"] != "running":
                break
            time.sleep(0.01)
        assert polled["state"] == "done"
        assert polled["result"]["totals"]["sizeBytes"] == 4096

        status, cancelled = call("/api/cleanup/jobs/{0}/cancel".format(started["id"]), {})
        assert status == 200
        assert cancelled["id"] == started["id"]
    finally:
        server.shutdown()
        server.server_close()


def wait_done(job, timeout=10):
    return wait_for(job, "done", timeout)


def test_a_plan_is_previewed_then_cleaned_from_the_console(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    with open(os.path.join(target, "one.bin"), "wb") as handle:
        handle.write(b"x" * 120)

    api = cleanup_api.CleanupAPI(REPO_ROOT)
    plan_job = wait_done(
        api.post("/api/cleanup/plan", {"entryIds": ["system.user-caches"], "workers": 1})
    )
    assert plan_job.kind == "plan"
    assert plan_job.error is None
    payload = plan_job.result
    assert payload["mode"] == "trash"
    assert payload["totals"]["ready"] == 1
    item = payload["items"][0]
    assert item["status"] == "ready"
    assert (item["sizeBytes"], item["files"]) == (120, 1)
    plan_id = payload["planId"]
    assert plan_id and plan_id == plan_job.result["planId"]

    clean_job = wait_done(api.post("/api/cleanup/clean", {"planId": plan_id}))
    assert clean_job.kind == "clean"
    assert clean_job.error is None
    result = clean_job.result
    assert result["planId"] == plan_id
    assert result["results"][0]["status"] == "trashed"
    assert result["totals"]["trashed"] == 1
    assert result["totals"]["bytes"] == 120
    assert not os.path.exists(os.path.join(target, "one.bin"))
    assert os.path.exists(result["results"][0]["trashPath"])

    listed = api.get("/api/cleanup/jobs", {})
    assert [row["kind"] for row in listed["jobs"]] == ["clean", "plan"]
    history = api.get("/api/cleanup/history", {})
    assert history["verified"] is True
    assert history["total"] == 1
    assert history["entries"][0]["result"]["results"][0]["path"] == target


def test_plan_and_clean_requests_are_typed(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    with open(os.path.join(target, "one.bin"), "wb") as handle:
        handle.write(b"x" * 10)

    api = cleanup_api.CleanupAPI(REPO_ROOT)
    for body in (
        {"path": target},
        {"entryIds": ["system.user-caches"], "root": target},
        {"entryIds": ["system.user-caches"], "command": "rm -rf"},
        {},
        {"entryIds": []},
        {"entryIds": "system.user-caches"},
        {"entryIds": ["nope.entry"]},
        {"entryIds": ["system.user-caches", "system.user-caches"]},
        {"entryIds": ["system.user-caches"], "mode": "shred"},
        {"entryIds": ["system.user-caches"], "workers": 0},
        {"entryIds": ["system.user-caches"], "workers": True},
    ):
        with pytest.raises(cleanup_api.CleanupError) as caught:
            api.post("/api/cleanup/plan", body)
        assert caught.value.status == 400, body

    for body in ({}, {"planId": ""}, {"planId": 3}, {"planId": "x", "force": True}):
        with pytest.raises(cleanup_api.CleanupError) as caught:
            api.post("/api/cleanup/clean", body)
        assert caught.value.status == 400, body

    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.post("/api/cleanup/clean", {"planId": "not-a-plan"})
    assert caught.value.status == 404


def test_a_changed_item_fails_the_clean_and_removes_nothing(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    original = os.path.join(target, "one.bin")
    with open(original, "wb") as handle:
        handle.write(b"x" * 20)

    api = cleanup_api.CleanupAPI(REPO_ROOT)
    plan = wait_done(api.post("/api/cleanup/plan", {"entryIds": ["system.user-caches"]}))
    with open(os.path.join(target, "added.bin"), "wb") as handle:
        handle.write(b"new")

    job = wait_for(api.post("/api/cleanup/clean", {"planId": plan.result["planId"]}), "failed")
    assert "changed since it was confirmed" in job.error
    assert job.result is None
    assert os.path.exists(original)
    assert os.path.exists(os.path.join(target, "added.bin"))
    assert not os.path.exists(os.path.join(tmp_path, ".Trash"))


def test_a_plan_is_single_use_and_expires(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    with open(os.path.join(target, "one.bin"), "wb") as handle:
        handle.write(b"x" * 5)

    api = cleanup_api.CleanupAPI(REPO_ROOT)
    plan = wait_done(api.post("/api/cleanup/plan", {"entryIds": ["system.user-caches"]}))
    plan_id = plan.result["planId"]
    wait_done(api.post("/api/cleanup/clean", {"planId": plan_id}))

    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.post("/api/cleanup/clean", {"planId": plan_id})
    assert caught.value.status == 409
    assert "already run" in str(caught.value)

    second = wait_done(api.post("/api/cleanup/plan", {"entryIds": ["system.user-caches"]}))
    record = cleanup_api.PLANS.get(second.result["planId"])
    assert record is not None
    record.plan.expires_at = time.time() - 1
    with pytest.raises(cleanup_api.CleanupError) as caught:
        api.post("/api/cleanup/clean", {"planId": second.result["planId"]})
    assert caught.value.status == 410
    assert "expired" in str(caught.value)


def test_the_browser_route_plans_and_cleans(tmp_path, monkeypatch):
    target = catalog_cache_target(tmp_path, monkeypatch)
    with open(os.path.join(target, "blob.bin"), "wb") as handle:
        handle.write(b"z" * 64)

    from web_ui import LabHttpHandler

    server = HTTPServer(("127.0.0.1", 0), LabHttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:{0}".format(server.server_address[1])

    def call(path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = (
            {"Content-Type": "application/json", "X-OSLab": "1"} if body is not None else {}
        )
        request = urllib.request.Request(base + path, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, json.loads(answer.read().decode("utf-8"))

    def wait(identifier):
        deadline = time.time() + 10
        while time.time() < deadline:
            _, job = call("/api/cleanup/jobs/" + identifier)
            if job["state"] != "running":
                return job
            time.sleep(0.01)
        raise AssertionError("job stayed running")

    try:
        status, plan = call("/api/cleanup/plan", {"entryIds": ["system.user-caches"]})
        assert status == 202
        plan = wait(plan["id"])
        assert plan["state"] == "done"
        assert plan["result"]["items"][0]["status"] == "ready"

        status, clean = call("/api/cleanup/clean", {"planId": plan["result"]["planId"]})
        assert status == 202
        clean = wait(clean["id"])
        assert clean["state"] == "done"
        assert clean["result"]["results"][0]["status"] == "trashed"
        assert clean["result"]["totals"]["bytes"] == 64
    finally:
        server.shutdown()
        server.server_close()
