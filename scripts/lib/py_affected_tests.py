#!/usr/bin/env python3
"""Pick the Python test files of one lab that a change can affect (plan item L).

Usage:
  py_affected_tests.py --root <lab dir> [--tests <tests dir>] [--stdin] [changed file ...]

Changed files are paths relative to the repository root (the current directory).
Prints one of:
  NONE              no changed file is inside --root
  ALL               run the whole suite (see below)
  <test file> ...   one per line, relative to --root

A test file is selected when it is changed itself, when its imports reach a changed module
(directly or through other modules of the lab), or when its source names the changed
module's file stem (tests that load scripts by path or run them as subprocesses).

It answers ALL whenever it cannot be sure: a changed file that is not Python (fixtures,
requirements, golden files), a changed conftest.py or __init__.py, or a changed module that
no test reaches by either rule. Only the standard library is used.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def imports_of(path: Path) -> list[tuple[str, int]]:
    """(module name, relative level) for each import statement in the file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    except SyntaxError:
        return []
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            found.append((base, node.level))
            # `from pkg import mod` may import a submodule
            found.extend((f"{base}.{alias.name}" if base else alias.name, node.level) for alias in node.names)
    return found


def resolve(name: str, level: int, origin: Path, search: list[Path]) -> Path | None:
    parts = [part for part in name.split(".") if part]
    if level:
        base = origin.parent
        for _ in range(level - 1):
            base = base.parent
        roots = [base]
    else:
        roots = search
    for root in roots:
        candidate = root.joinpath(*parts) if parts else root
        if candidate.with_suffix(".py").is_file():
            return candidate.with_suffix(".py").resolve()
        if (candidate / "__init__.py").is_file():
            return (candidate / "__init__.py").resolve()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True)
    parser.add_argument("--tests", default="tests")
    parser.add_argument("--stdin", action="store_true", help="also read changed files from stdin, one per line")
    parser.add_argument("changed", nargs="*")
    args = parser.parse_args()
    if args.stdin:
        args.changed += [line.strip() for line in sys.stdin if line.strip()]

    repo = Path.cwd().resolve()
    root = (repo / args.root).resolve()
    tests_dir = (root / args.tests).resolve()
    changed = []
    for item in args.changed:
        path = (repo / item).resolve()
        if path == root or root in path.parents:
            changed.append(path)
    if not changed:
        print("NONE")
        return 0

    for path in changed:
        if path.suffix != ".py" or path.name in {"conftest.py", "__init__.py"}:
            print("ALL")
            return 0

    search = [root, tests_dir, root / "scripts", root.parent]
    tests = sorted(tests_dir.glob("test_*.py"))
    graph: dict[Path, set[Path]] = {}

    def deps(path: Path) -> set[Path]:
        if path in graph:
            return graph[path]
        graph[path] = set()
        for name, level in imports_of(path):
            target = resolve(name, level, path, search)
            if target and (target == root or root in target.parents):
                graph[path].add(target)
        return graph[path]

    def reach(start: Path) -> set[Path]:
        seen: set[Path] = set()
        todo = [start]
        while todo:
            current = todo.pop()
            for nxt in deps(current):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen

    selected: set[Path] = set()
    for path in changed:
        if path.parent == tests_dir and path.name.startswith("test_"):
            if path.is_file():
                selected.add(path)
            continue
        hits = set()
        for test in tests:
            named = not path.stem.startswith("__") and path.stem in test.read_text(encoding="utf-8", errors="replace")
            if named or path in reach(test.resolve()):
                hits.add(test.resolve())
        if not hits:
            # A module no test reaches: we cannot tell what covers it.
            print("ALL")
            return 0
        selected |= hits

    for test in sorted(selected):
        print(test.relative_to(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
