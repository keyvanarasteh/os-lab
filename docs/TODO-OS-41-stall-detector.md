# OS-41 Session-Drop & Memory-Stall Doctor — todo

[Plan](PLAN-OS-41-stall-detector.md) · [Manual detection guide](../linux-lab/docs/OS-41/DETECTION-GUIDE.md).
Reserve `OS-41` in [`reservations/`](../reservations/) before starting. One PR per phase is fine; keep the dashboard card in its own PR.

## Phase 0: docs (this PR)

- [x] Plan with general abilities, scenario catalog S1–S15 and fix catalog F1–F14.
- [x] Manual detection guide written from the 2026-11-16 incident.
- [x] OS-41 roadmap row in `CONTRIBUTING.md` and the Contribute page task list.
- [ ] Owner review of scope and fix list.

## Phase 1: collect

- [ ] `linux-lab/scripts/stall_doctor.py` skeleton: argparse subcommands, exit codes 0/1/2/3, `--json`, `--since`.
- [ ] `snapshot`: uptime, boots, RAM, each swap device (zram vs disk, % full), PSI, load vs CPU count, top RSS with age and parent chain.
- [ ] Readers for `journalctl -k`, system and `--user` journals, ssh, tunnel units, IDE server logs (VS Code family paths), optional wrapper log.
- [ ] Fall back to "unknown, needs sudo" when a source is unreadable. Never treat an unreadable `dmesg` as "no OOM" (S13).
- [ ] `timeline`: one sorted list, server clock with timezone, report generation time (S12).
- [ ] Fixtures: anonymised logs from 2026-11-16 under `linux-lab/tests/fixtures/os-41/`.

## Phase 2: classify

- [ ] Rules S1–S15 with evidence lines and confidence (`confirmed` / `likely` / `possible`).
- [ ] S5: exit 143 after a deploy or restart message is "planned", not "crash".
- [ ] S6 vs S7: heartbeat warning in the 60 s before a reconnect means stall; none, plus a still-alive old session and no tunnel error, means network path (`likely` only).
- [ ] `explain --at HH:MM` for "it crashed a few minutes ago".
- [ ] One unit test per scenario on fixtures.

## Phase 3: sessions, tunnels, workload, lint

- [ ] `sessions`: half-open SSH sessions, sshd keepalive (`sshd -T` or config files), duplicate IDE servers with RSS (S8).
- [ ] `tunnels`: managing unit from `/proc/<pid>/cgroup` (system / user / none, S10), `/ready` on metrics ports, restarts, `oom_score_adj`, effective `memory.min` with ancestors, swap max, restart policy, transport and error counts (S9, S14).
- [ ] Origin readiness at boot: tunnel up but hostname 502 until the app starts (S15).
- [ ] `workload`: heavy job starts, caller, frequency, overlap with stalls (S3, S4).
- [ ] `lint` for S11: `OOMScoreAdjust` in `[Slice]`, ancestor `memory.min` = 0, `IOWeight` without `io` controller, missing `systemd-oomd`/`earlyoom`, `StartLimitBurst` trap, user unit `OOMScoreAdjust` below the manager's.

## Phase 4: watch

- [ ] `watch --interval 2 --out file.jsonl`: PSI, swap in/out, load, top RSS, session count; size cap and rotation.
- [ ] `explain` uses watch samples when present, so stalls are measured instead of inferred.

## Phase 5: advise and apply

- [ ] `advise` maps findings to F1–F14.
- [ ] `apply <fix-id>`: preview diff or command, confirmation, rollback printed; `--yes` for non-TTY.
- [ ] F1–F3 drop-ins checked with `systemd-analyze verify`, then effective values re-read.
- [ ] F2 also writes `system.slice` `MemoryMin`, and fails if `memory.min` stays 0.
- [ ] F4 migration: start the system unit, check `/ready`, then disable the user unit; never two instances.
- [ ] F5 wrapper and F6 agent-rule text.
- [ ] F8 sshd keepalive drop-in, `sshd -t`, reload, re-read `sshd -T`.
- [ ] F9 / F13 stop by listed PID only.
- [ ] Restarting the tunnel or sshd that carries the current session runs as a detached job with a health check and automatic rollback.
- [ ] F10 prints client `~/.ssh/config` lines; F11 transport drop-in with a 10-minute before/after error count; F12 advice only; F14 `After=`/`Wants=`.

## Phase 6: docs and verification

- [ ] `linux-lab/docs/OS-41/VERIFY.md`: VM steps to trigger S2/S6 with a capped memory hog and S7 by cutting the client network, and to show each being classified.
- [ ] `lat.md/linux-lab.md` node for OS-41 behavior; run `lat check`.
- [ ] Performance: `explain --since 1h` under 10 s and 100 MB RSS on a loaded host.
- [ ] Redaction of hostnames, tunnel IDs and tokens in `--report`.

## Phase 7 (optional, separate PR): dashboard

- [ ] Linux Lab card that runs `explain --json` and shows the timeline and findings, following `docs/UX_READINESS.md`.
