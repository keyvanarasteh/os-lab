# Codex plugin

The local Codex plugin packages os-lab skills and connects Codex to the guarded MCP server in a verified checkout.

## Package and launch

[[plugins/codex/os-lab/plugin.json]] is the portable manifest and [[plugins/codex/os-lab/mcp.json]] declares one stdio server. [[.agents/plugins/marketplace.json]] exposes it as `os-lab@os-lab-local`. A CLI client adds this repository as a marketplace and installs the entry; no checkout action changes the user's Codex configuration.

[[plugins/codex/os-lab/launcher.py#find_checkout]] uses `OSLAB_ROOT` when supplied. An invalid explicit path fails closed. Without one, it walks up only to this repository's verified local marketplace. When no checkout is found, it answers MCP with read-only doctor and status tools explaining the fix.

The plugin has setup and doctor skills plus ten lab skills generated from `console/mcp_skills/` by [[scripts/codex-plugin.py]]; `build --check` reports drift. The package contains its README and Apache license. An installed copy from a cache needs `OSLAB_ROOT` because it cannot infer the source checkout.

## Management and safety

[[console/codex_plugin.py]] checks package requirements and reads install state without returning config secrets. [[console/mcp_codex_plugin.py]] exposes seven management tools.

Install plans name exact Codex CLI commands; MCP `apply` refuses installation. The terminal helper shows the plan, asks interactively, rechecks state and runs only fixed arguments. Plans, outcomes and refusals are logged without tokens or settings values. Other lifecycle actions remain unsupported until their Codex CLI behavior and approval path are proven.

The plugin tools are refused inside `macos_task`. They do not add an arm tool or bypass the existing lab scope and confirmation gates. The server also advertises a Codex requirement resource, guided setup prompt and initialize instructions. [[console/mcp_verification.json]] holds the proof slots; [[android-lab/lab/tests/test_codex_plugin.py]] tests the package, fallback protocol, isolated CLI install and MCP surface.

## Limits

The current proof uses Codex CLI 0.167.0 on macOS with a temporary `CODEX_HOME`.

Desktop plugin browser behavior, a copied desktop cache, Windows/Linux launch commands, hooks and UI rendering still need direct proof. This local stdio plugin is separate from public-directory submission.
