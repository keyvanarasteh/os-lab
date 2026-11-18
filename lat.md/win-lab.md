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

It serves a read-only desktop mirror through [[console/winapps.py]] with ctypes
window enumeration and a `PrintWindow` capture; no process control is offered.
This is separate from the Windows VM lifecycle and public Pages never mounts it.

A window is listed only when it is actually on screen: visible, captioned,
not minimized, not a tool or shell window and not DWM-cloaked (suspended UWP
frames stay "visible" to Win32 but cannot be seen). Each entry carries
`elevated` (true, false, or null when Windows will not say) so an elevated
window a standard-user console cannot capture is marked rather than hidden.
`GET /api/labs/winapps/doctor` and `python console/winapps.py --doctor` report
the desktop session, this console's own elevation and one live capture probe.

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
through the same check. Unknown keys in the policy file are an error, and an
invalid allowlist still keeps the restrictions that did parse. An agent capture
is capped at 4K and every capture has a 15 second deadline, so a huge or hung
window cannot exhaust memory or stall the MCP server.

Every agent call and every refusal is audited without titles or images, in memory
and in a daily JSONL file (capped at 10,000 rows per process and day); identical
consecutive rows within a minute are counted, not repeated. The agent's own view of
the audit hides other audiences' rows and the app name of any refusal.
The MCP server adds read-only `winapps_*` tools on Windows and no arm or input tool.

### Input gate

[[console/winapps_input_gate.py]] is the single door any future input (`SendInput`) must
pass; it authorizes one action and never sends input itself. It covers #288's
WINMIR-11a to 11e: arming has exactly one owner and expires on its own (5 s to 5 min,
60 s by default), a panic stop disarms at once and bumps an epoch that streams can
watch, a locked screen or secure prompt refuses input, the app allowlist is
default-deny for input even for a person (an empty policy refuses everything), and
submit-class input (a paste or Enter) needs an explicit `confirm: true` even while armed.
The window is read again at the moment of the action, restricted windows stay
refused, and every refusal and every authorization is audited without titles or the
owner's name. `GET /api/labs/winapps/input` shows the state; `POST .../input/arm`,
`.../disarm` and `.../panic` need the `X-OSLab` header. There is no arm tool on MCP, and
`winapps_capabilities` reports the gate without its owner.

Honest limits: the filter reads process names and titles only, so it is a
heuristic. The allowlist binds the MCP path; the local HTTP address serves the
human panel, so an agent that can run commands on this machine can still request
unrestricted windows there. It guards against agent mistakes, not a hostile local
user; a secret the agent does not hold on that address is a later phase. For the
same reason a local process that sets the header can arm the input gate over HTTP.

The audit trail is per process: the HTTP console and each MCP server keep their own
in-memory rows and `seq` numbers, all appending to the same daily file, and the file
keeps a coalesced row's first count only. `GET /api/labs/winapps/policy` includes the
policy file's path on purpose, so people know where to edit it.

## Research

Windows-lab research and the command reference.

They live in [[win-lab/knowledge]] and [[win-lab/dockur-windows-cheat-sheet.md]].
Cross-lab operation is via [[labctl]] (`./labctl win ...`).
