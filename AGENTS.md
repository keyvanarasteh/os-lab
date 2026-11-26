# Working in os-lab

[`lat.md/lat.md`](lat.md/lat.md) is the entry point to the project's main architecture and behavior documentation. Read the relevant nodes in [`lat.md/`](lat.md/) before changing a lab, the dashboard, installers, or shared tooling, and update them when behavior changes.

For dashboard work, follow [`docs/UX_READINESS.md`](docs/UX_READINESS.md) and [`lat.md/ux-readiness.md`](lat.md/ux-readiness.md). Keep actions tied to live readiness and available capabilities, label configured endpoints clearly, show operation errors, and verify both the local app and public Pages routes.

For new features, build types, stores, API calls, and plain usable pages/components before the visual design pass. Verify functional success and failure flows first; preserve existing working UX. Keep each Cleanup Lab task in its own PR.

Run the relevant checks for the area changed. Dashboard changes use `npm run check`, `npm run test:i18n`, `npm run build`, and `npm run test:e2e` from `dashboard/`; run `lat check` after editing the knowledge graph. See [`lat.md/tooling.md`](lat.md/tooling.md) for broader repository checks.

## Dashboard CI traps

These failed master e2e (and release follow-up) after 0.4.9 and will fail the next page, spec, or mock the same way. Details live in [`lat.md/dashboard.md`](lat.md/dashboard.md), [`lat.md/ux-readiness.md`](lat.md/ux-readiness.md) and [`lat.md/tooling.md`](lat.md/tooling.md).

- TopBar and PageHead both render the page title as `h1`. Scope Playwright headings to `main`, or use `.first()`.
- After a successful clean the confirm dialog stays open with a report, so it has two Close controls: the header `aria-label="Close"` icon and the footer `Close` button. Scope to `dialog.locator("footer")`.
- A focused lab replaces the OS Lab sidebar group with that lab's items. Cleanup focus lists Dashboard, Space Explorer, and the other `cleanupNavItems()` leaves — there is no button named "Cleanup Lab". iOS focus is one "iOS Lab" button. The Switch lab footer unmounts while the sidebar is collapsed.
- `client:only` islands unmount on a throw (Playwright screenshot is a white page). Guard `.map` / `.length` on API fields (`reasons ?? []`, `activeWarnings?.length`). An e2e `mockApi` catch-all of `{ logs: [] }` must stub every `/api/<lab>/` path the island fetches; copy the Cleanup stubs in `dashboard/e2e/lab-switcher.spec.ts`.
- A new spec file belongs in `dashboard/e2e/affected.json` or the map test fails.
- Keep translation ids that contain paths, filenames, or dotted identifiers in a JS/TS module. The i18n scanner requires every locale to keep those tokens.
- The first paragraph of each `lat.md/` node stays under 250 characters (`lat check`).
- Local `tsc` can fail on Vite `ImportMeta.env`, `import.meta.glob`, and `?raw` while the GitHub `dashboard-e2e` typecheck job passes. Use GitHub as the merge gate. `OSLAB_SKIP_PREPUSH=1` skips the hook when that local failure is the only block.
- Merge with `gh pr merge --merge --delete-branch` from a checkout that is not the worktree still using the branch, then `scripts/worktree.sh rm`.
- A tag or GitHub Release created with `GITHUB_TOKEN` does not start other workflows. After `app-v*` installers exist, dispatch `gh workflow run updater-manifest.yml -f version=…` ([`app/RELEASE_CI.md`](app/RELEASE_CI.md)).

## Parallel agents

Several agents work on os-lab at once, each in its own worktree. These rules keep them from overloading the machine or breaking each other's runs ([plan](docs/PLAN-parallel-agents.md), [landing steps](CONTRIBUTING.md#landing-a-branch)).

- Label every draft with one activity label (`ACTIVE` while working, `ON-HOLD` when parked) and one priority (`CRITICAL`, `PRIORITY-LEVEL-HIGH`, `MID`, or `LOW`). See [docs/plans/pr-labels.md](docs/plans/pr-labels.md).
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
