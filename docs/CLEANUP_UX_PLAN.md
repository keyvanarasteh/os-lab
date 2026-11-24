# Cleanup Lab UX plan — one-click paths (CUX)

Why: the Cleanup Lab dashboard and its macOS widget are hard to use with one click, or with a few, across the features they offer. This plan compares them with [PureMac](https://github.com/momenbasel/PureMac) (MIT, SwiftUI; read at its `master`, files in `PureMac/Views` and `PureMac/Services`) and lists one PR per item. Rules: [UX readiness](UX_READINESS.md), one Cleanup Lab task per PR, behavior before visual design.

Findings below come from reading the code and from screenshots of `/cleanup/`, `/cleanup/scan/` and `/cleanup/settings/` on the local dev stack (macOS, 2026-11-24, no scan run yet).

## What PureMac does that we do not

| PureMac | os-lab today |
|---|---|
| One "Review cleanup" button scans everything, then lists categories with "N of M selected" and a **Clean selected** action. | Two competing cards: **Quick clean** (disabled until a bookmark is flagged) and **Clean** (Scan now → review plan → Clean → Run clean). A new user has no working one-click action. |
| Category detail has a search box, size / age / sort pickers and **Select visible**, and says when filters hide selected items. | **Advanced scan** is a grid of 100+ small cards with truncated names and "Not measured". No search, no filter, no select-visible. Defaults / All / None only. |
| Every row has Reveal, Copy path, Exclude from cleanup in one menu. | Row actions sit behind a `…` menu or right-click; no reveal / copy path / exclude. |
| Menu-bar popover with live monitor and a way back into the app; the app has a Back control and sidebar. | Widget shows status only; its quick-clean button is dead until a bookmark is flagged. Dashboard has no page row, only a "Settings" link and the sidebar. |
| Honest copy: no fake urgency, purgeable space explained. | Already honest; keep it. |

## Items (all landed together in PR #325 at the owner's request)

- [x] **CUX-01 — Scan & review in one click** (shortcut `S`): scan, server-side suggestion, Trash plan, confirmation dialog.
- [x] **CUX-02 — Quick clean works with zero setup**: no bookmark flagged means it runs Scan & review on the suggested set; the widget intent follows.
- [x] **CUX-03 — Advanced scan filter bar**: search, risk filter, measured only, Select visible / Deselect visible, hidden-selection notice, wrapped names.
- [x] **CUX-04 — Row actions**: Reveal in file manager (typed endpoint) and Copy path in the row menu; "never suggest" lives in Suggestions.
- [x] **CUX-05 — Dashboard navigation and widget card**: one list of collapsed rows (Suggestions, Quick clean, Alerts, All tools); the widget preview opens by default when publishing works.
- [x] **CUX-06 — Keyboard**: `S` starts Scan & review; focus order and coarse-pointer targets reuse the shared buttons.
- [x] **CUX-07 — Monitor alerts**: critical level, reminders, desktop notification, store kept across versions.
- [x] **CUX-08 — Suggestions and preferences**: pressure-aware auto mode, stored customisation (include, exclude, minimum size, free-space target).
- [x] **CUX-09 — Compact dashboard**: one primary action plus collapsed rows with live summaries.
- [x] **CUX-10 — MCP tools** for every function above.

Visual pass (2026-11-24, real console, 390 px phone, Arabic right-to-left, 200% text): no horizontal overflow in any of them and every row opens; the row summaries were English-only in Arabic and are now translatable fragments.

Still open, stated honestly: "Exclude from cleanup" as a catalog-level action beyond the suggestion "never" list; the report-only inventories (containers, VMs, packages, projects, simulators, leftovers) are a link from All tools, not an automatic run, because each needs its own preview.

## Coverage: every ability, and how it is reached

| Ability | One click | Where the settings live |
|---|---|---|
| Measure and clean safe caches | Scan & review (`S`) | Suggestions row |
| Quick clean bookmarks | Quick clean row, or the widget | Bookmarks (Settings) |
| Suggestions and free-space target | Suggestions row | same row, stored on this computer |
| Low-space alerts and notifications | Alerts row, Turn on alerts | Background monitor (Settings): interval, remind, notify, critical level |
| Individual items, filters, per-item actions | All tools → Advanced scan | filter bar and row menu |
| Space Explorer, Results, Leftovers, History | All tools | none needed |
| Containers, VMs, packages, projects, simulators | All tools → Advanced scan | preview before any action |
| Relocation, privileged actions | All tools | preview and confirmation by design |
| Permissions, widgets | All tools, or Alerts | Settings |
| Agents | MCP `cleanup_review`, then `cleanup_clean` with `confirm: true` | same stored preferences |

## Gates for every item

- Types, API contract and error states first; plain page works before styling.
- Loading, empty, success, failure, retry, cancel and confirmation paths verified in the browser against the real console.
- `npm run check`, `npm run test:i18n`, `npm run build`, `scripts/e2e.sh --changed` (ask the user for the mode first), `lat check`, and a `lat.md/cleanup-lab.md` update when behavior changes.
- New UI copy added to all eight locale catalogs.
- Nothing deletes without the existing plan → confirm dialog; Trash stays the default.
