#!/usr/bin/env bash
# Sahte readelf: son argümanın adına göre fixtures/pent05/<ad>.<h|l|d|s> dosyasını basar.
set -u
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
flag=""; target=""
for a in "$@"; do
  case "$a" in
    -h) flag=h ;; -l) flag=l ;; -d) flag=d ;; -s) flag=s ;; -W) ;;
    *) target="$a" ;;
  esac
done
f="$dir/$(basename "$target").$flag"
if [ -f "$f" ]; then cat "$f"; exit 0; fi
echo "readelf: Error: Not an ELF file - it has the wrong magic bytes at the start" >&2
exit 1
