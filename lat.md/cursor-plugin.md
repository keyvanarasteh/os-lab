# Cursor plugin

The local Cursor plugin packages os-lab skills and connects Cursor to the guarded MCP server through a project MCP config.

## Package and launch

[[plugins/cursor/os-lab/.cursor-plugin/plugin.json]] is the Cursor-native manifest; [[plugins/cursor/os-lab/plugin.json]] and [[plugins/cursor/os-lab/mcp.json]] mirror the portable layout.

[[plugins/cursor/os-lab/launcher.py#find_checkout]] uses `OSLAB_ROOT` when supplied. An invalid explicit path fails closed. Without one, it walks up to a checkout that contains `labctl` and `console/mcp_server.py`. When no checkout is found, it answers MCP with read-only doctor and status tools explaining the fix.

The plugin has setup and doctor skills plus ten lab skills generated from `console/mcp_skills/` by [[scripts/cursor-plugin.py]]. The legacy fragment [[plugins/mcp/cursor/mcp.json]] remains for docs.

## Requirement checks

[[console/cursor_requirements.json]] lists each Cursor rule with its source and severity. [[console/host_plugin.py#check]] runs them for host `cursor`.

## Management and safety

[[console/host_plugin.py]] checks package requirements and reads install state from `.cursor/mcp.json` without returning secrets. Install writes that project config to point at this checkout's launcher.

[[console/mcp_host_plugins.py]] exposes the `cursor_plugin_*` tools. Install, update and uninstall plans are terminal-only; MCP and console `apply` refuse writes. [[console/host_plugin_api.py#handle]] serves `/api/cursor-plugin` for the `/mcp/` cards.

## Limits

Cursor CLI is optional. Live desktop plugin-browser behavior still needs direct proof on each OS.
