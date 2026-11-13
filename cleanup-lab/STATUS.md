# Cleanup Lab status

Maintainer ledger for the CLN roadmap. The task text is
[`../dashboard/src/views/cleanup-lab-tasks.tsx`](../dashboard/src/views/cleanup-lab-tasks.tsx),
the contract is [`README.md`](README.md), the evidence is [`VERIFY.md`](VERIFY.md).
One row per task; the row is updated in the next task's PR (or in a final docs PR
when the last task lands).

## Work split (decided 2026-11-13)

This Run owns the **engine layer**: `cleanup-lab/` (engine, catalog, PARITY,
VERIFY, this file), `console/cleanup_api.py`, `labctl`, the tests and `lat.md/`.
It does **not** write anything under `dashboard/` — not `api.ts`, not pages or
views, not the seven locale catalogs, not the rebuilt `dist`.

The **dashboard layer** is handed to Claude Code. Each task below carries a
"Dashboard handoff" section with the endpoint contract, the UI states and every
user-visible English string; that section is also in the PR body.

Why: the workspace write guard in this build rejects any file whose *existing*
content matches its credential-assignment heuristic (`assertWriteCarriesNoCredential`
runs on the whole content, with no path allowlist and `materializeArtifacts`
defaulting to true). `dashboard/src/lib/api.ts` contains TypeScript annotations
named `token` and every locale catalog contains UI copy mentioning passwords, so
those eight files cannot be written here. Nothing was worked around: the attempts,
the finding and the decision are in the session log.

## Ledger

| ID | Status | PR | Merge commit | Deliverables not done | Deviations | Student reservations / PRs |
|---|---|---|---|---|---|---|
| CLN-01 | merged | [#134](https://github.com/keyvanarasteh/os-lab/pull/134) | d04941f6 | `/cleanup/` page, sidebar entry, seven locale catalogs, dashboard screenshots — handed over below | dashboard layer deferred | none |
| CLN-02 | merged | [#135](https://github.com/keyvanarasteh/os-lab/pull/135) | 39ea0f1f | — | — | none |
| CLN-03 | merged | [#138](https://github.com/keyvanarasteh/os-lab/pull/138) | c253cf34 | `/cleanup/` scan page, sidebar/route, seven locale catalogs, dashboard screenshots — handed over below | dashboard layer deferred | none |
| CLN-04 | pending | — | — | — | — | none |
| CLN-05 | pending | — | — | — | — | none |
| CLN-06 | pending | — | — | — | — | none |
| CLN-07 | pending | — | — | — | — | none |
| CLN-08 | pending | — | — | — | — | none |
| CLN-09 | pending | — | — | — | — | none |
| CLN-10 | pending | — | — | — | — | none |
| CLN-11 | pending | — | — | — | — | none |
| CLN-12 | merged | [#136](https://github.com/keyvanarasteh/os-lab/pull/136) | 3d5ab866 | — | — | none |
| CLN-13 | merged | [#139](https://github.com/keyvanarasteh/os-lab/pull/139) | 6656ed55 | `/cleanup/` plan + confirm UI, mode picker, seven locale catalogs, dashboard screenshots — handed over below | dashboard layer deferred to CLN-16 | none |
| CLN-14 | pending | — | — | — | — | none |
| CLN-15 | in progress (this PR) | [#140](https://github.com/keyvanarasteh/os-lab/pull/140) | — | history view on `/cleanup/` belongs to CLN-16 | dashboard layer deferred to CLN-16 | none |
| CLN-16 | pending | — | — | dashboard page is the whole task | console side only | none |
| CLN-17 | in progress (this PR) | [#154](https://github.com/keyvanarasteh/os-lab/pull/154) | — | plain settings controls on `/cleanup/` after CLN-16 lands | backend and typed API first | none |
| CLN-18 | in progress (this PR) | [#155](https://github.com/keyvanarasteh/os-lab/pull/155) | — | plain schedules section on `/cleanup/` after CLN-16 lands | scan-only store, runner and typed API first | none |
| CLN-19 | in progress (this PR) | [#156](https://github.com/keyvanarasteh/os-lab/pull/156) | — | — | headless CLI after engine API | none |
| CLN-20 | in progress (this PR) | [#157](https://github.com/keyvanarasteh/os-lab/pull/157) | — | plain privileged preview and disk-access guidance on `/cleanup/` after CLN-16 lands | typed engine and API first | none |
| CLN-21 | pending | — | — | — | — | none |
| CLN-22 | merged | [#137](https://github.com/keyvanarasteh/os-lab/pull/137) | a3133e76 | — | done ahead of order by Claude Code at the maintainer's request; engine and dashboard untouched | none |
| CLN-23 | pending | — | — | Disk Explorer page | console side only | none |
| CLN-24 | pending | — | — | — | — | none |
| CLN-25 | pending | — | — | — | — | none |
| CLN-26 | pending | — | — | — | — | none |
| CLN-27 | pending | — | — | — | — | none |
| CLN-28 | pending | — | — | `/cleanup/` volumes card | console side only | none |
| CLN-29 | pending | — | — | — | — | none |

No CLN task has a student reservation or open student PR: `grep -rl CLN-
reservations/` matches only `README.md` and `_schema.json`, and no open PR title or
branch names a CLN id.

## Dashboard handoff — CLN-13

### Console endpoints (live on this branch)

`POST /api/cleanup/plan` — header `X-OSLab: 1`, JSON body:

```json
{ "entryIds": ["system.user-caches"], "workers": 4, "mode": "trash" }
```

`entryIds` is **required** (catalog ids from `GET /api/cleanup/catalog`); `workers`
is `1`–`16`; `mode` is `trash` (default) or `delete`. A path, a command, any other
key, an empty/duplicate/unknown id list, a bad worker count and any other mode are
`400`. The answer is `202` with a job whose `kind` is `plan`:

```json
{
  "id": "9e1c0a7b3d21", "kind": "plan", "state": "running",
  "request": { "entryIds": ["system.user-caches"], "workers": 4, "mode": "trash" },
  "progress": { "phase": "planning", "pathsDone": 0, "pathsTotal": 1,
                "bytesSeen": 0, "filesSeen": 0, "currentPath": "" },
  "result": null, "error": null,
  "startedAt": 0, "finishedAt": null
}
```

Poll `GET /api/cleanup/jobs/<id>`. When `state` is `done`, `result` is the plan:

```json
{
  "planId": "8c1f2a9b0d44", "createdAt": 0, "expiresAt": 0, "ttlSeconds": 600,
  "mode": "trash", "platform": "macos",
  "items": [
    {
      "entryId": "system.user-caches", "entryName": "User caches", "risk": "low",
      "template": "~/Library/Caches", "path": "/Users/me/Library/Caches",
      "status": "ready", "code": "", "reason": "",
      "privileged": false, "mode": "trash",
      "sizeBytes": 40960, "sizeOnDiskBytes": 40960, "files": 3, "folders": 4
    }
  ],
  "totals": { "items": 1, "ready": 1, "skipped": 0, "bytes": 40960,
              "files": 3, "folders": 4 }
}
```

`POST /api/cleanup/clean` — header `X-OSLab: 1`, body `{ "planId": "8c1f2a9b0d44" }`,
no other key → `202` job `kind: "clean"`. Errors are answered before a job starts:
`404` unknown plan, `410` expired, `409` already used. A plan is **single-use** and
expires after ten minutes **or** when any item's fingerprint changed; the change is
re-checked inside the job, which ends `failed` with that message and removes nothing.

Clean progress: `phase` `queued`/`cleaning`/`done`/`cancelled`, `itemsDone`,
`itemsTotal`, `bytesRemoved`, `currentPath`. When finished:

```json
{
  "planId": "8c1f2a9b0d44", "mode": "trash", "platform": "macos",
  "startedAt": 0, "finishedAt": 0, "durationMs": 0, "cancelled": false,
  "results": [
    {
      "entryId": "system.user-caches", "entryName": "User caches",
      "template": "~/Library/Caches", "path": "/Users/me/Library/Caches",
      "mode": "trash", "status": "trashed",
      "code": "", "reason": "", "error": null,
      "bytes": 40960, "files": 3, "folders": 4,
      "trashPath": "/Users/me/.Trash/Caches"
    }
  ],
  "progress": { "phase": "done", "itemsDone": 1, "itemsTotal": 1,
                "bytesRemoved": 40960, "currentPath": "" },
  "totals": { "items": 1, "trashed": 1, "deleted": 0,
              "skipped": 0, "failed": 0, "bytes": 40960,
              "files": 3, "folders": 4 }
}
```

Statuses are exactly `trashed`, `deleted`, `skipped` and `failed`. A skipped item
has a stable `code` plus an English `reason`: `no-path`, `privileged`,
`app-running`, `foreign-owner`, `protected`, `system-root`, `outside-root`,
`missing`, `unreadable`, `not-cleanable`, `duplicate`, `nested`, `trash-nesting`,
`cancelled`. A failed item has an `error`; a failed Trash is **failed, not
deleted** — the original is still there. `bytes`/`files`/`folders` are this run's
measurement and only counted after the item is really gone; a failed/skipped item
counts 0. `trashPath` is `null` for `delete`, skips and failures. **Do not sum the
plan's estimate**; show `result.totals.bytes` and say “moved to Trash” (or “deleted”
only in delete mode).

`mode: "delete"` is permanent and only happens when the plan names it; never make it
the default, never fall back to it, and warn in the confirm step. There is no audit
history yet (CLN-15) and no undo beyond the user's own Trash. Privileged items are
planned as skipped and must offer no clean action.

### What the page does with it

CLN-16 owns the page. The scan section stays; add a plan/confirm section with:

| State | What the page shows |
|---|---|
| idle | selected catalog entries, **Build plan**; Trash is the default and delete is a deliberate second choice with a warning |
| planning | `pathsDone / pathsTotal`, `bytesSeen`, `filesSeen`, `currentPath`; **Cancel** |
| plan ready | every item with `status`, `code`/`reason`, size, files, folders; **N items ready**, byte total; **Confirm clean** disabled when `totals.ready` is 0; “Expires in 10 minutes” |
| expired / stale / used | that sentence verbatim plus **Build a new plan**; never retry the same `planId` |
| cleaning | `itemsDone / itemsTotal`, `bytesRemoved`, `currentPath`; **Cancel** |
| done | one row per item with its status, reason/error and (for Trash) `trashPath`; the counted `totals.bytes`; say space was **moved to Trash**, not “freed” |
| cancelled | “Clean cancelled” and the partial rows; remaining items are skipped with reason `cancelled`; a new plan is needed |
| failed | `error`; for a stale plan explicitly “nothing was removed”; if some rows exist, show them |
| public Pages | no plan/clean action: “The Cleanup Lab runs in the local app.” |

Keep the confirm action behind an explicit dialog that names the item count, the
byte total and the mode (Trash default / delete permanent). Never pre-select a
`credentials`/`privacy` entry, and never expose a free-form path or command field.

### Visible strings (English; these are the i18n keys)

`Build plan` · `Confirm clean` · `Trash (default)` · `Delete permanently` ·
`Planning…` · `Plan ready` · `Nothing to clean` · `items ready` · `Cleaning…` ·
`Clean cancelled` · `Clean failed` · `Moved to Trash` · `Deleted permanently` ·
`Skipped` · `Failed` · `Moved to Trash, not freed` ·
`This plan expired because an item changed. Build a new plan.` ·
`This plan was already run. Build a new plan.` ·
`This plan expired. Build a new plan.` ·
`The item could not be moved to Trash and was left in place.` ·
`Deleting permanently cannot be undone.` ·
`The cleanup engine could not start the job.` ·
`No answer from the cleanup engine. Start os-lab from a terminal, then try again.` ·
`The Cleanup Lab runs in the local app.`

Dynamic strings (`entryName`, `template`, `path`, `reason`, `error`, `trashPath`)
come from the engine/API in English, like every other lab payload; they are not
translated client-side.

## Dashboard handoff — CLN-03

### Console endpoints (live on this branch)

`POST /api/cleanup/scan` — header `X-OSLab: 1`, JSON body:

```json
{ "entryIds": ["system.user-caches"], "workers": 4 }
```

Both keys are optional; `entryIds` is a list of catalog ids (`GET
/api/cleanup/catalog`), `workers` is `1`–`16`. A path, a command, any other key, a
duplicate or unknown id, an empty id list and a bad worker count are `400`. The
answer is `202` with the same job object as below. The scan is read-only and runs
on a console thread; there is no command string and no path list from the page.

`GET /api/cleanup/jobs/<id>` → `200` job, `404` unknown id. `GET
/api/cleanup/jobs` → `{ "jobs": [ … ] }`, newest first, at most the recent 20
finished jobs plus any running one. `POST /api/cleanup/jobs/<id>/cancel` — header
`X-OSLab: 1`, empty object body → `200` job; the cancel flag is set immediately and
the worker finishes with `state: "cancelled"` after its current listing. A
non-empty body is `400`, an unknown id `404`.

```json
{
  "id": "2b8cc9ba670f",
  "kind": "scan",
  "state": "running",
  "request": { "entryIds": ["system.user-caches"], "workers": 4 },
  "progress": {
    "phase": "scanning",
    "pathsDone": 1, "pathsTotal": 3,
    "bytesSeen": 40960, "filesSeen": 1,
    "currentPath": "/Users/me/Library/Logs"
  },
  "result": null,
  "error": null,
  "startedAt": 1794536063.8,
  "finishedAt": null
}
```

`state` is `running`, `done`, `cancelled` or `failed`; `failed` carries a string
`error` and no result. `progress.phase` is `queued`, `scanning`, `done` or
`cancelled`; `pathsTotal` is the number of top-level paths that can be measured.
When finished, `result` is:

```json
{
  "startedAt": 0, "finishedAt": 0, "durationMs": 0, "platform": "macos",
  "cancelled": false,
  "entries": [
    {
      "id": "system.user-caches", "name": "User caches", "family": "system",
      "category": "system", "risk": "low", "hint": "…", "impact": "…",
      "defaultSelected": true, "needsPrivilege": false,
      "owningProcesses": [], "detector": "paths",
      "paths": [
        {
          "template": "~/Library/Caches", "path": "/Users/me/Library/Caches",
          "reason": "", "missing": false, "symlink": false,
          "sizeBytes": 40960, "sizeOnDiskBytes": 40960,
          "files": 1, "folders": 2, "unreadable": [], "error": null,
          "measured": true
        }
      ],
      "sizeBytes": 40960, "sizeOnDiskBytes": 40960,
      "files": 1, "folders": 2, "unreadable": [], "missing": false
    }
  ],
  "progress": { "phase": "done", "pathsDone": 3, "pathsTotal": 3, "…": "…" },
  "totals": {
    "sizeBytes": 0, "sizeOnDiskBytes": 0, "files": 0, "folders": 0,
    "paths": 0, "unreadable": 0, "entries": 0
  }
}
```

Honest fields: `sizeOnDiskBytes` is `null` where the OS does not expose a block
count; a path with `path: null` has a `reason`; `missing`/`symlink` paths carry a
`reason` and zero bytes; `unreadable` lists paths under this path that could not be
read; `measured: false` means the walk was cancelled (partial counters are still
real). Totals exclude unmeasured and unreadable bytes — never invent them. Jobs are
in-process only, so a console restart loses them; do not persist or promise them.

Errors on the namespace: `400` bad query/key/id/worker, `404` unknown path or job,
`403` missing `X-OSLab` on POST, `500` malformed catalog, `501` engine missing.

### What the page does with it

CLN-16 owns the page. A scan section offers exactly one action, **Start scan**
(disabled while a job is running), then **Cancel scan**; no clean/delete action
until CLN-13. Poll `GET /api/cleanup/jobs/<id>` every ~500–750 ms while `running`;
stop polling on `done`, `cancelled` or `failed`.

| State | What the page shows |
|---|---|
| idle | Start scan, the catalog's entry count, and a sentence that scanning is read-only. Never say space was freed. |
| running | progress bar from `pathsDone / pathsTotal`, `bytesSeen`/`filesSeen` and `currentPath`; Cancel scan |
| done | totals plus one row per entry and per path: apparent size, on-disk size when not null, files, folders; risk and `needsPrivilege` from the entry |
| done with zero bytes | the entry stays visible with its `reason` (`missing`, symlink, nothing to measure) — never hidden |
| cancelled | a neutral “Scan cancelled” badge and the partial rows; offer Start scan again |
| failed | `error` next to the action; no results card |
| request failed | the existing offline sentence; do not poll |
| public Pages | no polling, no scan action: “The Cleanup Lab runs in the local app.” |

`unreadable` is a list, shown under the path (“N paths could not be read”) with the
paths in a collapsed detail; it is not an error. A privileged entry
(`needsPrivilege`) can be scanned but must not offer cleaning.

### Visible strings (English; these are the i18n keys)

`Start scan` · `Cancel scan` · `Scanning…` · `Scan cancelled` · `Scan failed` ·
`Scan results` · `Reclaimable space` · `Apparent size` · `On disk` · `Files` ·
`Folders` · `Unreadable paths` · `Missing` · `Symlink not followed` ·
`Nothing to measure` · `Scanning is read-only. Nothing is removed.` ·
`Scanning runs on this computer. Cleaning arrives in a later task.` ·
`The cleanup engine could not start the scan.` ·
`No answer from the cleanup engine. Start os-lab from a terminal, then try again.` ·
`The Cleanup Lab runs in the local app.`

Dynamic strings (`name`, `hint`, `impact`, `risk`, `reason`, `error`, `currentPath`)
come from the engine/API in English, like every other lab payload; they are not
translated client-side.

## Dashboard handoff — CLN-12

### Console endpoint

None. The guard is engine-internal: CLN-13's plan and CLN-15's run will return a
`reason` and `reasonCode` per item from `safety.check_target()`.

### What the page shows per item

`Ok` items carry the resolved path. A refused item must show its translated code and
keep the entry visible — never silently drop it. Codes:

| Code | Meaning | English fallback |
|---|---|---|
| `empty` | empty path in a request | A filesystem path cannot be empty. |
| `nul` | NUL byte in a path | A filesystem path cannot contain NUL bytes. |
| `relative` | not absolute and not `~/…` | Filesystem paths must be absolute: `<path>` |
| `protected` | `/`, the home folder or a drive root | Refusing to operate on protected root `<path>`. |
| `system-root` | `/System`, `/usr`, `C:\Windows` … | Refusing to operate on system directory `<path>`. |
| `missing` | vanished since the scan | Path no longer exists. |
| `no-path` | entry has no path for this OS | This entry has no path for this system. |
| `outside-root` | symlink resolved outside the entry's root | Path resolves outside its catalog root (symlink escape). |
| `foreign-owner` | owned by another account | Owned by another user account; a privileged plan is required. |
| `app-running` | an owning app is running | The owning application is running: `<apps>`. |

Also refused, for CLN-23 and CLN-27: `missing` / `not-a-folder` / `unreadable` when
choosing a scan folder, `outside-roots` for a target outside every allowed root,
`same-path` / `nested` / `destination-outside` for a copy.

### Suggested UI strings

`Skipped` · `Could not be cleaned` · `Some items were skipped` — the reasons themselves
come from the payload. A privileged entry shows `Needs administrator rights` and stays
unselected.

## Dashboard handoff — CLN-02

### Console endpoint (already live)

`GET /api/cleanup/catalog` → `200 application/json`

```json
{
  "platform": "macos",
  "entries": [
    {
      "id": "system.user-caches",
      "name": "User caches",
      "family": "system",
      "category": "system",
      "risk": "low",
      "hint": "Application caches for the current user. They speed up loading.",
      "impact": "Apps rebuild these; the first launch after cleaning is slower.",
      "defaultSelected": true,
      "needsPrivilege": false,
      "owningProcesses": [],
      "detector": "paths",
      "note": "",
      "paths": [
        { "template": "~/Library/Caches", "path": "/Users/Q/Library/Caches", "reason": "" }
      ]
    }
  ]
}
```

`risk` is `low` / `medium` / `high` / `credentials` / `privacy`; the last three are
never pre-selected. `paths[].path` is `null` when the template could not be resolved
(e.g. an unset `XDG_CACHE_HOME`), and `paths[].reason` then says why. Errors: `400`
unexpected or duplicate query parameters, `404` unknown path, `500` malformed catalog
(the message names the file). No POST, no jobs.

### UI

CLN-02 adds no page. When a later page lists detectors (CLN-16), it reads this
endpoint; a path with `path: null` must show its `reason`, not be hidden. Suggested
strings, if such a list is built: `Detector catalog` · `No detector catalog` ·
`Could not resolve this path`. Everything else comes from `name`, `hint`, `impact`
and `risk` in the payload.

## Dashboard handoff — CLN-01

### Console endpoint (already live)

`GET /api/cleanup/status` → `200 application/json`

```json
{
  "engine": { "name": "cleanup-lab", "version": "0.1.0", "python": "3.15.0", "mode": "stdlib" },
  "state": "ready",
  "platform": { "id": "macos", "label": "macOS", "supported": true },
  "home": "/Users/Q",
  "stateDir": "/Users/Q/Library/Application Support/os-lab/cleanup",
  "requirements": [
    { "id": "platform", "label": "Supported operating system", "found": true, "required": true, "hint": "Cleanup Lab runs on macOS, Linux and Windows.", "detail": "macOS" },
    { "id": "python", "label": "Python 3.11 or newer", "found": true, "required": true, "hint": "labctl cleanup prefers the checkout's .venv; install Python 3.11 or newer.", "detail": "3.15.0" },
    { "id": "home", "label": "Home folder readable", "found": true, "required": true, "hint": "The scan targets live under this folder; make it readable by your user.", "detail": "/Users/Q" },
    { "id": "trash", "label": "Trash available", "found": true, "required": true, "hint": "Cleaning moves items to the Trash; a platform without one cannot clean.", "detail": "/Users/Q/.Trash" },
    { "id": "state", "label": "Private state folder writable", "found": true, "required": true, "hint": "The audit history and the learned profile live here. Set OSLAB_CLEANUP_STATE to a writable folder.", "detail": "/Users/Q/Library/Application Support/os-lab/cleanup" }
  ],
  "capabilities": [
    { "id": "detectors", "label": "Detector catalog", "found": false, "detail": "No detector catalog yet" },
    { "id": "native-scan", "label": "Native scan backend", "found": false, "detail": "Reference crate present; not wired into the app yet" },
    { "id": "containers", "label": "Container engine", "found": false, "detail": "No docker or podman on PATH" },
    { "id": "package-managers", "label": "Package managers", "found": true, "detail": "pip3 at /usr/bin/pip3" },
    { "id": "simulators", "label": "Simulator tools", "found": true, "detail": "xcrun at /usr/bin/xcrun" }
  ],
  "reasons": [],
  "checkedAt": 1794530446.947456
}
```

`state` is `ready` / `needs-setup` / `unavailable`. `reasons` lists the `hint` of
every required requirement that failed. Errors: `404` unknown `/api/cleanup/...`
path, `400` unexpected or duplicate query parameters, `501` when
`console/cleanup_api.py` or `cleanup-lab/engine` is missing. No POST, no jobs, no
progress or cancel in this task.

### UI states

| State | What the page shows |
|---|---|
| loading | skeleton rows, headline "Checking this computer…" |
| ready | success badge, "Ready on this computer", every requirement row ticked |
| needs-setup | warning badge, "Needs setup on this computer", the failed row's `hint` under it, plus the `reasons` list |
| unavailable | neutral badge, "Not available on this computer", unsupported-platform sentence |
| request failed | empty state with "No answer from the cleanup engine. Start os-lab from a terminal, then press Re-check." |
| public Pages | no polling: "The Cleanup Lab runs in the local app." |

Actions: exactly one, Re-check (re-fetch). No scan/clean button until CLN-03/13.

### Files to add (dashboard layer)

* `dashboard/src/pages/cleanup/index.astro` — `<Base title="Cleanup Lab" …>` +
  `<CleanupPage client:only="react" />`.
* `dashboard/src/views/cleanup/cleanup-page.tsx` — `AppShell activeId="cleanup"`,
  `TopBar`, `PageHead`, two `Section`s (Readiness, Capabilities), a collapsed
  "Technical details" block with engine version, Python, home and state paths.
* `dashboard/src/lib/api.ts` — `CleanupRequirement`, `CleanupCapability`,
  `CleanupStatus` types and `cleanupStatus: () => call<CleanupStatus>("/api/cleanup/status")`.
* `dashboard/src/shell/app-shell.tsx` — `sectionHref("cleanup")` → `/cleanup/`,
  a "Cleanup Lab" item in the **OS Lab** group (local mode only), Spotlight meta.
* `dashboard/src/pages/[locale]/[...rest].astro` — add `cleanup` to `routes` and
  render the page for `rest === "cleanup"`, otherwise language switching 404s.

### Visible strings (English; these are the i18n keys)

`Cleanup Lab` · `Find reclaimable disk space, inspect every item, and clean only what you confirm.` ·
`Checking this computer…` · `Ready on this computer` · `Needs setup on this computer` ·
`Not available on this computer` · `Every required check answered. Nothing has been scanned or removed.` ·
`The engine is installed but a required check below did not answer.` ·
`This operating system is not supported by the Cleanup Lab engine.` · `Asking the local cleanup engine…` ·
`Re-check` · `Readiness` · `Checks the local engine answers before it scans anything. Nothing on this page changes your system.` ·
`Capabilities` · `Optional tools and detectors this build can use. A missing one never blocks a scan.` ·
`Technical details` · `Engine version` · `Python` · `Home folder` · `Private state` ·
`No answer from the cleanup engine. Start os-lab from a terminal, then press Re-check.` ·
`This build reports readiness only. Scanning, planning and cleaning arrive in later tasks.` ·
`The Cleanup Lab runs in the local app.` ·
`The public site describes the lab. Scanning and cleaning need the engine on your own computer.`

Dynamic strings from the API (`label`, `detail`, `hint`, `reasons`) are English
server-side, like every other lab label; they are not translated client-side.

## Session log

**2026-11-13 — CLN-01.** Read `AGENTS.md`, `CONTRIBUTING.md` §2b,
`docs/UX_READINESS.md`, `lat.md/`, `cleanup-lab/README.md`,
`cleanup-lab/reference/README.md` and the task file. No CLN reservations or open
CLN PRs. Built the `cleanup_lab` package (readiness, paths, CLI), the console
endpoint, the `labctl cleanup` dispatch, the unit suite, `lat.md/cleanup-lab.md`,
the README status/CLI section and the engine stage in `scripts/run-tests.sh`.

Write guard: `dashboard/src/lib/api.ts` and all seven
`dashboard/src/i18n/generated/*.json` were refused (`token`, then `password`
hits) because the guard scans the whole file content and this build exposes no
path allowlist. The maintainer asked for an 8-path allowlist; it did not take
effect in the Run, and the cause was reported. Decision on 2026-11-13: split the
work by layer (engine here, dashboard in a later pass), never work around the
guard, record any further refusal here. A draft `dashboard/src/views/cleanup/`
page written before that decision was removed again; `git status` shows no change
under `dashboard/`.

Baseline: `./scripts/run-tests.sh` reports 8 passed, 1 failed, 1 skipped. The
failure is the android suite, already failing on a clean `master` worktree on this
arm64 Mac (5 failed + 10 errors there, 4 failed + 10 errors on this branch, same
ids, no new failure); `cargo` is not on `PATH`, so the qrust-scan stage is skipped
and this PR changes no Rust.

**2026-11-13 — CLN-01 review round.** Sourcery opened 12 threads; the branch merge
is blocked until they are resolved (`required_conversation_resolution`). Fixed 11:
Python 3.11 is now accepted (a three-element `(3, 11, 0)` compared against
`(3, 11)` was false, so the probe compares the first two components); Trash
readiness checks the target (existing folder writable, otherwise its nearest
existing ancestor, Recycle Bin on Windows); the state folder must be writable
**and** not group/other accessible (`is_private_dir`); relative `XDG_*` values are
ignored instead of resolving against the working directory; `nearest_existing` uses
`lstat`, so a dangling symlink or a permission-blocked component is reported
instead of climbing past it; absolute-path checks use the target platform's path
module; CLI output escapes control characters; `doctor` prints every hint and no
longer claims the engine can scan; README and the knowledge graph say the
`/cleanup/` page is not built yet; the doctor test asserts the hint text. One thread
was declined: absolute home and state paths in the status response — the console
binds `127.0.0.1` only, rejects a foreign Host header, and any local process can
read the home path without it, while the page needs the paths to be useful. Replied
to and resolved every thread.

**2026-11-13 — CLN-02.** Catalog format, loader, seeds and parity. Added
`cleanup-lab/catalog/schema.json` (draft 2020-12), `catalog/system.json` with three
seed entries (user caches, user logs, Trash), `cleanup_lab/catalog.py` (validation,
per-OS template expansion, unresolved paths reported with a reason, pre-selected
risk refused), `cleanup-lab/PARITY.md` mapping every Qleaner detector id read from
`detectors.rs`, `catalog/README.md`, `labctl cleanup catalog` and
`GET /api/cleanup/catalog`. No CLN reservation or open CLN PR existed for this task.

**2026-11-13 — CLN-12.** Safety guard. Added `cleanup_lab/safety.py`: the reference
path policy (canonical/resolved paths, protected and system roots, component
containment, `validate_scan_root`, `validate_target`, `validate_copy`) plus ownership
and a process-table lock matched on whole names from each entry's `owningProcesses`.
`check_target()` returns a verdict with a stable code and an English reason;
`assert_safe_target()` raises both. 22 new tests (69 total), including a check that no
shipped catalog entry points at a protected root. The old `contains("..")` and
`contains("system")` checks are gone; `a..b` is a valid path and `~/.cache/systemd`
is not blocked by a substring.

**2026-11-13 — CLN-03.** Scan job. Added `cleanup_lab/scan.py`: a read-only
`lstat` walk of the catalog's resolved paths, one worker per top-level path (1–16),
throttled progress, hard-link de-duplication by `(device, inode)` across workers,
symlinks never followed, sockets/FIFOs/devices not measured, unreadable paths
reported, and cancel returning the real partial counters. The console exposes
`POST /api/cleanup/scan`, `GET /api/cleanup/jobs/<id>`, `GET /api/cleanup/jobs`
and `POST /api/cleanup/jobs/<id>/cancel`, accepting catalog ids and `workers` only;
a non-empty cancel body and every unknown key/id are refused. Fixed the cancel route
(`/api/cleanup/jobs/<id>/cancel` was parsed as 4 parts) and a web-layer crash where
cancel returned a dict but the route assumed a job object. Added engine tests
(88 total, OK) and `android-lab/lab/tests/test_cleanup_console.py` (5 passed).
`PARITY.md`, `README.md`, `lat.md/cleanup-lab.md` and `VERIFY.md` updated. No CLN-03
reservation or open student PR existed. A completed `./scripts/run-tests.sh` run was
8 passed / 2 failed: the six android failures reproduce on a clean `master`
worktree (no new failure), and the one `lat check` failure (section summary too
long) was fixed and re-checked green. The full suite was not re-run after that
documentation-only fix, per the maintainer's instruction.

**2026-11-13 — CLN-13.** Plan → confirm → clean. Added `cleanup_lab/clean.py`: a
read-only plan build (safety guard, one `lstat` walk, per-item fingerprint), a
single-use ten-minute plan, and an executor that verifies fingerprints first and
then trashes (default) or deletes (explicit) each item. A failed Trash is a failed
item, never a permanent-delete fallback; transient errors retry; cross-volume moves
are copied, verified and only then removed, with the verified copy kept when the
source cannot be removed. Per-item `trashed`/`deleted`/`skipped`/`failed` results
carry reasons, and bytes are counted only when the item is gone from its original
path. The console exposes `POST /api/cleanup/plan`, `POST /api/cleanup/clean
{planId}` and poll/cancel through the shared job store; stale/expired/used plans
answer `409`/`410` and remove nothing. Fixed `_validate_entry_ids` calling
`catalog.load()` without the repo root. Added 24 engine tests (112 total, OK) and
five console tests (10 total, passed) including the real browser route. `README.md`,
`PARITY.md`, `VERIFY.md`, `lat.md/cleanup-lab.md` and this handoff updated. No
CLN-13 reservation or open student PR existed. A full `./scripts/run-tests.sh` run
was 7 passed / 1 failed / 1 skipped: the android stage shows the same six
pre-existing ids as `master` (158 passed), and the dashboard stage skipped because
this worktree has no `node_modules`. Dashboard typecheck/build/e2e were not run —
no dashboard file changed.
