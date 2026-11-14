# Cleanup Lab — port sprint plan

Planning document for the `feat/cleanup-port` workstream on the Cleanup Lab,
based on the current `master` (the cleaner-pro workstream already landed:
permissions, background monitor, bookmarks/quick-clean, custom entries and the
Space Explorer). This sprint ports the remaining capabilities the roadmap
promises, plus the new ones the maintainer approved, as original os-lab code.

The behaviours were specified during a discovery pass over mature open-source
cleaners whose local checkouts were used read-only for research. **Implementation
here is original os-lab code, and this document deliberately names no external
project** — features are described by what they do, not where they came from.

Task series: the pending roadmap ids `CLN-14`, `CLN-17`, `CLN-18`, `CLN-19`,
`CLN-21`, the deltas of the merged `CLNP-21…23` Space Explorer and `CLNP-14…19`
quick clean, `CLN-29`, and the provisional ids `CLN-30…36` recorded in the
discovery notes. Each task lands as its own commit (or stacked PR) per the
"each Cleanup Lab task in its own PR" rule. Every task obeys the architecture
contract and the eight safety rules in [`README.md`](README.md), and none may
reintroduce a bug from the "Do not port" tables.

---

## Task 1 — Engine-enforced ignore rules (CLN-17)

Paths, glob patterns and filename extensions the user marks as never-touch.
The engine enforces them everywhere — the scan prunes them, the plan refuses
them — and a broken rules store fails closed.

- Typed rule store in the private state folder (`ignore-rules.json`, same
  discipline as the settings store: `0700` folder, `0600` file, no symlink,
  atomic replace). Rule = `{id, type: path|glob|extension, value, note?}`;
  `path` rules must be absolute and cover the path and everything under it;
  `glob` rules match against the full path and against any path suffix, so a
  bare name matches at any depth; `extension` rules match case-insensitively.
- Enforcement: the catalog scan skips ignored paths (counted, reported), and a
  plan refuses an ignored item (`ignored`) and refuses a candidate folder that
  contains an ignored path (`contains-ignored`) — a folder the user excluded
  must never be deleted because of what is inside it.
- Fail closed: an unreadable or corrupt store refuses the plan
  (`ignore-store-corrupt`) and fails the scan with a typed error — rules that
  cannot be read are never silently dropped.
- Console CRUD (`GET/POST/DELETE /api/cleanup/ignore`, ids only), `labctl
  cleanup ignore add|remove|list --json`, settings section on `/cleanup/`.
- Engine tests: roundtrip, validation, dedup, corrupt store, scan prune,
  plan refusal, containment refusal.

## Task 2 — Secure shred, done honestly (CLN-14)

Overwrite-in-place destruction as an explicit plan mode, with every failure
reported and the physical limits stated in the UI.

- Engine `shred.py`: regular files overwritten pass by pass (1-pass zeros;
  3-pass zeros → ones → OS random), each pass flushed and `fsync`ed, then a
  random rename inside the file's own folder and an unlink; folders shredded
  bottom-up. `O_NOFOLLOW` opens; the target is re-verified (same device and
  inode, same size) after overwriting; symlinks are refused; sockets, FIFOs
  and device nodes are refused and left in place (their folder's removal then
  fails honestly).
- Typed settings store (`settings.json` in private state) holds
  `shredPolicy: off | 1-pass | 3-pass`, default `off`. Only shred plans read
  it: `off` refuses the plan (`shred-disabled`) and a corrupt store refuses it
  too (`shred-settings-corrupt`) — shred fails closed while Trash and delete
  never touch the store.
- `shred` joins the plan modes; the plan payload names the pass count; a plan
  without a valid count fails the item instead of shredding once. A partially
  shredded folder reports `failed` with the per-entry results and credits only
  bytes verifiably destroyed.
- Console settings endpoints, `labctl cleanup settings`, the policy picker in
  the dashboard settings, and confirm-dialog copy stating that overwriting is
  not a guarantee on SSD, APFS or copy-on-write filesystems.

## Task 3 — Headless CLI parity (CLN-19)

`labctl cleanup scan | plan | clean --plan <id> --yes --json` with exit codes
`0` clean / `1` problem / `2` usage. JSON never prompts; `clean` requires
`--yes` and an unexpired plan id; every text output sanitizes file names
(ANSI, bidi and control characters stripped); skip reasons ride along in the
JSON. CLI tests and README usage.

## Task 4 — Scheduled dry-run scans (CLN-18)

A schedule store in private state (add / toggle / delete with cron
validation), evaluated by the existing monitor runner hook: a due schedule
runs a **scan-only** pass and records the result; it can never clean. Pairs
with Task 8 (snapshots) so a scheduled scan can also export a snapshot.
Wake-catch-up semantics, tests for validation, catch-up and the no-clean
guarantee, and a schedules section on `/cleanup/`.

## Task 5 — Simulator and emulator runtimes (CLN-29)

Beyond the CLN-07 device list: Xcode simulator runtimes and unavailable
devices, plus Android AVDs and SDK system images — each with size and in-use
state (a runtime used by a booted device is skipped with a reason). Fixed
argv only; removal goes through the typed preview → single-use id → audited
run pattern with ids from the page, never paths. Parser tests on recorded
JSON samples; readiness hides the section where the tool is missing.

## Task 6 — Space Explorer deltas (CLN-23 remainder)

The merged Space Explorer walks a parent-summed tree over registered roots.
This task ports what its ledger records as not done, plus the interaction
affordances the current tab lacks:

- On-disk (allocated) sizes beside apparent sizes, with the usual honest
  `null` where the OS exposes no block count.
- Sort toggles: size / name / item count / newest, asc↔desc on repeat, with
  the displayed metric re-keying the sort.
- Largest-sibling relative bar as a view setting; item-count and mtime
  columns.
- Glob seek: a search over reported paths becomes a navigable virtual root.
- A gitignored overlay for the current view, and a cleanup-candidate overlay.
- Mid-scan preview (browse the point-in-time snapshot while the job runs) and
  cancel-keeps-partial-results semantics.
- Hotspot descent (jump along the biggest path) and re-select-on-return.

## Task 7 — Learning ledger (CLN-26 remainder)

Quick Clean itself landed with the bookmarks workstream. The remaining half is
the ledger: record every item really cleaned (bytes actually freed), rank the
patterns the user cleans repeatedly by choice, tick — never default-select —
matching rows in the next scan with a "Why is this selected?" hint, and keep
the ledger clearable. A corrupt ledger is moved aside and reported, never
overwritten; high-risk, credential and privacy rows are never touched.

## Task 8 — Scan snapshots export/import and diff (CLN-31)

A versioned, stream-verified snapshot format for catalog scans and Space
Explorer trees (compatible with the de-facto interchange format used by the
classic ncurses analyzers, so existing tooling can read our exports and we
can read theirs). Read-only imports; `labctl cleanup snapshot
export|import|diff`; a diff endpoint (added / removed / grown / shrunk) for
the dashboard; scheduled scans (Task 4) may export snapshots.

## Task 9 — Native scan backend (CLN-21)

Wire the already-hardened reference crate in `cleanup-lab/reference/qrust-scan`
into the desktop app behind one typed command (validated root id and options,
progress events, cancel, no `unsafe`). The Python scanner stays the default;
the native backend is opt-in and must agree with it on a parity tree (hard
links, symlinks, an unreadable folder). Throughput of both backends recorded
in `VERIFY.md`.

## Task 10 — Duplicate finder (CLN-30)

Report-only first: size grouping → cheap prehash of the first and last few
KiB → full SHA-256, grouped with one protected keeper per group and the
group-aware keeper vocabulary (all-but-newest / all-but-oldest / all-but-
biggest / all-but-smallest / one-keeper). Hard links counted once; cloud
placeholders and packages skipped with reasons; Trash-only removal through
the CLN-13 plan. Results cards reuse the group-aware bulk-selection presets.

## Task 11 — Age and size filters (CLN-32)

Min-age / max-age filters on catalog and deep-scan results (durations like
`7d`, `2h30m`, `1y2mo`), and "Large & Old Files" catalog entries driven by
settings thresholds — never pre-selected. While an age filter is active, plan
building refuses the affected selections, mirroring the delete-blocked-while-
filtered rule; minimal-file-size filtering rides the same request fields.

## Task 12 — Safety hardening pack (CLN-33, re-scoped)

The permission probes and unreadable-path classification already landed with
the cleaner-pro permissions work. The remaining hardening, all in
`safety.py`/readiness with fakes in tests:

- macOS immutable/restricted flags and rootless xattrs as skip reasons.
- A cloud FileProvider denylist (never clean iCloud/cloud placeholder state)
  with a written rationale comment.
- A live-socket/FIFO guard for runtime directories.
- A post-delete "item survived removal" verification step.
- An open-handle probe (lsof / `/proc`) before planned removals; SQLite-in-use
  detection.
- macOS dataless-file materialization prevention during scans (never let a
  scan download cloud placeholders).
- The grant → poll → auto-retry-the-failed-batch flow for permission-gated
  batches on the dashboard.

## Task 13 — Dynamic user-cache discovery (CLN-34, stretch)

The catalog stays the source of truth: a `discover: caches-children` template
in `schema.json` expands at scan time like the existing `profile-glob`
detector does — enumerating the user cache root's children, per-app sandbox
containers and per-app HTTP storage as report-only, plan-capable entries
through the normal guard.

## Task 14 — Deferred (P3, recorded)

Free-space wipe (fill-with-zeros temp file, trim afterwards, orphaned-temp
cleanup; explicit opt-in; SSD/COW limits documented) — `CLN-35`. Locale and
locale-cache cleaning, report-only first, with a keep-list — `CLN-36`.
Recorded for later without a sprint slot: exclusive-size / shared-extent
accounting, git-tracked-content verification for dev-cache candidates, a
versioned scan cache with auto-invalidation, an installer-file hunter,
per-volume Trash entries, browser service-worker guards with PWA-domain
protection and browser old-version sweeps, AI-assistant app caches, orphaned
LaunchAgents detection, stale git-worktree detection, `labctl` shell
completions, and row-level SQLite privacy cleaning (far future, needs its own
safety story).

---

## Verification (every task)

```bash
cd cleanup-lab/engine && python3 -m unittest discover -s tests -p 'test_*.py'
cd android-lab/lab && python3 -m unittest discover -s tests -p 'test_cleanup_console.py'
scripts/run-tests.sh                       # full repo gate
# dashboard tasks only:
cd dashboard && npm run check && npm run test:i18n && npm run build && npm run test:e2e
lat check                                  # after every lat.md edit
```

Each task updates `lat.md/cleanup-lab.md`, `cleanup-lab/README.md`,
`cleanup-lab/VERIFY.md` (commands + real output) and `cleanup-lab/PARITY.md`
where detectors change, in the same commit series as the code.
