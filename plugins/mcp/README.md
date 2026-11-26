# os-lab MCP host plugins

Stdio server: `python3 console/mcp_server.py` (or `make -C ios-lab mac-mcp`).

Each subdirectory is a drop-in config scaffold. Replace `<REPO>` with the absolute
checkout path. Skills live in `console/mcp_skills/`; prompts and tools are advertised
by the server (`prompts/list`, `tools/list`, `resources/list`).

| Host | Folder | Notes |
| --- | --- | --- |
| Claude Desktop | `claude-desktop/` | `claude_desktop_config.json` fragment |
| Claude Code | `claude-code/` | `.mcp.json` + skill pointers |
| Codex | `codex/` | `config.toml` fragment |
| Cursor | `cursor/` | `.cursor/mcp.json` fragment |
| OpenCode | `opencode/` | `opencode.json` MCP block |
| Zcode | `zcode/` | stdio MCP entry |
| Antigravity | `antigravity/` | generic MCP connector JSON |

Verification proofs: edit `console/mcp_verification.json` and open a PR.
