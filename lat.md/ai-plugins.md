# Claude plugin

os-lab installs into Claude Code as one plugin: the MCP server, a skill per lab, setup and doctor skills, and a read-only session check.

## Package

The plugin stays thin and runs the server from a checkout, because Claude Code copies only the plugin folder into its cache.

[[.claude-plugin/marketplace.json]] names the marketplace `os-lab`; the plugin lives in
`plugins/claude/os-lab/`. [[plugins/claude/os-lab/launcher.py#find_checkout]] takes the
`repo_path` option, then `OSLAB_ROOT`, then the folders above itself that are the os-lab
marketplace. A configured but wrong path is never replaced. Without a checkout the launcher
serves only `plugin_doctor` and `plugin_status`, which say how to set the path.

The `python_command` option picks the interpreter, since Windows often lacks `python3`. Lab
skills are generated from `console/mcp_skills/` by `scripts/claude-plugin.py build`, and a
check fails when they differ.

## Requirement checks

[[console/claude_requirements.json]] lists each plugin rule with its source and severity, and [[console/claude_plugin.py#check]] runs them against the checkout.

Rules without an automatic check report `manual` or `n/a`. A rule that needs a newer Claude
Code reports `skipped`. Add a rule with its check function and a failing case in
[[android-lab/lab/tests/test_mcp_plugin.py]].

## Changes

Install, update, configure, enable and disable are previewed, then run with a one-use token and `confirm: true`; removals run only from a terminal.

[[console/claude_plugin.py#plan]] builds fixed `claude` argument lists, so a caller picks only
an action and a scope. [[console/claude_plugin.py#apply]] refuses a missing confirmation, a
used or expired token and a state that changed since the preview, stops at the first failed
step and writes `artifacts/claude-plugin-audit-<date>.jsonl`. A marketplace named `os-lab` that
points elsewhere is a conflict, and verification never starts its code. Hand-made MCP entries
that duplicate the plugin are reported without their environment values.

`confirm: true` comes from the model, so the client's permission prompt is the human gate for
the tools; uninstall and duplicate removal need an interactive terminal.

## Claude Desktop and updates

In Claude Desktop the plugin is the `.mcpb` extension: [[console/claude_desktop.py#build_plan]] builds it and opens it, and the user confirms in the app.

[[console/claude_desktop.py#extension_info]] reads the installed extension's version and finds
duplicate entries in `claude_desktop_config.json`. [[console/claude_desktop.py#updates]]
compares the checkout with the Claude Code installs and the extension; asked for `online`, it
also reads the plugin version published on master. Neither Claude app is ever installed or
updated, and the plugin itself changes only through a previewed plan. Opening the bundle is
automatic on macOS only; elsewhere the plan gives the manual step.

The session start check stays silent when healthy. It reports a missing checkout and an older
Desktop extension, and with the `update_check` option (off by default) a newer published
version, asked for at most once a day.

## MCP page cards

The `/mcp/` page checks, installs and updates the plugin through the local console, with the same preview and token as the tools.

[[console/claude_plugin_api.py#handle]] serves `/api/claude-plugin`; every POST needs the
`X-OSLab` header, and removals are refused with the terminal command. The cards in
[[dashboard/src/views/mcp-plugin-cards.tsx]] show Claude Code, Claude Desktop and update
state, open the planned commands in a dialog and apply only after Confirm. Without the
console they show the terminal command instead.

## Server surface

[[console/mcp_plugin.py]] adds the `plugin_*` tools, the resource `oslab://plugin/requirements` and a status widget; they are refused inside `macos_task`.

The server also sends `instructions` on initialize and raises the result-size limit of its
largest read tools. `scripts/claude-plugin.py bundle` builds a Claude Desktop `.mcpb` whose
checkout path is required.
