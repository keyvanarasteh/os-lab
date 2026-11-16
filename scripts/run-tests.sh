#!/usr/bin/env bash
# os-lab local test runner — the CI replacement.
#
# Run locally alongside the enabled browser/content and package workflows.
# It mirrors what the old workflow did, plus repo-wide shell and graph checks.
#
# Usage:
#   scripts/run-tests.sh                 run everything (same as --all)
#   scripts/run-tests.sh --changed[=<base>]
#                                        only the stages and Python test files that the
#                                        files changed since <base> (default origin/master) touch
#   scripts/run-tests.sh --all           every stage, whatever changed
#   scripts/run-tests.sh --quick         unit suites only (stage 1); combines with --changed
#   scripts/run-tests.sh --dry-run       print the stages that would run and exit
#   scripts/run-tests.sh --no-venv       use the current environment, do not create .venv-test
#   scripts/run-tests.sh -h|--help       show this help
#
# Stages:
#   1. unit suites                          [required; all that --quick runs]
#      android (pytest) + PENT-07 golden suite, source-lab engine (pytest),
#      cleanup-lab reference and engine (unittest), cleanup-lab qrust-scan
#      (cargo test; skipped without cargo), OS-30 linux-lab hardening mocks (unittest)
#   2. android sample analysis pipeline     [smoke, non-fatal]
#   3. shell script syntax check (bash -n)  [required; --changed checks changed scripts only]
#   4. lat.md knowledge-graph check         [if `lat` is installed]
#   5. dashboard typecheck, translations, tooling tests, build freshness [if dashboard/node_modules exists]
#
# --changed picks stages from paths (scripts/lib/changed-files.sh, shared with scripts/e2e.sh):
#   android-lab/** -> android pytest + PENT-07   source-lab/** -> source-lab pytest
#   cleanup-lab/** -> cleanup unittest; cargo test only for cleanup-lab/reference/qrust-scan/**
#   linux-lab/** -> OS-30 mocks   *.sh -> bash -n on those files   dashboard/** -> stage 5
#   lat.md/** or a changed file with an @lat comment -> lat check
#   console/**, requirements files, scripts/run-tests.sh, scripts/lib/** -> everything
# Inside a Python lab only the test files that reach the changed modules run
# (scripts/lib/py_affected_tests.py); when that is unclear the lab's whole suite runs.
# Stage times are written to test-results/timings.json.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
ANDROID_LAB="$ROOT/android-lab/lab"
# shellcheck source=lib/cache-env.sh
. "$ROOT/scripts/lib/cache-env.sh"

QUICK=0
USE_VENV=1
MODE=all
BASE=origin/master
DRY=0
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --no-venv) USE_VENV=0 ;;
    --all) MODE=all ;;
    --changed) MODE=changed ;;
    --changed=*) MODE=changed; BASE="${arg#*=}" ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,/^set -uo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; BOLD=""; RESET=""
fi
PASS=0; FAIL=0; SKIP=0
hdr()  { printf '\n%s== %s ==%s\n' "$BOLD" "$*" "$RESET"; }
ok()   { printf '%s[ok]%s   %s\n'   "$GREEN"  "$RESET" "$*"; PASS=$((PASS+1)); }
bad()  { printf '%s[fail]%s %s\n'   "$RED"    "$RESET" "$*"; FAIL=$((FAIL+1)); }
skip() { printf '%s[skip]%s %s\n'   "$YELLOW" "$RESET" "$*"; SKIP=$((SKIP+1)); }

# --- Which stages run -----------------------------------------------------------
ALL_STAGES="android pent07 source cleanup_ref cleanup_engine qrust linux sample shell lat dashboard"
QUICK_STAGES="android pent07 source cleanup_ref cleanup_engine qrust linux"
STAGES=""
CHANGED_FILES=""
SHELL_FILES=""
SHARED=0
add() { for s in "$@"; do case " $STAGES " in *" $s "*) ;; *) STAGES="$STAGES $s" ;; esac; done; }
want() { case " $STAGES " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

if [ "$MODE" = all ]; then
  add $ALL_STAGES
else
  CHANGED_FILES="$("$ROOT/scripts/lib/changed-files.sh" "$BASE")" || exit 2
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in
      console/*|requirements*.txt|*/requirements*.txt|scripts/run-tests.sh|scripts/lib/*) SHARED=1; add $ALL_STAGES ;;
    esac
    case "$f" in
      android-lab/lab/scripts/*) add android pent07 sample ;;
      android-lab/*) add android pent07 ;;
      source-lab/*) add source ;;
      cleanup-lab/reference/qrust-scan/*) add qrust ;;
      cleanup-lab/reference/python/*) add cleanup_ref ;;
      cleanup-lab/engine/*) add cleanup_engine ;;
      cleanup-lab/*) add cleanup_ref cleanup_engine ;;
      linux-lab/*) add linux ;;
      lat.md/*) add lat ;;
      dashboard/*) add dashboard ;;
    esac
    case "$f" in *.sh) [ -f "$f" ] && SHELL_FILES="$SHELL_FILES
$f"; add shell ;; esac
    if [ -f "$f" ] && ! want lat && grep -q '@lat' "$f" 2>/dev/null; then add lat; fi
  done <<< "$CHANGED_FILES"
fi
if [ "$QUICK" = 1 ]; then
  kept=""; for s in $STAGES; do case " $QUICK_STAGES " in *" $s "*) kept="$kept $s" ;; esac; done; STAGES="$kept"
fi

# Python test files per lab: ALL (whole suite), NONE, or a newline-separated list.
py_pick() { # <lab dir> -> prints ALL, NONE or test files
  if [ "$MODE" = all ] || [ "$SHARED" = 1 ]; then echo ALL; return; fi
  printf '%s\n' "$CHANGED_FILES" | python3 "$ROOT/scripts/lib/py_affected_tests.py" --root "$1" --stdin 2>/dev/null || echo ALL
}
pick_label() { case "$1" in ALL|"") echo "whole suite" ;; NONE) echo "none" ;; *) echo "$(printf '%s\n' "$1" | wc -l | tr -d ' ') test file(s)" ;; esac; }
if command -v python3 >/dev/null 2>&1 && [ "$MODE" = changed ]; then
  want android && PICK_ANDROID="$(py_pick android-lab/lab)"
  want source && PICK_SOURCE="$(py_pick source-lab/engine)"
  want cleanup_ref && PICK_CLEANUP_REF="$(py_pick cleanup-lab/reference/python)"
  want cleanup_engine && PICK_CLEANUP_ENGINE="$(py_pick cleanup-lab/engine)"
fi
PICK_ANDROID="${PICK_ANDROID:-ALL}"; PICK_SOURCE="${PICK_SOURCE:-ALL}"
PICK_CLEANUP_REF="${PICK_CLEANUP_REF:-ALL}"; PICK_CLEANUP_ENGINE="${PICK_CLEANUP_ENGINE:-ALL}"

if [ "$MODE" = changed ] || [ "$DRY" = 1 ]; then
  printf '%smode:%s %s%s\n' "$BOLD" "$RESET" "$MODE" "$([ "$MODE" = changed ] && echo " (base $BASE, $(printf '%s\n' "$CHANGED_FILES" | sed '/^$/d' | wc -l | tr -d ' ') changed file(s))")"
  printf '%sstages:%s%s\n' "$BOLD" "$RESET" "${STAGES:- none}"
  want android && echo "  android tests: $(pick_label "$PICK_ANDROID")"
  want source && echo "  source-lab tests: $(pick_label "$PICK_SOURCE")"
  want cleanup_ref && echo "  cleanup reference tests: $(pick_label "$PICK_CLEANUP_REF")"
  want cleanup_engine && echo "  cleanup engine tests: $(pick_label "$PICK_CLEANUP_ENGINE")"
  if [ "$MODE" = changed ] && want shell; then echo "  shell scripts: $(printf '%s\n' "$SHELL_FILES" | sed '/^$/d' | wc -l | tr -d ' ') changed"; fi
fi
[ "$DRY" = 1 ] && exit 0
if [ -z "$STAGES" ]; then
  printf '%sNothing to test for these changes.%s Use --all to run everything.\n' "$YELLOW" "$RESET"
  exit 0
fi

# --- Timings (plan item S) --------------------------------------------------------
TIMINGS=""
STAGE_NAME=""; STAGE_START=0
stage_start() { STAGE_NAME="$1"; STAGE_START=$(date +%s); }
stage_end() {
  [ -n "$STAGE_NAME" ] || return 0
  local took=$(( $(date +%s) - STAGE_START ))
  TIMINGS="${TIMINGS}${TIMINGS:+,}
    {\"stage\": \"$STAGE_NAME\", \"seconds\": $took}"
  STAGE_NAME=""
}
RUN_START=$(date +%s)

# --- Resolve a Python with pytest ------------------------------------------
PY=""
pick_python() {
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; return 0; fi
  done
  return 1
}
ensure_pytest() {
  pick_python || { bad "no python3 found; install Python 3.11+"; return 1; }
  if "$PY" -c 'import pytest, cryptography' >/dev/null 2>&1; then return 0; fi
  if [ "$USE_VENV" = "1" ]; then
    local venv="$ROOT/.venv-test"
    if [ ! -d "$venv" ]; then
      printf 'creating test virtualenv at .venv-test ...\n'
      "$PY" -m venv "$venv" || { bad "could not create venv"; return 1; }
    fi
    if [ -f "$venv/bin/activate" ]; then
      # shellcheck disable=SC1091
      . "$venv/bin/activate"
    elif [ -f "$venv/Scripts/activate" ]; then
      # shellcheck disable=SC1091
      . "$venv/Scripts/activate"
    fi
    PY="$(command -v python)"
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet pytest requests cryptography
    if [ -f "$ANDROID_LAB/requirements.txt" ]; then
      "$PY" -m pip install --quiet -r "$ANDROID_LAB/requirements.txt" || true
    fi
  else
    "$PY" -m pip install --quiet pytest requests cryptography || { bad "pytest/cryptography unavailable and --no-venv set"; return 1; }
  fi
  "$PY" -c 'import pytest, cryptography' >/dev/null 2>&1
}

# pytest_suite <dir> <pick> <label>: the whole tests/ folder, or only the picked files.
pytest_suite() {
  local dir="$1" pick="$2" label="$3"
  if [ "$pick" = NONE ]; then skip "$label: no affected test files"; return; fi
  local files=(tests)
  if [ "$pick" != ALL ]; then
    files=()
    while IFS= read -r t; do [ -n "$t" ] && files+=("$t"); done <<< "$pick"
    label="$label (${#files[@]} affected file(s))"
  fi
  if ( cd "$dir" && "$PY" -m pytest "${files[@]}" -q ); then ok "$label"; else bad "$label"; fi
}
# unittest_suite <dir> <pick> <label>
unittest_suite() {
  local dir="$1" pick="$2" label="$3" status=0
  if [ "$pick" = NONE ]; then skip "$label: no affected test files"; return; fi
  if [ "$pick" = ALL ]; then
    ( cd "$dir" && "$PY" -m unittest discover -s tests -p 'test_*.py' -q ) || status=1
  else
    local n=0
    while IFS= read -r t; do
      [ -n "$t" ] || continue
      n=$((n+1))
      ( cd "$dir" && "$PY" -m unittest discover -s tests -p "$(basename "$t")" -q ) || status=1
    done <<< "$pick"
    label="$label ($n affected file(s))"
  fi
  if [ "$status" = 0 ]; then ok "$label"; else bad "$label"; fi
}

# --- Stage 1: android unit tests -------------------------------------------
if want android; then
  stage_start android
  hdr "Stage 1: android unit tests (pytest)"
  if ensure_pytest; then
    pytest_suite "$ANDROID_LAB" "$PICK_ANDROID" "android-lab/lab test suite"
  else
    bad "could not prepare a Python environment with pytest"
  fi
  stage_end
fi

# --- PENT-07 golden-file verification --------------------------------------
if want pent07; then
  stage_start pent07
  hdr "PENT-07 interceptor golden-file verification"
  [ -n "$PY" ] || pick_python
  if [ -n "$PY" ] && [ -f "$ANDROID_LAB/scripts/tamper_runner.py" ]; then
    if "$PY" "$ANDROID_LAB/scripts/tamper_runner.py" --verify-golden; then
      ok "PENT-07 golden-file verification"
    else
      bad "PENT-07 golden-file verification"
    fi
  else
    bad "tamper_runner.py unavailable for PENT-07 verification"
  fi
  stage_end
fi

# Source Lab runs separately to keep its package/test imports out of Android.
if want source; then
  stage_start source
  hdr "Source Lab engine tests (pytest)"
  if ensure_pytest; then
    pytest_suite "$ROOT/source-lab/engine" "$PICK_SOURCE" "source-lab/engine test suite"
  else
    bad "could not prepare a Python environment with pytest"
  fi
  stage_end
fi

# Cleanup Lab reference logic: standard library only, so plain unittest is enough.
if want cleanup_ref; then
  stage_start cleanup_ref
  hdr "Cleanup Lab reference tests (unittest)"
  if [ -n "$PY" ] || pick_python; then
    unittest_suite "$ROOT/cleanup-lab/reference/python" "$PICK_CLEANUP_REF" "cleanup-lab/reference/python"
  else
    bad "no python3 for cleanup-lab/reference/python"
  fi
  stage_end
fi

# Cleanup Lab engine: stdlib-only package, plain unittest is enough (CLN-01).
if want cleanup_engine; then
  stage_start cleanup_engine
  hdr "Cleanup Lab engine tests (unittest)"
  if [ -n "$PY" ] || pick_python; then
    unittest_suite "$ROOT/cleanup-lab/engine" "$PICK_CLEANUP_ENGINE" "cleanup-lab/engine"
  else
    bad "no python3 for cleanup-lab/engine"
  fi
  stage_end
fi

if want qrust; then
  stage_start qrust
  hdr "Cleanup Lab qrust-scan crate (cargo test)"
  if command -v cargo >/dev/null 2>&1; then
    if ( cd "$ROOT/cleanup-lab/reference/qrust-scan" && cargo test --quiet ); then
      ok "cleanup-lab/reference/qrust-scan"
    else
      bad "cleanup-lab/reference/qrust-scan"
    fi
  else
    skip "cargo not installed; qrust-scan tests not run"
  fi
  stage_end
fi

# OS-30 Ubuntu hardening checker: stdlib unittest with fake system commands
# and temporary fixtures; it changes nothing on the host.
if want linux; then
  stage_start linux
  hdr "OS-30 linux-lab hardening tests (unittest)"
  if [ -n "$PY" ] || pick_python; then
    if ( cd "$ROOT" && "$PY" -m unittest discover -s linux-lab/tests -q ); then
      ok "linux-lab/tests (OS-30 hardening)"
    else
      bad "linux-lab/tests (OS-30 hardening)"
    fi
  else
    bad "no python3 for linux-lab/tests (OS-30 hardening)"
  fi
  stage_end
fi

if [ "$QUICK" = "1" ]; then
  printf '\n%s--quick: skipping remaining stages%s\n' "$YELLOW" "$RESET"
fi

# --- Stage 2: sample analysis smoke test ---------------------------------
if want sample; then
  stage_start sample
  hdr "Stage 2: android sample analysis pipeline (smoke)"
  [ -n "$PY" ] || pick_python
  if [ -n "$PY" ] && [ -f "$ANDROID_LAB/scripts/create_sample_apk.py" ]; then
    if ( cd "$ANDROID_LAB" \
         && "$PY" scripts/create_sample_apk.py \
         && "$PY" scripts/app_analyzer.py scripts/vulnerable-test.apk artifacts/security-scan \
         && "$PY" scripts/app_reporter.py artifacts/security-scan/app-analysis.json -o artifacts/security-scan ); then
      ok "sample analysis + report generated in android-lab/lab/artifacts/security-scan"
    else
      skip "sample analysis pipeline did not complete (non-fatal; needs the analysis deps)"
    fi
    rm -f "$ANDROID_LAB/scripts/vulnerable-test.apk"
  else
    skip "sample analysis scripts unavailable"
  fi
  stage_end
fi

# --- Stage 3: shell script syntax --------------------------------------
if want shell; then
  stage_start shell
  hdr "Stage 3: shell script syntax (bash -n)"
  sh_fail=0; sh_count=0
  check_sh() {
    sh_count=$((sh_count+1))
    bash -n "$1" 2>/dev/null || { printf '  %s[fail]%s %s\n' "$RED" "$RESET" "${1#"$ROOT"/}"; sh_fail=$((sh_fail+1)); }
  }
  if [ "$MODE" = changed ] && [ "$SHARED" = 0 ] && [ -n "$(printf '%s' "$SHELL_FILES" | sed '/^$/d')" ]; then
    while IFS= read -r s; do [ -n "$s" ] && check_sh "$ROOT/$s"; done <<< "$SHELL_FILES"
  else
    while IFS= read -r -d '' s; do check_sh "$s"; done \
      < <(find "$ROOT" \( -type d \( -name .git -o -name node_modules \) \) -prune -o -type f -name '*.sh' -print0)
  fi
  if [ "$sh_fail" -eq 0 ]; then ok "all $sh_count shell scripts parse"; else bad "$sh_fail of $sh_count shell scripts failed bash -n"; fi
  stage_end
fi

# --- Stage 4: lat graph check ------------------------------------------
if want lat; then
  stage_start lat
  hdr "Stage 4: lat.md knowledge graph"
  if command -v lat >/dev/null 2>&1; then
    if lat check >/dev/null 2>&1; then ok "lat check"; else bad "lat check (run: lat check)"; fi
  else
    skip "lat not installed (npm i -g lat.md) — skipping graph check"
  fi
  stage_end
fi

# --- Stage 5: dashboard ------------------------------------------------
# Typecheck, translations and the tooling tests. Then rebuild into a temp folder and compare
# with the committed dashboard/dist (plan item D): on master a stale dist fails, because hosts
# without Node serve it; on feature branches dist is rebuilt after merge, so it only warns,
# and --changed skips the build.
if want dashboard; then
  stage_start dashboard
  hdr "Stage 5: dashboard (typecheck, translations, tooling tests, build freshness)"
  DASH="$ROOT/dashboard"
  if [ -e "$DASH/node_modules" ] && command -v node >/dev/null 2>&1; then
    if ( cd "$DASH" && ./node_modules/.bin/astro sync >/dev/null && ./node_modules/.bin/tsc --noEmit ); then ok "dashboard typecheck"; else bad "dashboard typecheck (cd dashboard && npm run check)"; fi
    if ( cd "$DASH" && node scripts/check-translations.mjs >/dev/null ); then ok "dashboard translations"; else bad "dashboard translations (cd dashboard && npm run test:i18n)"; fi
    if ( cd "$DASH" && node --test scripts/affected.test.mjs scripts/i18n-merge.test.mjs >/dev/null 2>&1 ); then ok "tooling tests (e2e map, locale merge)"; else bad "tooling tests (cd dashboard && npm run test:tooling)"; fi
    branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    if [ "$branch" != master ] && [ "$MODE" = changed ]; then
      skip "dist freshness: rebuilt on master after merge (plan item D); run --all to check"
    else
      # Same filesystem as the project: Astro moves build files with rename(2)
      TMP_OUT="$(mktemp -d "$DASH/.check-build.XXXXXX")"
      if ( cd "$DASH" && ./node_modules/.bin/astro build --outDir "$TMP_OUT" >/dev/null 2>&1 ); then
        if diff -rq "$TMP_OUT" "$DASH/dist" >/dev/null 2>&1; then
          ok "dashboard/dist matches the sources"
        elif [ "$branch" = master ]; then
          bad "dashboard/dist is stale on master — the dashboard-dist workflow should rebuild it"
        else
          skip "dashboard/dist differs from the sources; expected on a feature branch, master rebuilds it after merge"
        fi
      else
        bad "dashboard build failed (cd dashboard && npm run build)"
      fi
      rm -rf "$TMP_OUT"
    fi
  else
    skip "dashboard dependencies not installed (scripts/worktree.sh doctor, or cd dashboard && npm ci) — skipping"
  fi
  stage_end
fi

# --- Summary ----------------------------------------------------------------
TOTAL=$(( $(date +%s) - RUN_START ))
mkdir -p "$ROOT/test-results"
cat > "$ROOT/test-results/timings.json" <<JSON
{
  "mode": "$MODE",
  "quick": $([ "$QUICK" = 1 ] && echo true || echo false),
  "finished": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "total_seconds": $TOTAL,
  "stages": [${TIMINGS}
  ]
}
JSON
hdr "Summary"
printf 'stage times (s):'; printf '%s\n' "$TIMINGS" | sed -n 's/.*"stage": "\([^"]*\)", "seconds": \([0-9]*\).*/ \1=\2/p' | tr -d '\n'; printf '  total=%s  (test-results/timings.json)\n' "$TOTAL"
printf '%s%d passed%s, %s%d failed%s, %s%d skipped%s\n' \
  "$GREEN" "$PASS" "$RESET" "$RED" "$FAIL" "$RESET" "$YELLOW" "$SKIP" "$RESET"
[ "$FAIL" -eq 0 ] || exit 1
printf '%sAll required checks passed.%s\n' "$GREEN" "$RESET"
