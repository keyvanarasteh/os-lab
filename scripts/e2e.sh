#!/usr/bin/env bash
# os-lab dashboard e2e runner for parallel worktrees (plan items B, F, G).
#
# Picks a free port, takes a machine-wide lock so only one heavy run happens at a time,
# and runs Playwright on the specs a change touches. Works on macOS (bash 3.2) and Linux.
#
# Usage: scripts/e2e.sh [options] [spec…]
#
#   --changed[=<base>]   specs that cover files changed since <base> (default origin/master);
#                        on when no spec, --grep or --full is given (with --crawl alone it
#                        only chooses the routes to crawl)
#   <spec>…              these spec files (e2e/x.spec.ts or x.spec.ts)
#   --grep <text>        only tests whose title matches
#   --full               the whole suite; only before a PR
#   --workers <n>        parallel browsers (default 2)
#   --port <n>           fixed port (default: a free port in 4330-4399)
#   --lock | --no-lock   machine-wide lock (default on); --no-lock is refused with --full or --crawl
#   --screenshots=off|on-failure|on   (default on-failure)
#   --trace=off|on-failure|on         (default on-failure)
#   --video=off|on-failure            (default off; expensive, one failing spec only)
#   --crawl              full-page PNG of each selected route, plus index.html
#   --routes <list>      comma-separated routes to crawl (default: the changed routes)
#   --locales <list>|all locales to crawl (default en, plus changed locale files)
#   --widths <list>      desktop,phone (default desktop)
#   --out <dir>          output folder (default dashboard/test-results/<run-id>/)
#   --build | --no-build rebuild the test build in dashboard/.e2e-dist first (default: when
#                        the sources changed since its last build); dist/ is never touched
#   --dry-run            print the plan and exit
#   -h, --help           this help
#
# Each option has an environment variable that playwright.config.ts reads, so a plain
# `npx playwright test` follows the same defaults: OSLAB_E2E_PORT, OSLAB_E2E_WORKERS,
# OSLAB_E2E_REUSE, OSLAB_E2E_DIST, OSLAB_E2E_SCREENSHOTS, OSLAB_E2E_TRACE, OSLAB_E2E_VIDEO, OSLAB_E2E_OUT,
# OSLAB_CRAWL, OSLAB_CRAWL_ROUTES, OSLAB_CRAWL_LOCALES, OSLAB_CRAWL_WIDTHS.
# The lock lives in OSLAB_LOCK_DIR (default ${TMPDIR:-/tmp}).
#
# Examples:
#   scripts/e2e.sh --dry-run                       what --changed would run
#   scripts/e2e.sh e2e/cleanup.spec.ts --no-lock   one spec, no waiting
#   scripts/e2e.sh --changed --crawl --widths desktop,phone
#   scripts/e2e.sh --full                          once, right before the PR
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASH="$ROOT/dashboard"
# shellcheck source=lib/cache-env.sh
. "$ROOT/scripts/lib/cache-env.sh"

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die() { echo "e2e.sh: $*" >&2; exit 2; }

changed=""; changed_base="origin/master"; full=0; grep_text=""
workers="${OSLAB_E2E_WORKERS:-2}"; port="${OSLAB_E2E_PORT:-}"; lock=1
screenshots="on-failure"; trace="on-failure"; video="off"
crawl=0; routes=""; locales=""; widths="desktop"; out=""; build="auto"; dry=0
specs=()

while [ $# -gt 0 ]; do
  case "$1" in
    --changed) changed=1 ;;
    --changed=*) changed=1; changed_base="${1#*=}" ;;
    --full) full=1 ;;
    --grep) [ $# -ge 2 ] || die "--grep needs a value"; grep_text="$2"; shift ;;
    --grep=*) grep_text="${1#*=}" ;;
    --workers) [ $# -ge 2 ] || die "--workers needs a value"; workers="$2"; shift ;;
    --workers=*) workers="${1#*=}" ;;
    --port) [ $# -ge 2 ] || die "--port needs a value"; port="$2"; shift ;;
    --port=*) port="${1#*=}" ;;
    --lock) lock=1 ;;
    --no-lock) lock=0 ;;
    --screenshots=*) screenshots="${1#*=}" ;;
    --screenshots) screenshots="on" ;;
    --trace=*) trace="${1#*=}" ;;
    --video=*) video="${1#*=}" ;;
    --crawl) crawl=1 ;;
    --routes) [ $# -ge 2 ] || die "--routes needs a value"; routes="$2"; shift ;;
    --routes=*) routes="${1#*=}" ;;
    --locales) [ $# -ge 2 ] || die "--locales needs a value"; locales="$2"; shift ;;
    --locales=*) locales="${1#*=}" ;;
    --widths) [ $# -ge 2 ] || die "--widths needs a value"; widths="$2"; shift ;;
    --widths=*) widths="${1#*=}" ;;
    --out) [ $# -ge 2 ] || die "--out needs a value"; out="$2"; shift ;;
    --out=*) out="${1#*=}" ;;
    --build) build=1 ;;
    --no-build) build=0 ;;
    --dry-run) dry=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown option: $1 (see --help)" ;;
    *) specs+=("$1") ;;
  esac
  shift
done

case "$workers" in ''|*[!0-9]*|0) die "--workers must be a positive number" ;; esac
case "$screenshots" in off|on|on-failure) ;; *) die "--screenshots must be off, on-failure or on" ;; esac
case "$trace" in off|on|on-failure) ;; *) die "--trace must be off, on-failure or on" ;; esac
case "$video" in off|on-failure) ;; *) die "--video must be off or on-failure" ;; esac
if [ "$lock" = 0 ] && { [ "$full" = 1 ] || [ "$crawl" = 1 ]; }; then
  die "--no-lock is refused with --full or --crawl: those runs are heavy and must wait for the lock"
fi
if [ "$full" = 1 ] && [ "${#specs[@]}" -gt 0 ]; then die "--full and spec files exclude each other"; fi
# --changed is the default when nothing else is asked for. With --crawl alone it only picks
# the routes and locales to crawl, and runs no specs.
routes_only=0
if [ -z "$changed" ] && [ "$full" = 0 ] && [ "${#specs[@]}" -eq 0 ] && [ -z "$grep_text" ]; then
  changed=1
  [ "$crawl" = 1 ] && routes_only=1
fi
[ "$full" = 1 ] && changed=""

# Playwright's own names for the capture modes.
pw_screenshot="$screenshots"; [ "$screenshots" = on-failure ] && pw_screenshot="only-on-failure"
pw_trace="$trace"; [ "$trace" = on-failure ] && pw_trace="retain-on-failure"
pw_video="$video"; [ "$video" = on-failure ] && pw_video="retain-on-failure"

# --- What to run -------------------------------------------------------------
affected_json=""
if [ -n "$changed" ]; then
  files="$("$ROOT/scripts/lib/changed-files.sh" "$changed_base")"
  affected_json="$(printf '%s\n' "$files" | node "$DASH/scripts/affected.mjs" --stdin --json)"
  json_field() { printf '%s' "$affected_json" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const v=JSON.parse(s)[process.argv[1]];console.log(Array.isArray(v)?v.join(","):v)})' "$1"; }
  mode="$(json_field mode)"
  if [ "$routes_only" = 1 ]; then :
  elif [ "$mode" = full ]; then full=1; else
    IFS=',' read -r -a found <<< "$(json_field specs)"
    for spec in "${found[@]+"${found[@]}"}"; do [ -n "$spec" ] && specs+=("e2e/$spec"); done
  fi
  [ -z "$routes" ] && routes="$(json_field routes)"
  changed_locales="$(json_field locales)"
  if [ -z "$locales" ] && [ -n "$changed_locales" ]; then locales="en,$changed_locales"; fi
  unmapped="$(json_field unmapped)"
fi
[ -z "$locales" ] && locales="en"

normalized=()
for spec in "${specs[@]+"${specs[@]}"}"; do
  case "$spec" in
    dashboard/*) spec="${spec#dashboard/}" ;;
    e2e/*) ;;
    *) spec="e2e/$spec" ;;
  esac
  [ -f "$DASH/$spec" ] || die "no such spec: $spec"
  normalized+=("$spec")
done
specs=("${normalized[@]+"${normalized[@]}"}")
if [ "$crawl" = 1 ]; then specs+=("e2e/crawl.spec.ts"); fi

if [ "$full" = 0 ] && [ "${#specs[@]}" -eq 0 ] && [ -z "$grep_text" ]; then
  echo "e2e.sh: no dashboard change needs an e2e spec (base $changed_base). Nothing to run."
  echo "        Use --full, a spec file or --crawl to run something anyway."
  exit 0
fi

# --- Port, output, build ------------------------------------------------------
free_port() {
  python3 - <<'PY'
import socket
for port in range(4330, 4400):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        continue
    finally:
        s.close()
    print(port)
    break
PY
}
if [ -z "$port" ]; then
  if [ "$dry" = 1 ]; then port="(a free port in 4330-4399)"; else port="$(free_port)"; fi
  [ -n "$port" ] || die "no free port in 4330-4399; pass --port"
fi
run_id="$(date +%Y%m%d-%H%M%S)-$$"
[ -z "$out" ] && out="$DASH/test-results/$run_id"
case "$out" in /*) ;; *) out="$(pwd)/$out" ;; esac

# File times are unreliable after a checkout or rebase, so the build is keyed by the content
# of the sources: the last build writes this hash to test-results/.dist-source-hash.
source_hash() {
  (cd "$DASH" && {
    git ls-files -s -- src public astro.config.mjs package-lock.json
    git diff HEAD -- src public astro.config.mjs package-lock.json
    git ls-files --others --exclude-standard -- src public | while IFS= read -r f; do git hash-object "$f"; done
  } | git hash-object --stdin)
}
# Tests serve their own build in dashboard/.e2e-dist (git-ignored), never the committed dist/,
# so a test run cannot leave changes in dist/ or race another run that rebuilds it.
E2E_DIST="$DASH/.e2e-dist"
STAMP="$E2E_DIST/.source-hash"
current_hash="$(source_hash)"
needs_build=0
if [ "$build" = 1 ]; then needs_build=1
elif [ "$build" = auto ]; then
  if [ ! -f "$E2E_DIST/index.html" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$current_hash" ]; then needs_build=1; fi
fi

if [ "$full" = 1 ]; then what="the whole suite"; else what="${specs[*]+"${specs[*]}"}"; fi
[ -n "$grep_text" ] && what="$what (grep: $grep_text)"

count_tests() {
  local list
  # shellcheck disable=SC2086
  list="$(cd "$DASH" && OSLAB_CRAWL="$crawl" OSLAB_CRAWL_ROUTES="$routes" OSLAB_CRAWL_LOCALES="$locales" OSLAB_CRAWL_WIDTHS="$widths" \
    ./node_modules/.bin/playwright test --list "${pw_args[@]+"${pw_args[@]}"}" 2>/dev/null | tail -1)" || true
  printf '%s' "$list" | sed -n 's/^Total: \([0-9]*\) tests\{0,1\}.*/\1/p'
}

pw_args=()
if [ "$full" = 0 ]; then pw_args+=("${specs[@]+"${specs[@]}"}"); fi
[ -n "$grep_text" ] && pw_args+=(--grep "$grep_text")

print_plan() {
  echo "e2e plan"
  echo "  run:          $what"
  [ -n "$changed" ] && echo "  changed from: $changed_base"
  [ -n "${unmapped:-}" ] && echo "  unmapped:     $unmapped (smoke set added; add them to e2e/affected.json)"
  echo "  workers:      $workers"
  echo "  port:         $port"
  echo "  lock:         $([ "$lock" = 1 ] && echo on || echo off)"
  echo "  screenshots:  $screenshots   trace: $trace   video: $video"
  if [ "$crawl" = 1 ]; then
    echo "  crawl:        routes ${routes:-main routes}; locales $locales; widths $widths"
  fi
  echo "  build:        $([ "$needs_build" = 1 ] && echo "yes, into dashboard/.e2e-dist" || echo "no, dashboard/.e2e-dist is current")"
  echo "  output:       $out"
  if [ -x "$DASH/node_modules/.bin/playwright" ]; then
    local n; n="$(count_tests)"
    if [ -n "$n" ]; then
      # Rough: about 10 s per test per worker when the machine is not overloaded.
      echo "  tests:        $n (roughly $(( (n * 10 / workers + 59) / 60 )) min with $workers workers)"
    fi
  fi
}

print_plan
[ "$dry" = 1 ] && exit 0

[ -d "$DASH/node_modules" ] || die "dashboard/node_modules is missing; run scripts/worktree.sh doctor (or npm ci in dashboard/)"

# --- Lock ----------------------------------------------------------------------
LOCK="${OSLAB_LOCK_DIR:-${TMPDIR:-/tmp}}/os-lab-e2e.lock"
release_lock() { [ -n "${HAVE_LOCK:-}" ] && rm -rf "$LOCK"; HAVE_LOCK=""; }
if [ "$lock" = 1 ]; then
  waited=0
  while ! mkdir "$LOCK" 2>/dev/null; do
    holder="$(cat "$LOCK/pid" 2>/dev/null || true)"
    if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
      echo "e2e.sh: clearing a stale lock left by PID $holder"
      rm -rf "$LOCK"
      continue
    fi
    if [ -z "$holder" ] && [ "$waited" -ge 10 ]; then
      # A lock folder without a PID for 10 s: its owner died between mkdir and writing the PID.
      rm -rf "$LOCK"
      continue
    fi
    if [ $((waited % 30)) -eq 0 ]; then
      echo "e2e.sh: waiting for the e2e lock held by PID ${holder:-?} ($(cat "$LOCK/info" 2>/dev/null || echo unknown run))"
    fi
    sleep 2
    waited=$((waited + 2))
  done
  HAVE_LOCK=1
  echo "$$" > "$LOCK/pid"
  echo "$ROOT: $what" > "$LOCK/info"
  trap release_lock EXIT
  trap 'exit 130' INT TERM
fi

if [ "$needs_build" = 1 ]; then
  echo "e2e.sh: building dashboard/.e2e-dist (sources changed since the last e2e build)"
  rm -rf "$E2E_DIST"
  (cd "$DASH" && ./node_modules/.bin/astro build --outDir "$E2E_DIST" >/dev/null)
  echo "$current_hash" > "$STAMP"
fi

mkdir -p "$out"
start=$(date +%s)
set +e
(cd "$DASH" && \
  OSLAB_E2E_DIST="$E2E_DIST" OSLAB_E2E_PORT="$port" OSLAB_E2E_WORKERS="$workers" OSLAB_E2E_REUSE=0 \
  OSLAB_E2E_SCREENSHOTS="$pw_screenshot" OSLAB_E2E_TRACE="$pw_trace" OSLAB_E2E_VIDEO="$pw_video" \
  OSLAB_E2E_OUT="$out" OSLAB_CRAWL="$crawl" OSLAB_CRAWL_ROUTES="$routes" \
  OSLAB_CRAWL_LOCALES="$locales" OSLAB_CRAWL_WIDTHS="$widths" \
  ./node_modules/.bin/playwright test "${pw_args[@]+"${pw_args[@]}"}")
status=$?
set -e

if [ "$crawl" = 1 ] && ls "$out/crawl"/part-*.json >/dev/null 2>&1; then
  node - "$out/crawl" <<'JS'
const fs = require("fs"), path = require("path");
const dir = process.argv[2];
const shots = fs.readdirSync(dir).filter((f) => /^part-.*\.json$/.test(f))
  .flatMap((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")))
  .sort((a, b) => (a.route + a.locale + a.width).localeCompare(b.route + b.locale + b.width));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cards = shots.map((s) => `<figure><figcaption>${esc(s.route)} · ${esc(s.locale)} · ${esc(s.width)} · HTTP ${esc(s.status)}</figcaption><a href="${esc(s.file)}"><img loading="lazy" src="${esc(s.file)}"></a></figure>`).join("\n");
fs.writeFileSync(path.join(dir, "index.html"), `<!doctype html><meta charset="utf-8"><title>os-lab crawl</title>
<style>body{font:14px system-ui;margin:16px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}figure{margin:0}img{width:100%;border:1px solid #ccc}</style>
<h1>os-lab crawl: ${shots.length} pages</h1><main>${cards}</main>`);
console.log(`e2e.sh: crawl report ${path.join(dir, "index.html")}`);
JS
fi

elapsed=$(( $(date +%s) - start ))
echo "e2e.sh: finished in $((elapsed / 60))m$((elapsed % 60))s with exit code $status; output in $out"
exit "$status"
