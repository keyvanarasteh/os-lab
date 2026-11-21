#!/usr/bin/env bash
# Offline tests for auth-audit.sh using the fixtures in ./fixtures.
# Usage: ./tests/test-auth-audit.sh   (exit 0 = all passed)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT="$HERE/../auth-audit.sh"
SAMPLE="$HERE/fixtures/auth.log.sample"
CLEAN="$HERE/fixtures/auth.log.clean"
pass=0
fail=0

ok()  { pass=$((pass + 1)); echo "  PASS  $1"; }
bad() { fail=$((fail + 1)); echo "  FAIL  $1 (got: $2)"; }

# expect <description> <expected> <actual>
expect() {
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "$3, want $2"; fi
}
# rc_of <cmd...>: print the exit code without tripping set -e
rc_of() { set +e; "$@" >/dev/null 2>&1; local r=$?; set -e; echo "$r"; }
# jget <python-expr on d> <cmd...>: run cmd, parse its JSON stdout
jget() {
  local expr="$1"; shift
  set +e
  "$@" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print($expr)"
  set -e
}

echo "auth-audit tests"
expect "valid JSON, failed_logins=8"     8   "$(jget 'd["failed_logins"]' "$AUDIT" --file "$SAMPLE")"
expect "unique_ips=3"                    3   "$(jget 'd["unique_ips"]' "$AUDIT" --file "$SAMPLE")"
expect "threshold 4 flags 1 IP"          1   "$(jget 'len(d["suspicious_ips"])' "$AUDIT" --file "$SAMPLE")"
expect "top attacker is 203.0.113.50"    203.0.113.50 "$(jget 'd["suspicious_ips"][0]["ip"]' "$AUDIT" --file "$SAMPLE")"
expect "top attacker has 5 attempts"     5   "$(jget 'd["suspicious_ips"][0]["attempts"]' "$AUDIT" --file "$SAMPLE")"
expect "sudo_violations=4"               4   "$(jget 'd["sudo_violations"]' "$AUDIT" --file "$SAMPLE")"
expect "--threshold 2 flags 2 IPs"      2   "$(jget 'len(d["suspicious_ips"])' "$AUDIT" --file "$SAMPLE" --threshold 2)"
expect "--threshold 6 flags 0 IPs"       0   "$(jget 'len(d["suspicious_ips"])' "$AUDIT" --file "$SAMPLE" --threshold 6)"
expect "stdin input (--file -) works"    8   "$(set +e; cat "$SAMPLE" | "$AUDIT" --file - 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["failed_logins"])'; set -e)"

summary="$("$AUDIT" --file "$SAMPLE" --summary || true)"
[[ "$summary" == *SUSPICIOUS* && "$summary" == *203.0.113.50* ]] \
  && ok "--summary shows SUSPICIOUS table" || bad "--summary shows SUSPICIOUS table" "$summary"

expect "exit 1 on findings"              1 "$(rc_of "$AUDIT" --file "$SAMPLE")"
expect "exit 1 on sudo-only findings"    1 "$(rc_of "$AUDIT" --file "$SAMPLE" --threshold 99)"
expect "exit 0 on clean log"             0 "$(rc_of "$AUDIT" --file "$CLEAN")"
expect "exit 2 on missing file"          2 "$(rc_of "$AUDIT" --file /nonexistent/auth.log)"
expect "exit 2 on bad threshold"         2 "$(rc_of "$AUDIT" --file "$SAMPLE" --threshold 0)"
expect "exit 2 on file+journal conflict" 2 "$(rc_of "$AUDIT" --file "$SAMPLE" --journal)"
expect "--help exits 0"                  0 "$(rc_of "$AUDIT" --help)"
expect "bash -n auth-audit.sh"           0 "$(rc_of bash -n "$AUDIT")"
expect "bash -n test script"             0 "$(rc_of bash -n "$HERE/test-auth-audit.sh")"

echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
