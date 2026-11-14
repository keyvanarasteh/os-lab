# Cleanup Lab — port sprint TODO

Working checklist for the `feat/cleanup-port` workstream. The what-and-why of
every item lives in [`PLAN-port-sprint.md`](PLAN-port-sprint.md); the contract
and safety rules live in [`README.md`](README.md). One task = one commit
series; `VERIFY.md` gets an entry with real command output per task.

## Task 1 — CLN-17 engine-enforced ignore rules

- [x] `cleanup_lab/ignore.py`: typed store (`ignore-rules.json`, `0700`/`0600`,
      no symlink, atomic replace), rule validation (absolute `path`, sane
      `glob`, bare `extension`), dedup on type+value, fail-closed read.
- [x] Matching semantics: `path` covers the path and everything under it;
      `glob` matches the full path and any suffix (and a matched folder covers
      its subtree, with `*` never crossing a separator); `extension`
      case-insensitive.
- [x] Scan prune: catalog scan skips ignored paths, counted and reported.
- [x] Plan refusal: `ignored` for a direct match, `contains-ignored` when an
      ignored path lies inside a planned folder (path rules by containment,
      glob/extension rules during the fingerprint walk), `ignore-store-corrupt`
      fail-closed on an unreadable/corrupt store.
- [x] `tests/test_ignore.py`: store roundtrip, validation, dedup, corrupt
      store, matching, scan prune, plan refusals, fail-closed plan.
- [ ] Console CRUD: `GET /api/cleanup/ignore`, `POST /api/cleanup/ignore`
      (add), `DELETE /api/cleanup/ignore/<id>` — ids only, typed 400s.
- [ ] `labctl cleanup ignore add|remove|list [--json]`, exit codes 0/1/2.
- [ ] Settings section on `/cleanup/` (list, add, remove) + seven locales.
- [ ] Deep-sweep and Space Explorer candidate pruning through the same rules.
- [ ] Docs: `lat.md/cleanup-lab.md` section, README section, `VERIFY.md`.

## Task 2 — CLN-14 secure shred

- [ ] `cleanup_lab/shred.py`: overwrite passes (1/3, fsync per pass),
      same-folder random rename, unlink, bottom-up folders, symlink and
      special-node refusal, TOCTOU re-verification, per-entry results.
- [ ] `cleanup_lab/settings.py`: `shredPolicy` store, fail-closed read
      (`shred-settings-corrupt`), Trash/delete never read it.
- [ ] `shred` plan mode: settings gate (`shred-disabled`), pass count in the
      plan payload, corrupt-plan refusal, partial-shred honesty.
- [ ] `tests/test_shred.py` for all of the above.
- [ ] Fix the three known self-test defects: the trash-mode expectation reads
      the original path instead of the Trash destination; the FIFO refusal
      asserts on the status word instead of the error text; decide and align
      the unreadable-empty-folder behaviour (remove vs keep) between code and
      test.
- [ ] Console settings endpoints + `labctl cleanup settings show|set`.
- [ ] Dashboard settings policy picker + shred confirmation wording stating
      the SSD/APFS/COW limits, seven locales.
- [ ] Docs: README section, `VERIFY.md`, `PARITY.md` technique row.

## Task 3 — CLN-19 headless CLI

- [ ] `labctl cleanup scan|plan|clean --plan <id> --yes --json`.
- [ ] JSON never prompts; `clean` requires `--yes` + unexpired plan id.
- [ ] Sanitize file names in text output (ANSI/bidi/control stripped).
- [ ] Exit codes 0/1/2 in every path; CLI tests; README usage.

## Task 4 — CLN-18 scheduled dry-run scans

- [ ] Schedule store in private state (add/toggle/delete, cron validation).
- [ ] Runner hook in the monitor thread: due schedule → scan-only pass,
      recorded result; schedules can never clean.
- [ ] Wake-catch-up semantics; tests; `/cleanup/` schedules section + locales.

## Task 5 — CLN-29 simulator/emulator runtimes

- [ ] Xcode simulator runtimes + unavailable devices (fixed `simctl` argv,
      parser tests on recorded JSON).
- [ ] Android AVDs + SDK system images (fixed argv, sizes, in-use state).
- [ ] Typed preview → single-use id → audited run for removals (ids, never
      paths); booted-device runtime skipped with a reason; readiness gating.

## Task 6 — CLN-23 Space Explorer deltas

- [ ] On-disk sizes beside apparent sizes (honest `null` where unavailable).
- [ ] Sort toggles (size/name/count/newest, asc↔desc, re-keyed metric).
- [ ] Largest-sibling bar setting; count and mtime columns.
- [ ] Glob seek as a navigable virtual root; gitignored + candidate overlays.
- [ ] Mid-scan preview; cancel keeps partial results.
- [ ] Hotspot descent; re-select-on-parent-return.
- [ ] E2E with mocked API; scripted screenshots; seven locales.

## Task 7 — CLN-26 learning ledger

- [ ] Cleaned-items ledger in private state (bytes actually freed, per run).
- [ ] Learned rows ticked (never default-selected) + "Why is this selected?"
      hint; never high-risk/credentials/privacy.
- [ ] Corrupt ledger moved aside and reported; clearable from the page; tests.

## Task 8 — CLN-31 scan snapshots

- [ ] Versioned snapshot writer/reader (interchange-compatible), digest
      verified, atomic write; read-only imports.
- [ ] `labctl cleanup snapshot export|import|diff`; diff endpoint (added /
      removed / grown / shrunk) with depth/prefix/summary options.
- [ ] Optional snapshot export from scheduled scans; corrupt-file tests.

## Task 9 — CLN-21 native scan backend

- [ ] Typed Tauri command over `cleanup-lab/reference/qrust-scan` (validated
      root id + options, progress events, cancel, no `unsafe`).
- [ ] Parity test vs the Python scanner on a generated tree; throughput of
      both backends in `VERIFY.md`.

## Task 10 — CLN-30 duplicates

- [ ] Size grouping → prehash → full SHA-256; keeper vocabulary; hard links
      once; cloud placeholders and packages skipped with reasons.
- [ ] Report-only cards; Trash-only removal via the CLN-13 plan; group-aware
      bulk-selection presets; tests on generated trees.

## Task 11 — CLN-32 age and size filters

- [ ] Min/max-age filter fields on scan + deep-scan requests (durations);
      plan refuses filtered-in-flux selections.
- [ ] Large & Old Files catalog entries with settings thresholds, never
      pre-selected; minimal-size filtering; tests.

## Task 12 — CLN-33 safety hardening (re-scoped post cleaner-pro)

- [ ] Immutable/restricted-flag and rootless-xattr skip reasons (macOS).
- [ ] Cloud FileProvider denylist with rationale comment.
- [ ] Live-socket/FIFO guard; open-handle probe; SQLite-in-use detection.
- [ ] Post-delete survivor verification step in the executor.
- [ ] Dataless-file materialization prevention during scans (macOS).
- [ ] Grant → poll → auto-retry-the-failed-batch flow on the dashboard.

## Task 13 — CLN-34 dynamic user-cache discovery (stretch)

- [ ] `discover: caches-children` template in `schema.json` + loader,
      expanding like `profile-glob`; report-only, plan-capable entries;
      fixture tests.

## Task 14 — deferred P3 backlog

Free-space wipe (CLN-35) · locale cleaning (CLN-36) · exclusive-size
accounting · git-verified dev-cache candidates · versioned scan cache ·
installer-file hunter · per-volume Trash · browser service-worker guards and
old-version sweeps · AI-assistant caches · orphaned LaunchAgents · stale
git-worktrees · `labctl` completions · SQLite privacy cleaning (far future).
