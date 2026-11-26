#!/usr/bin/env python3
"""SessionStart check: silent when healthy, one line per problem or available update.

Reads files only and starts no process. With the update_check option on, it also asks for the
published plugin version at most once a day and caches it in the plugin data folder. Always
exits 0.
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
    if not root:
        return "os-lab plugin is not set up: {0} Run /os-lab:doctor.".format(problem)
    console = os.path.join(root, "console")
    if not os.path.isfile(os.path.join(console, "claude_desktop.py")):
        return ""
    sys.path.insert(0, console)
    import claude_desktop

    online = env.get("CLAUDE_PLUGIN_OPTION_UPDATE_CHECK", "").lower() == "true"
    return "\n".join(claude_desktop.session_notes(root, online, env.get("CLAUDE_PLUGIN_DATA", "")))


if __name__ == "__main__":
    try:
        text = message()
        if text:
            print(text)
    except Exception:  # a broken check must never disturb a session
        pass
    sys.exit(0)
