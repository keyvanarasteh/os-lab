# Draft PR — feat/cleanup-port

> Local working copy of the pull-request text for the `feat/cleanup-port`
> branch. Nothing has been pushed; open the draft PR only when the maintainer
> says so. Kept free of any reference to the projects whose behaviour was
> studied during discovery — the PR, like the plan, describes features by what
> they do.

---

**Title:** `feat(cleanup-lab): port sprint — ignore rules, secure shred, headless CLI, schedules, runtimes, explorer deltas, ledger, snapshots, duplicates, age filters, safety hardening`

**Body:**

## Summary

Second workstream on top of the cleaner-pro merge. Ports the remaining
Cleanup Lab roadmap tasks and the maintainer-approved additions as original
os-lab code, one task per commit series, under the same architecture contract
and safety rules as every Cleanup Lab change:

- **CLN-17** engine-enforced ignore rules (paths / globs / extensions; scan
  prune; plan refusal incl. contains-ignored; fail-closed store; CRUD +
  `labctl cleanup ignore` + settings section)
- **CLN-14** secure shred as an explicit plan mode (1/3-pass overwrite,
  verified rename + unlink, per-entry honest results, fail-closed settings
  policy, SSD/APFS/COW limits in the UI)
- **CLN-19** headless CLI parity (`labctl cleanup scan|plan|clean --json`,
  `--yes` gating, sanitized output, exit codes 0/1/2)
- **CLN-18** scheduled **dry-run** scans (cron store, wake catch-up; a
  schedule can never clean)
- **CLN-29** Xcode simulator runtimes + unavailable devices + Android AVDs
  and system images (sizes, in-use state, typed previewed removals)
- **CLN-23 deltas** for the Space Explorer: on-disk sizes, sort toggles,
  largest-sibling bars, glob seek, gitignored overlay, mid-scan preview,
  cancel-keeps-partial, hotspot descent
- **CLN-26 deltas**: cleaned-items learning ledger with soft pre-selection
  and "Why is this selected?" hints
- **CLN-31** scan snapshots export/import + diff (interchange-compatible
  format; read-only imports; scheduled scans may export)
- **CLN-30** duplicate finder (report-only first; keeper vocabulary; Trash-only
  via the plan)
- **CLN-32** age/size filters and Large & Old Files entries
- **CLN-33** safety hardening pack (immutable-flag skip reasons, cloud
  placeholder denylist, live-socket guard, survivor verification, open-handle
  probe, dataless-materialization prevention, grant→poll→auto-retry)
- **CLN-34** dynamic user-cache discovery via a catalog `discover` template
  (stretch)
- Deferred backlog recorded in `cleanup-lab/PLAN-port-sprint.md` (CLN-35/36 and
  smaller items)

## Contract

Unchanged: engine = Python stdlib; all target paths are catalog data; typed
console APIs (ids in, never paths or command strings); plan → confirm → run
with fingerprints and Trash by default; honest bytes; HMAC-chained audit
history; tests on generated trees only. The full plan and per-task deliverables
live in [`cleanup-lab/PLAN-port-sprint.md`](../cleanup-lab/PLAN-port-sprint.md)
with the working checklist in
[`cleanup-lab/TODO-port-sprint.md`](../cleanup-lab/TODO-port-sprint.md).

## Verification

Per merged task: `cleanup-lab/engine` unittest suite, the console typed-job
suite, `scripts/run-tests.sh`, and for dashboard tasks `npm run check`,
`npm run test:i18n`, `npm run build`, `npm run test:e2e`; `lat check` after
every knowledge-graph edit. `VERIFY.md` carries the commands and their real
output per task.

## Notes for reviewers

- Draft until the first task series is green on this branch.
- The clean-pro workstream's honest deviations (treemap view, explorer on-disk
  sizes) are picked up by the CLN-23 deltas here instead of being reopened
  there.
- Docs updated in the same series as the code: `lat.md/cleanup-lab.md`,
  `cleanup-lab/README.md`, `cleanup-lab/VERIFY.md`, `cleanup-lab/PARITY.md`.
