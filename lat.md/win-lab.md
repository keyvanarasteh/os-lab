# win-lab

A reproducible Windows VM on Ubuntu Server, built on `dockur/windows`.

One compose service runs QEMU+KVM with a noVNC web viewer and RDP.
The persistent disk lives in `storage/`.

See [[win-lab]], the service in [[win-lab/docker-compose.yml]] and the runbook
[[win-lab/README.md]].

## Service and endpoints

The `windows` service (container `win-lab`) serves the web viewer on `WEB_PORT`
(8006) and RDP on `RDP_PORT` (3389, tcp+udp).

It requires `/dev/kvm` and `/dev/net/tun` and `NET_ADMIN`. Host paths `storage/`,
`shared/` (guest drive Z:) and `oem/` (C:\OEM automation) are bind-mounted.
Configuration is environment-driven via [[win-lab/.env.example]].

## Lifecycle and readiness

`make boot` starts the VM and waits for the web viewer; `make wait-install`
blocks on the `storage/windows.boot` marker that signals the install finished.

Targets are in [[win-lab/Makefile]], readiness logic in
[[win-lab/scripts/wait-ready.sh]], host checks in [[win-lab/scripts/preflight.sh]].
The three readiness stages are container `Up`, web viewer HTTP 200 (visible
during install too), and the `windows.boot` marker (install complete).

## State, backup and reset

All guest state is in `storage/`; configuration is `.env` plus compose.

[[win-lab/scripts/backup.sh]] takes a cold, crash-consistent archive (unless
`--live`); [[win-lab/scripts/restore.sh]] moves the current `storage/` aside
before extracting, so restores are reversible. `make reset CONFIRM=yes` destroys
the disk and reinstalls on next boot.

## Windows Apps Lab

On a real Windows host, the dashboard can open the separate `winapps` lab.

It serves a local desktop mirror through [[console/winapps.py]] with ctypes
window enumeration, per-monitor physical-pixel coordinates, `PrintWindow`
capture and standard-library COM UI Automation; this is separate from the
Windows VM lifecycle and public Pages never mounts it.

A window is listed only when it is actually on screen: visible, captioned,
not minimized, not a tool or shell window and not DWM-cloaked (suspended UWP
frames stay "visible" to Win32 but cannot be seen). Each entry carries
`elevated` (true, false, or null when Windows will not say) so an elevated
window a standard-user console cannot capture is marked rather than hidden.
`GET /api/labs/winapps/doctor` and `python console/winapps.py --doctor` report
the desktop session, this console's own elevation and one live capture probe.

The UI Automation tree exposes only visible control-view elements, omits
password controls and value properties, bounds labels and result counts, and
returns window-relative physical-pixel bounds plus a per-HWND revision diff.
Window rectangles and UIA hotspots use the same per-monitor-aware coordinate
space as capture and `SendInput`; the inventory also reports the owning
window's DPI when Windows provides it. Capture retries with
`PrintWindow(PW_RENDERFULLCONTENT)` when the normal render fails or is black,
and only uses desktop BitBlt as a fallback when no higher window overlaps the
target.

Search is limited to roles and labels. Input is opt-in: a single local owner
holds a ten-minute arm lock, every click, double-click, right-click, scroll,
typed text or allowlisted key requires explicit confirmation, and each action
revalidates the visible HWND. Mouse coordinates must land inside the selected
window and not behind another window; keyboard input also verifies that the
target is foreground. `/api/labs/winapps/control` includes a bounded recent
action summary with no typed content or window titles. `/api/labs/winapps/stop`
disarms and ends active mirror streams. POST requests remain protected by the
console's Host and `X-OSLab: 1` checks.

### Agent safety gate

Everything the web endpoints and the MCP server show of this lab passes through
[[console/winapps_guard.py]]; an agent sees only allowlisted apps and nothing sensitive.

The guard reads the policy file `win-lab/winapps-policy.json` (or `OSLAB_WINAPPS_POLICY`).
An agent sees only windows of apps on `allowedApps`; an
empty, missing or broken policy means it sees nothing and reports `policyError`.
Windows that look sensitive (built-in password managers, private or incognito
browsing, online-banking title hints, plus anything the policy adds) are never
captured for anyone and are marked restricted in the panel. Restricted beats the
allowlist, and the built-in restrictions cannot be removed. A capture is checked
before and after the pixels are taken, against the policy as it is at that moment,
because a title or the policy file can change meanwhile. The doctor probe goes
through the same check. Unknown keys, an unreadable file or invalid JSON are a
policy error, and a broken policy restricts every window for everyone (reason
`policy-error`) until it is fixed, because it may have lost a restriction it meant to
add. An agent capture is capped at 4K, checked again on the captured PNG's own size,
and every capture has a 15 second deadline; at most two timed-out captures may still be
running before new ones get `CAPTURE_BUSY`, so a huge or hung window cannot exhaust
memory or stall the MCP server.

Every agent call and every refusal is audited without titles or images, in memory
and in a daily JSONL file (capped at 10,000 rows per process and day, the count starting
again each day; after a failed write that day's file gets no more rows, so a half-written
line is never followed by another); identical rows (including the tool) within a minute
are counted, not repeated. The agent's own view of
the audit hides other audiences' rows and the app name of any refusal.
The MCP server adds read-only `winapps_*` tools on Windows and no arm or input tool.
The console's UI Automation, search, stream, click and input routes call
`require_window` first, so a restricted window is refused there as well, and a
screenshot keeps the `windowToken` identity check.

### Input gate

[[console/winapps_input_gate.py]] is the door every click and input action passes
before [[console/winapps.py#winapps_control_click]] or `winapps_control_input` sends it.

The gate authorizes one action and never sends input itself. It has no arm state of its
own: arming, the single owner, the timeout and the panic stop are the control lock from
#316/#318, and the gate's `arm`, `disarm` and `panic_stop` are audited doors to that same
lock (the console's `/control` and `/stop` routes go through them too). On top of the lock
it covers #288's WINMIR-11a to 11e: a locked screen or secure prompt refuses input
(`desktop_locked()`), the window is read again at the moment of the action, restricted
windows stay refused, the app allowlist is default-deny for input even for a person (an
empty or missing `win-lab/winapps-policy.json` refuses every action), and submit-class
input (a paste or Enter) needs an explicit `confirm: true`. The send path re-checks the
lock's owner and confirmation under its own mutex, so a disarm or panic stop that lands
while the gate runs still stops the action. Every refusal and every authorization is
audited without titles or the owner's name. `GET /api/labs/winapps/input` shows the gate
state; `POST .../input/arm`, `.../disarm` and `.../panic` need the `X-OSLab` header. There
is no arm tool on MCP, and `winapps_capabilities` reports only the gate's fixed rules:
the arm state lives in the console's process, so the MCP server never reports a copy of it.

Honest limits: the filter reads process names and titles only, so it is a
heuristic. The allowlist binds the MCP path; the local HTTP address serves the
human panel, so an agent that can run commands on this machine can still request
unrestricted windows there. It guards against agent mistakes, not a hostile local
user; a secret the agent does not hold on that address is a later phase. For the
same reason a local process that sets the header can arm the input gate over HTTP.

The audit trail is per process: the HTTP console and each MCP server keep their own
in-memory rows and `seq` numbers, all appending to the same daily file. Coalescing matches
any identical row of the last minute, the final count of a coalesced row reaches the file as
one `{"seq", "kind": "count"}` line, and a console restarted on the same day continues
that day's `seq`. `GET /api/labs/winapps/policy` includes the
policy file's path on purpose, so people know where to edit it.

## Research

Windows-lab research and the command reference.

They live in [[win-lab/knowledge]] and [[win-lab/dockur-windows-cheat-sheet.md]].
Cross-lab operation is via [[labctl]] (`./labctl win ...`).
