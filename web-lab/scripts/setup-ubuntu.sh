#!/usr/bin/env bash
# Web Lab setup: ensure a Rust toolchain, then build the engine.
# Called by `./labctl web setup` and the console's "Install dependencies" action.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/web-lab"

if ! command -v cargo >/dev/null 2>&1; then
  case "$(uname -s)" in
    Linux|Darwin)
      echo "cargo not found — installing the Rust toolchain (rustup, minimal profile)"
      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
      # shellcheck disable=SC1091
      . "$HOME/.cargo/env"
      ;;
    *)
      echo "cargo is required. Install Rust from https://rustup.rs, then run this setup again." >&2
      exit 1
      ;;
  esac
fi

cargo --version
echo "Building the Web Lab engine (cargo build --release)…"
(cd browser && cargo build --release)
echo "Engine built: web-lab/browser/target/release/weblab"
