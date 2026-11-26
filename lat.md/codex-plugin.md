# Codex plugin

The local Codex plugin packages os-lab skills and connects Codex to the guarded MCP server in a verified checkout.

## Package and launch

[[plugins/codex/os-lab/plugin.json]] is the portable manifest and [[plugins/codex/os-lab/mcp.json]] declares one stdio server.

[[.agents/plugins/marketplace.json]] exposes it as `os-lab@os-lab-local`. A CLI client adds this repository as a marketplace and installs the entry; no checkout action changes the user's Codex configuration.

[[plugins/codex/os-lab/launcher.py#find_checkout]] uses `OSLAB_ROOT` when supplied. An invalid explicit path fails closed. Without one, it walks up only to this repository's verified local marketplace. When no checkout is found, it answers MCP with read-only doctor and status tools explaining the fix.

The plugin has setup and doctor skills plus ten lab skills generated from `console/mcp_skills/` by [[scripts/codex-plugin.py]]; `build --check` reports drift. The package contains its README and Apache license. An installed copy from a cache needs `OSLAB_ROOT` because it cannot infer the source checkout.

## Requirement checks

[[console/codex_requirements.json]] lists each Codex rule with its source and severity.

[[console/codex_plugin.py#check]] runs them. Claude-only formats (`.mcpb`, `${user_config.*}`, lifecycle hooks) are recorded as `n/a` until a live Codex client proves support.

## Management and safety

[[console/codex_plugin.py]] checks package requirements and reads install state without returning config secrets.

[[console/mcp_codex_plugin.py]] exposes the `codex_plugin_*` tools, including updates. Install, update and uninstall plans name exact Codex CLI commands; MCP and console `apply` refuse writes. The terminal helper shows the plan, asks interactively, rechecks state and runs only fixed arguments. Plans, outcomes and refusals are logged without tokens or settings values. Manual `plugins/mcp/codex/config.toml` duplicates are reported with a migration note.

[[console/codex_plugin.py#updates]] compares the checkout with the installed plugin; `online: true` also reads the version published on master. There is no Codex counterpart to Claude Desktop `.mcpb`.

## MCP page cards

The `/mcp/` page shows Codex status through [[console/codex_plugin_api.py#handle]] (`/api/codex-plugin`).

Cards preview commands and point at the terminal helper; they never apply from the browser.

## Server surface

The tools are refused inside `macos_task`. They do not add an arm tool or bypass lab gates.

The server advertises a Codex requirement resource, guided setup prompt, status widget and initialize instructions. [[console/mcp_verification.json]] holds the proof slots; [[android-lab/lab/tests/test_codex_plugin.py]] covers the package, fallback protocol, isolated CLI install, API refusal and MCP surface. CI job `codex-plugin` runs the package tests on three OSes.

## Limits

The current proof uses Codex CLI 0.167.0 on macOS with a temporary `CODEX_HOME`.

Desktop plugin browser behavior and a copied desktop cache still need direct proof on other platforms. This local stdio plugin is separate from public-directory submission.
