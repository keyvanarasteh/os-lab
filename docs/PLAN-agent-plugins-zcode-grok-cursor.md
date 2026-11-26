# Agent plugins: Zcode, Grok and Cursor (ON-HOLD)

Status: **ON-HOLD** plan stubs. Do not implement until Claude (#385/#388/#390) and Codex (#386) patterns are stable on master and this work is taken off hold.

Companion checklist: [TODO-agent-plugins-zcode-grok-cursor.md](TODO-agent-plugins-zcode-grok-cursor.md).

## Shared goal

Ship an installable os-lab plugin (or the closest host-native equivalent) for each of **Zcode**, **Grok** and **Cursor**, following the same spirit as the Claude and Codex work:

1. **Describe** host-specific requirements with sources and used / n/a.
2. **Check** the package, host and installation automatically.
3. **Install / set up** with a preview first and an explicit human gate (never invent unsupported CLI verbs).
4. **Verify** that the installed connection starts and lists the expected tools.
5. **Surface** status on `/mcp/` (console API + cards), register tools in `console/mcp_verification.json`, and add focused CI when a real client round trip is possible.

Reuse shared MCP helpers and skill generation. Keep **separate** management tool names (`zcode_plugin_*`, `grok_plugin_*`, `cursor_plugin_*`) so they never collide with Claude `plugin_*` or Codex `codex_plugin_*`.

## Claude / Codex patterns to copy

| Pattern | Claude | Codex | Apply here |
| --- | --- | --- | --- |
| Package + marketplace / host install | `plugins/claude/os-lab/` | `plugins/codex/os-lab/` + `.agents/plugins/` | Per-host package under `plugins/<host>/os-lab/` when the host has a plugin format; otherwise keep the scaffold and document the gap |
| Launcher + checkout resolution | `repo_path` / `OSLAB_ROOT` / walk-up | `OSLAB_ROOT` / marketplace walk-up | Same fail-closed rules |
| Requirement catalog JSON + checks | `claude_requirements.json` | `codex_requirements.json` | Host-specific catalog; no Claude-only numeric limits |
| MCP tools + resource + prompt | `plugin_*` | `codex_plugin_*` | Prefixed tools; refuse inside `macos_task` |
| Terminal-only removals / weak apply gates | uninstall terminal-only | all installs terminal-only | Match proven host approval; `confirm: true` alone is not the human gate |
| Updates check | Code + Desktop + optional GitHub | installed vs checkout + optional GitHub | Only where the host exposes version/state |
| `/mcp/` cards + `/api/<host>-plugin` | yes | yes | Same UX readiness rules |
| CI round trip | three-OS Claude CLI | three-OS package + optional Codex CLI | Skip live install when the runner has no client |
| Widgets / hooks | status widget + SessionStart | status widget; hooks n/a until proven | Optional until a live host proves support |

Deliberate exclusions until proven: Claude Desktop `.mcpb`, Claude `${user_config.*}` placeholders, inventing update/enable/disable verbs the host does not have.

## Section A — Zcode

**Today:** `plugins/mcp/zcode/mcp.json` stdio scaffold with `<REPO>` and skill pointers.

**Deliverable:** an installable or documented Zcode-native plugin path that connects to `console/mcp_server.py`, packages the ten lab skills (+ setup/doctor), and exposes `zcode_plugin_*` management tools.

**Stage 0 (before code):** record Zcode version and OS; confirm how local MCP servers and skills are registered; whether a marketplace/plugin format exists; what files a copied install receives; Windows interpreter strategy; whether hooks/widgets/resources/prompts work for local servers.

**Package:** prefer `plugins/zcode/os-lab/` if Zcode has a portable plugin schema; otherwise extend the scaffold and keep a helper `scripts/zcode-plugin.py` that only runs proven commands.

**Safety:** fixed argument lists, preview tokens, secret-free status, duplicate MCP detection for hand-edited configs.

**Proof:** fake-CLI or fake-config fixtures; one isolated real install when a client is available; register proofs in `mcp_verification.json`.

## Section B — Grok

**Today:** no `plugins/mcp/grok/` scaffold on master.

**Deliverable:** first-class Grok (xAI) client integration for os-lab MCP: document the supported transport, add a scaffold under `plugins/mcp/grok/`, and if Grok gains a plugin/package format, add `plugins/grok/os-lab/` with the same lifecycle pattern.

**Stage 0:** confirm which Grok surface is in scope (Grok app, xAI API tools, browser, or another host); whether stdio MCP is supported or only remote/HTTP; auth and local-filesystem constraints; whether skills or “custom instructions” are the right packaging for lab workflows.

**Until Stage 0 is done:** keep this section plan-only. Do not invent a Grok plugin schema. Ship a README scaffold and requirement catalog stubs marked `manual` / `n/a` where unknown.

**Management names:** `grok_plugin_*` once a real install path exists; until then, docs-only.

## Section C — Cursor

**Today:** `plugins/mcp/cursor/mcp.json` fragment (`.cursor/mcp.json` shape).

**Deliverable:** Cursor-native setup that matches Claude/Codex UX as far as Cursor allows: project and/or user MCP config, packaged skills if Cursor Agent Skills apply, `cursor_plugin_*` doctor/status/check/plan/verify, and `/mcp/` cards.

**Stage 0:** confirm current Cursor MCP config locations (project `.cursor/mcp.json` vs user); whether Cursor supports installable plugins/marketplaces beyond MCP config; how Agent Skills interact with repo skills; whether a deep link or command can open MCP settings; Windows/macOS/Linux path rules.

**Package:** start from the existing scaffold. Add `plugins/cursor/os-lab/` only if Cursor gains a real plugin package format; otherwise the “plugin” is the managed MCP config + skills sync checked by `scripts/cursor-plugin.py`.

**Safety:** never write Cursor settings that embed secrets; preview every config mutation; refuse agent-initiated destructive edits without a terminal or UI confirm path proven in Stage 0.

## Shared delivery sequence (when un-held)

| Stage | Gate |
| --- | --- |
| 0 | Host capability notes in the TODO for that host |
| 1 | Package or scaffold + launcher/doctor |
| 2 | Skills sync + requirement catalog |
| 3 | Management tools + verify/apply/verify with host-appropriate gates |
| 4 | `/mcp/` API + cards + i18n; optional widget |
| 5 | CI job; lat.md node; README; verification registry |

Keep each host’s implementation PR separate when work starts (same as Claude vs Codex). This ON-HOLD PR only lands the plans and TODO.

## References

- Claude: #385, #388, #390 · `lat.md/ai-plugins.md` · `docs/PLAN-ai-agent-plugins.md`
- Codex: #386 · `lat.md/codex-plugin.md` · `docs/PLAN-codex-plugin.md` (on the Codex branch until merged)
- Scaffolds: `plugins/mcp/README.md`
- UX: `docs/UX_READINESS.md`, `lat.md/ux-readiness.md`
