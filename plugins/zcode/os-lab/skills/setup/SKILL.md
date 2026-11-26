---
name: setup
description: Install and verify the os-lab ZCode plugin connection to the guarded MCP server.
---
# Setup

1. Call `zcode_plugin_doctor` and `zcode_plugin_status`.
2. Call `zcode_plugin_plan` with action `install`; show the commands.
3. Run `python3 scripts/zcode-plugin.py install` in an interactive terminal.
4. Call `zcode_plugin_verify` and report missing tools.
\n