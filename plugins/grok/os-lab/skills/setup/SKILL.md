---
name: setup
description: Install and verify the os-lab Grok Build plugin connection to the guarded MCP server.
---
# Setup

1. Call `grok_plugin_doctor` and `grok_plugin_status`.
2. Call `grok_plugin_plan` with action `install`; show the commands.
3. Run `python3 scripts/grok-plugin.py install` in an interactive terminal.
4. Call `grok_plugin_verify` and report missing tools.
\n