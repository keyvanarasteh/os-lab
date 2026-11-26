# Remaining work for the 0.4.9 release

A handoff plan, written when the session paused. Work through it in order; each step says how to
check it is done. Worktrees live under `/Volumes/Projects/iQ/os-lab-worktrees/`. Keep temporary
files off the system disk (`export TMPDIR=/Volumes/Projects/tmp/...`).

## Already merged

- #341 full-screen bento cleanup confirm dialog (+ short-screen and Trash-label review fixes)
- #343 CLS-01 simulator device cleanup (typed `simctl` actions, preview → confirm, audit)
- #344 CLS-02 simulator storage (saved disk, suggestion, monitor notification, setup report)
- #345 nav: one icon per lab page, Web Sec Lab in the OS Lab list and ⌘L switcher

## 1. CLS-03 simulator runtimes — PR #346 (critical)

- Branch `feat/cls-03-simulator-runtimes` was rebased on master after #344 (one `lat.md`
  conflict, both sections kept) and force-pushed with `--force-with-lease`.
- To do: check the push landed (`git ls-remote --heads origin feat/cls-03-simulator-runtimes`
  matches the worktree HEAD), wait for CI, resolve any Sourcery threads, merge.
- Not verified on a machine with downloaded runtimes: the code follows the documented
  `xcrun simctl runtime list -j` shape and is tested with a fake `simctl`. Before release, run it
  once on a Mac with a downloaded runtime (Advanced scan → Simulators → Runtimes).

## 2. Update center on every page — branch `feat/app-update-everywhere` (critical)

- Commit `729fe9b71`, pushed by a background push (check with `git ls-remote`). **No PR yet.**
- Open the PR (title: `feat(app): update center on every page; close for the installer when idle`),
  body from the commit message, wait for CI, merge.
- Contents: top-bar update button on every page, update center modal in the layout, streamed
  download with progress, `busy` work in `GET /api/app/update`, close-for-update flow
  (5 s countdown when idle, waits with progress while lab/Cleanup jobs run, Close now / Don't
  close), desktop app handles `oslab://app/quit-for-update` only from its own window and asks the
  console again (`console::may_quit_for_update`). The This computer panel is removed.
  Also fixes the flaky `test_app_update.py::test_install_downloads_verifies_and_opens` race.
- Do not commit `app/src-tauri/resources/os-lab`: it is a local symlink used to compile the Rust
  crate in the worktree.
- Manual check before release: in a real desktop build, install an update with a Cleanup scan
  running → the modal waits and lists it; when it ends the app quits; Close now quits at once.

## 3. MCP guides page under Help — branch `feat/mcp-guides-page` (this draft PR)

Not started beyond research. Facts gathered:

- One stdio server, `console/mcp_server.py` (`serverInfo.name` is `os-lab-macos`, or
  `os-lab-windows` on Windows), run with `python3 console/mcp_server.py` or
  `make -C ios-lab mac-mcp`. Standard library only.
- Tool groups: 19 `macos_*` (macOS only; input tools need the dashboard's armed control mode,
  submit-class actions need `confirm: true`, `macos_stop` is the panic stop, `macos_task` runs a
  bounded step list), 21 `cleanup_*` (`console/mcp_cleanup.py`; `cleanup_clean` needs
  `confirm: true`, Trash only), 21 `websec_*` (`console/mcp_websec.py`; scope guard, intrusive
  checks need `active` + `confirm`), 5 read-only `winapps_*` (Windows only, allowlist in
  `win-lab/winapps-policy.json`). Cleanup and Web Sec tools are refused inside `macos_task`.
- Existing docs to link: `lat.md/ios-lab.md` (MIR-12), `lat.md/cleanup-lab.md` (CUX-10),
  `lat.md/web-sec.md` (MCP tools), `lat.md/win-lab.md`, `web-sec/README.md`.

To build:

1. `dashboard/src/pages/mcp.astro` (+ the locale route like the other Help pages) and
   `dashboard/src/views/mcp-page.tsx`.
2. Sections as cards: what the server is; setup per client with copy buttons —
   Claude Code `claude mcp add os-lab-macos -- python3 <repo>/console/mcp_server.py`,
   Claude Desktop `mcpServers` JSON, generic stdio (`make -C ios-lab mac-mcp`) — filling `<repo>`
   from `GET /api/host` (`host.root`); one card per tool group with its tools (read from the module
   lists), platform and safety rules; troubleshooting (permissions, armed mode, scope file).
3. Help nav: add `{ id: "mcp", label: "MCP servers", icon: <PlugsIcon/> }` in `buildGroups`, a
   `sectionHref` case, Spotlight meta (aliases: mcp, agent, claude, tools).
4. Translations for every new string in all seven locales (`npm run test:i18n`).
5. e2e: the page renders the four groups and the setup snippet contains the mocked repo root.
6. `lat.md/dashboard.md` section; `lat check`.

## 4. Version bump and release (critical, after 1–3 are merged)

1. `scripts/worktree.sh new release/app-v0.4.9` from master.
2. Bump `0.4.8` → `0.4.9` in the same five files as the 0.4.8 release (commit `62cfd675b`):
   `app/package.json`, `app/package-lock.json` (two places), `app/src-tauri/Cargo.toml`,
   `app/src-tauri/Cargo.lock`, `app/src-tauri/tauri.conf.json`.
3. Commit `chore(app): release 0.4.9`, PR, CI, merge.
4. Tag master with an annotated tag and push it — the user approved this:
   `git tag -a app-v0.4.9 -m "os-lab app 0.4.9" <merge commit>` then
   `git push origin app-v0.4.9`. This starts `release-mac/linux/win` and the updater manifest.
5. Watch the release workflows; confirm the `app-v0.4.9` release and `app-updates/latest.json`.

## 5. Cleanup

- `scripts/worktree.sh rm <branch>` for each merged branch: `fix/cleanup-review-modal-ux`,
  `feat/cls-01-simulator-cleanup`, `feat/cls-02-simulator-storage`,
  `feat/cls-03-simulator-runtimes`, `fix/nav-icons-websec-switcher`, `feat/app-update-everywhere`,
  `feat/mcp-guides-page`, the release branch.
- Full e2e (`scripts/e2e.sh --full`) was not run locally for any of these PRs; CI's browser jobs
  are the full-suite check.
