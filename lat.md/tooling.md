# Repository tooling

Cross-cutting process, tests and conventions for the monorepo: CI, the android
test suite, contribution flow and the project's security/licensing stance.

## Local test runner

The local runner complements enabled browser/content and Linux/macOS package
workflows. Windows tag builds publish unsigned until SignPath credentials are
configured and then sign automatically; pull-request builds never publish.

The release workflows report their outcome to Telegram when the
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` repository secrets are set, and stay
silent without them (see [app/RELEASE_CI.md](../app/RELEASE_CI.md)).

[[scripts/run-tests.sh]] is the CI replacement. It prepares a Python
environment (a `.venv-test` unless `--no-venv`), runs the pytest suite in
[[android-lab/lab/tests]], runs a sample-analysis smoke test, checks every
shell script with `bash -n`, runs `lat check` when `lat` is installed, and,
when `dashboard/node_modules` exists, typechecks the [[dashboard]], checks the
translations and the e2e change map, and compares the committed `dashboard/dist`
with a fresh build: a difference fails on master and only warns on a feature
branch, because master rebuilds `dist` after each merge (see [[tooling#Parallel work]]).
`--changed` runs only what the branch touches, `--dry-run` shows the selection,
and stage times go to `test-results/timings.json`.
The OS-30 standard-library suite in [[linux-lab/tests/test_hardening.py]],
[[linux-lab/tests/test_harden_check.py]] and [[linux-lab/tests/test_rollback.py]]
also runs in stage 1, using fake commands and temporary files rather than live
security changes. `--quick` runs only the unit suites. The dormant workflow file
[[.github/workflows/mobile-sec-scan.yml]] is kept for reference but is disabled.

## Parallel work

Several agents and contributors work in separate worktrees at once. The tooling
keeps their runs isolated, small and conflict-free.

On 2026-11-16 three parallel sessions overloaded a laptop (Playwright started
one browser per core), tested each other's builds (every worktree used port
4322 and reused whatever server was there), killed each other's runs with
`pkill`, and conflicted on every rebase in `dashboard/dist` and the locale files.
[[docs/PLAN-parallel-agents.md]] records the plan; the fixes are below.

### Change detection

[[scripts/lib/changed-files.sh]] lists what a branch changes since its merge
base with `origin/master`, plus staged, unstaged and untracked files.

[[scripts/run-tests.sh]] `--changed` maps those paths to stages (a lab's own
suite, `cargo test` only for `qrust-scan`, `bash -n` only on changed scripts,
the dashboard stage for `dashboard/**`). Shared files such as `console/**` and
requirements files select everything. Inside a Python lab,
[[scripts/lib/py_affected_tests.py]] picks the test files whose imports reach a
changed module, and falls back to the whole suite when it cannot tell.
[[dashboard/e2e/affected.json]] maps dashboard paths to e2e specs, routes and
locales; [[dashboard/scripts/affected.mjs]] applies it, shared files get a smoke
set, and its test fails when a spec is missing from the map.

### E2e runs

[[scripts/e2e.sh]] runs the specs a change touches on a free port with two
browsers, behind a machine-wide lock.

The lock is a `mkdir` folder holding the owner's PID (macOS has no `flock`), and a
lock whose owner died is cleared. Tests serve their own build in
`dashboard/.e2e-dist`, rebuilt when a hash of the sources changes, so a run never
rewrites the committed `dist`. [[dashboard/playwright.config.ts]] reads every
setting from `OSLAB_E2E_*` variables, defaults to two workers and reuses a server
only with `OSLAB_E2E_REUSE=1`. `--crawl` runs [[dashboard/e2e/crawl.spec.ts]],
which saves a full-page PNG per route, locale and width plus an `index.html`.
`--no-lock` is refused with `--full` or `--crawl`.

### Shared caches

[[scripts/worktree.sh]] creates and removes worktrees with one shared copy of each
dependency, under `OSLAB_CACHE_ROOT` (default `~/.cache/os-lab`).

`dashboard/node_modules` links to an install keyed by the hash of
`package-lock.json`, and `.venv-test` to a virtualenv keyed by the requirements
files, so a branch that changes dependencies gets its own copy. npm, pip,
Playwright and sccache caches live under the same root
([[scripts/lib/cache-env.sh]]). Astro and Vite write their caches to the
per-worktree `dashboard/.vite-cache`, never into the shared `node_modules`.
`dist`, test output, lab `.env` files and `target/` folders are never shared.
`doctor` relinks after a rebase, `rm` deletes only the worktree's own output, and
`cache prune` asks before deleting unused entries.

### Merges and CI

The committed `dashboard/dist` is rebuilt on master, locale files merge by key,
and CI runs only what a pull request touches.

[[.github/workflows/dashboard-e2e.yml]] fails a pull request that changes
`dashboard/dist`, runs the typecheck, translations and tooling tests, and runs
the affected specs in shards with cached browsers (the whole suite on master).
[[.github/workflows/dashboard-dist.yml]] rebuilds `dist` after a merge and lands
it as a `build/dist-<sha>` pull request. [[scripts/lib/i18n-merge-driver.mjs]]
merges `src/i18n/generated/*.json` key by key, so two branches that both append
keys no longer conflict. Every workflow cancels superseded pull-request runs,
and the release workflows build installers on pull requests only when packaging
inputs change. [[scripts/hooks/pre-push]] runs the quick changed suites before a
push; `OSLAB_SKIP_PREPUSH=1` skips it.

## Tests

Android and Source Lab have independent automated test suites.

It lives in [[android-lab/lab/tests]] (analyzer, reporter, MobSF client, secret
scanner, patcher, flow parser, agentic engine, web UI, the host engine in
[[console/oslab.py]] and the [[tooling#Scope guard]]). Shell scripts across the
VM labs are kept `bash -n` clean and use `set -euo pipefail`.
The [[source-lab]] engine tests run in their own process from
[[source-lab/engine]] so their imports cannot collide with Android tests.

## Firewall rule renderer

[[firewall-lab/vm/scripts/render-rules.py]] turns a company's abstract rules into UFW
commands, an nftables ruleset or a vendor-neutral table, so the same ordered policy
can be loaded in the disposable firewall guest.

Port handling follows the declared rule exactly. A comma list becomes an nft
anonymous set (`dport { 22, 443 }`) and stays a UFW multiport list. `proto: any`
with a port means TCP or UDP to those ports (`meta l4proto { tcp, udp } th dport`
in nft, one tcp and one udp command in UFW), never all traffic. A port on `icmp`
is ignored by both backends. Items that are not ports or ascending ranges in
1–65535 (`esp`, `80,,443`, `500:400`) are skipped with a comment and a stderr
warning. Notes and names are flattened to one line before they go into comments.
[[.github/workflows/firewall-lab.yml]] renders every branch of every company and
checks the output with `nft -c` and `bash -n`, and rejects duplicate branch ids.

## Scope guard

[[console/scope_guard.py]] turns the authorization-only rule into code: a lab
tool names the target it is about to touch and is refused unless the declared
lab scope covers it.

A tool calls [[console/scope_guard.py#assert_in_scope]] with a kind (`host`,
`package`, `device` or `path`) and the target, and gets a decision naming the
manifest rule that allowed it, or a `ScopeError` whose message says why it was
refused. [[console/scope_guard.py#check]] returns the same decision without
raising. The module uses only the standard library, never resolves DNS and never
opens a connection, so a decision is the same offline and in tests.

### Manifest

The scope is a JSON file listing the hosts, app ids, device serials and folders
that may be tested, with who authorized it and an optional end date.

[[console/scope_guard.py#load_scope]] reads the `path` argument, then
`$OSLAB_SCOPE_FILE`, then `scope.json` in the checkout (git-ignored;
[[console/scope.example.json]] is the starting point). Validation is strict:
unknown fields, wrong types, a missing `authorization` text and more than 512
entries per list, a repeated field and a range with address bits beyond its
prefix (`10.25.130.14/24`) are errors, so a typo cannot silently widen or empty
a scope. The file must be a regular file and at most 256 KiB is read.
A scope must name its targets: `*`, `0.0.0.0/0`, `::/0`, `*.com` and `com.*` are
rejected. Address ranges must be loopback, private or link-local unless the
manifest sets `allowPublic`, which is the written-authorization case.

### Hosts

A host target may be an address, a name, `host:port` or a URL; only its host
part is matched, against addresses, CIDR ranges, exact names and `*.suffix`.

A wildcard covers subdomains at any depth but not the bare domain, and whole
top-level domains are accepted only for reserved lab names such as `.test` and
`.local`. An IPv4-mapped IPv6 address, in a rule or a target, is matched as its
IPv4 address. Targets that could hide another host are refused before matching:
user info and fragments in URLs are not the host, `inet_aton` spellings such as
`127.1` or `2130706433` are not names, and non-ASCII names must be written in
punycode. A `file:` URL is a path, not a host, and is refused. So is an address
with an interface zone (`fe80::1%eth0`), because rules carry no interface, and
square brackets around anything but one IPv6 address.
Names are matched as text, so a tool that connects by name should also check
the address it resolved.

### Apps and devices

App ids and device serials are case-sensitive and match exactly or by a
trailing wildcard: `com.vendor.*` for ids, `emulator-*` for serials.

An id wildcard matches whole dotted parts, so `com.oslab.*` covers
`com.oslab.demo` but not `com.oslabs.demo` or `com.oslab` itself. Anything that
is not a plain id or serial (spaces, shell characters, extra arguments) is
refused rather than matched.

### Paths

A path is in scope when its real location is inside a declared folder; relative
manifest folders start at the manifest, relative targets at the working directory.

Targets are resolved the way the operating system would open them, with links
followed, so `..`, a sibling folder that shares a name prefix and a link that
leaves the lab folder are all refused. A filesystem root cannot be declared.
The manifest is the operator's declaration, so it may also name an absolute or
`~` folder. A decision describes the path when it was checked: tools should open
the resolved path it returns, and lab folders should be writable only by the
operator, since the guard cannot prevent a later swap of a folder for a link.

### Refusal

The guard fails closed: no manifest, an unreadable or invalid manifest, an
expired scope, an unknown kind or a malformed target are refusals, never passes.

Each refusal states the target, the scope name and the declared rules of that
kind, so the operator can see whether the target or the manifest is wrong.
Control characters and leading or trailing whitespace are refused rather than
trimmed, because the tool would use the raw value. A scope is valid through its `expires` date and refuses
everything after it.

### Console and command line

The declared scope is visible without reading the file: `GET /api/scope` on the
local console and `python3 console/scope_guard.py show`.

[[console/oslab.py#scope_status]] reports whether a scope is declared and valid,
its name, authorization, expiry and rule counts; [[android-lab/lab/web_ui.py]]
serves it read-only. The command line checks one target and exits 0 in scope,
1 refused and 2 for a usage or manifest error, with `--json` for agents and
scripts. The tests are in [[android-lab/lab/tests/test_scope_guard.py]].

## Community and contribution

Contribution flow, coding conventions and the authorization stance.

They are in [[CONTRIBUTING.md]], step by step from setup to pull request, and
the [[dashboard]] renders the same file at `/contribute/`. Contributions must not
add vendor binaries or proprietary media (see [[legal#Google platform-tools]]).
The Source Lab migration is tracked in [[source-lab/README.md]], with its plan,
task queue and pinned source inventory. [[source-lab]] records the implemented
engine, console and file-backed dashboard workflows. Remaining native/live
verification and patches are open Source bonus tasks in [[CONTRIBUTING.md]].

Issue and PR templates are in
[[.github/ISSUE_TEMPLATE]] and [[.github/PULL_REQUEST_TEMPLATE.md]]; behavior
expectations in [[CODE_OF_CONDUCT.md]].

## Security and licensing

Private vulnerability reporting and the authorization-only scope.

These are defined in [[SECURITY.md]]; the project is Apache-2.0 ([[LICENSE]]).
The VM base images (`dockur/windows`, `qemux/qemu`, `dockurr/macos`) are MIT and
do not distribute OS media; users are responsible for valid licences.

[[dashboard/scripts/source-brain-model.test.mjs]] validates provider paths, graph
limits/windows and bounded revision diff without a browser.
[[source-lab/RUNBOOK.md]] records the portable release/rollback workflow.
