# Cleanup Lab

A disk-cleanup lab for os-lab: scan a host for reclaimable space (caches, build
artifacts, app leftovers, containers, VM images) and clean it through previewed,
confirmed, audited actions.

The detections, detection signatures and clean techniques come from
[Qleaner](https://github.com/keyvanarasteh/Qleaner) (Rust + Tauri v2). **Only the
behaviour is ported, not the code or the look.** Qleaner has known bugs (below) and
its own visual style; Cleanup Lab pages use the os-lab dashboard shell and follow
[`docs/UX_READINESS.md`](../docs/UX_READINESS.md).

Status: **Engine skeleton (CLN-01), detector catalog (CLN-02), safety guard
(CLN-12), the read-only scan job (CLN-03) and the plan → clean flow (CLN-13) are
in place; the rest is roadmap.** The engine package, the readiness probe (`labctl
cleanup status|doctor`, `GET /api/cleanup/status`) and the catalog (`GET
/api/cleanup/catalog`) exist; `POST /api/cleanup/scan` runs a catalog scan as a
console job with progress and cancel, `POST /api/cleanup/plan` previews a clean,
and `POST /api/cleanup/clean {planId}` runs that confirmed plan. The `/cleanup/`
page is **not built yet**: the dashboard layer lands separately, and
[`STATUS.md`](STATUS.md) carries the endpoint contract, page states and strings it
must use. Audit history is stored privately with a per-install HMAC key (CLN-15). The work
is split into tasks `CLN-01` … `CLN-29` on the dashboard **Contribute → Roadmap &
TODOs** tab (filter: Open Source OS, label "Cleanup Lab"). Reserve a task before you
start, as with every os-lab task
([`reservations/README.md`](../reservations/README.md)).

Tasks `CLN-21` … `CLN-29` also have **working reference code** in
[`reference/`](reference/README.md): the `qrust-scan` Rust crate (parallel
allocated-size scan, size tree, hotspots, glob seek, progress, cancel) and the
`cleanup_ref` Python modules (path policy, marker-verified artifact signatures,
tool-reported cache locations, relocation planner, learning profile). That code
was contributed by the maintainer from private projects, with known bugs fixed,
and is covered by tests. It is read-only and not yet wired into the engine.

## Engine and CLI

`cleanup-lab/engine/` is a standard-library Python package, `cleanup_lab`. The
console imports it from `console/cleanup_api.py`; `labctl` runs its CLI.

```bash
./labctl cleanup status          # readiness of this computer, exit 0 ready / 1 problem
./labctl cleanup doctor          # every check, path and hint
./labctl cleanup catalog         # detector catalog for this OS, with resolved paths
./labctl cleanup status --json   # the same probe as JSON (what /api/cleanup/status returns)
cd cleanup-lab/engine && python3 -m unittest discover -s tests -p 'test_*.py'
```

The probe never writes: it reports the operating system, the interpreter, the home
folder, the Trash target and the private state folder, plus optional capabilities
(the detector catalog, the native scan backend, the tools on `PATH`). State lives
in `~/Library/Application Support/os-lab/cleanup` on macOS,
`$XDG_STATE_HOME/os-lab/cleanup` on Linux and `%LOCALAPPDATA%\os-lab\cleanup` on
Windows; `OSLAB_CLEANUP_STATE` overrides it.

## Detector catalog

`cleanup-lab/catalog/*.json` holds every target as data: id, name, category, risk,
hint, impact, default selection, owning processes, privilege flag and per-OS paths.
[`schema.json`](catalog/schema.json) documents the format, `catalog.py` validates and
expands it, and [`PARITY.md`](PARITY.md) records which Qleaner detector each entry
replaces. `./labctl cleanup catalog` prints the entries for this computer with every
path it could resolve — and the reason for each it could not.

## Scan job

`cleanup_lab/scan.py` measures the resolved catalog paths and nothing else. Every
size comes from `lstat`: symlinks are never followed or recursed into, sockets and
device nodes are not measured, and a hard link is counted once per scan by
`(device, inode)`. Apparent size and on-disk size are reported separately (on-disk
is `null` where the OS exposes no block count). A path that cannot be read is listed
in `unreadable`; it never fails the scan.

`POST /api/cleanup/scan` starts the job with a request naming only catalog
`entryIds` and an optional `workers` count (1–16) — never a path list. `GET
/api/cleanup/jobs/<id>` returns its progress and result, `GET /api/cleanup/jobs`
lists the recent jobs, and `POST /api/cleanup/jobs/<id>/cancel` sets the cancel
flag. A cancelled scan returns its partial counters with `"cancelled": true` — never
an error and never invented bytes. Jobs live in the console process, like the other
lab jobs.

## Plan → clean

`cleanup_lab/clean.py` turns catalog entries into a confirmable plan and runs only
that plan. Building is read-only: every path goes through the safety guard, then
one `lstat` walk records its size, files, folders and a fingerprint (symlinks are
counted, never followed). `POST /api/cleanup/plan` requires catalog `entryIds`
(plus optional `workers` and `mode`) — the page never sends a path list. The plan
lists every item as `ready` or `skipped` with a stable code and reason, defaults to
`trash`, and expires after ten minutes or as soon as an item changes.

`POST /api/cleanup/clean {planId}` verifies the fingerprints again, then runs the
plan once (`used` afterwards). Trash is the default and the only automatic choice:
a failed move is a failed item, never a silent permanent delete; `mode: "delete"`
must be explicit. A cross-volume move is copied into the Trash, compared against a
fresh walk of the original, and only then removed from the source — if removing the
source fails, the verified copy stays. Transient errors are retried, and every item
reports `trashed`, `deleted`, `skipped` (code + reason) or `failed` (error). Bytes
are credited only after the item is really gone from its original path, using this
run's measurement — never the plan estimate. Privileged items and items whose app
is running stay skipped.

## Safety guard

`cleanup_lab/safety.py` is the only place a destructive call is allowed to pass. It
ports the reference path policy (resolved containment, component comparison, no purge
of a protected root) and adds the two checks the page needs next to each item:
ownership (`lstat` owner against the current user) and the running-app lock, matched
against the entry's `owningProcesses` by whole name — not a substring, and not only
Chrome and Firefox. `check_target()` returns a verdict with a stable `code` plus an
English `reason`; `assert_safe_target()` raises both as `SafetyError`. Refusal codes:
`empty`, `nul`, `relative`, `protected`, `system-root`, `missing`, `no-path`,
`outside-root`, `foreign-owner`, `app-running`.

## Architecture contract

| Layer | Where | Rule |
|---|---|---|
| Engine | `cleanup-lab/engine/` | Python standard library first. Pure functions for detection; one module (`safety.py`) guards every destructive call. |
| Catalog | `cleanup-lab/catalog/*.json` | All target paths live here as data, per OS. No hardcoded paths in code. |
| Console API | `console/` (`/api/cleanup/...`) | Typed, validated actions. Never accept a command string or a free-form path list from the page. Long work runs as console jobs with preview, progress and cancel. |
| Dashboard | `dashboard/src/pages/cleanup/`, `dashboard/src/views/cleanup/` | Existing shell and components, typed `api.ts` client, all seven locale catalogs. |
| CLI | `labctl cleanup …` | Same engine, `--json` output, exit codes `0` clean / `1` problem / `2` usage. |
| Desktop | `app/src-tauri/` | Only when a native feature is required; no `unsafe`. |

### Safety rules (apply to every task)

1. **Scan is read-only.** Sizes use `lstat`; symlinks are never followed.
2. **Clean = plan → confirm → run.** The plan lists every item, its size, the mode
   (Trash / delete / shred) and any privilege needed. Running without a confirmed,
   unexpired plan is impossible.
3. **Trash by default.** If moving to Trash fails, the item fails. Never fall back
   to permanent deletion on your own.
4. **Resolved paths only.** Every target is resolved and must stay inside an allowed
   root; ownership is checked; items whose owning app is running are skipped with a reason.
5. **Credentials are not cache.** CLI auth stores (gh, aws, gcloud, azure, k9s…) and
   browser history are a separate risk class and are never pre-selected.
6. **Honest results.** Count only bytes actually removed; report every skipped and
   failed item with its reason; write every run to the audit history.
7. **No secrets in code.** Keys (e.g. the audit HMAC key) are generated per install
   in private state.
8. Tests never touch real user files: use generated temp trees and fake binaries.

## What to port from Qleaner

Source: `src-tauri/src/cleaner/` in Qleaner. `CLN-02` adds `PARITY.md`, mapping
every Qleaner detector id to a catalog id, or to a written reason for dropping it.

| Family | Qleaner source | Task |
|---|---|---|
| User caches, logs, temp, crash reports, font caches, Spotlight indexes, Trash size | `get_cache_locations`, `detect_temp_data`, `detect_crash_reports`, `detect_font_caches`, `detect_spotlight_indexes`, `detect_trash_size` | CLN-04 |
| Browser caches and privacy data (Chrome, Edge, Brave, Opera, Vivaldi, Firefox, Safari; Chrome history and extension telemetry) | `detect_browser_caches`, `get_cache_locations` | CLN-05 |
| ~36 developer/CLI caches (Gradle, Maven, Ivy, Coursier, Poetry, pip, Composer, Go, RubyGems, Ansible, Terraform, Pulumi, Helm, kubectl, Minikube, pyenv/nvm/rbenv, rustup, Bun, Deno, wasm-pack, sccache, ccache, Jest, ESLint, Prettier, Turbo, Nx…) plus npm/yarn/pnpm/cargo/Discord/Slack | `detect_cli_tool_data`, `get_cache_locations` | CLN-06 |
| Deep `node_modules` / Rust `target` sweep, Xcode DerivedData, iOS/watchOS simulators | `find_deep_evictions`, `detect_xcode_simulators` | CLN-07 |
| Docker build cache, dangling images/volumes, stopped containers; VirtualBox/VMware/Parallels/UTM images | `get_cache_locations` (Containers), `detect_virtual_machines` | CLN-08 |
| macOS leftover signatures: Info.plist bundle ids → orphan Containers, Group Containers, Preferences, Application Support, LaunchAgents, Caches, Libraries; hidden apps; large app data | `parse_plist_bundle_id`, `infer_app_name`, `get_installed_bundle_ids`, `detect_*_orphans`, `detect_hidden_apps`, `detect_large_app_data` | CLN-09 |
| Linux / Windows leftovers (missing in Qleaner) | — | CLN-10 |
| Homebrew leaves, global pip packages, gems | `detect_homebrew_orphans`, `detect_pip_global_packages`, `detect_gem_packages` | CLN-11 |
| Process lock, traversal and restricted-root guards, ownership check | `clean_items` guards, `is_owned_by_current_user` | CLN-12 |
| Trash / delete with retry, streaming progress | `clean_items`, `clean_leftovers`, `retry_remove` | CLN-13 |
| Secure shred (zeros / ones / random, rename, unlink) | `secure_shred_file`, `get_all_files` | CLN-14 |
| HMAC-signed audit history | `db.rs` | CLN-15 |
| Ignore rules, schedules, headless CLI, disk-access check | `rules`, `schedules` pages, `cli.rs`, `check_system_disk_access` | CLN-17 … CLN-20 |

### Headless commands (CLN-19)

```sh
./labctl cleanup scan --entry system.user-caches --json
./labctl cleanup plan --entry system.user-caches --json
./labctl cleanup clean --plan PLAN_ID --yes --json
```

Repeat `--entry` to select multiple catalog detectors. `plan` defaults to Trash;
`--mode delete` must be explicit. The plan id expires after ten minutes, is
signed in the private state folder, and can be consumed only once. `clean`
verifies the paths and ignore rules again and writes the signed audit history.
Exit codes: 0 complete, 1 problem or partial result, 2 usage. No command accepts
a free-form path or shell command.

### Privileged maintenance (CLN-20)

The ordinary clean plan leaves administrator targets skipped. The local console
has a separate typed `POST /api/cleanup/privileged/plan` preview accepting only
known `actionIds`, followed by `POST /api/cleanup/privileged/run` with its
single-use `planId`. The preview lists exact arguments and expires in ten
minutes. Only root-owned system binaries in trusted directories can run; the
runner uses `pkexec` on Linux when present or noninteractive `sudo`, never a
shell or stored password. A failed authorization is reported as a failed action
and the result is written to audit history. Actions are: Linux journal vacuum
(archived logs older than seven days), APT archive cleanup, shared font-cache
rebuild, and macOS startup-volume Spotlight rebuild. Other platforms do not
list them. `GET /api/cleanup/disk-access` gives a read-only macOS Full Disk
Access hint; it cannot prove a complete operating-system grant.

## What the reference code adds

| Capability | Reference | Task |
|---|---|---|
| Native parallel scan: allocated vs apparent size, hard-link de-duplication, one-filesystem mode, size tree, progress, cancel | `reference/qrust-scan` (`walk`, `platform`, `cancel`) | CLN-21 |
| Hardening of that crate (nested ignore files, iterative glob, marker-verified candidates, pool error, saturating counts) — done | `reference/README.md` | CLN-22 |
| Drill-down, sort modes, hotspot descent, glob seek, gitignored view | `qrust-scan` (`tree`, `glob_search`, `gitignore`); `cleanup_ref.path_policy.validate_scan_root` | CLN-23 |
| Build artifacts proved by marker files and `CACHEDIR.TAG` | `cleanup_ref.artifacts` | CLN-24 |
| Cache paths from env var → tool probe (fixed argv) → per-OS default | `cleanup_ref.devcache` | CLN-25 |
| Cleaned-items ledger, learned score, soft pre-selection, Quick Clean | `cleanup_ref.learning` | CLN-26 |
| Move / restore / relink a cache behind a symlink, 7 link states | `cleanup_ref.relocation` | CLN-27 |
| Volumes and disk pressure | — (spec only) | CLN-28 |
| Simulator runtimes, unavailable devices, Android AVDs and system images | — (spec only) | CLN-29 |

## Do not port (known Qleaner bugs)

These were found by reading Qleaner (`src-tauri/src/cleaner/`, `commands.rs` unless noted). A PR that copies one of them is not accepted.

| Bug | Where | What Cleanup Lab does instead |
|---|---|---|
| If Trash fails, the item is **silently deleted permanently**, and bytes are counted as freed even when deletion failed | `clean_leftovers`, `clean_items` (`trash::delete(...).is_err()` → `remove_dir_all`, `let _ =`) | Rule 3 and rule 6 |
| Path traversal check is a substring test `contains("..")`. It rejects valid names like `a..b` and never resolves the path | `clean_items`, `clean_leftovers` | Rule 4 (resolved path inside an allowed root) |
| The restricted-path guard is `contains("system")`, so it blocks any path with "system" in it (e.g. `~/.cache/systemd`) yet protects nothing it does not literally name | same | Allowed-root list per OS |
| The running-app lock checks only Chrome and Firefox, by substring | same | Owning process per catalog entry, for every browser/app |
| The leftover scan returns immediately on Linux and Windows, although the TODO marks it fixed | `start_leftover_scan` (non-macOS) | CLN-10 |
| macOS paths (`Library/Caches/pip`, `…/pypoetry`, `…/helm`) used on every OS | `detectors.rs` CLI entries | Per-OS paths in the catalog |
| Tool presence via `sh -c "command -v nvm"`: shell functions (nvm, workon) are never found, so those entries never appear | `detect_cli_tool_data` | Check the directory itself; no shell |
| Only the Chrome `Default` profile is scanned | `get_cache_locations` | All profiles (CLN-05) |
| Credential stores (gh, AWS, gcloud, Azure) are listed as "cache" | `detect_cli_tool_data` | Rule 5 |
| Shredder ignores write and remove errors and still reports success | `secure_shred_file` | CLN-14 reports every failure |
| The audit-log HMAC key is hardcoded in source (`QleanerTelemetryCryptoIntegrity`), so the signature proves nothing | `clean_leftovers`, `db.rs` | Rule 7, CLN-15 |
| The Ignore Rules page is a placeholder; nothing enforces it | `src/routes/rules` | CLN-17 enforces it in the engine |

The private sources behind `reference/` had bugs of their own. They are fixed in
the reference code, and a PR that brings any of them back is not accepted either:

| Bug | What the reference code does instead |
|---|---|
| Purge removed items permanently (no Trash), counted apparent size and counted folders as files | CLN-13: Trash by default, bytes actually freed |
| Purge only refused `/` and the home folder, so any other home folder (Documents, Desktop…) could be purged | `path_policy.validate_target`: inside a catalog allowed root, not the root itself |
| Containment compared strings without resolving symlinks | `path_policy.is_contained`: resolved paths, path components |
| Relocation ran `rm -rf` on the original right after copying, with no verification, and retried as an elevated shell script built by string interpolation | `relocation.plan_move`: copy → verify → rename aside → symlink → verify → remove aside; no elevated fallback |
| "Prepare" / "link" ran `rm -rf` on whatever was at the home path | `relocation.plan_relink` refuses a real folder (CONFLICT) |
| An unreadable learning ledger was silently replaced, losing lifetime totals | `learning.LedgerStore` moves it aside and reports it |
| Pre-selection excluded only `high` risk | Also excludes `credentials` and `privacy` (rule 5) |
| Cleanup candidates `target` / `venv` matched by name only | `artifacts`: marker files required |
| Windows: directory identity read with `File::open`, so `stay_on_filesystem` zeroed every file | Fixed in `qrust-scan/src/platform.rs` |
| Apps quit (or force-quit) through AppleScript before cleaning | Rule 4: skip with a reason; never quit the user's apps |

## Definition of a good PR

- One CLN task per PR, reserved first, linked in the reservation file.
- Follows the contract and safety rules above. Does not copy a listed bug.
- Tests pass; dashboard changes pass `npm run check`, `npm run test:i18n`, `npm run build`, `npm run test:e2e`.
- `VERIFY.md` entry: commands run and their output, plus phone/tablet/desktop screenshots taken by script for UI changes.
- Parity: the PR updates `PARITY.md` for the detectors it ports.
- MYO063 bonus: at most two merged CLN PRs per student; hold at most two CLN reservations at a time.
