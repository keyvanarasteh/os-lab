# macOS Lab app mirror roadmap — plan (draft PR)

Implementation plan for the macOS Lab roadmap tasks `MIR-01…MIR-06`
(dashboard/src/views/macos-lab-tasks.tsx), all on this branch as the user
directed. Every task keeps the shipped guardrails: read-only endpoints by
default, preview → confirm before anything runs, armed control mode that
disarms itself, localhost-only POSTs with `X-OSLab: 1`, and honest permission
labeling (Screen Recording, Accessibility). Reference: lat.md/ios-lab.md,
docs/UX_READINESS.md.

Surfaces touched by every task: `ios-lab/mac/macos-app.sh` (the one script the
previewed flow and armed control both run), `console/oslab.py` (typed plans,
guards, in-process state), `android-lab/lab/web_ui.py` (localhost routes) and
`dashboard/src/views/macos-app-mirror.tsx` (the panel).

---

## MIR-01 — Element action menu (double, right, type, key)

- `macos-app.sh input <pid> <x> <y> <kind> [text]` with fixed argv and
  `kind ∈ double|right|type|key`. `type` posts characters through CGEvents
  with the text echoed to stderr; newlines are stripped — Return is never sent
  from a type action. `key` takes an allowlisted key name (tab, escape, delete,
  arrows, space, enter) — enter is its own explicit action.
- `plan()` accepts `inputKind`/`inputText`/`inputKey` only with
  `action = macos-input` (bounds-checked like the click fields; text capped at
  200 chars, no control characters); effects state the kind, the text (type)
  or key, and that no Return is sent by type.
- Armed direct route `POST /api/labs/macos/input` mirrors
  `macos_control_click` and records an audit row (kind, text length).
- Panel: long-press/right-click on a hotspot opens a small menu (double,
  right, type…, key…); type and key open dialogs whose preview echoes the
  payload; armed mode runs the same action immediately and records the audit
  row.

## MIR-02 — Accessibility diff overlay

- `GET …/elements?revision=<token>` returns, when the token matches the
  console's cached snapshot for that window, `{added, removed, changed}`
  alongside the new snapshot and revision. Matching is role+label+geometry
  proximity; the 150-element cap is unchanged and diffs are bounded.
- Panel keeps the previous revision per window, rings added hotspots, fades
  removed ones for one refresh cycle, and marks changed ones.

## MIR-03 — Retina and multi-display correctness

- `macos_windows()` reports each display's origin, size and backing scale
  (CGWindowCopyScreenInfo through the same ctypes bridge) and each window's
  scale factor; capture pixel size is compared against window points so a
  mismatched scale cannot silently skew hotspots.
- Hotspot math stays in points end to end; the mirror maps pointer → window
  points through the element bounds, not pixels.
- `macos-app.sh doctor` prints a displays report (origins, sizes, scale
  factors) so coordinates can be reasoned about remotely.

## MIR-04 — Streaming mirror (MJPEG)

- `GET /api/labs/macos/apps/<id>/stream` streams
  `multipart/x-mixed-replace` frames with no-store headers and correct
  boundaries; the loop stops on client disconnect or after a hard 10-minute
  cap, so handlers never dangle.
- The panel fetches the stream with an AbortController (pauses on hidden
  tabs, closes when no client wants frames), picks `?fps=` per pointer
  proximity to the mirror (fast while hovered, slow otherwise — no extra
  permissions), and falls back to the existing poll when the stream errors;
  capture errors degrade to an inline frame message.

## MIR-05 — mac2 deep-inspect mode

- Console session helper: open/find/close one Appium mac2 session per app
  bundle id (`_MACOS_SESSIONS`, pid-guarded against visible windows). The
  session id lets both the console (armed actions, element lists) and a
  previewed job (`macos-app.sh element <session> <element> <kind>`) drive
  Appium directly.
- `POST /api/labs/macos/session` (open), `GET /api/labs/macos/session`
  (state), `GET …/session/<bundle>/elements` (stable element ids), `POST
  …/session/<bundle>/action` (armed click/type on an element id), `DELETE
  …/session/<bundle>`.
- Panel deep-inspect toggle: opens the session for the selected app, routes
  hotspot actions through element ids while it is open, falls back to
  CGEvent coordinates otherwise, closes on panel hide/tab unload/app quit,
  and never leaves a dangling session. Plans display element routing in
  effects.

## MIR-06 — Session audit log

- Console-side recorder: a bounded ring buffer plus an
  `artifacts/macos-audit-<date>.jsonl` writer. Rows: time, app, window,
  kind, coordinates or element, armed vs previewed, plus arm/disarm events
  and small base64 frame thumbnails captured with actions (and opportunistically
  while the mirror is actively polled, at most one per interval).
- `GET /api/labs/macos/audit` lists rows; `GET /api/labs/macos/audit.json`
  downloads the single JSON file with embedded thumbnails. Everything stays
  local; no preview secrets are recorded (tokens are hashed).

## Verification

- `dashboard/`: `npm run check`, `npm run test:i18n`, `npm run build`,
  `npm run test:e2e` (stream fallback covered with a stubbed stream).
- `lat check` after lat.md updates; `python3 -m compileall` for the Python
  side; `bash -n` for scripts.
- Live verification on this Mac (status/doctor, element reads, armed clicks,
  doctor display report) recorded in ios-lab/VERIFY.md; two-display hotspot
  acceptance stays noted where hardware limits it to one display.
