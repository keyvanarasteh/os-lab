#!/usr/bin/env bash
# auth-audit.sh - thin wrapper around auth_audit.py (OS-04).
# Read-only audit of SSH brute-force attempts and unauthorized sudo use.
# Usage: ./auth-audit.sh [--file PATH | --journal] [--threshold N] [--summary]
# Exit codes: 0 clean, 1 findings, 2 usage/read error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/auth_audit.py"

if ! command -v python3 >/dev/null 2>&1; then
  echo "auth-audit: python3 is required (sudo apt install python3)" >&2
  exit 2
fi
if [[ ! -f "$PY" ]]; then
  echo "auth-audit: missing $PY" >&2
  exit 2
fi

exec python3 "$PY" "$@"
