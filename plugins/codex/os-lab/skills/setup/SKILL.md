---
name: os-lab-setup
description: Set up the local os-lab Codex plugin and diagnose a missing checkout or MCP connection.
---

# Set up OS Lab

Check whether `OSLAB_ROOT` points to the intended os-lab checkout and whether the plugin's MCP server lists tools. If the server exposes only `codex_plugin_doctor` and `codex_plugin_status`, show their reported fix. Explain the exact marketplace and plugin installation steps from this package's README. Ask for approval before changing Codex plugin state. After installation, verify `tools/list` and report any missing capabilities. Do not arm macOS control or bypass lab scope checks.
