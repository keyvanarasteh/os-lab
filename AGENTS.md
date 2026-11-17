# Working in os-lab

[`lat.md/lat.md`](lat.md/lat.md) is the entry point to the project's main architecture and behavior documentation. Read the relevant nodes in [`lat.md/`](lat.md/) before changing a lab, the dashboard, installers, or shared tooling, and update them when behavior changes.

For dashboard work, follow [`docs/UX_READINESS.md`](docs/UX_READINESS.md) and [`lat.md/ux-readiness.md`](lat.md/ux-readiness.md). Keep actions tied to live readiness and available capabilities, label configured endpoints clearly, show operation errors, and verify both the local app and public Pages routes.

For new features, build types, stores, API calls, and plain usable pages/components before the visual design pass. Verify functional success and failure flows first; preserve existing working UX. Keep each Cleanup Lab task in its own PR.

Run the relevant checks for the area changed. Dashboard changes use `npm run check`, `npm run test:i18n`, `npm run build`, and `npm run test:e2e` from `dashboard/`; run `lat check` after editing the knowledge graph. See [`lat.md/tooling.md`](lat.md/tooling.md) for broader repository checks.

## Parallel agents

Several agents work on os-lab at once, each in its own worktree. These rules keep them from overloading the machine or breaking each other's runs ([plan](docs/PLAN-parallel-agents.md), [landing steps](CONTRIBUTING.md#landing-a-branch)).

- Start every worktree with `scripts/worktree.sh new <branch>`. It links the shared `node_modules`, test virtualenv and browser caches and configures the locale merge driver. Run `scripts/worktree.sh doctor` after a rebase that changed `package-lock.json` or a requirements file, and remove the worktree with `scripts/worktree.sh rm <branch>`.
- Run tests for what you changed: `scripts/run-tests.sh --changed` for the unit suites, `scripts/e2e.sh --changed` for e2e. Before any `scripts/e2e.sh` run, ask the user which mode to use: suggest one that fits the change and show its `--dry-run` output.
  - one view: `scripts/e2e.sh --changed`;
  - layout or styles: `--changed --crawl --widths desktop,phone`;
  - new or changed translations: `--changed --crawl --locales <changed locales>`;
  - shared shell or styling: `--changed` (it picks the smoke set) plus `--crawl`;
  - right before the PR, once: `--full`.
- Never start Playwright with more than two workers, never reuse another worktree's server, and never `pkill` or `killall` by name. Kill only PIDs you started. `scripts/e2e.sh` picks a free port and waits for a machine-wide lock.
- Do not commit `dashboard/dist`. CI refuses PRs that change it, and master rebuilds it after merge (`dashboard-dist` workflow).
- Rebase on `origin/master` at the start of each work phase, not only at the end. Only one agent lands work on master at a time, in the order the user chooses.
- Check `reservations/` and the remote branches before choosing a task ID.
- Run at most two or three heavy agents at once on a laptop.
