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

## Research

Windows-lab research and the command reference.

They live in [[win-lab/knowledge]] and [[win-lab/dockur-windows-cheat-sheet.md]].
Cross-lab operation is via [[labctl]] (`./labctl win ...`).
