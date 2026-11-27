#!/usr/bin/env bash
#
# Controller entrypoint — waits for the emulator container to appear on adb,
# then hands over to the Python pipeline. Everything the controller does is
# argv-driven and scope-guarded (see scripts/scope.py); this wrapper also
# refuses to connect adb anywhere that is not an in-scope lab device.
#
# Usage inside the container (set by docker-compose):
#   EMULATOR_HOST / EMULATOR_ADB_PORT point adb at the emulator sidecar.
#   Any extra args are passed straight to pipeline.py, e.g.:
#     docker compose run controller com.securebank.mobile --proxy 10.0.2.2:8080
set -euo pipefail

# The Compose service host/port are authoritative; we do not honour a baked-in
# ANDROID_SERIAL that could point adb at an unintended device.
EMULATOR_HOST="${EMULATOR_HOST:-emulator}"
EMULATOR_ADB_PORT="${EMULATOR_ADB_PORT:-5555}"
SERIAL="${EMULATOR_HOST}:${EMULATOR_ADB_PORT}"
CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-180}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scripts_dir="${here}/../scripts"

log() { printf '[controller] %s\n' "$*"; }

# Scope gate BEFORE any adb call: refuse to connect to a non-lab destination.
if ! python3 "${scripts_dir}/scope.py" --serial "${SERIAL}" >/dev/null; then
  log "ERROR: refusing to connect adb to out-of-scope device '${SERIAL}'"
  exit 2
fi

log "connecting adb to ${SERIAL} (timeout ${CONNECT_TIMEOUT}s)"
adb start-server >/dev/null 2>&1 || true

deadline=$(( $(date +%s) + CONNECT_TIMEOUT ))
until adb connect "${SERIAL}" 2>/dev/null | grep -qiE 'connected|already'; do
  if [ "$(date +%s)" -ge "${deadline}" ]; then
    log "ERROR: could not reach emulator at ${SERIAL} within ${CONNECT_TIMEOUT}s"
    exit 1
  fi
  sleep 3
done
log "adb connected to ${SERIAL}"

export ANDROID_SERIAL="${SERIAL}"

if [ "$#" -eq 0 ]; then
  log "no target package given — printing pipeline help"
  exec python3 "${scripts_dir}/pipeline.py" --help
fi

# First positional arg is the target package; the rest are pipeline flags.
exec python3 "${scripts_dir}/pipeline.py" "$@" -s "${SERIAL}"
