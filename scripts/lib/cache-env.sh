# shellcheck shell=bash
# Shared dependency and download caches for parallel worktrees (plan item I).
# Sourced by scripts/e2e.sh, scripts/run-tests.sh and scripts/worktree.sh.
#
# Nothing changes unless OSLAB_CACHE_ROOT is set, either in the environment or in the
# worktree's git-ignored .oslab-env file that `scripts/worktree.sh new` writes. Then npm,
# pip, Playwright and sccache all keep their caches under it, so with an external volume
# nothing new lands in ~/.cache, ~/.npm or ~/Library/Caches.
_oslab_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ -z "${OSLAB_CACHE_ROOT:-}" ] && [ -f "$_oslab_root/.oslab-env" ]; then
  # shellcheck disable=SC1091
  . "$_oslab_root/.oslab-env"
fi
if [ -n "${OSLAB_CACHE_ROOT:-}" ]; then
  export OSLAB_CACHE_ROOT
  export npm_config_cache="${npm_config_cache:-$OSLAB_CACHE_ROOT/npm}"
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$OSLAB_CACHE_ROOT/pip}"
  export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$OSLAB_CACHE_ROOT/playwright}"
  if command -v sccache >/dev/null 2>&1; then
    export RUSTC_WRAPPER="${RUSTC_WRAPPER:-sccache}"
    export SCCACHE_DIR="${SCCACHE_DIR:-$OSLAB_CACHE_ROOT/sccache}"
  fi
fi
unset _oslab_root
