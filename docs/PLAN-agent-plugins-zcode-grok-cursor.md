# Agent plugins: Zcode, Grok and Cursor

Status: **implemented** on PR #392 (OL-15). Claude (#385/#388/#390) and Codex (#386) patterns are on master; this work ships the three remaining hosts.

Companion checklist: [TODO-agent-plugins-zcode-grok-cursor.md](TODO-agent-plugins-zcode-grok-cursor.md).

## Shared goal

Ship an installable os-lab plugin for each of **Zcode**, **Grok Build** and **Cursor**, following Claude/Codex:

1. Describe host-specific requirements with sources and used / n/a.
2. Check the package, host and installation automatically.
3. Install / set up with a preview first and a terminal-only human gate.
4. Verify that the installed connection starts and lists the expected tools.
5. Surface status on `/mcp/` (console API + cards), register tools in `console/mcp_verification.json`, and run focused CI.

Management tool names stay separate: `zcode_plugin_*`, `grok_plugin_*`, `cursor_plugin_*`.

## Implementation summary

| Host | Package | Install path | API | Helper |
| --- | --- | --- | --- | --- |
| Cursor | `plugins/cursor/os-lab/` (`.cursor-plugin/`) | `.cursor/mcp.json` | `/api/cursor-plugin` | `scripts/cursor-plugin.py` |
| ZCode | `plugins/zcode/os-lab/` | `.zcode/mcp.json` (`servers`) | `/api/zcode-plugin` | `scripts/zcode-plugin.py` |
| Grok | `plugins/grok/os-lab/` + `.grok-plugin/` | `.grok/mcp.json` | `/api/grok-plugin` | `scripts/grok-plugin.py` |

Shared engine: `console/host_plugin.py` + `console/mcp_host_plugins.py` + `console/host_plugin_api.py`. Proofs: `android-lab/lab/tests/test_host_plugins.py`. CI: `.github/workflows/host-plugins.yml`. Docs: `lat.md/{cursor,zcode,grok}-plugin.md`.

Deliberate exclusions until proven: Claude Desktop `.mcpb`, inventing host CLI verbs the client does not have, remote HTTP-only Grok surfaces.
