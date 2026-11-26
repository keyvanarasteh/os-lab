# TODO: Zcode, Grok and Cursor plugins (ON-HOLD)

Companion to [PLAN-agent-plugins-zcode-grok-cursor.md](PLAN-agent-plugins-zcode-grok-cursor.md).
Parked behind Claude (#385/#388/#390) and Codex (#386). Uncheck nothing until Stage 0 for that host is written up.

## Shared

- [ ] Confirm Claude and Codex patterns on master before starting any host implementation.
- [ ] Reserve tool-name prefixes `zcode_plugin_*`, `grok_plugin_*`, `cursor_plugin_*`.
- [ ] Keep Cleanup Lab and unrelated MCP coverage work in separate PRs.

## Zcode

- [ ] Stage 0: record client version, MCP registration, plugin/marketplace support, copied-install paths, hooks/UI.
- [ ] Package or extend `plugins/mcp/zcode/`; launcher + checkout discovery.
- [ ] Requirement catalog + `zcode_plugin_*` tools; terminal-safe apply.
- [ ] `/mcp/` cards + API; CI; lat.md; verification proofs.

## Grok

- [ ] Stage 0: define which Grok surface is in scope and whether stdio MCP exists.
- [ ] Add `plugins/mcp/grok/` scaffold + README once transport is known.
- [ ] Only then: package, catalog, `grok_plugin_*`, cards, CI.

## Cursor

- [ ] Stage 0: project vs user MCP config, skills support, settings mutation gates.
- [ ] Helper to preview/apply `.cursor/mcp.json` (or proven Cursor plugin format).
- [ ] Requirement catalog + `cursor_plugin_*`; `/mcp/` cards; CI; lat.md.
