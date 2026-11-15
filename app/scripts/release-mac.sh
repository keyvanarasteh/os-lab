#!/usr/bin/env bash
# Build, sign, notarize and (optionally) publish the os-lab macOS app as a universal DMG.
#
#   app/scripts/release-mac.sh                 build + sign + notarize + verify, upload nothing
#   app/scripts/release-mac.sh --publish       ...and create/update the GitHub release app-v<version>
#   app/scripts/release-mac.sh --no-notarize   build + sign only (no Apple upload) for a local check
#   app/scripts/release-mac.sh --arch arm64    one architecture instead of universal
#
# Credentials never live in the repository. They come from the environment, from the git-ignored
# secrets/ folder (see secrets/README.md), or from the login keychain. This script prints which
# source it used, never the values.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$APP_DIR/.." && pwd)"
SLUG="keyvanarasteh/os-lab"
PUBLISH=0; NOTARIZE=1; TARGET="universal-apple-darwin"

while [ $# -gt 0 ]; do
  case "$1" in
    --publish) PUBLISH=1 ;;
    --no-notarize) NOTARIZE=0 ;;
    --arch) shift; case "${1:-}" in arm64) TARGET=aarch64-apple-darwin ;; x64) TARGET=x86_64-apple-darwin ;; universal) ;; *) echo "--arch arm64|x64|universal" >&2; exit 2 ;; esac ;;
    -h|--help) sed -n 2,12p "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[ "$(uname -s)" = Darwin ] || die "macOS only: signing and notarization need Xcode's tools"
for t in node npm cargo xcrun codesign security hdiutil shasum; do command -v "$t" >/dev/null || die "$t not found"; done
if [ "$PUBLISH" = 1 ]; then command -v gh >/dev/null && gh auth status >/dev/null 2>&1 || die "--publish needs the gh CLI, logged in"; fi

VERSION="$(node -p "require('$APP_DIR/src-tauri/tauri.conf.json').version")"
TAG="app-v$VERSION"
OUT="$APP_DIR/out/$VERSION"
if [ "$PUBLISH" = 1 ]; then
  # --force: CI checks out the tag ref, so the tag already exists locally and a plain
  # fetch is rejected for clobbering it. Fall back to an already-present local tag.
  git -C "$REPO" fetch -q --force origin "refs/tags/$TAG:refs/tags/$TAG" 2>/dev/null \
    || git -C "$REPO" rev-parse -q --verify "refs/tags/$TAG^{commit}" >/dev/null \
    || die "release tag $TAG is missing"
  [ "$(git -C "$REPO" rev-list -n 1 "$TAG")" = "$(git -C "$REPO" rev-parse HEAD)" ] \
    || die "$TAG does not point to this checkout; publish from the tagged commit"
fi

# ── 1. Secrets must never be tracked ────────────────────────────────────────────────────────────
TRACKED="$(git -C "$REPO" ls-files -- secrets | grep -v '^secrets/README.md$' || true)"
[ -z "$TRACKED" ] || die "tracked files under secrets/ (remove them from git, rotate the keys):
$TRACKED"
if git -C "$REPO" ls-files -- '*.p8' '*.p12' '*.mobileprovision' '*.pem' | grep -q .; then
  die "a key or certificate file is tracked by git"
fi

# ── 2. Locate credentials ───────────────────────────────────────────────────────────────────────
cred_dirs=()
[ -n "${OSLAB_SECRETS_DIR:-}" ] && cred_dirs+=("$OSLAB_SECRETS_DIR")
cred_dirs+=("$REPO/secrets/cupertino/credentials" "$REPO/secrets/cupertino" "$REPO/../qLar/secrets/cupertino/credentials")

first_file() { # name... → first existing file under any credential dir
  local d n
  for d in "${cred_dirs[@]}"; do for n in "$@"; do [ -f "$d/$n" ] && { echo "$d/$n"; return; }; done; done
}
first_value() { local f; f="$(first_file "$@")"; [ -n "$f" ] && tr -d '[:space:]' < "$f" || true; }

if [ -z "${APPLE_API_KEY_PATH:-}" ]; then
  for d in "${cred_dirs[@]}"; do
    p="$(ls "$d"/app-store-connect/AuthKey_*.p8 2>/dev/null | head -1 || true)"
    [ -n "$p" ] && { APPLE_API_KEY_PATH="$p"; src_note="secrets folder"; break; }
  done
fi
: "${APPLE_API_KEY:=$(first_value app-store-connect/key-id.txt app-store-connect/keyId.key)}"
: "${APPLE_API_ISSUER:=$(first_value app-store-connect/issuer-id.txt app-store-connect/IssuerId.key)}"

if [ -z "${APPLE_SIGNING_IDENTITY:-}" ]; then
  APPLE_SIGNING_IDENTITY="$(security find-identity -v -p codesigning | sed -n 's/.*"\(Developer ID Application: [^"]*\)".*/\1/p' | head -1)"
fi
[ -n "${APPLE_SIGNING_IDENTITY:-}" ] || [ -n "${APPLE_CERTIFICATE:-}" ] || die "no Developer ID Application identity in the keychain, and no APPLE_CERTIFICATE"

say "version $VERSION, tag $TAG, target $TARGET"
say "signing identity: ${APPLE_SIGNING_IDENTITY:-from APPLE_CERTIFICATE}"
if [ "$NOTARIZE" = 1 ]; then
  [ -f "${APPLE_API_KEY_PATH:-}" ] && [ -n "${APPLE_API_KEY:-}" ] && [ -n "${APPLE_API_ISSUER:-}" ] \
    || die "notarization needs APPLE_API_KEY, APPLE_API_ISSUER and APPLE_API_KEY_PATH (see secrets/README.md), or pass --no-notarize"
  say "notarization key: id ${APPLE_API_KEY} (.p8 found)"
  export APPLE_API_KEY APPLE_API_ISSUER APPLE_API_KEY_PATH
else
  say "notarization skipped (--no-notarize)"
  unset APPLE_API_KEY APPLE_API_ISSUER APPLE_API_KEY_PATH
fi
export APPLE_SIGNING_IDENTITY
# Cargo must not strip host proc-macro dylibs; doing so breaks some macOS toolchains with E0463.
export CARGO_PROFILE_RELEASE_STRIP=false

# ── 3. Build ────────────────────────────────────────────────────────────────────────────────────
cd "$APP_DIR"
say "installing build tools"
npm ci --no-audit --no-fund >/dev/null
say "installing dashboard build tools"
npm ci --no-audit --no-fund --prefix "$APP_DIR/../dashboard" >/dev/null
say "staging the runtime and dashboard"
node scripts/stage-runtime.mjs
[ -n "${APPLE_SIGNING_IDENTITY:-}" ] || die "bundled Python helpers need a Developer ID identity in the keychain; import APPLE_CERTIFICATE before building"
node scripts/stage-python-helper.mjs
# The Web Lab engine ships as a nested resource binary (staged under
# resources/os-lab/web-lab). `npx tauri build` below signs the app and
# notarizes it in this environment, and notarization refuses unsigned nested
# Mach-O binaries, so sign the staged engine before the build. Skipped
# silently when the engine is not staged.
ENGINE_BIN="$APP_DIR/src-tauri/resources/os-lab/web-lab/browser/target/release/weblab"
if [ -f "$ENGINE_BIN" ]; then
  say "signing the staged web-lab engine"
  codesign --force --options runtime --timestamp \
    --sign "$APPLE_SIGNING_IDENTITY" "$ENGINE_BIN" \
    || die "signing the web-lab engine failed"
fi
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ] && [ -f "$REPO/secrets/updater/os-lab.key" ]; then
  export TAURI_SIGNING_PRIVATE_KEY="$(cat "$REPO/secrets/updater/os-lab.key")"
fi
[ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ] || die "updater signing key is missing (TAURI_SIGNING_PRIVATE_KEY)"
# CLW-08: build the widget extension and reload bridge first (fast, fails early).
# OSLAB_SKIP_WIDGETS=1 skips them for debugging — the app then ships without widgets.
if [ "${OSLAB_SKIP_WIDGETS:-0}" != "1" ]; then
  say "building the widget extension and reload bridge"
  ( command -v xcodegen >/dev/null || brew install xcodegen >/dev/null ) || die "xcodegen is required for the widget targets"
  WIDGET_ARCH="${TARGET%%-apple-darwin}"; [ "$WIDGET_ARCH" = "universal" ] && WIDGET_ARCH=""
  bash "$APP_DIR/widget/build.sh" $WIDGET_ARCH || die "widget build failed"
  [ -d "$APP_DIR/widget/build/OSLabWidgets.appex" ] && [ -d "$APP_DIR/widget/build/OSLabWidgetReloader.framework" ] \
    || die "widget build produced no products"
fi

say "building ($TARGET) — Tauri signs the app with hardened runtime and notarizes it when the API key is set"
npx tauri build --target "$TARGET" --bundles app

BUNDLE="${CARGO_TARGET_DIR:-$APP_DIR/src-tauri/target}/$TARGET/release/bundle"
ARCH_LABEL="${TARGET%%-apple-darwin}"
APP="$BUNDLE/macos/os-lab.app"
DMG="$BUNDLE/dmg/os-lab_${VERSION}_${ARCH_LABEL}.dmg"
UPDATE="$BUNDLE/macos/os-lab.app.tar.gz"
[ -d "$APP" ] && [ -f "$UPDATE" ] && [ -f "$UPDATE.sig" ] \
  || die "build produced no app or signed updater bundle"

# ── 3b. Embed the widget extension, then re-sign and re-notarize ────────────────────────────────
# Tauri signed and (optionally) notarized the app; embedding nested code
# invalidates both, so the seal is rebuilt here: appex → framework → app.
if [ -d "$APP_DIR/widget/build/OSLabWidgets.appex" ]; then
  say "embedding the widget extension"
  HOST_ENTITLEMENTS="$APP_DIR/src-tauri/entitlements-macos.plist"
  WIDGET_ENTITLEMENTS="$APP_DIR/widget/entitlements-widget.plist"
  [ -f "$HOST_ENTITLEMENTS" ] || die "host entitlements are missing"
  # CI resolves APPLE_SIGNING_IDENTITY before calling this script; the local
  # APPLE_CERTIFICATE-only path imports the P12 here, like the workflow does.
  if [ -z "${APPLE_SIGNING_IDENTITY:-}" ] && [ -n "${APPLE_CERTIFICATE:-}" ]; then
    say "importing APPLE_CERTIFICATE for the widget signing"
    CERT_DIR="$(mktemp -d)"
    printf '%s' "$APPLE_CERTIFICATE" | base64 --decode > "$CERT_DIR/sign.p12"
    KEYCHAIN="$CERT_DIR/oslab-sign.keychain-db"
    security create-keychain -p "${APPLE_CERTIFICATE_PASSWORD:-oslab}" "$KEYCHAIN"
    security import "$CERT_DIR/sign.p12" -k "$KEYCHAIN" -P "${APPLE_CERTIFICATE_PASSWORD:-oslab}" -T /usr/bin/codesign
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "${APPLE_CERTIFICATE_PASSWORD:-oslab}" "$KEYCHAIN" >/dev/null
    APPLE_SIGNING_IDENTITY="$(security find-identity -v -p codesigning "$KEYCHAIN" | sed -n 's/.*"\(Developer ID Application: [^"]*\)".*/\1/p' | head -1)"
  fi
  [ -n "${APPLE_SIGNING_IDENTITY:-}" ] || die "no Developer ID Application identity for the widget embed"
  mkdir -p "$APP/Contents/PlugIns" "$APP/Contents/Frameworks"
  rm -rf "$APP/Contents/PlugIns/OSLabWidgets.appex" "$APP/Contents/Frameworks/OSLabWidgetReloader.framework"
  cp -R "$APP_DIR/widget/build/OSLabWidgets.appex" "$APP/Contents/PlugIns/"
  cp -R "$APP_DIR/widget/build/OSLabWidgetReloader.framework" "$APP/Contents/Frameworks/"
  codesign --force --options runtime --timestamp --entitlements "$WIDGET_ENTITLEMENTS" \
    --sign "$APPLE_SIGNING_IDENTITY" "$APP/Contents/PlugIns/OSLabWidgets.appex" \
    || die "signing the widget extension failed"
  codesign --force --options runtime --timestamp \
    --sign "$APPLE_SIGNING_IDENTITY" "$APP/Contents/Frameworks/OSLabWidgetReloader.framework" \
    || die "signing the reloader framework failed"
  say "re-signing the app with the widget contents"
  codesign --force --options runtime --timestamp --entitlements "$HOST_ENTITLEMENTS" \
    --sign "$APPLE_SIGNING_IDENTITY" "$APP" \
    || die "re-signing the app failed"
  # The updater bundle is built from the pre-embed app: rebuild it from the
  # re-signed app and re-sign it for the updater feed.
  say "rebuilding the updater bundle"
  rm -f "$UPDATE" "$UPDATE.sig"
  tar -czf "$UPDATE" -C "$BUNDLE/macos" os-lab.app
  npx tauri signer sign --app-version "$VERSION" "$UPDATE" >/dev/null
  [ -f "$UPDATE.sig" ] || die "updater bundle signature is missing"
  if [ "$NOTARIZE" = 1 ]; then
    say "re-notarizing the app (waits for Apple)"
    APP_ZIP="$(mktemp -d)/os-lab.app.zip"
    # --keepParent keeps os-lab.app as the archive's root entry, which notarytool expects.
    ditto -c -k --keepParent "$APP" "$APP_ZIP"
    xcrun notarytool submit "$APP_ZIP" --key "$APPLE_API_KEY_PATH" --key-id "$APPLE_API_KEY" --issuer "$APPLE_API_ISSUER" --wait
    xcrun stapler staple "$APP"
  else
    say "app notarization skipped (--no-notarize)"
  fi
fi

# Package the DMG ourselves. Tauri's bundle_dmg.sh mounts a read-write volume and runs
# Finder to lay out icons, then frequently cannot unmount it ("hdiutil: Resource busy"),
# which failed every macOS release on the build host. Create a compressed DMG straight
# from the signed, notarized .app with no interstitial read-write mount to get stuck.
say "packaging the DMG from the signed app"
mkdir -p "$(dirname "$DMG")"
rm -f "$DMG"
DMG_STAGE="$(mktemp -d)"
cp -R "$APP" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"
hdiutil create -volname "os-lab" -srcfolder "$DMG_STAGE" -fs HFS+ -format UDZO -ov "$DMG"
rm -rf "$DMG_STAGE"
[ -f "$DMG" ] || die "DMG packaging failed"

# ── 4. Sign + notarize the DMG itself (Tauri notarizes the .app) ────────────────────────────────
say "signing the DMG"
codesign --force --sign "$APPLE_SIGNING_IDENTITY" --timestamp "$DMG"
if [ "$NOTARIZE" = 1 ]; then
  say "notarizing the DMG (waits for Apple)"
  xcrun notarytool submit "$DMG" --key "$APPLE_API_KEY_PATH" --key-id "$APPLE_API_KEY" --issuer "$APPLE_API_ISSUER" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler staple "$APP" >/dev/null 2>&1 || true
fi

# ── 5. Verify what will ship ────────────────────────────────────────────────────────────────────
say "verifying"
codesign --verify --deep --strict --verbose=1 "$APP"
if [ -d "$APP/Contents/PlugIns/OSLabWidgets.appex" ]; then
  codesign --verify --strict "$APP/Contents/PlugIns/OSLabWidgets.appex"
  codesign --verify --strict "$APP/Contents/Frameworks/OSLabWidgetReloader.framework"
  # codesign -d --entitlements - prints XML on some codesign builds and a DER
  # blob on others (macOS 15+): DER carries boolean keys as OIDs, so a grep for
  # the key name finds nothing even though the entitlement is present. Grep the
  # raw display AND the DER-decoded XML (":-") so the check is format-proof.
  host_ents="$( { codesign -d --entitlements - "$APP" 2>/dev/null; codesign -d --entitlements :- "$APP" 2>/dev/null; } || true)"
  appex_ents="$( { codesign -d --entitlements - "$APP/Contents/PlugIns/OSLabWidgets.appex" 2>/dev/null; codesign -d --entitlements :- "$APP/Contents/PlugIns/OSLabWidgets.appex" 2>/dev/null; } || true)"
  echo "$host_ents" | grep -q "group.com.keyvanarasteh.oslab" \
    || { echo "the app signature is missing the widget App Group entitlement; entitlements output:"; echo "$host_ents"; die "the app signature is missing the widget App Group entitlement"; }
  echo "$appex_ents" | grep -q "com.apple.security.app-sandbox" \
    || { echo "the widget extension signature is missing the App Sandbox entitlement; entitlements output:"; echo "$appex_ents"; die "the widget extension signature is missing the App Sandbox entitlement"; }
  echo "$appex_ents" | grep -q "group.com.keyvanarasteh.oslab" \
    || { echo "the widget extension signature is missing the widget App Group entitlement; entitlements output:"; echo "$appex_ents"; die "the widget extension signature is missing the widget App Group entitlement"; }
fi
codesign --verify --verbose=1 "$DMG"
if [ "$NOTARIZE" = 1 ]; then
  xcrun stapler validate "$APP"
  xcrun stapler validate "$DMG"
  spctl --assess --type exec --verbose=2 "$APP"
  spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
fi

# ── 6. Collect ──────────────────────────────────────────────────────────────────────────────────
mkdir -p "$OUT"
ASSET="$OUT/os-lab_${VERSION}_macos_${ARCH_LABEL}.dmg"
cp "$DMG" "$ASSET"
( cd "$OUT" && shasum -a 256 "$(basename "$ASSET")" > "$(basename "$ASSET").sha256" )
say "ready: $ASSET"
cat "$ASSET.sha256"
npx tauri signer sign --app-version "$VERSION" "$ASSET" >/dev/null
[ -f "$ASSET.sig" ] || die "DMG signature is missing"
UPDATE_ASSET="$OUT/os-lab_${VERSION}_macos_${ARCH_LABEL}.app.tar.gz"
cp "$UPDATE" "$UPDATE_ASSET"
cp "$UPDATE.sig" "$UPDATE_ASSET.sig"
( cd "$OUT" && shasum -a 256 "$(basename "$UPDATE_ASSET")" > "$(basename "$UPDATE_ASSET").sha256" )

# ── 7. Publish ──────────────────────────────────────────────────────────────────────────────────
if [ "$PUBLISH" = 1 ]; then
  [ "$NOTARIZE" = 1 ] || die "refusing to publish an un-notarized DMG"
  if gh release view "$TAG" -R "$SLUG" >/dev/null 2>&1; then
    say "updating release $TAG"
    gh release upload "$TAG" "$ASSET" "$ASSET.sha256" "$ASSET.sig" "$UPDATE_ASSET" "$UPDATE_ASSET.sig" "$UPDATE_ASSET.sha256" --clobber -R "$SLUG"
  else
    say "creating release $TAG"
    gh release create "$TAG" "$ASSET" "$ASSET.sha256" "$ASSET.sig" "$UPDATE_ASSET" "$UPDATE_ASSET.sig" "$UPDATE_ASSET.sha256" -R "$SLUG" --title "os-lab app $VERSION" \
      --notes "os-lab desktop app $VERSION. One installer per platform, each with a .sha256 file. The macOS DMG is universal, signed and notarized. The app can download managed Python on request."
  fi
  say "published: https://github.com/$SLUG/releases/tag/$TAG"
else
  say "dry run: nothing uploaded (use --publish)"
fi
