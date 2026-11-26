# AI agent plugins — TODO

Plan: [PLAN](PLAN-ai-agent-plugins.md). Tick an item only with its proof (test
name, PR or command output).

## Phase 0 — spikes

- [ ] AIP-00a Run `claude plugin install` from a process started by a Claude Code session; record the result
- [ ] AIP-00b Record how an unset optional `userConfig` value reaches `.mcp.json`
- [ ] AIP-00c Find a launcher command that works on macOS, Linux and Windows
- [ ] AIP-00d Prove a temporary `CLAUDE_CONFIG_DIR` leaves the real configuration untouched
- [ ] AIP-00e Decide the confirmation gate for `plugin_apply` (needs the maintainer)
- [ ] AIP-00f Decide merge order with #317 and #306; pick one server name

## Phase 1 — plugin and marketplace

- [ ] AIP-01 `.claude-plugin/marketplace.json` and `plugins/claude/os-lab/.claude-plugin/plugin.json` (`repo_path`, `console_port` options)
- [ ] AIP-02 `launcher.py` and `.mcp.json`; setup-only mode when no checkout is found
- [ ] AIP-03 `scripts/claude-plugin.py build [--check]`: generate lab skills, fix their names for `/os-lab:<lab>`
- [ ] AIP-04 Plugin README and license; point `plugins/mcp/claude-code/` at the plugin
- [ ] AIP-05 Tests: launcher resolution order, skill drift, no `bin/`, no escaping paths
- [ ] AIP-06 Proof: `claude plugin validate --strict` and an isolated local install

## Phase 2 — requirements and checks

- [ ] AIP-10 `console/claude_requirements.json`; confirm every limit against its doc page
- [ ] AIP-11 `console/claude_plugin.py` standard-library checks, version-aware
- [ ] AIP-12 `console/mcp_plugin.py`: `plugin_requirements`, `plugin_doctor`, `plugin_status`, `plugin_check`
- [ ] AIP-13 Detect duplicate hand-made entries (`os-lab`, `os-lab-macos`, `os-lab-windows`)
- [ ] AIP-14 Resource `oslab://plugin/requirements`; refuse `plugin_*` in `macos_task`
- [ ] AIP-15 Register tools in `mcp_verification.json`
- [ ] AIP-16 Tests: passing and failing fixture per rule; no CLI; old CLI; malformed CLI output

## Phase 3 — plan, apply, verify

- [ ] AIP-20 `plugin_plan` with fixed command tables and a one-use expiring token (reuse #317)
- [ ] AIP-21 `plugin_apply`: confirm, token, state recheck, timeout, audit log
- [ ] AIP-22 `plugin_verify`: handshake and tool-list comparison
- [ ] AIP-23 `scripts/claude-plugin.py check | doctor | install | verify`
- [ ] AIP-24 `/os-lab:setup` and `/os-lab:doctor` skills; `claude_plugin_setup_flow` prompt
- [ ] AIP-25 Tests: fake CLI for success, refusal, partial failure, stale and reused token
- [ ] AIP-26 Proof: one real install, configure, verify and uninstall

## Phase 4 — automatic check and surfaces

- [ ] AIP-30 SessionStart hook: read-only, short timeout, silent when healthy, exit 0
- [ ] AIP-31 Server `instructions` under 4,096 characters
- [ ] AIP-32 Result-size hints for tools that can pass 50,000 characters
- [ ] AIP-33 Plugin status widget
- [ ] AIP-34 `/mcp/` page and `mcp-guides.ts`, all seven locales
- [ ] AIP-35 `lat.md` MCP sections, `lat check`, `npm run check`, `npm run test:i18n`, e2e

## Phase 5 — Claude Desktop

- [ ] AIP-40 `.mcpb` manifest and build step
- [ ] AIP-41 Catalog rules and `plugin_check` support for the bundle
- [ ] AIP-42 Proof: manual install on macOS
