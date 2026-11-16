#!/usr/bin/env bash
# Build and (optionally) publish the os-lab Linux app as a .deb, plus optional RPM and AppImage.
#
#   app/scripts/release-deb.sh                  build + verify, upload nothing
#   app/scripts/release-deb.sh --publish        ...and add it to the GitHub release app-v<version>
#   app/scripts/release-deb.sh --install-deps   apt-get the Tauri build libraries first (uses sudo)
#   app/scripts/release-deb.sh --all-formats    build .deb, .rpm and .AppImage for the host architecture
#
# Tauri updater signatures need TAURI_SIGNING_PRIVATE_KEY (or ignored secrets/updater/os-lab.key).
# Debian and RPM are not distributed through a signed package repository. --publish uses the gh
# CLI's own login. The script refuses to run if any key file is tracked.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$APP_DIR/.." && pwd)"
SLUG="keyvanarasteh/os-lab"
PUBLISH=0; INSTALL_DEPS=0; ALL_FORMATS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --publish) PUBLISH=1 ;;
    --install-deps) INSTALL_DEPS=1 ;;
    --all-formats) ALL_FORMATS=1 ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[ "$(uname -s)" = Linux ] || die "Linux only (the .deb is built with the host's WebKitGTK and dpkg)"
if [ "$INSTALL_DEPS" = 1 ]; then
  say "installing Tauri build libraries (sudo)"
  sudo apt-get update
  sudo apt-get install -y build-essential curl wget file pkg-config libssl-dev libxdo-dev \
    libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev patchelf xdg-utils rpm
fi
for t in node npm cargo dpkg dpkg-deb sha256sum git tar; do command -v "$t" >/dev/null || die "$t not found"; done
pkg-config --exists webkit2gtk-4.1 \
  || die "libwebkit2gtk-4.1-dev is missing; run again with --install-deps, or see https://v2.tauri.app/start/prerequisites/#linux"
if [ "$PUBLISH" = 1 ]; then command -v gh >/dev/null && gh auth status >/dev/null 2>&1 || die "--publish needs the gh CLI, logged in"; fi

VERSION="$(node -p "require('$APP_DIR/src-tauri/tauri.conf.json').version")"
TAG="app-v$VERSION"
ARCH="$(dpkg --print-architecture)"
OUT="$APP_DIR/out/$VERSION"
if [ "$PUBLISH" = 1 ]; then
  git -C "$REPO" fetch -q origin "refs/tags/$TAG:refs/tags/$TAG" || die "release tag $TAG is missing"
  [ "$(git -C "$REPO" rev-list -n 1 "$TAG")" = "$(git -C "$REPO" rev-parse HEAD)" ] \
    || die "$TAG does not point to this checkout; publish from the tagged commit"
fi

# ── 1. Secrets must never be tracked ────────────────────────────────────────────────────────────
TRACKED="$(git -C "$REPO" ls-files -- secrets | grep -v '^secrets/README.md$' || true)"
[ -z "$TRACKED" ] || die "tracked files under secrets/ (remove them from git, rotate the keys):
$TRACKED"
if git -C "$REPO" ls-files -- '*.p8' '*.p12' '*.pfx' '*.pem' '*.key' | grep -q .; then
  die "a key or certificate file is tracked by git"
fi

say "version $VERSION, tag $TAG, arch $ARCH"

# ── 2. Build ────────────────────────────────────────────────────────────────────────────────────
cd "$APP_DIR"
say "installing build tools"
npm ci --no-audit --no-fund >/dev/null
say "installing dashboard build tools"
npm ci --no-audit --no-fund --prefix "$APP_DIR/../dashboard" >/dev/null
say "staging the runtime and dashboard"
node scripts/stage-runtime.mjs
node scripts/stage-python-helper.mjs
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ] && [ -f "$REPO/secrets/updater/os-lab.key" ]; then
  export TAURI_SIGNING_PRIVATE_KEY="$(cat "$REPO/secrets/updater/os-lab.key")"
fi
[ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ] || die "updater signing key is missing (TAURI_SIGNING_PRIVATE_KEY)"
say "building Linux bundles"
if [ "$ALL_FORMATS" = 1 ]; then
  npx tauri build --bundles deb,rpm,appimage
else
  npx tauri build --bundles deb
fi

DEB="$APP_DIR/src-tauri/target/release/bundle/deb/os-lab_${VERSION}_${ARCH}.deb"
[ -f "$DEB" ] || die "build produced no .deb for version $VERSION and architecture $ARCH at $DEB"

# ── 3. Verify what will ship ────────────────────────────────────────────────────────────────────
say "verifying $(basename "$DEB")"
dpkg-deb --info "$DEB" | sed -n '/Package:/p;/Version:/p;/Architecture:/p;/Depends:/p'
LISTING="$(dpkg-deb --contents "$DEB")"
grep -q 'os-lab/labctl' <<<"$LISTING" || die "the .deb has no bundled runtime (os-lab/labctl)"
grep -q 'os-lab/dashboard/dist/index.html' <<<"$LISTING" || die "the .deb has no dashboard build"
if grep -Eq '/(\.env|config\.env)$|\.(p8|p12|pfx|pem|key)$|/secrets/|/storage/' <<<"$LISTING"; then
  die "the .deb contains a secret-looking file"
fi

# ── 4. Collect ──────────────────────────────────────────────────────────────────────────────────
mkdir -p "$OUT"
ASSET="$OUT/os-lab_${VERSION}_linux_${ARCH}.deb"
cp "$DEB" "$ASSET"
( cd "$OUT" && sha256sum "$(basename "$ASSET")" > "$(basename "$ASSET").sha256" )
say "ready: $ASSET"
cat "$ASSET.sha256"
ASSETS=("$ASSET" "$ASSET.sha256")
npx tauri signer sign --app-version "$VERSION" "$ASSET" >/dev/null
[ -f "$ASSET.sig" ] || die "Debian package signature is missing"
ASSETS+=("$ASSET.sig")

if [ "$ALL_FORMATS" = 1 ]; then
  command -v rpm >/dev/null || die "rpm is required to verify the RPM package"
  for format in rpm appimage; do
    case "$format" in
      rpm) bundle_dir="$APP_DIR/src-tauri/target/release/bundle/rpm"; extension=rpm ;;
      appimage) bundle_dir="$APP_DIR/src-tauri/target/release/bundle/appimage"; extension=AppImage ;;
    esac
    mapfile -d '' matches < <(find "$bundle_dir" -maxdepth 1 -type f -name "*${VERSION}*.${extension}" -print0)
    [ "${#matches[@]}" = 1 ] || die "expected exactly one $extension for $VERSION, found ${#matches[@]}"
    package="${matches[0]}"
    if [ "$format" = rpm ]; then
      rpm -qip "$package" | grep -F "Version     : $VERSION" >/dev/null || die "RPM version mismatch"
    else
      [ -s "$package" ] || die "AppImage is empty"
    fi
    asset="$OUT/os-lab_${VERSION}_linux_${ARCH}.${extension}"
    cp "$package" "$asset"
    if [ "$format" = appimage ]; then
      [ -f "$package.sig" ] || die "AppImage updater signature is missing"
      cp "$package.sig" "$asset.sig"
      ASSETS+=("$asset.sig")
    fi
    ( cd "$OUT" && sha256sum "$(basename "$asset")" > "$(basename "$asset").sha256" )
    ASSETS+=("$asset" "$asset.sha256")
    if [ "$format" = rpm ]; then
      npx tauri signer sign --app-version "$VERSION" "$asset" >/dev/null
      [ -f "$asset.sig" ] || die "RPM package signature is missing"
      ASSETS+=("$asset.sig")
    fi
    say "ready: $asset"
    cat "$asset.sha256"
  done
fi

# ── 5. Publish ──────────────────────────────────────────────────────────────────────────────────
if [ "$PUBLISH" = 1 ]; then
  if gh release view "$TAG" -R "$SLUG" >/dev/null 2>&1; then
    say "adding to release $TAG"
    gh release upload "$TAG" "${ASSETS[@]}" --clobber -R "$SLUG"
  else
    say "creating release $TAG"
    gh release create "$TAG" "${ASSETS[@]}" -R "$SLUG" --title "os-lab app $VERSION" \
      --notes "os-lab desktop app $VERSION. Verify each download with its .sha256 file."
  fi
  say "published: https://github.com/$SLUG/releases/tag/$TAG"
else
  say "dry run: nothing uploaded (use --publish)"
fi
