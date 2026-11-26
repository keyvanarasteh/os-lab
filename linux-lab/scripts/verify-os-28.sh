#!/bin/bash
cd "$(git rev-parse --show-toplevel)"
while IFS= read -r cmd; do
  clear
  echo "\$ $cmd"
  eval "$cmd"
  sleep 10
done <<'EOF'
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /tmp/os28-test '*.py' 'def'
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /tmp/os28-test '*.py' 'def' --execute
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /tmp/os28-test '*.py' '-x test(' --execute
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /tmp/os28-test '*.py' "it's" --execute
python3 linux-lab/scripts/os-28-search-grep-wrapper.py /yok/dizin '*.py' 'def' --execute
EOF
