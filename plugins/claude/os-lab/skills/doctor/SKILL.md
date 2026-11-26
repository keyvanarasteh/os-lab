---
name: doctor
description: Check the os-lab Claude plugin and this computer, and say how to fix each problem. Use when os-lab tools are missing or failing.
---

# os-lab plugin doctor

Read-only. Change nothing.

1. Call `plugin_doctor`. If it reports `ready: false` with a `fix`, show that and stop.
2. Call `plugin_status` for the marketplace, the installed plugin and duplicate MCP entries.
3. Call `plugin_check` and list only `fail` and `warn` results, each with its fix.
4. Call `plugin_verify` when the plugin is installed.

Report what is healthy in one line, then the problems in order of severity.
