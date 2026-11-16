#!/usr/bin/env bash
# CI helper: install minisign 0.12 from its official release, pinned by SHA-256.
set -euo pipefail
arch="$(uname -m)"
case "$arch" in x86_64|aarch64) ;; *) echo "Unsupported minisign architecture: $arch" >&2; exit 1 ;; esac
destination="${RUNNER_TEMP:-/tmp}/os-lab-minisign"
mkdir -p "$destination"
archive="$destination/minisign-0.12-linux.tar.gz"
curl -fL --silent --show-error \
  https://github.com/jedisct1/minisign/releases/download/0.12/minisign-0.12-linux.tar.gz \
  -o "$archive"
echo "9a599b48ba6eb7b1e80f12f36b94ceca7c00b7a5173c95c3efc88d9822957e73  $archive" | sha256sum -c -
tar -xOf "$archive" "minisign-linux/$arch/minisign" > "$destination/minisign"
chmod 755 "$destination/minisign"
if [ -n "${GITHUB_PATH:-}" ]; then echo "$destination" >> "$GITHUB_PATH"; fi
echo "minisign installed for $arch"
