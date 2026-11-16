# Plan: OS-41 Session-Drop & Memory-Stall Doctor

**Status: draft, not implemented.** Tracking checklist: [TODO-OS-41-stall-detector.md](TODO-OS-41-stall-detector.md).
How a person does the same investigation by hand: [linux-lab/docs/OS-41/DETECTION-GUIDE.md](../linux-lab/docs/OS-41/DETECTION-GUIDE.md).

## Why

"The server crashed" usually means something narrower: an IDE window dropped, an SSH
session hung, a web app returned 502, or the box went slow for a minute. On 2026-11-16 a
lab server (19.5 GB RAM, 9.5 GB zram + 4 GB disk swap, Cloudflare Tunnel for SSH and web)
"crashed" several times in one afternoon. In practice:

- one real kernel OOM kill (a `uvicorn` worker),
- several swap-thrash stalls caused by parallel `tsc --noEmit` runs from coding agents,
- two app restarts that were planned deploys, not crashes,
- many IDE disconnects, only some of which followed a server stall; the rest left
  half-open SSH sessions behind, which points at the network path,
- a slow leak: every drop left an old SSH session and sometimes a whole IDE server behind,
  which made the next stall more likely.

Each answer took a dozen commands, and the first written plan got several facts wrong
(it read an unreadable `dmesg` as "no OOM kills", called `systemd --user` units
"unmanaged", and proposed settings that systemd silently ignores). OS-41 turns that
investigation into one read-only tool that classifies what happened, shows the evidence,
and proposes fixes that are applied only with approval.

## Goal

`linux-lab/scripts/stall_doctor.py`: one command that answers
**"what just happened, why, and what should I change?"** for a Linux host that serves
SSH, IDE remote sessions, tunnels and dev workloads.

- Read-only by default. Changes only through `apply <fix-id>`, which shows the exact diff
  or command, asks for confirmation, and prints its rollback.
- Works without root. Steps that need root (`sshd -T`, some cgroup files, other users'
  `/proc`) degrade to "unknown, needs sudo" instead of a wrong answer.
- Python 3 standard library only, like `permission_audit.py` and `harden_check.py`.
- Exit codes: `0` nothing found, `1` findings, `2` usage error, `3` could not collect
  enough evidence to decide.
- Output: text by default, `--json` for the dashboard and CI, `--report <file.md>` for a
  Markdown incident report.

## General abilities

| Ability | Subcommand | What it does |
|---|---|---|
| Snapshot | `snapshot` | Uptime and boot list, RAM, each swap device and how full it is (zram vs disk), PSI memory/cpu/io, load, top processes by RSS with age and parent chain |
| Timeline | `timeline --since 2h` | Merges events from all sources into one sorted list (see Sources) |
| Classify | `explain [--at HH:MM]` | Takes the timeline and labels each disruption with a scenario from the catalog below, with the evidence lines that support it and a confidence (`confirmed`, `likely`, `possible`) |
| Sessions | `sessions` | Live SSH sessions with start times, which are half-open (newer session from the same client while the old one still exists), sshd keepalive settings, duplicate IDE remote servers and what they hold in memory |
| Tunnels | `tunnels` | For each `cloudflared` process: managing unit (system / user / none), `/ready` connections, restarts, `oom_score_adj`, effective `memory.min` including ancestors, swap limit, restart policy, transport (QUIC/HTTP2) and recent edge errors |
| Workload | `workload` | Heavy recurring jobs (type-checks, builds, test runners): who started them, how often, peak RSS, overlap with stalls; reads the optional run log of a capped wrapper |
| Config lint | `lint` | Catches protection settings that look right but do nothing (see S11) |
| Watch | `watch --interval 2 --out <file.jsonl>` | Light sampler (PSI, swap in/out, load, top RSS, session count) so the next stall is caught as it happens instead of reconstructed later |
| Advise / apply | `advise`, `apply <fix-id>` | Lists fixes for the findings; applies one with preview, confirmation and rollback |

### Sources the timeline reads

| Source | Events |
|---|---|
| `journalctl --list-boots`, `uptime` | Reboots |
| `journalctl -k` (not `dmesg`, which is often unreadable without root) | OOM kills, hung tasks, CPU hog warnings |
| `journalctl` system and `--user` | Unit stop/start/fail with exit code and signal; deploy messages if the unit logs them |
| `journalctl -u ssh` | Logins (`Accepted ...`) and disconnects |
| Tunnel units' journal | `ERR`/`WRN` lines such as `no recent network activity`, `timeout`, connection index |
| IDE remote server logs (VS Code family: `~/.vscode-server`, `~/.antigravity-ide-server`, `~/.cursor-server`, ...) | `No ptyHost heartbeat after N seconds`, `The client has reconnected`, new server process start |
| `/proc/pressure/*`, `/proc/meminfo`, `swapon` | Pressure and swap at sample time; history only from `watch` |
| Optional wrapper log (for example `~/tsc-safe.log`) | Heavy job starts with caller and working directory |
| Process table | Start times of IDE servers, `tsc`, agents; parent chain via `/proc/<pid>/stat` |

Every timestamp is shown in the server clock with its timezone. The report states the
time it was generated so readers can spot drift (S12).

## Scenario catalog

Each scenario has an ID, the evidence that confirms it, what rules it out, and the fixes
`advise` offers. Fix IDs are what `apply` accepts.

| ID | Scenario | Confirmed by | Ruled out by | Fixes |
|---|---|---|---|---|
| **S1** | Kernel OOM kill | `journalctl -k`: `Out of memory: Killed process <pid> (<name>)` with `oom_score_adj` | No such line in the window | F1, F5, F6, F7 |
| **S2** | Swap thrash stall | zram at or near 100% and disk swap in use; PSI `full avg10` high; load far above CPU count; heartbeat warnings | Swap mostly free, PSI near 0 | F5, F6, F7, F12 |
| **S3** | Heavy parallel or repeated jobs | Two or more `tsc`/build processes overlapping, or one caller restarting a 2 GB job every few minutes; wrapper log | Single job, long gaps | F5, F6 |
| **S4** | Runaway long-lived process | One process with high CPU for a long time and growing RSS (an agent, a language server) | Normal CPU history | F13 (stop by PID only, with approval) |
| **S5** | Planned restart mistaken for a crash | Unit `exit-code` with status 143 (SIGTERM) right after a deploy or `systemctl restart` message | Exit by signal 9, OOM line, or non-zero app exit with an error | None; report it as planned |
| **S6** | IDE stall then reconnect | `No ptyHost heartbeat after 6 seconds`, then a new SSH login and `client has reconnected`, or a new IDE server process | No heartbeat warning in the 60 s before the reconnect | F5, F6, F7, F9 |
| **S7** | Network-path drop (half-open sessions) | Reconnect with **no** server stall and **no** tunnel error, while the old SSH session process is still alive | Old session closed cleanly, or a stall precedes it | F8 on the server, F10 on the client; check client network |
| **S8** | Session and IDE server leak | Many `sshd-session: <user>@notty` processes older than the newest; more than one IDE remote server for the same user and version | One session and one server per window | F8, F9 |
| **S9** | Tunnel exposed to OOM or stalls | `cloudflared` with `oom_score_adj` ≥ 0, `memory.min` effectively 0, swap allowed, `Restart=on-failure` | Hardened unit | F1, F2, F3 |
| **S10** | Tunnel management misidentified | A tunnel the operator thinks is "unmanaged" is in `user@<uid>.service/app.slice/<unit>`; or truly has no unit | `/proc/<pid>/cgroup` matches a system unit | F4 (migrate, never duplicate) |
| **S11** | Protection that does nothing | `OOMScoreAdjust` in a `[Slice]` (unknown key); child `MemoryMin` with ancestor `memory.min` = 0; `IOWeight` without the `io` controller in `cgroup.subtree_control`; `systemd-oomd` enabled but not installed; `StartLimitBurst` that trips under `Restart=always`; unprivileged user unit asking for `OOMScoreAdjust` below its manager's | `systemd-analyze verify` clean and effective cgroup values match | F2, F3 (corrected forms) |
| **S12** | Wrong timestamps in a report | Times in notes ahead of or behind the server clock | Report generated by the tool | Always print server time and timezone |
| **S13** | False "no OOM" from `dmesg` | `dmesg` fails with permission denied | `journalctl -k` readable | Use `journalctl -k`; mark unknown if neither works |
| **S14** | Tunnel transport failures | Repeated QUIC `timeout` / `no recent network activity` on one tunnel while others are healthy | Errors on every tunnel (network-wide) | F11 |
| **S15** | Origin not ready at boot | Tunnel healthy but hostname returns 502 until an app unit starts later | App starts before the tunnel | F14 |

## Fix catalog

All fixes are previewed and need confirmation. The tool never kills by process name, only
by PID it has shown, and never restarts the tunnel that carries the current SSH session
inline: it schedules that restart as a detached job with a health check and automatic
rollback.

| ID | Fix | Change |
|---|---|---|
| **F1** | Tunnel OOM priority | Drop-in `OOMScoreAdjust=-900` (not -1000, so a leaking tunnel can still be killed last) |
| **F2** | Real memory reservation | `MemoryMin=64M` on the tunnel unit **and** `MemoryMin=256M` on `system.slice`; verify `memory.min` is non-zero afterwards |
| **F3** | Restart and swap policy | `Restart=always`, `RestartSec=5s`, `StartLimitIntervalSec=0`, `MemorySwapMax=0` |
| **F4** | Move a user tunnel to a system unit | Start the system unit first, confirm `/ready`, then `systemctl --user disable --now` the old one, so two instances never run and there is no downtime |
| **F5** | Capped, serialised heavy jobs | Wrapper: `flock` + `systemd-run --user --scope -p MemoryHigh=3G -p MemoryMax=4G -p MemorySwapMax=0` + matching `--max-old-space-size`; logs caller and cwd |
| **F6** | Agent rule | A line in the repo's `AGENTS.md`: use the wrapper, no parallel type-checks, minimum gap between runs |
| **F7** | Userspace OOM policy | Install `earlyoom` or `systemd-oomd`; exclude `cloudflared*` and `ssh`; act on a dev scope, not the whole user slice |
| **F8** | Reap dead SSH sessions | `/etc/ssh/sshd_config.d/50-keepalive.conf`: `ClientAliveInterval 15`, `ClientAliveCountMax 4`; `sshd -t`, then reload (existing sessions stay) |
| **F9** | Stop stale IDE servers | List each IDE server with start time, RSS and child count; stop the chosen PIDs only |
| **F10** | Client keepalive | Print the `~/.ssh/config` lines for the user's own machine: `ServerAliveInterval 15`, `ServerAliveCountMax 4` |
| **F11** | Tunnel transport | Drop-in `Environment=TUNNEL_TRANSPORT_PROTOCOL=http2` for the affected tunnel only; compare error counts for 10 minutes |
| **F12** | Swap layout advice | Report zram size vs RAM, disk swap on encrypted storage, `vm.swappiness`; advice only |
| **F13** | Stop a runaway process | Show PID, command, CPU time, RSS; stop on confirmation |
| **F14** | Boot ordering | `After=` and `Wants=` on the origin app unit for the tunnel unit |

## Safety rules

- Read-only unless `apply` is used. `apply` refuses without a TTY unless `--yes` is given.
- Never `pkill`/`killall` by name. Never touch PIDs that were not listed in the same run.
- Restarting the tunnel or sshd that carries the current session runs as a detached
  `systemd-run` job with a check and rollback.
- Evidence is quoted as log lines, so a reader can check every conclusion.
- Hostnames, tunnel IDs and tokens are redacted in `--report` unless `--no-redact` is set.
- Confidence is explicit. "Network-path drop" is `likely`, never `confirmed`, because the
  server cannot see the client side.

## Phases

1. **Collect:** snapshot, sources, timeline, `--json`. Unit tests on recorded log fixtures.
2. **Classify:** scenario rules S1–S15 with evidence and confidence. Fixtures from the
   2026-11-16 incident (anonymised) for each scenario.
3. **Sessions, tunnels, workload, lint.**
4. **Watch:** sampler with a size-capped JSONL file.
5. **Advise and apply:** F1–F14 with preview, confirmation, rollback.
6. **Dashboard (optional, separate PR):** Linux Lab card that runs `explain --json` and
   shows the timeline, following `docs/UX_READINESS.md`.

## Acceptance

- On the anonymised fixtures, `explain` labels each disruption with the right scenario.
- On a live host, `explain --since 1h` finishes in under 10 s and uses under 100 MB RSS,
  so it can run while the box is under pressure.
- Without root, it reports unknown fields instead of wrong ones.
- `apply` for F1–F3 and F8 produces files that pass `systemd-analyze verify` / `sshd -t`,
  and the effective values (`memory.min`, `oom_score_adj`, `sshd -T`) are checked after.
- `VERIFY.md` with reproducible steps: start a capped memory hog to trigger S2/S6 in a VM,
  kill the client network to trigger S7, and show both being classified.

## Out of scope

Fixing billing, CI or deploy pipelines; network diagnosis on the client machine (the tool
prints what to check there); Windows and macOS hosts.
