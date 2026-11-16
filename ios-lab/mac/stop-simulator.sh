#!/usr/bin/env bash
# Shut down iOS Simulators (all of them, or one device with --device UDID) and quit Simulator.app.
#
#   stop-simulator.sh                 shut every simulator down
#   stop-simulator.sh --device UDID   shut one device down; the others keep running
set -euo pipefail

. "$(dirname "$0")/lib.sh"
require_macos

DEVICE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --device)
      [ $# -ge 2 ] || die "--device needs a UDID"
      DEVICE="$2"; shift 2 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

if [ -n "$DEVICE" ]; then
  say "shutting down simulator $DEVICE"
  xcrun simctl shutdown "$DEVICE" 2>/dev/null || true
  say "stopped"
  exit 0
fi

say "shutting down simulators"
xcrun simctl shutdown all 2>/dev/null || true
osascript -e 'tell application "Simulator" to quit' >/dev/null 2>&1 || true
rm -f "$MAC_DIR/.sim-device"
say "stopped"
