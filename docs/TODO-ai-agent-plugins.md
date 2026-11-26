# AI agent plugins — TODO

Plan: [PLAN](PLAN-ai-agent-plugins.md). Tick an item only with its proof (test
name, PR or command output).

## Phase 0 — spikes

- [x] AIP-00a Run `claude plugin install` from a process started by a Claude Code session; record the result — proof: real CLI, Phase 0 answer 1
- [x] AIP-00b Record how an unset optional `userConfig` value reaches `.mcp.json` — proof: answer 2
- [ ] AIP-00c Find a launcher command that works on macOS, Linux and Windows — macOS proven (answer 3); Linux and Windows untested
- [x] AIP-00d Prove a temporary `CLAUDE_CONFIG_DIR` leaves the real configuration untouched — proof: answer 4
- [x] AIP-00e Decide the confirmation gate for `plugin_apply` (needs the maintainer) — proof: answer 5
- [x] AIP-00f Decide merge order with #317 and #306; pick one server name — proof: plan, merge order

## Phase 1 — plugin and marketplace

- [x] AIP-01 `.claude-plugin/marketplace.json` and `plugins/claude/os-lab/.claude-plugin/plugin.json` (`repo_path`, `console_port` options) — proof: `claude plugin validate --strict`
- [x] AIP-02 `launcher.py` and `.mcp.json`; setup-only mode when no checkout is found — proof: `test_mcp_plugin.py`
- [x] AIP-03 `scripts/claude-plugin.py build [--check]`: generate lab skills, fix their names for `/os-lab:<lab>` — proof: `test_mcp_plugin.py`
- [x] AIP-04 Plugin README and license; point `plugins/mcp/claude-code/` at the plugin — proof: README and catalog check
- [x] AIP-05 Tests: launcher resolution order, skill drift, no `bin/`, no escaping paths — proof: `test_mcp_plugin.py`
- [x] AIP-06 Proof: `claude plugin validate --strict` and an isolated local install — proof: validate, install and `mcp list` Connected

## Phase 2 — requirements and checks

- [ ] AIP-10 `console/claude_requirements.json`; confirm every limit against its doc page — catalog done; some limits come from summarized pages
- [x] AIP-11 `console/claude_plugin.py` standard-library checks, version-aware — proof: `test_mcp_plugin.py`
- [x] AIP-12 `console/mcp_plugin.py`: `plugin_requirements`, `plugin_doctor`, `plugin_status`, `plugin_check` — proof: `test_mcp_plugin.py`
- [x] AIP-13 Detect duplicate hand-made entries (`os-lab`, `os-lab-macos`, `os-lab-windows`) — proof: `test_mcp_plugin.py`
- [x] AIP-14 Resource `oslab://plugin/requirements`; refuse `plugin_*` in `macos_task` — proof: `test_mcp_plugin.py`
- [x] AIP-15 Register tools in `mcp_verification.json` — proof: `test_mcp_verification.py`
- [x] AIP-16 Tests: passing and failing fixture per rule; no CLI; old CLI; malformed CLI output — proof: `test_mcp_plugin.py`

## Phase 3 — plan, apply, verify

- [x] AIP-20 `plugin_plan` with fixed command tables and a one-use expiring token (reuse #317) — proof: own implementation, not #317; `test_mcp_plugin.py`
- [x] AIP-21 `plugin_apply`: confirm, token, state recheck, timeout, audit log — proof: `test_mcp_plugin.py`
- [x] AIP-22 `plugin_verify`: handshake and tool-list comparison — proof: real install, 148 tools, none missing
- [x] AIP-23 `scripts/claude-plugin.py check | doctor | install | verify` — proof: real CLI round trip
- [x] AIP-24 `/os-lab:setup` and `/os-lab:doctor` skills; `claude_plugin_setup_flow` prompt — proof: `test_mcp_plugin.py`
- [x] AIP-25 Tests: fake CLI for success, refusal, partial failure, stale and reused token — proof: `test_mcp_plugin.py`
- [x] AIP-26 Proof: one real install, configure, verify and uninstall — proof: real CLI: install, configure, disable, enable, update, verify, uninstall

## Phase 4 — automatic check and surfaces

- [x] AIP-30 SessionStart hook: read-only, short timeout, silent when healthy, exit 0 — proof: `test_mcp_plugin.py`
- [x] AIP-31 Server `instructions` under 4,096 characters — proof: `test_mcp_plugin.py`
- [x] AIP-32 Result-size hints for tools that can pass 50,000 characters — proof: `test_mcp_plugin.py`
- [x] AIP-33 Plugin status widget — proof: `test_mcp_ui_hosts.py`
- [x] AIP-34 `/mcp/` page and `mcp-guides.ts`, all seven locales — proof: #385, `test:i18n`, CI browser tests
- [x] AIP-35 `lat.md` MCP sections, `lat check`, `npm run check`, `npm run test:i18n`, e2e — proof: #385 CI `check` and browser jobs

## Phase 5 — Claude Desktop

- [x] AIP-40 `.mcpb` manifest and build step — proof: `test_mcp_plugin.py`
- [x] AIP-41 Catalog rules and `plugin_check` support for the bundle — proof: `test_mcp_plugin.py`
- [ ] AIP-42 Proof: manual install on macOS

## Phase 6 — plugin in Claude Desktop and update checks

- [x] AIP-50 Detect Claude Desktop, the installed os-lab extension and duplicate entries — proof: `test_mcp_plugin.py`
- [x] AIP-51 `extension-install` plan: build the bundle and open it in Claude Desktop — proof: `test_mcp_plugin.py` (command faked)
- [x] AIP-52 `plugin_updates` for Claude Code, Claude Desktop and the published version — proof: `test_mcp_plugin.py`
- [x] AIP-53 Session check: older extension, and an opt-in daily published-version check — proof: `test_mcp_plugin.py`
- [ ] AIP-54 Proof: install and update the extension in a real Claude Desktop

## Phase 7 — plugin cards on the MCP page

- [ ] AIP-60 Console API: status and updates, preview, apply
- [ ] AIP-61 MCP page cards: check, install and update for Claude Code and Claude Desktop
- [ ] AIP-62 Browser tests and all seven locales
- [ ] AIP-63 CI: plugin checks and an isolated CLI round trip on Linux, macOS and Windows

## Follow-ups

- [ ] Share one plan-and-token implementation with #317 once it lands
- [ ] Try the plugin and the session check on Windows and Linux
- [ ] Watch the SessionStart check fire in a live session (only run directly so far)
