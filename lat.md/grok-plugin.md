# Grok Build plugin

The local Grok Build plugin packages os-lab skills and connects Grok to the guarded MCP server through a project MCP config, with a repo-local marketplace.

## Package and launch

[[plugins/grok/os-lab/plugin.json]] and [[plugins/grok/os-lab/.mcp.json]] declare the package and one stdio server. [[.grok-plugin/marketplace.json]] exposes it as a local `os-lab` entry (qLar-style).

[[plugins/grok/os-lab/launcher.py#find_checkout]] uses `OSLAB_ROOT` when supplied. An invalid explicit path fails closed. Without one, it walks up to a checkout that contains `labctl` and `console/mcp_server.py`.

The plugin has setup and doctor skills plus ten lab skills generated from `console/mcp_skills/` by [[scripts/grok-plugin.py]]. The scaffold [[plugins/mcp/grok/mcp.json]] remains for docs.

## Requirement checks

[[console/grok_requirements.json]] lists each Grok rule with its source and severity. [[console/host_plugin.py#check]] runs them for host `grok`.

## Management and safety

[[console/host_plugin.py]] installs by writing `.grok/mcp.json`. [[console/mcp_host_plugins.py]] exposes `grok_plugin_*`. MCP and console `apply` refuse writes; [[scripts/grok-plugin.py]] applies in an interactive terminal. [[console/host_plugin_api.py#handle]] serves `/api/grok-plugin`.

## Limits

Grok CLI is optional. This is a local stdio package for Grok Build-style hosts; remote HTTP-only Grok surfaces are out of scope until proven.
