#!/usr/bin/env bash
# Verify the running os-lab app's Cleanup panel over its local console.
#
# Reproduces the 2026-11-15 panel audit as one command: discovers the app's
# console port, probes every cleaner endpoint, runs the default and full
# catalog scans (measurement only — nothing is deleted), writes a JSON + MD
# report into ios-lab/artifacts/, and can apply the recommended quick-clean
# bookmarks (BOOKMARK=1) and record the screen during the run (RECORD=1).
#
# Usage:
#   make -C ios-lab mac-cleanup-verify                 # verify + scans + report
#   PORT=62635 make -C ios-lab mac-cleanup-verify      # skip port discovery
#   BOOKMARK=1 make -C ios-lab mac-cleanup-verify      # also set the bookmarks
#   RECORD=1 make -C ios-lab mac-cleanup-verify        # screencapture video of the run
set -euo pipefail

. "$(dirname "$0")/lib.sh"
require_macos

OUT_DIR="${LAB_DIR}/artifacts/cleanup-verify-$(date +%Y%m%d-%H%M%S)"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "$OUT_DIR"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# req METHOD PATH [JSON_BODY] — sets RES_BODY (headers stripped) and STATUS.
# Never called inside $(): command substitution would lose both globals.
req() {
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS --max-time 300 -w '\n%{http_code}' -X "$method")
  [ -n "$body" ] && args+=(-H 'Content-Type: application/json' -H 'X-OSLab: 1' -d "$body")
  local raw
  raw="$(curl "${args[@]}" "http://127.0.0.1:${PORT}${path}")" || die "console unreachable on $PORT"
  STATUS="$(printf '%s' "$raw" | tail -n1)"
  RES_BODY="$(printf '%s' "$raw" | sed '$d')"
}

# ── 1. Discover the running app's console port ─────────────────────────────────
if [ -z "${PORT:-}" ] && [ "$#" -ge 1 ]; then PORT="$1"; fi
if [ -z "${PORT:-}" ]; then
  # The app spawns: python -c '<watchdog>' web_ui.py <port> <app-pid>
  PORT="$(ps -axo command= | sed -n 's/.*web_ui\.py \([0-9][0-9]*\) .*/\1/p' | tail -n1)"
  [ -n "$PORT" ] || die "no running os-lab console found (start the app, or pass PORT=)"
fi
say "== os-lab Cleanup panel verification — console 127.0.0.1:$PORT =="

rec_pid=""
if [ "${RECORD:-0}" = 1 ]; then
  say "recording the run to $OUT_DIR/run.mov"
  screencapture -v "$OUT_DIR/run.mov" & rec_pid=$!
fi
trap '[ -n "$rec_pid" ] && kill -INT "$rec_pid" 2>/dev/null || true' EXIT

# ── 2. Readiness + endpoint table ──────────────────────────────────────────────
req GET /api/cleanup/status
[ "$STATUS" = 200 ] || die "cleanup status returned $STATUS (is the engine ready?)"
say "engine   $(printf '%s' "$RES_BODY" | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["engine"]["name"], s["engine"]["mode"], "—", s["state"])')"

fail=0
for ep in status catalog history jobs bookmarks monitor permissions volumes deep-roots relocation; do
  req GET "/api/cleanup/$ep"
  mark="ok"; [ "$STATUS" = 200 ] || { mark="FAIL($STATUS)"; fail=1; }
  printf '  %-38s %s\n' "GET /api/cleanup/$ep" "$mark"
done
# Known bug (PR #248): the dashboard GETs explorer/roots; a 404 here is the
# Space Explorer error state, not a network failure.
req GET /api/cleanup/explorer/roots
if [ "$STATUS" = 200 ]; then
  say "  GET /api/cleanup/explorer/roots   ok (PR #248 fix present)"
else
  say "  GET /api/cleanup/explorer/roots   FAIL($STATUS) — Space Explorer bug (fixed by PR #248; update the app)"
fi

# ── 3. Scans (measurement only) ────────────────────────────────────────────────
scan() { # scan LABEL IDS_JSON -> sets RES_BODY to the finished job JSON
  local label="$1" ids="$2" t0 id j state
  t0="$(date +%s)"
  req POST /api/cleanup/scan "{\"entryIds\": $ids}"
  [ "$STATUS" = 202 ] || [ "$STATUS" = 200 ] || die "$label scan start returned $STATUS"
  id="$(printf '%s' "$RES_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  while :; do
    sleep 2
    req GET "/api/cleanup/jobs/$id"
    j="$RES_BODY"
    state="$(printf '%s' "$j" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state"))')"
    [ "$state" = done ] || [ "$state" = failed ] || [ "$state" = cancelled ] && break
  done
  say "  $label scan: $state in $(( $(date +%s) - t0 ))s"
  [ "$state" = done ] || die "$label scan ended: $state"
  RES_BODY="$j"
}

say "== scans (measurement only) =="
req GET /api/cleanup/catalog
default_ids="$(printf '%s' "$RES_BODY" | python3 -c 'import json,sys; print(json.dumps([e["id"] for e in json.load(sys.stdin)["entries"] if e.get("defaultSelected")]))')"
req GET /api/cleanup/catalog
all_ids="$(printf '%s' "$RES_BODY" | python3 -c 'import json,sys; print(json.dumps([e["id"] for e in json.load(sys.stdin)["entries"]]))')"
scan default "$default_ids"
scan full "$all_ids"
printf '%s' "$RES_BODY" > "$OUT_DIR/full-scan-job.json"

python3 - "$OUT_DIR" "$STAMP" "$PORT" "$OUT_DIR/full-scan-job.json" <<'PYEOF'
import json, sys
out_dir, stamp, port, job_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
job = json.load(open(job_path))
res = job.get("result", {})
entries = res.get("entries", [])
total = res.get("totalBytes") or sum(e.get("sizeBytes") or 0 for e in entries)
rows = [{"id": e["id"], "name": e["name"], "risk": e.get("risk"),
         "sizeBytes": e.get("sizeBytes") or 0} for e in entries]
json.dump({"stamp": stamp, "port": port, "jobId": job.get("id"),
           "state": job["state"], "durationMs": res.get("durationMs"),
           "totalBytes": total, "entries": rows},
          open(f"{out_dir}/full-scan-result.json", "w"), indent=2)
human = lambda b: f"{b/1e9:.2f} GB" if b >= 1e9 else f"{b/1e6:.1f} MB"
lines = [f"# Cleanup panel verification — {stamp}", "",
         f"Console: 127.0.0.1:{port} · job {job.get('id')} · {res.get('durationMs')} ms · {len(rows)}-entry total {human(total)}", "",
         "| Size | Entry | Risk |", "|---|---|---|"]
for e in sorted(rows, key=lambda r: -r["sizeBytes"])[:12]:
    lines.append(f"| {human(e['sizeBytes'])} | {e['id']} | {e['risk']} |")
open(f"{out_dir}/report.md", "w").write("\n".join(lines) + "\n")
print(f"  total reclaimable {human(total)} — report in {out_dir}/report.md")
PYEOF

# ── 4. Quick-clean bookmarks (BOOKMARK=1) ──────────────────────────────────────
# Quick clean should be safe to run repeatedly without review: low-risk,
# regenerating caches of meaningful size. High/medium risk (shared-temp,
# temp) and privacy entries (browser history) stay out — they deserve the
# plan → confirm flow, not one-tap cleaning.
if [ "${BOOKMARK:-0}" = 1 ]; then
  say "== applying quick-clean bookmarks (low risk, ≥ 50 MB, largest first, max 8) =="
  picks="$(python3 - "$OUT_DIR/full-scan-result.json" <<'PYEOF'
import json, sys
rows = json.load(open(sys.argv[1]))["entries"]
picks = [e["id"] for e in sorted(rows, key=lambda r: -r["sizeBytes"])
         if e["risk"] == "low" and e["sizeBytes"] >= 50_000_000][:8]
print("\n".join(picks))
PYEOF
)"
  for id in $picks; do
    req POST /api/cleanup/bookmarks "{\"entryId\": \"$id\"}"
    [ "$STATUS" = 200 ] || [ "$STATUS" = 409 ] || say "  warning: add $id returned $STATUS"
    req POST /api/cleanup/bookmarks/update "{\"entryId\": \"$id\", \"quickClean\": true}"
    say "  bookmarked $id quickClean=true (add $STATUS, update $STATUS)"
  done
  req GET /api/cleanup/bookmarks
  printf '%s' "$RES_BODY" | python3 -c 'import json,sys; d=json.load(sys.stdin); bs=d["bookmarks"]; print(f"  bookmarks now: {len(bs)} quick-clean flagged: {sum(1 for b in bs if b.get(\"quickClean\"))}"); print(f"  store note: {d.get(\"error\")}")'
fi

say "== done — artifacts in $OUT_DIR =="
exit "$fail"
