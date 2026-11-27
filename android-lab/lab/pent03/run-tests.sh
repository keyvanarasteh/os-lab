#!/usr/bin/env bash
# Offline test runner for the PENT-03 module.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/tests"
exec python3 -m pytest -q "$@"
