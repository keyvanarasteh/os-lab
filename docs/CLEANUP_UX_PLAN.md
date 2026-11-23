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

## Items (one PR each, in this order)

- [ ] **CUX-01 — Scan & review in one click.** The Clean card's primary button runs the scan, then builds the Trash plan for the recommended safe set and opens the confirmation, so scan → confirm is one click plus the confirmation. Cancel, failure and an empty result stay visible next to the button. Same code path serves the widget intent.
- [ ] **CUX-02 — Quick clean works with zero setup.** With no quick-clean bookmark the Quick clean button offers the recommended set (measured, safe, unprivileged) instead of being disabled, and says which set it will use. The widget's quick-clean button follows. Bookmarks still override.
- [ ] **CUX-03 — Advanced scan filter bar.** Search by name or path, risk and "measured only" filters, **Select visible / Deselect visible**, and a notice when selected entries are hidden by a filter. Full names on hover or wrap, no truncation of the only identifier.
- [ ] **CUX-04 — Row actions in view.** Scan, Clean, Bookmark, Reveal, Copy path and Exclude as one visible row menu (keyboard reachable); Reveal / Copy need console endpoints, Exclude reuses custom entries.
- [ ] **CUX-05 — Dashboard navigation and widget card.** Page row on the dashboard (as on the other pages), widget card open by default on macOS with a visible Add-widget step list and the real state of the publish, widget rows deep-link to the exact result.
- [ ] **CUX-06 — Keyboard and coarse-pointer pass.** Shortcuts for Scan, Clean, Select visible; 44 px targets; RTL and 200% zoom checks. Visual pass last.

## Gates for every item

- Types, API contract and error states first; plain page works before styling.
- Loading, empty, success, failure, retry, cancel and confirmation paths verified in the browser against the real console.
- `npm run check`, `npm run test:i18n`, `npm run build`, `scripts/e2e.sh --changed` (ask the user for the mode first), `lat check`, and a `lat.md/cleanup-lab.md` update when behavior changes.
- New UI copy added to all eight locale catalogs.
- Nothing deletes without the existing plan → confirm dialog; Trash stays the default.
