# Development workflow

How a dashboard or Cleanup Lab change is run, watched and proven locally: a two-mode dev stack, a reusable browser check library and the habits that kept parallel agents from breaking each other.

Everything here lives in [[scripts/ux/dev-stack.sh]], [[scripts/ux/run.mjs]] and [[scripts/ux/lib/ux.mjs]]. Output goes to `test-results/`, which is git-ignored and per worktree.

## Dev stack

One script starts the console API and the dashboard in either of two modes and records only the server PIDs it started.

| Mode | Command | Serves | Hot reload |
|---|---|---|---|
| dev | `scripts/ux/dev-stack.sh dev` | console `:5050` plus Astro dev `:4321` (proxies `/api` to the console) | yes, edit `src/` and the browser updates |
| run | `scripts/ux/dev-stack.sh run` | `npm run build:local` into `dashboard/build`, then the console alone on `:5050` | no, rebuild after each change |

Open `http://localhost:4321` for dev and `http://127.0.0.1:5050` for run. `build:local` writes the git-ignored `dashboard/build`, which the console prefers when it is newer than the committed `dashboard/dist`; never commit `dist` (CI refuses it, see [[tooling#Parallel work]]).

The desktop window is a third mode: `cd app && npm run dev` runs `tauri dev`, which starts its own console on a free port and shows the built dashboard (`dashboard/build` when newer than `dist`), not the Astro dev server, so it has Rust rebuilds but no dashboard hot reload. It compiles Rust and is the heaviest, so use it only for work that needs the native app, such as the widget actions in [[cleanup-lab#Cleaner Widgets (CLW)]].

`OSLAB_API_PORT` and `OSLAB_UI_PORT` run a second stack beside the first; PID and log files are named per port. `astro dev` allows one server per project, so a second `dev` only reports where the first runs and the script adopts it. A server found on the port that this script did not start is used but never stopped, and `stop [console|dashboard|all]` kills only recorded PIDs, never by process name.

## Monitoring

Status, health probes and logs are one command each, and a few system numbers decide whether a heavy run is safe.

`scripts/ux/dev-stack.sh status` prints each port, its HTTP code, whether the PID is this script's and the real listener (`lsof`); its exit code is non-zero when the console does not answer. `logs [console|dashboard]` tails the per-port log under `test-results/dev-stack`. Health is `curl http://127.0.0.1:5050/api/health`.

Before a build or a Tauri run, check `sysctl vm.swapusage` (above about 2 GB means close heavy apps) and `df -h /System/Volumes/Data` (keep 20 % free). Two to three heavy agents at most, per [[tooling#Parallel work]].

Restart the console after changing `cleanup-lab/engine/` or `console/`: Python imports those modules once, so a new catalog file can disagree with an old allowlist and the page shows "The detector catalog is invalid". `dev-stack.sh restart-console` does it.

## UX check library

`scripts/ux/lib/ux.mjs` wraps Playwright for any UX test: one headless Chromium, named checks, screenshots and an exit code.

It loads Playwright from `dashboard/node_modules` (override with `OSLAB_PLAYWRIGHT`) and the shared browser cache under `OSLAB_CACHE_ROOT`. Exports:

- `loadPlaywright()` resolves the module and sets `PLAYWRIGHT_BROWSERS_PATH`.
- `boxInViewport(box, viewport)` is true when a bounding box is fully on screen.
- `CheckLog` records `ok(name, pass, info)`, with `failed`, `summary()` and `toJSON()`.
- `UxSession.open({ base, out, viewport, headless })` starts a session. Instance methods: `goto(route, { waitFor, settle })`, `check(name, pass, info)`, `visible(locator)`, `inViewport(locator)`, `setViewport(w, h)`, `scrollToBottom()`, `columnsInRow(selector)`, `requestsTo(fragment)` (non-GET calls with bodies), `consoleErrors(ignore)`, `shot(name, { locator, fullPage })` and `close()`.

`close()` writes `<out>/report.json` (checks, screenshot paths, errors) and returns 0 only when every check passed.

```js
const ux = await UxSession.open({ base: "http://localhost:4321" });
await ux.goto("/cleanup/scan/", { waitFor: "text=User caches" });
ux.check("one scan button", (await ux.page.getByRole("button", { name: "Scan selected" }).count()) === 1);
await ux.shot("scan");
process.exit(await ux.close());
```

## UX suites

Suites are small modules in `scripts/ux/suites/` that export `name` and `run(ux)`; [[scripts/ux/run.mjs]] runs one or all of them.

`node scripts/ux/run.mjs --list` lists them; `--suite shell,cleanup`, `--base <url>`, `--out <dir>` and `--headed` choose what to run. It exits 2 when nothing answers at the base URL.

- `shell` ([[scripts/ux/suites/shell.mjs]]) checks the collapsible Help group, its remembered state, the lab switcher, Firewall Lab as a lab, the focused-lab navigation and the Cleanup Lab sub-navs (Settings last, groups closed, a link lands on its card).
- `cleanup` ([[scripts/ux/suites/cleanup.mjs]]) checks the grouped volume cards, the sticky Advanced scan toolbar at desktop and phone width, the compact grid, the per-entry context menu and that Review & clean only builds a plan.
- `catalogs` ([[scripts/ux/suites/catalogs.mjs]]) runs a real scan and checks the Scanning/Scan complete card (with the category name), the classified plan rows, a catalog group page with its Size and Modified filters, the sidebar group icons and size badges, the permission guide, Review removal opening the confirmation dialog, and that no clean is requested. It takes a few minutes.

A new suite is one file; use the exact visible text a user sees, wait for hydration with `goto(..., { waitFor })`, and check network side effects with `requestsTo`.

## Screenshots

Screenshots are taken by the same session, numbered in order and saved as PNGs next to a JSON report.

`ux.shot("name")` writes `<out>/shots/NN-name.png`; a locator crops to that element (the storage card, a dialog). `run.mjs` gives each suite its own folder under `test-results/ux/<suite>/`. Read the PNGs to judge layout, because a passing selector does not prove the page looks right: a first run reported all-green while the volume cards had not merged, and only the screenshot showed it.

The older [[scripts/capture-dashboard-screenshots.sh]] still makes the marketing images under `docs/media`; it uses system Chrome and is separate from these checks.

## Proving a change

A change is done when typecheck, translations, graph and a real browser run agree, and what was not run is stated.

1. `cd dashboard && npm run check && npm run test:i18n`; new visible strings need all seven locales.
2. Engine changes: `python3 -m unittest discover -s tests -t .` in `cleanup-lab/engine`.
3. `lat check`; `lat.md/tooling.md` has one older too-long paragraph that is not from this work.
4. `scripts/ux/dev-stack.sh dev`, then `node scripts/ux/run.mjs` and look at the screenshots.
5. Run mode (`run`) for anything that must work from the built app; the Playwright suite (`scripts/e2e.sh`) is a separate, heavier step; ask the user before running it.

Parallel agents each take a task with disjoint files, run the same checks without e2e, and report files changed, checks and what is left; the lead re-runs the browser suite because agents cannot see the page.
