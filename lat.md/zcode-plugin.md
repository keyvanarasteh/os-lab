# ZCode plugin

The local ZCode plugin packages os-lab skills and connects ZCode to the guarded MCP server through a project MCP config.

## Package and launch

[[plugins/zcode/os-lab/plugin.json]] and [[plugins/zcode/os-lab/.mcp.json]] declare the package and one stdio server.

[[plugins/zcode/os-lab/launcher.py#find_checkout]] uses `OSLAB_ROOT` when supplied. An invalid explicit path fails closed. Without one, it walks up to a checkout that contains `labctl` and `console/mcp_server.py`.

The plugin has setup and doctor skills plus ten lab skills generated from `console/mcp_skills/` by [[scripts/zcode-plugin.py]]. The legacy fragment [[plugins/mcp/zcode/mcp.json]] keeps the `servers` shape for docs.

## Requirement checks

[[console/zcode_requirements.json]] lists each ZCode rule with its source and severity. [[console/host_plugin.py#check]] runs them for host `zcode`.

## Management and safety

[[console/host_plugin.py]] installs by writing `.zcode/mcp.json` with a `servers.os-lab` entry. [[console/mcp_host_plugins.py]] exposes `zcode_plugin_*`. MCP and console `apply` refuse writes; [[scripts/zcode-plugin.py]] applies in an interactive terminal. [[console/host_plugin_api.py#handle]] serves `/api/zcode-plugin`.

## Limits

ZCode CLI is optional. Hooks and host-native marketplace install remain n/a until a live client proves support.
