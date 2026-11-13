# Cleanup Lab verification record

One section per task: the commands that were run, their real output, and anything
that was not run and why. The checks in
[`README.md`](README.md#definition-of-a-good-pr) and [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
apply; this file is the evidence, not a second contract.

## CLN-01 — skeleton: engine, labctl, readiness endpoint

Branch `feat/cln-01-cleanup-skeleton`. Scope of this PR: engine, console API,
`labctl`, tests, knowledge graph. The dashboard page lives in the handoff section
of `STATUS.md` (this environment cannot write under `dashboard/`; see the session
log there).

### Engine unit tests

```console
$ cd cleanup-lab/engine && ../../.venv-test/bin/python -m unittest discover -s tests -p 'test_*.py'
Ran 29 tests in 0.048s
OK
```

Covers: platform mapping, per-OS state and Trash paths, the `OSLAB_CLEANUP_STATE`
override, relative XDG values being ignored, dangling-symlink and non-directory
components, the "never writes the state folder" rule, Python 3.11 exactly (the
`(3, 11, 0) >= (3, 11)` boundary), an unusable Trash, a group-readable state
folder, old-Python and unsupported-OS states, missing home folder, detector
counting, fake `PATH` lookups, the Windows Recycle Bin entry, control-character
escaping in CLI output, and the CLI exit codes (`0` ready / `1` problem / `2` usage).

### CLI

```console
$ ./labctl cleanup status
Cleanup Lab 0.1.0 · macOS · ready
  [ok] Supported operating system       macOS
  [ok] Python 3.11 or newer             3.15.0
  [ok] Home folder readable             /Users/Q
  [ok] Trash available                  /Users/Q/.Trash
  [ok] Private state folder writable    /Users/Q/Library/Application Support/os-lab/cleanup

Capabilities:
  [--] Detector catalog                 No detector catalog yet
  [--] Native scan backend              Reference crate present; not wired into the app yet
  [--] Container engine                 No docker or podman on PATH
  [ok] Package managers                 pip3 at /usr/bin/pip3
  [ok] Simulator tools                  xcrun at /usr/bin/xcrun
$ echo $?
0
```

`./labctl cleanup doctor` adds `Paths:` and a `Hints:` block with every
requirement's hint (failed ones marked `(needs attention)`); `--json` prints the same
payload as the HTTP endpoint. `bash -n labctl` parses.

### Console endpoint

```console
$ .venv/bin/python android-lab/lab/web_ui.py 5099 &
$ curl -sS -i http://127.0.0.1:5099/api/cleanup/status | head -5
HTTP/1.0 200 OK
Server: BaseHTTP Python/3.15.0
Date: Fri, 13 Nov 2026 00:40:46 GMT
Content-Type: application/json

$ curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5099/api/cleanup/nope
404
$ curl -sS -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:5099/api/cleanup/status?x=1'
400
$ curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5099/health/
200
```

Payload: `engine`, `state` (`ready` / `needs-setup` / `unavailable`), `platform`,
`home`, `stateDir`, `requirements[]`, `capabilities[]`, `reasons[]`, `checkedAt`.
On this Mac: `state: ready`, five requirements found, detector catalog absent
(CLN-02 has not landed), no reasons.

### Repository checks

```console
$ ./scripts/run-tests.sh
...
8 passed, 1 failed, 1 skipped
```

* `[ok] cleanup-lab/engine` — the new stage.
* `[ok] cleanup-lab/reference/python`, `[ok] source-lab/engine test suite`.
* `[ok]` bash -n (499 scripts), `lat check`, dashboard typecheck and
  `dashboard/dist matches the sources`.
* `[fail] android-lab/lab test suite` — **pre-existing on this arm64 Mac**, proved
  by running the same suite on a clean `master` worktree:

  ```console
  # branch feat/cln-01-cleanup-skeleton
  4 failed, 139 passed, 2 skipped, 10 errors in 12.42s
  # master (git worktree add .worktrees/cln01-baseline master)
  5 failed, 138 passed, 2 skipped, 10 errors in 17.47s
  ```

  The failing ids are the same set (three `test_app_update` download cases, one
  `test_web_ui` plan-token case, ten `test_content` OpenSSL signing cases); the
  branch has one fewer because `test_source_console` needs the primary checkout.
  No new failure.
* `[skip] cargo not installed` — `cargo` is only at `~/.cargo/bin`, which is not on
  `PATH` for this shell. This PR changes no Rust code; CLN-21/22 must run it.

```console
$ lat check
All checks passed in 222ms
$ git diff --check
$ echo $?
0
```

### Not run

* `npm run test:e2e` — this PR changes nothing under `dashboard/`, and Playwright
  browsers are not installed on this machine (no `~/Library/Caches/ms-playwright`).
* Dashboard screenshots — same reason, and the page is the handoff, not this PR.

## CLN-02 — detector catalog format, loader and Qleaner parity

Branch `feat/cln-02-catalog`. Scope: catalog data + schema, loader, parity table,
CLI and console endpoint. No dashboard file is touched.

### Engine unit tests

```console
$ cd cleanup-lab/engine && ../../.venv-test/bin/python -m unittest discover -s tests -p 'test_*.py'
Ran 47 tests in 0.023s
OK
```

18 new cases: template expansion (`~`, `{home}`, `{cache}`, `${VAR}`,
`${VAR:-fallback}`, `%VAR%`, unavailable context, relative path), per-platform
filtering, duplicate ids across files, a pre-selected `high`/`credentials`/`privacy`
entry refused, nine malformed-entry cases, bad file version, and `path: null` with a
reason instead of a guess. `SchemaTest` asserts the loader's required keys equal
`schema.json`'s and that every catalog file uses only declared fields.

### CLI

```console
$ ./labctl cleanup catalog
Cleanup Lab catalog · macos · 3 entries
  system.user-caches     User caches                low         pre-selected
      /Users/Q/Library/Caches
  system.user-logs       User logs                  low         pre-selected
      /Users/Q/Library/Logs
  system.trash           Trash                      medium      not pre-selected
      /Users/Q/.Trash
$ echo $?
0
```

`--json` prints the same payload as the endpoint.

### Console endpoint

```console
$ python3 -c '…CleanupAPI(".").get("/api/cleanup/catalog", {})…'
entries: 3 platform: macos
query -> 400 Unexpected query parameters
broken -> 500 The detector catalog is invalid: system.json: entry nope is missing name, category, risk,
```

The broken-catalog case uses a generated temp catalog, not the repository one.

### Repository checks

```console
$ ./scripts/run-tests.sh
8 passed, 1 failed, 1 skipped
```

The failure is still the android suite, pre-existing on this arm64 Mac (a clean
`master` worktree: 5 failed + 10 errors; this branch: 5 failed + 10 errors, same ids).
`cargo` is not on `PATH`, so qrust-scan is skipped; this PR changes no Rust.

```console
$ lat check
All checks passed in 538ms
$ git diff --check
(clean)
```

### Not run

`npm run check|test:i18n|build|test:e2e` — no file under `dashboard/` changed, and
Playwright browsers are not installed here.

## CLN-12 — one safety guard for every destructive call

Branch `feat/cln-12-safety-guard`. Scope: `cleanup_lab/safety.py` and its tests; the
modules that will call it are CLN-13 (plan) and CLN-15 (run).

### Engine unit tests

```console
$ cd cleanup-lab/engine && ../../.venv-test/bin/python -m unittest discover -s tests -p 'test_*.py'
Ran 69 tests in 0.144s
OK
```

22 new cases: path inside / equal to / outside its catalog root, a sibling with the
same prefix (`caches-old` vs `caches`), the valid name `a..b` that Qleaner's
`contains("..")` rejected, a symlink resolving outside the root, protected roots (`/`
and home), a missing path, a foreign owner (injected `lstat`), a running owning app,
whole-name vs basename process matching, the Windows `tasklist` CSV parser, a failing
process listing, scan-folder validation, copy pairs, the refusal codes, and a check
that every shipped catalog entry resolves to a non-protected path.

### Repository checks

```console
$ ./scripts/run-tests.sh
8 passed, 1 failed, 1 skipped
```

The failure is the android suite, pre-existing on this arm64 Mac (same ids on a clean
`master` worktree); `cargo` is not installed, so qrust-scan is skipped and no Rust
changed.

```console
$ lat check
All checks passed in 318ms
$ git diff --check
(clean)
```

### Not run

`npm` checks — no `dashboard/` file changed. Process matching was exercised with
injected tables on this macOS host; no Windows or Linux host ran the `tasklist` path.

## CLN-22 — harden qrust-scan

Branch `feat/cln-22-qrust-scan-hardening`. Rust only, under `cleanup-lab/reference/qrust-scan/`.

One failing test per gap, written first (`tests/hardening.rs`, `walk::tests`). Before the
fix the four ignore-stack tests failed and the 20 000-deep glob test aborted with
`thread ... has overflowed its stack`. After:

```console
$ cd cleanup-lab/reference/qrust-scan && cargo test
test result: ok. 6 passed   (unit: platform, walk)
test result: ok. 9 passed   (tests/hardening.rs)
test result: ok. 12 passed  (tests/scan.rs)
$ cargo clippy --all-targets -- -D warnings
Finished `dev` profile
$ cargo clippy --target x86_64-pc-windows-msvc --all-targets -- -D warnings
Finished `dev` profile
$ cargo fmt --check
(clean)
```

Covers: a nested `.gitignore` applying below its own folder only; a deeper file re-including
what a parent ignored; `.git/info/exclude`; the global excludes file as lowest priority;
no re-inclusion below an ignored folder; a 12 000-deep glob; pre-order and prune-on-match
unchanged; `target/` without `Cargo.toml` rejected; Rust, Maven, Node, venv and
`CACHEDIR.TAG` signatures proved (and a `.venv` without `pyvenv.cfg`, or a tag without the
signature, rejected); thread-pool failure returned as an error; `entry_count` saturating.

### Not run

The Windows target was type-checked and linted only; no Windows host ran the tests. The
Rust and Python signature tables are kept in step by hand (same ids), not by a shared file.

## CLN-03 — scan job: bounded-parallel size scan with progress and cancel

Branch `feat/cln-03-scan-jobs`. Engine, console API, tests and the knowledge graph.
The scan is read-only; no file under `dashboard/` changed (the page is CLN-16, and
the endpoint contract, states and strings are in the CLN-03 handoff in `STATUS.md`).

### Engine unit tests

```console
$ cd cleanup-lab/engine && ../../.venv-test/bin/python -m unittest discover -s tests -p 'test_*.py'
Ran 88 tests in 0.149s
OK
```

Covers: apparent and on-disk sizes from a generated tree; a symlink inside the tree
and a top-level symlink never followed; a symlink loop terminating; hard links
counted once across parallel paths (thread-safe inode set); a mode-000 file still
sized because only `lstat` is used; a permission-denied directory reported in
`unreadable` without failing the scan; missing path and unset-variable reasons; a
FIFO not measured; cancel mid-walk and before start (partial counters,
`cancelled: true`, phase `cancelled`); progress keys and totals; one and four
workers agreeing; the shipped catalog against a fake `HOME`.

### Console tests

```console
$ cd android-lab/lab && ../../.venv-test/bin/python -m pytest tests/test_cleanup_console.py -q
5 passed in 0.62s
```

Covers: a real scan job from `POST /api/cleanup/scan` to
`GET /api/cleanup/jobs/<id>`; refusal of a path list, unknown keys, duplicate or
unknown ids, non-string ids and out-of-range workers (`400`); unknown job and
endpoint (`404`); cancel reaching a running scan and mapping to `cancelled`; the
browser route (`X-OSLab`) starting, polling and cancelling a job.

### End to end over HTTP (generated temp `HOME`)

```console
$ curl -sS -X POST -H 'Content-Type: application/json' -H 'X-OSLab: 1' \
    -d '{"entryIds":["system.user-caches"],"workers":1}' \
    http://127.0.0.1:5098/api/cleanup/scan
HTTP/1.0 202 Accepted
{"id":"2b8cc9ba670f","kind":"scan","state":"running",...}

$ curl -sS http://127.0.0.1:5098/api/cleanup/jobs/2b8cc9ba670f
{
  "id": "2b8cc9ba670f",
  "kind": "scan",
  "state": "done",
  "progress": {"phase": "done", "pathsDone": 1, "pathsTotal": 1,
               "bytesSeen": 40960, "filesSeen": 1, "currentPath": ".../Library/Caches/demo"},
  "error": null
}
totals: {'sizeBytes': 40960, 'sizeOnDiskBytes': 40960, 'files': 1, 'folders': 2,
         'paths': 1, 'unreadable': 0, 'entries': 1}
path:   {'path': '.../Library/Caches', 'measured': True, 'sizeBytes': 40960,
         'files': 1, 'folders': 2, 'unreadable': []}

$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST -H 'X-OSLab: 1' -d '{}' \
    http://127.0.0.1:5098/api/cleanup/jobs/2b8cc9ba670f/cancel
200
$ ... POST /api/cleanup/scan with {"path":"/tmp"}           -> 400
$ ... GET  /api/cleanup/jobs/nope                           -> 404
$ ... GET  '/api/cleanup/jobs?x=1'                          -> 400
```

The server ran with `HOME` pointing at a `mktemp -d` tree; no real user folder was
scanned.

### Repository checks

A completed `./scripts/run-tests.sh` run reported **8 passed, 2 failed, 0 skipped**:

* `[ok] cleanup-lab/reference/python`, `[ok] cleanup-lab/engine`,
  `[ok] cleanup-lab/reference/qrust-scan`, `[ok]` sample smoke, `[ok]` `bash -n`
  (125 scripts), `[ok]` dashboard typecheck, `[ok]` `dashboard/dist matches the
  sources`.
* `[fail] android-lab/lab test suite` — **pre-existing**, proved by running the
  same six failing ids on a clean `master` worktree:
  `6 failed, 56 passed, 1 skipped` (three `test_app_update` download cases,
  `test_jadx_decompiler_on_real_dex`, `test_source_console` mutation guards,
  `test_web_ui` plan preview). The branch's full-suite result was
  `6 failed, 153 passed, 1 skipped`; no new failure. The new
  `test_cleanup_console.py` passes.
* `[fail] lat check` in that run — the CLN-03 section summary exceeded the
  250-character lead limit. Shortened; re-run:

```console
$ lat check
All checks passed in 146ms
```

The full suite was not re-run after that one-line documentation fix (maintainer
instruction). No code changed.

### Not run

`npm run test:e2e` and dashboard screenshots — nothing under `dashboard/` changed
and this PR adds no page. `cargo clippy`/`fmt` — no Rust changed. No Windows host
ran the POSIX permission and FIFO tests; they are skipped there by design.

## CLN-13 — plan → confirm → clean, Trash by default, honest results

Branch `feat/cln-13-plan-confirm-clean`. Engine, console API, tests and the
knowledge graph. No file under `dashboard/` changed; the page and its confirm step
are CLN-16 and the contract is in the CLN-13 handoff in `STATUS.md`.

### Engine unit tests

```console
$ cd cleanup-lab/engine && ../../.venv-test/bin/python -m unittest discover -s tests -p 'test_*.py'
Ran 112 tests in 1.059s

OK
```

The 24 new tests cover: a read-only plan that lists sizes and marks ready items;
the safety guard skipping running apps and privileged entries; duplicate and nested
paths yielding to the first item; a FIFO planned as not cleanable; a cancelled plan
build making no plan; the Trash never being moved into itself; planning leaving
mtimes untouched; Trash by default with collision names; a **failed Trash staying a
failure** (the original remains, no bytes counted); transient `EBUSY` retries with
backoff; partial failure across two entries; cancel between items; cross-volume copy
verified before removing the source; a failed source removal keeping the verified
copy; the freedesktop `.trashinfo` sidecar on Linux; explicit delete mode; changed,
added and vanished items expiring the plan; the TTL clock; planned skips carrying
reasons and zero bytes; and invalid requests/worker bounds.

### Console tests

```console
$ cd android-lab/lab && ../../.venv-test/bin/python -m pytest tests/test_cleanup_console.py -q
..........                                                               [100%]
10 passed in 1.21s
```

Covers: a real plan job previewed and cleaned from the console (job kinds, ready
size, Trash move, counted bytes, Trash path, recent jobs); typed refusal of a path,
command, unknown key, empty/duplicate/unknown ids, bad mode/workers and bad
`planId`; a changed item failing the clean with nothing removed; a plan being
single-use (`409`) and expiring (`410`); and the browser route starting both a
plan and a clean with `202`, polling to `done`.

### Repository checks

```console
$ PATH=.../.venv-test/bin:$PATH CARGO_TARGET_DIR=/Volumes/Projects/iQ/.cargo-target-cln13 \
    ./scripts/run-tests.sh --no-venv
...
6 failed, 158 passed, 1 skipped in 21.50s
[fail] android-lab/lab test suite
[ok]   source-lab/engine test suite         176 passed
[ok]   cleanup-lab/reference/python          35 tests, OK
[ok]   cleanup-lab/engine                    112 tests, OK
[ok]   cleanup-lab/reference/qrust-scan      27 tests, OK
[ok]   sample analysis + report generated
[ok]   all 70 shell scripts parse
[ok]   lat check
[skip] dashboard dependencies not installed
7 passed, 1 failed, 1 skipped
```

The only failure is the known android stage: the same six ids as `master`
(`test_app_update` ×3, `test_jadx_decompiler_on_real_dex`, the
`test_source_console` mutation guard, the `test_web_ui` plan preview), with the
suite at `158 passed` thanks to the ten console tests. The dashboard stage was
skipped because this worktree has no `node_modules`; nothing under `dashboard/`
changed. `lat check` also ran clean on its own:

```console
$ lat check
All checks passed in 456ms
$ git diff --check
(clean)
$ python -m py_compile cleanup-lab/engine/cleanup_lab/clean.py console/cleanup_api.py \
    android-lab/lab/web_ui.py android-lab/lab/tests/test_cleanup_console.py
(ok)
```

### Not run

`npm run check` / `build` / `test:e2e` and dashboard screenshots — no dashboard
file changed and this worktree has no Node dependencies; the page is CLN-16. Rust
`fmt`/`clippy` — no Rust changed. No Windows host ran the cross-volume and
freedesktop-Trash paths; those use injected tests.

## CLN-15 — private audit history

Branch `codex/cln-15-audit-history` from master `6656ed55`. A clean request
checks that a private state folder, 32-byte per-install key and SQLite store are
usable before claiming the plan. Completed clean results are recorded with their
paths, mode, counted bytes and outcomes. Rows and the chain head have HMAC-SHA256
signatures; `labctl cleanup history --verify` and `GET /api/cleanup/history`
verify the full chain. Changed or removed rows fail verification. Like any local
integrity scheme, restoring an older complete snapshot of both database and key
cannot be distinguished without an external trusted anchor.

```console
$ cd cleanup-lab/engine && ../../.venv-test/bin/python -m unittest discover -s tests -p 'test_*.py'
Ran 118 tests — OK
$ cd android-lab/lab && ../../.venv-test/bin/python -m pytest tests/test_cleanup_console.py -q
10 passed
$ lat check
All checks passed
```

`./scripts/run-tests.sh --no-venv` passed the cleanup engine, reference Python,
Rust, Source Lab, shell syntax, knowledge graph and dashboard typecheck/build
stages. Its Android stage had the same six host or baseline failures recorded for
CLN-13 (three AppImage architecture expectations, invalid `JAVA_HOME` for JADX,
source console mutation guard, and web UI preview status): 6 failed, 158 passed,
1 skipped. No dashboard files changed; CLN-16 owns the history view.

## CLN-04 … CLN-29

Each task appends its own section when it lands.

## CLN-17 — enforced ignore rules

Branch `codex/cln-17-ignore-rules`, stacked on CLN-15. Private rule store and
typed CRUD API accept `path`, `extension` and `glob` rules. Scans omit matching
paths. Plans skip any catalog parent containing an ignored descendant. A rules
change expires a plan before cleaning and execution rechecks between items.

```console
$ cd cleanup-lab/engine && python3 -m unittest discover -s tests -p 'test_*.py'
Ran 122 tests — OK
$ uv run --with pytest python -m pytest android-lab/lab/tests/test_cleanup_console.py -q
11 passed
$ PATH=/Volumes/Projects/iQ/os-lab/.venv-test/bin:$PATH ./scripts/run-tests.sh --no-venv
7 passed, 1 failed, 1 skipped
$ lat check
All checks passed
```

The broader gate has the same six Android failures recorded for CLN-13/15
(three architecture-specific update fixtures, JADX on this host, Source Lab
mutation guard, and the web UI preview status). It passes the Cleanup Lab,
Source Lab, Rust, shell, smoke and graph stages. Dashboard checks are skipped
because this worktree has no `node_modules` and no dashboard source changed.

The `/cleanup/` plain settings controls depend on CLN-16's page branch and remain
for that integration. No dashboard source changed in this PR.

## CLN-18 — scheduled dry-run scans

Branch `codex/cln-18-scheduled-scans`, stacked on CLN-17. Cron validation,
private CRUD store, and a console-lifetime runner claim each due local minute
once. The runner launches scan jobs only, records a compact result, and never
calls plan or clean. It does not replay missed minutes after the console stops.

```console
$ cd cleanup-lab/engine && python3 -m unittest discover -s tests -p 'test_*.py'
Ran 124 tests — OK
$ uv run --with pytest python -m pytest android-lab/lab/tests/test_cleanup_console.py -q
12 passed
$ PATH=/Volumes/Projects/iQ/os-lab/.venv-test/bin:$PATH ./scripts/run-tests.sh --no-venv
7 passed, 1 failed, 1 skipped
$ /Volumes/Projects/iQ/os-lab/.venv-test/bin/python -m pytest android-lab/lab/tests/test_web_ui.py::test_post_requires_oslab_header -q
1 passed
$ lat check
All checks passed
```

The broader gate had the six documented host/baseline Android failures and one
connection reset in `test_post_requires_oslab_header`; that test passed alone
immediately after. Cleanup Lab, Source Lab, Rust, shell, smoke and graph stages
passed. Dashboard checks were skipped because this worktree has no dependencies
and no dashboard source changed.

The plain schedules section on `/cleanup/` depends on CLN-16's page branch.
