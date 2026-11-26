#!/usr/bin/env python3
"""SessionStart check: one line when the plugin cannot find a checkout, otherwise nothing.

Reads files only: no network, no subprocess, no writes. Always exits 0.
"""
from __future__ import annotations

import os
import sys


def message(env=None):
    sys.dont_write_bytecode = True
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    import launcher

    env = dict(os.environ if env is None else env)
    env.setdefault("OSLAB_PLUGIN_REPO", env.get("CLAUDE_PLUGIN_OPTION_REPO_PATH", ""))
    root, _source, problem = launcher.find_checkout(env)
    if root:
        return ""
    return "os-lab plugin is not set up: {0} Run /os-lab:doctor.".format(problem)


if __name__ == "__main__":
    try:
        text = message()
        if text:
            print(text)
    except Exception:  # a broken check must never disturb a session
        pass
    sys.exit(0)
