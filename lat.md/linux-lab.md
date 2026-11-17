# linux-lab

A disposable Linux VM on Ubuntu Server, built on `qemux/qemu`, for malware
detonation, ELF reverse engineering, exploit/kernel work and container-escape
practice behind KVM. It mirrors [[win-lab]] but boots any distro or ISO.

See [[linux-lab]], the service in [[linux-lab/docker-compose.yml]] and the
runbook [[linux-lab/README.md]].

## Service and endpoints

The `linux` service (container `linux-lab`) serves the noVNC web viewer on
`WEB_PORT` (8006) and SSH on `SSH_PORT` (2222 -> guest 22).

The guest is chosen with `BOOT` (a distro shortcut or an ISO URL) and
`BOOT_MODE` (UEFI by default), configured in [[linux-lab/.env.example]]. It
requires `/dev/kvm` and `/dev/net/tun` and `NET_ADMIN`; `storage/` and `shared/`
are bind-mounted.

## Lifecycle and readiness

`make boot` waits for the web viewer; `make wait-ready` also waits for SSH and
then writes the `storage/linux.ready` marker.

Probing logic is in [[linux-lab/scripts/wait-ready.sh]]; host checks (with a
lower 16 GB disk floor than the Windows lab) in [[linux-lab/scripts/preflight.sh]].
Readiness stages: container `Up`, web viewer HTTP 200, and SSH accepting.

## State, backup and containment

All guest state is in `storage/`; backup/restore reuse the shared pattern.

See [[linux-lab/scripts/backup.sh]] and [[linux-lab/scripts/restore.sh]];
`make reset CONFIRM=yes` re-provisions a clean guest. Because untrusted code is
expected, network containment is documented in
[[linux-lab/knowledge/networking.md]] and worked workflows in
[[linux-lab/knowledge/usecases.md]].

## Server first-look diagnostics (OS-16)

[[linux-lab/scripts/server_firstlook.py]] reports Linux guest facts without
changing the system or requiring sudo.

It runs fixed argument lists for uname, lsb_release, inxi (CPU only),
free, local df and systemctl service listing, with locale-independent parsing and
per-command timeouts. Each subprocess call has literal arguments and disables
the shell; unknown command names are rejected. It needs only Python's standard
library and no sudo.

Readable text and JSON expose kernel/architecture, distro, CPU, memory bytes,
local mount usage and loaded service states. An architecture note distinguishes
kernel names from distribution package names. Missing tools, failed commands,
unrecognized output and timeouts stay explicit; unavailable service data is null,
not an empty healthy list. Exit 0 means report generation, not a health verdict.
Empty or unknown service states and malformed distro/CPU fields produce partial
reports. Zero-sized disks may have null usage percentages. ASCII-only stdout
uses character escapes; JSON preserves the original values on decoding.
Nothing is installed, changed, automatically saved or sent over the network.

[[android-lab/lab/tests/test_server_firstlook.py]] covers normal output, missing
tools, timeouts, malformed tables, failed/non-systemd services, empty/unknown
service states, distro/CPU validation, zero-sized disks, ASCII stdout, fixed
command execution, JSON and CLI errors.
[[linux-lab/docs/OS-16/VERIFY.md]] describes lab reproduction and evidence capture.

## Permission and ownership audit

[[linux-lab/scripts/permission_audit.py]] audits an owned lab tree's Unix modes
and UID/GID against configurable limits. It reports world-write, excess bits,
privileged regular files and ownership drift as text or JSON without applying fixes.

Directory-relative stats and `fwalk` do not follow symlinks. Other filesystems
and special files are counted as skipped; access errors and the entry budget
make coverage incomplete. Exit codes are 0 clean, 1 findings, 2 incomplete/usage.

The mode masks default to 0644/0755 and owner to the current UID; group is opt-in.
Directory sticky/setgid semantics are preserved in suggestions. ACLs and file
contents are outside scope; the audit is not an atomic filesystem snapshot.

Offline cases in [[android-lab/lab/tests/test_permission_audit.py]] cover rules,
root changes, links, limits, failure reporting and read-only behavior.
[[linux-lab/docs/OS-26/VERIFY.md]] supplies the reproducible lab and video steps.

OS-26 review hardening normalizes byte paths with `fsdecode`, rejects filesystem
root aliases by device/inode, and compares opened child directories with their
previously observed identities before inspecting contents. Changed directories
make coverage incomplete. Findings include device/inode and stale-path warnings;
commands are manual examples, never race-safe remediation. Ownership commands
precede chmod; setgid directory mode restoration is suggested after chown.
At most 1000 combined finding/error records are retained, including a terminal
limit error; reaching that budget stops the audit with exit 2. `fwalk` directory
name lists remain a limitation for very wide directories; use small owned labs.


## Why qemux/qemu

The engine was chosen to match the Windows and macOS labs' compose+web-viewer UX.

Rationale and the alternatives considered (privileged containers, libvirt,
Firecracker, gVisor) are recorded in [[linux-lab/knowledge/draft.md]].

## OS-30 Ubuntu baseline checker and explicit repairs

[[linux-lab/scripts/harden_check.py]] is the standard-library Python entry point
requested by the roadmap. It provides a read-only audit and selected,
consent-gated repairs.

Both entry points accept unquoted `ID=ubuntu` and double-quoted `ID="ubuntu"`
in `/etc/os-release`, without sourcing that file.

Its default audit delegates to [[linux-lab/scripts/hardening.sh]] for local SSH,
user/sudo, cached-update and UFW checks; text or versioned JSON reports preserve
WARN and FAIL evidence. A missing/empty collector or execution returning no
findings is refused rather than treated as a clean audit.
This runs inside an authorized Ubuntu guest (including ARM64 UTM), independently
of the Docker VM host and its SSH forwarding port.

Repair planning is read-only. Explicitly selected permission/timer/management-rule
repairs require root and exact interactive consent immediately before application.
Snapshots, metadata checks, no-follow file descriptors and a repair lock protect
against drift and overlapping application. SSH authentication and ports are not
changed; no package upgrades, UFW reset or automatic UFW activation occur. Failed
permission/timer changes are rolled back. Failed or interrupted apply never
automatically deletes UFW rules, including verified additions. Attempted
additions retain the backup and manifest, with manual inspection required and
the backup path reported.

The allowlist and limitations are explained in [[linux-lab/knowledge/hardening.md]].
[[linux-lab/tests/test_hardening.py]] and [[linux-lab/tests/test_harden_check.py]]
use command fakes and temporary files.

See [[linux-lab/os-30/VERIFY.md]] for test results and UTM verification.
[[linux-lab/os-30/REPORT.md]] records the scope of the work.

Completed schema-2 repair manifests record verified post-state for explicit
`rollback ID`. The same lock and exact consent protect rollback; snapshot and
post-state drift refuse permission/timer restoration. Only a uniquely tagged,
proven run-owned UFW addition may be removed, with ambiguous firewall state
reported as partial recovery. Legacy/incomplete evidence is not trusted.
Rollback tests in [[linux-lab/tests/test_rollback.py]] use temporary files
and fake commands.

## OS-24 Local .deb Installer

The OS-24 script installs local Debian packages on Ubuntu.

Script: `linux-lab/scripts/os-24-deb-installer.sh`

### Usage

Install a local Debian package: the script validates it first, then hands
it to apt.

```bash
./linux-lab/scripts/os-24-deb-installer.sh ./package.deb
```

### Behavior

Validation and install steps, in order:

- Requires exactly one package path.
- Checks whether the file exists.
- Requires a `.deb` file extension.
- Validates the package using `dpkg-deb --info`.
- Installs the package using `sudo apt install -y`.
- Uses `realpath` to resolve the package's absolute path.

### Safety

Only install trusted `.deb` packages. Installation requires sudo
permissions and may modify the operating system.
