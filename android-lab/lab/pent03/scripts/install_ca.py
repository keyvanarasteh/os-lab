#!/usr/bin/env python3
"""Install the mitmproxy CA into the Android **system** trust store.

Since Android 7 (API 24) apps no longer trust user-added CAs by default, so to
MITM lab traffic the mitmproxy root CA has to be trusted at the *system* level.
Android looks system certificates up by a hashed filename: ``<subject_hash_old>.0``,
where ``subject_hash_old`` is the legacy OpenSSL hash of the certificate subject.

Two install methods, auto-selected by the device SDK level:

* **writable-system** (API <= 33) — ``adb remount`` makes ``/system`` writable on
  a ``-writable-system`` emulator image; the cert is copied straight into
  ``/system/etc/security/cacerts/``.
* **apex-tmpfs** (API >= 34, Android 14+) — the trust store moved into the
  Conscrypt APEX (``/apex/com.android.conscrypt/cacerts``) and is read-only.
  We stage the full existing cert set plus ours, then mount a ``tmpfs`` over both
  the legacy dir and the APEX dir and repopulate them, restoring owner, mode and
  the ``system_security_cacerts_file`` SELinux context. (The APEX mount is per
  mount-namespace; apps spawned after the overlay see it. For already-running
  apps the same mount can be re-entered into the zygote with ``nsenter`` — see
  ``apex_nsenter_commands``.)

The hashing, filename, on-device path and the command *builders* are pure and
unit-tested; the remount/overlay execution lives in the ``install_*`` runners.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import adb
import scope

SYSTEM_CACERTS_DIR = "/system/etc/security/cacerts"
APEX_CACERTS_DIR = "/apex/com.android.conscrypt/cacerts"
DEVICE_STAGING = "/data/local/tmp/ca-overlay"
SELINUX_CACERT_CONTEXT = "u:object_r:system_security_cacerts_file:s0"

#: SDK level at which the Conscrypt-APEX trust store replaces writable /system.
APEX_MIN_SDK = 34


class CaInstallError(RuntimeError):
    """Installing the system CA failed."""


# --- pure helpers (offline-testable) ---------------------------------------


def default_mitmproxy_ca_path() -> str:
    """Return the conventional mitmproxy CA PEM location."""
    return os.path.join(os.path.expanduser("~"), ".mitmproxy", "mitmproxy-ca-cert.pem")


def system_cert_filename(hash_old: str) -> str:
    """Return the Android system-store filename for a subject hash."""
    hash_old = hash_old.strip()
    if not hash_old:
        raise CaInstallError("empty subject hash")
    return f"{hash_old}.0"


def system_cert_path(hash_old: str) -> str:
    """Return the full on-device (legacy /system) path for the installed CA."""
    return f"{SYSTEM_CACERTS_DIR}/{system_cert_filename(hash_old)}"


def install_method_for_sdk(sdk: int) -> str:
    """Return ``'apex-tmpfs'`` for API 34+, else ``'writable-system'``."""
    return "apex-tmpfs" if sdk >= APEX_MIN_SDK else "writable-system"


def apex_overlay_commands(cert_filename: str) -> list[list[str]]:
    """Return the ordered on-device shell arg-lists for the API 34+ overlay.

    Each element is an argv list (no shell string). ``cert_filename`` is the
    ``<hash>.0`` file already pushed to ``/data/local/tmp``.
    """
    staged_cert = f"/data/local/tmp/{cert_filename}"
    cmds: list[list[str]] = [
        # 1. stage the existing trusted set + our cert.
        ["mkdir", "-p", DEVICE_STAGING],
        ["sh", "-c", f"cp {SYSTEM_CACERTS_DIR}/* {DEVICE_STAGING}/ 2>/dev/null || true"],
        ["sh", "-c", f"cp {APEX_CACERTS_DIR}/* {DEVICE_STAGING}/ 2>/dev/null || true"],
        ["cp", staged_cert, f"{DEVICE_STAGING}/{cert_filename}"],
    ]
    # 2. overlay both stores with a writable tmpfs and repopulate + fix labels.
    for target in (SYSTEM_CACERTS_DIR, APEX_CACERTS_DIR):
        cmds += [
            ["mount", "-t", "tmpfs", "tmpfs", target],
            ["sh", "-c", f"cp {DEVICE_STAGING}/* {target}/"],
            ["sh", "-c", f"chown root:root {target}/*"],
            ["sh", "-c", f"chmod 644 {target}/*"],
            ["sh", "-c", f"chcon {SELINUX_CACERT_CONTEXT} {target}/*"],
        ]
    return cmds


def apex_nsenter_commands() -> list[list[str]]:
    """Return commands to re-enter the APEX overlay into the running zygote.

    Needed only to expose the overlay to apps that were already running before
    it was mounted; freshly spawned apps pick it up without this.
    """
    inject = (
        "for pid in $(pgrep zygote); do "
        f"nsenter --target $pid --mount -- "
        f"sh -c 'mount -t tmpfs tmpfs {APEX_CACERTS_DIR}; "
        f"cp {DEVICE_STAGING}/* {APEX_CACERTS_DIR}/; "
        f"chmod 644 {APEX_CACERTS_DIR}/*; "
        f"chcon {SELINUX_CACERT_CONTEXT} {APEX_CACERTS_DIR}/*'; done"
    )
    return [["sh", "-c", inject]]


def _default_runner(argv: list[str]) -> str:
    # Safe by construction: argv is a list and shell is False (default), so no
    # shell interpretation/metacharacter expansion is possible. Only used to run
    # a fixed ``openssl`` argv over a local PEM path. (opengrep audit rule flags
    # any non-literal argv regardless of shell=False.)
    proc = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        argv, check=False, text=True, capture_output=True, shell=False
    )
    if proc.returncode != 0:
        raise CaInstallError(
            f"command failed ({proc.returncode}): {' '.join(argv)}\n"
            f"{(proc.stderr or '').strip()}"
        )
    return proc.stdout


def subject_hash_old(pem_path: str, *, runner=_default_runner) -> str:
    """Compute the legacy OpenSSL subject hash of a PEM certificate.

    ``runner`` is injectable; by default it shells out to ``openssl``.
    """
    if not os.path.isfile(pem_path):
        raise CaInstallError(f"certificate not found: {pem_path}")
    out = runner(
        ["openssl", "x509", "-inform", "PEM", "-subject_hash_old", "-noout", "-in", pem_path]
    )
    first = out.strip().splitlines()[0].strip() if out.strip() else ""
    if not first:
        raise CaInstallError(f"openssl returned no hash for {pem_path}")
    return first


def prepare_cert(pem_path: str, hash_old: str, dest_dir: str) -> str:
    """Copy the PEM to ``<dest_dir>/<hash>.0`` and return the new path."""
    if not os.path.isfile(pem_path):
        raise CaInstallError(f"certificate not found: {pem_path}")
    out_path = os.path.join(dest_dir, system_cert_filename(hash_old))
    shutil.copyfile(pem_path, out_path)
    os.chmod(out_path, 0o644)
    return out_path


# --- side-effecting install ------------------------------------------------


def _resolve_ca(ca_path: str | None) -> str:
    ca_path = ca_path or default_mitmproxy_ca_path()
    if not os.path.isfile(ca_path):
        raise CaInstallError(
            f"mitmproxy CA not found at {ca_path}; run mitmproxy once to generate it"
        )
    return ca_path


def install_writable_system(
    serial: str | None,
    ca_path: str,
    hash_old: str,
    *,
    adb_bin: str = adb.DEFAULT_ADB,
    tmp_dir: str | None = None,
) -> str:
    """API <= 33 path: remount /system and drop the cert in. Returns remote path."""
    remote = system_cert_path(hash_old)
    adb.enable_root(serial, adb=adb_bin)
    if not adb.is_root(serial, adb=adb_bin):
        raise CaInstallError(
            f"device {serial!r} is not rooted after 'adb root'; writing to /system "
            f"needs root + a '-writable-system' emulator image"
        )
    adb.remount(serial, adb=adb_bin)
    with tempfile.TemporaryDirectory(prefix="mitmca-", dir=tmp_dir) as tmp:
        local = prepare_cert(ca_path, hash_old, tmp)
        adb.run(adb.push_argv(serial, local, remote, adb=adb_bin))
    adb.shell(serial, "chmod", "644", remote, adb=adb_bin)
    adb.shell(serial, "chown", "root:root", remote, adb=adb_bin, check=False)
    return remote


def install_apex_tmpfs(
    serial: str | None,
    ca_path: str,
    hash_old: str,
    *,
    adb_bin: str = adb.DEFAULT_ADB,
    tmp_dir: str | None = None,
) -> str:
    """API >= 34 path: tmpfs-overlay both trust stores. Returns APEX cert path."""
    cert_filename = system_cert_filename(hash_old)
    adb.enable_root(serial, adb=adb_bin)
    if not adb.is_root(serial, adb=adb_bin):
        raise CaInstallError(
            f"device {serial!r} is not rooted after 'adb root'; the APEX overlay "
            f"needs root (use an emulator 'userdebug'/'eng' image)"
        )
    # disable verity/remount so mounts stick (best effort on emulator images).
    adb.run(adb.adb_argv(serial, "shell", "mount", "-o", "rw,remount", "/",
                         adb=adb_bin), check=False)
    with tempfile.TemporaryDirectory(prefix="mitmca-", dir=tmp_dir) as tmp:
        local = prepare_cert(ca_path, hash_old, tmp)
        adb.run(adb.push_argv(serial, local, f"/data/local/tmp/{cert_filename}", adb=adb_bin))
    # Run the overlay. mkdir / mount / cp are load-bearing and must succeed;
    # chown/chmod/chcon are best-effort (SELinux may be permissive on an image).
    for argv in apex_overlay_commands(cert_filename):
        best_effort = argv[0] in ("chown", "chmod", "chcon") or (
            len(argv) >= 3 and argv[0] == "sh" and
            any(argv[2].startswith(c) for c in ("chown", "chmod", "chcon"))
        )
        proc = adb.run(adb.shell_argv(serial, *argv, adb=adb_bin), check=False)
        if proc.returncode != 0 and not best_effort:
            raise CaInstallError(
                f"APEX overlay step failed ({proc.returncode}): {' '.join(argv)}\n"
                f"{(proc.stderr or '').strip()}"
            )
    # The overlay lives in the adb-shell mount namespace; re-apply it inside the
    # zygote namespace so freshly forked apps also see the CA. Best-effort:
    # nsenter may be unavailable on some images, in which case apps spawned from
    # the shell-namespace overlay still work after a cold app start.
    for argv in apex_nsenter_commands():
        adb.run(adb.shell_argv(serial, *argv, adb=adb_bin), check=False)
    return f"{APEX_CACERTS_DIR}/{cert_filename}"


def install(
    serial: str | None,
    ca_path: str | None = None,
    *,
    adb_bin: str = adb.DEFAULT_ADB,
    runner=_default_runner,
    tmp_dir: str | None = None,
    method: str | None = None,
) -> str:
    """Install the mitmproxy CA, auto-selecting the method by device SDK.

    ``method`` forces ``'writable-system'`` or ``'apex-tmpfs'``; otherwise it is
    chosen from ``ro.build.version.sdk``. Returns the on-device cert path.
    """
    serial = scope.require_serial(serial)
    ca_path = _resolve_ca(ca_path)
    hash_old = subject_hash_old(ca_path, runner=runner)

    if method is None:
        sdk = adb.get_sdk(serial, adb=adb_bin)
        method = install_method_for_sdk(sdk)

    if method == "apex-tmpfs":
        return install_apex_tmpfs(
            serial, ca_path, hash_old, adb_bin=adb_bin, tmp_dir=tmp_dir
        )
    return install_writable_system(
        serial, ca_path, hash_old, adb_bin=adb_bin, tmp_dir=tmp_dir
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the mitmproxy CA into the Android system trust store."
    )
    parser.add_argument("-s", "--serial", default="emulator-5554")
    parser.add_argument(
        "--ca", default=None, help="path to mitmproxy CA PEM (default: ~/.mitmproxy/...)"
    )
    parser.add_argument(
        "--method",
        choices=["auto", "writable-system", "apex-tmpfs"],
        default="auto",
        help="install method (default: auto-detect from device SDK)",
    )
    args = parser.parse_args(argv)
    method = None if args.method == "auto" else args.method
    try:
        remote = install(args.serial, args.ca, method=method)
    except (CaInstallError, adb.AdbError, scope.ScopeError) as exc:
        print(f"CA install failed: {exc}", file=sys.stderr)
        return 1
    print(f"mitmproxy CA installed at {remote} on {args.serial}")
    if remote.startswith(APEX_CACERTS_DIR):
        # The APEX overlay is a tmpfs and does NOT survive a reboot — do not tell
        # the user to reboot; restart the target app, or re-run after a reboot.
        print("APEX tmpfs overlay is non-persistent: it is lost on reboot. "
              "Restart the target app to pick up the CA; re-run this after any reboot.")
    else:
        print("Reboot the emulator (adb reboot) if apps were already running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
