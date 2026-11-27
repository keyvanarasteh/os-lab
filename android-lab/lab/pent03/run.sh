#!/usr/bin/env bash
#
# run.sh — one-command launcher for the PENT-03 pipeline.
#
# Two modes:
#   --docker   bring the Alpine controller + emulator + mitmproxy stack up and
#              run the pipeline inside the container (needs Docker + /dev/kvm).
#   (default)  run the pipeline directly against an already-running emulator
#              using the host's adb / frida / objection install.
#
# Examples:
#   ./run.sh com.securebank.mobile
#   ./run.sh --docker com.securebank.mobile --proxy 10.0.2.2:8080
#   ./run.sh --dry-run com.securebank.mobile
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose_file="${here}/docker/docker-compose.yml"
pipeline="${here}/scripts/pipeline.py"

use_docker=0
args=()
for a in "$@"; do
  if [ "${a}" = "--docker" ]; then
    use_docker=1
  else
    args+=("${a}")
  fi
done

if [ "${#args[@]}" -eq 0 ]; then
  echo "usage: ./run.sh [--docker] <package> [pipeline flags...]" >&2
  echo "example: ./run.sh com.securebank.mobile --proxy 10.0.2.2:8080" >&2
  exit 2
fi

if [ "${use_docker}" -eq 1 ]; then
  echo "[run] bringing up emulator + mitmproxy..."
  docker compose -f "${compose_file}" up -d emulator mitmproxy
  echo "[run] running pipeline in controller container..."
  exec docker compose -f "${compose_file}" run --rm controller "${args[@]}"
fi

echo "[run] host mode — driving local adb"
exec python3 "${pipeline}" "${args[@]}"
