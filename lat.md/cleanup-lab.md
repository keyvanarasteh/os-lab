# Cleanup Lab

A disk-cleanup lab: measure reclaimable space, show every item with its size and
risk, and clean only through a confirmed plan. The behaviour is ported from
Qleaner; its code, styling and known bugs are not.

## Layers

The engine is a standard-library Python package; the console and `labctl` are thin
typed layers over it.

The package lives in [[cleanup-lab/engine/cleanup_lab]]. `readiness`, `paths`, the
catalog loader (CLN-02), the scan job (CLN-03), the safety guard (CLN-12) and the
plan → clean executor (CLN-13), audit history (CLN-15) and ignore rules (CLN-17) exist now. One module, `safety.py`,
guards every destructive call, so no other module may delete, move or shred.

Target paths are data, never code: every platform path, risk class, owning process
and privilege flag belongs in `cleanup-lab/catalog/*.json` (CLN-02). Per-OS
resolution comes from [[cleanup-lab/engine/cleanup_lab/paths.py]].

[[console/cleanup_api.py]] answers `/api/cleanup/...` with typed, validated calls
and never accepts a command string or a free-form path list from the page.
[[android-lab/lab/web_ui.py]] routes the namespace before the static dashboard
fallthrough. Long work becomes a console job with preview, progress and cancel.

`labctl cleanup status|doctor|history [--json]` runs the same engine through
`cleanup_lab.cli`: exit `0` when ready, `1` when a required check fails, `2` for a
usage error, matching [[lat.md/labctl.md]].

## Catalog

Target paths are data. One JSON file per family under `cleanup-lab/catalog`, validated
against `schema.json`.

[[cleanup-lab/engine/cleanup_lab/catalog.py]] loads it: unique ids, a family prefix,
the known risk classes, and `defaultSelected` refused for `high`, `credentials` and
`privacy`. Templates (`~`, `{cache}`, `${VAR}`, `${VAR:-fallback}`, `%VAR%`) expand per
operating system; an unset variable yields `path: null` plus a reason instead of a
guess. [[cleanup-lab/PARITY.md]] maps every Qleaner detector id to a catalog id or to
why it was dropped, and [[cleanup-lab/catalog/README.md]] documents the format.

## Scan job

[[cleanup-lab/engine/cleanup_lab/scan.py]] measures the catalog's resolved paths
read-only, with progress and cancel.

Sizes come from `lstat`; a symlink is never followed or recursed into, a hard link
is counted once per scan by `(device, inode)`, and an unreadable path is reported in
`unreadable` instead of failing the scan. Apparent and on-disk sizes are separate
(on-disk may be `null`). One worker measures one top-level path, at most 16; the
callback is throttled, and a cancel returns the partial counters with
`"cancelled": true`.

## Plan → clean

[[cleanup-lab/engine/cleanup_lab/clean.py]] previews and runs destructive work; only a confirmed, unexpired plan can move a file.

Building is read-only: the guard checks each catalog path, one `lstat` walk records
its size and a fingerprint, and the plan lists every item as ready or skipped with a
reason. `POST /api/cleanup/plan` names catalog ids and an optional mode; `POST
/api/cleanup/clean {planId}` verifies the fingerprints, runs once, and reports
`trashed` / `deleted` / `skipped` / `failed`. Trash is the default; a failed Trash
is a failed item, never a silent delete, and bytes are counted only when the
original is gone.

[[cleanup-lab/engine/cleanup_lab/rules.py]] keeps path, extension and glob ignore
rules in a private JSON file. Scan walks omit matching paths. A plan skips a
catalog target when the target or any descendant matches, so cleaning a parent
cannot remove an ignored child. The plan records a digest of the rules and a rule
change makes confirmation stale; execution checks again before each item.

## Readiness

`readiness.py` reports what the engine can do on this host without writing anything.

[[cleanup-lab/engine/cleanup_lab/readiness.py]] checks the operating system, the
interpreter, the home folder, the Trash target and the private state folder; those
decide `ready`, `needs-setup` or `unavailable`. The detector catalog, the native
scan backend and the tools on `PATH` are optional capabilities, so a missing one
never blocks a scan.

`/cleanup/` will render that probe in the dashboard shell, offering only Re-check and
saying in words that cleaning is not wired yet; until that page lands,
`labctl cleanup status` and `GET /api/cleanup/status` are how to read it. Public Pages
has no engine, so the page will explain that instead of polling, per
[[lat.md/ux-readiness.md]].

## Console API

`console/cleanup_api.py` answers `/api/cleanup/...`; the web console routes that prefix
before the static dashboard fallthrough.

`GET /api/cleanup/status` and `GET /api/cleanup/catalog` are read-only.
`POST /api/cleanup/scan`, `POST /api/cleanup/plan` and `POST /api/cleanup/clean
{planId}` start jobs whose requests carry catalog ids, an optional worker count or
mode, and a plan id only. `GET /api/cleanup/jobs/<id>` returns progress and result;
`POST /api/cleanup/jobs/<id>/cancel` cancels. A request carries no command string and
no free-form path list: an unknown path is `404`, unexpected or duplicate query
parameters, unknown keys or unknown ids are `400`, and a missing engine is `501`.
A stale, expired or already-used plan is `409`/`410` with nothing removed. The job
lives in the console process, and its worker always ends in `done`, `cancelled` or
`failed` — never `running`. `GET /api/cleanup/history` returns the latest 100
verified runs from the private SQLite store. The store writes each completed
clean result with path, bytes, mode and outcome, chaining records with
HMAC-SHA256 and a random per-install key. `labctl cleanup history --verify`
checks the full chain and exits 1 on tampering. History is durable across console
restarts. `GET /api/cleanup/rules` lists private ignore rules; `POST` to that route
adds a typed rule, and `POST /api/cleanup/rules/<id>/update|delete` changes one.
Later tasks add volumes (CLN-28) and runtimes (CLN-29) here, each typed and validated again by the
engine.

[[cleanup-lab/engine/cleanup_lab/schedules.py]] keeps scan-only schedules in a
private store. Five-field cron expressions use the host's local time. The web
console starts a background hook that claims each due minute once and launches
an ordinary scan job; its last result is persisted. Stopped consoles do not
replay missed minutes. `GET /api/cleanup/schedules` lists schedules;
`POST /api/cleanup/schedules` adds one with catalog detector ids, and
`POST /api/cleanup/schedules/<id>/toggle|delete` changes it. A schedule cannot
start a plan or clean job.

## Safety

The eight rules in the README are the acceptance criteria for every task.

Every destructive call passes through [[cleanup-lab/engine/cleanup_lab/safety.py]]:
the target is resolved with its symlinks and must stay inside its catalog entry's
roots; it is refused when it is a protected or system root, when it is owned by
another account, or when an owning application is running (whole-name match against
the process table, not a Chrome/Firefox substring). `check_target()` returns a
verdict with a stable `code` and an English reason; `assert_safe_target()` raises
the same pair. Scans stay read-only (`lstat`, symlinks never followed). Cleaning is
plan → confirm → run with Trash by default, and a failed Trash never becomes a silent
permanent delete. Credentials and privacy data are never pre-selected. Bytes are
counted only when removed, every skip and failure carries a reason, and every run is
written to the audit history. Tests use generated temp trees and fake binaries,
never real user files.

## Tests

The engine tests run under `unittest` from the engine folder.

`cd cleanup-lab/engine && python3 -m unittest discover -s tests -p 'test_*.py'`
covers the probe, the catalog, the scan, plan → clean (guard, fingerprints,
Trash by default, honest failures), the path rules and the CLI exit codes.
Tests live in [[cleanup-lab/engine/tests]]; the console's typed job contract is
covered by [[android-lab/lab/tests/test_cleanup_console.py]]. [[scripts/run-tests.sh]]
runs the same suites next to the reference code tests, the Android suite, `bash -n`,
`lat check` and the dashboard build check.
