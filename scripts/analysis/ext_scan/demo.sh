#!/usr/bin/env bash
# PENT-02 demo: runs the scanner on the lab samples and the tests, with short
# captions, so the whole flow (run -> output -> verification) can be recorded.
# Usage: bash scripts/analysis/ext_scan/demo.sh   (PAUSE=3 for a faster run)
set -euo pipefail

cd "$(dirname "$0")/.."                  # scripts/analysis
PY="${PYTHON:-python3}"
"$PY" -c "import sys" 2>/dev/null || PY=python   # Kali/Linux: python3, Windows: python
PAUSE="${PAUSE:-10}"
export PYTHONIOENCODING=utf-8

say() { printf '\n\033[1;33m# %s\033[0m\n' "$1"; sleep 2; }
run() {
  printf '\033[1;32m$ %s\033[0m\n' "$1"
  sleep 1
  # A failing step stops the demo, so a broken run can never look successful.
  # (The --fail-on steps below print their exit code themselves and return 0.)
  if ! bash -c "$1"; then
    printf '\n\033[1;31mFAILED: %s\033[0m\n' "$1"
    exit 1
  fi
  sleep "$PAUSE"
}

clear
printf '\033[1;36mPENT-02 - Browser Extension Injection & Malicious Script Audit Engine\033[0m\n'
printf '\033[1;36m%s\033[0m\n' "$(uname -sr) - $("$PY" --version)"
say "Scores an extension 0-100 from its permissions (manifest) and its code, before install."
say "All samples were written for this task; every URL points to 127.0.0.1 (lab only)."
sleep 2

clear
say "1) Clean extension. 'eval(' appears only in a comment and a string: no false alarm expected."
run "head -5 ext_scan/lab/clean-notes/popup.js"
run "$PY -m ext_scan scan ext_scan/lab/clean-notes"

clear
say "2) Over-privileged: harmless code, but <all_urls>, cookies, history, nativeMessaging."
run "$PY -m ext_scan scan ext_scan/lab/over-privileged"
say "Permissions alone stop at 40 (MEDIUM). CRITICAL needs dangerous code."
sleep 2

clear
say "3) Two-stage loader ('clean dropper'): downloads code and runs it with a hidden eval."
run "grep -n '' ext_scan/lab/two-stage-loader/sw.js | sed -n '10,15p'"
run "$PY -m ext_scan scan ext_scan/lab/two-stage-loader"
say "Hidden eval, fetch -> eval (two-stage), cookie exfiltration and hidden iframe, with line numbers."
sleep 2

clear
say "4) CI gate: exit code 3 when the grade is HIGH or worse, 0 when clean."
run "$PY -m ext_scan scan ext_scan/lab/two-stage-loader --fail-on high >/dev/null; echo \"exit code: \$?\""
run "$PY -m ext_scan scan ext_scan/lab/clean-notes --fail-on high >/dev/null; echo \"exit code: \$?\""

clear
say "5) Tests (also a stage of scripts/run-tests.sh)."
run "$PY -m pytest ext_scan/tests -q"

say "Report: docs/tasks/PENT-02/REPORT.md  -  done, thank you."
