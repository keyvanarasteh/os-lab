#!/usr/bin/env bash
# CLW-08: build the widget extension and reload bridge for embedding.
#
#   app/widget/build.sh                       universal (arm64 + x86_64)
#   app/widget/build.sh arm64                 one architecture
#
# Output (best effort, printed at the end):
#   app/widget/build/OSLabWidgets.appex
#   app/widget/build/OSLabWidgetReloader.framework
#
# Code signing stays with release-mac.sh, which signs both products with the
# release identity before the outer app is re-signed.
set -euo pipefail

WIDGET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHS="arm64 x86_64"
while [ $# -gt 0 ]; do
  case "$1" in
    arm64|x86_64) ARCHS="$1" ;;
    *) echo "usage: build.sh [arm64|x86_64]" >&2; exit 2 ;;
  esac
  shift
done

command -v xcodegen >/dev/null || { echo "xcodegen is required (brew install xcodegen)" >&2; exit 1; }
command -v xcodebuild >/dev/null || { echo "xcodebuild is required" >&2; exit 1; }

cd "$WIDGET_DIR"
xcodegen generate >/dev/null
mkdir -p build
xcodebuild -project OSLabWidgets.xcodeproj -scheme OSLabWidgets -configuration Release \
  ARCHS="$ARCHS" ONLY_ACTIVE_ARCH=NO -derivedDataPath build/DerivedData build >/dev/null 2>&1

APP_PATH="$(find build/DerivedData/Build/Products/Release -maxdepth 1 -name "OSLabWidgets.appex" | head -1)"
FW_PATH="$(find build/DerivedData/Build/Products/Release -maxdepth 1 -name "OSLabWidgetReloader.framework" | head -1)"
[ -n "$APP_PATH" ] && [ -n "$FW_PATH" ] || { echo "build produced no products" >&2; exit 1; }

rm -rf build/OSLabWidgets.appex build/OSLabWidgetReloader.framework
cp -R "$APP_PATH" build/OSLabWidgets.appex
cp -R "$FW_PATH" build/OSLabWidgetReloader.framework
echo "built: app/widget/build/OSLabWidgets.appex"
echo "built: app/widget/build/OSLabWidgetReloader.framework"
