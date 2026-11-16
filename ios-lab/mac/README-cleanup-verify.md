# Cleanup panel verification (mac-lab)

`make -C ios-lab mac-cleanup-verify` audits the Cleanup (cleaner) panel of the
running os-lab desktop app end to end: it finds the app's local console, checks
every panel endpoint, runs the default and full catalog scans (measurement
only — nothing is deleted), and writes a JSON + Markdown report under
`ios-lab/artifacts/cleanup-verify-<timestamp>/`. Set `BOOKMARK=1` to also apply
the recommended quick-clean bookmarks, and `RECORD=1` to capture a
`screencapture` video of the run. `PORT=<n>` skips port discovery.

## What it checks

| Panel part | Endpoint(s) |
|---|---|
| Header readiness badge | `GET /api/cleanup/status` |
| Dashboard tool cards | `monitor`, `permissions`, `volumes`, `relocation`, `deep-roots` |
| Advanced scan catalog | `GET /api/cleanup/catalog` (64 entries) |
| Results / Leftovers / History | `GET /api/cleanup/jobs`, `/history` (+ scan jobs) |
| Bookmarks card | `GET/POST /api/cleanup/bookmarks` |
| Space Explorer | `GET /api/cleanup/explorer/roots` — a 404 is the known bug fixed by PR #248 (the route shipped in `post()` while the dashboard GETs it); the script says so instead of failing the run |

## Quick-clean bookmark policy (`BOOKMARK=1`)

Quick clean is the one-tap flow from the bookmarks card, so its entries must be
safe to clean **repeatedly without review**: `risk == "low"`, at least 50 MB,
largest first, at most 8. High/medium risk (`system.shared-temp`,
`system.temp`) and privacy entries (browser history) are deliberately excluded —
they belong in the plan → confirm flow on the Advanced scan page, not behind
one tap. From the 2026-11-15 audit scan (15.6 GB across 64 entries) this picks
`system.user-caches`, `developers.npm`, `developers.go-mod`,
`browser.chrome.cache`, `developers.cargo-registry`, `developers.go-build`,
`developers.pip`.

## The manual runbook this automates

The audit was first performed by hand on 2026-11-15; the steps, for an agent or
a person with the repo open:

1. **Find the console.** `ps -axo command= | grep '[w]eb_ui\.py [0-9]'` — the
   app spawns `python … web_ui.py <port> <app-pid>`; the second column after
   the script is the port (the listener belongs to the Python child, so
   `lsof -a -p <app-pid>` finds nothing). The installed app version:
   `defaults read /Applications/os-lab.app/Contents/Info.plist CFBundleShortVersionString`.
2. **Probe the endpoints** (curl the table above; `catalog` may take ~8 s
   cold — it walks the filesystem once, then caches).
3. **Walk the six tabs** in any browser against `http://127.0.0.1:<port>/cleanup/`
   — Dashboard, `/space/`, `/scan/`, `/results/`, `/leftovers/`, `/history/` —
   and read each page's state (headings, empty states, alerts). The Space
   Explorer error alert is `"Cleanup Lab endpoint not found"`.
4. **Record it** with `screencapture -v out.mov` around the walkthrough
   (Screen Recording permission required for the terminal).
5. **Run the scans**: `POST /api/cleanup/scan {"entryIds": […]}` with the
   default-selected entries, then all 64; poll
   `GET /api/cleanup/jobs/<id>` until `state == done` (~3 s default, ~26 s
   full on an M-series Mini).
6. **Save the evidence**: job JSON, a size-sorted entry table, endpoint
   statuses and the recording into one dated directory.

The script is steps 1, 2, 5 and 6 in one command; steps 3–4 stay manual (or
`RECORD=1` captures whatever the screen shows while the scans run).
