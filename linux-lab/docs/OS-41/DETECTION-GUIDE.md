# OS-41 detection guide: "the server crashed"

How to find out what really happened when a Linux host "crashed": a reboot, an OOM kill, a
planned restart, a memory stall, or a network drop. Every step is read-only. This is the
manual version of what [`stall_doctor.py`](../../../docs/PLAN-OS-41-stall-detector.md) will
automate.

Work from the outside in: first rule out the big causes, then follow the clues that remain.
Write down the server time (`date -u`) before you start, and use it for every timestamp.

## Step 1: did the machine reboot?

```bash
date -u; uptime
journalctl --list-boots | tail -3
```

If uptime is days and there is one boot entry covering the incident, it did not reboot.

## Step 2: did the kernel kill something?

```bash
journalctl -k --since "-90 min" | grep -iE 'out of memory|killed process|oom'
```

Use `journalctl -k`, not `dmesg`: without root `dmesg` often fails, and an empty result is
easy to misread as "no kills" (scenario S13). A hit shows the victim and its
`oom_score_adj`; that is a confirmed S1.

## Step 3: is memory under pressure now?

```bash
free -m
swapon --show            # zram vs disk swap, and how full each is
cat /proc/pressure/memory
vmstat 2 5               # si/so = swap in/out per second
ps -eo pid,ppid,etime,rss,pcpu,args --sort=-rss | head -15
```

How to read it:
- zram at 100% with disk swap in use means pages now come from slow storage (S2).
- PSI `full avg10` is the share of the last 10 s in which all tasks waited on memory.
  A few percent is noticeable, tens of percent is a stall.
- Load far above the CPU count together with high swap means thrashing.
- In the process list, look at the age (`etime`) as well as size: a new 2 GB `tsc` that is
  2 minutes old is a likely trigger (S3); a process with hours of high CPU is a runaway (S4).

Find who started a heavy process:

```bash
pstree -sp <pid> | head -3
```

## Step 4: are the tunnels healthy?

```bash
systemctl show cloudflared -p NRestarts -p ActiveEnterTimestamp
curl -s 127.0.0.1:<metrics-port>/ready        # expect readyConnections: 4
journalctl -u cloudflared --since "-60 min" | grep -E 'ERR|WRN'
cat /proc/$(pgrep -o cloudflared)/oom_score_adj
cat /proc/$(pgrep -o cloudflared)/cgroup        # which unit really manages it (S10)
```

0 restarts, 4 ready connections and no errors means the tunnel was not the cause.
An error like `no recent network activity` a few seconds after a stall means the stall hit
the tunnel too. Errors on one tunnel only, repeatedly, point at its transport (S14).

## Step 5: which services stopped, and was it planned?

```bash
journalctl --since "-35 min" -p warning | grep -v pam_unix
journalctl --user -u <unit> --since "-40 min" | grep -iE 'exit|fail|deploy|stopp|start'
```

`status=143` is SIGTERM: someone or something asked it to stop. If a deploy or restart
message comes right before it, that is a planned restart (S5), not a crash. A crash shows
signal 9, an OOM line, or an application error.

## Step 6: did an IDE remote session drop?

Remote IDEs (VS Code, Cursor, Antigravity and similar) keep logs on the server, for example
`~/.vscode-server/data/logs/` or `~/.antigravity-ide-server/data/logs/`.

```bash
LOG=$(ls -td ~/.vscode-server/data/logs/*/ | head -1)
grep -rh 'heartbeat' "$LOG" | sort | tail
grep -rhE 'reconnected|auto-select family' "$LOG" | sort | tail
pgrep -f 'server-main|dns-result-order' | xargs -r ps -o pid,lstart,rss -p
journalctl -u ssh --since "-30 min" | grep Accepted
```

What it means:
- `No ptyHost heartbeat after 6 seconds` is the server side freezing for 6 s or more.
- `The client has reconnected` plus a new SSH login at the same second is a dropped
  connection that came back.
- A new IDE server process starting next to an old one means the client could not resume
  and started over.

## Step 7: was it the server or the network? (S6 vs S7)

For each reconnect time, check the 60 seconds before it:

| Seen before the reconnect | Most likely |
|---|---|
| Heartbeat warning, high PSI, a heavy job running | Server stall (S6, caused by S2/S3) |
| Nothing on the server, tunnel shows no errors | Network path between the client and the edge (S7) |

Then look at the old sessions:

```bash
ps -eo pid,lstart,args | grep 'sshd-session: .*@notty' | grep -v grep
sshd -T 2>/dev/null | grep -i clientalive   # needs root; else read /etc/ssh/sshd_config*
```

If every old session is still alive, the server never saw them close: the client side went
silent (half-open connections). With `ClientAliveInterval 0` sshd never cleans them up.
The server cannot see the client side, so call this "likely", not "confirmed".

## Step 8: is something piling up? (S8)

Count SSH sessions and IDE servers per user. Each dropped session can leave its process,
and each restarted IDE can leave a whole server with its language servers and agents. That
memory makes the next stall more likely, so S7 and S8 feed S2.

## Step 9: correlate with heavy jobs

If heavy jobs go through a logging wrapper, line up its start times with the heartbeat
warnings and reconnects:

```bash
tail -20 ~/tsc-safe.log
```

A match is a correlation, not proof. Running `watch` sampling (or `vmstat 2` in a spare
terminal) during the next incident turns it into a measurement.

## Common traps

| Trap | Reality |
|---|---|
| `dmesg` is empty, so there were no OOM kills | It may just be unreadable. Use `journalctl -k` |
| Exit code in red means crash | 143 after a deploy is a planned stop |
| A process outside the system units is unmanaged | Check `/proc/<pid>/cgroup`; it may be a `systemd --user` unit |
| `MemoryMin` on the service protects it | Not unless every ancestor slice also has `memory.min` |
| `OOMScoreAdjust` on a slice | Unknown key in `[Slice]`, silently ignored |
| `IOWeight=1000` | Does nothing without the `io` controller in `cgroup.subtree_control` |
| Enable `systemd-oomd` | Check it is installed first |
| `StartLimitBurst` plus `Restart=always` | Can trip the limit and leave the unit failed |
| Times copied into notes by hand | Check them against the server clock |

## Fixes to consider

Match the scenario to a fix from the [fix catalog](../../../docs/PLAN-OS-41-stall-detector.md#fix-catalog).
The ones used most often:
- S2/S3/S6: cap and serialise heavy jobs (F5), agent rule (F6), userspace OOM policy (F7).
- S7/S8: `ClientAliveInterval 15` and `ClientAliveCountMax 4` on the server (F8), stop
  stale IDE servers by PID (F9), `ServerAliveInterval 15` on the client (F10).
- S9/S11: tunnel `OOMScoreAdjust=-900`, `MemoryMin` with `system.slice` reservation,
  `MemorySwapMax=0`, `Restart=always` (F1–F3).

Restart sshd or the tunnel that carries your own session only from a detached job with a
health check and rollback, or from a second session you know works.
