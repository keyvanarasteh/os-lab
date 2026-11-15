# Cleaner Widgets — plan (draft PR)

Planning document for the `feat/cleaner-widgets` workstream on the Cleanup Lab.
Tasks are appended here (and to the PR body) as the maintainer dictates them;
**no implementation starts until they say so.** Each task lands as its own
commit on this branch once approved; a task that outgrows the branch splits
into a stacked PR per the "each Cleanup Lab task in its own PR" rule.

Task series: `CLW-01…` (Cleaner Lab Widgets). New ids join the dashboard
Contribute → Roadmap page at implementation time with the seven-locale
translations.

Goal: port QleanerPro's **Widgets** feature (macOS desktop / Notification
Center widgets) to the os-lab desktop app, surfacing **every Cleaner Lab
capability** in the QleanerPro widget style — glanceable storage, scan status,
reclaimable totals, monitor warnings, bookmark quick-clean, permission state —
with the same interaction model (deep links into the dashboard + an
app-consumed "act now" request from a widget button).

Reference material: https://github.com/keyvanarasteh/QleanerPro (cloned to a
temp folder while planning; only *architecture and layout* are ported —
QleanerPro's colours, brand, identifiers and code stay behind).

---

## Reference architecture (grounded in the QleanerPro source)

- **Snapshot data contract** — `Sources/QleanerProWidgetKit/WidgetSnapshot.swift`:
  one `Codable` struct (`capturedAt`, sign-in state, disk total/available,
  last-scan target count + bytes, total reclaimed bytes + last cleanup,
  `isScanning` / `isCleaning`, highest risk, scan progress n/m, schedule
  enabled + frequency + next occurrence) with derived helpers (`usedBytes`,
  `usedPercent`, `statusLabel` = Cleaning → Scanning → Ready to clean → Up to
  date) and `placeholder` / `empty` fixtures.
- **Transport** — `WidgetConfig.swift`: a shared **App Group** container
  (`group.tech.qline.qleanerpro`) holding `widget-snapshot.json` (atomic
  write, ISO-8601 dates) and `widget-pending-scan-request.txt` (timestamp file
  for app-consumed actions). Host writes + calls `WidgetCenter.shared
  .reloadAllTimelines()` in `AppViewModel.publishWidgetSnapshot()` after every
  scan / refresh / history / schedule change; the widget's `SnapshotProvider`
  re-reads the file per timeline build with a `.after(15 min)` refresh policy.
- **Actions** — `ScanNowIntent` (AppIntents, `openAppWhenRun`) writes the
  pending-request file; the app consumes it **once on foreground** with a
  120-second max-age so a stale request can never re-trigger. Widgets carry
  `widgetURL` deep links (`qleanerpro://scan|review|history|settings`).
- **Widgets** — `QleanerProWidget/`: `QleanerProStatusWidget`
  (`systemSmall` / `systemMedium` / `systemLarge`) plus an iOS-only accessory
  widget behind `#if os(iOS)`. Layouts live in `WidgetContentViews.swift`:
  header row (glyph + name + status dot), status label, metric tiles (Found /
  Reclaimable / Disk free / Total reclaimed), scan progress capsule bar,
  disk-used gauge, relative-time rows (last scan, last cleanup, next
  scheduled), Scan-Now capsule button.
- **Palette** — `WidgetPalette.swift` mirrors the app's design tokens by hand
  (separate module can't import the app's DesignSystem): bg / fg / primary /
  card / border / mutedFg / danger / warning / success, light + dark, with a
  `riskTint` map (high → danger, medium → warning, low → success).

## How os-lab maps onto it (grounded in this repo)

| QleanerPro concept | os-lab equivalent |
| --- | --- |
| Native SwiftUI app | Tauri app (`app/`, identifier `com.keyvanarasteh.oslab`, min macOS 12.0, console runs in-process on a free loopback port, UI = committed dashboard build) |
| `WidgetSnapshot` fields | Engine/console data that already exists: volumes inventory (`totalBytes`/`freeBytes`/`purgeableBytes`), latest scan job (plan totals, unreadable, progress), history (`reclaimedBytes`, last run), monitor store (config, events, next check), bookmarks (`quickClean` flags, size alerts), permissions report (FDA granted) |
| Schedule fields | The **background monitor** is the schedule analog (interval 60–3600 s + next check); no scheduled scans exist — the widget shows "Monitor: every N min" or "Monitor off" |
| Scan-Now intent | **Quick clean** of `quickClean`-flagged bookmarks (Trash-only, automated=True) through the existing bookmark quick-clean endpoint |
| Deep links | Dashboard island router paths (`scan/`, `results/`, `history/`, `space/`, `cleanup-bookmarks`, `cleanup-monitor`) via an `oslab://` scheme |
| QPColors token mirror | Mirror of the dashboard's iux token hexes + `#f36c21` accent in a Swift palette file |
| QP widget bundle | New `app/widget/` Swift targets embedded as `Contents/PlugIns/*.appex` |

## Design rules (README safety rules + architecture contract, unchanged)

1. **No new authority** — widgets display state and open the app; the only
   action a widget can trigger is the quick clean of `quickClean`-flagged
   bookmarks, which is already user-preauthorized and Trash-only. The widget
   never invents paths, plans or commands; it speaks the same typed console
   API (unknown keys → 400, missing engine → 501).
2. **Read-only snapshot** — the widget snapshot builder folds existing engine
   modules (volumes, jobs, history, monitor, bookmarks, permissions); it adds
   no state writes and no scans on its own.
3. **No free-form paths anywhere** — the snapshot contains counts, byte
   totals, ids and statuses; no absolute paths beyond the mount point strings
   the volumes endpoint already exposes.
4. **Typed transport only** — one JSON schema versioned in code, atomic
   writes, corrupt/missing file → `empty` placeholder, never a crash.
5. **Honest availability** — widget support is a capability like every other:
   readiness surfaces it (macOS + extension bundled), other platforms render
   the dashboard section with the honest "not available here" note, and the
   widget never blocks readiness.

---

## Task 1 — Snapshot contract + console surface (CLW-01, CLW-02)

**CLW-01 Widget snapshot builder (engine).** New
`cleanup_lab/widget.py`: `snapshot()` folds `volumes.inventory()`, the latest
job (jobs module), `history` totals, `monitor.status()`, `bookmarks` counts
and `permissions.report()` into one typed dict mirroring the QleanerPro field
names (plus os-lab extras: `purgeableBytes`, `monitorEnabled`,
`monitorIntervalSeconds`, `nextMonitorCheckAt`, `latestMonitorEvent`,
`quickCleanCount`, `bookmarkedCount`, `fullDiskAccessGranted`,
`unreadableCount`). Pure read-only; `snapshot_schema_version` field included.
Unit tests: every field present on a fixture HOME, no absolute paths except
mount points, monotonic derived values (`usedPercent` clamped), placeholder +
empty fixtures.

**CLW-02 Console endpoint.** `GET /api/cleanup/widget` (read-only, PUBLIC
filter applies) returning the snapshot; `console/cleanup_api.py` body-key
guard for its optional `mountPoint` selector (default home volume). Missing
engine → 501; unknown query → 400. API client + TS types in
`dashboard/src/lib/api.ts`.

## Task 2 — Shared transport: App Group, entitlements, deep link (CLW-03)

**CLW-03 App Group + entitlements.** Group id
`group.com.keyvanarasteh.oslab`; entitlements files for the host app and the
widget extension (hardened runtime, Developer ID, app groups); wire
`tauri.conf.json > bundle > macOS > entitlements`. **Early spike + risk
call:** verify the unsandboxed Tauri host can read/write
`~/Library/Group Containers/<group>/widget-snapshot.json` with the
entitlement signed in — if not, fall back to a documented alternative (shared
path inside the app's Application Support, with the extension given read
access via its own entitlements) before anything else builds on it.
`WidgetConfig`-equivalent constants live in one Swift file (group id, file
names, scheme, route map) mirrored by a Rust constant so both sides agree.

**Deep links.** Register `oslab` scheme in `tauri.conf.json` (deep-link
config) with routes `scan | results | history | space | bookmarks | monitor |
review` mapping to dashboard island-router paths; Rust forwards to the
webview event → `pages.tsx` router navigates in place (no reload, same as
on-page cards).

## Task 3 — Host-side publish + reload + consume (CLW-04, CLW-05)

**CLW-04 Publish from the console, reload from the app.** The **console**
(Python, single source of truth) writes `widget-snapshot.json` atomically on:
status refresh, job state changes, monitor evaluations/re-hook runs, monitor
config changes, bookmark changes. The **app** triggers the WidgetKit reload
(`WidgetCenter.shared.reloadAllTimelines()`) on window focus and after each
dashboard data refresh. Reload path: a tiny Swift shim compiled into the
Tauri binary (swift-rs, or an ObjC bridge) — a standalone CLI helper cannot
reload another bundle's widgets, so in-process is required; document the
fallback (extension relies on its 15-minute policy + reload-on-timeline) if
the shim proves fragile.

**CLW-05 Consume widget actions.** `widget-pending-quick-clean.txt`
(timestamp) written by the widget intent; Rust consumes it once on focus with
a 120-second max-age (mirroring `consumePendingScanRequest`), forwards an
event to the dashboard, which runs the existing bookmark quick-clean flow
(plan → run, `automated: true`) and shows the result in place. The intent
also opens the app (like `openAppWhenRun`).

## Task 4 — Widget extension (CLW-06, CLW-07)

**CLW-06 WidgetKit targets.** `app/widget/` (Swift, macOS 12+):
`os-labWidgetKit` shared module (snapshot mirror struct + decoder, palette
mirror of the dashboard tokens light/dark, route map, views) and
`os-labWidgets` appex target (`@main` bundle + `StaticConfiguration` +
`SnapshotProvider` with placeholder/snapshot/timeline). **macOS targets
only** — `systemSmall` / `systemMedium` / `systemLarge` in Notification
Center and on the desktop; QleanerPro's `#if os(iOS)` accessory families are
noted in comments but not shipped. `.containerBackground` guarded by
availability (macOS 14+) with a plain background for 12/13. Preview macros
for all three families.

**CLW-07 Widget views, os-lab data.** Port of the three layouts restyled with
os-lab tokens and the CLW-01 field set: header (lab glyph + "os-lab" + status
dot), status label (Cleaning / Scanning / Ready to clean / Up to date / Low
disk space when the latest monitor warning is fresh), metric tiles (Found
items, Reclaimable, Disk free, Total reclaimed), scan progress bar while a
job runs, disk-used gauge (used% + purgeable note when proven), rows (last
scan, last cleanup, monitor interval/next check or "Monitor off", quick-clean
bookmarks count, FDA state), Quick-clean capsule button (QuickCleanIntent) +
widgetURL to the review flow. Everything degrades honestly on missing data
(placeholder/empty fixtures).

## Task 5 — Build, sign, ship (CLW-08, CLW-09)

**CLW-08 Embed + sign in release-mac.sh.** Build the appex (xcodebuild via a
checked-in `project.yml`/project or xcodegen if present) universal Release →
copy into `os-lab.app/Contents/PlugIns/` → codesign the appex (Developer ID,
same identity, entitlements) → the existing Tauri sign + notarize flow covers
the embedded extension (nested code must be signed before the outer bundle).
Local-only build script for iterating. Windows/Linux releases untouched; a
missing appex must not fail their builds.

**CLW-09 CI.** `release-mac.yml` unchanged apart from invoking the updated
script; verify the notarized app contains the signed appex (`codesign --verify
--deep`, `spctl`), and the dry-run (pull_request) path exercises the embed
without secrets.

## Task 6 — Dashboard surface, i18n, docs, tests (CLW-10 … CLW-13)

**CLW-10 Dashboard "Widgets" section.** A card in the Overview "System &
maintenance" group + a settings section (availability readiness: macOS +
extension bundled → actionable; otherwise the honest note), add-to-desktop
guidance, a "Test publish" button (refresh + reload), and the deep-link
route map documented inline.

**CLW-11 i18n.** All new UI strings ×7 locales via the generated
dictionaries (check script stays green).

**CLW-12 Docs + knowledge graph.** `lat.md/cleanup-lab.md` widget section
(≤250-char leads), `cleanup-lab/README.md`, `STATUS.md` ledger, `VERIFY.md`
evidence, roadmap entries in `cleanup-lab-tasks.tsx` marked shipped in this
PR.

**CLW-13 Tests + e2e.** Engine snapshot tests, console endpoint tests, Rust
publish/consume tests (atomic write, stale-request max-age), a Swift test
target for the snapshot mirror encode/decode (runs on the mac runner),
dashboard e2e for the Widgets section with mocked snapshot payloads.

---

## Open questions (ask before implementing)

1. App Group reachability from the unsandboxed Tauri host (CLW-03 spike) —
   if the entitlement path fails, the fallback changes transport but not the
   contract.
2. Does the maintainer want the widget's quick-clean to run **immediately**
   on intent (matching QleanerPro's scan-now semantics) or open the app with
   the quick-clean dialog pre-armed for one confirmation? The `quickClean`
   flag already records user pre-authorization, so immediate matches the
   reference; default to immediate unless told otherwise.
3. Widget refresh cadence: keep QleanerPro's 15-minute policy, or shorter?
   (WidgetKit budgets refreshes; monitor warnings pushed via the app's
   reload calls are the timely path.)
4. Should the launcher `app/ui` also gain a "Widgets" explainer, or does the
   dashboard surface suffice?

## Implementation status (2026-11-15)

Implemented on `feat/cleaner-widgets` (PR #226), commits up to the docs:

- **CLW-01/02/04** — `cleanup_lab/widget.py` (14 tests), `GET /api/cleanup/widget`
  + publish hooks (3 console tests). Committed as `7b379228` + `89d0d64a`.
- **CLW-10/11/13** — dashboard WidgetsCard, overview card, `__oslabNavigate` /
  `__oslabQuickClean` globals, 27 strings × 7 locales, `cleanup-widgets.spec.ts`
  (5 tests). Commit `fd58b8d6`.
- **CLW-03/04/05/06/07** — `app/widget` Swift targets (appex macOS 14+,
  reloader framework macOS 12), Rust bridge + deep links + entitlements.
  Commit `84c0a0416`.
- **CLW-08/09** — release-mac.sh embed/re-sign/re-notarize/updater rebuild +
  PR dry-run widget compile. Commits `105738e45`, `0e6c7ffbb`.
- **CLW-12** — lat.md, README, STATUS, VERIFY, roadmap, this status. This commit.

Deviations from the plan, honestly:

1. **macOS 14 for the appex, not 13** — the AppIntents `Button(intent:)` needs
   macOS 14 (the plan assumed 13). On macOS 12/13 hosts the system never loads
   the extension; the app itself keeps macOS 12.
2. **macOS targets only, confirmed** — no iOS accessory families shipped
   (`#if os(iOS)` noted, not ported).
3. **The purgeable segment is not in the widget snapshot** — the widget's disk
   gauge uses used%; purgeable stays on the dashboard hero, since probing it
   per publish would run diskutil on every monitor tick.
4. **Reload via an embedded framework instead of swift-rs** — one @objc class
   dlopen'd from Contents/Frameworks; a missing framework degrades to the
   extension's 15-minute policy (plan's documented fallback).
5. **Quick-clean runs immediately on intent** — open question 2 resolved to
   the reference semantics; the review dialog still shows the built plan.

Open question 1 (App Group reachability from the unsandboxed host) stays
honest: the console's `capable` probe drives everything, the dashboard states
the idle reason, and the first signed release verifies it for real.
