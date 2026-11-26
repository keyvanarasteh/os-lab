# TODO: Zcode, Grok and Cursor plugins

Companion to [PLAN-agent-plugins-zcode-grok-cursor.md](PLAN-agent-plugins-zcode-grok-cursor.md). OL-15 / PR #392.

## Shared

- [x] Confirm Claude and Codex patterns on master before starting any host implementation.
- [x] Reserve tool-name prefixes `zcode_plugin_*`, `grok_plugin_*`, `cursor_plugin_*`.
- [x] Keep Cleanup Lab and unrelated MCP coverage work in separate PRs.

## Zcode

- [x] Stage 0: file-based MCP via project `.zcode/mcp.json` (`servers` shape); plugin package under `plugins/zcode/os-lab/`; CLI optional.
- [x] Package + launcher + checkout discovery.
- [x] Requirement catalog + `zcode_plugin_*` tools; terminal-safe apply.
- [x] `/mcp/` cards + API; CI; lat.md; verification proofs.

## Grok

- [x] Stage 0: Grok Build local stdio package + `.grok-plugin` marketplace; project `.grok/mcp.json`.
- [x] Add `plugins/mcp/grok/` scaffold + README.
- [x] Package, catalog, `grok_plugin_*`, cards, CI.

## Cursor

- [x] Stage 0: project `.cursor/mcp.json`; `.cursor-plugin/plugin.json` package format (qLar-aligned).
- [x] Helper to preview/apply `.cursor/mcp.json`.
- [x] Requirement catalog + `cursor_plugin_*`; `/mcp/` cards; CI; lat.md.

## Follow-ups (optional)

- [ ] Live desktop install proofs when each host CLI is available on CI runners.
- [ ] Host-native marketplace/plugin-browser verbs if/when documented.
