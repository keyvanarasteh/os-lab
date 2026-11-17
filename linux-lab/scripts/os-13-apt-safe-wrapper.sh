#!/usr/bin/env bash
set -euo pipefail

# OS-13 - apt update/upgrade Safe Wrapper (Order + Dry-Run)
#
# One ordered pipeline for the three package commands the lab teaches:
#
#   step 1  apt-get update        refresh the index (writes /var/lib/apt/lists)
#   step 2  apt-get -s upgrade    simulate the plan, change nothing
#   step 3  apt-get -y upgrade    apply, only if step 1 succeeded in this run
#
# The order is enforced in code, not in a comment: step 3 refuses to run unless
# step 1 exited 0 in this same invocation, so a dead mirror, a broken DNS or a
# package lock cannot leave the machine half upgraded. Dry-run is the default;
# nothing on the system changes unless --apply is given.
#
# Exit codes: 0 = clean run, 1 = a guard or an apt step failed, 2 = usage error.

readonly PROG="${0##*/}"
readonly VERSION="1.1.0"

# apt-get comes from PATH on purpose: the offline tests in
# linux-lab/tests/test_os13_apt_safe_wrapper.py put a stub apt-get on PATH and
# assert the call order without touching the host package database.
APT_GET="${APT_GET:-apt-get}"
# Privilege prefix for --apply. Empty means "already privileged" (root, a
# container, or a test stub), and then no escalation is attempted.
# May contain options ("sudo -n", "doas -u root"); it is split into argv.
SUDO="${SUDO-sudo}"

MODE="dry-run"
ASSUME_YES=0
ALLOW_PARTIAL=0
ALLOW_REMOVALS=0
NONINTERACTIVE=0
SUBCOMMAND="upgrade"

UPDATE_OK=0
UPDATE_STATE="not run"
PLAN_COUNT=0
PLAN_INST=0
PLAN_REMV=0
NEW_INSTALLED=0
KEPT_BACK=0
REMAIN_AFTER=-1
PLAN_SIGNATURE=""
PRIV=()
APT_RC=0
APT_CAPTURE=""
APPLY_RC=0
LOG_LOCKED=0

# Per-user default: a root-owned /tmp/os-13-apt-last.log would make a later
# unprivileged dry-run fail on truncate. Override with OS13_LOG.
LOG_FILE="${OS13_LOG:-${TMPDIR:-/tmp}/os-13-apt-last-$(id -u).log}"
STEP_DIR=""

if [ -t 1 ]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_OK=''; C_WARN=''; C_ERR=''; C_DIM=''; C_OFF=''
fi

usage() {
  cat <<EOF
Usage: $PROG [--dry-run | --apply] [--yes] [--dist-upgrade] [--allow-partial]
             [--allow-removals] [--noninteractive] [--help]

Ordered apt upgrade pipeline. Step 1 (index refresh) must succeed before the
upgrade may start; there is no flag to skip it, that is the point.

  --dry-run        (default) plan only: show the ordered commands and the
                   simulated upgrade. Touches nothing and needs no root.
  --apply          run the sequence for real; refuses to upgrade when
                   apt-get update fails or only partially succeeds.
  --yes, -y        skip the apply confirmation prompt (unattended runs).
  --dist-upgrade   use dist-upgrade instead of upgrade (allows new packages
                   and removals; read the plan before you agree).
  --allow-partial  continue when some index files failed to download
                   (explicit override of the partial-index guard).
  --allow-removals apply a plan that removes packages. Required with --yes
                   when the simulated plan contains Remv actions.
  --noninteractive unattended upgrade: DEBIAN_FRONTEND=noninteractive is
                   passed to the elevated apt process (including through
                   sudo) and local config files are kept, so a dpkg conffile
                   prompt cannot hang an --yes run. Read the log afterwards.
  -h, --help       this help.
  --version        print the version and exit.

Environment:
  APT_GET   apt-get binary to call (default: apt-get; tests use a stub).
  SUDO      privilege prefix for --apply (default: sudo; set it empty when the
            caller is already privileged). Options are allowed: SUDO="sudo -n".
  OS13_LOG  log file (default: $LOG_FILE). Created 0600, never followed
            through a symlink.

Examples:
  sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh                # plan
  sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --apply        # upgrade
  sudo bash linux-lab/scripts/os-13-apt-safe-wrapper.sh --apply --yes  # unattended
EOF
}

hr()   { printf '%s\n' "------------------------------------------------------------------------"; }
say()  { printf '%s\n' "$*"; }
step() { printf '\n%s== %s ==%s\n' "$C_DIM" "$*" "$C_OFF"; }
ok()   { printf '%s[ok]%s   %s\n' "$C_OK" "$C_OFF" "$*"; }
warn() { printf '%s[warn]%s %s\n' "$C_WARN" "$C_OFF" "$*" >&2; }
err()  { printf '%s[fail]%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; }
die()  { err "$*"; exit 1; }

show_capture() {
  local file="$1" limit="${2:-30}" total
  total=$(wc -l <"$file" | tr -d ' ')
  if [ "$total" -le "$limit" ]; then
    sed 's/^/    /' "$file"
  else
    head -n $((limit / 2)) "$file" | sed 's/^/    /'
    printf '    ... %s line(s) hidden, full text in %s ...\n' "$((total - limit))" "$LOG_FILE"
    tail -n $((limit / 2)) "$file" | sed 's/^/    /'
  fi
}

# run_apt TAG ARGS... - run one apt command, keep its exact output, never let
# `set -e` abort before we can inspect the exit code.
run_apt() {
  local tag="$1"; shift
  local file="$STEP_DIR/$tag.log"
  local -a cmd=("${PRIV[@]}")
  # sudo strips the caller's environment; put the frontend on the command
  # line so an unattended apply cannot hang on a debconf prompt.
  if [ "$NONINTERACTIVE" -eq 1 ]; then
    cmd+=(env DEBIAN_FRONTEND=noninteractive)
  fi
  cmd+=("$APT_GET" "$@")
  {
    printf '# %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '$ %s\n' "${cmd[*]}"
  } >"$file"
  set +e
  LC_ALL=C "${cmd[@]}" >>"$file" 2>&1
  APT_RC=$?
  set -e
  APT_CAPTURE="$file"
  cat "$file" >>"$LOG_FILE"
  printf '\n' >>"$LOG_FILE"
}

# extract_number FILE ERE - last number matched by ERE, or 0.
extract_number() {
  local n
  n=$(grep -Eo "$2" "$1" 2>/dev/null | grep -Eo '[0-9]+' | tail -n 1 || true)
  printf '%s' "${n:-0}"
}

# diagnose FILE - turn the usual apt failures into the fix, not just a red line.
diagnose() {
  local file="$1" hint=""
  if grep -qiE 'Could not get lock|Unable to acquire the dpkg frontend lock' "$file"; then
    hint="lock: another apt/dpkg run (often unattended-upgrades) holds it; wait, or stop that unit first"
  elif grep -qiE 'Temporary failure in name resolution|Temporary failure resolving' "$file"; then
    hint="DNS: the mirror name does not resolve; check the resolver before blaming apt (OS-37)"
  elif grep -qiE 'No space left on device' "$file"; then
    hint="disk: apt cannot unpack archives on a full filesystem; reclaim space first (OS-15)"
  elif grep -qiE 'NO_PUBKEY|is not signed|no longer has a Release file' "$file"; then
    hint="signature: a repo key is missing or rotated; re-add the key or fix the source (OS-25)"
  elif grep -qiE '404  Not Found|Hash Sum mismatch' "$file"; then
    hint="metadata: stale mirror or a wrong suite in sources.list/sources.list.d (OS-25)"
  fi
  if [ -n "$hint" ]; then
    warn "hint: $hint"
  fi
}

# plan_signature FILE - stable "action package" pairs, so a re-check can be
# compared with the plan the operator actually saw.
plan_signature() {
  awk '$1 == "Inst" || $1 == "Remv" { print $1, $2 }' "$1" | sort
}

private_log() {
  local p
  p=$(mktemp "${TMPDIR:-/tmp}/os-13-apt-log.XXXXXXXX")
  chmod 600 "$p" 2>/dev/null || true
  LOG_FILE="$p"
  LOG_LOCKED=0
}

# open_log - pick a writable, private, non-symlink log and start this run's
# section. Never truncate through a symlink; never share a truncated file
# between concurrent runs.
open_log() {
  local want="$LOG_FILE"

  if [ -L "$want" ]; then
    warn "log path is a symlink; not writing through it: $want"
    private_log
    return 0
  fi

  if [ -e "$want" ] && [ ! -f "$want" ]; then
    warn "log path is not a regular file: $want"
    private_log
    return 0
  fi

  if ! ( umask 077; : >>"$want" ) 2>/dev/null; then
    warn "cannot write the log ($want); using a private log"
    private_log
    return 0
  fi
  chmod 600 "$want" 2>/dev/null || true
  LOG_FILE="$want"

  # Same-path concurrency: serialize with flock when we can. Without a lock
  # we append (never truncate), so a second run cannot erase the first.
  if command -v flock >/dev/null 2>&1; then
    local lock="$LOG_FILE.lock"
    if [ -L "$lock" ]; then
      warn "log lock is a symlink; appending without a shared lock"
    else
      ( umask 077; : >>"$lock" ) 2>/dev/null || true
      # Never put 2>/dev/null on this exec: it would stay in effect for the
      # whole script and swallow every later warn/err on stderr.
      if exec 9>>"$lock"; then
        if flock -n 9 2>/dev/null; then
          LOG_LOCKED=1
          : >"$LOG_FILE"
        else
          warn "another OS-13 run holds this log; using a private log"
          private_log
        fi
      fi
    fi
  fi

  {
    printf '===== OS-13 %s pid=%s mode=%s =====\n' \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$$" "$MODE"
  } >>"$LOG_FILE"
}

resolve_privileges() {
  PRIV=()
  if [ "$MODE" != "apply" ]; then
    return 0
  fi
  if [ "$(id -u)" -eq 0 ]; then
    return 0
  fi
  if [ -z "$SUDO" ]; then
    warn "not root and SUDO is empty; assuming this session may already write /var/lib/apt"
    return 0
  fi
  local -a parts=()
  read -r -a parts <<<"$SUDO"
  if [ "${#parts[@]}" -eq 0 ]; then
    die "--apply needs root: SUDO='$SUDO' did not name a program"
  fi
  if ! command -v "${parts[0]}" >/dev/null 2>&1; then
    die "--apply needs root: '${parts[0]}' is not installed. Run as root or set SUDO=<prefix>"
  fi
  PRIV=("${parts[@]}")
}

print_header() {
  local pretty="" space_target="/var/cache/apt" free_mb=""
  printf '%sOS-13 apt update/upgrade safe wrapper %s%s\n' "$C_DIM" "$VERSION" "$C_OFF"
  hr
  if [ "$MODE" = "dry-run" ]; then
    say "mode     : dry-run (plan only, nothing on this system changes)"
  else
    say "mode     : apply (runs in order, then changes the system)"
  fi
  say "step 3   : apt-get -y $SUBCOMMAND"
  say "apt-get  : $APT_GET${PRIV[*]:+ (via ${PRIV[*]})}"
  if [ -r /etc/os-release ]; then
    pretty=$(sed -n 's/^PRETTY_NAME="\{0,1\}\(.*\)"\{0,1\}$/\1/p' /etc/os-release | head -n 1)
  fi
  say "distro   : ${pretty:-unknown}"
  [ -d "$space_target" ] || space_target="/"
  free_mb=$(df -Pm "$space_target" 2>/dev/null | awk 'NR == 2 { print $4 }' || true)
  if [ -n "$free_mb" ]; then
    say "free     : ${free_mb} MB on $space_target"
    if [ "$free_mb" -lt 500 ]; then
      warn "low free space: a large upgrade needs room for the .deb archives it downloads (OS-15)"
    fi
  fi
  say "log      : $LOG_FILE"
}

preflight() {
  if ! command -v "$APT_GET" >/dev/null 2>&1; then
    die "apt-get not found (APT_GET='$APT_GET'); this wrapper only makes sense on Debian/Ubuntu"
  fi
  run_apt version --version
  if [ "$APT_RC" -ne 0 ]; then
    show_capture "$APT_CAPTURE" 10
    die "'$APT_GET --version' failed (exit $APT_RC); refusing to touch the package index"
  fi
  ok "preflight: $APT_GET is usable"
}

# step 1 ---------------------------------------------------------------------
do_update() {
  step "step 1/3 - refresh the package index (apt-get update)"
  if [ "$MODE" = "dry-run" ]; then
    say "[plan] $APT_GET update"
    say "       skipped: it rewrites /var/lib/apt/lists. --apply runs it for real"
    say "       and gates the upgrade on its exit code."
    UPDATE_STATE="skipped (dry-run)"
    return 0
  fi
  run_apt update update
  if [ "$APT_RC" -ne 0 ]; then
    show_capture "$APT_CAPTURE" 30
    diagnose "$APT_CAPTURE"
    err "apt-get update exited $APT_RC."
    err "GUARD: upgrade refused - the plan would be built on stale indexes."
    exit 1
  fi
  if grep -qiE 'Failed to fetch|Some index files failed to download' "$APT_CAPTURE"; then
    show_capture "$APT_CAPTURE" 20
    if [ "$ALLOW_PARTIAL" -ne 1 ]; then
      diagnose "$APT_CAPTURE"
      err "apt-get update exited 0 but some index files failed to download."
      err "GUARD: upgrade refused - a 'successful' update with partial indexes still"
      err "       plans against old metadata, which is the silent half of this failure."
      err "       Fix the source (OS-25), or re-run with --allow-partial if you mean it."
      exit 1
    fi
    warn "partial index failure ignored because --allow-partial was given"
    UPDATE_STATE="ok (partial indexes, --allow-partial)"
    UPDATE_OK=1
    return 0
  fi
  ok "index refreshed"
  UPDATE_STATE="ok"
  UPDATE_OK=1
}

# step 2 ---------------------------------------------------------------------
do_plan() {
  step "step 2/3 - simulate the upgrade plan (apt-get -s $SUBCOMMAND)"
  if [ "$MODE" = "apply" ] && [ "$UPDATE_OK" -ne 1 ]; then
    err "GUARD: no successful index refresh in this run - refusing to plan an upgrade."
    exit 1
  fi
  run_apt simulate -s "$SUBCOMMAND"
  if [ "$APT_RC" -ne 0 ]; then
    show_capture "$APT_CAPTURE" 30
    diagnose "$APT_CAPTURE"
    die "the simulated upgrade failed (exit $APT_RC); nothing was changed."
  fi
  show_capture "$APT_CAPTURE" 24

  PLAN_INST=$(awk '$1 == "Inst" { print $2 }' "$APT_CAPTURE" | sort -u | wc -l | tr -d ' ')
  PLAN_REMV=$(awk '$1 == "Remv" { print $2 }' "$APT_CAPTURE" | sort -u | wc -l | tr -d ' ')
  PLAN_COUNT=$((PLAN_INST + PLAN_REMV))
  PLAN_SIGNATURE=$(plan_signature "$APT_CAPTURE")
  NEW_INSTALLED=$(extract_number "$APT_CAPTURE" '[0-9]+ newly installed')
  KEPT_BACK=$(extract_number "$APT_CAPTURE" '[0-9]+ not upgraded')

  if [ "$PLAN_COUNT" -eq 0 ]; then
    ok "nothing to upgrade - the installed set is already current"
    return 0
  fi

  say ""
  say "packages that would be upgraded:"
  awk '$1 == "Inst" { print $2 }' "$APT_CAPTURE" | sort -u | head -n 15 | sed 's/^/    - /'
  if [ "$PLAN_INST" -gt 15 ]; then
    say "    ... and $((PLAN_INST - 15)) more (full list in $LOG_FILE)"
  fi
  if [ "$PLAN_REMV" -gt 0 ]; then
    say ""
    say "packages that would be REMOVED:"
    awk '$1 == "Remv" { print $2 }' "$APT_CAPTURE" | sort -u | head -n 15 | sed 's/^/    - /'
    if [ "$PLAN_REMV" -gt 15 ]; then
      say "    ... and $((PLAN_REMV - 15)) more (full list in $LOG_FILE)"
    fi
    warn "$PLAN_REMV package(s) would be removed; read this list before applying."
  fi
  if [ "$NEW_INSTALLED" -gt 0 ]; then
    warn "$NEW_INSTALLED new package(s) would be pulled in"
  fi
  if [ "$KEPT_BACK" -gt 0 ]; then
    say ""
    warn "$KEPT_BACK package(s) kept back: phased updates or new dependencies."
    warn "upgrade leaves them alone on purpose; --dist-upgrade shows the wider plan."
  fi
  ok "plan: $PLAN_INST package(s) upgradeable, $PLAN_REMV to remove, $KEPT_BACK kept back"
}

# step 3 ---------------------------------------------------------------------
do_apply() {
  local answer=""
  local -a up_args=(-y)

  if [ "$MODE" = "dry-run" ]; then
    step "step 3/3 - apply (apt-get -y $SUBCOMMAND)"
    say "[plan] $APT_GET -y $SUBCOMMAND"
    say "       skipped in dry-run; nothing was modified."
    return 0
  fi

  step "step 3/3 - apply the upgrade (apt-get -y $SUBCOMMAND)"
  if [ "$UPDATE_OK" -ne 1 ]; then
    err "GUARD: refusing to upgrade without a successful apt-get update in this run."
    err "       That order is the whole point of this wrapper; there is no override."
    exit 1
  fi
  if [ "$PLAN_COUNT" -eq 0 ]; then
    ok "no packages to upgrade - skipping apt-get $SUBCOMMAND"
    UPDATE_STATE="$UPDATE_STATE, upgrade skipped (nothing to do)"
    return 0
  fi

  if [ "$PLAN_REMV" -gt 0 ]; then
    if [ "$ASSUME_YES" -eq 1 ] && [ "$ALLOW_REMOVALS" -ne 1 ]; then
      die "the plan removes $PLAN_REMV package(s); unattended apply needs --allow-removals"
    fi
  fi

  if [ "$ASSUME_YES" -ne 1 ]; then
    if [ ! -t 0 ]; then
      die "confirmation needs a terminal; re-run with --yes for an unattended run"
    fi
    printf '%s will be upgraded, %s removed. Type "yes" to continue: ' \
      "$PLAN_INST package(s)" "$PLAN_REMV package(s)"
    read -r answer
    if [ "$answer" != "yes" ]; then
      say "aborted by the operator; nothing was changed."
      exit 0
    fi
  fi

  # Another apt run could change indexes or package state after the plan was
  # shown. Re-simulate and compare, so the operator never applies a plan they
  # did not review.
  step "step 3/3 - re-check the plan is still the one you reviewed"
  run_apt recheck -s "$SUBCOMMAND"
  if [ "$APT_RC" -ne 0 ]; then
    show_capture "$APT_CAPTURE" 20
    diagnose "$APT_CAPTURE"
    err "GUARD: re-check simulation failed; refusing to apply a stale plan."
    APPLY_RC=1
    return 0
  fi
  local now_sig
  now_sig=$(plan_signature "$APT_CAPTURE")
  if [ "$now_sig" != "$PLAN_SIGNATURE" ]; then
    err "GUARD: the upgrade plan changed after it was shown (another apt ran?)."
    err "       Refusing to apply a plan you did not review. Re-run this wrapper."
    APPLY_RC=1
    return 0
  fi
  ok "plan unchanged"

  if [ "$NONINTERACTIVE" -eq 1 ]; then
    up_args=(-y -o Dpkg::Options::=--force-confold)
  fi
  run_apt apply "${up_args[@]}" "$SUBCOMMAND"
  if [ "$APT_RC" -ne 0 ]; then
    show_capture "$APT_CAPTURE" 30
    diagnose "$APT_CAPTURE"
    err "apt-get $SUBCOMMAND exited $APT_RC."
    err "The index was fine, so this is a package-level failure (dpkg, disk, dependency)."
    err "Read the log above and fix the cause; do not re-run blindly."
    exit 1
  fi
  show_capture "$APT_CAPTURE" 20
  ok "upgrade finished"

  # post-check: re-simulate, so "finished" is a measurement and not a claim.
  run_apt verify -s "$SUBCOMMAND"
  if [ "$APT_RC" -eq 0 ]; then
    REMAIN_AFTER=$(awk '$1 == "Inst" { print $2 }' "$APT_CAPTURE" | sort -u | wc -l | tr -d ' ')
    if [ "$REMAIN_AFTER" -eq 0 ]; then
      ok "post-check: no upgradeable package left"
    else
      warn "post-check: $REMAIN_AFTER package(s) still upgradeable (kept back or phased)"
      warn "see: apt list --upgradable"
    fi
  else
    warn "post-check could not re-simulate (exit $APT_RC); treating the run as failed"
    APPLY_RC=1
  fi
  if [ -e /var/run/reboot-required ]; then
    warn "a reboot is required to finish this upgrade (/var/run/reboot-required exists)"
  fi
}

print_summary() {
  hr
  say "summary"
  say "  order     : update -> simulate -> $SUBCOMMAND"
  say "  update    : $UPDATE_STATE"
  say "  plan      : $PLAN_INST package(s) to upgrade, $PLAN_REMV to remove, $KEPT_BACK kept back"
  if [ "$MODE" = "apply" ] && [ "$REMAIN_AFTER" -ge 0 ]; then
    say "  remaining : $REMAIN_AFTER package(s) still upgradeable"
  fi
  say "  log       : $LOG_FILE"
  if [ "$MODE" = "dry-run" ]; then
    say ""
    say "nothing was changed. Run the same order for real with:"
    say "  sudo bash $0 --apply"
  fi
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) MODE="dry-run" ;;
      --apply) MODE="apply" ;;
      --yes|-y) ASSUME_YES=1 ;;
      --dist-upgrade) SUBCOMMAND="dist-upgrade" ;;
      --allow-partial) ALLOW_PARTIAL=1 ;;
      --allow-removals) ALLOW_REMOVALS=1 ;;
      --noninteractive) NONINTERACTIVE=1 ;;
      -h|--help) usage; exit 0 ;;
      --version) printf '%s %s\n' "$PROG" "$VERSION"; exit 0 ;;
      *) err "unknown argument: $1"; usage >&2; exit 2 ;;
    esac
    shift
  done

  if [ "$NONINTERACTIVE" -eq 1 ]; then
    export DEBIAN_FRONTEND=noninteractive
  else
    # A caller (or a CI runner image) may already export this. Dry-run and a
    # normal apply must not inherit it: only --noninteractive opts into it.
    unset DEBIAN_FRONTEND
  fi

  # Logs and step captures must not be world-readable: apt output can include
  # private repository hostnames and the full upgradeable set.
  umask 077

  open_log
  STEP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/os-13-apt.XXXXXX")
  trap 'rm -rf -- "$STEP_DIR"' EXIT

  resolve_privileges
  print_header
  preflight
  do_update
  do_plan
  do_apply
  print_summary
  exit "$APPLY_RC"
}

main "$@"
