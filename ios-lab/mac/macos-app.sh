#!/usr/bin/env bash
# Status, doctor and one Appium mac2 smoke session for macOS applications on this Mac.
# The macOS Lab drives installed applications (Appium mac2); the iOS Simulator lives
# in the iOS Lab through run-simulator.sh.
#
#   macos-app.sh status|doctor|smoke|repl|click|input|element|build-ax-helper
set -uo pipefail

. "$(dirname "$0")/lib.sh"
require_macos

ACTION="${1:-status}"
shift 2>/dev/null || true  # the action word leaves the argument list: click/input/element read $1 onwards

# Appium installed by `appium.sh install` lives in the user's folder, so no administrator
# rights or global npm directory are needed. A copy already on PATH keeps working.
APPIUM_PREFIX="${OSLAB_APPIUM_HOME:-$HOME/.oslab/appium}"
MANAGED_BIN="$APPIUM_PREFIX/node_modules/.bin/appium"
AX_HELPER_SRC="$MAC_DIR/ax-helper.swift"
AX_HELPER_BIN="$MAC_DIR/build/ax-helper"
appium_bin() {
  if [ -x "$MANAGED_BIN" ]; then echo "$MANAGED_BIN"; else command -v appium 2>/dev/null || true; fi
}
ax_helper_state() {
  # The native AX reader (MIR-09): full attribute trees in milliseconds.
  if [ -x "$AX_HELPER_BIN" ]; then
    ok "native AX helper: built ($AX_HELPER_BIN)"
  elif command -v swiftc >/dev/null 2>&1; then
    warn "native AX helper: not built (Build AX helper in the macOS Lab page); element reads use the slower osascript path"
  else
    warn "native AX helper: unavailable (no swiftc; install the Xcode command line tools); element reads use the slower osascript path"
  fi
}

ok()   { printf '  [ok]   %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*"; }
bad()  { printf '  [FAIL] %s\n' "$*"; FAIL=1; }
progress() { printf '##PROGRESS %s/%s %s\n' "$1" "$2" "$3"; say "$3"; }

appium_state() {
  if curl -fsS --max-time 2 "http://${APPIUM_HOST}:${APPIUM_PORT}/status" >/dev/null 2>&1; then
    ok "Appium is listening on ${APPIUM_HOST}:${APPIUM_PORT}"
  else
    warn "Appium is not running on ${APPIUM_HOST}:${APPIUM_PORT} (make mac-appium)"
  fi
}

mac2_driver_state() {
  APPIUM="$(appium_bin)"
  [ -n "$APPIUM" ] || { warn "appium not found (Install Appium in the macOS Lab page)"; return; }
  if [ -x "$MANAGED_BIN" ]; then export APPIUM_HOME="$APPIUM_PREFIX/home"; fi
  if "$APPIUM" driver list --installed 2>/dev/null | grep -q mac2; then
    ok "mac2 driver installed"
  else
    warn "mac2 driver missing (appium driver install mac2, or Install Appium again)"
  fi
}

case "$ACTION" in
  status)
    echo "macos-lab (macOS applications)"
    echo "config      $CONFIG"
    echo "macos       $(sw_vers -productName) $(sw_vers -productVersion) ($(uname -m))"
    echo "appium"
    if command -v appium >/dev/null 2>&1; then
      echo "  $(appium --version 2>/dev/null || echo present)"
    else
      echo "  not installed"
    fi
    if curl -fsS --max-time 2 "http://${APPIUM_HOST}:${APPIUM_PORT}/status" >/dev/null 2>&1; then
      echo "  http://${APPIUM_HOST}:${APPIUM_PORT} ready"
    else
      echo "  not running"
    fi
    echo "mac2 driver"
    if command -v appium >/dev/null 2>&1 && appium driver list --installed 2>/dev/null | grep -q mac2; then
      echo "  installed"
    else
      echo "  missing"
    fi
    echo "resources"
    echo "  disk free $(df -h "$LAB_DIR" | awk 'NR==2 {print $4}')"
    echo "  memory    $(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 )) GB"
    ;;
  doctor)
    FAIL=0
    say "host"
    ok "$(sw_vers -productName) $(sw_vers -productVersion) ($(uname -m))"
    ok "cpu: $(sysctl -n hw.ncpu) cores"
    MEM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
    if [ "$MEM_GB" -lt 8 ]; then warn "memory: ${MEM_GB} GB (8 GB+ recommended for mac2 sessions)"; else ok "memory: ${MEM_GB} GB"; fi
    ok "disk free: $(df -h "$LAB_DIR" | awk 'NR==2 {print $4}')"

    say "displays"
    if command -v python3 >/dev/null 2>&1; then
      # Origin, size and backing scale per display (MIR-03): CGWindowBounds are points and
      # pixels are 2x on Retina, so remote coordinates can be reasoned about from this report.
      python3 - <<'PY' || warn "the display report failed"
import ctypes
cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
class Size(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]
class Rect(ctypes.Structure):
    _fields_ = [("origin", Point), ("size", Size)]
cg.CGGetActiveDisplayList.restype = ctypes.c_int32
cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
cg.CGDisplayBounds.restype = Rect
cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
cg.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
for name in ("CGDisplayModeGetWidth", "CGDisplayModeGetHeight", "CGDisplayModeGetPixelWidth", "CGDisplayModeGetPixelHeight"):
    fn = getattr(cg, name)
    fn.restype = ctypes.c_size_t
    fn.argtypes = [ctypes.c_void_p]
count = ctypes.c_uint32()
ids = (ctypes.c_uint32 * 16)()
if cg.CGGetActiveDisplayList(16, ids, ctypes.byref(count)) != 0:
    raise SystemExit(1)
for i in range(count.value):
    did = ids[i]
    r = cg.CGDisplayBounds(did)
    mode = cg.CGDisplayCopyDisplayMode(did)
    scale = 1.0
    if mode:
        points, pixels = cg.CGDisplayModeGetWidth(mode), cg.CGDisplayModeGetPixelWidth(mode)
        scale = round(pixels / points, 2) if points else 1.0
    print("  display %d: origin (%d, %d) size %dx%d scale %sx" % (
        i + 1, r.origin.x, r.origin.y, r.size.width, r.size.height, scale))
PY
    else
      warn "python3 not found; skipping the display report"
    fi

    say "appium"
    if command -v node >/dev/null 2>&1; then ok "node: $(node --version)"; else warn "node not found (brew install node)"; fi
    if command -v appium >/dev/null 2>&1; then
      ok "appium: $(appium --version 2>/dev/null || echo present)"
    else
      warn "appium not found (Install Appium in the macOS Lab page)"
    fi
    mac2_driver_state
    appium_state

    say "advanced element reads"
    ax_helper_state

    say "permissions"
    AX_PROBE="$(osascript -e 'tell application "System Events" to get position of window 1 of (first application process whose frontmost is true)' 2>&1 || true)"
    if [ -n "$AX_PROBE" ] && [ "${AX_PROBE#*assistive}" = "$AX_PROBE" ]; then
      ok "Accessibility: granted (element reads work)"
    else
      warn "Accessibility: not granted for the console — mac2 sessions, the REPL and the app mirror cannot read or click (System Settings > Privacy & Security > Accessibility)"
    fi
    warn "Screen Recording: grant it to the console if the app mirror stays empty or captures fail (System Settings > Privacy & Security > Screen Recording)"
    ok "config file: $CONFIG"

    echo
    if [ "$FAIL" -eq 0 ]; then echo "macOS Lab ready. Next: make mac-appium && make mac-app-smoke"; else echo "macOS Lab has failures."; fi
    exit "$FAIL"
    ;;
  smoke)
    TOTAL=4
    progress 1 $TOTAL "Checking the automation stack"
    APPIUM="$(appium_bin)"
    [ -n "$APPIUM" ] || die "Appium is not installed; use Install Appium in the macOS Lab page"
    if [ -x "$MANAGED_BIN" ]; then export APPIUM_HOME="$APPIUM_PREFIX/home"; fi
    "$APPIUM" driver list --installed 2>/dev/null | grep -q mac2 \
      || die "the Appium mac2 driver is not installed; run Install Appium again"
    curl -fsS --max-time 2 "http://${APPIUM_HOST}:${APPIUM_PORT}/status" >/dev/null 2>&1 \
      || die "Appium is not running on ${APPIUM_HOST}:${APPIUM_PORT}; start it first (Start Appium)"

    progress 2 $TOTAL "Preparing the mac2 session for Finder"
    CAPS="$(python3 -c 'import json; print(json.dumps({"capabilities": {"alwaysMatch": {
      "platformName": "mac", "appium:automationName": "mac2", "appium:bundleId": "com.apple.finder"}}}))')"

    progress 3 $TOTAL "Creating the mac2 session (grant Accessibility permission if macOS asks)"
    RESPONSE="$(curl -fsS --max-time 300 -X POST "http://${APPIUM_HOST}:${APPIUM_PORT}/session" \
      -H "Content-Type: application/json" -d "$CAPS")" \
      || die "the mac2 session failed; see the Appium log (${APPIUM_LOG}) and grant Accessibility permission if macOS asked"
    SESSION_ID="$(printf '%s' "$RESPONSE" | python3 -c 'import json, sys; print(json.load(sys.stdin)["value"]["sessionId"])' 2>/dev/null || true)"
    [ -n "$SESSION_ID" ] || die "Appium did not return a session id; see the Appium log (${APPIUM_LOG})"

    progress 4 $TOTAL "Closing the session"
    curl -fsS --max-time 30 -X DELETE "http://${APPIUM_HOST}:${APPIUM_PORT}/session/$SESSION_ID" >/dev/null 2>&1 || true
    say "macOS app smoke passed: mac2 session $SESSION_ID activated Finder"
    ;;
  repl)
    # Interactive mac2 REPL (macos-repl.mjs): a local operator tool with its own terminal
    # session. Never a console job — stdin does not survive the background job runner, and
    # the web console keeps its preview → confirm model for everything it runs.
    command -v node >/dev/null 2>&1 || die "node is required for the REPL (brew install node)"
    APPIUM="$(appium_bin)"
    [ -n "$APPIUM" ] || die "Appium is not installed; use Install Appium in the macOS Lab page"
    if [ -x "$MANAGED_BIN" ]; then export APPIUM_HOME="$APPIUM_PREFIX/home"; fi
    "$APPIUM" driver list --installed 2>/dev/null | grep -q mac2 \
      || die "the Appium mac2 driver is not installed; run Install Appium again"
    curl -fsS --max-time 2 "http://${APPIUM_HOST}:${APPIUM_PORT}/status" >/dev/null 2>&1 \
      || die "Appium is not running on ${APPIUM_HOST}:${APPIUM_PORT}; start it first (make mac-appium)"
    mkdir -p "$LAB_DIR/artifacts"
    exec node "$MAC_DIR/macos-repl.mjs" "http://${APPIUM_HOST}:${APPIUM_PORT}" "${MACOS_APP:-com.apple.finder}" "$LAB_DIR/artifacts"
    ;;
  click)
    # One real click on this Mac: bring the owning app forward, then post the event at the
    # point. Runs as a previewed lab action (macos-click) and, while control mode is armed,
    # directly from the app mirror. Needs Accessibility permission for the console.
    PID="${1:-}"; X="${2:-}"; Y="${3:-}"
    case "$PID$X$Y" in ''|*[!0-9]*) die "usage: $0 click <pid> <x> <y> (integers)" ;; esac
    osascript -e "tell application \"System Events\" to set frontmost of (first application process whose unix id is $PID) to true" >/dev/null 2>&1 \
      || warn "could not bring pid $PID forward; the click may land elsewhere"
    sleep 0.4
    osascript -l JavaScript -e '
      ObjC.import("CoreGraphics");
      function run(argv) {
        const p = $.CGPointMake(parseFloat(argv[0]), parseFloat(argv[1]));
        $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateMouseEvent($(), $.kCGEventMouseMoved, p, $.kCGMouseButtonLeft));
        $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateMouseEvent($(), $.kCGEventLeftMouseDown, p, $.kCGMouseButtonLeft));
        $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateMouseEvent($(), $.kCGEventLeftMouseUp, p, $.kCGMouseButtonLeft));
        return "clicked " + argv[0] + "," + argv[1];
      }
    ' "$X" "$Y" || die "the click could not be posted; grant Accessibility permission to the console"
    ;;
  input)
    # The mirror's action family (MIR-01): double-click, right-click, type and press-key,
    # with the same preview → confirm (or armed) pipeline as the single click. Fixed argv:
    # pid, x, y, kind, payload. `type` never sends Return — newlines are refused here and
    # by the console; Enter is its own explicit `key enter` action. Needs Accessibility.
    PID="${1:-}"; X="${2:-}"; Y="${3:-}"; KIND="${4:-}"; PAYLOAD="${5:-}"
    case "$PID$X$Y" in ''|*[!0-9]*) die "usage: $0 input <pid> <x> <y> <double|right|type|key|paste> [payload]" ;; esac
    osascript -e "tell application \"System Events\" to set frontmost of (first application process whose unix id is $PID) to true" >/dev/null 2>&1 \
      || warn "could not bring pid $PID forward; the action may land elsewhere"
    sleep 0.4
    case "$KIND" in
      double|right)
        osascript -l JavaScript -e '
          ObjC.import("CoreGraphics");
          function run(argv) {
            const p = $.CGPointMake(parseFloat(argv[0]), parseFloat(argv[1]));
            const right = argv[2] === "right";
            const button = right ? $.kCGMouseButtonRight : $.kCGMouseButtonLeft;
            const press = (type, state) => {
              const e = $.CGEventCreateMouseEvent($(), type, p, button);
              $.CGEventSetIntegerValueField(e, $.kCGMouseEventClickState, state);
              $.CGEventPost($.kCGHIDEventTap, e);
            };
            $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateMouseEvent($(), $.kCGEventMouseMoved, p, button));
            if (right) {
              press($.kCGEventRightMouseDown, 1); press($.kCGEventRightMouseUp, 1);
              return "right-clicked " + argv[0] + "," + argv[1];
            }
            press($.kCGEventLeftMouseDown, 1); press($.kCGEventLeftMouseUp, 1);
            press($.kCGEventLeftMouseDown, 2); press($.kCGEventLeftMouseUp, 2);
            return "double-clicked " + argv[0] + "," + argv[1];
          }
        ' "$X" "$Y" "$KIND" || die "the action could not be posted; grant Accessibility permission to the console"
        ;;
      type)
        # Printable ASCII only; the console caps the length and refuses newlines, so a typed
        # text can never submit a form on its own.
        case "$PAYLOAD" in
          ''|*[![:print:]]*) die "the text may only contain printable characters (no Return)" ;;
        esac
        [ "${#PAYLOAD}" -le 200 ] || die "the text is longer than 200 characters"
        ESCAPED="$(printf '%s' "$PAYLOAD" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
        osascript -e "tell application \"System Events\" to keystroke \"$ESCAPED\"" \
          || die "the text could not be typed; grant Accessibility permission to the console"
        say "typed ${#PAYLOAD} characters (no Return)"
        ;;
      key)
        case "$PAYLOAD" in
          tab|escape|delete|forward-delete|up|down|left|right|space|enter|return) ;;
          *) die "key must be one of: tab, escape, delete, forward-delete, up, down, left, right, space, enter" ;;
        esac
        osascript -l JavaScript -e '
          ObjC.import("CoreGraphics");
          function run(argv) {
            const codes = { tab: 48, escape: 53, delete: 51, "forward-delete": 117,
                            up: 126, down: 125, left: 123, right: 124, space: 49, enter: 36, return: 36 };
            const code = codes[argv[0]];
            $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateKeyboardEvent($(), code, true));
            $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateKeyboardEvent($(), code, false));
            return "pressed " + argv[0];
          }
        ' "$PAYLOAD" || die "the key could not be posted; grant Accessibility permission to the console"
        ;;
      paste)
        # MIR-07: clipboard paste — the one input that may carry newlines, gated behind an
        # explicit confirm even while armed (MIR-11). The clipboard is replaced, honestly.
        [ -n "$PAYLOAD" ] || die "a paste needs text"
        [ "${#PAYLOAD}" -le 2000 ] || die "the text is longer than 2000 characters"
        printf '%s' "$PAYLOAD" | pbcopy || die "the clipboard could not be written"
        osascript -e 'tell application "System Events" to keystroke "v" using command down' \
          || die "the paste could not be posted; grant Accessibility permission to the console"
        say "pasted ${#PAYLOAD} characters (the clipboard was replaced)"
        ;;
      *)
        die "input kind must be one of: double, right, type, key, paste"
        ;;
    esac
    ;;
  axset)
    # One AX value write through the native AX helper (MIR-07): fixed argv pid, AX window
    # index ("-" for none), path, identity, value. The helper fails closed when the tree
    # moved (STALE_PATH) instead of acting on the wrong node.
    PID="${1:-}"; WIN="${2:-}"; PATH_ARG="${3:-}"; IDENTITY="${4:-}"; VALUE="${5:-}"
    [ -x "$AX_HELPER_BIN" ] || die "the native AX helper is not built; use Build AX helper in the macOS Lab page"
    case "$PID" in ''|*[!0-9]*) die "usage: $0 axset <pid> <window|-> <path> <identity> <value>" ;; esac
    case "$WIN" in -|*[!0-9]*) [ "$WIN" = "-" ] || die "window must be an index or -" ;; esac
    case "$PATH_ARG" in ''|*[!0-9.]*) die "path must be a child-index chain like 0.3.1" ;; esac
    case "$IDENTITY" in *[!0-9a-f]*) die "identity must be the hex hash from the tree read" ;; esac
    [ -n "$VALUE" ] || die "a value is required"
    ARGS=(set --pid "$PID" --path "$PATH_ARG" --identity "$IDENTITY" --value "$VALUE")
    [ "$WIN" = "-" ] || ARGS+=(--window "$WIN")
    exec "$AX_HELPER_BIN" "${ARGS[@]}"
    ;;
  axperform)
    # One advertised AX action through the native AX helper (MIR-07): the helper refuses
    # actions the element does not advertise, so nothing is guessed.
    PID="${1:-}"; WIN="${2:-}"; PATH_ARG="${3:-}"; IDENTITY="${4:-}"; AX_ACTION="${5:-}"
    [ -x "$AX_HELPER_BIN" ] || die "the native AX helper is not built; use Build AX helper in the macOS Lab page"
    case "$PID" in ''|*[!0-9]*) die "usage: $0 axperform <pid> <window|-> <path> <identity> <action>" ;; esac
    case "$WIN" in -|*[!0-9]*) [ "$WIN" = "-" ] || die "window must be an index or -" ;; esac
    case "$PATH_ARG" in ''|*[!0-9.]*) die "path must be a child-index chain like 0.3.1" ;; esac
    case "$IDENTITY" in *[!0-9a-f]*) die "identity must be the hex hash from the tree read" ;; esac
    case "$AX_ACTION" in AX*) ;; *) die "action must be an advertised AX action (e.g. AXPress)" ;; esac
    ARGS=(perform --pid "$PID" --path "$PATH_ARG" --identity "$IDENTITY" --action "$AX_ACTION")
    [ "$WIN" = "-" ] || ARGS+=(--window "$WIN")
    exec "$AX_HELPER_BIN" "${ARGS[@]}"
    ;;
  element)
    # One WebDriver action on an existing mac2 session's element (MIR-05 deep inspect). The
    # session is opened and closed by the console (armed control mode); this never creates
    # or closes one, so a previewed job can also run it by session id. kind is click or type.
    SESSION="${1:-}"; ELEMENT="${2:-}"; KIND="${3:-}"; PAYLOAD="${4:-}"
    case "$SESSION" in ''|*[!A-Za-z0-9._-]*) die "invalid Appium session id" ;; esac
    case "$ELEMENT" in ''|*[!A-Za-z0-9._-]*) die "invalid element id" ;; esac
    curl -fsS --max-time 2 "http://${APPIUM_HOST}:${APPIUM_PORT}/status" >/dev/null 2>&1 \
      || die "Appium is not running on ${APPIUM_HOST}:${APPIUM_PORT}"
    case "$KIND" in
      click)
        curl -fsS --max-time 30 -X POST "http://${APPIUM_HOST}:${APPIUM_PORT}/session/$SESSION/element/$ELEMENT/click" \
          -H "Content-Type: application/json" -d '{}' >/dev/null \
          || die "the element click failed; the session may have expired (re-arm deep inspect)"
        say "clicked element $ELEMENT through the mac2 session"
        ;;
      type)
        case "$PAYLOAD" in
          ''|*[![:print:]]*) die "the text may only contain printable characters (no Return)" ;;
        esac
        [ "${#PAYLOAD}" -le 200 ] || die "the text is longer than 200 characters"
        TEXT="$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$PAYLOAD")" \
          || die "the text could not be encoded"
        curl -fsS --max-time 30 -X POST "http://${APPIUM_HOST}:${APPIUM_PORT}/session/$SESSION/element/$ELEMENT/value" \
          -H "Content-Type: application/json" -d "{\"text\": $TEXT}" >/dev/null \
          || die "the element typing failed; the session may have expired (re-arm deep inspect)"
        say "typed ${#PAYLOAD} characters into element $ELEMENT (no Return)"
        ;;
      *)
        die "element kind must be click or type"
        ;;
    esac
    ;;
  build-ax-helper)
    # Compile the native AX reader (MIR-09). Needs only the Xcode command line tools;
    # the binary lands in ios-lab/mac/build/ and the console picks it up on the next read.
    command -v swiftc >/dev/null 2>&1 || die "swiftc is not available; install the Xcode command line tools (xcode-select --install)"
    mkdir -p "$MAC_DIR/build"
    say "Compiling the native AX helper"
    swiftc -O "$AX_HELPER_SRC" -o "$AX_HELPER_BIN" || die "the AX helper did not compile; see the swiftc output above"
    FPID="$(pgrep -x Finder | head -1)"
    if [ -n "$FPID" ] && "$AX_HELPER_BIN" windows --pid "$FPID" >/dev/null 2>&1; then
      say "AX helper ready: $AX_HELPER_BIN"
    else
      warn "the helper built but its probe failed; grant Accessibility permission to the console for element reads"
    fi
    ;;
  *)
    die "usage: $0 status|doctor|smoke|repl|click|input|element|axset|axperform|build-ax-helper"
    ;;
esac
