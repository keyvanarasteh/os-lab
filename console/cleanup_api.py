"""Cleanup Lab HTTP contracts (``/api/cleanup/...``).

The console accepts typed, validated calls only: never a command string and never
a free-form path list from the page (``cleanup-lab/README.md``). Ready:
readiness (CLN-01), the detector catalog (CLN-02), the scan job (CLN-03) and the
plan → clean flow (CLN-13) and audit history (CLN-15); the remaining endpoints add
their own actions here, each validated again by the engine's safety guard.

The engine is imported from ``cleanup-lab/engine`` (``cleanup_lab``), which is a
plain standard-library package: the console does not install it.

Long work runs as an in-process console job: ``POST /api/cleanup/scan`` starts a
scan, ``POST /api/cleanup/plan`` builds a plan (guard, measure, fingerprint),
``POST /api/cleanup/clean {planId}`` runs a confirmed plan — each on a worker
thread polled through ``GET /api/cleanup/jobs/<id>`` and cancelled through
``POST /api/cleanup/jobs/<id>/cancel``. The job store keeps the most recent
:data:`MAX_JOBS` jobs; the plan store keeps the most recent :data:`MAX_PLANS`
plans with the fingerprints that expire them. Both live only in this console
process, like the lab jobs: a restart loses them, and nothing is persisted.
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
import time
import uuid

MAX_JOBS = 20
MAX_PLANS = 20
MAX_ENTRY_IDS = 200
#: The only keys a scan request may carry. Paths are deliberately not among
#: them: the scan walks the catalog, never a list the page sends.
SCAN_KEYS = ("entryIds", "workers")
#: The only keys a plan request may carry; ``mode`` defaults to ``trash``.
PLAN_KEYS = ("entryIds", "workers", "mode")
#: The only key a clean request may carry: which confirmed plan to run.
CLEAN_KEYS = ("planId",)
RULE_ADD_KEYS = ("kind", "value", "enabled")
RULE_UPDATE_KEYS = RULE_ADD_KEYS
SCHEDULE_ADD_KEYS = ("cron", "entryIds", "enabled")
SCHEDULE_TOGGLE_KEYS = ("enabled",)
#: Engine ``PlanError.code`` → HTTP status on the plan → clean namespace.
PLAN_STATUS = {
    "plan-invalid": 400,
    "unknown-plan": 404,
    "expired": 410,
    "stale": 409,
    "used": 409,
    "cancelled": 409,
}
BODY_KEYS = {"scan": SCAN_KEYS, "plan": PLAN_KEYS, "clean": CLEAN_KEYS,
             "rule-add": RULE_ADD_KEYS, "rule-update": RULE_UPDATE_KEYS,
             "rule-delete": (), "schedule-add": SCHEDULE_ADD_KEYS,
             "schedule-toggle": SCHEDULE_TOGGLE_KEYS, "schedule-delete": ()}


class CleanupError(ValueError):
    """A request the Cleanup Lab refused, with the HTTP status to answer."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _module(root, name):
    engine = os.path.join(root, "cleanup-lab", "engine")
    if engine not in sys.path:
        sys.path.insert(0, engine)
    try:
        return importlib.import_module("cleanup_lab." + name)
    except ImportError as exc:  # a lone console copy without the engine
        raise CleanupError(501, "The cleanup engine (cleanup-lab/engine) is not installed") from exc


def _query(query):
    """Reject duplicate or unexpected query parameters instead of guessing."""
    if query:
        raise CleanupError(400, "Unexpected query parameters")


def _object_body(body, kind):
    """Every POST body is a JSON object carrying that action's keys and no others."""
    if not isinstance(body, dict):
        raise CleanupError(400, "Expected a JSON object")
    unknown = set(body) - set(BODY_KEYS[kind])
    if unknown:
        raise CleanupError(400, "Unexpected key(s): {0}".format(", ".join(sorted(unknown))))


def _validate_entry_ids(root, catalog, entry_ids, *, required=False):
    """Catalog ids only, unique, known, bounded — never paths, never commands."""
    if entry_ids is None:
        if required:
            raise CleanupError(400, "entryIds is required")
        return None
    if (
        not isinstance(entry_ids, list)
        or not entry_ids
        or any(not isinstance(item, str) or not item for item in entry_ids)
    ):
        raise CleanupError(400, "entryIds must be a list of detector ids")
    if len(set(entry_ids)) != len(entry_ids):
        raise CleanupError(400, "entryIds contains duplicates")
    if len(entry_ids) > MAX_ENTRY_IDS:
        raise CleanupError(400, "Too many detector ids")
    try:
        known = {entry["id"] for entry in catalog.load(root)}
    except catalog.CatalogError as exc:
        raise CleanupError(500, "The detector catalog is invalid: {0}".format(exc)) from exc
    unknown = sorted(set(entry_ids) - known)
    if unknown:
        raise CleanupError(400, "Unknown detector id(s): {0}".format(", ".join(unknown)))
    return entry_ids


def _validate_workers(scan, workers):
    if workers is None:
        return None
    if not isinstance(workers, int) or isinstance(workers, bool):
        raise CleanupError(400, "workers must be a whole number")
    if not 1 <= workers <= scan.MAX_WORKERS:
        raise CleanupError(400, "workers must be between 1 and {0}".format(scan.MAX_WORKERS))
    return workers


class CleanupJob:
    """One running (or finished) cleanup action: a scan, a plan or a clean."""

    def __init__(self, kind, request):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.state = "running"
        self.request = request
        if kind == "clean":
            self.progress = {
                "phase": "queued",
                "itemsDone": 0,
                "itemsTotal": 0,
                "bytesRemoved": 0,
                "currentPath": "",
            }
        else:
            self.progress = {
                "phase": "queued",
                "pathsDone": 0,
                "pathsTotal": 0,
                "bytesSeen": 0,
                "filesSeen": 0,
                "currentPath": "",
            }
        self.result = None
        self.error = None
        self.startedAt = time.time()
        self.finishedAt = None
        self.cancel = threading.Event()

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "request": self.request,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "startedAt": self.startedAt,
            "finishedAt": self.finishedAt,
        }


class PlanRecord:
    """A built plan plus its single-use flag (the engine's Plan stays pure)."""

    def __init__(self, plan):
        self.plan = plan
        self.used = False

    @property
    def id(self):
        return self.plan.id

    @property
    def created_at(self):
        return self.plan.created_at


class CleanupJobStore:
    """The console's cleanup jobs (scan, plan, clean). One store per process."""

    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def _register(self, job):
        with self.lock:
            self.jobs[job.id] = job
            self._prune_locked()
        return job

    def _spawn(self, job, target, args):
        try:
            threading.Thread(target=target, args=args, daemon=True).start()
        except RuntimeError as exc:
            job.state = "failed"
            job.error = "Could not start the job worker: {0}".format(exc)
            job.finishedAt = time.time()
        return job

    def start_scan(self, root, request):
        """Validate the scan request, then run it on a worker thread.

        ``request`` may name ``entryIds`` (catalog ids only) and ``workers``;
        anything else — a path, a command, an unknown key — is refused before a
        thread exists.
        """
        scan = _module(root, "scan")
        catalog = _module(root, "catalog")
        entry_ids = _validate_entry_ids(root, catalog, request.get("entryIds"))
        workers = _validate_workers(scan, request.get("workers"))
        job = CleanupJob("scan", {"entryIds": entry_ids, "workers": workers})
        self._register(job)
        return self._spawn(job, self._run_scan, (root, job, entry_ids, workers))

    def start_plan(self, root, request):
        """Validate the plan request, then build the plan on a worker thread.

        The typed keys of a scan plus ``mode`` (``trash`` by default; ``delete``
        must be explicit). ``entryIds`` is required — a plan always names what it
        would clean. The request carries no path list and no command.
        """
        clean = _module(root, "clean")
        scan = _module(root, "scan")
        catalog = _module(root, "catalog")
        entry_ids = _validate_entry_ids(root, catalog, request.get("entryIds"), required=True)
        workers = _validate_workers(scan, request.get("workers"))
        mode = request.get("mode", clean.DEFAULT_MODE)
        if mode not in clean.MODES:
            raise CleanupError(400, "mode must be one of {0}".format(", ".join(clean.MODES)))
        job = CleanupJob("plan", {"entryIds": entry_ids, "workers": workers, "mode": mode})
        self._register(job)
        return self._spawn(job, self._run_plan, (root, job, entry_ids, workers, mode))

    def start_clean(self, root, plan_id):
        """Claim the plan (single-use, unexpired) and run it on a worker thread.

        The cheap checks — unknown, already run, past its TTL — answer here; the
        expensive one (an item changed since the plan was made) is re-checked
        inside the job, which then fails honestly with nothing removed.
        """
        clean = _module(root, "clean")
        try:
            _module(root, "history").prepare()
        except Exception as exc:
            raise CleanupError(500, "Audit history is unavailable: {0}".format(exc)) from exc
        try:
            record = PLANS.claim(plan_id)
        except PlanStoreError as exc:
            raise CleanupError(PLAN_STATUS.get(exc.code, 409), str(exc)) from exc
        job = CleanupJob("clean", {"planId": plan_id})
        self._register(job)
        return self._spawn(job, self._run_clean, (root, job, record.plan, clean))

    def _run_scan(self, root, job, entry_ids, workers):
        def update(payload):
            job.progress = dict(payload)

        try:
            result = _module(root, "scan").scan_catalog(
                root, entry_ids, cancel=job.cancel, progress_callback=update, workers=workers
            )
            job.result = result
            job.progress = result["progress"]
            job.state = "cancelled" if result["cancelled"] else "done"
        except Exception as exc:  # the job must answer, never hang in "running"
            job.state = "failed"
            job.error = "{0}: {1}".format(type(exc).__name__, exc)
        finally:
            job.finishedAt = time.time()

    def _run_plan(self, root, job, entry_ids, workers, mode):
        def update(payload):
            job.progress = dict(payload)

        try:
            plan = _module(root, "clean").build_plan(
                root,
                entry_ids,
                mode=mode,
                workers=workers,
                cancel=job.cancel,
                progress_callback=update,
            )
            if plan.payload is None:  # cancelled before it finished: no plan exists
                job.progress = plan.progress
                job.state = "cancelled"
            else:
                PLANS.register(plan)
                job.result = plan.to_dict()
                job.progress = plan.progress
                job.state = "done"
        except Exception as exc:  # the job must answer, never hang in "running"
            job.state = "failed"
            job.error = "{0}: {1}".format(type(exc).__name__, exc)
        finally:
            job.finishedAt = time.time()

    def _run_clean(self, root, job, plan, clean):
        def update(payload):
            job.progress = dict(payload)

        try:
            measures = clean.verify_plan(plan, cancel=job.cancel)
            result = clean.execute_plan(
                plan, measures, cancel=job.cancel, progress_callback=update
            )
            job.result = result
            job.progress = result["progress"]
            _module(root, "history").append(result)
            job.state = "cancelled" if result["cancelled"] else "done"
        except clean.PlanError as exc:
            # A stale or expired plan fails the job honestly: nothing was removed.
            job.state = "failed"
            job.error = str(exc)
        except Exception as exc:  # the job must answer, never hang in "running"
            job.state = "failed"
            job.error = "{0}: {1}".format(type(exc).__name__, exc)
        finally:
            job.finishedAt = time.time()

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def list(self):
        with self.lock:
            return [
                job.to_dict()
                for job in sorted(self.jobs.values(), key=lambda j: j.startedAt, reverse=True)
            ]

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            job.cancel.set()
            return job

    def _prune_locked(self):
        finished = sorted(
            (j for j in self.jobs.values() if j.state != "running"),
            key=lambda j: j.startedAt,
        )
        for old in finished[:-MAX_JOBS]:
            self.jobs.pop(old.id, None)


class PlanStoreError(ValueError):
    """A plan was refused by the store. ``code`` maps to an HTTP status."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class PlanStore:
    """The console's built plans, each single-use, with the fingerprints that expire them."""

    def __init__(self):
        self.plans = {}
        self.lock = threading.Lock()

    def register(self, plan):
        with self.lock:
            self.plans[plan.id] = PlanRecord(plan)
            self._prune_locked()
        return plan

    def get(self, plan_id):
        with self.lock:
            return self.plans.get(plan_id)

    def claim(self, plan_id, *, clock=time.time):
        """Mark the plan as run — atomically, so one plan can never run twice."""
        with self.lock:
            record = self.plans.get(plan_id)
            if record is None:
                raise PlanStoreError("Unknown plan id.", "unknown-plan")
            if record.used:
                raise PlanStoreError("This plan was already run. Build a new plan.", "used")
            if record.plan.expires_at < clock():
                raise PlanStoreError("This plan expired; build a new one.", "expired")
            record.used = True
            return record

    def _prune_locked(self):
        ordered = sorted(self.plans.values(), key=lambda record: record.created_at, reverse=True)
        for old in ordered[MAX_PLANS:]:
            self.plans.pop(old.id, None)


#: One store per console process; the handler instances are per-request.
JOBS = CleanupJobStore()
PLANS = PlanStore()


def run_due_schedules(root, *, now=None):
    """Launch only scans for this minute; completion writes a compact report."""
    schedules = _module(root, "schedules")
    launched = []
    for row in schedules.claim_due(now):
        try:
            job = JOBS.start_scan(root, {"entryIds": row["entryIds"]})
            job.request["scheduleId"] = row["id"]
        except Exception as exc:
            schedules.record(row["id"], {"state": "failed", "error": str(exc), "finishedAt": time.time()})
            continue

        def finish(schedule_id, active):
            while active.state == "running":
                time.sleep(0.05)
            result = active.result or {}
            schedules.record(schedule_id, {"state": active.state, "jobId": active.id,
                                          "totals": result.get("totals"), "error": active.error,
                                          "finishedAt": active.finishedAt})

        threading.Thread(target=finish, args=(row["id"], job), daemon=True).start()
        launched.append(job)
    return launched


def start_schedule_runner(root):
    """Console-lifetime hook. Missed minutes are not replayed after shutdown."""
    def loop():
        while True:
            try:
                run_due_schedules(root)
            except Exception as exc:
                print("Cleanup schedule runner: {0}: {1}".format(type(exc).__name__, exc),
                      file=sys.stderr)
            time.sleep(15)
    threading.Thread(target=loop, daemon=True, name="cleanup-schedules").start()


class CleanupAPI:
    # @lat: [[cleanup-lab#Console API]]
    def __init__(self, root):
        self.root = os.path.realpath(root)

    def get(self, path, query):
        if path == "/api/cleanup/status":
            _query(query)
            return _module(self.root, "readiness").probe(self.root)
        if path == "/api/cleanup/catalog":
            _query(query)
            catalog = _module(self.root, "catalog")
            try:
                return catalog.report(self.root)
            except catalog.CatalogError as exc:
                raise CleanupError(500, "The detector catalog is invalid: {0}".format(exc)) from exc
        if path == "/api/cleanup/rules":
            _query(query)
            return _module(self.root, "rules").read()
        if path == "/api/cleanup/schedules":
            _query(query)
            try:
                return _module(self.root, "schedules").read()
            except ValueError as exc:
                raise CleanupError(500, str(exc)) from exc
        if path == "/api/cleanup/history":
            _query(query)
            try:
                return _module(self.root, "history").read()
            except Exception as exc:
                raise CleanupError(500, "Audit history is unavailable: {0}".format(exc)) from exc
        if path == "/api/cleanup/jobs":
            _query(query)
            return {"jobs": JOBS.list()}
        if path.startswith("/api/cleanup/jobs/"):
            _query(query)
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:3] == ["api", "cleanup", "jobs"]:
                job = JOBS.get(parts[3])
                if job is None:
                    raise CleanupError(404, "Job not found")
                return job.to_dict()
            raise CleanupError(404, "Cleanup Lab endpoint not found")
        raise CleanupError(404, "Cleanup Lab endpoint not found")

    def post(self, path, body):
        """The typed POST surface: start a scan, plan or clean; cancel a job."""
        if path == "/api/cleanup/scan":
            _object_body(body, "scan")
            return JOBS.start_scan(self.root, body)
        if path == "/api/cleanup/rules":
            _object_body(body, "rule-add")
            try:
                return _module(self.root, "rules").add(body.get("kind"), body.get("value"),
                                                          enabled=body.get("enabled", True))
            except ValueError as exc:
                raise CleanupError(400, str(exc)) from exc
        if path == "/api/cleanup/schedules":
            _object_body(body, "schedule-add")
            cron = body.get("cron")
            entry_ids = _validate_entry_ids(self.root, _module(self.root, "catalog"),
                                            body.get("entryIds"), required=True)
            try:
                return _module(self.root, "schedules").add(cron, entry_ids,
                    enabled=body.get("enabled", True))
            except ValueError as exc:
                raise CleanupError(400, str(exc)) from exc
        schedule_parts = path.strip("/").split("/")
        if len(schedule_parts) == 5 and schedule_parts[:3] == ["api", "cleanup", "schedules"]:
            schedule_id, action = schedule_parts[3], schedule_parts[4]
            schedules = _module(self.root, "schedules")
            try:
                if action == "toggle":
                    _object_body(body, "schedule-toggle")
                    if "enabled" not in body:
                        raise CleanupError(400, "enabled is required")
                    return schedules.toggle(schedule_id, body["enabled"])
                if action == "delete":
                    _object_body(body, "schedule-delete")
                    return schedules.delete(schedule_id)
            except schedules.ScheduleError as exc:
                raise CleanupError(404 if str(exc) == "Schedule not found" else 400, str(exc)) from exc
        rule_parts = path.strip("/").split("/")
        if len(rule_parts) == 5 and rule_parts[:3] == ["api", "cleanup", "rules"]:
            rule_id, action = rule_parts[3], rule_parts[4]
            rules = _module(self.root, "rules")
            try:
                if action == "update":
                    _object_body(body, "rule-update")
                    if not body:
                        raise CleanupError(400, "Rule update needs a field")
                    return rules.update(rule_id, **body)
                if action == "delete":
                    _object_body(body, "rule-delete")
                    return rules.delete(rule_id)
            except rules.RulesError as exc:
                status = 404 if str(exc) == "Ignore rule not found" else 400
                raise CleanupError(status, str(exc)) from exc
        if path == "/api/cleanup/plan":
            _object_body(body, "plan")
            return JOBS.start_plan(self.root, body)
        if path == "/api/cleanup/clean":
            _object_body(body, "clean")
            plan_id = body.get("planId")
            if not isinstance(plan_id, str) or not plan_id:
                raise CleanupError(400, "planId must be the id of a built plan")
            return JOBS.start_clean(self.root, plan_id)
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:3] == ["api", "cleanup", "jobs"] and parts[4] == "cancel":
            if body:
                raise CleanupError(400, "A cancel request carries no body")
            job = JOBS.cancel(parts[3])
            if job is None:
                raise CleanupError(404, "Job not found")
            return job.to_dict()
        raise CleanupError(404, "Cleanup Lab endpoint not found")
