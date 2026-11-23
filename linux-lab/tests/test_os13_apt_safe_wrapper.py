"""OS-13 apt update/upgrade safe wrapper: offline behaviour tests.

The wrapper is driven through a stub ``apt-get`` placed on PATH, so these tests
never touch the host package database, the network or a real upgrade. What they
pin down is the contract the task is about:

* dry-run is the default and changes nothing,
* ``apt-get update`` always runs before ``apt-get upgrade``,
* a failed or partial index refresh stops the upgrade before it starts,
* an empty plan skips the upgrade instead of running it for nothing,
* the apply command is ``<prefix> apt-get -y <subcommand>`` (not a duplicated
  subcommand),
* the reviewed plan is re-simulated before it is applied,
* a removal plan is not applied unattended without ``--allow-removals``,
* the log is private and is never written through a symlink.

Run from the repository root::

    python3 -m unittest discover -s linux-lab/tests -p 'test_os13*' -q
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "linux-lab" / "scripts" / "os-13-apt-safe-wrapper.sh"
BASH = shutil.which("bash")

STUB = r"""#!/usr/bin/env bash
# Stand-in for apt-get: records the call and answers like apt on Ubuntu.
printf '%s\n' "$*" >> "$OS13_STUB_LOG"
# The elevated process must actually see this, not just have it exported in
# the wrapper's own shell (sudo would filter it).
if [ -n "${DEBIAN_FRONTEND:-}" ]; then
  printf 'received DEBIAN_FRONTEND=%s\n' "$DEBIAN_FRONTEND" >> "$OS13_STUB_LOG"
fi

if [ "${1:-}" = "--version" ]; then
  printf 'apt 2.7.14 (amd64)\n'
  exit 0
fi

sim=0
for a in "$@"; do
  case "$a" in
    -s|--simulate) sim=1 ;;
  esac
done

if [ "$*" = "update" ]; then
  if [ -n "${OS13_STUB_UPDATE_FAIL:-}" ]; then
    printf 'Err:1 http://mirror.invalid/ubuntu noble InRelease\n'
    printf '  Could not connect to mirror.invalid:80\n'
    printf 'E: Failed to fetch http://mirror.invalid/ubuntu/dists/noble/InRelease  Could not connect\n'
    exit 100
  fi
  printf 'Hit:1 http://archive.ubuntu.com/ubuntu noble InRelease\n'
  printf 'Reading package lists...\n'
  if [ -n "${OS13_STUB_UPDATE_PARTIAL:-}" ]; then
    printf 'W: Failed to fetch http://archive.ubuntu.com/ubuntu/dists/noble/universe/binary-amd64/Packages  404  Not Found [IP: 91.189.91.82 80]\n'
    printf 'W: Some index files failed to download. They have been ignored, or old ones used instead.\n'
  fi
  exit 0
fi

if [ "$sim" -eq 1 ]; then
  # Post-check runs after a real "-y upgrade"; fail that one on request.
  if [ -n "${OS13_STUB_VERIFY_FAIL:-}" ] && grep -q -- '-y upgrade' "$OS13_STUB_LOG"; then
    printf 'E: forced post-check failure\n'
    exit 100
  fi
  # Second simulate (the apply re-check) returns a different plan on request.
  if [ -n "${OS13_STUB_PLAN_CHANGE:-}" ]; then
    ns=$(grep -c -- '-s upgrade' "$OS13_STUB_LOG" || true)
    if [ "${ns:-0}" -ge 2 ]; then
      printf 'Reading package lists...\n'
      printf '1 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n'
      printf 'Inst bash [5.2.21-2] (5.2.21-3 Ubuntu:24.04/noble-updates [amd64])\n'
      exit 0
    fi
  fi
  if [ -n "${OS13_STUB_SIM_EMPTY:-}" ]; then
    printf 'Reading package lists...\n'
    printf '0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n'
    exit 0
  fi
  printf 'Reading package lists...\n'
  printf 'Building dependency tree...\n'
  if [ -n "${OS13_STUB_REMOVAL_ONLY:-}" ]; then
    printf 'The following packages will be REMOVED:\n  legacy-config\n'
    printf '0 upgraded, 0 newly installed, 1 to remove and 0 not upgraded.\n'
    printf 'Remv legacy-config [1.0-1]\n'
    exit 0
  fi
  if [ -n "${OS13_STUB_REMOVALS:-}" ]; then
    printf 'The following packages will be REMOVED:\n  legacy-config\n'
    printf 'The following packages will be upgraded:\n  bash curl\n'
    printf '2 upgraded, 0 newly installed, 1 to remove and 0 not upgraded.\n'
    printf 'Inst bash [5.2.21-2] (5.2.21-3 Ubuntu:24.04/noble-updates [amd64])\n'
    printf 'Inst curl [8.5.0-2] (8.5.0-2ubuntu10.1 Ubuntu:24.04/noble-updates [amd64])\n'
    printf 'Remv legacy-config [1.0-1]\n'
    exit 0
  fi
  printf 'The following packages will be upgraded:\n  bash curl\n'
  printf '2 upgraded, 0 newly installed, 0 to remove and 3 not upgraded.\n'
  printf 'Inst bash [5.2.21-2] (5.2.21-3 Ubuntu:24.04/noble-updates [amd64])\n'
  printf 'Inst curl [8.5.0-2] (8.5.0-2ubuntu10.1 Ubuntu:24.04/noble-updates [amd64])\n'
  exit 0
fi

printf 'Unpacking bash (5.2.21-3) ...\n'
printf 'Setting up bash (5.2.21-3) ...\n'
exit 0
"""


@unittest.skipUnless(BASH, "bash is required (Linux, macOS, WSL or Git Bash)")
class AptSafeWrapperTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.stub = self.tmp / "stub-apt-get"
        self.stub.write_text(STUB, encoding="utf-8", newline="\n")
        self.stub.chmod(0o755)
        self.calls_file = self.tmp / "calls.log"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def run_wrapper(self, *args: str, _unset: tuple = (), **env_extra: str) -> subprocess.CompletedProcess:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("OS13_") and k != "DEBIAN_FRONTEND"
        }
        env.update(
            {
                "APT_GET": self.stub.as_posix(),
                "SUDO": "",
                "OS13_LOG": (self.tmp / "apt-last.log").as_posix(),
                "OS13_STUB_LOG": self.calls_file.as_posix(),
                "TMPDIR": self.tmp.as_posix(),
            }
        )
        env.update(env_extra)
        for key in _unset:
            env.pop(key, None)
        return subprocess.run(
            [BASH, SCRIPT.as_posix(), *args],
            env=env,
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=180,
        )

    def calls(self) -> list:
        if not self.calls_file.exists():
            return []
        return [line.strip() for line in self.calls_file.read_text().splitlines() if line.strip()]

    def wrapper_log(self) -> str:
        log = self.tmp / "apt-last.log"
        if not log.exists():
            return ""
        return log.read_text(encoding="utf-8", errors="replace")

    def log_path(self) -> Path:
        return Path(self.run_wrapper and self.tmp / "apt-last.log")

    # -- contract --------------------------------------------------------
    def test_script_parses(self) -> None:
        result = subprocess.run([BASH, "-n", SCRIPT.as_posix()], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help_exits_zero_and_calls_nothing(self) -> None:
        result = self.run_wrapper("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage:", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_unknown_argument_is_a_usage_error(self) -> None:
        result = self.run_wrapper("--nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument", result.stderr)

    def test_dry_run_is_default_and_runs_no_change(self) -> None:
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry-run", result.stdout)
        self.assertIn("nothing was changed", result.stdout)
        # Only the version probe and the simulation: no update, no upgrade,
        # and no apply-time re-check.
        self.assertEqual(self.calls(), ["--version", "-s upgrade"])
        self.assertNotIn("received DEBIAN_FRONTEND=noninteractive", self.calls())

    def test_inherited_frontend_is_not_passed_without_noninteractive(self) -> None:
        # ubuntu-22.04 runner images export DEBIAN_FRONTEND=noninteractive.
        # run_wrapper strips it; only --noninteractive may put it on argv.
        result = self.run_wrapper(DEBIAN_FRONTEND="noninteractive")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("received DEBIAN_FRONTEND=noninteractive", self.calls())

    def test_failed_update_stops_before_upgrade(self) -> None:
        result = self.run_wrapper("--apply", "--yes", OS13_STUB_UPDATE_FAIL="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("GUARD", result.stdout + result.stderr)
        self.assertEqual(self.calls(), ["--version", "update"])

    def test_order_is_update_then_simulate_then_recheck_then_upgrade(self) -> None:
        result = self.run_wrapper("--apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.calls()[:5],
            ["--version", "update", "-s upgrade", "-s upgrade", "-y upgrade"],
        )
        self.assertNotIn("GUARD", result.stdout + result.stderr)

    def test_apply_does_not_duplicate_the_subcommand(self) -> None:
        result = self.run_wrapper("--apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The bug this pins: a single argv of `upgrade -y upgrade` must not
        # come back (the extra subcommand makes apt fail).
        self.assertNotIn("upgrade -y upgrade", self.calls())
        self.assertNotIn("dist-upgrade -y dist-upgrade", self.calls())
        self.assertIn("-y upgrade", self.calls())

    def test_partial_index_failure_is_a_guard(self) -> None:
        result = self.run_wrapper("--apply", "--yes", OS13_STUB_UPDATE_PARTIAL="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("GUARD", result.stdout + result.stderr)
        self.assertNotIn("-y upgrade", self.calls())

    def test_allow_partial_continues_on_request(self) -> None:
        result = self.run_wrapper("--apply", "--yes", "--allow-partial", OS13_STUB_UPDATE_PARTIAL="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("-y upgrade", self.calls())

    def test_empty_plan_skips_the_upgrade(self) -> None:
        result = self.run_wrapper("--apply", "--yes", OS13_STUB_SIM_EMPTY="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to upgrade", result.stdout)
        self.assertNotIn("-y upgrade", self.calls())

    def test_dist_upgrade_selection_is_honoured(self) -> None:
        result = self.run_wrapper("--apply", "--yes", "--dist-upgrade")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertIn("-s dist-upgrade", calls)
        self.assertIn("-y dist-upgrade", calls)

    def test_noninteractive_keeps_local_configs(self) -> None:
        result = self.run_wrapper("--apply", "--yes", "--noninteractive")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        upgrade_calls = [c for c in self.calls() if c.endswith(" upgrade") and "-y" in c]
        self.assertEqual(
            upgrade_calls,
            ["-y -o Dpkg::Options::=--force-confold upgrade"],
        )

    def test_noninteractive_frontend_is_on_the_command_line(self) -> None:
        # sudo filters exported vars; the frontend must travel with argv.
        result = self.run_wrapper("--apply", "--yes", "--noninteractive")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DEBIAN_FRONTEND=noninteractive", self.wrapper_log())
        self.assertIn("received DEBIAN_FRONTEND=noninteractive", self.calls())

    @unittest.skipIf(os.name == "nt", "PATH lookup differs on Windows")
    def test_sudo_prefix_with_options_is_split(self) -> None:
        bindir = self.tmp / "bin"
        bindir.mkdir()
        fake = bindir / "gotobin"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'SUDO %s\\n' \"$*\" >> \"$OS13_STUB_LOG\"\n"
            "# Drop a leading -n like a real sudo would, so exec gets the command.\n"
            "if [ \"${1:-}\" = \"-n\" ]; then shift; fi\n"
            "exec \"$@\"\n",
            encoding="utf-8",
            newline="\n",
        )
        fake.chmod(0o755)
        result = self.run_wrapper(
            "--apply",
            "--yes",
            SUDO="gotobin -n",
            PATH=f"{bindir.as_posix()}{os.pathsep}{os.environ.get('PATH', '')}",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("-y upgrade", self.calls())
        self.assertTrue(any(c.startswith("SUDO -n ") for c in self.calls()), self.calls())

    def test_plan_change_between_sim_and_apply_is_a_guard(self) -> None:
        result = self.run_wrapper("--apply", "--yes", OS13_STUB_PLAN_CHANGE="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("GUARD", result.stdout + result.stderr)
        self.assertNotIn("-y upgrade", self.calls())
        # plan + re-check happened; apply did not
        self.assertEqual(self.calls().count("-s upgrade"), 2)

    def test_failed_post_check_is_not_a_success(self) -> None:
        result = self.run_wrapper("--apply", "--yes", OS13_STUB_VERIFY_FAIL="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("post-check", result.stdout + result.stderr)
        self.assertIn("-y upgrade", self.calls())

    def test_removal_plan_is_not_applied_unattended_without_ack(self) -> None:
        result = self.run_wrapper("--apply", "--yes", OS13_STUB_REMOVALS="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("allow-removals", result.stdout + result.stderr)
        self.assertNotIn("-y upgrade", self.calls())

    def test_allow_removals_permits_the_plan(self) -> None:
        result = self.run_wrapper(
            "--apply", "--yes", "--allow-removals", OS13_STUB_REMOVALS="1"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("-y upgrade", self.calls())
        self.assertIn("REMOVED", result.stdout)

    def test_removal_only_plan_is_not_treated_as_empty(self) -> None:
        result = self.run_wrapper(
            "--apply", "--yes", "--allow-removals", OS13_STUB_REMOVAL_ONLY="1"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("-y upgrade", self.calls())
        self.assertIn("1 to remove", result.stdout)

    def test_default_log_path_includes_the_uid(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX uid")
        result = self.run_wrapper(_unset=("OS13_LOG",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"os-13-apt-last-{os.getuid()}.log", result.stdout)

    # -- log safety ------------------------------------------------------
    def test_log_file_is_created_private(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX permissions")
        log = self.tmp / "apt-last.log"
        result = self.run_wrapper(OS13_LOG=str(log))
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = log.stat().st_mode & 0o777
        self.assertEqual(oct(mode), oct(0o600), oct(mode))

    def test_log_symlink_is_not_followed(self) -> None:
        victim = self.tmp / "victim.txt"
        victim.write_text("do not destroy\n", encoding="utf-8")
        link = self.tmp / "apt-last.log"
        try:
            link.symlink_to(victim)
        except OSError:
            self.skipTest("symlinks unavailable")
        result = self.run_wrapper(OS13_LOG=str(link))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(victim.read_text(encoding="utf-8"), "do not destroy\n")
        # The wrapper either refused the path or wrote a private log; the
        # victim must be intact either way.
        self.assertIn("dry-run", result.stdout)

    def test_unwritable_log_falls_back_and_still_runs(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX permissions")
        log = self.tmp / "rooted.log"
        log.write_text("root owned\n", encoding="utf-8")
        log.chmod(0o000)
        try:
            result = self.run_wrapper(OS13_LOG=str(log))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("dry-run", result.stdout)
            self.assertIn("private log", result.stderr)
        finally:
            log.chmod(0o600)


if __name__ == "__main__":
    unittest.main()
