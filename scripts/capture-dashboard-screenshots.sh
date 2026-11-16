#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base_url="${OSLAB_SCREENSHOT_URL:-http://127.0.0.1:5050}"
chrome="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
out="$repo/docs/media/screenshots"
mkdir -p "$out"

capture() {
  local name="$1" path="$2"
  "$chrome" --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
    --user-data-dir="$(mktemp -d /private/tmp/oslab-shot.XXXXXX)" \
    --window-size=1440,900 --virtual-time-budget=4000 \
    --screenshot="$out/$name.png" "$base_url$path" >/dev/null 2>&1
  echo "$out/$name.png"
}

capture android-overview /android/
capture android-workflows /android/workflows/
capture firewall-company /firewall/acme-academy/
capture firewall-audit '/firewall/acme-academy/#gaps'
capture firewall-persian /fa/firewall/

"$chrome" --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --user-data-dir="$(mktemp -d /private/tmp/oslab-promo.XXXXXX)" \
  --window-size=1200,630 --virtual-time-budget=3000 \
  --screenshot="$repo/docs/media/os-lab-promo.png" \
  "file://$repo/docs/media/promo.html" >/dev/null 2>&1
echo "$repo/docs/media/os-lab-promo.png"
