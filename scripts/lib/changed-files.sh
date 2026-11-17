#!/usr/bin/env bash
# Print the files this branch changes, one per line, relative to the repository root
# (plan items G and K). Shared by scripts/e2e.sh --changed and scripts/run-tests.sh --changed,
# so both pick tests from the same list.
#
# Usage: scripts/lib/changed-files.sh [<base>]     (default base: origin/master)
#
# The list is: commits since the merge base with <base>, plus staged, unstaged and untracked
# files in the working tree. Deleted files are included, so a removed module still selects
# its tests. With OSLAB_CHANGED_FILES set (newline- or comma-separated), that list is printed
# instead; tests and CI use it.
set -euo pipefail

if [ -n "${OSLAB_CHANGED_FILES:-}" ]; then
  printf '%s\n' "$OSLAB_CHANGED_FILES" | tr ',' '\n' | sed '/^[[:space:]]*$/d' | sort -u
  exit 0
fi

base="${1:-origin/master}"
root="$(git rev-parse --show-toplevel)"
cd "$root"
if ! git rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
  echo "changed-files: unknown base '$base' (run: git fetch origin)" >&2
  exit 2
fi
merge_base="$(git merge-base "$base" HEAD)"
{
  git diff --name-only "$merge_base" HEAD
  git diff --name-only --cached
  git diff --name-only
  git ls-files --others --exclude-standard
} | sed '/^$/d' | sort -u
