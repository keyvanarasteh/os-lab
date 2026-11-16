#!/usr/bin/env bash
# Prepare the native macOS lab.
#
#   setup-mac.sh            check prerequisites and print the next steps
#   setup-mac.sh --install  install Node (Homebrew), Appium and the XCUITest driver for this user
set -euo pipefail

. "$(dirname "$0")/lib.sh"
require_macos

INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

mkdir -p "$LAB_DIR/artifacts"
[ -f "$CONFIG" ] || cp "$MAC_DIR/config.env.example" "$CONFIG"

say "checking Xcode"
if ! command -v xcodebuild >/dev/null 2>&1 || ! xcodebuild -version >/dev/null 2>&1; then
  warn "Xcode is missing or not initialized"
  if command -v xcode-select >/dev/null 2>&1; then
    xcode-select --install || true
  fi
  echo "Install Xcode from the App Store or developer.apple.com, open it once, accept the licence, then re-run: make mac-setup"
  exit 1
fi
ok_version="$(xcodebuild -version | tr '\n' ' ')"
say "Xcode: $ok_version"

say "checking simulators"
if ! xcrun simctl list runtimes 2>/dev/null | grep -q '^iOS '; then
  warn "no iOS runtime installed; open Xcode > Settings > Components and install one"
else
  xcrun simctl list runtimes 2>/dev/null | grep '^iOS ' | sed 's/^/    /'
fi

# The native AX helper (MIR-09) is what makes element reads fast and rich; build it as part of
# setup instead of waiting for a manual "Build AX helper" click. Needs only swiftc.
say "native AX helper"
if [ -x "$MAC_DIR/build/ax-helper" ]; then
  say "already built"
elif command -v swiftc >/dev/null 2>&1; then
  bash "$MAC_DIR/macos-app.sh" build-ax-helper || warn "the AX helper did not build; element reads use the slower osascript path"
else
  warn "swiftc is missing (xcode-select --install); element reads use the slower osascript path"
fi
[ -f "$MAC_DIR/mac-lab.json" ] || say "optional tuning: cp ios-lab/mac/mac-lab.json.example ios-lab/mac/mac-lab.json"

if [ "$INSTALL" -eq 1 ]; then
  say "installing Node/Appium tooling"
  bash "$MAC_DIR/appium.sh" install
else
  say "no packages installed"
  echo "Next: make mac-setup INSTALL=1  (or install Node + Appium manually)"
fi

say "configuration"
echo "    device: $SIM_DEVICE"
echo "    runtime: $IOS_RUNTIME"
echo "    appium: http://${APPIUM_HOST}:${APPIUM_PORT}"
echo
echo "Next: make mac-doctor && make mac-sim"
