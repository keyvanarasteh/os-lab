---
name: setup
description: Install and verify the os-lab Cursor plugin connection to the guarded MCP server.
---
# Setup

1. Call `cursor_plugin_doctor` and `cursor_plugin_status`.
2. Call `cursor_plugin_plan` with action `install`; show the commands.
3. Run `python3 scripts/cursor-plugin.py install` in an interactive terminal.
4. Call `cursor_plugin_verify` and report missing tools.
\n