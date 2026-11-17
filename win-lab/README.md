# win-lab: the runnable Windows lab

Minimal, reproducible Windows VM on Ubuntu Server, built on
[`dockur/windows`](https://github.com/dockur/windows). One compose stack, one
set of scripts, and a Makefile that covers setup, boot, status, backup and
recovery.

```
┌──────────────────── win-lab (docker compose) ────────────────────┐
│ windows (dockurr/windows)                                        │
│   QEMU + KVM · UEFI · TPM/Secure Boot (BOOT_MODE)                │
│   noVNC web viewer  :8006                                        │
│   RDP               :3389/tcp,udp                                │
│   /storage  -> ./storage   (disk, ISO, windows.boot marker)      │
│   /shared   -> ./shared    (drive Z:, Shared on desktop)         │
│   /oem      -> ./oem       (C:\OEM + install.bat)                │
└──────────────────────────────────────────────────────────────────┘
        devices: /dev/kvm, /dev/net/tun   cap: NET_ADMIN
```

## Requirements

- Ubuntu Server (22.04/24.04/26.04) or another Linux with KVM.
- `/dev/kvm` accessible to your user (member of the `kvm` group).
- Docker Engine with Compose (or Podman with a Compose provider).
- 32 GB free disk minimum, 64 GB+ recommended; 2 GB free RAM minimum.
- Outbound HTTPS on first boot, unless you provide a local ISO.

Run `make preflight` to check all of it.

## Quick start

```bash
cd win-lab
cp .env.example .env
$EDITOR .env                  # change WINDOWS_PASSWORD at least
sudo make setup               # KVM + Docker + groups + directories
newgrp docker                 # or log out/in
make preflight
make boot                     # start; open http://<server-ip>:8006/
make wait-install             # wait for storage/windows.boot
make status
```

Shortcuts: `./setup.sh` (= `sudo make setup`) and `./run.sh --install`
(= `make boot` plus `make wait-install`).

The first boot downloads media and installs Windows automatically. Expect
20-60+ minutes. Do not stop the container mid-installation.

Connect over RDP (`make rdp` prints the details) or use the web viewer for the
initial setup.

## Windows Apps Lab

On a real Windows host, a separate `/labs/winapps/` page mirrors one visible
desktop window. It is independent of this Windows VM, works before the VM is set
up, and offers no input or process control in the read-only phase. The collector
is [`console/winapps.py`](../console/winapps.py) (standard-library ctypes only).

```powershell
python console/winapps.py            # JSON window inventory
python console/winapps.py --doctor   # desktop session, console elevation, capture probe
```

Honest limits: a window is listed only when it is on screen (visible, captioned,
not minimized, not a tool window and not DWM-cloaked, so suspended UWP frames are
skipped). `PrintWindow` captures what Windows will render for that window; a
standard-user console may be refused or get a blank image for elevated windows,
which the list marks `Elevated` and `--doctor` reports for the console itself.
UAC secure-desktop prompts cannot be captured.

## Make targets

| Target | What it does |
|---|---|
| `preflight` | OS / KVM / runtime / ports / disk / RAM checks |
| `setup` | install KVM and Docker, add user to `kvm`/`docker`, create dirs |
| `prepare` | create `.env` and `storage/ shared/ oem/ backups/` |
| `up` / `boot` | start; `boot` also waits for the web viewer |
| `wait` | wait for the web viewer |
| `wait-install` | wait for `storage/windows.boot` (installation done) |
| `status` | compose state, web port, install marker, storage size |
| `monitor` / `profiles` | live dashboard; list management profiles |
| `logs` / `shell` | follow logs; shell inside the container |
| `rdp` / `smb` | print connection details and the shared folder path |
| `restart` / `update` | graceful restart; pull image and recreate |
| `backup` / `restore` | cold backup and restore (`FULL=1` adds shared/oem) |
| `install-service` | systemd unit so the VM starts at boot |
| `down` | graceful stop |
| `reset` | destroy disks and reinstall on next boot (`CONFIRM=yes`) |
| `clean` | remove `backups/` only |

Examples:

```bash
make boot
make backup FULL=1
make restore FILE=backups/win-lab-20260101-120000.tar.gz
make logs
make reset CONFIRM=yes
```

## Profiles and management

The repo-level `labctl` adds presets, hardware changes and a live dashboard:

```bash
../labctl win profiles
../labctl win profile use lightweight   # 2 CPU / 4 GB, sharing and shortcut off
../labctl win start --wait
../labctl win monitor
../labctl win resize --cpus 4 --ram 8G --apply
../labctl win config show
../labctl win stop
```

| Profile | CPU | RAM | Notes |
|---|---:|---:|---|
| `lightweight` | 2 | 4G | practical Windows 11 minimum, Samba/shortcut off |
| `development` | 4 | 6G | balanced, Samba/shortcut on, debug logging on |
| `performance` | 6 | 8G | builds and heavier workloads, debug logging off |

`profile use` writes the preset into `.env`; `--profile P` is a one-shot
overlay. The disk is persistent and grow-only: `resize --disk 128G` expands the
virtual disk, then extend the partition in Windows Disk Management. Hardware
changes require `--apply` (or `restart`) to recreate the container.

## Layout

```
win-lab/
├── docker-compose.yml      # dockurr/windows service
├── .env.example            # version, resources, ports, credentials
├── profiles/               # lightweight / development / performance presets
├── Makefile                # all targets above
├── scripts/
│   ├── preflight.sh        # read-only host checks
│   ├── setup-ubuntu.sh     # KVM + Docker + groups + dirs (+ optional ufw)
│   ├── wait-ready.sh       # web readiness and installation marker
│   ├── backup.sh           # cold archive of storage + config
│   ├── restore.sh          # restore an archive
│   ├── install-service.sh  # systemd unit generator
│   └── uninstall-service.sh
├── storage/                # VM disk, ISO cache, windows.boot (gitignored)
├── shared/                 # host <-> guest files (drive Z:)
├── oem/                    # optional C:\OEM + install.bat
└── backups/                # archives (gitignored)
```

## Readiness model

- Container `Up`: QEMU started. Not enough to use Windows.
- Web viewer HTTP 200: setup screen is visible. This is also true during
  installation, so it does not mean Windows is installed.
- `storage/windows.boot` exists: installation finished; later boots use the
  installed disk. `make wait-install` polls this marker.

## Customisation

Everything is environment-driven; edit `.env` and `make restart`:

- `VERSION` (`11`, `11l`, `10`, `2022`, `tiny11`, an ISO URL, ...)
- `RAM_SIZE`, `CPU_CORES`, `DISK_SIZE`, `DISK_FMT`
- `WINDOWS_USER`, `WINDOWS_PASSWORD`, `LANGUAGE`, `KEYBOARD`, `REGION`
- `WEB_PORT`, `RDP_PORT`, `WEB_PROTECT`
- `SAMBA`, `SHORTCUT`, `REMOVE_ISO`, `SHUTDOWN`, `DEBUG`

For a local ISO, bind `./custom.iso:/custom.iso` in compose and set
`VERSION` to anything (it is ignored). For OEM automation, put `install.bat`
and its files in `oem/`; they run at the end of installation.

## Agent brief (compact)

- **Mission:** provide a reproducible, isolated Windows guest on an Ubuntu
  Server host, reachable over the web viewer or RDP, driven by `make`.
- **Tools:** `docker compose`, `curl` (readiness), `tar` (backup), `ufw`
  (optional), `xfreerdp`/`mstsc` (client side).
- **State:** all guest state is in `storage/`; configuration is `.env` plus
  `docker-compose.yml`. There is no other state.
- **Guardrails:** never expose RDP publicly; do not run untrusted guests on a
  shared bridge without egress filtering; `make reset` is destructive.
- **Return shape:** a running container named `win-lab`, a web viewer on
  `WEB_PORT`, and `storage/windows.boot` once installation completes.

See `knowledge/` for research, deployment, operations, networking and use
cases, and `dockur-windows-cheat-sheet.md` for the command reference.
