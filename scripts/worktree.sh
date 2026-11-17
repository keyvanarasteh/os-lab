#!/usr/bin/env bash
# Create, check and remove os-lab worktrees with the shared caches wired in (plan items I, J, R).
# Works on macOS (bash 3.2) and Linux.
#
# Usage:
#   scripts/worktree.sh new <branch> [--path <dir>] [--no-hook] [--no-browsers]
#       fetch, create the worktree (from origin/<branch> when it exists, else a new branch from
#       origin/master), link dashboard/node_modules and .venv-test from the cache, write
#       .oslab-env, install the pre-push hook, print the path and a free e2e port
#   scripts/worktree.sh doctor [<dir>] [--no-browsers]
#       check the links against the current package-lock.json and requirements hashes;
#       relink or install into the cache when a rebase changed them; configure the locale
#       JSON merge driver (scripts/lib/i18n-merge-driver.mjs)
#   scripts/worktree.sh rm <branch|dir> [--force]
#       remove the worktree and its own output (test-results/, build-pages/, .vite-cache/,
#       .e2e-dist/); never the shared caches
#   scripts/worktree.sh cache prune [--yes]
#       delete cache entries that no worktree links to, after asking
#   scripts/worktree.sh cache path | env
#       print the cache root, or the variables .oslab-env sets
#   scripts/worktree.sh hook install | uninstall
#       the optional pre-push hook (scripts/hooks/pre-push); OSLAB_SKIP_PREPUSH=1 skips it
#
# Cache root: OSLAB_CACHE_ROOT (default ~/.cache/os-lab). On a Mac with an external project
# volume, set it there, e.g. OSLAB_CACHE_ROOT=/Volumes/Projects/iQ/.cache-build.
#   node_modules/<lockfile hash>/node_modules   one install per package-lock.json
#   venv/<requirements hash>                     one test virtualenv per requirements set
#   npm, pip, playwright, sccache                download and compiler caches
# Never shared: dist/, build-pages/, test-results/, .astro, .vite-cache, lab .env files,
# storage/, artifacts/ and target/ folders.
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
REPO="$(git -C "$(dirname "$SELF")" rev-parse --show-toplevel)"
CACHE="${OSLAB_CACHE_ROOT:-$HOME/.cache/os-lab}"
# Test-only Python packages run-tests.sh installs next to the requirements files.
PY_EXTRA="pytest requests cryptography"

usage() { sed -n '2,/^set -euo/p' "$SELF" | sed '$d' | sed 's/^# \{0,1\}//'; }
die() { echo "worktree.sh: $*" >&2; exit 2; }
say() { echo "worktree.sh: $*"; }

# mkdir lock so two worktrees never install into the same cache entry at once.
with_lock() {
  local lock="$1"; shift
  local waited=0
  mkdir -p "$(dirname "$lock")"
  while ! mkdir "$lock" 2>/dev/null; do
    local holder; holder="$(cat "$lock/pid" 2>/dev/null || true)"
    if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then rm -rf "$lock"; continue; fi
    [ $((waited % 30)) -eq 0 ] && say "waiting for $lock (PID ${holder:-?})"
    sleep 2; waited=$((waited + 2))
  done
  echo $$ > "$lock/pid"
  local status=0
  "$@" || status=$?
  rm -rf "$lock"
  return "$status"
}

lock_hash() { git -C "$1" hash-object dashboard/package-lock.json; }
req_hash() {
  local wt="$1"
  { echo "$PY_EXTRA"; python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])'
    find "$wt" \( -name node_modules -o -name .git -o -name .venv-test \) -prune -o -name 'requirements*.txt' -type f -print \
      | sort | while IFS= read -r f; do echo "${f#"$wt"/}"; git hash-object "$f"; done
  } | git hash-object --stdin
}

install_node_modules() { # <worktree> <hash>
  local wt="$1" entry="$CACHE/node_modules/$2"
  [ -f "$entry/.complete" ] && return 0
  say "installing dashboard dependencies into $entry (once per package-lock.json)"
  rm -rf "$entry"; mkdir -p "$entry"
  cp "$wt/dashboard/package.json" "$wt/dashboard/package-lock.json" "$entry/"
  (cd "$entry" && npm_config_cache="$CACHE/npm" npm ci --prefer-offline --no-audit --no-fund --loglevel=error >/dev/null)
  touch "$entry/.complete"
}

install_venv() { # <worktree> <hash>
  local wt="$1" entry="$CACHE/venv/$2"
  [ -f "$entry/.complete" ] && return 0
  say "creating the test virtualenv $entry (once per requirements set)"
  rm -rf "$entry"
  python3 -m venv "$entry"
  # shellcheck disable=SC2086
  PIP_CACHE_DIR="$CACHE/pip" "$entry/bin/python" -m pip install --quiet --upgrade pip $PY_EXTRA
  if [ -f "$wt/android-lab/lab/requirements.txt" ]; then
    PIP_CACHE_DIR="$CACHE/pip" "$entry/bin/python" -m pip install --quiet -r "$wt/android-lab/lab/requirements.txt" \
      || say "some android-lab requirements did not install (run-tests.sh tolerates this too)"
  fi
  touch "$entry/.complete"
}

# link <path> <target>: point a symlink at target. A real folder is left alone.
link() {
  local path="$1" target="$2"
  if [ -L "$path" ]; then
    [ "$(readlink "$path")" = "$target" ] && return 0
    rm "$path"
  elif [ -e "$path" ]; then
    say "$path is a real folder, not a cache link; remove it to use the shared cache"
    return 0
  fi
  ln -s "$target" "$path"
  say "linked ${path#"$REPO"/} -> $target"
}

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

write_env() { # <worktree>
  cat > "$1/.oslab-env" <<EOF
# Written by scripts/worktree.sh (git-ignored). scripts/e2e.sh and scripts/run-tests.sh read it;
# run \`. ./.oslab-env\` to use the same caches in your own shell.
export OSLAB_CACHE_ROOT="$CACHE"
EOF
}

doctor() { # <worktree> <browsers 0|1>
  local wt="$1" browsers="$2" lh rh
  [ -f "$wt/dashboard/package-lock.json" ] || die "$wt is not an os-lab checkout"
  mkdir -p "$CACHE"
  [ -f "$wt/.oslab-env" ] || write_env "$wt"
  # Plan item C: merge locale JSON key by key (.gitattributes names the driver). The config
  # is shared by every worktree of the repository.
  if [ "$(git -C "$wt" config merge.oslab-i18n.driver || true)" != "node scripts/lib/i18n-merge-driver.mjs %O %A %B %P" ]; then
    git -C "$wt" config merge.oslab-i18n.name "os-lab locale JSON merge"
    git -C "$wt" config merge.oslab-i18n.driver "node scripts/lib/i18n-merge-driver.mjs %O %A %B %P"
    say "configured the locale JSON merge driver"
  fi
  lh="$(lock_hash "$wt")"
  if command -v npm >/dev/null 2>&1; then
    with_lock "$CACHE/locks/node_modules-$lh" install_node_modules "$wt" "$lh"
    link "$wt/dashboard/node_modules" "$CACHE/node_modules/$lh/node_modules"
  else
    say "npm not found; dashboard/node_modules not linked"
  fi
  if command -v python3 >/dev/null 2>&1; then
    rh="$(req_hash "$wt")"
    with_lock "$CACHE/locks/venv-$rh" install_venv "$wt" "$rh"
    link "$wt/.venv-test" "$CACHE/venv/$rh"
  else
    say "python3 not found; .venv-test not linked"
  fi
  if [ "$browsers" = 1 ] && [ -x "$wt/dashboard/node_modules/.bin/playwright" ]; then
    # Versioned folders: one download serves every worktree with the same Playwright version.
    (cd "$wt/dashboard" && PLAYWRIGHT_BROWSERS_PATH="$CACHE/playwright" ./node_modules/.bin/playwright install chromium >/dev/null) \
      || say "Playwright browser install failed; run it again later with: scripts/worktree.sh doctor"
  fi
  say "ok: $wt (lockfile ${lh:0:12}${rh:+, requirements ${rh:0:12}})"
}

hook_install() {
  local hooks; hooks="$(git -C "$REPO" rev-parse --git-common-dir)/hooks"
  hooks="$(cd "$REPO" && cd "$hooks" && pwd)"
  mkdir -p "$hooks"
  if [ -e "$hooks/pre-push" ] && ! grep -q 'os-lab pre-push wrapper' "$hooks/pre-push"; then
    say "a different pre-push hook exists at $hooks/pre-push; left unchanged"
    return 0
  fi
  cat > "$hooks/pre-push" <<'EOF'
#!/usr/bin/env bash
# os-lab pre-push wrapper (scripts/worktree.sh hook install): runs the hook of the worktree
# being pushed, if it has one. OSLAB_SKIP_PREPUSH=1 skips it.
hook="$(git rev-parse --show-toplevel)/scripts/hooks/pre-push"
[ -x "$hook" ] || exit 0
exec "$hook" "$@"
EOF
  chmod +x "$hooks/pre-push"
  say "pre-push hook installed in $hooks (shared by every worktree; OSLAB_SKIP_PREPUSH=1 skips it)"
}

hook_uninstall() {
  local hooks; hooks="$(cd "$REPO" && cd "$(git rev-parse --git-common-dir)/hooks" && pwd)"
  if [ -f "$hooks/pre-push" ] && grep -q 'os-lab pre-push wrapper' "$hooks/pre-push"; then
    rm "$hooks/pre-push"; say "pre-push hook removed"
  else
    say "no os-lab pre-push hook installed"
  fi
}

worktree_paths() { git -C "$REPO" worktree list --porcelain | sed -n 's/^worktree //p'; }

cmd_new() {
  local branch="" path="" hook=1 browsers=1
  while [ $# -gt 0 ]; do
    case "$1" in
      --path) path="$2"; shift ;;
      --no-hook) hook=0 ;;
      --no-browsers) browsers=0 ;;
      -*) die "unknown option: $1" ;;
      *) [ -z "$branch" ] || die "one branch only"; branch="$1" ;;
    esac
    shift
  done
  [ -n "$branch" ] || die "usage: scripts/worktree.sh new <branch>"
  [ -n "$path" ] || path="${OSLAB_WORKTREE_ROOT:-$(dirname "$REPO")/os-lab-worktrees}/$(echo "$branch" | tr '/' '-')"
  [ -e "$path" ] && die "$path already exists"
  git -C "$REPO" fetch --quiet origin
  mkdir -p "$(dirname "$path")"
  if git -C "$REPO" show-ref --verify --quiet "refs/heads/$branch"; then
    git -C "$REPO" worktree add --quiet "$path" "$branch"
  elif git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    git -C "$REPO" worktree add --quiet --track -b "$branch" "$path" "origin/$branch"
  else
    git -C "$REPO" worktree add --quiet --no-track -b "$branch" "$path" origin/master
  fi
  doctor "$path" "$browsers"
  [ "$hook" = 1 ] && hook_install
  echo
  echo "worktree: $path"
  echo "branch:   $branch"
  echo "e2e port: $(free_port) (scripts/e2e.sh picks a free one by itself)"
  echo "next:     cd $path && scripts/e2e.sh --dry-run"
}

cmd_rm() {
  local target="" force=""
  while [ $# -gt 0 ]; do
    case "$1" in --force) force="--force" ;; -*) die "unknown option: $1" ;; *) target="$1" ;; esac
    shift
  done
  [ -n "$target" ] || die "usage: scripts/worktree.sh rm <branch|dir>"
  local path=""
  if [ -d "$target" ]; then path="$(cd "$target" && pwd)"
  else
    path="$(git -C "$REPO" worktree list --porcelain | awk -v b="refs/heads/$target" '/^worktree /{p=substr($0,10)} $0=="branch "b{print p}')"
  fi
  [ -n "$path" ] || die "no worktree for $target"
  if [ "$path" = "$(worktree_paths | head -1)" ]; then die "refusing to remove the main checkout"; fi
  # Per-worktree output and the cache links (removing a link never touches the cache).
  rm -rf "$path/dashboard/test-results" "$path/dashboard/playwright-report" "$path/dashboard/build-pages" \
    "$path/dashboard/build-pages.raw" "$path/dashboard/.vite-cache" "$path/dashboard/.e2e-dist" "$path/test-results"
  [ -L "$path/dashboard/node_modules" ] && rm "$path/dashboard/node_modules"
  [ -L "$path/.venv-test" ] && rm "$path/.venv-test"
  rm -f "$path/.oslab-env"
  # shellcheck disable=SC2086
  git -C "$REPO" worktree remove $force "$path"
  say "removed $path (branch kept; delete it with git branch -d when merged)"
}

cmd_cache() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    path) echo "$CACHE" ;;
    env) echo "export OSLAB_CACHE_ROOT=\"$CACHE\""; (OSLAB_CACHE_ROOT="$CACHE"; . "$REPO/scripts/lib/cache-env.sh"; env | grep -E '^(npm_config_cache|PIP_CACHE_DIR|PLAYWRIGHT_BROWSERS_PATH|RUSTC_WRAPPER|SCCACHE_DIR)=' | sed 's/^/export /') ;;
    prune)
      local yes=0; [ "${1:-}" = "--yes" ] && yes=1
      local used="" wt
      while IFS= read -r wt; do
        [ -L "$wt/dashboard/node_modules" ] && used="$used $(readlink "$wt/dashboard/node_modules")"
        [ -L "$wt/.venv-test" ] && used="$used $(readlink "$wt/.venv-test")"
      done <<< "$(worktree_paths)"
      local unused="" entry
      for entry in "$CACHE"/node_modules/* "$CACHE"/venv/*; do
        [ -d "$entry" ] || continue
        case "$used " in *" $entry/node_modules "*|*" $entry "*) ;; *) unused="$unused $entry" ;; esac
      done
      if [ -z "$unused" ]; then say "every cache entry is in use"; return 0; fi
      echo "Cache entries no worktree links to:"
      for entry in $unused; do echo "  $entry ($(du -sh "$entry" 2>/dev/null | cut -f1))"; done
      if [ "$yes" = 0 ]; then
        if [ -t 0 ]; then
          printf 'Delete them? [y/N] '; read -r answer
          case "$answer" in y|Y|yes) ;; *) say "nothing deleted"; return 0 ;; esac
        else
          say "not deleted; run again in a terminal or with --yes"; return 0
        fi
      fi
      for entry in $unused; do rm -rf "$entry"; done
      say "deleted$unused" ;;
    *) die "usage: scripts/worktree.sh cache prune|path|env" ;;
  esac
}

case "${1:-}" in
  new) shift; cmd_new "$@" ;;
  doctor)
    shift; dir="$REPO"; browsers=1
    for a in "$@"; do case "$a" in --no-browsers) browsers=0 ;; -*) die "unknown option: $a" ;; *) dir="$(cd "$a" && pwd)" ;; esac; done
    [ "$dir" = "$REPO" ] && dir="$(git rev-parse --show-toplevel 2>/dev/null || echo "$REPO")"
    doctor "$dir" "$browsers" ;;
  rm) shift; cmd_rm "$@" ;;
  cache) shift; cmd_cache "$@" ;;
  hook)
    case "${2:-}" in install) hook_install ;; uninstall) hook_uninstall ;; *) die "usage: scripts/worktree.sh hook install|uninstall" ;; esac ;;
  -h|--help|"") usage ;;
  *) die "unknown command: $1 (see --help)" ;;
esac
