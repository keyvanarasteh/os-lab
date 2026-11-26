# Remaining work for the 0.4.9 release

Handoff written 2026-11-26 after the previous session hit its token limit.
Work through it in order. Each step says how to check it is done.

Worktrees live under `/Volumes/Projects/iQ/os-lab-worktrees/`. Keep temporary
files off the system disk (`export TMPDIR=/Volumes/Projects/tmp/os-lab`).
Start every new worktree with `scripts/worktree.sh new <branch>`. Land one
branch at a time (`CONTRIBUTING.md` landing steps). Merge with
`gh pr merge <N> --merge --delete-branch` only after CI is green.

This document is the body of **draft PR #350** (label: `critical`).
https://github.com/keyvanarasteh/os-lab/pull/350

## Snapshot (2026-11-26, after this handoff)

| Item | State |
|---|---|
| #341 full-screen bento confirm | Merged |
| #343 CLS-01 simulator devices | Merged |
| #344 CLS-02 simulator storage | Merged |
| #345 nav icons + Web Sec in lab list | Merged (review: unguarded `setJobs` on poll + catalog fallback) |
| #346 CLS-03 simulator runtimes | Open, rebased onto `origin/master` (`1f835c56f`). **Do not merge until CI is green and Sourcery High threads are triaged.** |
| Update center (`feat/app-update-everywhere`) | Rebased onto `origin/master` (`ecadbb584`). Open the PR if it is not open yet, wait for CI, merge. |
| MCP guides page (this branch) | Research only. Build it here. |
| Version bump 0.4.8 → 0.4.9 | Not started. After 1–3 merge. |
| Tag `app-v0.4.9` | Already approved. Push only after the bump is on master. |

Master at handoff: `1eef927b5` (includes dist regen #349).

## Already merged

- #341 full-screen bento cleanup confirm dialog (+ short-screen and Trash-label review fixes)
- #343 CLS-01 simulator device cleanup (typed `simctl` actions, preview → confirm, audit)
- #344 CLS-02 simulator storage (saved disk, suggestion, monitor notification, setup report)
- #345 nav: one icon per lab page, Web Sec Lab in the OS Lab list and ⌘L switcher
- dist regen PRs #342, #347, #348, #349

## 1. CLS-03 simulator runtimes — PR #346 (critical)

https://github.com/keyvanarasteh/os-lab/pull/346

- Branch `feat/cls-03-simulator-runtimes`, worktree
  `/Volumes/Projects/iQ/os-lab-worktrees/feat-cls-03-simulator-runtimes`.
- Rebased onto `origin/master` after #344/#345/#349. Expected HEAD after the
  force-push: `1f835c56f`. Confirm with
  `git ls-remote --heads origin feat/cls-03-simulator-runtimes`.
- What it does: `simctl runtime list -j` inventory; `simulators.delete-runtime`
  takes exactly one UUID, refuses Xcode-managed (`deletable: false`) runtimes
  and runtimes a booted device uses; dashboard Runtimes list with Delete →
  preview → Confirm.

### Before merge

1. Wait for GitHub CI on the rebased commit (unit, dashboard-e2e, release-*).
2. Triage Sourcery threads. **High** ones to confirm against real
   `xcrun simctl runtime list -j` output (the code treats the JSON as a
   UUID-keyed object of runtime records, and IDs as UUIDs):
   - Runtime deletion skips safety check if device inventory is unavailable
     (`_preview_runtime` treats empty `devices` as “no users”).
   - Booted runtime users go undetected if the record has `identifier` but no
     `runtimeIdentifier` (usage match uses `runtime["runtime"]`).
   - Downloaded runtimes disappear if Apple returns a top-level `runtimes`
     array instead of a UUID-keyed map.
   - Valid runtime IDs are rejected if Apple uses
     `com.apple.CoreSimulator.SimRuntime.*` instead of UUIDs.
3. Medium (do or reply, do not silently ignore):
   - Runtime list depends on device listing in `console/cleanup_api.py`.
   - History labels a runtime deletion as “1 simulator”.
   - Test only covers one matching device for `devicesUsing`.
   - New UI strings hard-coded English (check whether they already go through i18n).
   - MCP tools for runtimes are out of scope for this PR (the MCP page is §3).
   - “Persist audit intent before delete” is a wider engine change; reply if
     the existing preview+digest+history path is the project rule.
4. Manual check before release: on a Mac with a downloaded runtime,
   Advanced scan → Simulators → Runtimes → Delete → Confirm.

Merge: `gh pr merge 346 --merge --delete-branch`. Then
`scripts/worktree.sh rm feat/cls-03-simulator-runtimes`.

## 2. Update center on every page — `feat/app-update-everywhere` (critical)

Worktree: `/Volumes/Projects/iQ/os-lab-worktrees/feat-app-update-everywhere`.
Commit after rebase onto master: `ecadbb584`.

If the PR is not open yet:

```bash
cd /Volumes/Projects/iQ/os-lab-worktrees/feat-app-update-everywhere
git push --force-with-lease origin feat/app-update-everywhere
# do not add app/src-tauri/resources/os-lab (local compile symlink)
gh pr create --base master --head feat/app-update-everywhere \
  --title "feat(app): update center on every page; close for the installer when idle" \
  --body-file -   # use the commit message
```

Contents:

- Top-bar update button on every page; update center modal in the layout.
- Streamed download with `received`/`total` progress.
- `GET /api/app/update` adds `busy` (running lab jobs and Cleanup jobs).
- After the installer opens: 5 s countdown when idle, or wait with progress
  while work is running; Close now / Don't close.
- Desktop app handles `oslab://app/quit-for-update` only from its own window
  and asks the console again (`console::may_quit_for_update`).
- This computer panel removed.
- Flaky `test_app_update.py::test_install_downloads_verifies_and_opens` race fixed.

`lat.md/dashboard.md` on this branch keeps **both** “Lab navigation icons”
(from #345) and “App updates”.

Local unit / Rust / e2e passed in the previous session. The desktop-app quit
path has a unit test; it has **not** been run end-to-end in a real app build.

Manual check before release: in a real desktop build, start a Cleanup scan,
install an update → the modal waits and lists the work; when it ends the app
quits; Close now quits at once.

Merge after CI: `gh pr merge <N> --merge --delete-branch`. Then
`scripts/worktree.sh rm feat/app-update-everywhere` (the untracked
`resources/os-lab` symlink goes away with the worktree).

## 3. MCP guides page under Help — this draft PR (critical)

Branch `feat/mcp-guides-page`, worktree
`/Volumes/Projects/iQ/os-lab-worktrees/feat-mcp-guides-page`.
Nothing is written yet except this plan. Rebase onto `origin/master` (and onto
#346 / the update PR if they landed) before building.

### Inventory (already gathered)

- One stdio server: `console/mcp_server.py`.
  `serverInfo.name` is `os-lab-macos`, or `os-lab-windows` on Windows.
  Start with `python3 console/mcp_server.py` or `make -C ios-lab mac-mcp`.
  Standard library only. 66 tools in four groups:
  - 19 `macos_*` (macOS only; input tools need the dashboard's armed control
    mode; submit-class actions need `confirm: true`; `macos_stop` is the panic
    stop; `macos_task` runs a bounded step list).
  - 21 `cleanup_*` (`console/mcp_cleanup.py`; `cleanup_clean` needs
    `confirm: true`, Trash only).
  - 21 `websec_*` (`console/mcp_websec.py`; scope guard; intrusive checks need
    `active` + `confirm`).
  - 5 read-only `winapps_*` (Windows only, allowlist in
    `win-lab/winapps-policy.json`).
- Cleanup and Web Sec tools are refused inside `macos_task`.
- Docs to link: `lat.md/ios-lab.md` (MIR-12), `lat.md/cleanup-lab.md` (CUX-10),
  `lat.md/web-sec.md`, `lat.md/win-lab.md`, `web-sec/README.md`.

### Build

1. `dashboard/src/pages/mcp.astro` (+ the locale route like the other Help
   pages) and `dashboard/src/views/mcp-page.tsx`.
2. Sections as cards:
   - what the server is;
   - setup per client with copy buttons, filling `<repo>` from `GET /api/host`
     (`host.root`):
     - Claude Code: `claude mcp add os-lab-macos -- python3 <repo>/console/mcp_server.py`
     - Claude Desktop `mcpServers` JSON
     - generic stdio (`make -C ios-lab mac-mcp`);
   - one card per tool group with its tools (read from the module lists),
     platform and safety rules;
   - troubleshooting (permissions, armed mode, scope file).
3. Help nav: `{ id: "mcp", label: "MCP servers", icon: <PlugsIcon/> }` in
   `buildGroups`, a `sectionHref` case, Spotlight meta (aliases: mcp, agent,
   claude, tools).
4. Translations for every new string in all seven locales (`npm run test:i18n`).
5. e2e: the page renders the four groups and the setup snippet contains the
   mocked repo root. Before `scripts/e2e.sh`, ask which mode; suggest
   `scripts/e2e.sh --changed` and show `--dry-run`.
6. `lat.md/dashboard.md` section; `lat check`.
7. Convert this PR from draft to ready, wait for CI, merge.

Follow `docs/UX_READINESS.md` / `lat.md/ux-readiness.md`. Keep actions tied to
live readiness. Do not commit `dashboard/dist`.

## 4. Version bump and release (critical, after 1–3 are merged)

1. `scripts/worktree.sh new release/app-v0.4.9` from master.
2. Bump `0.4.8` → `0.4.9` in the same five files as commit `62cfd675b`:
   `app/package.json`, `app/package-lock.json` (two places),
   `app/src-tauri/Cargo.toml`, `app/src-tauri/Cargo.lock`,
   `app/src-tauri/tauri.conf.json`.
3. Commit `chore(app): release 0.4.9`, PR, CI, merge.
4. Tag master with an annotated tag and push it — **already approved**:
   `git tag -a app-v0.4.9 -m "os-lab app 0.4.9" <merge commit>`
   then `git push origin app-v0.4.9`.
   This starts `release-mac` / `release-linux` / `release-win` and the updater
   manifest.
5. Watch the workflows; confirm the `app-v0.4.9` GitHub release and
   `app-updates/latest.json`.

## 5. Cleanup

`scripts/worktree.sh rm <branch>` for each merged branch. At handoff these
release worktrees still exist under `/Volumes/Projects/iQ/os-lab-worktrees/`:

- `fix/cleanup-review-modal-ux` (#341, merged — safe to remove now)
- `feat/cls-01-simulator-cleanup` (#343, merged — safe to remove now)
- `feat/cls-02-simulator-storage` (#344, merged — safe to remove now)
- `fix/nav-icons-websec-switcher` (#345, merged — safe to remove now)
- `feat/cls-03-simulator-runtimes` (after #346 merges)
- `feat/app-update-everywhere` (after its PR merges; includes untracked
  `app/src-tauri/resources/os-lab` symlink)
- `feat/mcp-guides-page` (after #350 merges)
- the 0.4.9 release worktree

Leave unrelated worktrees (`docs-websec-domain-portfolio-plan`,
`feat-mcp-dev-mode`, `feat-cleanup-ux-one-click-plan`, `.worktrees/*`).

Full e2e (`scripts/e2e.sh --full`) was not run locally for these PRs; CI
browser jobs are the full-suite check.

## Continue prompt (paste when the next session starts)

```
Continue 0.4.9 from draft PR #350 (critical).
Plan: docs/PLAN-release-0.4.9-remaining.md
1. If #346 CI is green and Sourcery High threads are triaged, merge it.
2. If the update-center PR is open and green, merge it; if not open, push
   feat/app-update-everywhere and open it.
3. Build the MCP guides page on feat/mcp-guides-page (this PR), then merge.
4. Version bump 0.4.8 → 0.4.9, merge, push annotated tag app-v0.4.9
   (already approved).
5. Remove finished worktrees with scripts/worktree.sh rm.
TMPDIR=/Volumes/Projects/tmp/os-lab. Do not commit dashboard/dist.
```
