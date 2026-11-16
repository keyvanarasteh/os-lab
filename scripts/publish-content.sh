#!/usr/bin/env bash
# Build, sign and publish the content pack from this machine (the workflow does the same on master).
#   scripts/publish-content.sh           build + sign, upload nothing
#   scripts/publish-content.sh --publish ...and replace the content-latest release
# The signing key is secrets/content/content-signing.pem (git-ignored) or $OSLAB_CONTENT_SIGNING_KEY.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SLUG="keyvanarasteh/os-lab"
cd "$ROOT"
[ -z "$(git status --porcelain -- firewall-lab ios-lab/knowledge docs/legal android-lab/lab/hooks console/content.py)" ] \
  || { echo "error: uncommitted changes in content paths; the pack is built from tracked files at HEAD" >&2; exit 1; }
python3 firewall-lab/scripts/validate.py
python3 scripts/build-content.py --require-signature
[ "${1:-}" = "--publish" ] || { echo "==> dry run: nothing uploaded (use --publish)"; exit 0; }
command -v gh >/dev/null && gh auth status >/dev/null 2>&1 || { echo "error: --publish needs the gh CLI, logged in" >&2; exit 1; }
seq="$(python3 -c "import json;print(json.load(open('dist-content/manifest.json'))['sequence'])")"
python3 scripts/content-release-notes.py --sequence "$seq" > dist-content/release-notes.md
for tag in "content-$seq" content-latest; do
  gh release delete "$tag" -R "$SLUG" --cleanup-tag --yes 2>/dev/null || true
  gh release create "$tag" dist-content/manifest.json dist-content/manifest.json.sig dist-content/content-pack.tar.gz \
    -R "$SLUG" --title "os-lab content $seq" --notes-file dist-content/release-notes.md --target "$(git rev-parse HEAD)" \
    --latest=false   # never take "Latest" from the app release
done
echo "==> published content-$seq and content-latest"
