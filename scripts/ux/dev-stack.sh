#!/usr/bin/env bash
# Run the local stack of one worktree in either of two modes, watch it, and stop it.
#
#   dev  (hot reload)  console API :5050 + Astro dev server :4321 that proxies /api to it.
#                      Edit src/ files and the browser updates. Open http://localhost:4321.
#   run  (built)       `npm run build:local` once into dashboard/build (git-ignored), then only the
#                      console :5050 serves it (it prefers a newer build/ over the committed dist/).
#                      No hot reload; this is what the desktop app serves. Open http://127.0.0.1:5050.
#                      Rebuild after every change. Never commit dashboard/dist.
#
#   scripts/ux/dev-stack.sh dev | run | build | stop [console|dashboard|all] | status | restart-console | logs [console|dashboard]
#
# PIDs and logs (one per port) live in test-results/dev-stack. Only the server PIDs this script recorded are ever
# stopped, never a process found by name, and never another worktree's server.
# OSLAB_API_PORT / OSLAB_UI_PORT run a second stack beside the main one.
# Restart the console after changing cleanup-lab/engine or console/: it imports those modules once.
# The desktop window (Tauri, hot-reloading webview) is `cd app && npm run dev`; see lat.md/development.md.
# @lat: [[development#Dev stack]]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="$REPO/test-results/dev-stack"
API_PORT="${OSLAB_API_PORT:-5050}"
UI_PORT="${OSLAB_UI_PORT:-4321}"
mkdir -p "$STATE"
[ -f "$REPO/.oslab-env" ] && . "$REPO/.oslab-env"

http() { curl -s -o /dev/null -w '%{http_code}' --max-time 4 "$1" 2>/dev/null || true; }
owner_pid() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }
owner_name() { local p; p="$(owner_pid "$1")"; [ -n "$p" ] && echo "$(ps -o comm= -p "$p" | xargs basename) pid $p" || true; }
pidfile() { case "$1" in console) echo "$STATE/console-$API_PORT.pid" ;; *) echo "$STATE/dashboard-$UI_PORT.pid" ;; esac; }
recorded() { [ -f "$(pidfile "$1")" ] && cat "$(pidfile "$1")" || true; }
alive() { local p; p="$(recorded "$1")"; [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
wait_http() { local i=0; while [ "$i" -lt "$2" ]; do [ "$(http "$1")" = 200 ] && return 0; sleep 1; i=$((i+1)); done; return 1; }

# Record the PID that really listens on the port (the launcher scripts exit or fork).
record_server() { local p; p="$(owner_pid "$2")"; [ -n "$p" ] && echo "$p" >"$(pidfile "$1")"; }

start_console() {
  alive console && { echo "console already running (pid $(recorded console))"; return; }
  if [ -n "$(owner_pid "$API_PORT")" ]; then
    [ "$(http "http://127.0.0.1:$API_PORT/api/health")" = 200 ] && { echo "console already serving on :$API_PORT ($(owner_name "$API_PORT")); leaving it alone"; return; }
    echo "port $API_PORT is taken by $(owner_name "$API_PORT") and is not an os-lab console" >&2; return 1
  fi
  ( cd "$REPO" && exec nohup ./labctl ui --port "$API_PORT" >"$STATE/console-$API_PORT.log" 2>&1 </dev/null ) &
  wait_http "http://127.0.0.1:$API_PORT/api/health" 40 || { echo "console did not answer in 40 s; see $STATE/console-$API_PORT.log" >&2; return 1; }
  record_server console "$API_PORT"
}
start_dashboard() {
  alive dashboard && { echo "dashboard already running (pid $(recorded dashboard))"; return; }
  if [ -n "$(owner_pid "$UI_PORT")" ]; then
    [ "$(http "http://localhost:$UI_PORT/")" = 200 ] && { echo "dev server already serving on :$UI_PORT ($(owner_name "$UI_PORT")); leaving it alone"; return; }
    echo "port $UI_PORT is taken by $(owner_name "$UI_PORT") and does not answer" >&2; return 1
  fi
  : >"$STATE/dashboard-$UI_PORT.log"
  ( cd "$REPO/dashboard" && OSLAB_API="http://127.0.0.1:$API_PORT" exec nohup npm run dev -- --port "$UI_PORT" >"$STATE/dashboard-$UI_PORT.log" 2>&1 </dev/null ) &
  # `astro dev` allows one server per project: a second start only prints where the first one runs.
  local i=0 line
  while [ "$i" -lt 90 ]; do
    line="$(grep -h 'Dev server \(already \)\{0,1\}running at' "$STATE/dashboard-$UI_PORT.log" 2>/dev/null | head -1 || true)"
    [ -n "$line" ] && break; sleep 1; i=$((i+1))
  done
  [ -n "$line" ] || { echo "dashboard did not start in 90 s; see $STATE/dashboard-$UI_PORT.log" >&2; return 1; }
  case "$line" in *already*) echo "an Astro dev server already runs for this worktree: $(echo "$line" | sed 's/.*running at \(http[^ ]*\).*(pid \([0-9]*\)).*/\1 pid \2/')"
    echo "$line" | sed 's/.*(pid \([0-9]*\)).*/\1/' >"$(pidfile dashboard)"; return ;; esac
  wait_http "http://localhost:$UI_PORT/" 60 || { echo "dashboard did not answer; see $STATE/dashboard-$UI_PORT.log" >&2; return 1; }
  record_server dashboard "$UI_PORT"
}
stop_one() {
  local p; p="$(recorded "$1")"
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && kill "$p" 2>/dev/null || true
  rm -f "$(pidfile "$1")"
}
build() { echo "building dashboard/build (git-ignored)"; (cd "$REPO/dashboard" && npm run build:local >"$STATE/build.log" 2>&1) && echo "build ok" || { tail -20 "$STATE/build.log" >&2; return 1; }; }
status() {
  local api ui
  api=$(http "http://127.0.0.1:$API_PORT/api/health"); ui=$(http "http://localhost:$UI_PORT/")
  echo "console   :$API_PORT  http ${api:-000}  $(alive console && echo "ours, pid $(recorded console)" || echo "not started here")  $(owner_name "$API_PORT")"
  echo "dashboard :$UI_PORT  http ${ui:-000}  $(alive dashboard && echo "ours, pid $(recorded dashboard)" || echo "not started here")  $(owner_name "$UI_PORT")"
  [ "$api" = 200 ]
}

case "${1:-status}" in
  dev)  start_console; start_dashboard; status; echo "hot reload: http://localhost:$UI_PORT" ;;
  run)  build; start_console; status; echo "built app: http://127.0.0.1:$API_PORT" ;;
  build) build ;;
  stop) case "${2:-all}" in
          console) stop_one console ;; dashboard) stop_one dashboard ;;
          all) stop_one dashboard; stop_one console ;;
          *) echo "stop [console|dashboard|all]" >&2; exit 2 ;;
        esac; echo stopped ;;
  restart-console) stop_one console; sleep 1; start_console; status ;;
  logs) case "${2:-console}" in console) tail -n 60 "$STATE/console-$API_PORT.log" ;; *) tail -n 60 "$STATE/dashboard-$UI_PORT.log" ;; esac ;;
  status) status ;;
  *) sed -n '2,13p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
